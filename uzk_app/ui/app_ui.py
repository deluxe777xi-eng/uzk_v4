# -*- coding: utf-8 -*-
"""Адаптер интерфейса для движков (PdfEngine, ExcelImport).

В v3 модули pdf_mixin/import_mixin вызывали tkinter напрямую:
messagebox.showwarning / filedialog.asksaveasfilename / Toplevel-диалоги.
Здесь — тонкая обёртка над QMessageBox/QFileDialog PyQt6 с тем же API
(UiHost), чтобы движки остались чистыми и не импортировали Qt-виджеты.
"""
from __future__ import annotations

import os
import subprocess
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)


class UiHost:
    """Единая точка взаимодействия движков с GUI."""

    def __init__(self, parent: QWidget):
        self.parent = parent

    # ---------- сообщения ----------
    def info(self, title, text):
        QMessageBox.information(self.parent, title, text)

    def warn(self, title, text):
        QMessageBox.warning(self.parent, title, text)

    def error(self, title, text):
        QMessageBox.critical(self.parent, title, text)

    def ask_yes_no(self, title, text) -> bool:
        ret = QMessageBox.question(
            self.parent, title, text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return ret == QMessageBox.StandardButton.Yes

    # ---------- файловые диалоги ----------
    def save_pdf_path(self, title, default_name) -> str | None:
        path, _ = QFileDialog.getSaveFileName(
            self.parent, title, default_name, "PDF files (*.pdf)")
        if not path:
            return None
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        return path

    def open_excel_path(self) -> str | None:
        path, _ = QFileDialog.getOpenFileName(
            self.parent, "Выберите файл Excel", "",
            "Файлы Excel (*.xlsx *.xls);;Все файлы (*)")
        return path or None

    def open_file(self, path):
        """Открыть готовый файл в стандартной программе ОС."""
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:  # noqa: BLE001
            self.error("Ошибка", f"Не удалось открыть файл: {e}")

    # ---------- логирование ----------
    def log_action(self, action, details=None, diff_data=None):
        """Пишет лог через MainWindow, если он доступен."""
        win = self.parent
        if hasattr(win, "log_action"):
            win.log_action(action, details, diff_data=diff_data)

    # ---------- спец-диалог переполнения страницы PDF ----------
    def show_oversized_dialog(self, error) -> str | None:
        """Возвращает 'auto' | 'manual' | None (аналог диалога из v3)."""
        dlg = QDialog(self.parent)
        dlg.setWindowTitle("Строка не помещается на страницу PDF")
        dlg.resize(660, 420)
        dlg.setModal(True)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(
            "⚠  Одна часть заключения не помещается на страницу"))
        lay.addWidget(QLabel(
            f"Заключение №{error.report_num or '—'}"))
        points_to_mm = 25.4 / 72.0
        height_mm = error.seg_height * points_to_mm
        capacity_mm = error.capacity * points_to_mm
        lay.addWidget(QLabel(
            f"Высота блока: {height_mm:.0f} мм, доступно на странице: "
            f"{capacity_mm:.0f} мм."))
        lay.addWidget(QLabel("Что обычно является причиной:"))
        causes = QLabel(
            "  •  Слишком длинный комментарий к заключению.\n"
            "  •  Переполненные столбцы «Изделие / Деталь / Заказ / Объект / Материал».\n"
            "  •  Много преобразователей в столбце «Оборудование»."
        )
        causes.setWordWrap(True)
        lay.addWidget(causes)
        lay.addWidget(QLabel("Что делать:"))
        guidance = QLabel(
            "✅  Перенести автоматически — программа повторно попробует "
            "уложить данные, перенеся часть строк на следующую страницу. "
            "PDF соберётся, страниц может быть больше обычного.\n\n"
            "✏  Исправить вручную — экспорт будет прерван. Откройте окно "
            "«💬 Комментарии» к заключению, сократите текст (или проверьте "
            "длину полей «Изделие», «Деталь», «Заказ», «Объект» и количество "
            "преобразователей), затем повторите экспорт."
        )
        guidance.setWordWrap(True)
        lay.addWidget(guidance)
        row = QHBoxLayout()
        b_auto = QPushButton("Перенести автоматически")
        b_manual = QPushButton("Исправить вручную")
        b_cancel = QPushButton("Отмена")
        row.addStretch(1)
        row.addWidget(b_auto)
        row.addWidget(b_manual)
        row.addWidget(b_cancel)
        lay.addLayout(row)

        result = {"choice": None}

        def pick_auto():
            result["choice"] = "auto"
            dlg.accept()

        def pick_manual():
            result["choice"] = "manual"
            dlg.accept()

        def cancel():
            result["choice"] = None
            dlg.reject()

        b_auto.clicked.connect(pick_auto)
        b_manual.clicked.connect(pick_manual)
        b_cancel.clicked.connect(cancel)
        dlg.exec()
        return result["choice"]