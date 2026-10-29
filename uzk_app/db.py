# -*- coding: utf-8 -*-
"""Слой данных v4 (sqlite3). Чистый, без GUI.

Объединяет логику v3: uzk_app/data_mixin.py + db-часть editors/journal.
Все сообщения об ошибках возвращаются вызывающему коду (UI сам решает,
показывать QMessageBox или нет) — модуль не зависит от PyQt6.
"""
import datetime
import json
import os
import re
import sqlite3

from .config import DB_NAME, SETTINGS_FILE
from .helpers import _ensure_parent_dir, timestamp_now
from .security import _hash_password, _verify_password

DEFAULT_JOURNAL_NAME = "Общий"


# ============================================================
#  Валидаторы для пользователей
# ============================================================

_FIO_ALLOWED = re.compile(r'^[А-Яа-яЁё\s\.\-]+$')
_FIO_HAS_LETTER = re.compile(r'[А-Яа-яЁё]')


def validate_fio(name):
    """Проверка ФИО/логина. Возвращает (ok, message)."""
    if not name:
        return False, "ФИО не может быть пустым."
    if not _FIO_ALLOWED.match(name):
        return False, "ФИО может содержать только русские буквы, пробелы, точки и дефисы."
    if not _FIO_HAS_LETTER.search(name):
        return False, "ФИО должно содержать хотя бы одну русскую букву."
    return True, ""


def validate_password(password):
    """Проверка пароля. Возвращает (ok, message)."""
    if not password or len(password) < 4:
        return False, "Пароль должен быть не менее 4 символов."
    return True, ""


class DataError(Exception):
    """Ошибка уровня данных (дубликат, целостность и т.п.)."""


class Database:
    """Единая точка доступа к SQLite-базе УЗК."""

    def __init__(self, db_path=None):
        self.db_path = db_path or DB_NAME
        self.settings = {}
        self.current_user = None

    # ------------------------------------------------------------
    #  Соединение / схема
    # ------------------------------------------------------------

    def _connect(self):
        _ensure_parent_dir(self.db_path)
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db(self):
        conn = self._connect()
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS conclusions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_num TEXT, date TEXT, record_num TEXT, izdeliye TEXT, detal TEXT, order_num TEXT,
                object_kontr TEXT, material TEXT, thickness TEXT, volume_kontr TEXT,
                norm_doc TEXT, method_kontr TEXT, map_kontr TEXT,
                quality TEXT, fio TEXT, signature TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conclusion_id INTEGER,
                prog_obespec TEXT, tip_defectoscope TEXT, tip_skan_ustr TEXT,
                tip_preobr TEXT, tip_preobr_sn TEXT, tip_prism TEXT, tip_prism_sn TEXT,
                tip_preobr2 TEXT, tip_preobr2_sn TEXT, tip_prism2 TEXT, tip_prism2_sn TEXT,
                kanal TEXT, tip_skanirov TEXT, time_delay TEXT, angle TEXT,
                focus TEXT, dist_points TEXT, preamp TEXT, averaging TEXT,
                offset_y TEXT, scan_range_x TEXT, sample_ref TEXT, setup_method TEXT,
                we_level TEXT, gain TEXT,
                FOREIGN KEY(conclusion_id) REFERENCES conclusions(id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS defects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                measurement_id INTEGER,
                defect_object TEXT,
                plot_num TEXT, amp_s_def TEXT, y_start_end TEXT,
                len_y TEXT, x_start_end TEXT, len_x TEXT, z_start_end TEXT,
                height TEXT, defect_type TEXT, no_defect TEXT,
                quality TEXT, fio TEXT,
                FOREIGN KEY(measurement_id) REFERENCES measurements(id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS dict_lists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT,
                value TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS defectoscopes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                serial TEXT,
                UNIQUE(type, serial)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS equipment (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                type TEXT NOT NULL,
                serial TEXT,
                method TEXT NOT NULL,
                device_ids TEXT,
                UNIQUE(category, type, serial, device_ids)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                login TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                fio TEXT NOT NULL,
                position TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                timestamp TEXT,
                action TEXT,
                details TEXT,
                diff_data TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS password_resets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                timestamp TEXT,
                reset_by TEXT,
                screenshot_name TEXT,
                screenshot_data BLOB,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')

        cursor.execute("PRAGMA table_info(logs)")
        logs_cols = [col[1] for col in cursor.fetchall()]
        if 'diff_data' not in logs_cols:
            cursor.execute("ALTER TABLE logs ADD COLUMN diff_data TEXT")

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conclusion_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                file_data BLOB NOT NULL,
                FOREIGN KEY(conclusion_id) REFERENCES conclusions(id) ON DELETE CASCADE
            )
        ''')

        cursor.execute("PRAGMA table_info(equipment)")
        equip_cols = [col[1] for col in cursor.fetchall()]
        if 'device_ids' not in equip_cols:
            cursor.execute("ALTER TABLE equipment ADD COLUMN device_ids TEXT")

        cursor.execute("PRAGMA table_info(users)")
        user_cols = [col[1] for col in cursor.fetchall()]
        if 'position' not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN position TEXT")
        if 'must_change_password' not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER DEFAULT 0")

        cursor.execute("PRAGMA table_info(defects)")
        defect_cols = [col[1] for col in cursor.fetchall()]
        if 'channel' not in defect_cols:
            cursor.execute("ALTER TABLE defects ADD COLUMN channel TEXT")

        cursor.execute("PRAGMA table_info(conclusions)")
        conclusion_cols = [col[1] for col in cursor.fetchall()]
        if 'journal' not in conclusion_cols:
            cursor.execute("ALTER TABLE conclusions ADD COLUMN journal TEXT")
        if 'comment' not in conclusion_cols:
            cursor.execute("ALTER TABLE conclusions ADD COLUMN comment TEXT")

        cursor.execute("SELECT COUNT(*) FROM dict_lists WHERE key = 'journal_list'")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO dict_lists (key, value) VALUES ('journal_list', ?)", (DEFAULT_JOURNAL_NAME,))
        cursor.execute(
            "UPDATE conclusions SET journal = ? WHERE journal IS NULL OR journal = ''",
            (DEFAULT_JOURNAL_NAME,)
        )

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_conclusions_journal_id ON conclusions(journal, id DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_conclusions_journal_report_id ON conclusions(journal, report_num, id DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_conclusions_journal_record_id ON conclusions(journal, record_num, id DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_measurements_conclusion_id ON measurements(conclusion_id, id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_defects_measurement_id ON defects(measurement_id, id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_attachments_conclusion_id ON attachments(conclusion_id, id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_user_id ON logs(user_id, id DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp, id DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_password_resets_user_id ON password_resets(user_id, id DESC)")

        admin_hash = _hash_password('admin')
        cursor.execute(
            "INSERT OR IGNORE INTO users (login, password_hash, fio, position) VALUES ('admin', ?, 'Администратор', 'Системный администратор')",
            (admin_hash,)
        )

        # Мастер-пароль по умолчанию — masterUZK.
        cursor.execute("SELECT 1 FROM app_settings WHERE key = 'master_password_hash'")
        if not cursor.fetchone():
            master_hash = _hash_password('masterUZK')
            cursor.execute(
                "INSERT INTO app_settings (key, value) VALUES ('master_password_hash', ?)",
                (master_hash,)
            )

        conn.commit()
        conn.close()

    # ------------------------------------------------------------
    #  Настройки приложения (JSON)
    # ------------------------------------------------------------

    def load_settings(self):
        _ensure_parent_dir(SETTINGS_FILE)
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    self.settings = json.load(f)
            except Exception as e:
                print(f"Ошибка загрузки настроек: {e}")
                self.settings = {}
        else:
            self.settings = {}
        return self.settings

    def save_settings(self):
        try:
            _ensure_parent_dir(SETTINGS_FILE)
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f)
        except Exception as e:
            print(f"Ошибка сохранения настроек: {e}")

    # ------------------------------------------------------------
    #  Пользователи
    # ------------------------------------------------------------

    def get_users(self):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT id, login, password_hash, fio, position, must_change_password FROM users ORDER BY fio")
        rows = cursor.fetchall()
        conn.close()
        return [
            {'id': r[0], 'login': r[1], 'password_hash': r[2], 'fio': r[3],
             'position': r[4], 'must_change_password': r[5] or 0}
            for r in rows
        ]

    def get_loginable_users(self):
        """Пользователи для окна входа (без Администратора)."""
        return [u for u in self.get_users() if u['fio'] != 'Администратор']

    def get_user_by_fio(self, fio):
        if fio is None:
            return None
        fio = fio.strip()
        target = fio.casefold()
        for u in self.get_users():
            if (u.get('fio') or '').strip().casefold() == target:
                return u
        return None

    def get_user_by_id(self, user_id):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, login, password_hash, fio, position, must_change_password FROM users WHERE id = ?",
            (user_id,)
        )
        r = cursor.fetchone()
        conn.close()
        if not r:
            return None
        return {
            'id': r[0], 'login': r[1], 'password_hash': r[2],
            'fio': r[3], 'position': r[4], 'must_change_password': r[5] or 0,
        }

    def authenticate(self, fio, password):
        """Проверяет пару ФИО/пароль; возвращает пользователя или None."""
        user = self.get_user_by_fio(fio)
        if not user:
            return None
        if _verify_password(password, user['password_hash']):
            return user
        return None

    def add_user(self, fio, position, password):
        ok, msg = validate_fio(fio)
        if not ok:
            raise DataError(msg)
        ok, msg = validate_password(password)
        if not ok:
            raise DataError(msg)

        conn = self._connect()
        cursor = conn.cursor()
        try:
            login = fio
            pwd_hash = _hash_password(password)
            cursor.execute(
                "INSERT INTO users (login, password_hash, fio, position) VALUES (?, ?, ?, ?)",
                (login, pwd_hash, fio, position)
            )
            cursor.execute(
                "SELECT 1 FROM dict_lists WHERE key = 'fio_list' AND value = ? LIMIT 1",
                (fio,)
            )
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO dict_lists (key, value) VALUES ('fio_list', ?)",
                    (fio,)
                )
            conn.commit()
        except sqlite3.IntegrityError:
            raise DataError(f"Пользователь с ФИО '{fio}' уже существует в базе!")
        finally:
            conn.close()
        return True

    def edit_user(self, old_fio, new_fio, new_position, new_password=None):
        ok, msg = validate_fio(new_fio)
        if not ok:
            raise DataError(msg)
        if new_password and new_password.strip():
            ok, msg = validate_password(new_password.strip())
            if not ok:
                raise DataError(msg)

        old_user = self.get_user_by_fio(old_fio)
        if not old_user:
            raise DataError("Пользователь не найден.")

        pwd_hash = old_user['password_hash']
        if new_password and new_password.strip():
            pwd_hash = _hash_password(new_password.strip())

        conn = self._connect()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE users SET login=?, password_hash=?, fio=?, position=? WHERE id=?",
                (new_fio, pwd_hash, new_fio, new_position, old_user['id'])
            )
            if old_fio != new_fio:
                cursor.execute(
                    "SELECT 1 FROM dict_lists WHERE key = 'fio_list' AND value = ? LIMIT 1",
                    (new_fio,)
                )
                if not cursor.fetchone():
                    cursor.execute(
                        "INSERT INTO dict_lists (key, value) VALUES ('fio_list', ?)",
                        (new_fio,)
                    )
            conn.commit()
        except sqlite3.IntegrityError:
            raise DataError(f"Пользователь с ФИО '{new_fio}' уже существует в базе!")
        finally:
            conn.close()
        return True

    # ------------------------------------------------------------
    #  Мастер-пароль и история сбросов
    # ------------------------------------------------------------

    def get_master_password_hash(self):
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM app_settings WHERE key = 'master_password_hash'")
            row = cursor.fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def set_master_password_hash(self, hash_str):
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO app_settings (key, value) VALUES ('master_password_hash', ?)",
                (hash_str,)
            )
            conn.commit()
        finally:
            conn.close()

    def verify_master_password(self, password):
        hash_str = self.get_master_password_hash()
        if not hash_str:
            return False
        return _verify_password(password, hash_str)

    def get_password_resets(self, user_id, limit=20):
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, timestamp, reset_by, screenshot_name, screenshot_data
                FROM password_resets WHERE user_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (user_id, limit)
            )
            return cursor.fetchall()
        finally:
            conn.close()

    def add_password_reset(self, user_id, reset_by, screenshot_name, screenshot_data):
        conn = self._connect()
        try:
            cursor = conn.cursor()
            timestamp = timestamp_now()
            cursor.execute(
                """
                INSERT INTO password_resets (user_id, timestamp, reset_by, screenshot_name, screenshot_data)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, timestamp, reset_by, screenshot_name, screenshot_data)
            )
            # Оставляем только 20 последних записей на пользователя
            cursor.execute(
                """
                DELETE FROM password_resets
                WHERE user_id = ? AND id NOT IN (
                    SELECT id FROM password_resets WHERE user_id = ? ORDER BY id DESC LIMIT 20
                )
                """,
                (user_id, user_id)
            )
            conn.commit()
        finally:
            conn.close()

    def reset_user_password(self, user_id, new_password):
        """Сброс пароля + флаг must_change_password=1."""
        conn = self._connect()
        try:
            cursor = conn.cursor()
            pwd_hash = _hash_password(new_password)
            cursor.execute(
                "UPDATE users SET password_hash = ?, must_change_password = 1 WHERE id = ?",
                (pwd_hash, user_id)
            )
            conn.commit()
        finally:
            conn.close()

    def change_user_password(self, user_id, new_password):
        """Обычная смена пароля (флаг сбрасывается)."""
        conn = self._connect()
        try:
            cursor = conn.cursor()
            pwd_hash = _hash_password(new_password)
            cursor.execute(
                "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
                (pwd_hash, user_id)
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------
    #  Журнал действий
    # ------------------------------------------------------------

    def log_action(self, action, details=None, diff_data=None, user=None):
        """Логирование от имени текущего (или переданного) пользователя."""
        user = user if user is not None else self.current_user
        if not user:
            return
        conn = self._connect()
        cursor = conn.cursor()
        diff_json = json.dumps(diff_data, ensure_ascii=False) if diff_data is not None else None
        cursor.execute(
            "INSERT INTO logs (user_id, timestamp, action, details, diff_data) VALUES (?, ?, ?, ?, ?)",
            (user['id'], timestamp_now(), action, details, diff_json)
        )
        conn.commit()
        conn.close()

    def log_action_anonymous(self, action, details=None, diff_data=None):
        """Логирование действий без авторизованного пользователя (мастер-доступ)."""
        conn = self._connect()
        cursor = conn.cursor()
        diff_json = json.dumps(diff_data, ensure_ascii=False) if diff_data is not None else None
        cursor.execute(
            "INSERT INTO logs (user_id, timestamp, action, details, diff_data) VALUES (NULL, ?, ?, ?, ?)",
            (timestamp_now(), action, details, diff_json)
        )
        conn.commit()
        conn.close()

    def get_logs(self, start_date=None, end_date=None, fio=None, search_text=None, limit=3500):
        """Фильтрация журнала. Даты — строки dd.mm.yyyy (как в v3)."""
        conn = self._connect()
        try:
            cursor = conn.cursor()
            query = """
                SELECT logs.id, logs.timestamp, users.fio, logs.details, logs.diff_data
                FROM logs
                LEFT JOIN users ON logs.user_id = users.id
                WHERE 1=1
            """
            params = []
            for bound_date, op in ((start_date, '>='), (end_date, '<=')):
                if bound_date:
                    try:
                        sd = datetime.datetime.strptime(bound_date, '%d.%m.%Y').strftime('%Y-%m-%d')
                        query += f" AND date(logs.timestamp) {op} date(?)"
                        params.append(sd)
                    except Exception:
                        pass
            if fio:
                query += " AND users.fio = ?"
                params.append(fio)
            if search_text:
                query += " AND (logs.action LIKE ? OR logs.details LIKE ?)"
                params.append(f"%{search_text}%")
                params.append(f"%{search_text}%")
            query += f" ORDER BY logs.id DESC LIMIT {int(limit)}"
            cursor.execute(query, params)
            return cursor.fetchall()
        finally:
            conn.close()

    def get_log_entry(self, log_id):
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT logs.timestamp, users.fio, logs.action, logs.details, logs.diff_data
                FROM logs LEFT JOIN users ON logs.user_id = users.id
                WHERE logs.id = ?
            """, (log_id,))
            return cursor.fetchone()
        finally:
            conn.close()

    # ------------------------------------------------------------
    #  Словари
    # ------------------------------------------------------------

    def get_dict_values(self, key):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM dict_lists WHERE key = ? ORDER BY value", (key,))
        values = [row[0] for row in cursor.fetchall()]
        conn.close()
        return values

    def get_journals(self) -> list[str]:
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT journal FROM conclusions "
                "WHERE journal IS NOT NULL AND journal <> ''")
            conclusion_journals = {row[0] for row in cursor.fetchall()}
        finally:
            conn.close()
        return sorted(conclusion_journals | set(self.get_dict_values("journal_list")))

    def replace_dict_values(self, key, values):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM dict_lists WHERE key = ?", (key,))
        for val in values:
            cursor.execute("INSERT INTO dict_lists (key, value) VALUES (?, ?)", (key, val))
        conn.commit()
        conn.close()

    def dict_pairs(self, key):
        """Для словарей вида 'Тип / Зав.№' -> {type: [serial,...]} с сохранением порядка."""
        data = {}
        for item in self.get_dict_values(key):
            if " / " in item:
                p_type, p_sn = item.split(" / ", 1)
            else:
                p_type, p_sn = item, None
            data.setdefault(p_type, [])
            if p_sn is not None:
                data[p_type].append(p_sn)
        return data

    def dict_pairs_to_flat(self, data):
        flat = []
        for p_type, sns in data.items():
            if sns:
                for sn in sns:
                    flat.append(f"{p_type} / {sn}")
            else:
                flat.append(p_type)
        return flat

    # ------------------------------------------------------------
    #  Дефектоскопы
    # ------------------------------------------------------------

    def get_defectoscopes(self) -> list[str]:
        """Return defectoscope display names, matching the v3 data-layer API."""
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT type, serial FROM defectoscopes ORDER BY type, serial")
        rows = cursor.fetchall()
        conn.close()
        return [f"{type_} {serial}" if serial else type_ for type_, serial in rows]

    def get_defectoscope_display_list(self):
        return self.get_defectoscopes()

    def get_defectoscope_records(self) -> list[dict[str, int | str | None]]:
        """Return defectoscope rows with ids for v4 management widgets."""
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, type, serial FROM defectoscopes ORDER BY type, serial")
            rows = cursor.fetchall()
        finally:
            conn.close()
        return [{'id': row[0], 'type': row[1], 'serial': row[2]} for row in rows]

    def get_defectoscope_id_by_str(self, full_str):
        if not full_str:
            return None
        parts = full_str.rsplit(' ', 1)
        t = parts[0]
        s = parts[1] if len(parts) > 1 else ""
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM defectoscopes WHERE type=? AND serial=?", (t, s))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

    def add_defectoscope(self, type_, serial):
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO defectoscopes (type, serial) VALUES (?, ?)", (type_, serial))
            conn.commit()
        except sqlite3.IntegrityError:
            raise DataError("Такой дефектоскоп уже существует!")
        finally:
            conn.close()

    def update_defectoscope(self, scope_id, type_, serial):
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE defectoscopes SET type=?, serial=? WHERE id=?", (type_, serial, scope_id))
            conn.commit()
        except sqlite3.IntegrityError:
            raise DataError("Такой дефектоскоп уже существует!")
        finally:
            conn.close()

    def delete_defectoscope(self, scope_id):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM defectoscopes WHERE id=?", (scope_id,))
        conn.commit()
        conn.close()

    # ------------------------------------------------------------
    #  Оборудование (преобразователи / призмы)
    # ------------------------------------------------------------

    def get_equipment(self, category, method, current_device_id=None):
        conn = self._connect()
        cursor = conn.cursor()
        if current_device_id:
            query = """
                SELECT type, serial FROM equipment
                WHERE category = ? AND (method = ?)
                AND (device_ids IS NULL OR device_ids = '' OR ',' || device_ids || ',' LIKE '%,' || ? || ',%')
                ORDER BY type, serial
            """
            cursor.execute(query, (category, method, str(current_device_id)))
        else:
            query = """
                SELECT type, serial FROM equipment
                WHERE category = ? AND (method = ?)
                AND (device_ids IS NULL OR device_ids = '')
                ORDER BY type, serial
            """
            cursor.execute(query, (category, method))
        rows = cursor.fetchall()
        conn.close()
        return [{'type': r[0], 'serial': r[1]} for r in rows]

    def get_equipment_rows(self, category):
        conn = self._connect()
        cursor = conn.cursor()
        query = """
            SELECT e.id, e.type, e.serial, e.method, e.device_ids, GROUP_CONCAT(d.type || ' ' || d.serial, ', ')
            FROM equipment e
            LEFT JOIN defectoscopes d ON ',' || e.device_ids || ',' LIKE '%,' || d.id || ',%'
            WHERE e.category = ?
            GROUP BY e.id
            ORDER BY e.type, e.serial
        """
        cursor.execute(query, (category,))
        rows = cursor.fetchall()
        conn.close()
        result = []
        for r in rows:
            result.append({
                'id': r[0], 'type': r[1], 'serial': r[2],
                'method': r[3], 'device_ids': r[4], 'device_str': r[5] if r[5] else "Для всех"
            })
        return result

    def save_equipment(self, category, equip_id, type_, serial, method, device_ids, mode):
        conn = self._connect()
        try:
            cursor = conn.cursor()
            if mode == 'add':
                cursor.execute(
                    "INSERT INTO equipment (category, type, serial, method, device_ids) VALUES (?, ?, ?, ?, ?)",
                    (category, type_, serial, method, device_ids))
            else:
                cursor.execute(
                    "UPDATE equipment SET type=?, serial=?, method=?, device_ids=? WHERE id=?",
                    (type_, serial, method, device_ids, equip_id))
            conn.commit()
        except sqlite3.IntegrityError:
            raise DataError("Такое оборудование уже существует!")
        finally:
            conn.close()

    def delete_equipment_by_id(self, equip_id):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM equipment WHERE id=?", (equip_id,))
        conn.commit()
        conn.close()

    def delete_equipment_type(self, category, type_):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM equipment WHERE category=? AND type=?", (category, type_))
        conn.commit()
        conn.close()

    def insert_equipment_if_missing(self, category, type_, serial, method):
        """Импорт Excel: добавляет оборудование, если его ещё нет (без привязки)."""
        if not type_:
            return
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM equipment WHERE category=? AND type=? AND serial=? AND (device_ids IS NULL OR device_ids='')",
            (category, type_, serial))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO equipment (category, type, serial, method, device_ids) VALUES (?, ?, ?, ?, ?)",
                (category, type_, serial, method if method in ("TOFD", "PAUT") else "TOFD", None))
        conn.commit()
        conn.close()

    # ------------------------------------------------------------
    #  Заключения: проверка дублей, сохранение, чтение
    # ------------------------------------------------------------

    def conclusion_exists(self, report_num, journal, exclude_id=None):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM conclusions WHERE report_num = ? AND journal = ? AND id != ? LIMIT 1",
            (report_num, journal, exclude_id or 0))
        found = cursor.fetchone() is not None
        conn.close()
        return found

    def record_exists(self, record_num, journal, exclude_id=None):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM conclusions WHERE record_num = ? AND journal = ? AND id != ? LIMIT 1",
            (record_num, journal, exclude_id or 0))
        found = cursor.fetchone() is not None
        conn.close()
        return found

    def get_conclusion_signature(self, conclusion_id):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT signature FROM conclusions WHERE id = ?", (conclusion_id,))
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return None
        signature = row[0] or ""
        try:
            signed = json.loads(signature) if signature else []
        except Exception:
            signed = []
        return signed

    def get_conclusion_originals(self, conclusion_id):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT report_num, record_num, journal FROM conclusions WHERE id = ?",
            (conclusion_id,))
        row = cursor.fetchone()
        conn.close()
        return row if row else (None, None, None)

    def save_conclusion(self, g_data, normalized_measurements, conclusion_id=None):
        """Сохраняет заключение целиком. Возвращает id заключения."""
        g_data = dict(g_data)
        if not str(g_data.get("journal") or "").strip():
            g_data["journal"] = DEFAULT_JOURNAL_NAME
        conn = self._connect()
        try:
            cursor = conn.cursor()
            if conclusion_id:
                update_data = dict(g_data)
                update_data.pop("quality", None)
                update_data.pop("fio", None)
                assignments = ", ".join(f"{key} = ?" for key in update_data)
                cursor.execute(
                    f"UPDATE conclusions SET {assignments}, quality = ?, fio = ?, signature = ? WHERE id = ?",
                    list(update_data.values()) + [g_data["quality"], g_data["fio"], "", conclusion_id]
                )
                cursor.execute(
                    "DELETE FROM defects WHERE measurement_id IN (SELECT id FROM measurements WHERE conclusion_id = ?)",
                    (conclusion_id,)
                )
                cursor.execute("DELETE FROM measurements WHERE conclusion_id = ?", (conclusion_id,))
            else:
                gen_cols = ", ".join(g_data.keys())
                gen_placeholders = ", ".join(["?" for _ in g_data])
                cursor.execute(f"INSERT INTO conclusions ({gen_cols}) VALUES ({gen_placeholders})",
                               list(g_data.values()))
                conclusion_id = cursor.lastrowid

            for m_data in normalized_measurements:
                defects = list(m_data.get('defects', []))
                measurement_record = dict(m_data)
                measurement_record["conclusion_id"] = conclusion_id
                measurement_record.pop('defects', None)
                m_cols = ", ".join(measurement_record.keys())
                m_placeholders = ", ".join(["?" for _ in measurement_record])
                cursor.execute(f"INSERT INTO measurements ({m_cols}) VALUES ({m_placeholders})",
                               list(measurement_record.values()))
                measurement_id = cursor.lastrowid

                for d_data in defects:
                    defect_record = {k: str(v).strip() if v is not None else "" for k, v in d_data.items()}
                    defect_record["measurement_id"] = measurement_id
                    d_cols = ", ".join(defect_record.keys())
                    d_placeholders = ", ".join(["?" for _ in defect_record])
                    cursor.execute(f"INSERT INTO defects ({d_cols}) VALUES ({d_placeholders})",
                                   list(defect_record.values()))
            conn.commit()
            return conclusion_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def delete_conclusion(self, conclusion_id):
        """Delete a conclusion and its dependent rows in foreign-key-safe order."""
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM defects WHERE measurement_id IN "
                "(SELECT id FROM measurements WHERE conclusion_id = ?)",
                (conclusion_id,))
            cursor.execute(
                "DELETE FROM measurements WHERE conclusion_id = ?",
                (conclusion_id,))
            cursor.execute(
                "DELETE FROM attachments WHERE conclusion_id = ?",
                (conclusion_id,))
            cursor.execute(
                "DELETE FROM conclusions WHERE id = ?",
                (conclusion_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def load_old_conclusion_state(self, conclusion_id):
        """Старое состояние заключения из БД (для diff при сохранении)."""
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, report_num, date, record_num, izdeliye, detal, order_num,
                       object_kontr, material, thickness, volume_kontr, norm_doc,
                       method_kontr, map_kontr, quality, fio, journal
                FROM conclusions WHERE id = ?
            """, (conclusion_id,))
            row = cursor.fetchone()
            if not row:
                return None
            general = {
                "report_num": row[1] or "", "date": row[2] or "", "record_num": row[3] or "",
                "izdeliye": row[4] or "", "detal": row[5] or "", "order_num": row[6] or "",
                "object_kontr": row[7] or "", "material": row[8] or "", "thickness": row[9] or "",
                "volume_kontr": row[10] or "", "norm_doc": row[11] or "", "method_kontr": row[12] or "",
                "map_kontr": row[13] or "", "quality": row[14] or "", "fio": row[15] or "",
                "journal": row[16] or "",
            }
            cursor.execute("""
                SELECT id, prog_obespec, tip_defectoscope, tip_skan_ustr,
                       tip_preobr, tip_preobr_sn, tip_prism, tip_prism_sn,
                       tip_preobr2, tip_preobr2_sn, tip_prism2, tip_prism2_sn,
                       kanal, tip_skanirov, time_delay, angle, focus, dist_points,
                       preamp, averaging, offset_y, scan_range_x, sample_ref,
                       setup_method, we_level, gain
                FROM measurements WHERE conclusion_id = ? ORDER BY id
            """, (conclusion_id,))
            measurements = []
            for mr in cursor.fetchall():
                m = {"id": mr[0]}
                keys = ["prog_obespec", "tip_defectoscope", "tip_skan_ustr", "tip_preobr",
                        "tip_preobr_sn", "tip_prism", "tip_prism_sn", "tip_preobr2", "tip_preobr2_sn",
                        "tip_prism2", "tip_prism2_sn", "kanal", "tip_skanirov", "time_delay", "angle",
                        "focus", "dist_points", "preamp", "averaging", "offset_y", "scan_range_x",
                        "sample_ref", "setup_method", "we_level", "gain"]
                for i, key in enumerate(keys, start=1):
                    m[key] = mr[i] or ""
                m["defects"] = []
                measurements.append(m)

            cursor.execute("""
                SELECT measurement_id, defect_object, plot_num, amp_s_def,
                       y_start_end, len_y, x_start_end, len_x, z_start_end,
                       height, defect_type, no_defect, quality, fio
                FROM defects
                WHERE measurement_id IN (SELECT id FROM measurements WHERE conclusion_id = ?)
                ORDER BY id
            """, (conclusion_id,))
            by_meas = {m["id"]: m for m in measurements}
            for dr in cursor.fetchall():
                if dr[0] not in by_meas:
                    continue
                by_meas[dr[0]]["defects"].append({
                    "defect_object": dr[1] or "", "plot_num": dr[2] or "", "amp_s_def": dr[3] or "",
                    "y_start_end": dr[4] or "", "len_y": dr[5] or "", "x_start_end": dr[6] or "",
                    "len_x": dr[7] or "", "z_start_end": dr[8] or "", "height": dr[9] or "",
                    "defect_type": dr[10] or "", "no_defect": dr[11] or "", "quality": dr[12] or "",
                    "fio": dr[13] or "",
                })
            return {"general": general, "measurements": measurements}
        finally:
            conn.close()

    def get_conclusion_journal_and_comment(self, report_id):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT journal, comment FROM conclusions WHERE id = ?", (report_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return "", ""
        return (row[0] or ""), (row[1] or "")

    def set_conclusion_comment(self, report_id, comment):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("UPDATE conclusions SET comment = ? WHERE id = ?", (comment, report_id))
        conn.commit()
        conn.close()

    def set_conclusion_signature(self, report_id, signature_json):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("UPDATE conclusions SET signature=? WHERE id=?", (signature_json, report_id))
        conn.commit()
        conn.close()

    def get_conclusion_signature_raw(self, report_id):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT report_num, signature FROM conclusions WHERE id=?", (report_id,))
        row = cursor.fetchone()
        conn.close()
        return row

    # ------------------------------------------------------------
    #  Приложения (PDF во вкладке просмотра)
    # ------------------------------------------------------------

    def get_attachments(self, conclusion_id):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT id, filename FROM attachments WHERE conclusion_id = ? ORDER BY id",
                       (conclusion_id,))
        rows = cursor.fetchall()
        conn.close()
        return rows

    def add_attachment(self, conclusion_id, filename, data):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO attachments (conclusion_id, filename, file_data) VALUES (?, ?, ?)",
            (conclusion_id, filename, data))
        conn.commit()
        conn.close()

    def get_attachment_data(self, attachment_id):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT file_data FROM attachments WHERE id = ?", (attachment_id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

    def delete_attachment(self, attachment_id):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
        conn.commit()
        conn.close()

    def get_screenshot(self, reset_id):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT screenshot_name, screenshot_data FROM password_resets WHERE id = ?",
                       (reset_id,))
        row = cursor.fetchone()
        conn.close()
        return row