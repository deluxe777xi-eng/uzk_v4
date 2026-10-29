# -*- coding: utf-8 -*-
"""Подготовка данных заключения для отчётов/PDF/печати (перенос v3).

В v3 эти SELECT-кортежи собирались внутри pdf_mixin/journal_mixin. Здесь —
чистые функции без GUI; кортежи имеют тот же порядок полей, что ожидает
PdfEngine (_build_conclusion_full_table): common[0..12], signature,
measurement[0..24], defects[i][0..13].
"""
from .journal_repo import CONCLUSION_SELECT, build_report_data_from_rows


def get_conclusion_report_data(db, report_id):
    """Возвращает (report_data, attachments, journal_name, comment) или (None,...)."""
    conn = db._connect()
    try:
        cursor = conn.cursor()
        cursor.execute(CONCLUSION_SELECT + " WHERE c.id = ? ORDER BY m.id, d.id", (report_id,))
        rows = cursor.fetchall()

        cursor.execute(
            "SELECT id, filename FROM attachments WHERE conclusion_id = ? ORDER BY id",
            (report_id,))
        attachments = cursor.fetchall()

        cursor.execute("SELECT journal, comment FROM conclusions WHERE id = ?", (report_id,))
        jrow = cursor.fetchone()
        journal_name = (jrow[0] or "") if jrow else ""
        comment = (jrow[1] or "") if jrow else ""

        if not rows:
            return None, attachments, journal_name, comment
        return build_report_data_from_rows(rows), attachments, journal_name, comment
    finally:
        conn.close()


def get_journal_latest_ids(db, journal_name):
    from .journal_repo import get_latest_conclusion_ids
    conn = db._connect()
    try:
        return get_latest_conclusion_ids(conn, journal_name)
    finally:
        conn.close()


def fetch_journal_rows(db, journal_name):
    """Строки журнала: (id, '№ (дата)', изделие, деталь, заказ, объект, оценка, ФИО, подписи, № записи)."""
    from .journal_repo import get_latest_conclusion_ids, fetch_journal_rows as _fetch
    conn = db._connect()
    try:
        ids = get_latest_conclusion_ids(conn, journal_name)
        return _fetch(conn, ids)
    finally:
        conn.close()