# -*- coding: utf-8 -*-
"""Движок генерации PDF через HTML + Chromium (QWebEngineView)."""
import os
import json
import tempfile
import shutil
from PyQt6.QtCore import Qt, QEventLoop, QTimer, QUrl, QMarginsF
from PyQt6.QtGui import QPageSize, QPageLayout
from PyQt6.QtWidgets import QProgressDialog, QApplication
from PyQt6.QtWebEngineWidgets import QWebEngineView
from jinja2 import Environment

from .helpers import safe_text


def _build_conclusion_context(report_data, comment=""):
    if not report_data:
        return None
        
    items = list(report_data.values())
    first_common = list(items[0]["common"])
    signature_str = items[0].get("signature") or ""
    
    try:
        signed_fios = json.loads(signature_str) if signature_str else []
    except Exception:
        signed_fios = []
    signed_fios = [str(f).strip() for f in signed_fios if str(f).strip()]

    all_objects = set()
    for m in items:
        for d in m.get('defects', []):
            obj = d.get('defect_object', '') if isinstance(d, dict) else (d[13] if len(d) > 13 else '')
            if obj:
                all_objects.add(str(obj).strip())
    show_objects = len(all_objects) > 1

    channels = []
    total_data_rows = 0
    
    for m in items:
        plan = []
        defects = m.get('defects', [])
        if not defects:
            defects = [{'no_defect': 'Да', 'plot_num': '-', 'quality': 'уд.', 'fio': '', 'defect_object': ''}]

        seen_objs = set()
        for d in defects:
            if isinstance(d, dict):
                obj = str(d.get('defect_object', '')).strip()
            else:
                obj = str(d[13] if len(d) > 13 else '').strip()

            if show_objects and obj and obj not in seen_objs:
                plan.append({'type': 'obj_header', 'payload': obj})
                seen_objs.add(obj)
                
            if isinstance(d, dict):
                d_tuple = (d.get('plot_num',''), d.get('amp_s_def',''), d.get('y_start_end',''), d.get('len_y',''),
                           d.get('x_start_end',''), d.get('len_x',''), d.get('z_start_end',''), d.get('height',''),
                           d.get('defect_type',''), d.get('quality',''), d.get('fio',''), d.get('no_defect',''))
            else:
                d_tuple = d[1:13] if len(d) >= 13 else tuple([""]*12)
                
            plan.append({'type': 'defect', 'payload': d_tuple})
            
        channels.append({
            'measurement': list(m['measurement']),
            'plan': plan,
            'rowspan': len(plan)
        })
        total_data_rows += len(plan)

    channel_converters = {}
    for m in items:
        meas = m['measurement']
        ch = meas[11] or ""
        channel_converters.setdefault(ch, set())
        for t, s, p, ps in ((meas[3], meas[4], meas[5], meas[6]), (meas[7], meas[8], meas[9], meas[10])):
            if any((t, s, p, ps)):
                channel_converters[ch].add(f"{t} №{s}\n{p} №{ps}")

    second_col = (
        f"{first_common[3]}\n{first_common[4]}\n{first_common[5]}\n"
        f"{first_common[6]}\n{first_common[7]}\n{first_common[8]}\n{first_common[9]}"
    )
    if comment:
        second_col += f"\n\n{comment}"

    first_meas = channels[0]['measurement'] if channels else [""]*25
    common_vals = [
        f"№ {first_common[0]}\n{first_common[1]}",
        second_col,
        f"{first_common[10]}\n{first_common[11]}\n{first_common[12]}",
        f"{safe_text(first_meas[0])}\n{safe_text(first_meas[1])}\n{safe_text(first_meas[2])}",
    ]

    return {
        'common_vals': common_vals,
        'record_num': first_common[2],
        'method_is_tofd': str(first_common[11]).strip().upper() == "TOFD",
        'total_data_rows': total_data_rows,
        'channels': channels,
        'channel_converters': {k: "\n".join(sorted(v)) or "-" for k, v in channel_converters.items()},
        'signed_fios': signed_fios,
    }


def _render_conclusion_html(context, template_str):
    env = Environment(autoescape=True)
    env.filters["display"] = lambda v: str(v) if str(v).strip() else "-"
    tpl = env.from_string(template_str)
    return tpl.render(**context)


def export_conclusion_to_pdf(report_data, comment, output_path, template_str):
    context = _build_conclusion_context(report_data, comment)
    if not context:
        return False
    html_body = _render_conclusion_html(context, template_str)
    full_html = f"<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>{html_body}</body></html>"
    return _print_html_to_pdf(full_html, output_path, parent_widget=None)


def export_journal_to_pdf(report_list, output_path, template_str, parent_widget=None):
    html_parts = []
    total = len(report_list)
    
    progress = QProgressDialog("Подготовка данных...", "Отмена", 0, total, parent_widget)
    progress.setWindowTitle("Формирование PDF")
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)

    for i, (report_data, comment) in enumerate(report_list):
        if progress.wasCanceled():
            break
            
        progress.setLabelText(f"Формирование заключения {i+1} из {total}...")
        progress.setValue(i)
        
        context = _build_conclusion_context(report_data, comment)
        if context:
            html_body = _render_conclusion_html(context, template_str)
            # Оборачиваем в div для принудительного разрыва страницы
            html_parts.append(f'<div class="conclusion-page">{html_body}</div>')

    progress.setValue(total)
    
    if not html_parts:
        return False

    # Добавляем CSS-стили для разрыва страниц
    full_html = """
    <!DOCTYPE html><html><head><meta charset='utf-8'>
    <style>
        .conclusion-page { page-break-after: always; }
        .conclusion-page:last-child { page-break-after: auto; }
    </style>
    </head><body>""" + "".join(html_parts) + "</body></html>"
    
    progress.setLabelText("Печать в PDF (Chromium)...")
    progress.setRange(0, 0)
    return _print_html_to_pdf(full_html, output_path, parent_widget=progress)


def _print_html_to_pdf(html, output_path, parent_widget=None):
    fd_html, temp_html = tempfile.mkstemp(suffix=".html", prefix="uzk_")
    with os.fdopen(fd_html, "w", encoding="utf-8") as f:
        f.write(html)
        
    fd_pdf, temp_pdf = tempfile.mkstemp(suffix=".pdf", prefix="uzk_")
    os.close(fd_pdf)
    
    view = QWebEngineView()
    view.hide()

    completed = {"ok": False, "msg": ""}
    loop = QEventLoop()

    def on_finished(file_path, success):
        completed["ok"] = bool(success)
        if not success:
            completed["msg"] = "printToPdf вернул False"
        loop.quit()

    def on_load_finished(ok):
        if not ok:
            completed["msg"] = "loadFinished вернул False (ошибка в HTML)"
            loop.quit()
            return
        QTimer.singleShot(1000, do_print)

    def do_print():
        page_layout = QPageLayout(
            QPageSize(QPageSize.PageSizeId.A3),
            QPageLayout.Orientation.Landscape,
            QMarginsF(10, 10, 10, 10),
            QPageLayout.Unit.Millimeter
        )
        view.page().printToPdf(temp_pdf, page_layout)

    view.page().pdfPrintingFinished.connect(on_finished)
    view.loadFinished.connect(on_load_finished)
    
    view.load(QUrl.fromLocalFile(temp_html))
    
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(300000) 
    loop.exec()
    timer.stop()
        
    view.deleteLater()
    
    success = False
    if completed["ok"] and os.path.exists(temp_pdf):
        try:
            out_dir = os.path.dirname(output_path)
            if out_dir and not os.path.exists(out_dir):
                os.makedirs(out_dir, exist_ok=True)
                
            shutil.move(temp_pdf, output_path)
            success = True
        except Exception as e:
            print(f"Ошибка при сохранении файла: {e}")
    else:
        print(f"PDF не создан. Причина: {completed.get('msg', 'Таймаут или неизвестная ошибка')}")
        
    for p in (temp_html, temp_pdf):
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass
                
    # Закрываем прогресс-бар ТОЛЬКО после завершения всех операций (решает проблему задержки)
    if parent_widget:
        parent_widget.close()
        QApplication.processEvents() # Принудительно обновляем интерфейс
            
    return success