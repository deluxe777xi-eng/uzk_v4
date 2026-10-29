# -*- coding: utf-8 -*-
"""Редакторы словарей, дефектоскопов и оборудования."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QTabWidget, QVBoxLayout,
    QWidget, QTreeWidget, QTreeWidgetItem, QHeaderView
)

from ..db import Database, DataError
from ..helpers import safe_text


DICT_KEYS = [
    ("journal_list", "Журналы"),
    ("fio_list", "ФИО Дефектоскопистов"),
    ("sample_list", "Обозначения образцов"),
    ("scanner_list", "Типы сканирующих устройств"),
]


class SimpleDictTab(QWidget):
    """Одноколоночный редактируемый список dict_lists."""

    def __init__(self, db: Database, key: str, title: str, readonly=False):
        super().__init__()
        self.db = db
        self.key = key
        self.readonly = readonly
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>{title}</b>"))
        self.lst = QListWidget()
        self.lst.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.lst.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.lst.model().rowsMoved.connect(lambda *_: self.save_order())
        layout.addWidget(self.lst, 1)

        row = QHBoxLayout()
        for label, slot in (
            ("➕ Добавить", self.add_value),
            ("✏️ Переименовать", self.rename_value),
            ("🗑 Удалить", self.del_value),
        ):
            button = QPushButton(label)
            button.setVisible(not readonly)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        self.reload()

    def reload(self):
        self.lst.clear()
        self.lst.addItems(self.db.get_dict_values(self.key))

    def _values(self):
        return [self.lst.item(i).text() for i in range(self.lst.count())]

    def save_order(self):
        if not self.readonly:
            self.db.replace_dict_values(self.key, self._values())

    def add_value(self):
        value, accepted = QInputDialog.getText(
            self, "Добавить", "Введите новое значение:")
        value = safe_text(value)
        if accepted and value:
            values = self._values()
            if value not in values:
                values.append(value)
                self.db.replace_dict_values(self.key, values)
                self.reload()

    def rename_value(self):
        index = self.lst.currentRow()
        if index < 0:
            return
        old_value = self.lst.item(index).text()
        value, accepted = QInputDialog.getText(
            self, "Переименовать", "Новое значение:", text=old_value)
        value = safe_text(value)
        if not accepted or not value:
            return
        values = self._values()
        values[index] = value
        self.db.replace_dict_values(self.key, values)
        self.reload()

    def del_value(self):
        index = self.lst.currentRow()
        if index < 0:
            return
        values = self._values()
        del values[index]
        self.db.replace_dict_values(self.key, values)
        self.reload()


class DefectoscopeTab(QWidget):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Список Дефектоскопов</b>"))
        self.lst = QListWidget()
        layout.addWidget(self.lst, 1)
        row = QHBoxLayout()
        for label, slot in (
            ("➕ Добавить", self.add),
            ("✏️ Переименовать", self.edit),
            ("🗑 Удалить", self.delete),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        self.reload()

    def reload(self):
        self.lst.clear()
        for record in self.db.get_defectoscope_records():
            item = QListWidgetItem(
                f"{record['type']}  {record['serial'] or ''}".strip())
            item.setData(Qt.ItemDataRole.UserRole, record)
            self.lst.addItem(item)

    def current(self):
        item = self.lst.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def add(self):
        type_, accepted = QInputDialog.getText(self, "Новый тип", "Введите название нового типа:")
        if not accepted or not safe_text(type_):
            return
        try:
            self.db.add_defectoscope(safe_text(type_), "")
            self.reload()
        except DataError as exc:
            QMessageBox.critical(self, "Ошибка", str(exc))

    def edit(self):
        selected = self.current()
        if not selected:
            return
        type_, accepted = QInputDialog.getText(
            self, "Переименовать", "Тип оборудования:",
            text=selected["type"])
        if not accepted:
            return
        serial, accepted = QInputDialog.getText(
            self, "Переименовать", "Заводской номер:",
            text=selected["serial"] or "")
        if not accepted:
            return
        try:
            self.db.update_defectoscope(
                selected["id"], safe_text(type_), safe_text(serial))
            self.reload()
        except DataError as exc:
            QMessageBox.critical(self, "Ошибка", str(exc))

    def delete(self):
        selected = self.current()
        if not selected:
            return
        if QMessageBox.question(
                self, "Подтверждение",
                f"Удалить «{selected['type']} {selected['serial']}»?") != \
                QMessageBox.StandardButton.Yes:
            return
        self.db.delete_defectoscope(selected["id"])
        self.reload()


class EquipmentTab(QWidget):
    """Список оборудования в виде дерева (как в V3)."""

    def __init__(self, db: Database, category: str, title: str):
        super().__init__()
        self.db = db
        self.category = category
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>{title}</b>"))
        
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Тип / Зав. номер", "Метод", "Привязка"])
        self.tree.setColumnWidth(0, 250)
        self.tree.setColumnWidth(1, 80)
        self.tree.setColumnWidth(2, 200)
        self.tree.setAlternatingRowColors(True)
        layout.addWidget(self.tree, 1)
        
        row = QHBoxLayout()
        for label, slot in (
            ("➕ Добавить тип", self.add_type),
            ("➕ Добавить номер", self.add_serial),
            ("✏️ Изменить", self.edit),
            ("🗑 Удалить", self.delete),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        self.reload()

    def reload(self):
        self.tree.clear()
        rows = self.db.get_equipment_rows(self.category)
        grouped = {}
        for r in rows:
            grouped.setdefault(r['type'], []).append(r)
            
        for t, children in grouped.items():
            parent = QTreeWidgetItem(self.tree, [t, "", ""])
            parent.setData(0, Qt.ItemDataRole.UserRole, {"is_group": True, "type": t})
            for c in children:
                child = QTreeWidgetItem(parent, [c['serial'] or "", c['method'], c['device_str']])
                child.setData(0, Qt.ItemDataRole.UserRole, c)
            parent.setExpanded(True)

    def add_type(self):
        t, ok = QInputDialog.getText(self, "Новый тип", "Введите тип оборудования:")
        if ok and safe_text(t):
            try:
                self.db.save_equipment(self.category, None, safe_text(t), "", "TOFD", None, mode="add")
                self.reload()
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))

    def add_serial(self):
        item = self.tree.currentItem()
        if not item:
            QMessageBox.warning(self, "Внимание", "Выберите тип, к которому нужно добавить номер.")
            return
            
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data.get("is_group"):
            target_type = data["type"]
        else:
            target_type = self.tree.parent(item).text(0)

        s, ok = QInputDialog.getText(self, "Новый номер", f"Зав. номер для '{target_type}':")
        if not ok:
            return
            
        m, ok = QInputDialog.getItem(self, "Метод", "Метод контроля:", ["TOFD", "PAUT"], 0, False)
        if not ok:
            return
            
        accepted, device_ids = self._edit_device_ids(None)
        if not accepted:
            return
            
        try:
            self.db.save_equipment(self.category, None, target_type, safe_text(s), m, device_ids, mode="add")
            self.reload()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def edit(self):
        item = self.tree.currentItem()
        if not item:
            return
            
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data.get("is_group"):
            old_t = data["type"]
            new_t, ok = QInputDialog.getText(self, "Изменить тип", "Новый тип:", text=old_t)
            if not ok or not safe_text(new_t) or new_t == old_t:
                return
            try:
                # Обновляем тип для всех записей этого типа
                for i in range(item.childCount()):
                    child = item.child(i)
                    c_data = child.data(0, Qt.ItemDataRole.UserRole)
                    self.db.save_equipment(self.category, c_data["id"], safe_text(new_t), c_data.get("serial") or "", c_data.get("method"), c_data.get("device_ids"), mode="edit")
                self.reload()
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))
        else:
            old_s = data.get("serial") or ""
            new_s, ok = QInputDialog.getText(self, "Изменить номер", "Новый зав. номер:", text=old_s)
            if not ok:
                return
                
            m, ok = QInputDialog.getItem(self, "Метод", "Метод контроля:", ["TOFD", "PAUT"], 0 if data.get("method") == "TOFD" else 1, False)
            if not ok:
                return
                
            accepted, device_ids = self._edit_device_ids(data.get("device_ids"))
            if not accepted:
                return
                
            try:
                self.db.save_equipment(self.category, data["id"], data["type"], safe_text(new_s), m, device_ids, mode="edit")
                self.reload()
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))

    def delete(self):
        item = self.tree.currentItem()
        if not item:
            return
            
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data.get("is_group"):
            if QMessageBox.question(self, "Удаление", f"Удалить тип '{data['type']}' и все его номера?") == QMessageBox.StandardButton.Yes:
                for i in range(item.childCount()):
                    child = item.child(i)
                    self.db.delete_equipment_by_id(child.data(0, Qt.ItemDataRole.UserRole)["id"])
                self.reload()
        else:
            if QMessageBox.question(self, "Удаление", f"Удалить зав. номер '{data['serial']}'?") == QMessageBox.StandardButton.Yes:
                self.db.delete_equipment_by_id(data["id"])
                self.reload()

    def _edit_device_ids(self, initial=None):
        dialog = QDialog(self)
        dialog.setWindowTitle("Привязка к дефектоскопам")
        layout = QVBoxLayout(dialog)
        selected = {part.strip() for part in (initial or "").split(",") if part.strip()}
        checks = []
        for device in self.db.get_defectoscope_records():
            check = QCheckBox(f"{device['type']} {device['serial'] or ''}".strip())
            check.setProperty("device_id", device["id"])
            check.setChecked(str(device["id"]) in selected)
            checks.append(check)
            layout.addWidget(check)
        result = {"all": False}
        buttons = QHBoxLayout()
        all_button = QPushButton("Для всех")
        all_button.clicked.connect(lambda: (result.update(all=True), dialog.accept()))
        accept = QPushButton("ОК")
        accept.clicked.connect(dialog.accept)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(dialog.reject)
        buttons.addWidget(all_button)
        buttons.addStretch(1)
        buttons.addWidget(accept)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False, initial
        if result["all"]:
            return True, None
        return True, ",".join(str(check.property("device_id")) for check in checks if check.isChecked()) or None


class DictEditorDialog(QDialog):
    def __init__(self, parent, db: Database, selected_key=None, readonly_keys=None):
        super().__init__(parent)
        self.setWindowTitle("Справочники")
        self.resize(750, 550)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        readonly_keys = readonly_keys or set()
        for key, title in DICT_KEYS:
            self.tabs.addTab(SimpleDictTab(db, key, title, readonly=key in readonly_keys), title)
        self.tabs.addTab(DefectoscopeTab(db), "Дефектоскопы")
        self.tabs.addTab(EquipmentTab(db, "probe", "Преобразователи"), "Преобразователи")
        self.tabs.addTab(EquipmentTab(db, "prism", "Призмы"), "Призмы")
        if selected_key:
            for index, (key, _title) in enumerate(DICT_KEYS):
                if key == selected_key:
                    self.tabs.setCurrentIndex(index)
                    break
        layout.addWidget(self.tabs, 1)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        layout.addWidget(close)