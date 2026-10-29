# -*- coding: utf-8 -*-
"""Модель данных заключения для v4.

Хранит «общие сведения», список измерений (преобразователей) и дефекты в
обычных dict-структурах — тех же, что использовались во v3 как
self.current_measurements. Никакого GUI здесь нет: это доменная модель,
за которую отвечает вкладка регистрации и импорт Excel.
"""
from .helpers import safe_text


GENERAL_KEYS = [
    "report_num", "date", "record_num", "izdeliye", "detal", "order_num",
    "object_kontr", "material", "thickness", "volume_kontr", "norm_doc",
    "method_kontr", "map_kontr", "quality", "fio", "journal",
]

MEASUREMENT_KEYS = [
    "prog_obespec", "tip_defectoscope", "tip_skan_ustr",
    "tip_preobr", "tip_preobr_sn", "tip_prism", "tip_prism_sn",
    "tip_preobr2", "tip_preobr2_sn", "tip_prism2", "tip_prism2_sn",
    "kanal", "tip_skanirov", "time_delay", "angle", "focus", "dist_points",
    "preamp", "averaging", "offset_y", "scan_range_x", "sample_ref",
    "setup_method", "we_level", "gain",
]

DEFECT_KEYS = [
    "defect_object", "plot_num", "amp_s_def", "y_start_end", "len_y",
    "x_start_end", "len_x", "z_start_end", "height", "defect_type",
    "no_defect", "quality", "fio",
]


def empty_measurement():
    m = {k: "" for k in MEASUREMENT_KEYS}
    m["defects"] = []
    return m


def empty_defect():
    return {k: "" for k in DEFECT_KEYS}


def format_measurement_name(m):
    p1 = safe_text(m.get("tip_preobr"))
    s1 = safe_text(m.get("tip_preobr_sn"))
    p2 = safe_text(m.get("tip_preobr2"))
    s2 = safe_text(m.get("tip_preobr2_sn"))
    if p2 and s2:
        name = f"{p1} (№{s1}), {p2} (№{s2})"
    elif p2:
        name = f"{p1} (№{s1}), {p2}"
    else:
        name = f"{p1} (№{s1})"
    kanal = safe_text(m.get("kanal"))
    if kanal:
        name = f"{name} — канал {kanal}"
    return name


def normalize_measurements(raw_measurements):
    """Очищает данные перед сохранением в БД (как save_full_conclusion в v3)."""
    normalized = []
    for m_data in raw_measurements:
        if not isinstance(m_data, dict):
            continue
        cleaned = {k: safe_text(v) for k, v in m_data.items()
                   if k not in ('defects', '_import_object')}
        cleaned['defects'] = []
        for defect in m_data.get('defects', []):
            if not isinstance(defect, dict):
                continue
            cleaned['defects'].append({k: safe_text(v) for k, v in defect.items()})
        normalized.append(cleaned)
    return normalized


class ConclusionModel:
    """Состояние вкладки «Регистрация заключения»."""

    def __init__(self):
        self.general = {k: "" for k in GENERAL_KEYS}
        self.measurements = []
        self.editing_id = None

    def clear(self):
        self.general = {k: "" for k in GENERAL_KEYS}
        self.measurements = []
        self.editing_id = None

    def measurement_from_db(self, row_tuple):
        """row_tuple — 25 значений измерений из SELECT (порядок как в v3)."""
        m = empty_measurement()
        for key, value in zip(MEASUREMENT_KEYS, row_tuple):
            m[key] = safe_text(value)
        return m