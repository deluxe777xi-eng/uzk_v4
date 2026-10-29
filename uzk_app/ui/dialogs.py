# -*- coding: utf-8 -*-
"""PyQt6-диалоги авторизации и администрирования."""
from __future__ import annotations

import os
import sqlite3

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent, QPixmap, QIcon
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QVBoxLayout, QWidget, QSizePolicy, QStyle
)

from ..db import Database, DataError
from ..security import _hash_password


def _parent(parent):
    if isinstance(parent, QWidget):
        return parent
    for widget in QWidget.topLevelWidgets():
        if isinstance(widget, QMainWindow) and widget.isVisible():
            return widget
    return None


def information(parent, title, text):
    QMessageBox.information(_parent(parent), title, text)


def warning(parent, title, text):
    QMessageBox.warning(_parent(parent), title, text)


def critical(parent, title, text):
    QMessageBox.critical(_parent(parent), title, text)


def question(parent, title, text, yes_no=True) -> bool:
    buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    result = QMessageBox.question(_parent(parent), title, text, buttons,
                                  QMessageBox.StandardButton.No)
    return result == QMessageBox.StandardButton.Yes


def ask_text(parent, title, label, default="", password=False):
    echo = (QLineEdit.EchoMode.Password if password
            else QLineEdit.EchoMode.Normal)
    value, accepted = QInputDialog.getText(
        _parent(parent), title, label, echo, default)
    return (value, accepted) if accepted else (None, False)


class LoginDialog(QDialog):
    """Выбор ФИО, ввод пароля и мастер-доступ по Ctrl+Shift+P."""

    def __init__(self, parent=None, users=None, db=None):
        super().__init__(parent)
        self.db = db
        self.selected_user = None
        self.password = ""
        self.master_access = False
        self.setWindowTitle("Авторизация")
        self.setModal(True)
        self.setFixedSize(420, 340)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)
        
        # ИСПРАВЛЕНИЕ: Используем стандартную системную иконку "Щит" (Security)
        self.setWindowIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_VistaShield))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)

        # Заголовок
        title = QLabel("Вход в систему УЗК")
        title.setStyleSheet("font-size: 16pt; font-weight: bold; margin-bottom: 10px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # === ПОЛЬЗОВАТЕЛЬ ===
        user_layout = QHBoxLayout()
        self.fio_combo = QComboBox()
        self.fio_combo.setEditable(False)
        self.fio_combo.setFixedHeight(36)
        self.fio_combo.addItems(
            [user for user in (users or []) if user != "Администратор"])
        user_layout.addWidget(self.fio_combo, 1)

        self.add_user_button = QPushButton("➕")
        self.add_user_button.setFixedSize(36, 36)
        self.add_user_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.add_user_button.setToolTip("Добавить пользователя")
        self.add_user_button.setStyleSheet("""
            QPushButton {
                background-color: #3c3f41;
                border: 1px solid #555;
                border-radius: 4px;
                color: #f2f2f2;
                font-size: 12pt;
                padding: 0px;
            }
            QPushButton:hover { background-color: #4c5052; border: 1px solid #666; }
            QPushButton:pressed { background-color: #2b2b2b; }
        """)
        self.add_user_button.clicked.connect(self.add_user)
        user_layout.addWidget(self.add_user_button, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(user_layout)

        # === ПАРОЛЬ ===
        password_row = QHBoxLayout()
        self.pw_edit = QLineEdit()
        self.pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw_edit.setPlaceholderText("Пароль")
        self.pw_edit.setFixedHeight(36)
        self.pw_edit.returnPressed.connect(self._on_accept)
        password_row.addWidget(self.pw_edit, 1)

        self.edit_user_button = QPushButton("✏️")
        self.edit_user_button.setFixedSize(36, 36)
        self.edit_user_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.edit_user_button.setToolTip("Редактировать профиль")
        self.edit_user_button.setEnabled(False)
        self.edit_user_button.setStyleSheet("""
            QPushButton {
                background-color: #3c3f41;
                border: 1px solid #555;
                border-radius: 4px;
                color: #f2f2f2;
                font-size: 12pt;
                padding: 0px;
            }
            QPushButton:hover { background-color: #4c5052; border: 1px solid #666; }
            QPushButton:pressed { background-color: #2b2b2b; }
            QPushButton:disabled { background-color: #2b2b2b; color: #666; border: 1px solid #444; }
        """)
        self.edit_user_button.clicked.connect(self.edit_user)
        password_row.addWidget(self.edit_user_button, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(password_row)

        self.pw_edit.textChanged.connect(self._check_edit_permission)
        self.fio_combo.currentTextChanged.connect(self._check_edit_permission)

        layout.addSpacing(5)

        # === ЗАБЫЛИ ПАРОЛЬ ===
        forgot_layout = QHBoxLayout()
        forgot_layout.addStretch()
        self.forgot = QPushButton("Забыли пароль?")
        self.forgot.setCursor(Qt.CursorShape.PointingHandCursor)
        self.forgot.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #5c9bd1;
                text-decoration: underline;
                font-size: 10pt;
            }
            QPushButton:hover { color: #7ab3e3; }
        """)
        self.forgot.clicked.connect(lambda: information(
            self, "Забыли пароль?",
            "Обратитесь к администратору для сброса пароля."))
        forgot_layout.addWidget(self.forgot)
        forgot_layout.addStretch()
        layout.addLayout(forgot_layout)

        layout.addStretch(1)

        # === КНОПКИ ВНИЗУ ===
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        
        login = QPushButton("Войти")
        login.setFixedSize(110, 36)
        login.setStyleSheet("""
            QPushButton {
                background-color: #5c9bd1; 
                color: white; 
                font-weight: bold;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #4a8bc2; }
            QPushButton:pressed { background-color: #3a7ba3; }
        """)
        login.setDefault(True)
        login.clicked.connect(self._on_accept)
        buttons.addWidget(login)

        cancel = QPushButton("Отмена")
        cancel.setFixedSize(110, 36)
        cancel.setStyleSheet("""
            QPushButton {
                background-color: #3c3f41;
                border: 1px solid #555;
                border-radius: 4px;
                color: #f2f2f2;
            }
            QPushButton:hover { background-color: #4c5052; }
            QPushButton:pressed { background-color: #2b2b2b; }
        """)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def _check_edit_permission(self, *_args):
        user = self.db.get_user_by_fio(self.fio_combo.currentText())
        self.edit_user_button.setEnabled(bool(
            user and self.pw_edit.text()
            and self.db.authenticate(user["fio"], self.pw_edit.text())))

    def _on_accept(self, *_args):
        if not self.fio_combo.currentText():
            critical(self, "Ошибка", "Выберите пользователя!")
            return
        self.selected_user = self.fio_combo.currentText()
        self.password = self.pw_edit.text()
        user = self.db.get_user_by_fio(self.selected_user)
        if not user:
            critical(self, "Ошибка", "Пользователь не найден!")
            return
        if not self.db.authenticate(self.selected_user, self.password):
            critical(self, "Ошибка", "Неверный пароль!")
            self.pw_edit.clear()
            self.pw_edit.setFocus()
            self.edit_user_button.setEnabled(False)
            return
        self.accept()

    def keyPressEvent(self, event: QKeyEvent):
        master_hotkey = (Qt.KeyboardModifier.ControlModifier
                         | Qt.KeyboardModifier.ShiftModifier)
        if event.key() == Qt.Key.Key_P and event.modifiers() == master_hotkey:
            password, accepted = QInputDialog.getText(
                self, "Мастер-доступ", "Мастер-пароль:",
                QLineEdit.EchoMode.Password)
            if accepted:
                if self.db.verify_master_password(password):
                    self.master_access = True
                    self.selected_user = "master"
                    self.password = ""
                    self.accept()
                else:
                    critical(self, "Ошибка", "Неверный мастер-пароль.")
            return
        super().keyPressEvent(event)

    def add_user(self):
        fio, accepted = QInputDialog.getText(self, "Добавить пользователя", "ФИО:")
        if not accepted or not fio.strip():
            return
        position, accepted = QInputDialog.getText(
            self, "Добавить пользователя", "Должность:")
        if not accepted:
            return
        password, accepted = QInputDialog.getText(
            self, "Добавить пользователя", "Пароль:",
            QLineEdit.EchoMode.Password)
        if not accepted or not password.strip():
            return
        try:
            self.db.add_user(fio.strip(), position.strip(), password.strip())
            self.refresh_users(fio.strip())
        except DataError as exc:
            critical(self, "Ошибка", str(exc))

    def edit_user(self):
        user = self.db.get_user_by_fio(self.fio_combo.currentText())
        if not user:
            return
        fio, accepted = QInputDialog.getText(
            self, "Редактирование пользователя", "ФИО:",
            text=user["fio"])
        if not accepted or not fio.strip():
            return
        position, accepted = QInputDialog.getText(
            self, "Редактирование пользователя", "Должность:",
            text=user.get("position") or "")
        if not accepted:
            return
        password, accepted = QInputDialog.getText(
            self, "Редактирование пользователя",
            "Пароль (пусто — оставить):", QLineEdit.EchoMode.Password)
        if not accepted:
            return
        try:
            self.db.edit_user(user["fio"], fio.strip(), position.strip(),
                              password.strip() or None)
            self.refresh_users(fio.strip())
        except DataError as exc:
            critical(self, "Ошибка", str(exc))

    def refresh_users(self, selected=None):
        self.fio_combo.clear()
        self.fio_combo.addItems(
            [user["fio"] for user in self.db.get_loginable_users()])
        if selected:
            self.fio_combo.setCurrentText(selected)


class UserManagerDialog(QDialog):
    """Управление пользователями и журнал сбросов пароля."""

    def __init__(self, parent=None, db: Database = None,
                 current_admin_fio=None, is_admin=False):
        super().__init__(parent)
        self.db = db
        self.admin_fio = current_admin_fio
        self.is_admin = is_admin
        self.setWindowTitle("Управление пользователями (мастер-доступ)")
        self.resize(760, 520)
        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            "Двойной клик по пользователю — открыть карточку и историю сбросов"))
        self.user_list = QListWidget()
        self.user_list.itemDoubleClicked.connect(self.open_user_card)
        root.addWidget(self.user_list, 1)

        buttons = QHBoxLayout()
        for text, slot in (
            ("Добавить", self.add_user),
            ("Редактировать", self.edit_user),
            ("Удалить", self.delete_user),
            ("Смена мастер-пароля", self.change_master_password),
            ("🔄 Сбросить пароль", self.reset_password),
            ("История сбросов", self.show_reset_history),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        root.addLayout(buttons)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        root.addWidget(close)
        self.reload()

    def reload(self):
        selected_id = (self.current_user() or {}).get("id")
        self.user_list.clear()
        for user in self.db.get_users():
            flag = "Да" if user.get("must_change_password") else ""
            item = QListWidgetItem(
                f"{user['fio']}  |  {user.get('position') or ''}  |  {flag}")
            item.setData(Qt.ItemDataRole.UserRole, user)
            self.user_list.addItem(item)
            if user["id"] == selected_id:
                self.user_list.setCurrentItem(item)

    def current_user(self):
        item = self.user_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def add_user(self):
        fio, accepted = QInputDialog.getText(self, "Новый пользователь", "ФИО:")
        if not accepted:
            return
        position, accepted = QInputDialog.getText(
            self, "Новый пользователь", "Должность:")
        if not accepted:
            return
        password, accepted = QInputDialog.getText(
            self, "Новый пользователь", "Пароль:",
            QLineEdit.EchoMode.Password)
        if not accepted:
            return
        try:
            self.db.add_user(fio.strip(), position.strip(), password)
            self.reload()
        except DataError as exc:
            critical(self, "Ошибка", str(exc))

    def edit_user(self):
        user = self.current_user()
        if not user:
            warning(self, "Внимание", "Выберите пользователя.")
            return
        fio, accepted = QInputDialog.getText(
            self, "Редактирование", "ФИО:", text=user["fio"])
        if not accepted:
            return
        position, accepted = QInputDialog.getText(
            self, "Редактирование", "Должность:",
            text=user.get("position") or "")
        if not accepted:
            return
        password, accepted = QInputDialog.getText(
            self, "Редактирование",
            "Новый пароль (пусто — оставить):",
            QLineEdit.EchoMode.Password)
        if not accepted:
            return
        try:
            self.db.edit_user(user["fio"], fio.strip(), position.strip(),
                              password.strip() or None)
            self.reload()
        except DataError as exc:
            critical(self, "Ошибка", str(exc))

    def delete_user(self):
        user = self.current_user()
        if not user:
            warning(self, "Внимание", "Выберите пользователя.")
            return
        if user["fio"] == "Администратор":
            warning(self, "Внимание", "Нельзя удалить администратора.")
            return
        if not question(self, "Подтверждение",
                        f"Удалить пользователя {user['fio']}?"):
            return
        conn = self.db._connect()
        try:
            try:
                conn.execute("DELETE FROM users WHERE id = ?", (user["id"],))
                conn.commit()
            except sqlite3.IntegrityError:
                conn.rollback()
                critical(
                    self, "Невозможно удалить пользователя",
                    "Пользователь связан с записями журнала действий или "
                    "историей сброса пароля. Эти записи сохраняются; "
                    "пользователь не удалён.")
                return
        finally:
            conn.close()
        self.reload()

    def reset_password(self):
        user = self.current_user()
        if not user:
            warning(self, "Внимание", "Выберите пользователя.")
            return
        prompt = (
            "Пароль будет установлен на «1234».\n"
            "Пользователь обязан сменить его при первом входе.\n\n"
            "Для подтверждения сброса прикрепите скриншот JPG/PNG (обоснование).\n"
            "Максимальный размер — 10 МБ."
        )
        information(self, "Сброс пароля", prompt)
        path, _ = QFileDialog.getOpenFileName(
                self, "Выберите скриншот (JPG/PNG)", "",
            "Изображения (*.jpg *.jpeg *.png)")
        if not path:
            return
        if os.path.splitext(path)[1].lower() not in (".jpg", ".jpeg", ".png"):
            critical(self, "Ошибка", "Разрешены только файлы .jpg / .jpeg / .png.")
            return
        try:
            size = os.path.getsize(path)
            if size > 10 * 1024 * 1024:
                critical(self, "Ошибка",
                         f"Файл слишком большой: {size / (1024 * 1024):.1f} МБ. "
                         "Максимум — 10 МБ.")
                return
            with open(path, "rb") as stream:
                image_data = stream.read()
        except OSError as exc:
            critical(self, "Ошибка", f"Не удалось прочитать файл: {exc}")
            return
        if not question(
                self, "Подтверждение",
                f"Сбросить пароль пользователя «{user['fio']}» на 1234?"):
            return
        filename = os.path.basename(path)
        self.db.add_password_reset(
            user["id"], self.admin_fio or "Служба поддержки",
            filename, image_data)
        self.db.reset_user_password(user["id"], "1234")
        self.db.log_action_anonymous(
            "RESET_PASSWORD",
            f"Пользователю {user['fio']} был сброшен пароль")
        information(
            self, "Готово",
            f"Пароль пользователя «{user['fio']}» сброшен на 1234.\n"
            "При следующем входе пользователь должен будет задать новый пароль.")
        self.reload()

    def change_master_password(self):
        current_password, accepted = QInputDialog.getText(
            self, "Смена мастер-пароля", "Текущий мастер-пароль:",
            QLineEdit.EchoMode.Password)
        if not accepted:
            return
        if not self.db.verify_master_password(current_password):
            critical(self, "Ошибка", "Неверный мастер-пароль.")
            return

        new_password, accepted = QInputDialog.getText(
            self, "Смена мастер-пароля", "Новый мастер-пароль:",
            QLineEdit.EchoMode.Password)
        if not accepted:
            return
        confirm_password, accepted = QInputDialog.getText(
            self, "Смена мастер-пароля", "Повторите новый мастер-пароль:",
            QLineEdit.EchoMode.Password)
        if not accepted:
            return
        if not new_password or len(new_password) < 4:
            critical(self, "Ошибка", "Мастер-пароль должен быть не менее 4 символов.")
            return
        if new_password != confirm_password:
            critical(self, "Ошибка", "Пароли не совпадают.")
            return

        self.db.set_master_password_hash(_hash_password(new_password))
        information(self, "Готово", "Мастер-пароль успешно изменён.")

    def show_reset_history(self):
        user = self.current_user()
        if not user:
            warning(self, "Внимание", "Выберите пользователя.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"История сбросов — {user['fio']}")
        dialog.resize(760, 460)
        layout = QVBoxLayout(dialog)
        history = QListWidget()
        for reset_id, timestamp, reset_by, filename, image_data in \
                self.db.get_password_resets(user["id"]):
            item = QListWidgetItem(
                f"{timestamp}  •  {reset_by or '—'}  •  {filename}")
            item.setData(Qt.ItemDataRole.UserRole,
                         (reset_id, image_data, filename))
            history.addItem(item)
        history.itemDoubleClicked.connect(
            lambda item: self.preview_reset_screenshot(
                item.data(Qt.ItemDataRole.UserRole)))
        layout.addWidget(history, 1)
        close = QPushButton("Закрыть")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    def preview_reset_screenshot(self, record):
        reset_id, image_data, filename = record
        if not image_data:
            warning(self, "Внимание", "Скриншот отсутствует.")
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(image_data):
            critical(self, "Ошибка", "Не удалось открыть файл скриншота.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(filename or f"Скриншот {reset_id}")
        layout = QVBoxLayout(dialog)
        image = QLabel()
        image.setPixmap(pixmap.scaled(
            1000, 700, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(image)
        close = QPushButton("Закрыть")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    def open_user_card(self, item):
        user = item.data(Qt.ItemDataRole.UserRole)
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Карточка пользователя: {user['fio']}")
        dialog.resize(860, 600)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"ФИО: {user['fio']}"))
        layout.addWidget(QLabel(f"Должность: {user.get('position') or '—'}"))
        history_button = QPushButton("История сбросов пароля")
        history_button.clicked.connect(
            lambda: self._show_user_reset_history(user))
        layout.addWidget(history_button)
        reset_button = QPushButton("🔄 Сбросить пароль")
        reset_button.clicked.connect(lambda: self._reset_specific_user(user))
        layout.addWidget(reset_button)
        close = QPushButton("Закрыть")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    def _reset_specific_user(self, user):
        for row in range(self.user_list.count()):
            item = self.user_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole)["id"] == user["id"]:
                self.user_list.setCurrentItem(item)
                break
        self.reset_password()

    def _show_user_reset_history(self, user):
        for row in range(self.user_list.count()):
            item = self.user_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole)["id"] == user["id"]:
                self.user_list.setCurrentItem(item)
                break
        self.show_reset_history()