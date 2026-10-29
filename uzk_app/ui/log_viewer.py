# -*- coding: utf-8 -*-
"""Журнал действий с фильтрами."""
from __future__ import annotations

import json
from datetime import datetime

from PyQt6.QtCore import Qt, QDate
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QDateEdit, QTextEdit, QStyle
)

from ..db import Database


class LogViewerDialog(QDialog):
    def __init__(self, parent, db: Database):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Журнал действий системы")
        # Добавляем иконку для этого окна
        self.setWindowIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        
        self.resize(1100, 700)
        self._build_ui()
        self.load_logs()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # === ПАНЕЛЬ ФИЛЬТРОВ ===
        filter_layout = QHBoxLayout()
        
        filter_layout.addWidget(QLabel("С:"))
        self.date_from = QDateEdit()
        self.date_from.setDisplayFormat("dd.MM.yyyy")
        self.date_from.setCalendarPopup(True)
        self.date_from.setDate(QDate.currentDate().addMonths(-1))
        filter_layout.addWidget(self.date_from)

        filter_layout.addWidget(QLabel("По:"))
        self.date_to = QDateEdit()
        self.date_to.setDisplayFormat("dd.MM.yyyy")
        self.date_to.setCalendarPopup(True)
        self.date_to.setDate(QDate.currentDate())
        filter_layout.addWidget(self.date_to)

        filter_layout.addWidget(QLabel("ФИО:"))
        self.user_combo = QComboBox()
        self.user_combo.addItem("Все пользователи", "")
        users = self.db.get_users()
        for u in users:
            self.user_combo.addItem(u["fio"], u["fio"])
        filter_layout.addWidget(self.user_combo)

        filter_layout.addWidget(QLabel("Поиск:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Действие или описание...")
        filter_layout.addWidget(self.search_edit)

        self.btn_apply = QPushButton("🔍 Применить")
        self.btn_apply.clicked.connect(self.load_logs)
        filter_layout.addWidget(self.btn_apply)

        self.btn_reset = QPushButton("❌ Сброс")
        self.btn_reset.clicked.connect(self._reset_filters)
        filter_layout.addWidget(self.btn_reset)

        self.btn_refresh = QPushButton("🔄 Обновить")
        self.btn_refresh.clicked.connect(self.load_logs)
        filter_layout.addWidget(self.btn_refresh)

        layout.addLayout(filter_layout)

        # === ТАБЛИЦА ===
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Дата и время", "Пользователь", "Действие", "Описание"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        
        self.table.doubleClicked.connect(self._show_details)
        layout.addWidget(self.table, 1)

        # === НИЖНЯЯ ПАНЕЛЬ ===
        bottom_layout = QHBoxLayout()
        bottom_layout.addWidget(QLabel("(Двойной клик по записи для просмотра подробностей)"))
        bottom_layout.addStretch()
        btn_close = QPushButton("Закрыть")
        btn_close.clicked.connect(self.accept)
        bottom_layout.addWidget(btn_close)
        layout.addLayout(bottom_layout)

    def _reset_filters(self):
        self.date_from.setDate(QDate.currentDate().addMonths(-1))
        self.date_to.setDate(QDate.currentDate())
        self.user_combo.setCurrentIndex(0)
        self.search_edit.clear()
        self.load_logs()

    def load_logs(self):
        start_date = self.date_from.date().toString("yyyy-MM-dd")
        end_date = self.date_to.date().toString("yyyy-MM-dd")
        selected_fio = self.user_combo.currentData()
        search_text = self.search_edit.text().strip()

        try:
            all_logs = self.db.get_logs()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка БД", f"Не удалось загрузить логи:\n{e}")
            return

        filtered = []
        for log in all_logs:
            if hasattr(log, 'keys'):
                log_dict = dict(log)
            else:
                log_dict = {
                    "id": log[0] if len(log) > 0 else None,
                    "timestamp": str(log[1]) if len(log) > 1 else "",
                    "fio": "Служба поддержки",
                    "action": "—",
                    "details": "",
                    "diff_data": None
                }
                if len(log) == 5:
                    log_dict["fio"] = str(log[2]) if log[2] else "Служба поддержки"
                    log_dict["details"] = str(log[3]) if log[3] else ""
                    log_dict["diff_data"] = log[4]
                elif len(log) >= 6:
                    val2 = str(log[2]) if log[2] else ""
                    val3 = str(log[3]) if log[3] else ""
                    if val2.isascii() and not val2.isdigit():
                        log_dict["action"] = val2
                        log_dict["fio"] = val3 or "Служба поддержки"
                        log_dict["details"] = str(log[4]) if log[4] else ""
                        log_dict["diff_data"] = log[5] if len(log) > 5 else None
                    else:
                        log_dict["fio"] = val2 or "Служба поддержки"
                        log_dict["action"] = val3
                        log_dict["details"] = str(log[4]) if log[4] else ""
                        log_dict["diff_data"] = log[5] if len(log) > 5 else None

            log_date_str = str(log_dict.get("timestamp", ""))[:10]
            if start_date and log_date_str < start_date:
                continue
            if end_date and log_date_str > end_date:
                continue
                
            if selected_fio and log_dict.get("fio") != selected_fio:
                continue

            if search_text:
                txt = f"{log_dict.get('action', '')} {log_dict.get('details', '')}".casefold()
                if search_text.casefold() not in txt:
                    continue

            filtered.append(log_dict)

        self.table.setRowCount(len(filtered))
        for row, log in enumerate(filtered):
            dt_str = str(log.get("timestamp", ""))
            try:
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                display_dt = dt.strftime("%d.%m.%Y %H:%M:%S")
            except:
                display_dt = dt_str

            fio = log.get("fio") or "Служба поддержки"
            
            self.table.setItem(row, 0, QTableWidgetItem(display_dt))
            self.table.setItem(row, 1, QTableWidgetItem(fio))
            self.table.setItem(row, 2, QTableWidgetItem(str(log.get("action", ""))))
            
            details_item = QTableWidgetItem(str(log.get("details", "")))
            details_item.setData(Qt.ItemDataRole.UserRole, log)
            self.table.setItem(row, 3, details_item)

    def _show_details(self, index):
        row = index.row()
        item = self.table.item(row, 3)
        if not item:
            return
            
        log = item.data(Qt.ItemDataRole.UserRole)
        if not log:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Подробности записи журнала")
        dialog.setWindowIcon(self.windowIcon()) # Наследуем иконку
        dialog.resize(800, 600)
        layout = QVBoxLayout(dialog)

        info_text = (
            f"Дата: {log.get('timestamp', '')}\n"
            f"Пользователь: {log.get('fio') or 'Служба поддержки'}\n"
            f"Действие: {log.get('action', '')}\n"
            f"Описание: {log.get('details', '')}\n"
        )
        info_label = QLabel(info_text)
        info_label.setStyleSheet("font-size: 11pt; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(info_label)

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setStyleSheet("font-family: Consolas, monospace; font-size: 10pt;")
        
        diff_json = log.get("diff_data")
        if diff_json:
            try:
                diff = json.loads(diff_json)
                formatted = self._format_diff(diff)
                text_edit.setPlainText(formatted)
            except Exception as e:
                text_edit.setPlainText(f"Ошибка чтения данных изменений:\n{e}\n\nСырые данные:\n{diff_json}")
        else:
            text_edit.setPlainText("Действие не содержит детальной информации об изменениях.")
            
        layout.addWidget(text_edit, 1)

        btn_close = QPushButton("Закрыть")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close, alignment=Qt.AlignmentFlag.AlignRight)

        dialog.exec()

    def _format_diff(self, diff: dict) -> str:
        lines = []
        
        # 1. Общие сведения
        lines.append("═══ ОБЩИЕ СВЕДЕНИЯ ═══")
        if diff.get("conclusion"):
            for item in diff["conclusion"]:
                lines.append(f"  • {item.get('field')}:")
                lines.append(f"      было:  {item.get('old') or '—'}")
                lines.append(f"      стало: {item.get('new') or '—'}")
        else:
            lines.append("  (Без изменений)")
        lines.append("")

        # 2. Измерения (Каналы)
        lines.append("═══ ИЗМЕРЕНИЯ (КАНАЛЫ) ═══")
        if diff.get("measurements"):
            for item in diff["measurements"]:
                act = item.get("action")
                ch = item.get("channel") or "Без имени"
                if act == "added":
                    lines.append(f"  [+] Добавлен канал '{ch}': {item.get('name', '')}")
                elif act == "deleted":
                    lines.append(f"  [-] Удалён канал '{ch}': {item.get('name', '')}")
                elif act == "changed":
                    lines.append(f"  [~] Изменён канал '{ch}':")
                    for c in item.get("changes", []):
                        lines.append(f"      • {c.get('field')}: '{c.get('old') or '—'}' -> '{c.get('new') or '—'}'")
        else:
            lines.append("  (Без изменений)")
        lines.append("")

        # 3. Дефекты
        lines.append("═══ ДЕФЕКТЫ ═══")
        if diff.get("defects"):
            for item in diff["defects"]:
                act = item.get("action")
                ch = item.get("channel") or "Без имени"
                plot = item.get("plot_num") or "—"
                if act == "added":
                    lines.append(f"  [+] Канал '{ch}', уч. №{plot}: добавлен")
                elif act == "deleted":
                    lines.append(f"  [-] Канал '{ch}', уч. №{plot}: удалён")
                elif act == "changed":
                    lines.append(f"  [~] Канал '{ch}', уч. №{plot}:")
                    for c in item.get("changes", []):
                        lines.append(f"      • {c.get('field')}: '{c.get('old') or '—'}' -> '{c.get('new') or '—'}'")
        else:
            lines.append("  (Без изменений)")

        return "\n".join(lines)