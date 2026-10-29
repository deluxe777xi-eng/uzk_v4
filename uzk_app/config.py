# -*- coding: utf-8 -*-
"""Конфигурация v4 (PyQt6)."""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent      # <проект>/v4
PKG_DIR = Path(__file__).resolve().parent              # <проект>/v4/uzk_app
TEMPLATES_DIR = PKG_DIR / "templates"


def _resolve_data_dir() -> Path:
    env_dir = os.environ.get("UZK_DATA_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()

    frozen = getattr(sys, "frozen", False)
    if frozen:
        exe_dir = Path(sys.executable).resolve().parent
        base_dir = exe_dir.parent if exe_dir.name.lower() in {"uzk_app", "app"} else exe_dir
    else:
        base_dir = BASE_DIR

    if base_dir.name.lower() == "v4":
        v3_data_dir = base_dir.parent / "v3" / "UZK_Data"
        if v3_data_dir.is_dir():
            if not (v3_data_dir / "uzk_v3.db").is_file():
                raise FileNotFoundError(
                    f"В каталоге данных v3 не найдена БД: {v3_data_dir / 'uzk_v3.db'}")
            return v3_data_dir.resolve()

    if not frozen:
        root_candidate = BASE_DIR.parent
        if (root_candidate / "UZK_Data").exists() or (root_candidate / "prog.py").exists():
            base_dir = root_candidate

    data_dir = (base_dir / "UZK_Data").resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


DATA_DIR = _resolve_data_dir()
DB_NAME = str(DATA_DIR / "uzk_v3.db")          # формат БД не менялся (sqlite3)
SETTINGS_FILE = str(DATA_DIR / "uzk_settings.json")
LOG_FILE = str(DATA_DIR / "uzk_error.log")

APP_TITLE = "Журнал регистрации заключений (УЗК)"

# Общие настройки интерфейса
FONT_FAMILY = "Arial"
FONT_SIZE = 10