# -*- coding: utf-8 -*-
"""Вспомогательные функции v4 (без tkinter).

sqlite3 и Jinja2 не зависят от GUI; сюда вынесено то, что используют все
слои приложения. ReportLab вызывается PDF-движком отдельно. Функции,
работавшие с tk-виджетами
(_fit_dialog_height, _install_clipboard_hotkeys), в PyQt6 не нужны —
их заменяют стандартные механизмы Qt.
"""
import datetime
from pathlib import Path


def ensure_parent_dir(path_str):
    path = Path(path_str)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)


# Совместимость со старым именем
_ensure_parent_dir = ensure_parent_dir


def safe_date_str(value):
    """Преобразует дату в строку dd.mm.yyyy и безопасно обрабатывает пустые значения."""
    if value in (None, ""):
        return ""
    try:
        if isinstance(value, (datetime.date, datetime.datetime)):
            return value.strftime('%d.%m.%Y')
        return str(value)
    except Exception:
        return ""


_safe_date_str = safe_date_str


def safe_text(value):
    """Возвращает безопасную строку без None, лишних пробелов и пустых значений."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


_safe_text = safe_text


def pdf_escape(value):
    """Экранирует текст для вставки в reportlab.Paragraph / HTML (мини-XML разметка)."""
    from xml.sax.saxutils import escape
    text = safe_text(value)
    return escape(text).replace("\n", "<br/>")


_pdf_escape = pdf_escape


def display_value(value):
    """Значение для таблиц: пустое -> '-', неразрывные пробелы -> обычные."""
    value = "" if value is None else str(value).replace("\xa0", " ").strip()
    return value if value else "-"


def parse_date_string(value):
    """Разбирает дату из строки в любом распространённом формате -> datetime.date | None."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    s = str(value).strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%y"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def to_dotted_date(value):
    """Любое представление даты из БД/Qt -> dd.mm.YYYY ('' если пусто)."""
    if value in (None, ""):
        return ""
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.strftime("%d.%m.%Y")
    s = str(value).strip()
    d = parse_date_string(s)
    return d.strftime("%d.%m.%Y") if d else s


def timestamp_now():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def timestamp_display(ts):
    try:
        return datetime.datetime.strptime(ts, '%Y-%m-%d %H:%M:%S').strftime('%d.%m.%Y %H:%M:%S')
    except Exception:
        return ts or ""