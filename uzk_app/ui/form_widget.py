# -*- coding: utf-8 -*-
"""Редактор заключения на PyQt6 (единая форма + дерево)."""
from __future__ import annotations

import datetime
import copy
from PyQt6.QtCore import Qt, pyqtSignal, QDate, QSettings
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QCompleter, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QMessageBox, QPushButton, QSplitter, QStackedWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QScrollArea, QGridLayout,
    QInputDialog, QFrame, QTreeWidget, QTreeWidgetItem, QSizePolicy, QMenu,
    QDateEdit
)

from ..db import DEFAULT_JOURNAL_NAME, Database
from ..helpers import safe_text, to_dotted_date
from ..model import ConclusionModel, empty_measurement, empty_defect


GENERAL_FIELDS = [
    ("report_num", "№ Заключения"),
    ("date", "Дата проведения"),
    ("record_num", "№ записи"),
    ("izdeliye", "Изделие"),
    ("detal", "Деталь"),
    ("order_num", "№ заказа"),
    ("object_kontr", "Объект контроля"),
    ("material", "Материал"),
    ("thickness", "Толщина"),
    ("volume_kontr", "Объём контроля"),
    ("norm_doc", "Нормативный документ"),
    ("map_kontr", "Карта контроля/Процедура"),
]

MEASUREMENT_FIELDS = [
    ("prog_obespec", "Программное обеспечение"),
    ("tip_defectoscope", "Тип дефектоскопа, зав. номер"),
    ("tip_skan_ustr", "Тип сканирующего устройства, зав. номер"),
    ("tip_preobr", "Тип преобразователя 1"),
    ("tip_preobr_sn", "Зав. номер 1"),
    ("tip_prism", "Тип призмы 1"),
    ("tip_prism_sn", "Зав. номер 1"),
    ("tip_preobr2", "Тип преобразователя 2 (TOFD)"),
    ("tip_preobr2_sn", "Зав. номер 2"),
    ("tip_prism2", "Тип призмы 2 (TOFD)"),
    ("tip_prism2_sn", "Зав. номер 2"),
    ("kanal", "Канал"),
    ("tip_skanirov", "Тип сканирования"),
    ("time_delay", "Временная развертка (мкс)"),
    ("angle", "Угол(ы) ввода"),
    ("focus", "Фокусировка"),
    ("dist_points", "Расстояние между точками ввода"),
    ("preamp", "Предусилитель"),
    ("averaging", "Усреднение"),
    ("offset_y", "Смещение шва/Шаг Y (мм)"),
    ("scan_range_x", "Диапазон сканирования/Шаг X (мм)"),
    ("sample_ref", "Обозначение образца"),
    ("setup_method", "Способ настройки"),
    ("we_level", "Уровень ВЭ"),
    ("gain", "Усиление"),
]

DEFECT_COLUMNS = [
    ("defect_object", "Объект"),
    ("plot_num", "№ участка"),
    ("amp_s_def", "Aдеф (дБ) / Sдеф (мм²)"),
    ("y_start_end", "Yн:Yк (мм)"),
    ("len_y", "Протяженность по Y (мм)"),
    ("x_start_end", "Xн:Xк (мм)"),
    ("len_x", "Протяженность по X (мм)"),
    ("z_start_end", "Zн:Zк (мм)"),
    ("height", "Высота (мм)"),
    ("defect_type", "Тип дефекта"),
    ("no_defect", "Дефектов не обнаружено"),
    ("quality", "Оценка качества"),
    ("fio", "ФИО Дефектоскописта"),
]


def _autocomplete(combo: QComboBox, values):
    combo.clear()
    combo.addItems([str(value) for value in values if value is not None])
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    completer = QCompleter(combo.model(), combo)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    combo.setCompleter(completer)

def _small_btn_style(color: str = "#3c3f41", border: str = "#555"):
    return f"""
        QPushButton {{
            background-color: {color};
            border: 1px solid {border};
            border-radius: 4px;
            color: #f2f2f2;
            font-size: 10pt;
            padding: 0px;
        }}
        QPushButton:hover {{ background-color: #4c5052; border: 1px solid #666; }}
        QPushButton:pressed {{ background-color: #2b2b2b; }}
    """


class ConclusionEditorDialog(QWidget):
    """Постоянно встроенный редактор общих сведений, каналов и дефектов."""

    submitted = pyqtSignal()
    import_requested = pyqtSignal()

    def __init__(self, parent, db: Database, general=None, measurements=None,
                 conclusion_id=None, journals=None):
        super().__init__(parent)
        self.db = db
        self.journals = journals or db.get_dict_values("journal_list")
        self.conclusion_id = conclusion_id
        self.general_data: dict = {}
        self.measurements_data: list = []
        self.model = ConclusionModel()
        
        self.current_meas_idx = -1
        self.current_defect_idx = None
        self._rebuilding_tree = False
        
        self.gen_edits: dict[str, QWidget] = {}
        self.meas_edits: dict[str, QWidget] = {}
        self.def_edits: dict[str, QWidget] = {}
        self._equipment_rows: dict[str, list[dict]] = {}
        
        if general:
            self.model.general.update(general)
            
        if measurements:
            measurements = self._split_merged_measurements(measurements)
            
        for raw in measurements or []:
            item = empty_measurement()
            item.update(raw)
            self.model.measurements.append(item)
            
        self._build_ui()
        self._rebuild_tree()
        
        if self.model.measurements:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(5, 5, 5, 5)
        
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # ================= ЛЕВАЯ ПАНЕЛЬ (Форма) =================
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # 1. Общие сведения (Светло-зеленый)
        common = QGroupBox("1. Общие сведения")
        common.setStyleSheet("""
            QGroupBox { border: 2px solid #99FF99; border-radius: 5px; margin-top: 15px; font-weight: bold; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 5px; left: 10px; color: #99FF99; }
        """)
        cols_layout = QHBoxLayout(common)
        left_col = QFormLayout()
        right_col = QFormLayout()
        
        journal = QComboBox()
        journals = list(self.journals)
        if DEFAULT_JOURNAL_NAME not in journals:
            journals.append(DEFAULT_JOURNAL_NAME)
        _autocomplete(journal, journals)
        self.gen_edits["journal"] = journal
        left_col.addRow("Журнал:", journal)

        date_edit = QDateEdit()
        date_edit.setDisplayFormat("dd.MM.yyyy")
        date_edit.setCalendarPopup(True)
        if self.model.general.get("date"):
            d = QDate.fromString(self.model.general["date"], "dd.MM.yyyy")
            if d.isValid():
                date_edit.setDate(d)
            else:
                date_edit.setDate(QDate.currentDate())
        else:
            date_edit.setDate(QDate.currentDate())
        self.gen_edits["date"] = date_edit
        left_col.addRow("Дата проведения:", date_edit)

        for key in ["izdeliye", "order_num", "material", "volume_kontr", "map_kontr"]:
            widget = QLineEdit()
            self.gen_edits[key] = widget
            label = next((lbl for k, lbl in GENERAL_FIELDS if k == key), key)
            left_col.addRow(label + ":", widget)

        self.method_combo = QComboBox()
        self.method_combo.addItems(["TOFD", "PAUT"])
        self.method_combo.currentTextChanged.connect(self._apply_method)
        self.gen_edits["method_kontr"] = self.method_combo
        right_col.addRow("Метод контроля:", self.method_combo)

        for key in ["report_num", "record_num", "detal", "object_kontr", "thickness", "norm_doc"]:
            widget = QLineEdit()
            self.gen_edits[key] = widget
            label = next((lbl for k, lbl in GENERAL_FIELDS if k == key), key)
            right_col.addRow(label + ":", widget)

        cols_layout.addLayout(left_col)
        cols_layout.addSpacing(20)
        cols_layout.addLayout(right_col)
        left_layout.addWidget(common)

        # 2. Оборудование (Бледно-бирюзовый)
        equip_box = QGroupBox("2. Оборудование")
        equip_box.setStyleSheet("""
            QGroupBox { border: 2px solid #AFEEEE; border-radius: 5px; margin-top: 15px; font-weight: bold; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 5px; left: 10px; color: #AFEEEE; }
        """)
        equip_layout = QVBoxLayout(equip_box)
        
        top_form = QFormLayout()
        equipment_keys = {
            "tip_defectoscope": None, "tip_skan_ustr": "scanner_list",
            "tip_preobr": "probe", "tip_preobr_sn": "probe",
            "tip_prism": "prism", "tip_prism_sn": "prism",
            "tip_preobr2": "probe", "tip_preobr2_sn": "probe",
            "tip_prism2": "prism", "tip_prism2_sn": "prism",
        }
        
        for key, label in MEASUREMENT_FIELDS[:3]:
            if key == "prog_obespec":
                edit = QLineEdit()
            else:
                edit = QComboBox()
                if key in equipment_keys:
                    category = equipment_keys[key]
                    if category is None:
                        values = self.db.get_defectoscope_display_list()
                    elif category == "scanner_list":
                        values = self.db.get_dict_values(category)
                    else:
                        values = []
                    _autocomplete(edit, values)
            self.meas_edits[key] = edit
            top_form.addRow(label + ":", edit)
        equip_layout.addLayout(top_form)
        
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #AFEEEE;")
        equip_layout.addWidget(line)

        grid_eq = QGridLayout()
        grid_eq.setHorizontalSpacing(15)
        pairs = [("tip_preobr", "tip_preobr_sn"), ("tip_prism", "tip_prism_sn"), 
                 ("tip_preobr2", "tip_preobr2_sn"), ("tip_prism2", "tip_prism2_sn")]
        
        for row, (type_key, sn_key) in enumerate(pairs):
            t_label = next(lbl for k, lbl in MEASUREMENT_FIELDS if k == type_key)
            s_label = next(lbl for k, lbl in MEASUREMENT_FIELDS if k == sn_key)
            
            t_edit = QComboBox()
            category = equipment_keys[type_key]
            if category: 
                raw_eq = self.db.get_equipment(category, "TOFD")
                types = sorted({r["type"] for r in raw_eq if r.get("type")})
                _autocomplete(t_edit, types)
            self.meas_edits[type_key] = t_edit
            
            s_edit = QComboBox()
            self.meas_edits[sn_key] = s_edit
            
            grid_eq.addWidget(QLabel(t_label + ":"), row, 0, alignment=Qt.AlignmentFlag.AlignRight)
            grid_eq.addWidget(t_edit, row, 1)
            grid_eq.addWidget(QLabel(s_label + ":"), row, 2, alignment=Qt.AlignmentFlag.AlignRight)
            grid_eq.addWidget(s_edit, row, 3)
            
        grid_eq.setColumnStretch(1, 1)
        grid_eq.setColumnStretch(3, 1)
        equip_layout.addLayout(grid_eq)
        left_layout.addWidget(equip_box)

        # 3. Параметры настройки (Синий)
        params_box = QGroupBox("3. Параметры настройки")
        params_box.setStyleSheet("""
            QGroupBox { border: 2px solid #556EE6; border-radius: 5px; margin-top: 15px; font-weight: bold; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 5px; left: 10px; color: #556EE6; }
        """)
        params_layout = QGridLayout(params_box)
        param_values = {
            "tip_skanirov": ["Параллельный", "Непараллельный", "Поперечно-продольный", "Продольно-поперечный"],
            "preamp": ["вкл.", "выкл."],
            "sample_ref": self.db.get_dict_values("sample_list"),
            "setup_method": ["ВРЧ", "АРД"],
            "we_level": ["≥40%", "≥80%"],
        }
        row, col = 0, 0
        for key, label in MEASUREMENT_FIELDS[11:]:
            edit = QComboBox() if key in param_values else QLineEdit()
            if isinstance(edit, QComboBox):
                if key in ("tip_skanirov", "preamp"):
                    edit.addItems(param_values[key])
                    edit.setEditable(False)
                else:
                    _autocomplete(edit, param_values[key])
            self.meas_edits[key] = edit
            params_layout.addWidget(QLabel(label + ":"), row, col, alignment=Qt.AlignmentFlag.AlignRight)
            params_layout.addWidget(edit, row, col + 1)
            col += 2
            if col >= 4: col = 0; row += 1
            
        params_layout.setColumnStretch(1, 1)
        params_layout.setColumnStretch(3, 1)
        
        for cat, tk, sk in (("probe", "tip_preobr", "tip_preobr_sn"), ("prism", "tip_prism", "tip_prism_sn"), 
                            ("probe", "tip_preobr2", "tip_preobr2_sn"), ("prism", "tip_prism2", "tip_prism2_sn")):
            self.meas_edits[tk].currentTextChanged.connect(lambda text, c=cat, s=sk: self._update_serials(c, text, s))
            
        self.meas_edits["tip_defectoscope"].currentTextChanged.connect(lambda _: self._refresh_equipment())
        
        btn_add_channel = QPushButton("➕ Добавить преобразователь")
        btn_add_channel.setStyleSheet("background-color: #556EE6; color: white; padding: 8px; font-weight: bold; border-radius: 4px;")
        btn_add_channel.clicked.connect(lambda: self._add_channel())
        params_layout.addWidget(btn_add_channel, row + 1, 0, 1, 4)
        
        left_layout.addWidget(params_box)

        # 4. Дефекты (Бирюзовый)
        def_box = QGroupBox("4. Результаты контроля (Дефекты)")
        def_box.setStyleSheet("""
            QGroupBox { border: 2px solid #3EC1D3; border-radius: 5px; margin-top: 15px; font-weight: bold; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 5px; left: 10px; color: #3EC1D3; }
        """)
        def_main_layout = QVBoxLayout(def_box)
        
        def_grid = QGridLayout()
        
        self.no_defect = QCheckBox("Дефектов не обнаружено")
        self.no_defect.toggled.connect(self._toggle_no_defect)
        def_grid.addWidget(self.no_defect, 0, 0, 1, 2)
        
        def_grid.addWidget(QLabel("Объект:"), 0, 2, alignment=Qt.AlignmentFlag.AlignRight)
        self.def_edits["defect_object"] = QLineEdit()
        def_grid.addWidget(self.def_edits["defect_object"], 0, 3)
        
        row, col = 1, 0
        for key, label in DEFECT_COLUMNS[1:10]:
            widget = QComboBox() if key == "defect_type" else QLineEdit()
            if key == "defect_type":
                widget.addItems(["Поверхностный", "Подповерхностный", "Объёмный", "Плоскостной"])
                widget.setEditable(True)
            self.def_edits[key] = widget
            def_grid.addWidget(QLabel(label + ":"), row, col, alignment=Qt.AlignmentFlag.AlignRight)
            def_grid.addWidget(widget, row, col + 1)
            col += 2
            if col >= 4: col = 0; row += 1
            
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["уд.", "неуд."])
        self.quality_combo.setEditable(True)
        self.def_edits["quality"] = self.quality_combo
        def_grid.addWidget(QLabel("Оценка:"), row, col, alignment=Qt.AlignmentFlag.AlignRight)
        def_grid.addWidget(self.quality_combo, row, col + 1)
        
        def_main_layout.addLayout(def_grid)
        
        # ФИО (Фиолетовый)
        fio_box = QGroupBox("ФИО Дефектоскописта")
        fio_box.setStyleSheet("""
            QGroupBox { border: 1px solid #574B90; border-radius: 3px; margin-top: 10px; font-weight: bold; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 5px; left: 10px; color: #574B90; }
        """)
        self.fio_layout = QVBoxLayout(fio_box)
        self.fio_layout.setContentsMargins(10, 10, 10, 10)
        self.fio_combos = []
        self.add_fio_field()
        
        btn_add_fio = QPushButton("➕ Добавить ФИО")
        btn_add_fio.setStyleSheet("background-color: #574B90; color: white; padding: 5px; font-weight: bold; border-radius: 4px;")
        btn_add_fio.clicked.connect(lambda: self.add_fio_field())
        self.fio_layout.addWidget(btn_add_fio)
        
        def_main_layout.addWidget(fio_box)
        left_layout.addWidget(def_box)

        btn_def_layout = QHBoxLayout()
        btn_add_defect = QPushButton("➕ Добавить дефект")
        btn_add_defect.setStyleSheet("background-color: #3EC1D2; color: white; padding: 8px; font-weight: bold; border-radius: 4px;")
        btn_add_defect.clicked.connect(lambda: self._add_defect())
        btn_def_layout.addWidget(btn_add_defect)
        left_layout.addLayout(btn_def_layout)

        left_layout.addStretch()
        
        # НИЖНЯЯ ПАНЕЛЬ: Кнопки импорта и сохранения
        bottom_btn_layout = QHBoxLayout()
        
        btn_import = QPushButton("📂 Импорт Excel")
        btn_import.setStyleSheet("background-color: #FF9800; color: white; padding: 10px; font-weight: bold; border-radius: 4px;")
        btn_import.clicked.connect(lambda: self.import_requested.emit())
        bottom_btn_layout.addWidget(btn_import)
        
        btn_save = QPushButton("💾 Сохранить всё заключение в БД")
        btn_save.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px; font-weight: bold; border-radius: 4px;")
        btn_save.clicked.connect(lambda: self.save())
        bottom_btn_layout.addWidget(btn_save)
        
        left_layout.addLayout(bottom_btn_layout)

        left_scroll.setWidget(left_widget)
        self.splitter.addWidget(left_scroll)

        # ================= ПРАВАЯ ПАНЕЛЬ (Дерево) =================
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        right_layout.addWidget(QLabel("<b>Структура заключения (Управление)</b>"))
        
        move_layout = QHBoxLayout()
        
        btn_up_ch = QPushButton("⬆")
        btn_up_ch.setFixedSize(32, 32)
        btn_up_ch.setToolTip("Переместить канал вверх")
        btn_up_ch.setStyleSheet(_small_btn_style("#556EE6", "#556EE6"))
        btn_up_ch.clicked.connect(lambda: self._move_channel(-1))
        
        btn_dn_ch = QPushButton("⬇")
        btn_dn_ch.setFixedSize(32, 32)
        btn_dn_ch.setToolTip("Переместить канал вниз")
        btn_dn_ch.setStyleSheet(_small_btn_style("#556EE6", "#556EE6"))
        btn_dn_ch.clicked.connect(lambda: self._move_channel(1))
        
        btn_up_df = QPushButton("⬆")
        btn_up_df.setFixedSize(32, 32)
        btn_up_df.setToolTip("Переместить дефект вверх")
        btn_up_df.setStyleSheet(_small_btn_style("#3EC1D2", "#3EC1D2"))
        btn_up_df.clicked.connect(lambda: self._move_defect(-1))
        
        btn_dn_df = QPushButton("⬇")
        btn_dn_df.setFixedSize(32, 32)
        btn_dn_df.setToolTip("Переместить дефект вниз")
        btn_dn_df.setStyleSheet(_small_btn_style("#3EC1D2", "#3EC1D2"))
        btn_dn_df.clicked.connect(lambda: self._move_defect(1))

        btn_move_df = QPushButton("➡️")
        btn_move_df.setFixedSize(32, 32)
        btn_move_df.setToolTip("Переместить дефект на другой канал")
        btn_move_df.setStyleSheet(_small_btn_style("#3EC1D2", "#3EC1D2"))
        btn_move_df.clicked.connect(lambda: self._move_defect_to_channel())
        
        move_layout.addWidget(btn_up_ch)
        move_layout.addWidget(btn_dn_ch)
        move_layout.addSpacing(15)
        move_layout.addWidget(btn_up_df)
        move_layout.addWidget(btn_dn_df)
        move_layout.addWidget(btn_move_df)
        move_layout.addStretch()
        
        right_layout.addLayout(move_layout)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.currentItemChanged.connect(self._on_tree_selected)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        
        right_layout.addWidget(self.tree, 1)

        self.splitter.addWidget(right_widget)
        
        self.splitter.setSizes([850, 350])
        root.addWidget(self.splitter)
        
        self._fill_general()

    def save_layout(self, user_fio: str):
        settings = QSettings("UZK_App", "UZK_v4")
        settings.setValue(f"editor_splitter_state_{user_fio}", self.splitter.saveState())

    def restore_layout(self, user_fio: str):
        settings = QSettings("UZK_App", "UZK_v4")
        state = settings.value(f"editor_splitter_state_{user_fio}")
        if state:
            self.splitter.restoreState(state)

    # ================= ЛОГИКА =================

    def _split_merged_measurements(self, measurements):
        """При загрузке разъединяет каналы, которые были склеены (если у них несколько объектов)."""
        split_measurements = []
        for m in measurements:
            has_real_defects = any(str(d.get("no_defect") or "").strip() != "Да" for d in m.get("defects", []))
            
            if not has_real_defects and m.get("defects"):
                d = m["defects"][0]
                objs = [o.strip() for o in str(d.get("defect_object") or "").split(",") if o.strip()]
                if len(objs) > 1:
                    for obj in objs:
                        new_m = copy.deepcopy(m)
                        new_d = copy.deepcopy(d)
                        new_d["defect_object"] = obj
                        new_m["defects"] = [new_d]
                        split_measurements.append(new_m)
                    continue
            split_measurements.append(m)
        return split_measurements

    def load_data(self, general=None, measurements=None, conclusion_id=None):
        self._commit_current()
        self.model = ConclusionModel()
        if general:
            self.model.general.update(general)
            
        if measurements:
            measurements = self._split_merged_measurements(measurements)
            
        for raw in measurements or []:
            item = empty_measurement()
            item.update(raw)
            self.model.measurements.append(item)
            
        self.conclusion_id = conclusion_id
        self._fill_general()
        self._rebuild_tree()
        
        self.current_meas_idx = -1
        self.current_defect_idx = None
        if self.model.measurements:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        else:
            self._clear_defect_form()

    def _show_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item: return
        self.tree.setCurrentItem(item)
        
        menu = QMenu(self)
        delete_action = menu.addAction("🗑 Удалить выбранное")
        action = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if action == delete_action:
            self._del_item()

    def _format_defect_desc(self, d: dict) -> str:
        parts = []
        obj = str(d.get("defect_object", "")).strip()
        if obj:
            parts.append(f"Объект: {obj}")
            
        if d.get("no_defect") == "Да":
            q = d.get("quality", "")
            fio = d.get("fio", "")
            parts.append(f"Дефектов не обнаружено. Оценка: {q or 'уд.'}, ФИО: {fio or '—'}")
        else:
            if d.get("amp_s_def"): parts.append(f"A/S: {d['amp_s_def']}")
            if d.get("y_start_end"): parts.append(f"Y: {d['y_start_end']}")
            if d.get("x_start_end"): parts.append(f"X: {d['x_start_end']}")
            if d.get("z_start_end"): parts.append(f"Z: {d['z_start_end']}")
            if d.get("height"): parts.append(f"H: {d['height']}")
            if d.get("defect_type"): parts.append(f"Тип: {d['defect_type']}")
            if d.get("quality"): parts.append(f"Оценка: {d['quality']}")
            if d.get("fio"): parts.append(f"ФИО: {d['fio']}")
            
        return ", ".join(parts) if parts else "Дефект (нет данных)"

    def _fill_general(self):
        for key, widget in self.gen_edits.items():
            value = safe_text(self.model.general.get(key))
            if key == "journal" and not value and not self.conclusion_id:
                value = DEFAULT_JOURNAL_NAME
                self.model.general[key] = value
            if key == "date" and not value:
                value = datetime.date.today().strftime("%d.%m.%Y")
                self.model.general[key] = value
                
            if isinstance(widget, QComboBox):
                widget.setCurrentText(value)
            elif isinstance(widget, QLineEdit):
                widget.setText(to_dotted_date(value) if key == "date" else value)
            elif isinstance(widget, QDateEdit):
                d = QDate.fromString(to_dotted_date(value), "dd.MM.yyyy")
                if d.isValid():
                    widget.setDate(d)
                else:
                    widget.setDate(QDate.currentDate())

    def _rebuild_tree(self):
        self._rebuilding_tree = True
        self.tree.clear()
        
        for i, m in enumerate(self.model.measurements):
            kanal = m.get("kanal") or str(i+1)
            p1 = m.get("tip_preobr") or "—"
            p1_sn = m.get("tip_preobr_sn") or ""
            
            probe_str = f"{p1} {p1_sn}".strip()
            item_text = f"{probe_str} (Канал {kanal})" if probe_str else f"(Канал {kanal})"
            
            item = QTreeWidgetItem(self.tree, [item_text])
            item.setData(0, Qt.ItemDataRole.UserRole, (i, None))
            
            for j, d in enumerate(m.get("defects", [])):
                plot = d.get("plot_num") or "—"
                desc = self._format_defect_desc(d)
                
                child = QTreeWidgetItem(item, [f"Участок {plot}: {desc}"])
                child.setData(0, Qt.ItemDataRole.UserRole, (i, j))
                
            item.setExpanded(True)
        self._rebuilding_tree = False

    def _on_tree_selected(self, current, previous):
        if self._rebuilding_tree:
            return
            
        self._commit_current()
        
        if not current:
            return
            
        data = current.data(0, Qt.ItemDataRole.UserRole)
        if not data: return
        
        i, j = data
        self.current_meas_idx = i
        self.current_defect_idx = j
        
        m = self.model.measurements[i]
        self._populate_measurement(m)
        
        if j is not None:
            if 0 <= j < len(m["defects"]):
                d = m["defects"][j]
                self._populate_defect(d)
        else:
            self._clear_defect_form()

    def _populate_measurement(self, m: dict):
        for key, widget in self.meas_edits.items():
            self._set_val(widget, m.get(key))
        self._refresh_equipment()
        self._apply_method(self.method_combo.currentText())

    def _populate_defect(self, d: dict):
        self.def_edits["defect_object"].setText(safe_text(d.get("defect_object")))
        self.no_defect.setChecked(d.get("no_defect") == "Да")
        
        self._clear_fio_fields()
        fios = safe_text(d.get("fio")).split(",")
        for fio in fios:
            if fio.strip():
                self.add_fio_field(fio.strip())
                
        for key, widget in self.def_edits.items():
            if key != "defect_object":
                self._set_val(widget, d.get(key))
        self._toggle_no_defect(self.no_defect.isChecked())

    def _clear_defect_form(self):
        self.def_edits["defect_object"].clear()
        self.no_defect.setChecked(False)
        self._clear_fio_fields()
        for key, widget in self.def_edits.items():
            if key != "defect_object":
                self._set_val(widget, "")

    def _commit_current(self):
        if self.current_meas_idx < 0 or self.current_meas_idx >= len(self.model.measurements):
            return
            
        m = self.model.measurements[self.current_meas_idx]
        for key, widget in self.meas_edits.items():
            m[key] = self._get_val(widget)
            
        if self.current_defect_idx is not None and 0 <= self.current_defect_idx < len(m["defects"]):
            d = m["defects"][self.current_defect_idx]
            d["defect_object"] = self.def_edits["defect_object"].text()
            d["no_defect"] = "Да" if self.no_defect.isChecked() else ""
            d["fio"] = ", ".join(c.currentText().strip() for c in self.fio_combos if c.currentText().strip())
            for key, widget in self.def_edits.items():
                if key != "defect_object":
                    d[key] = self._get_val(widget)
                    
        top = self.tree.topLevelItem(self.current_meas_idx)
        if top:
            kanal = m.get("kanal") or str(self.current_meas_idx + 1)
            p1 = m.get("tip_preobr") or "—"
            p1_sn = m.get("tip_preobr_sn") or ""
            probe_str = f"{p1} {p1_sn}".strip()
            item_text = f"{probe_str} (Канал {kanal})" if probe_str else f"(Канал {kanal})"
            top.setText(0, item_text)
            
            if self.current_defect_idx is not None and 0 <= self.current_defect_idx < top.childCount():
                child = top.child(self.current_defect_idx)
                if child and self.current_defect_idx < len(m["defects"]):
                    dd = m["defects"][self.current_defect_idx]
                    plot = dd.get("plot_num") or "—"
                    desc = self._format_defect_desc(dd)
                    child.setText(0, f"Участок {plot}: {desc}")

    def _add_channel(self):
        self._commit_current()
        
        m = empty_measurement()
        for key, widget in self.meas_edits.items():
            m[key] = self._get_val(widget)
            
        self.model.measurements.append(m)
        self._rebuild_tree()
        idx = len(self.model.measurements) - 1
        self.tree.setCurrentItem(self.tree.topLevelItem(idx))
        self._apply_method(self.method_combo.currentText())

    def _del_item(self):
        item = self.tree.currentItem()
        if not item: return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data: return
        i, j = data
        
        if j is None:
            if QMessageBox.question(self, "Подтверждение", "Удалить выбранный преобразователь (канал) и все его дефекты?") != QMessageBox.StandardButton.Yes:
                return
            del self.model.measurements[i]
            self.current_meas_idx = -1
            self.current_defect_idx = None
        else:
            if QMessageBox.question(self, "Подтверждение", "Удалить выбранный дефект?") != QMessageBox.StandardButton.Yes:
                return
            del self.model.measurements[i]["defects"][j]
            self.current_defect_idx = None
            
        self._rebuild_tree()
        if self.tree.topLevelItemCount() > 0:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def _add_defect(self):
        if self.current_meas_idx < 0:
            self._add_channel()
            
        d = empty_defect()
        d["defect_object"] = self.def_edits["defect_object"].text().strip()
        d["no_defect"] = "Да" if self.no_defect.isChecked() else ""
        d["fio"] = ", ".join(c.currentText().strip() for c in self.fio_combos if c.currentText().strip())
        for key, widget in self.def_edits.items():
            if key != "defect_object":
                d[key] = self._get_val(widget)
                
        if not d["no_defect"] and not any(v for k, v in d.items() if k not in ("defect_object", "no_defect")):
            QMessageBox.warning(self, "Внимание", "Введите данные дефекта или поставьте галочку 'Дефектов не обнаружено'!")
            return

        m = self.model.measurements[self.current_meas_idx]
        for key, widget in self.meas_edits.items():
            m[key] = self._get_val(widget)

        m["defects"].append(d)
        
        self._rebuilding_tree = True
        self._rebuild_tree()
        self._rebuilding_tree = False
        
        item = self.tree.topLevelItem(self.current_meas_idx)
        item.setExpanded(True)
        new_child = item.child(len(m["defects"]) - 1)
        
        self.current_defect_idx = None
        self.tree.setCurrentItem(new_child)
        
        self.current_defect_idx = None
        self.no_defect.setChecked(False)
        for key, widget in self.def_edits.items():
            if key not in ("defect_object", "quality"):
                self._set_val(widget, "")

    def _move_channel(self, step):
        item = self.tree.currentItem()
        if not item: return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data[1] is not None: return
        
        i = data[0]
        target = i + step
        if not 0 <= target < len(self.model.measurements): return
        
        self._commit_current()
        m = self.model.measurements
        m[i], m[target] = m[target], m[i]
        self._rebuild_tree()
        self.tree.setCurrentItem(self.tree.topLevelItem(target))

    def _move_defect(self, step):
        if self.current_meas_idx < 0 or self.current_defect_idx is None: return
        m = self.model.measurements[self.current_meas_idx]
        defects = m["defects"]
        target = self.current_defect_idx + step
        if not 0 <= target < len(defects): return
        
        self._commit_current()
        defects[self.current_defect_idx], defects[target] = defects[target], defects[self.current_defect_idx]
        self._rebuild_tree()
        
        item = self.tree.topLevelItem(self.current_meas_idx)
        self.tree.setCurrentItem(item.child(target))

    def _move_defect_to_channel(self):
        if self.current_meas_idx < 0 or self.current_defect_idx is None:
            QMessageBox.warning(self, "Ошибка", "Выберите дефект в дереве!")
            return
            
        if len(self.model.measurements) < 2:
            QMessageBox.warning(self, "Ошибка", "Нет других преобразователей для перемещения!")
            return

        self._commit_current()
        
        options = []
        target_indices = {}
        for index, measurement in enumerate(self.model.measurements):
            if index == self.current_meas_idx:
                continue
            p1 = safe_text(measurement.get("tip_preobr"))
            p1_sn = safe_text(measurement.get("tip_preobr_sn"))
            probe_str = f"{p1} {p1_sn}".strip()
            kanal = safe_text(measurement.get("kanal")) or str(index + 1)
            name = f"{probe_str} (Канал {kanal})"
            
            option = f"{index + 1}. {name}"
            options.append(option)
            target_indices[option] = index

        choice, accepted = QInputDialog.getItem(
            self, "Переместить дефект",
            "Введите номер преобразователя для перемещения:", options, 0, False)
            
        if not accepted or not choice:
            return
            
        target_index = target_indices[choice]
        defect = self.model.measurements[self.current_meas_idx]["defects"].pop(self.current_defect_idx)
        self.model.measurements[target_index]["defects"].append(defect)
        
        self.current_defect_idx = None
        self._rebuild_tree()
        
        self.tree.setCurrentItem(self.tree.topLevelItem(target_index))

    def _apply_method(self, method):
        is_tofd = method == "TOFD"
        for key in ("tip_preobr2", "tip_preobr2_sn", "tip_prism2", "tip_prism2_sn", "preamp", "dist_points", "averaging"):
            self.meas_edits[key].setEnabled(is_tofd)
        self.meas_edits["setup_method"].setEnabled(not is_tofd)
        self.def_edits["amp_s_def"].setEnabled(not is_tofd and not self.no_defect.isChecked())
        self._refresh_equipment()

    def _toggle_no_defect(self, checked):
        for key, widget in self.def_edits.items():
            if key not in ("plot_num", "quality", "defect_object"):
                widget.setEnabled(not checked)
        for combo in self.fio_combos:
            combo.setEnabled(True)
        self._apply_method(self.method_combo.currentText())

    def _update_serials(self, category, eq_type, serial_key):
        widget = self.meas_edits[serial_key]
        current = widget.currentText()
        serials = sorted({r["serial"] for r in self._equipment_rows.get(category, []) if r["type"] == eq_type and r.get("serial")})
        _autocomplete(widget, serials)
        widget.setCurrentText(current)

    def _refresh_equipment(self):
        method = self.method_combo.currentText()
        scope = self._get_val(self.meas_edits["tip_defectoscope"])
        dev_id = self.db.get_defectoscope_id_by_str(scope)
        
        cats = {"probe", "prism"}
        self._equipment_rows = {c: self.db.get_equipment(c, method, dev_id) for c in cats}
        
        for cat, tk, sk in (("probe", "tip_preobr", "tip_preobr_sn"), ("prism", "tip_prism", "tip_prism_sn"), 
                            ("probe", "tip_preobr2", "tip_preobr2_sn"), ("prism", "tip_prism2", "tip_prism2_sn")):
            tw = self.meas_edits[tk]
            sel = tw.currentText()
            types = sorted({r["type"] for r in self._equipment_rows[cat] if r.get("type")})
            _autocomplete(tw, types)
            tw.setCurrentText(sel)
            self._update_serials(cat, sel, sk)

    def add_fio_field(self, value=""):
        if isinstance(value, bool):
            value = ""

        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        combo = QComboBox()
        _autocomplete(combo, self.db.get_dict_values("fio_list"))
        combo.setCurrentText(value)
        combo.setMinimumWidth(250)
        
        btn = QPushButton("✖")
        btn.setFixedSize(30, 30)
        btn.setStyleSheet(_small_btn_style())
        btn.clicked.connect(lambda: self._remove_fio(row))
        
        lay.addWidget(combo, 1)
        lay.addWidget(btn)
        self.fio_layout.insertWidget(self.fio_layout.count() - 1, row)
        self.fio_combos.append(combo)

    def _remove_fio(self, row):
        if len(self.fio_combos) <= 1: return
        idx = self.fio_layout.indexOf(row)
        if idx >= 0:
            self.fio_layout.removeWidget(row)
            row.deleteLater()
            self.fio_combos.pop(idx)

    def _clear_fio_fields(self):
        while len(self.fio_combos) > 1:
            self._remove_fio(self.fio_combos[-1].parentWidget())
        self.fio_combos[0].setCurrentText("")

    @staticmethod
    def _set_val(w: QWidget, v):
        val = safe_text(v)
        if isinstance(w, QComboBox):
            w.setCurrentText(val)
        elif isinstance(w, QLineEdit):
            w.setText(val)
        elif isinstance(w, QDateEdit):
            d = QDate.fromString(to_dotted_date(val), "dd.MM.yyyy")
            if d.isValid():
                w.setDate(d)
            else:
                w.setDate(QDate.currentDate())

    @staticmethod
    def _get_val(w: QWidget):
        if isinstance(w, QComboBox): 
            return w.currentText().strip()
        if isinstance(w, QLineEdit): 
            return w.text().strip()
        if isinstance(w, QDateEdit):
            return w.date().toString("dd.MM.yyyy")
        return ""

    def save(self):
        self._commit_current()
        general = dict(self.model.general)
        for key, widget in self.gen_edits.items():
            general[key] = self._get_val(widget)
            
        if not general.get("report_num") or not general.get("date"):
            QMessageBox.warning(self, "Ошибка", "№ Заключения и Дата обязательны!")
            return
            
        if not self.model.measurements:
            QMessageBox.warning(self, "Ошибка", "Нет ни одного преобразователя!")
            return

        measurements = []
        qualities = []
        fios = []
        for m in self.model.measurements:
            item = {k: safe_text(v) for k, v in m.items() if k != "defects" and not k.startswith("_")}
            item["defects"] = []
            for d in m.get("defects", []):
                dd = {k: safe_text(v) for k, v in d.items()}
                item["defects"].append(dd)
                if dd.get("quality"):
                    qualities.append(dd["quality"])
                for f in dd.get("fio", "").split(","):
                    if f.strip() and f.strip() not in fios:
                        fios.append(f.strip())
            measurements.append(item)

        def _has_real_defects(m_data):
            for d in m_data.get("defects", []):
                if str(d.get("no_defect") or "").strip() != "Да":
                    return True
            return False

        def _get_sig(m_data):
            return tuple(str(m_data.get(k) or "").strip() for k in [
                'prog_obespec', 'tip_defectoscope', 'tip_skan_ustr', 
                'tip_preobr', 'tip_preobr_sn', 'tip_prism', 'tip_prism_sn', 
                'tip_preobr2', 'tip_preobr2_sn', 'tip_prism2', 'tip_prism2_sn', 
                'kanal', 'tip_skanirov', 'time_delay', 'angle', 'focus', 
                'dist_points', 'preamp', 'averaging', 'offset_y', 'scan_range_x', 
                'sample_ref', 'setup_method', 'we_level', 'gain'
            ])

        merged_measurements = []
        for m in measurements:
            is_defect = _has_real_defects(m)
            match = None
            if not is_defect:
                for existing in merged_measurements:
                    if not _has_real_defects(existing) and _get_sig(existing) == _get_sig(m):
                        match = existing
                        break

            if match:
                # ИСПРАВЛЕНИЕ: Объединяем объекты контроля
                if match.get("defects") and m.get("defects"):
                    d1 = match["defects"][0]
                    d2 = m["defects"][0]
                    merged_objs = []
                    for o in str(d1.get("defect_object") or "").split(","):
                        if o.strip() and o.strip() not in merged_objs:
                            merged_objs.append(o.strip())
                    for o in str(d2.get("defect_object") or "").split(","):
                        if o.strip() and o.strip() not in merged_objs:
                            merged_objs.append(o.strip())
                    d1["defect_object"] = ", ".join(merged_objs)
                elif m.get("defects"):
                    match["defects"].extend(m["defects"])
            else:
                merged_measurements.append(m)
        measurements = merged_measurements

        general["quality"] = "неуд." if any(q.casefold().rstrip(".") == "неуд" for q in qualities) else "уд."
        general["fio"] = ", ".join(fios)
        
        self.general_data = general
        self.measurements_data = measurements
        self.submitted.emit()