# -*- coding: utf-8 -*-
"""Окно подробного просмотра заключения (в стиле V3)."""
from __future__ import annotations

import os
import json
import tempfile

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QColor, QFontMetrics
from PyQt6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QTextEdit,
    QVBoxLayout, QWidget, QScrollArea
)

from ..helpers import safe_text
from ..report_data import get_conclusion_report_data
from .app_ui import UiHost


class ReportViewDialog(QDialog):
    """Просмотр заключения в виде большой таблицы с объединенными ячейками."""
    
    edit_requested = pyqtSignal(int) # Сигнал для главного окна (передать ID)

    def __init__(self, parent, db, report_id, pdf_engine):
        super().__init__(parent)
        self.db = db
        self.report_id = report_id
        self.pdf_engine = pdf_engine
        self.ui_host = UiHost(self)
        
        # Получаем данные
        report_data, attachments, journal_name, comment = get_conclusion_report_data(db, report_id)
        if not report_data:
            raise ValueError("Заключение не найдено или пусто.")
            
        self.report_data = report_data
        self.comment = comment
        self.attachments = list(attachments)
        
        first_common = next(iter(report_data.values()))['common']
        self.setWindowTitle(f"Заключение №{first_common[0]} — подробности")
        self.resize(1500, 800)
        
        # Включаем кнопку "Развернуть на весь экран" в заголовке окна
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)
        
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        # === ВЕРХНЯЯ ПАНЕЛЬ КНОПОК ===
        top_bar = QHBoxLayout()
        
        btn_edit = QPushButton("✏️ Редактировать заключение")
        btn_edit.setStyleSheet("QPushButton { background-color: #1976D2; color: white; border-radius: 4px; padding: 6px 12px; font-weight: bold; } QPushButton:hover { background-color: #42A5F5; }")
        btn_edit.clicked.connect(self._edit_report)
        top_bar.addWidget(btn_edit)

        btn_pdf = QPushButton("📄 Экспорт в PDF")
        btn_pdf.setStyleSheet("QPushButton { background-color: #388E3C; color: white; border-radius: 4px; padding: 6px 12px; font-weight: bold; } QPushButton:hover { background-color: #66BB6A; }")
        btn_pdf.clicked.connect(self._export_pdf)
        top_bar.addWidget(btn_pdf)

        btn_comment = QPushButton("💬 Комментарии")
        btn_comment.setStyleSheet("QPushButton { background-color: #F57C00; color: white; border-radius: 4px; padding: 6px 12px; font-weight: bold; } QPushButton:hover { background-color: #FFA726; }")
        btn_comment.clicked.connect(self._edit_comment)
        top_bar.addWidget(btn_comment)

        btn_attach = QPushButton("📎 Вложения")
        btn_attach.setStyleSheet("QPushButton { background-color: #7B1FA2; color: white; border-radius: 4px; padding: 6px 12px; font-weight: bold; } QPushButton:hover { background-color: #AB47BC; }")
        btn_attach.clicked.connect(self._manage_attachments)
        top_bar.addWidget(btn_attach)
        
        top_bar.addStretch()
        root.addLayout(top_bar)

        # === ТАБЛИЦА ===
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.horizontalHeader().setVisible(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(True)
        
        self._fill_table()
        
        table_layout.addWidget(self.table)
        scroll.setWidget(table_container)
        root.addWidget(scroll, 1)

        # === НИЖНЯЯ ПАНЕЛЬ ===
        bottom_bar = QHBoxLayout()
        bottom_bar.addStretch()
        
        btn_close = QPushButton("Закрыть")
        btn_close.setStyleSheet("QPushButton { background-color: #455A64; color: white; border-radius: 4px; padding: 6px 20px; } QPushButton:hover { background-color: #78909C; }")
        btn_close.clicked.connect(self.accept)
        bottom_bar.addWidget(btn_close)
        
        root.addLayout(bottom_bar)

    def _get_text_height(self, text, col_width):
        """Вычисляет необходимую высоту ячейки для текста с переносами."""
        if not text:
            return 25
        metrics = QFontMetrics(self.table.font())
        rect = metrics.boundingRect(0, 0, col_width - 15, 10000, Qt.TextFlag.TextWordWrap, text)
        return max(25, rect.height() + 12)

    def _fill_table(self):
        headers = (
            "№ закл. / Дата", 
            "Изделие / Деталь / Заказ / Объект / Материал / Толщина / Объём",
            "Норм. документ / Метод / Карта",
            "ПО / Дефектоскоп / Сканер",
            "Преобразователи и призмы",
            "Канал / Тип скан.",
            "Врем. разв.",
            "Угол / Фокус",
            "Расст. / Предус. / Усред.",
            "Смещение / Шаг Y",
            "Диапазон / Шаг X",
            "НО / Настр. / ВЭ / Усил.",
            "№ уч.", "Aдеф / Sдеф", "Yн:Yк", "Прот. Y", "Xн:Xк", "Прот. X", "Zн:Zк", "Высота", "Тип дефекта", "Оценка", "ФИО", "Подпись", "№ зап."
        )
        
        widths = (135, 180, 180, 190, 210, 130, 115, 150, 190, 145, 145, 210,
                  120, 130, 120, 130, 120, 130, 120, 100, 150, 100, 180, 130, 100)

        # 1. Анализ объектов (как в V3)
        all_objects = set()
        for m in self.report_data.values():
            for d in m.get('defects', []):
                obj = d.get('defect_object', '') if isinstance(d, dict) else (d[13] if len(d) > 13 else '')
                if obj:
                    all_objects.add(str(obj).strip())
        show_objects = len(all_objects) > 1

        # 2. Формируем план строк (с учетом заголовков объектов)
        plan_per_channel = []
        total_rows = 2  # 2 строки под шапку

        for m in self.report_data.values():
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
                    plan.append(('obj_header', obj))
                    seen_objs.add(obj)
                plan.append(('defect', d))
            
            plan_per_channel.append((m, plan))
            total_rows += len(plan)

        self.table.clear()
        self.table.setRowCount(total_rows)
        self.table.setColumnCount(25)
        for i, w in enumerate(widths):
            self.table.setColumnWidth(i, w)

        # --- ЗАГОЛОВКИ (Строка 0 и 1) ---
        groups = [("Общие сведения", 1, 3), ("Оборудование", 3, 5), ("Параметры настройки", 5, 12), ("Результаты контроля", 12, 22)]
        for title, start, end in groups:
            item = QTableWidgetItem(title)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setBackground(QColor("#e6e6e6"))
            item.setForeground(QColor("black"))
            item.setFont(QFont("Arial", 8, QFont.Weight.Bold))
            self.table.setItem(0, start, item)
            self.table.setSpan(0, start, 1, end - start)

        tall_cols = (0, 22, 23, 24)
        for c in tall_cols:
            item = QTableWidgetItem(headers[c])
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setBackground(QColor("#eeeeee"))
            item.setForeground(QColor("black"))
            item.setFont(QFont("Arial", 8, QFont.Weight.Bold))
            self.table.setItem(0, c, item)
            self.table.setSpan(0, c, 2, 1)

        for i, h in enumerate(headers):
            if i in tall_cols: continue
            item = QTableWidgetItem(h)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setBackground(QColor("#eeeeee"))
            item.setForeground(QColor("black"))
            item.setFont(QFont("Arial", 8, QFont.Weight.Bold))
            self.table.setItem(1, i, item)

        self.table.setRowHeight(0, 30)
        self.table.setRowHeight(1, 45)

        # --- ДАННЫЕ ---
        first_common = next(iter(self.report_data.values()))['common']
        record_num = first_common[2]
        method_is_tofd = str(first_common[11]).strip().upper() == "TOFD"

        # Получаем список подписантов из JSON
        first_item = next(iter(self.report_data.values()))
        signature_str = first_item.get('signature', '')
        try:
            signed_fios = json.loads(signature_str) if signature_str else []
        except Exception:
            signed_fios = []
        signed_fios = [str(f).strip() for f in signed_fios if str(f).strip()]

        channel_converters = {}
        for m in self.report_data.values():
            meas = m['measurement']
            ch = meas[11] or ""
            channel_converters.setdefault(ch, set())
            for t, s, p, ps in ((meas[3], meas[4], meas[5], meas[6]), (meas[7], meas[8], meas[9], meas[10])):
                if any((t, s, p, ps)):
                    channel_converters[ch].add(f"{t} №{s}\n{p} №{ps}")

        # Общие сведения (глобальные колонки)
        total_data_rows = total_rows - 2
        second_col = (
            f"{first_common[3]}\n{first_common[4]}\n{first_common[5]}\n"
            f"{first_common[6]}\n{first_common[7]}\n{first_common[8]}\n{first_common[9]}"
        )
        if self.comment:
            second_col += f"\n\n{self.comment}"
            
        first_measurement = next(iter(self.report_data.values()))['measurement']
        common_vals = [
            f"№ {first_common[0]}\n{first_common[1]}",
            second_col,
            f"{first_common[10]}\n{first_common[11]}\n{first_common[12]}",
            f"{safe_text(first_measurement[0])}\n{safe_text(first_measurement[1])}\n{safe_text(first_measurement[2])}",
        ]
        
        for col_idx, text in enumerate(common_vals):
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            item.setBackground(QColor("#f7f9fc"))
            item.setForeground(QColor("black"))
            self.table.setItem(2, col_idx, item)
            self.table.setSpan(2, col_idx, total_data_rows, 1)
            
        rec_item = QTableWidgetItem(record_num)
        rec_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        rec_item.setBackground(QColor("#f7f9fc"))
        rec_item.setForeground(QColor("black"))
        self.table.setItem(2, 24, rec_item)
        self.table.setSpan(2, 24, total_data_rows, 1)

        current_row = 2
        
        # Блоки каналов
        for m, plan in plan_per_channel:
            meas = m['measurement']
            num_rows = len(plan)
            
            # Тексты для колонок параметров (4-11)
            eq_texts = [
                "\n".join(sorted(channel_converters.get(meas[11], []))) or "-",
                f"{safe_text(meas[11])}\n{safe_text(meas[12])}",
                safe_text(meas[13]),
                f"{safe_text(meas[14])}\n{safe_text(meas[15])}",
                f"{safe_text(meas[16])} / {safe_text(meas[17])} / {safe_text(meas[18])}",
                safe_text(meas[19]),
                safe_text(meas[20]),
                f"{safe_text(meas[21])}\n{safe_text(meas[22])}\n{safe_text(meas[23])}\n{safe_text(meas[24])}"
            ]
            
            # Вычисляем максимальную высоту для этого блока
            max_channel_height = 25
            for i, text in enumerate(eq_texts):
                h = self._get_text_height(text, widths[4 + i])
                if h > max_channel_height:
                    max_channel_height = h

            # Заполняем параметры настройки (4-11) с объединением
            for i, text in enumerate(eq_texts):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                item.setBackground(QColor("#f7f9fc"))
                item.setForeground(QColor("black"))
                self.table.setItem(current_row, 4 + i, item)
                self.table.setSpan(current_row, 4 + i, num_rows, 1)

            # Заполняем сами дефекты и заголовки объектов
            for j, (kind, payload) in enumerate(plan):
                row = current_row + j
                
                if kind == 'obj_header':
                    item = QTableWidgetItem(payload)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setBackground(QColor("white"))
                    item.setForeground(QColor("black"))
                    self.table.setItem(row, 12, item)
                    self.table.setSpan(row, 12, 1, 9) # Объединяем 12-20
                    for c in range(21, 25):
                        self._set_cell(row, c, "")
                    continue

                d = payload
                # Проверяем, кортеж это или словарь
                if isinstance(d, dict):
                    plot_num, amp_s_def = d.get('plot_num', ''), d.get('amp_s_def', '')
                    y_start_end, len_y = d.get('y_start_end', ''), d.get('len_y', '')
                    x_start_end, len_x = d.get('x_start_end', ''), d.get('len_x', '')
                    z_start_end, height = d.get('z_start_end', ''), d.get('height', '')
                    defect_type, quality, fio = d.get('defect_type', ''), d.get('quality', ''), d.get('fio', '')
                    no_defect_val = d.get('no_defect', '')
                else:
                    plot_num = d[1] if len(d) > 1 else ""
                    amp_s_def = d[2] if len(d) > 2 else ""
                    y_start_end = d[3] if len(d) > 3 else ""
                    len_y = d[4] if len(d) > 4 else ""
                    x_start_end = d[5] if len(d) > 5 else ""
                    len_x = d[6] if len(d) > 6 else ""
                    z_start_end = d[7] if len(d) > 7 else ""
                    height = d[8] if len(d) > 8 else ""
                    defect_type = d[9] if len(d) > 9 else ""
                    quality = d[10] if len(d) > 10 else ""
                    fio = d[11] if len(d) > 11 else ""
                    no_defect_val = d[12] if len(d) > 12 else ""

                no_def = safe_text(no_defect_val) == "Да"
                
                self._set_cell(row, 12, plot_num, center=True)
                
                if no_def:
                    item = QTableWidgetItem("Дефектов не обнаружено")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setBackground(QColor("white"))
                    item.setForeground(QColor("black"))
                    self.table.setItem(row, 13, item)
                    self.table.setSpan(row, 13, 1, 8) # Объединяем 13-20
                else:
                    amp = (amp_s_def or "").split(" / ")
                    self._set_cell(row, 13, "-" if method_is_tofd else " / ".join(amp), center=True)
                    self._set_cell(row, 14, y_start_end, center=True)
                    self._set_cell(row, 15, len_y, center=True)
                    self._set_cell(row, 16, x_start_end, center=True)
                    self._set_cell(row, 17, len_x, center=True)
                    self._set_cell(row, 18, z_start_end, center=True)
                    self._set_cell(row, 19, height, center=True)
                    self._set_cell(row, 20, defect_type, center=True)
                
                # Обработка подписи для дефекта (как в V3)
                fio_val = safe_text(fio)
                sig_for_defect = ", ".join([f.strip() for f in fio_val.split(",") if f.strip() in signed_fios])

                self._set_cell(row, 21, quality, center=True)
                self._set_cell(row, 22, fio_val, center=True)
                self._set_cell(row, 23, sig_for_defect, center=True) # Выводим подпись
                self._set_cell(row, 24, "")

            # ВРУЧНУЮ РАСПРЕДЕЛЯЕМ ВЫСОТУ, чтобы текст не обрезался
            row_height = int(max_channel_height / num_rows) + 1
            if row_height < 25:
                row_height = 25
                
            for r in range(current_row, current_row + num_rows):
                self.table.setRowHeight(r, row_height)

            current_row += num_rows

    def _set_cell(self, row, col, text, center=False):
        item = QTableWidgetItem(safe_text(text))
        if center:
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        
        # Принудительно белый фон и черный текст (как бланк документа)
        item.setBackground(QColor("white"))
        item.setForeground(QColor("black"))
        self.table.setItem(row, col, item)

    def _edit_report(self):
        self.accept()
        self.edit_requested.emit(self.report_id)

    def _export_pdf(self):
        self.pdf_engine.export_conclusion_to_pdf(self.report_data, self.comment)

    def _edit_comment(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Комментарий к заключению")
        dialog.resize(620, 420)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Текст комментария:"))
        editor = QTextEdit()
        editor.setPlainText(self.comment or "")
        layout.addWidget(editor, 1)
        
        actions = QHBoxLayout()
        
        save = QPushButton("💾 Сохранить")
        save.setStyleSheet("QPushButton { background-color: #388E3C; color: white; border-radius: 4px; padding: 6px 12px; font-weight: bold; } QPushButton:hover { background-color: #66BB6A; }")
        
        delete = QPushButton("🗑 Удалить")
        delete.setStyleSheet("QPushButton { background-color: #D32F2F; color: white; border-radius: 4px; padding: 6px 12px; font-weight: bold; } QPushButton:hover { background-color: #EF5350; }")
        
        close = QPushButton("Закрыть")
        close.setStyleSheet("QPushButton { background-color: #455A64; color: white; border-radius: 4px; padding: 6px 20px; } QPushButton:hover { background-color: #78909C; }")
        
        actions.addWidget(save)
        actions.addWidget(delete)
        actions.addStretch(1)
        actions.addWidget(close)
        layout.addLayout(actions)

        def save_comment():
            value = editor.toPlainText().strip()
            conn = self.db._connect()
            try:
                conn.execute("UPDATE conclusions SET comment=? WHERE id=?", (value or None, self.report_id))
                conn.commit()
                self.comment = value
                QMessageBox.information(dialog, "Успешно", "Комментарий сохранён.")
                self._fill_table()
            finally:
                conn.close()

        def delete_comment():
            if QMessageBox.question(dialog, "Подтверждение", "Удалить комментарий?") == QMessageBox.StandardButton.Yes:
                conn = self.db._connect()
                try:
                    conn.execute("UPDATE conclusions SET comment=NULL WHERE id=?", (self.report_id,))
                    conn.commit()
                    self.comment = ""
                    editor.clear()
                    QMessageBox.information(dialog, "Успешно", "Комментарий удалён.")
                    self._fill_table()
                finally:
                    conn.close()

        save.clicked.connect(save_comment)
        delete.clicked.connect(delete_comment)
        close.clicked.connect(dialog.accept)
        dialog.exec()

    # --- ВЛОЖЕНИЯ ---
    def _manage_attachments(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Вложения")
        dialog.resize(600, 200)
        layout = QVBoxLayout(dialog)

        combo = QComboBox()
        combo.setMinimumWidth(400)
        layout.addWidget(combo)

        btn_layout = QHBoxLayout()
        
        btn_open = QPushButton("📂 Открыть")
        btn_open.setStyleSheet("QPushButton { background-color: #1976D2; color: white; border-radius: 4px; padding: 6px 12px; font-weight: bold; } QPushButton:hover { background-color: #42A5F5; }")
        
        btn_upload = QPushButton("➕ Загрузить")
        btn_upload.setStyleSheet("QPushButton { background-color: #388E3C; color: white; border-radius: 4px; padding: 6px 12px; font-weight: bold; } QPushButton:hover { background-color: #66BB6A; }")
        
        btn_del = QPushButton("🗑 Удалить")
        btn_del.setStyleSheet("QPushButton { background-color: #D32F2F; color: white; border-radius: 4px; padding: 6px 12px; font-weight: bold; } QPushButton:hover { background-color: #EF5350; }")
        
        btn_layout.addWidget(btn_open)
        btn_layout.addWidget(btn_upload)
        btn_layout.addWidget(btn_del)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        btn_close = QPushButton("Закрыть")
        btn_close.setStyleSheet("QPushButton { background-color: #455A64; color: white; border-radius: 4px; padding: 6px 20px; } QPushButton:hover { background-color: #78909C; }")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close)

        def refresh():
            combo.clear()
            for att in self.attachments:
                combo.addItem(att[1], att[0])
            has_files = combo.count() > 0
            btn_open.setEnabled(has_files)
            btn_del.setEnabled(has_files)

        def open_att():
            att_id = combo.currentData()
            if not att_id: return
            
            conn = self.db._connect()
            try:
                row = conn.execute("SELECT file_data, filename FROM attachments WHERE id=?", (att_id,)).fetchone()
            finally:
                conn.close()
                
            if not row: return
            data, fname = row
            
            temp_path = os.path.join(tempfile.gettempdir(), f"uzk_{att_id}_{fname}")
            with open(temp_path, "wb") as f:
                f.write(data)
            try:
                os.startfile(temp_path)
            except Exception as e:
                QMessageBox.critical(dialog, "Ошибка", str(e))

        def upload_att():
            path, _ = QFileDialog.getOpenFileName(dialog, "Выберите файл", "", "Все файлы (*.*)")
            if not path: return
            fname = os.path.basename(path)
            with open(path, "rb") as f:
                data = f.read()
                
            conn = self.db._connect()
            try:
                conn.execute("INSERT INTO attachments (conclusion_id, filename, file_data) VALUES (?,?,?)", 
                             (self.report_id, fname, data))
                conn.commit()
                row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                self.attachments.append((row_id, fname))
            finally:
                conn.close()
            refresh()

        def delete_att():
            att_id = combo.currentData()
            if not att_id: return
            if not QMessageBox.question(dialog, "Удаление", "Удалить файл?"): return
            
            conn = self.db._connect()
            try:
                conn.execute("DELETE FROM attachments WHERE id=?", (att_id,))
                conn.commit()
                self.attachments = [a for a in self.attachments if a[0] != att_id]
            finally:
                conn.close()
            refresh()

        btn_open.clicked.connect(open_att)
        btn_upload.clicked.connect(upload_att)
        btn_del.clicked.connect(delete_att)

        refresh()
        dialog.exec()