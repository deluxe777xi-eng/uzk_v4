# -*- coding: utf-8 -*-
"""Точка входа v4 (аналог prog.py для PyQt6)."""
import sys
from pathlib import Path

# чтобы пакеты uzk_app импортировались из v4/ независимо от cwd
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt6.QtCore import QObject, QEvent, Qt
from PyQt6.QtWidgets import QApplication, QMessageBox, QStyle, QComboBox
from PyQt6.QtGui import QFont

# ОБЯЗАТЕЛЬНО: импорт WebEngine строго до создания QApplication
import PyQt6.QtWebEngineWidgets

from uzk_app.config import APP_TITLE, FONT_FAMILY, FONT_SIZE  # noqa: E402
from uzk_app.db import Database  # noqa: E402
from uzk_app.ui.main_window import MainWindow  # noqa: E402


class ComboBoxWheelFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel and isinstance(obj, QComboBox):
            event.ignore()
            return True
        return super().eventFilter(obj, event)


def main() -> int:
    # ОБЯЗАТЕЛЬНО: Установка атрибута для корректной работы Chromium (PDF)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setFont(QFont(FONT_FAMILY, FONT_SIZE))

    app_icon = app.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogListView)
    app.setWindowIcon(app_icon)
    
    wheel_filter = ComboBoxWheelFilter()
    app.installEventFilter(wheel_filter)

    try:
        db = Database()
        db.init_db()
    except Exception as e:
        QMessageBox.critical(None, "Ошибка запуска", f"Не удалось открыть базу данных:\n{e}")
        return 1

    win = MainWindow(db)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())