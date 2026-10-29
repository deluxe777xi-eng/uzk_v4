# -*- coding: utf-8 -*-
"""Чистые (без GUI) вычисления для журналов и заключений v4.

Перенос логики v3: uzk_app/journal_mixin.py (данные) и
form_mixin.py (_load_old_conclusion_state/_build_diff/...):
  * пакетная выборка строк журнала;
  * объединение одинаковых измерений (_merge_measurements);
  * diff-отчёт при редактировании заключения;
  * статусы подписей.
"""
import datetime
import json

from .helpers import safe_text


# ---------------------------------------------------------------
#  Выборка идентификаторов и строк журнала
# ---------------------------------------------------------------

def get_latest_conclusion_ids(conn, journal_name):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, report_num, record_num FROM conclusions WHERE journal = ? ORDER BY id DESC",
        (journal_name,)
    )
    rows = cursor.fetchall()

    result = []
    seen_report_nums = set()
    seen_record_nums = set()
    for report_id, report_num, record_num in rows:
        same_report = report_num is not None and report_num in seen_report_nums
        same_record = record_num not in (None, "") and record_num in seen_record_nums
        if report_num is not None:
            seen_report_nums.add(report_num)
        if record_num not in (None, ""):
            seen_record_nums.add(record_num)
        if same_report or same_record:
            continue
        result.append((report_id, report_num))

    def _sort_key(report_num):
        s = str(report_num or "").strip()
        if not s:
            return (2, 0, 0)
        if "/" in s:
            head, _, tail = s.partition("/")
            head = head.strip()
            tail = tail.strip()
            if head.isdigit():
                frac = int(tail) if tail.isdigit() else 0
                return (0, int(head), frac)
            return (1, 0, 0)
        if s.isdigit():
            return (0, int(s), 0)
        return (1, 0, 0)

    result.sort(key=lambda item: _sort_key(item[1]))
    return [report_id for report_id, _ in result]


def fetch_journal_rows(conn, report_ids, batch_size=400):
    ids = list(report_ids)
    if not ids:
        return []

    grouped = {}
    cursor = conn.cursor()
    for batch_start in range(0, len(ids), batch_size):
        batch = ids[batch_start:batch_start + batch_size]
        placeholders = ",".join("?" for _ in batch)
        cursor.execute(f"""
            SELECT
                c.id, c.report_num, c.date, c.izdeliye, c.detal, c.order_num,
                c.object_kontr, c.record_num, c.signature, d.quality, d.fio
            FROM conclusions c
            LEFT JOIN measurements m ON m.conclusion_id = c.id
            LEFT JOIN defects d ON d.measurement_id = m.id
            WHERE c.id IN ({placeholders})
            ORDER BY c.id DESC, m.id, d.id
        """, tuple(batch))

        for row in cursor.fetchall():
            report_id = row[0]
            item = grouped.get(report_id)
            if item is None:
                item = {
                    'report_num': row[1] or "", 'date': row[2] or "", 'izdeliye': row[3] or "",
                    'detal': row[4] or "", 'order_num': row[5] or "", 'object_kontr': row[6] or "",
                    'record_num': row[7] or "", 'signature': row[8] or "",
                    'overall_quality': "уд.", 'fio_set': set(),
                }
                grouped[report_id] = item

            quality = row[9]
            fio_value = row[10]
            for fio_name in (fio_value or "").split(","):
                fio_name = fio_name.strip()
                if fio_name:
                    item['fio_set'].add(fio_name)
            if (quality or "").strip().casefold().rstrip(".") == "неуд":
                item['overall_quality'] = "неуд."

    result = []
    for report_id in ids:
        item = grouped.get(report_id)
        if not item:
            continue

        fio_set = item['fio_set']
        try:
            signed_fios = json.loads(item['signature']) if item['signature'] else []
        except Exception:
            signed_fios = []
        signed_set = {str(v).strip() for v in signed_fios if v and str(v).strip()}

        if fio_set and signed_set >= fio_set:
            sign_status = f"Подписано: {', '.join(sorted(signed_set))}"
        elif signed_set:
            missing = sorted(fio_set - signed_set)
            sign_status = (
                f"Подписано частично ({len(signed_set)}/{len(fio_set)}): "
                f"{', '.join(sorted(signed_set))} (ожидает: {', '.join(missing)})"
            )
        else:
            sign_status = "Не подписано"

        result.append((
            report_id,
            f"{item['report_num']} ({item['date']})",
            item['izdeliye'], item['detal'], item['order_num'], item['object_kontr'],
            item['overall_quality'], ", ".join(sorted(fio_set)) if fio_set else "",
            sign_status, item['record_num']
        ))
    return result


# ---------------------------------------------------------------
#  Сборка report_data (кортежи, совместимые с v3/PDF-движком)
# ---------------------------------------------------------------

def merge_measurements(raw_measurements):
    """Объединяет измерения без дефектов с совпадающими параметрами (как в v3)."""
    def has_real_defects(m):
        for d in m.get('defects', []):
            if len(d) > 12 and str(d[12] or '').strip() != 'Да':
                return True
        return False

    def _norm(x):
        s = ''.join(str(x or '').split())
        return '' if s in ('0', '0.0', '0,0', '-') else s

    def get_sig(m):
        return tuple(_norm(x) for x in m.get('measurement', []))

    merged = []
    for m in raw_measurements:
        is_defect = has_real_defects(m)
        match = None
        if not is_defect:
            for existing in merged:
                if not has_real_defects(existing) and get_sig(existing) == get_sig(m):
                    match = existing
                    break

        if match:
            if match['defects'] and m['defects']:
                d1 = list(match['defects'][0])
                d2 = m['defects'][0]
                objs1 = set(o.strip() for o in str(d1[13] or '').split(',') if o.strip())
                objs2 = set(o.strip() for o in str(d2[13] or '').split(',') if o.strip())
                d1[13] = ", ".join(sorted(objs1 | objs2))
                match['defects'][0] = tuple(d1)
            elif m['defects']:
                match['defects'].extend(m['defects'])
        else:
            merged.append(m)
    return merged


CONCLUSION_SELECT = """
            SELECT
                c.report_num, c.date, c.record_num, c.izdeliye, c.detal, c.order_num, c.object_kontr,
                c.material, c.thickness, c.volume_kontr, c.norm_doc, c.method_kontr, c.map_kontr,
                c.signature,
                m.id as m_id, m.prog_obespec, m.tip_defectoscope, m.tip_skan_ustr,
                m.tip_preobr, m.tip_preobr_sn, m.tip_prism, m.tip_prism_sn,
                m.tip_preobr2, m.tip_preobr2_sn, m.tip_prism2, m.tip_prism2_sn,
                m.kanal, m.tip_skanirov, m.time_delay, m.angle, m.focus, m.dist_points,
                m.preamp, m.averaging, m.offset_y, m.scan_range_x, m.sample_ref, m.setup_method, m.we_level, m.gain,
                d.id as d_id, d.plot_num, d.amp_s_def, d.y_start_end, d.len_y, d.x_start_end,
                d.len_x, d.z_start_end, d.height, d.defect_type, d.quality, d.fio, d.no_defect,
                d.defect_object
            FROM conclusions c
            LEFT JOIN measurements m ON m.conclusion_id = c.id
            LEFT JOIN defects d ON d.measurement_id = m.id
"""


def build_report_data_from_rows(rows):
    """rows — результат CONCLUSION_SELECT; возвращает dict {idx: {...}} как в v3."""
    measurements_by_id = {}
    for row in rows:
        m_id = row[14]
        if m_id not in measurements_by_id:
            measurements_by_id[m_id] = {
                'common': row[0:13],
                'signature': row[13],
                'measurement': row[15:40],
                'defects': []
            }
        d_id = row[40]
        if d_id is not None:
            measurements_by_id[m_id]['defects'].append(row[40:])

    raw_list = list(measurements_by_id.values())
    merged_list = merge_measurements(raw_list)
    return {idx: m for idx, m in enumerate(merged_list)}


def fetch_conclusion_report_data(conn, report_id):
    """Возвращает (report_data|None, attachments, journal, comment)."""
    cursor = conn.cursor()
    cursor.execute(CONCLUSION_SELECT + " WHERE c.id = ? ORDER BY m.id, d.id", (report_id,))
    rows = cursor.fetchall()

    cursor.execute("SELECT id, filename FROM attachments WHERE conclusion_id = ? ORDER BY id", (report_id,))
    attachments = cursor.fetchall()

    cursor.execute("SELECT journal, comment FROM conclusions WHERE id = ?", (report_id,))
    jrow = cursor.fetchone()
    journal_name = (jrow[0] if jrow and jrow[0] else "") if jrow else ""
    comment = (jrow[1] if jrow and jrow[1] else "") if jrow else ""

    if not rows:
        return None, attachments, journal_name, comment
    return build_report_data_from_rows(rows), attachments, journal_name, comment


def iter_conclusion_report_data(conn, report_ids, batch_size=100, progress_callback=None):
    """Пакетная выдача (report_data, comment) — аналог v3 для экспорта журнала."""
    ids = list(report_ids)
    total = len(ids)
    if not ids:
        return

    cursor = conn.cursor()
    processed = 0
    for batch_start in range(0, total, batch_size):
        batch = ids[batch_start:batch_start + batch_size]
        placeholders = ",".join("?" for _ in batch)

        cursor.execute(f"SELECT id, comment FROM conclusions WHERE id IN ({placeholders})", tuple(batch))
        batch_comments = {r[0]: (r[1] or "") for r in cursor.fetchall()}

        cursor.execute(
            CONCLUSION_SELECT.replace("c.report_num", "c.id, c.report_num") +
            f" WHERE c.id IN ({placeholders}) ORDER BY c.id, m.id, d.id",
            tuple(batch)
        )
        rows = cursor.fetchall()

        reports = {}
        for row in rows:
            report_id = row[0]
            if report_id not in reports:
                reports[report_id] = {'measurements_by_id': {}, 'common': row[1:14], 'signature': row[14]}
            m_id = row[15]
            if m_id not in reports[report_id]['measurements_by_id']:
                reports[report_id]['measurements_by_id'][m_id] = {
                    'common': row[1:14],
                    'signature': row[14],
                    'measurement': row[16:41],
                    'defects': []
                }
            d_id = row[41]
            if d_id is not None:
                reports[report_id]['measurements_by_id'][m_id]['defects'].append(row[41:])

        for report_id in batch:
            if report_id in reports:
                raw_list = list(reports[report_id]['measurements_by_id'].values())
                merged_list = merge_measurements(raw_list)
                report_data = {idx: m for idx, m in enumerate(merged_list)}
                yield report_data, batch_comments.get(report_id, "")

            processed += 1
            if progress_callback:
                progress_callback(processed, total)


# ---------------------------------------------------------------
#  Diff при редактировании заключения
# ---------------------------------------------------------------

GENERAL_FIELD_NAMES = {
    "report_num": "Номер заключения", "date": "Дата", "record_num": "Номер записи",
    "izdeliye": "Изделие", "detal": "Деталь", "order_num": "Заказ",
    "object_kontr": "Объект контроля", "material": "Материал", "thickness": "Толщина",
    "volume_kontr": "Объём контроля", "norm_doc": "Нормативный документ",
    "method_kontr": "Метод контроля", "map_kontr": "Карта контроля",
    "quality": "Оценка качества", "fio": "ФИО дефектоскописта", "journal": "Журнал",
}

MEASUREMENT_FIELD_NAMES = {
    "prog_obespec": "Программное обеспечение", "tip_defectoscope": "Дефектоскоп",
    "tip_skan_ustr": "Сканирующее устройство", "tip_preobr": "Преобразователь 1",
    "tip_preobr_sn": "Зав. № преобразователя 1", "tip_prism": "Призма 1",
    "tip_prism_sn": "Зав. № призмы 1", "tip_preobr2": "Преобразователь 2",
    "tip_preobr2_sn": "Зав. № преобразователя 2", "tip_prism2": "Призма 2",
    "tip_prism2_sn": "Зав. № призмы 2", "kanal": "Канал", "tip_skanirov": "Тип сканирования",
    "time_delay": "Временная развертка", "angle": "Угол(ы) ввода", "focus": "Фокусировка",
    "dist_points": "Расстояние между точками ввода", "preamp": "Предусилитель",
    "averaging": "Усреднение", "offset_y": "Смещение шва/Шаг Y",
    "scan_range_x": "Диапазон сканирования/Шаг X", "sample_ref": "Обозначение образца",
    "setup_method": "Способ настройки", "we_level": "Уровень ВЭ", "gain": "Усиление",
}

DEFECT_FIELD_NAMES = {
    "defect_object": "Объект", "plot_num": "№ участка", "amp_s_def": "Aдеф/Sдеф",
    "y_start_end": "Yн:Yк", "len_y": "Протяженность по Y", "x_start_end": "Xн:Xк",
    "len_x": "Протяженность по X", "z_start_end": "Zн:Zк", "height": "Высота",
    "defect_type": "Тип дефекта", "no_defect": "Дефектов не обнаружено",
    "quality": "Оценка качества", "fio": "ФИО дефектоскописта",
}


def build_diff(old_state, new_general, new_measurements):
    diff = {"conclusion": [], "measurements": [], "defects": []}
    old_general = old_state["general"]

    for key, label in GENERAL_FIELD_NAMES.items():
        old_val = (old_general.get(key) or "").strip()
        new_val = (new_general.get(key) or "").strip()
        if old_val != new_val:
            diff["conclusion"].append({"field": label, "old": old_val, "new": new_val})

    old_meas_by_kanal = {(m.get("kanal") or "").strip(): m for m in old_state["measurements"]}
    new_meas_by_kanal = {(m.get("kanal") or "").strip(): m for m in new_measurements}

    all_kanals = set(old_meas_by_kanal) | set(new_meas_by_kanal)
    all_kanals.discard("")

    def build_defect_index(defects):
        index, counter = {}, {}
        for d in defects:
            pk = str(d.get("plot_num") or "").strip()
            cnt = counter.get(pk, 0)
            counter[pk] = cnt + 1
            index[(pk, cnt)] = d
        return index

    def display_plot(key):
        pk = key[0]
        return pk if pk else "(без номера)"

    for kanal in sorted(all_kanals):
        old_m = old_meas_by_kanal.get(kanal)
        new_m = new_meas_by_kanal.get(kanal)

        if old_m is None and new_m is not None:
            diff["measurements"].append({"channel": kanal, "action": "added", "name": format_meas_name(new_m)})
            continue
        if old_m is not None and new_m is None:
            diff["measurements"].append({"channel": kanal, "action": "deleted", "name": format_meas_name(old_m)})
            continue

        changes = []
        for key, label in MEASUREMENT_FIELD_NAMES.items():
            old_val = (old_m.get(key) or "").strip()
            new_val = (new_m.get(key) or "").strip()
            if old_val != new_val:
                changes.append({"field": label, "old": old_val, "new": new_val})
        if changes:
            diff["measurements"].append({"channel": kanal, "action": "changed", "changes": changes})

        old_defects = build_defect_index(old_m.get("defects", []))
        new_defects = build_defect_index(new_m.get("defects", []))
        for key in sorted(set(old_defects) | set(new_defects)):
            od = old_defects.get(key)
            nd = new_defects.get(key)
            if od is None and nd is not None:
                diff["defects"].append({"channel": kanal, "plot_num": display_plot(key), "action": "added"})
                continue
            if od is not None and nd is None:
                diff["defects"].append({"channel": kanal, "plot_num": display_plot(key), "action": "deleted"})
                continue
            changes = []
            for fkey, label in DEFECT_FIELD_NAMES.items():
                old_val = (od.get(fkey) or "").strip()
                new_val = (nd.get(fkey) or "").strip()
                if old_val != new_val:
                    changes.append({"field": label, "old": old_val, "new": new_val})
            if changes:
                diff["defects"].append({"channel": kanal, "plot_num": display_plot(key),
                                        "action": "changed", "changes": changes})
    return diff


def format_meas_name(m):
    p1 = safe_text(m.get("tip_preobr"))
    s1 = safe_text(m.get("tip_preobr_sn"))
    p2 = safe_text(m.get("tip_preobr2"))
    s2 = safe_text(m.get("tip_preobr2_sn"))
    if p2 and s2:
        return f"{p1} (№{s1}), {p2} (№{s2})"
    if p2:
        return f"{p1} (№{s1}), {p2}"
    return f"{p1} (№{s1})"


def format_diff_summary(g_data, diff, is_new):
    object_k = (g_data.get("object_kontr") or "").strip() or "—"
    detal = (g_data.get("detal") or "").strip() or "—"
    num = (g_data.get("report_num") or "").strip() or "—"

    if is_new:
        return f"Создано заключение №{num} (Объект: {object_k}, Деталь: {detal})"

    parts = [f"Изменено заключение №{num} (Объект: {object_k}, Деталь: {detal})"]
    summary_bits = []
    if diff and diff.get("conclusion"):
        summary_bits.append(f"полей: {len(diff['conclusion'])}")
    if diff and diff.get("measurements"):
        a = sum(1 for x in diff["measurements"] if x["action"] == "added")
        d = sum(1 for x in diff["measurements"] if x["action"] == "deleted")
        c = sum(1 for x in diff["measurements"] if x["action"] == "changed")
        bits = [s for s in (f"+{a}" if a else "", f"-{d}" if d else "", f"~{c}" if c else "") if s]
        summary_bits.append(f"измерений: {' '.join(bits)}")
    if diff and diff.get("defects"):
        a = sum(1 for x in diff["defects"] if x["action"] == "added")
        d = sum(1 for x in diff["defects"] if x["action"] == "deleted")
        c = sum(1 for x in diff["defects"] if x["action"] == "changed")
        bits = [s for s in (f"+{a}" if a else "", f"-{d}" if d else "", f"~{c}" if c else "") if s]
        summary_bits.append(f"дефектов: {' '.join(bits)}")

    if summary_bits:
        parts.append("[" + ", ".join(summary_bits) + "]")
    else:
        parts.append("[без изменений]")
    return " ".join(parts)