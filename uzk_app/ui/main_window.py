# -*- coding: utf-8 -*-
"""Главное окно v4 (миграция prog.py + mixins tkinter → PyQt6)."""
from __future__ import annotations

import datetime
import copy
import json
import os

from PyQt6.QtCore import Qt, QTimer, QSettings, QPoint
from PyQt6.QtGui import QAction, QFont, QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QMenu, QStyle
)

from ..config import APP_TITLE, DB_NAME
from ..db import Database, DataError, DEFAULT_JOURNAL_NAME
from ..helpers import safe_text, timestamp_now
from ..journal_repo import get_latest_conclusion_ids, fetch_journal_rows
from ..pdf_engine import PdfEngine
from ..report_data import get_conclusion_report_data
from .app_ui import UiHost
from .dialogs import (
    LoginDialog, UserManagerDialog, critical, information, question, warning,
)
from .form_widget import ConclusionEditorDialog
from .journal_view import COLUMNS, JournalTable
from .report_view import ReportViewDialog
from .dict_editor import DictEditorDialog


class MainWindow(QMainWindow):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.user: dict | None = None
        self.is_admin = False
        self.is_master = False
        self._filter_columns: list[int] = []
        self.journal_tabs = {}
        
        self.setFont(QFont("Arial", 10))
        
        # ================= ТЕМНАЯ ТЕМА (DARK MODE) =================
        self.setStyleSheet("""
            QMainWindow, QDialog { background-color: #2b2b2b; color: #f2f2f2; }
            QWidget { background-color: #2b2b2b; color: #f2f2f2; font-family: "Segoe UI", Arial, sans-serif; font-size: 10pt; }
            QGroupBox { border: 1px solid #444; border-radius: 5px; margin-top: 15px; font-weight: bold; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 5px; left: 10px; color: #e0e0e0; }
            QTabWidget::pane { border: 1px solid #444; background-color: #2b2b2b; }
            QTabBar::tab { background-color: #3c3f41; color: #a9b7c6; border: 1px solid #444; padding: 8px 20px; border-top-left-radius: 4px; border-top-right-radius: 4px; margin-right: 2px; }
            QTabBar::tab:selected { background-color: #2b2b2b; color: #ffffff; border-bottom-color: #2b2b2b; }
            QTabBar::tab:hover:!selected { background-color: #4c5052; }
            QLineEdit, QComboBox, QDateEdit, QTextEdit, QSpinBox, QDoubleSpinBox { background-color: #3c3f41; color: #f2f2f2; border: 1px solid #555; border-radius: 6px; padding: 4px 6px; selection-background-color: #214283; }
            QComboBox { padding-right: 30px; }
            QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTextEdit:focus { border: 1px solid #5c9bd1; }
            QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled, QTextEdit:disabled { background-color: #2b2b2b; color: #666; }
            QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 24px; border: none; background-color: #E66868; border-radius: 6px; margin: 2px; }
            QComboBox::down-arrow { image: none; }
            QComboBox QAbstractItemView { background-color: #3c3f41; color: #f2f2f2; selection-background-color: #214283; border: 1px solid #555; border-radius: 6px; }
            QPushButton { background-color: #4c5052; color: #f2f2f2; border: 1px solid #555; border-radius: 4px; padding: 6px 12px; min-height: 24px; }
            QPushButton:hover { background-color: #5c6062; border: 1px solid #666; }
            QPushButton:pressed { background-color: #3c3f41; }
            QPushButton:disabled { background-color: #333; color: #777; border: 1px solid #444; }
            QScrollArea { border: none; background-color: transparent; }
            QScrollBar:vertical { border: none; background: #2b2b2b; width: 12px; margin: 0px; }
            QScrollBar::handle:vertical { background: #555; min-height: 20px; border-radius: 6px; }
            QScrollBar::handle:vertical:hover { background: #666; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            QScrollBar:horizontal { border: none; background: #2b2b2b; height: 12px; margin: 0px; }
            QScrollBar::handle:horizontal { background: #555; min-width: 20px; border-radius: 6px; }
            QScrollBar::handle:horizontal:hover { background: #666; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
            QTableWidget, QTreeWidget, QListWidget { background-color: #1e1e1e; color: #f2f2f2; alternate-background-color: #292929; border: 1px solid #444; border-radius: 6px; gridline-color: #444; }
            QHeaderView::section { background-color: #333333; color: #f2f2f2; padding: 5px; font-weight: 600; border: 1px solid #4a4a4a; }
            
            /* ГАЛОЧКИ */
            QCheckBox { spacing: 5px; }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #555;
                background-color: #3c3f41;
                border-radius: 3px;
            }
            QCheckBox::indicator:hover {
                border: 1px solid #5c9bd1;
            }
            QCheckBox::indicator:checked {
                background-color: #5c9bd1;
                border: 1px solid #5c9bd1;
                image: url(:/qt-project.org/styles/commonstyle/images/standardbutton-apply-16.png);
            }
            
            QMenuBar { background-color: #2b2b2b; color: #f2f2f2; }
            QMenuBar::item:selected { background-color: #3c3f41; }
            QMenu { background-color: #3c3f41; color: #f2f2f2; border: 1px solid #555; border-radius: 6px; }
            QMenu::item:selected { background-color: #214283; }
            QStatusBar { background-color: #2b2b2b; color: #aaa; }
        """)
        # ===========================================================

        self.ui_host = UiHost(self)
        self.pdf = PdfEngine(db, self.ui_host)

        self.setWindowTitle(APP_TITLE)
        
        self._build_menu()
        self._build_central()
        self.statusBar().showMessage("Готов")

    def _build_menu(self):
        mb = self.menuBar()
        act_logs = QAction("📊 Журнал действий", self)
        act_logs.triggered.connect(self.open_log_viewer)
        mb.addAction(act_logs)

        act_switch = QAction("👤 Сменить пользователя", self)
        act_switch.triggered.connect(self.switch_user)
        mb.addAction(act_switch)

        act_dicts = QAction("⚙️ Управление списками", self)
        act_dicts.triggered.connect(self.open_dict_editor)
        mb.addAction(act_dicts)

    def _build_central(self):
        self.notebook = QTabWidget()
        self.editor = ConclusionEditorDialog(self, self.db, journals=self.journals())
        self.editor.submitted.connect(self._save_editor)
        self.editor.import_requested.connect(self.import_excel)
        self.notebook.addTab(self.editor, "📝 Регистрация заключения")

        self.setCentralWidget(self.notebook)
        self.rebuild_journal_tabs()

    def rebuild_journal_tabs(self):
        journals = self.journals()
        
        for name in list(self.journal_tabs.keys()):
            if name not in journals:
                idx = self.notebook.indexOf(self.journal_tabs[name]['widget'])
                if idx >= 0:
                    self.notebook.removeTab(idx)
                del self.journal_tabs[name]
                
        for name in journals:
            if name not in self.journal_tabs:
                self._build_journal_tab(name)
                
        self.reload_journal()

    def _build_journal_tab(self, journal_name):
        page = QWidget()
        layout = QVBoxLayout(page)
        toolbar = QHBoxLayout()
        
        b_refresh = QPushButton("🔄 Обновить")
        b_refresh.setStyleSheet("background-color: #1976D2; color: white; padding: 5px 12px; border-radius: 4px; font-weight: bold; border: none;")
        b_refresh.clicked.connect(lambda: self.reload_journal(journal_name))
        toolbar.addWidget(b_refresh)
        
        b_sign = QPushButton("📝 Подписать")
        b_sign.setStyleSheet("background-color: #388E3C; color: white; padding: 5px 12px; border-radius: 4px; font-weight: bold; border: none;")
        b_sign.clicked.connect(lambda: self.sign_selected(journal_name))
        toolbar.addWidget(b_sign)
        
        b_all = QPushButton("📄 Экспорт в PDF")
        b_all.setStyleSheet("background-color: #F57C00; color: white; padding: 5px 12px; border-radius: 4px; font-weight: bold; border: none;")
        b_all.clicked.connect(lambda: self.export_journal_pdf(journal_name))
        toolbar.addWidget(b_all)
        
        toolbar.addWidget(QLabel("Поиск:"))
        search_edit = QLineEdit()
        search_edit.setPlaceholderText("Введите запрос для поиска...")
        search_edit.returnPressed.connect(lambda: self.reload_journal(journal_name))
        search_edit.setMinimumWidth(250)
        
        action_settings = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView), "Настройки поиска", self)
        action_settings.triggered.connect(lambda _, w=search_edit: self.open_column_filter_dialog(w))
        search_edit.addAction(action_settings, QLineEdit.ActionPosition.TrailingPosition)
        
        action_clear = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogResetButton), "Очистить поиск", self)
        def clear_search():
            search_edit.clear()
            self.reload_journal(journal_name)
        action_clear.triggered.connect(clear_search)
        search_edit.addAction(action_clear, QLineEdit.ActionPosition.TrailingPosition)

        action_search = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView), "Найти", self)
        action_search.triggered.connect(lambda: self.reload_journal(journal_name))
        search_edit.addAction(action_search, QLineEdit.ActionPosition.LeadingPosition)
        
        toolbar.addWidget(search_edit)
        
        toolbar.addWidget(QLabel("(Двойной клик для просмотра подробностей)"))
        toolbar.addStretch()
        layout.addLayout(toolbar)
        
        table = JournalTable()
        table.doubleClicked.connect(lambda _, t=table: self.open_report_view_from_table(t))
        
        table.setSortingEnabled(False)
        table.horizontalHeader().setSortIndicatorShown(False)
        table.horizontalHeader().setSectionsClickable(False)
        
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(lambda pos, t=table: self._show_journal_context_menu(pos, t))
        
        layout.addWidget(table, 1)
        
        count_label = QLabel("Записей: 0")
        layout.addWidget(count_label)
        
        self.notebook.addTab(page, f"📋 {journal_name}")
        self.journal_tabs[journal_name] = {
            'widget': page, 'table': table, 'search_edit': search_edit, 'count_label': count_label
        }

    def _show_journal_context_menu(self, pos, table):
        index = table.indexAt(pos)
        if not index.isValid():
            return
            
        table.setCurrentIndex(index)
        
        menu = QMenu(self)
        delete_action = menu.addAction("🗑 Удалить выбранное")
        action = menu.exec(table.viewport().mapToGlobal(pos))
        if action == delete_action:
            self.delete_selected_from_table(table)

    def journals(self) -> list[str]:
        return self.db.get_journals()

    def reload_journal(self, journal_name=None):
        if journal_name is None:
            for name in self.journal_tabs:
                self.reload_journal(name)
            return
            
        info = self.journal_tabs.get(journal_name)
        if not info:
            return
            
        table = info['table']
        needle = info['search_edit'].text().strip().casefold()
        
        try:
            conn = self.db._connect()
            try:
                ids = get_latest_conclusion_ids(conn, journal_name)
                rows = fetch_journal_rows(conn, ids)
            finally:
                conn.close()
        except Exception as e:
            critical(self, "Ошибка БД", str(e))
            return

        out = []
        for (rid, num_date, izdeliye, detal, order_num, object_kontr,
             quality, fio, sign_status, record_num) in rows:
            row = {
                "report_num_date": num_date or "",
                "izdeliye": izdeliye or "",
                "detal": detal or "",
                "order_num": order_num or "",
                "object_kontr": object_kontr or "",
                "quality": quality or "",
                "fio_list": fio or "",
                "sign_status": sign_status or "",
                "record_num": record_num or "",
            }
            values = [row[COLUMNS[i][0]] for i in self._filter_columns]
            if not self._filter_columns:
                values = [row[key] for key, _title, _width, _alignment in COLUMNS]
            if needle and needle not in " ".join(map(str, values)).casefold():
                continue
            report_num, date = "", ""
            if " (" in (num_date or "") and (num_date or "").endswith(")"):
                report_num, date = num_date[:-1].split(" (", 1)
            out.append({
                "id": rid, "report_num": report_num, "date": date,
                "record_num": record_num, "izdeliye": izdeliye,
                "detal": detal, "order_num": order_num,
                "object_kontr": object_kontr, "quality": quality,
                "fio": fio, "fio_list": fio, "sign_status": sign_status,
            })
            
        table.load_rows(out)
        info['count_label'].setText(f"Записей: {len(out)}")
        
        if self.notebook.currentWidget() == info['widget']:
            self.statusBar().showMessage(f"Журнал «{journal_name}» — {len(out)} актуальных заключений")
            self.setWindowTitle(f"{APP_TITLE} — {self.user['fio'] if self.user else 'Не авторизован'} — {journal_name}")

    def selected_id_from_table(self, table) -> int | None:
        row = table.current_row_dict()
        return row["id"] if row else None

    def open_report_view_from_table(self, table):
        report_id = self.selected_id_from_table(table)
        if report_id is None:
            return
        try:
            dlg = ReportViewDialog(self, self.db, report_id, self.pdf)
            dlg.edit_requested.connect(lambda _: self.edit_selected())
            dlg.exec()
            self.reload_journal()
        except Exception as exc:
            critical(self, "Ошибка загрузки заключения", str(exc))

    def _save_editor(self):
        g, meas = self.editor.general_data, self.editor.measurements_data
        try:
            for category, type_, serial in getattr(self, "_pending_import_equipment", []):
                self.db.insert_equipment_if_missing(category, type_, serial, g.get("method_kontr", "TOFD"))
            self._pending_import_equipment = []
            if self.editor.conclusion_id:
                rid = self.editor.conclusion_id
                old = self.db.load_old_conclusion_state(rid)
                from ..journal_repo import build_diff, format_diff_summary
                diff = build_diff(old, g, meas)
                summary = format_diff_summary(g, diff, is_new=False)
                self.db.save_conclusion(g, meas, conclusion_id=rid)
                self.db.set_conclusion_signature(rid, "")
                self.log_action("Изменение заключения", f"№{g['report_num']}: {summary}", diff_data=diff)
                cid = rid
            else:
                cid = self.db.save_conclusion(g, meas)
                self.log_action("Создание заключения", f"№{g['report_num']} журнал «{g['journal']}»")
            
            self.rebuild_journal_tabs()
            
            journal_name = g.get("journal") or DEFAULT_JOURNAL_NAME
            if journal_name in self.journal_tabs:
                self.notebook.setCurrentWidget(self.journal_tabs[journal_name]['widget'])
                table = self.journal_tabs[journal_name]['table']
                for i, row in enumerate(table.model_.rows):
                    if row.get("id") == cid:
                        table.selectRow(i)
                        break
                        
            self.editor.load_data(general={"journal": journal_name})
        except (DataError, Exception) as e:
            critical(self, "Ошибка сохранения", str(e))

    def edit_selected(self):
        if not self._require_user():
            return
        current_page = self.notebook.currentWidget()
        table = None
        for info in self.journal_tabs.values():
            if info['widget'] == current_page:
                table = info['table']
                break
                
        if not table:
            warning(self, "Внимание", "Откройте вкладку журнала и выберите запись.")
            return
            
        rid = self.selected_id_from_table(table)
        if rid is None:
            warning(self, "Внимание", "Выберите запись в таблице.")
            return
        old = self.db.load_old_conclusion_state(rid)
        if old is None:
            critical(self, "Ошибка", "Заключение не найдено в БД.")
            return
        self._pending_import_equipment = []
        self.editor.load_data(
            general=old.get("general", {}),
            measurements=old.get("measurements", []), conclusion_id=rid)
        self.notebook.setCurrentIndex(0)

    def delete_selected(self):
        current_page = self.notebook.currentWidget()
        table = None
        for info in self.journal_tabs.values():
            if info['widget'] == current_page:
                table = info['table']
                break
        if not table:
            return
        self.delete_selected_from_table(table)

    def delete_selected_from_table(self, table):
        if not self._require_user():
            return
        rid = self.selected_id_from_table(table)
        if rid is None:
            warning(self, "Внимание", "Выберите запись в таблице.")
            return
        row = table.current_row_dict()
        if not question(self, "Подтверждение", f"Удалить заключение №{row['report_num']}?"):
            return
        try:
            self.db.delete_conclusion(rid)
            self.log_action("Удаление заключения", f"id={rid}")
            self.rebuild_journal_tabs()
        except Exception as e:
            critical(self, "Ошибка", str(e))

    def sign_selected(self, journal_name):
        if not self._require_user():
            return
        info = self.journal_tabs.get(journal_name)
        if not info: return
        
        row_data = info['table'].current_row_dict()
        if not row_data:
            warning(self, "Внимание", "Выберите запись в таблице.")
            return
            
        rid = row_data["id"]
        fio = self.user["fio"]
        
        valid_fios_str = row_data.get("fio", "")
        valid_fios = [f.strip() for f in valid_fios_str.split(",") if f.strip()]
        
        if fio not in valid_fios:
            warning(self, "Отказ", f"Вы не можете подписать это заключение, так как ваше ФИО ({fio}) отсутствует в списке дефектоскопистов данного заключения.")
            return

        try:
            signed = self.db.get_conclusion_signature(rid) or []
            if fio in signed:
                information(self, "Информация", f"Вы (ФИО: {fio}) уже подписали это заключение!")
                return
            signed.append(fio)
            self.db.set_conclusion_signature(rid, json.dumps(signed, ensure_ascii=False))
            self.log_action("Подписание заключения", f"id={rid}, {fio}")
            self.reload_journal(journal_name)
            information(self, "Успешно", f"Заключение подписано! Ваше ФИО ({fio}) добавлено в список подписавших.")
        except Exception as e:
            critical(self, "Ошибка", str(e))

    def open_column_filter_dialog(self, anchor_widget=None):
        dialog = QDialog(self)
        dialog.setWindowTitle("Настройки поиска")
        dialog.setMinimumWidth(200)
        
        layout = QVBoxLayout(dialog)
        for index, (_key, title, _width, _alignment) in enumerate(COLUMNS):
            check = QCheckBox(title)
            check.setChecked(index in self._filter_columns)
            check.toggled.connect(lambda checked, i=index: self._toggle_filter_column(i, checked))
            layout.addWidget(check)
            
        layout.addSpacing(10)
        close_button = QPushButton("Закрыть")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        
        if anchor_widget:
            pos = anchor_widget.mapToGlobal(QPoint(anchor_widget.width() - dialog.width(), anchor_widget.height()))
            if dialog.width() < 50:
                pos = anchor_widget.mapToGlobal(QPoint(0, anchor_widget.height()))
            dialog.move(pos)
            
        dialog.exec()

    def _toggle_filter_column(self, index, checked):
        if checked and index not in self._filter_columns:
            self._filter_columns.append(index)
        elif not checked and index in self._filter_columns:
            self._filter_columns.remove(index)
        self.rebuild_journal_tabs()

    def import_excel(self):
        if not self._require_user():
            return
        path = self.ui_host.open_excel_path()
        if not path:
            return
        try:
            from ..excel_import import parse_excel, build_measurements, ExcelParseError
            parsed = parse_excel(path)
            if not parsed:
                raise ExcelParseError("Файл Excel не содержит данных.")
            
            self.editor._commit_current()
            
            existing_measurements = copy.deepcopy(self.editor.model.measurements)
            current_object = self.editor.gen_edits["object_kontr"].text().strip()
            
            new_measurements, _ = build_measurements(
                parsed, current_object_value="", 
                existing_measurements=[]
            )
            
            final_measurements = existing_measurements + new_measurements

            all_objs = set()
            if current_object:
                for o in current_object.split(","):
                    if o.strip(): all_objs.add(o.strip())
            
            parsed_obj = parsed["general"].get("object_kontr", "")
            if parsed_obj:
                for o in str(parsed_obj).split(","):
                    if o.strip(): all_objs.add(o.strip())

            for m in final_measurements:
                for d in m.get("defects", []):
                    for o in str(d.get("defect_object", "")).split(","):
                        if o.strip(): all_objs.add(o.strip())

            for category, type_, serial in parsed.get("equipment_to_add", []):
                self.db.insert_equipment_if_missing(category, type_, serial, parsed.get("method", "TOFD"))

            general = {}
            for key, widget in self.editor.gen_edits.items():
                general[key] = (widget.currentText().strip() if isinstance(widget, QComboBox) else widget.text().strip())
            
            general["object_kontr"] = ", ".join(sorted(all_objs))
            
            if not existing_measurements:
                general.update({
                    "izdeliye": parsed["general"]["izdeliye"],
                    "detal": parsed["general"]["detal"],
                    "thickness": parsed["general"]["thickness"],
                    "method_kontr": parsed.get("method", ""),
                    "journal": self.notebook.tabText(self.notebook.currentIndex()).replace("📋 ", ""),
                })
                
            self._pending_import_equipment = []
            self.editor.load_data(
                general=general,
                measurements=final_measurements
            )
            self.notebook.setCurrentIndex(0)
            
            information(self, "Импорт Excel", 
                        f"Успешно загружено каналов: {len(new_measurements)}\n"
                        f"Итого каналов в форме: {len(final_measurements)}\n"
                        f"Объекты контроля: {general['object_kontr']}")
            
        except ExcelParseError as e:
            critical(self, "Ошибка импорта", str(e))
        except Exception as e:
            critical(self, "Ошибка импорта", f"Не удалось прочитать файл:\n{e}")

    def export_journal_pdf(self, journal_name):
        conn = self.db._connect()
        try:
            ids = get_latest_conclusion_ids(conn, journal_name)
        finally:
            conn.close()
        if not ids:
            warning(self, "Внимание", "В журнале нет заключений для экспорта.")
            return
        self.pdf.export_journal_to_pdf(journal_name, ids)

    def export_selected_pdf(self):
        current_page = self.notebook.currentWidget()
        table = None
        for info in self.journal_tabs.values():
            if info['widget'] == current_page:
                table = info['table']
                break
        if not table: return
            
        rid = self.selected_id_from_table(table)
        if rid is None:
            warning(self, "Внимание", "Выберите запись в таблице.")
            return
        report_data, attachments, journal, comment = get_conclusion_report_data(self.db, rid)
        if not report_data:
            critical(self, "Ошибка", "Нет данных для экспорта.")
            return
        self.pdf.export_conclusion_to_pdf(report_data, comment)

    def open_dict_editor(self):
        DictEditorDialog(self, self.db).exec()
        self.rebuild_journal_tabs()

    def open_log_viewer(self):
        from .log_viewer import LogViewerDialog
        LogViewerDialog(self, self.db).exec()

    def open_user_manager(self):
        if not self.is_admin:
            warning(self, "Внимание", "Только администратор.")
            return
        UserManagerDialog(self, self.db, self.user["fio"], True).exec()

    def _require_user(self) -> bool:
        if self.user is None:
            warning(self, "Внимание", "Необходим вход в систему.")
            self.login()
        return self.user is not None

    def switch_user(self):
        if self.user:
            self.save_user_layout()
            self.log_action("Выход из системы")
        self.user = None
        self.is_admin = False
        self.is_master = False
        self.login()

    def _toggle_master_access(self):
        from PyQt6.QtWidgets import QInputDialog
        password, accepted = QInputDialog.getText(self, "Мастер-доступ", "Мастер-пароль:", QLineEdit.EchoMode.Password)
        if not accepted:
            return False
        if not self.db.verify_master_password(password):
            warning(self, "Ошибка", "Неверный мастер-пароль.")
            return False
        self.user = {"id": None, "fio": "master", "login": "master", "is_admin": True}
        self.is_master = True
        self.is_admin = True
        self.setWindowTitle(f"{APP_TITLE} — master")
        return True

    def log_action(self, action: str, details: str = "", diff_data=None):
        try:
            if self.is_master:
                self.db.log_action_anonymous(action, details, diff_data)
            elif self.user:
                self.db.log_action(action, details, diff_data, user=self.user)
            else:
                self.db.log_action_anonymous(action, details, diff_data)
        except Exception:
            pass

    def login(self) -> bool:
        while True:
            users = [u["fio"] for u in self.db.get_loginable_users()]
            dlg = LoginDialog(self, users, self.db)
            if dlg.exec() != LoginDialog.DialogCode.Accepted:
                return False
            if dlg.master_access:
                self.user = {"id": None, "login": "master", "fio": "master", "is_admin": True}
                self.is_admin = True
                self.is_master = True
                self.setWindowTitle(f"{APP_TITLE} — master")
                self.statusBar().showMessage("Вошёл: master")
                QTimer.singleShot(0, self.open_user_manager)
                return True
            user = self.db.authenticate(dlg.selected_user, dlg.password)
            if user:
                self.user = user
                self.is_admin = bool(user.get("is_admin"))
                self.is_master = False
                self.setWindowTitle(f"{APP_TITLE} — {user['fio']}" + (" (админ)" if self.is_admin else ""))
                self.log_action("Вход в систему")
                self.statusBar().showMessage(f"Вошёл: {user['fio']}")
                if user.get("must_change_password"):
                    if not self._force_change_password(user):
                        self.user = None
                        continue
                    self.user = self.db.get_user_by_id(user["id"])
                
                self.restore_user_layout()
                return True
            critical(self, "Ошибка", "Неверный пароль!")

    def _force_change_password(self, user):
        from PyQt6.QtWidgets import QInputDialog
        information(self, "Требуется смена пароля", "Ваш пароль был сброшен.\n\nДля продолжения работы необходимо задать новый пароль.\nПароль по умолчанию (1234) использовать нельзя.\nМинимальная длина — 4 символа.")
        while True:
            password, accepted = QInputDialog.getText(self, "Требуется смена пароля", "Новый пароль:", QLineEdit.EchoMode.Password)
            if not accepted: return False
            if len(password) < 4 or password == "1234":
                warning(self, "Ошибка", "Пароль должен быть не менее 4 символов.\nПароль 1234 использовать нельзя.")
                continue
            confirm, accepted = QInputDialog.getText(self, "Требуется смена пароля", "Повторите новый пароль:", QLineEdit.EchoMode.Password)
            if not accepted: return False
            if password != confirm:
                warning(self, "Ошибка", "Пароли не совпадают.")
                continue
            self.db.change_user_password(user["id"], password)
            self.db.log_action_anonymous("CHANGE_PASSWORD", f"Пользователь {user['fio']} сменил пароль (после сброса)")
            return True

    def keyPressEvent(self, event):
        if (event.key() == Qt.Key.Key_P and event.modifiers() == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier) and self.user is None):
            self._toggle_master_access()
            return
        super().keyPressEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_logged_once", False):
            self._logged_once = True
            QTimer.singleShot(0, self._startup)

    def _startup(self):
        try:
            self.db.init_db()
        except Exception as e:
            critical(self, "Ошибка БД", f"Не удалось инициализировать базу:\n{e}")
            return
        
        self.hide()
        
        if not self.login():
            self.close()
            return
            
        self.showMaximized()
        self.rebuild_journal_tabs()

    def save_user_layout(self):
        if not self.user:
            return
        fio = self.user["fio"]
        settings = QSettings("UZK_App", "UZK_v4")
        
        if self.journal_tabs:
            first_table = next(iter(self.journal_tabs.values()))['table']
            settings.setValue(f"journal_header_state_{fio}", first_table.horizontalHeader().saveState())
            
        if self.editor:
            self.editor.save_layout(fio)

    def restore_user_layout(self):
        if not self.user:
            return
        fio = self.user["fio"]
        settings = QSettings("UZK_App", "UZK_v4")
        
        state = settings.value(f"journal_header_state_{fio}")
        if state:
            for info in self.journal_tabs.values():
                info['table'].horizontalHeader().restoreState(state)
                
        if self.editor:
            self.editor.restore_layout(fio)

    def closeEvent(self, event):
        if self.user:
            self.save_user_layout()
            self.log_action("Выход из системы")
        super().closeEvent(event)