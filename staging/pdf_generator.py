# -*- coding: utf-8 -*-
"""Генератор PDF через HTML + Chromium (QWebEngineView.printToPdf).

Модуль заменяет ReportLab-движок (pdf_engine.PdfEngine) в экспорте заключений
и журналов: данные из БД -> Jinja2 (templates/conclusion.html) -> HTML ->
Chromium -> PDF.

Ключевые решения (по итогам первой, неудачной миграции):

1. КИРИЛЛИЦА В ПУТЯХ / ДЛИННЫЙ HTML.
   setHtml() с большим HTML и печать сразу в путь с кириллицей в Chromium
   работают нестабильно. Поэтому:
     * HTML всегда пишется во временный файл с ЛАТИНСКИМ именем
       (tempfile.mkstemp(prefix="uzk_pdf_")) и грузится только через
       view.load(QUrl.fromLocalFile(temp_html));
     * printToPdf пишет во второй временный PDF-файл, а готовый документ
       перемещается shutil.move() по пути, который выбрал пользователь
       (пусть даже «C:\\Отчёты\\Журнал_Общий_31.12.2025.pdf»).

2. АСИНХРОННОСТЬ.
   QWebEnginePage.printToPdf() не возвращает результат синхронно — ждём сигнал
   page.pdfPrintingFinished(path, success) через локальный QEventLoop
   (никаких time.sleep(), события интерфейса продолжают обрабатываться).

3. ПРОГРЕСС ЖУРНАЛА (130+ заключений).
   QProgressDialog + QApplication.processEvents() на каждой итерации, текст
   вида «Формирование 1 из 130...». Отмена — по кнопке «Отмена».

4. РАЗМЕР СТРАНИЦЫ задаётся ТОЛЬКО здесь, через QPageLayout
   (A3, Landscape, отступы 10 мм). В conclusion.html правила @page нет.

Публичное API:
    export_conclusion_to_pdf(report_data, comment, output_path, parent=None) -> bool
    export_journal_to_pdf(journal_name, report_ids, db, output_path, parent=None) -> bool
"""
import json
import os
import shutil
import tempfile

from PyQt6.QtCore import Qt, QEventLoop, QTimer, QUrl, QMarginsF
from PyQt6.QtGui import QPageSize, QPageLayout
from PyQt6.QtWidgets import QApplication, QProgressDialog
from PyQt6.QtWebEngineWidgets import QWebEngineView
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import TEMPLATES_DIR
from .helpers import safe_text
from .journal_repo import get_latest_conclusion_ids, iter_conclusion_report_data


# ---------------------------------------------------------------------------
#  Параметры страницы (единственное место, где задаётся формат листа)
# ---------------------------------------------------------------------------
PDF_PAGE_FORMAT = QPageSize.PageSizeId.A3
PDF_PAGE_ORIENTATION = QPageLayout.Orientation.Landscape
PDF_PAGE_MARGINS_MM = (10.0, 10.0, 10.0, 10.0)      # left, top, right, bottom

CONCLUSION_TEMPLATE = "conclusion.html"
PAGE_BREAK_HTML = '<div style="page-break-before: always;"></div>'
PRINT_TIMEOUT_MS = 300_000        # запас для больших журналов (130+ заключений)
LAYOUT_SETTLE_MS = 250            # пауза после loadFinished до печати (вёрстка/шрифты)


def _make_page_layout():
    """QPageLayout: A3, альбомная ориентация, поля 10 мм."""
    return QPageLayout(
        QPageSize(PDF_PAGE_FORMAT),
        PDF_PAGE_ORIENTATION,
        QMarginsF(*PDF_PAGE_MARGINS_MM),
        QPageLayout.Unit.Millimeter,
    )


def _display(value):
    """Jinja-фильтр display: пустое значение печатается как «-».

    Неразрывные пробелы (\xa0), приходящие из БД, приводятся к обычным.
    """
    text = "" if value is None else str(value).replace("\xa0", " ").strip()
    return text if text else "-"


def _nl2br(value):
    """Переводит переводы строк в <br> (для многострочных ячеек)."""
    return _display(value).replace("\n", "<br>")


def _get_template_env():
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(("html", "htm", "xml")),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["display"] = _display
    env.filters["nl2br"] = _nl2br
    return env


def render_conclusion_html(context, template_source=None):
    """Рендерит HTML одного заключения (без <html>/<body>)."""
    env = _get_template_env()
    if template_source:
        template = env.from_string(template_source)
    else:
        template = env.get_template(CONCLUSION_TEMPLATE)
    return template.render(**context)


# ---------------------------------------------------------------------------
#  Подготовка контекста (все rowspan считаются ЗДЕСЬ, шаблон их только печатает)
# ---------------------------------------------------------------------------
def _parse_signed_fios(signature_value):
    """signature в БД — JSON-список ФИО, которые поставили подпись."""
    raw = safe_text(signature_value)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if isinstance(data, str):                 # иногда хранят просто строку
        data = [data]
    if not isinstance(data, (list, tuple)):
        return []
    return [str(item).strip() for item in data if str(item).strip()]


def _plan_rows(defects, show_objects):
    """Строки блока канала: заголовки объектов + дефекты (как в pdf_engine).

    kind: "obj_header" — отдельная строка объекта контроля (colspan=9),
          "defect"     — строка дефекта,
          "no_defect"  — строка «Дефектов не обнаружено».
    d — кортеж дефекта из CONCLUSION_SELECT: [0]=id, [1..11]=поля,
        [12]=no_defect, [13]=defect_object.
    """
    if not defects:
        return [{"kind": "no_defect", "d": None}]

    plan = []
    seen_objects = set()
    has_any_object = show_objects and any(
        len(d) > 13 and str(d[13] or "").strip() for d in defects if d
    )
    for d in defects:
        if not d:
            continue
        obj = str(d[13] or "").strip() if len(d) > 13 else ""
        if has_any_object and obj and obj not in seen_objects:
            plan.append({"kind": "obj_header", "obj": obj})
            seen_objects.add(obj)
        if safe_text(d[12]) == "Да":
            plan.append({"kind": "no_defect", "d": d})
        else:
            plan.append({"kind": "defect", "d": d})
    return plan or [{"kind": "no_defect", "d": None}]


def build_conclusion_context(report_data, comment=""):
    """Собирает контекст Jinja2 из report_data (dict|list измерений заключения).

    Возвращает None, если данных нет. Все rowspan (общие сведения, блоки
    каналов, всего строк) считаются здесь — шаблон использует готовые цифры.
    """
    if not report_data:
        return None

    items = list(report_data.values()) if isinstance(report_data, dict) else list(report_data)
    if not items:
        return None

    first_common = list(items[0]["common"])
    first_measurement = list(items[0].get("measurement") or [""] * 25)
    signed_fios = _parse_signed_fios(items[0].get("signature"))

    # Объекты контроля: отдельная строка нужна, только если объектов больше одного
    all_objects = set()
    for item in items:
        for d in item.get("defects") or []:
            if d and len(d) > 13:
                for part in str(d[13] or "").split(","):
                    if part.strip():
                        all_objects.add(part.strip())
    show_objects = len(all_objects) > 1

    channels = []
    total_data_rows = 0
    for item in items:
        meas = list(item.get("measurement") or [""] * 25)
        rows = _plan_rows(item.get("defects") or [], show_objects)

        converters = []
        for conv, conv_sn, prism, prism_sn in ((meas[3], meas[4], meas[5], meas[6]),
                                               (meas[7], meas[8], meas[9], meas[10])):
            if any((conv, conv_sn, prism, prism_sn)):
                converters.append("%s №%s\n%s №%s" % (_display(conv), _display(conv_sn),
                                                      _display(prism), _display(prism_sn)))
        converters_text = "\n".join(dict.fromkeys(converters)) or "-"

        channels.append({
            "measurement": meas,
            "converters": converters_text,
            "rows": rows,
            "rowspan": len(rows),           # готовая цифра rowspan для блока канала
        })
        total_data_rows += len(rows)

    common_vals = [
        "№ %s\n%s" % (_display(first_common[0]), _display(first_common[1])),
        "\n".join(_display(first_common[i]) for i in range(3, 10)),
        "\n".join(_display(first_common[i]) for i in (10, 11, 12)),
        "\n".join(_display(v) for v in first_measurement[:3]),
    ]
    if safe_text(comment):
        common_vals[1] += "\n\n" + str(comment)

    return {
        "common_vals": common_vals,
        "record_num": _display(first_common[2]),
        "method_is_tofd": str(first_common[11]).strip().upper() == "TOFD",
        "total_data_rows": total_data_rows,   # rowspan общих сведений (первая строка)
        "channels": channels,
        "signed_fios": signed_fios,           # JSON-список подписантов
    }


# ---------------------------------------------------------------------------
#  Обёртки экспорта
# ---------------------------------------------------------------------------
def export_conclusion_to_pdf(report_data, comment="", output_path=None,
                             parent=None, template_str=None):
    """Экспортирует ОДНО заключение в PDF. Возвращает True при успехе."""
    if not output_path:
        raise ValueError("export_conclusion_to_pdf: не задан output_path")

    context = build_conclusion_context(report_data, comment)
    if context is None:
        return False

    body = render_conclusion_html(context, template_str)
    html = _wrap_document(body, with_breaks=False)
    return _print_html_to_pdf(html, output_path, parent=parent)


def export_journal_to_pdf(journal_name, report_ids, db, output_path,
                          parent=None, template_str=None):
    """Экспортирует журнал (список id заключений) в один PDF с прогресс-баром.

    HTML всех заключений склеивается в один документ; между заключениями
    вставляется <div style="page-break-before: always;"></div>.
    Возвращает True при успехе, None — если экспорт отменён пользователем.
    """
    if not output_path:
        raise ValueError("export_journal_to_pdf: не задан output_path")

    ids = list(report_ids or [])
    if not ids and db is not None:
        conn = db._connect()
        try:
            ids = get_latest_conclusion_ids(conn, journal_name)
        finally:
            conn.close()
    if not ids:
        return False

    total = len(ids)
    progress = QProgressDialog("Подготовка данных...", "Отмена", 0, total, parent)
    progress.setWindowTitle("Экспорт журнала в PDF")
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setAutoClose(False)
    progress.setValue(0)
    QApplication.processEvents()

    parts = []
    canceled = False
    conn = db._connect()
    try:
        for index, (report_data, row_comment) in enumerate(
                iter_conclusion_report_data(conn, ids, batch_size=100)):
            if progress.wasCanceled():
                canceled = True
                break
            # «Формирование 1 из 130...» + processEvents() — интерфейс не виснет
            progress.setLabelText("Формирование %d из %d..." % (index + 1, total))
            progress.setValue(index + 1)
            QApplication.processEvents()

            context = build_conclusion_context(report_data, row_comment)
            if context is None:
                continue
            parts.append(render_conclusion_html(context, template_str))
    finally:
        conn.close()

    if canceled:
        progress.close()
        QApplication.processEvents()
        return None
    if not parts:
        progress.close()
        QApplication.processEvents()
        return False

    progress.setLabelText("Печать в PDF (Chromium)...")
    progress.setRange(0, 0)                 # безлиний режим на время печати
    QApplication.processEvents()

    html = _wrap_document(parts, with_breaks=True)
    ok = _print_html_to_pdf(html, output_path, parent=progress)
    progress.close()
    QApplication.processEvents()
    return ok


def _wrap_document(body_parts, with_breaks):
    """Собирает полноценный HTML-документ из тела заключения(й).

    Правило @page НЕ используется — размер листа и поля задаёт QPageLayout
    в Python (_make_page_layout).
    """
    chunks = [body_parts] if isinstance(body_parts, str) else list(body_parts)
    separator = PAGE_BREAK_HTML if with_breaks else ""
    body = separator.join(chunks)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="ru">\n<head><meta charset="utf-8"><title>УЗК</title>\n'
        "<style>\n"
        "  * { box-sizing: border-box; }\n"
        "  html, body { margin: 0; padding: 0; background: #fff; color: #000; }\n"
        "  body { font-family: Arial, 'PT Sans', sans-serif; font-size: 8pt; }\n"
        "  table { border-collapse: collapse; width: 100%; table-layout: fixed; }\n"
        "  th, td { border: 1px solid #000; padding: 1px 3px; vertical-align: top;"
        " overflow-wrap: anywhere; }\n"
        "  thead th { text-align: center; vertical-align: middle; font-weight: bold; }\n"
        "  .center { text-align: center; }\n"
        "  .nowrap { white-space: nowrap; }\n"
        "  .bold { font-weight: bold; }\n"
        "  .page-break { page-break-before: always; break-before: page; height: 0; }\n"
        "</style>\n</head>\n<body>\n" + body + "\n</body>\n</html>\n"
    )


# ---------------------------------------------------------------------------
#  Печать через Chromium (асинхронно, без блокировок)
# ---------------------------------------------------------------------------
def _print_html_to_pdf(html, output_path, parent=None, timeout_ms=PRINT_TIMEOUT_MS):
    """HTML -> временный файл (латиница) -> QWebEngineView -> временный PDF -> shutil.move.

    Возвращает True, если PDF создан и сохранён по output_path.
    """
    temp_html = None
    temp_pdf = None
    error = {"msg": "печать не завершена (таймаут или ошибка Chromium)"}

    # 1. HTML во временный файл с ЛАТИНСКИМ именем (кириллица в путях ломает Chromium)
    fd, temp_html = tempfile.mkstemp(suffix=".html", prefix="uzk_pdf_")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(html)

    # 2. PDF тоже во временный файл — потом перенесём в путь пользователя
    fd_pdf, temp_pdf = tempfile.mkstemp(suffix=".pdf", prefix="uzk_pdf_")
    os.close(fd_pdf)                        # содержимое создаст сам Chromium

    view = QWebEngineView(parent)           # скрытый view нужен только для рендера
    view.hide()

    loop = QEventLoop()
    state = {"ok": False}

    def finish(ok, reason=""):
        state["ok"] = bool(ok)
        if not ok and reason:
            error["msg"] = reason
        if loop.isRunning():
            loop.quit()

    def on_pdf_finished(file_path, success):
        if file_path and os.path.normcase(file_path) != os.path.normcase(temp_pdf):
            return                          # событие от другой печати — игнорируем
        finish(bool(success), "" if success else "printToPdf вернул success=False")

    def on_load_finished(ok):
        if not ok:
            finish(False, "loadFinished(False): Chromium не смог загрузить HTML")
            return
        QTimer.singleShot(LAYOUT_SETTLE_MS, do_print)

    def do_print():
        try:
            view.page().printToPdf(temp_pdf, _make_page_layout())
        except Exception as exc:
            finish(False, "исключение printToPdf: %s" % exc)

    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(lambda: finish(False, "превышено время ожидания печати"))

    view.page().pdfPrintingFinished.connect(on_pdf_finished)
    view.loadFinished.connect(on_load_finished)
    view.load(QUrl.fromLocalFile(temp_html))

    watchdog.start(timeout_ms)
    loop.exec()                             # крутим события вместо while/sleep
    watchdog.stop()

    saved = False
    if state["ok"] and os.path.exists(temp_pdf) and os.path.getsize(temp_pdf) > 0:
        try:
            out_dir = os.path.dirname(os.path.abspath(output_path))
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            if os.path.exists(output_path):
                os.remove(output_path)      # shutil.move не перезаписывает существующее
            shutil.move(temp_pdf, output_path)
            temp_pdf = None
            saved = True
        except Exception as exc:
            error["msg"] = "не удалось сохранить файл %r: %s" % (output_path, exc)

    view.loadFinished.disconnect(on_load_finished)
    view.page().pdfPrintingFinished.disconnect(on_pdf_finished)
    view.deleteLater()

    for path in (temp_html, temp_pdf):
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    if not saved:
        print("[pdf_generator] PDF не создан: %s" % error["msg"])
    return saved
