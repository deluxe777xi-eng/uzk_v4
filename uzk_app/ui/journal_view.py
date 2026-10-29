# -*- coding: utf-8 -*-
"""Таблица журнала заключений с колонками исходного интерфейса v3."""
from __future__ import annotations

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtWidgets import QTableView


COLUMNS = [
    ("report_num_date", "№ заключения / Дата", 150, Qt.AlignmentFlag.AlignLeft),
    ("izdeliye", "Изделие", 150, Qt.AlignmentFlag.AlignLeft),
    ("detal", "Деталь", 150, Qt.AlignmentFlag.AlignLeft),
    ("order_num", "№ заказа", 120, Qt.AlignmentFlag.AlignLeft),
    ("object_kontr", "Объект контроля", 120, Qt.AlignmentFlag.AlignLeft),
    ("quality", "Оценка", 100, Qt.AlignmentFlag.AlignCenter),
    ("fio_list", "ФИО Дефектоскопист", 150, Qt.AlignmentFlag.AlignLeft),
    ("sign_status", "Статус подписи", 100, Qt.AlignmentFlag.AlignCenter),
    ("record_num", "№ записи", 100, Qt.AlignmentFlag.AlignCenter),
]


class JournalTableModel(QAbstractTableModel):
    def __init__(self, rows=None):
        super().__init__()
        self.rows = rows or []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        key, _title, _width, alignment = COLUMNS[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            if key == "report_num_date":
                return f"{row.get('report_num', '')} ({row.get('date', '')})"
            return str(row.get(key, "") or "")
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(alignment | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section][1]
        return None

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        if not 0 <= column < len(COLUMNS):
            return
        key = COLUMNS[column][0]

        def sort_key(row):
            if key == "report_num_date":
                value = row.get("report_num", "")
            else:
                value = row.get(key, "")
            return str(value or "").casefold()

        self.layoutAboutToBeChanged.emit()
        self.rows.sort(
            key=sort_key,
            reverse=order == Qt.SortOrder.DescendingOrder,
        )
        self.layoutChanged.emit()

    def load(self, rows):
        self.beginResetModel()
        self.rows = list(rows or [])
        self.endResetModel()


class JournalTable(QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.model_ = JournalTableModel()
        self.setModel(self.model_)
        self.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.setSortingEnabled(True)
        self.horizontalHeader().setSortIndicatorShown(True)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        for column, (_key, _title, width, _alignment) in enumerate(COLUMNS):
            self.setColumnWidth(column, width)

    def load_rows(self, rows):
        self.model_.load(rows)

    def current_row_dict(self):
        index = self.currentIndex()
        if not index.isValid():
            return None
        return self.model_.rows[index.row()]

    def selected_row_dicts(self):
        indexes = self.selectionModel().selectedRows()
        return [self.model_.rows[index.row()] for index in indexes]
