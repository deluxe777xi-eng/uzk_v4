# -*- coding: utf-8 -*-
"""Отчёты v4: шаблоны Jinja2 -> HTML; PDF строится тем же ReportLab, что и в v3.

Структура данных для шаблонов (conclusion / journal):
  conclusion = {
      "common": [report_num, date, record_num, izdeliye, detal, order_num,
                 object_kontr, material, thickness, volume_kontr, norm_doc,
                 method_kontr, map_kontr],
      "signature": [...], "comment": str,
      "measurements": [{"measurement": [25 полей], "defects": [[14 полей], ...]}]
  }
Порядки полей совпадают с SELECT из db.py/report_data.py, поэтому шаблоны
переезжают между версиями без правок.
"""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import TEMPLATES_DIR
from .helpers import display_value, safe_text, to_dotted_date


def get_environment():
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR), encoding="utf-8"),
        autoescape=select_autoescape(("html", "xml")),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["display"] = display_value
    env.filters["date"] = to_dotted_date
    return env


def render_template(template_name, **context):
    env = get_environment()
    template = env.get_template(template_name)
    return template.render(**context)


# ============================================================
#  Подготовка данных для шаблонов
# ============================================================

MEAS_LABELS_ORDER = [
    ("prog_obespec", "Программное обеспечение"),
    ("tip_defectoscope", "Тип дефектоскопа"),
    ("tip_skan_ustr", "Тип сканирующего устройства"),
]

DEFECT_HEADERS = ["№ участка", "Aдеф/Sдеф", "Yн:Yк", "Протяженность Y", "Xн:Xк",
                  "Протяженность X", "Zн:Zк", "Высота", "Тип дефекта", "Оценка",
                  "ФИО", "Подпись"]


def conclusion_to_report_context(report_data, comment=""):
    """report_data — dict {idx: {'common':..., 'measurement':..., 'defects':...}} из report_data.py."""
    if not report_data:
        return None
    items = list(report_data.values())
    common = list(items[0]["common"])
    signature = items[0].get("signature") or ""
    if isinstance(signature, str):
        try:
            import json
            signature_list = json.loads(signature) if signature else []
        except Exception:
            signature_list = [signature] if signature else []
    else:
        signature_list = list(signature or [])

    measurements = []
    for item in items:
        measurements.append({
            "measurement": list(item["measurement"]),
            "defects": [list(d) for d in item.get("defects", [])],
        })

    return {
        "common": common,
        "signature": signature_list,
        "comment": safe_text(comment),
        "measurements": measurements,
        "method_is_tofd": str(common[11]).strip().upper() == "TOFD",
    }


def journal_rows_to_context(journal_name, rows):
    """rows — результат Database/JournalRepository.fetch_journal_rows."""
    out = []
    for row in rows:
        out.append({
            "id": row[0],
            "report_num_date": row[1],
            "izdeliye": row[2],
            "detal": row[3],
            "order_num": row[4],
            "object_kontr": row[5],
            "quality": row[6],
            "fio_list": row[7],
            "sign_status": row[8],
            "record_num": row[9],
        })
    return {"journal_name": journal_name, "rows": out}


# ============================================================
#  Экспорт HTML/PDF через PyQt6-WebEngine (быстрый путь)
# ============================================================

def export_html_via_webengine(html, output_path, timeout_ms=30000):
    """Рендерит HTML через QWebEngineView и сохраняет PDF (printToPdf).

    Возвращает True/False. Требует работающий QApplication и импорт
    PyQt6.QtWebEngine (на Windows может потребоваться
    multiprocessing.freeze_support() в точке входа).
    """
    from PyQt6.QtCore import QEventLoop, QTimer, QUrl
    from PyQt6.QtGui import QPageSize, QPageLayout
    from PyQt6.QtWebEngineWidgets import QWebEngineView

    view = QWebEngineView()
    completed = {"ok": False}
    loop = QEventLoop()

    def on_finished(ok):
        completed["ok"] = bool(ok)
        loop.quit()

    view.page().pdfPrintFinished.connect(on_finished)
    view.setHtml(html, QUrl("about:blank"))

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)

    def do_print():
        page_layout = QPageLayout(
            QPageSize(QPageSize.PageSizeId.A3),
            QPageLayout.Orientation.Landscape,
        )
        view.page().printToPdf(output_path, page_layout)

    timer.start(timeout_ms)
    QTimer.singleShot(700, do_print)  # ждём загрузки шрифтов/вёрстки
    loop.exec()
    timer.stop()
    view.deleteLater()
    return completed["ok"]


def export_pdf_reportlab(elements, output_path, page_size, margins):
    """Обёртка над SimpleDocTemplate — единая точка записи PDF (ReportLab)."""
    from reportlab.platypus import SimpleDocTemplate

    left, right, top, bottom = margins
    doc = SimpleDocTemplate(
        output_path, pagesize=page_size,
        leftMargin=left, rightMargin=right, topMargin=top, bottomMargin=bottom,
    )
    doc.build(elements)
    return output_path