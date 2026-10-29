# -*- coding: utf-8 -*-
"""PDF-движок v4 (ReportLab).

Перенесён из v3 (uzk_app/pdf_mixin.py) без изменений вёрстки: те же
колонки, переносы блоков между страницами, стили и обработка слишком
высоких сегментов. Отличия только в слое взаимодействия: вместо tkinter
(messagebox/Toplevel/filedialog/self.root) модуль принимает объект UiHost —
адаптер интерфейса PyQt6 (ui/app_ui.py) с методами:
    warn(title, text), error(title, text), ask_yes_no(title, text) -> bool,
    save_pdf_path(title, default_name) -> str|None,
    show_oversized_dialog(error) -> "auto"|"manual"|None,
    log_action(action, details), open_file(path).
"""
import datetime
import os
from pathlib import Path

from .helpers import _safe_text as safe_text_impl, _pdf_escape
from .journal_repo import iter_conclusion_report_data, fetch_conclusion_report_data
from .config import DB_NAME

import sqlite3


def _safe_text(value):
    return safe_text_impl(value)


class PDFExportTooLargeError(Exception):
    """Часть заключения не помещается на страницу PDF."""
    def __init__(self, message, report_num="—", seg_height=0.0, capacity=0.0):
        super().__init__(message)
        self.report_num = report_num
        self.seg_height = seg_height
        self.capacity = capacity


class PdfEngine:
    """Экспорт PDF через ReportLab. ui — адаптер интерфейса (UiHost)."""

    def __init__(self, db, ui):
        self.db = db
        self.ui = ui

    def _connect(self):
        import sqlite3
        return sqlite3.connect(self.db.db_path)

    def _register_pdf_fonts(self):
        if getattr(self, '_pdf_fonts_registered', False):
            return True
        try:
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
        except ImportError:
            self.ui.error("Ошибка", "Библиотека reportlab не установлена.\nВыполните: pip install reportlab")
            return False
        fonts_dir = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
        candidates = [
            (str(fonts_dir / 'arial.ttf'), str(fonts_dir / 'arialbd.ttf')),
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ]
        try:
            for regular, bold in candidates:
                if Path(regular).exists():
                    pdfmetrics.registerFont(TTFont('PDFFont', regular))
                    pdfmetrics.registerFont(TTFont('PDFFont-Bold', bold if Path(bold).exists() else regular))
                    break
            else:
                raise FileNotFoundError(f"Шрифт не найден (ожидался arial.ttf в {fonts_dir})")
        except Exception as e:
            self.ui.error("Ошибка", f"Не удалось загрузить шрифт для PDF (нужен arial.ttf в {fonts_dir}): {e}")
            return False
        self._pdf_fonts_registered = True
        return True

    def _pdf_page_setup(self):
        from reportlab.lib.pagesizes import A3, landscape
        from reportlab.lib.units import cm
        left_margin = right_margin = 1.5 * cm
        top_margin = bottom_margin = 0.5 * cm
        page_size = landscape(A3)
        return page_size, left_margin, right_margin, top_margin, bottom_margin

    def _conclusion_pdf_headers(self):
        SHY = "\u00ad"
        return (
            f"№ за{SHY}клю{SHY}че{SHY}ния / Дата про{SHY}ве{SHY}де{SHY}ния кон{SHY}тро{SHY}ля",
            f"Из{SHY}де{SHY}лие чер{SHY}тёж / Де{SHY}таль чер{SHY}тёж / За{SHY}каз / Объ{SHY}ект кон{SHY}тро{SHY}ля / "
            f"Ма{SHY}те{SHY}ри{SHY}ал / Тол{SHY}щи{SHY}на / Объ{SHY}ём \nкон{SHY}тро{SHY}ля",
            f"Нор{SHY}ма{SHY}тив{SHY}ный до{SHY}ку{SHY}мент / Метод \nкон{SHY}тро{SHY}ля / "
            f"\nКар{SHY}та \nкон{SHY}тро{SHY}ля \n(Про{SHY}це{SHY}ду{SHY}ра)",
            f"Про{SHY}грамм{SHY}ное обес{SHY}пе{SHY}че{SHY}ние / Тип де{SHY}фек{SHY}то{SHY}ско{SHY}па, зав.но{SHY}мер / "
            f"Тип ска{SHY}ни{SHY}ру{SHY}ю{SHY}ще{SHY}го устрой{SHY}ства, зав.но{SHY}мер",
            f"Пре{SHY}об{SHY}ра{SHY}зо{SHY}ва{SHY}те{SHY}ли и призмы",
            f"Канал / Тип ска{SHY}ни{SHY}ро{SHY}ва{SHY}ния",
            f"Вре{SHY}мен{SHY}ная раз{SHY}верт{SHY}ка, мкс",
            f"Угол(ы) ввода, ° / Фо{SHY}ку{SHY}си{SHY}ров{SHY}ка",
            f"Рас{SHY}стоя{SHY}ние между точ{SHY}ка{SHY}ми ввода, мм / \nПре{SHY}ду{SHY}си{SHY}ли{SHY}тель / Ус{SHY}ред{SHY}не{SHY}ние",
            f"Сме{SHY}ще{SHY}ние ска{SHY}ни{SHY}ро{SHY}ва{SHY}ния от{SHY}но{SHY}си{SHY}тель{SHY}но оси шва, мм / "
            f"Шаг ска{SHY}ни{SHY}ро{SHY}ва{SHY}ния по Y, мм",
            f"Диа{SHY}па{SHY}зон ска{SHY}ни{SHY}ро{SHY}ва{SHY}ния, мм / Шаг ска{SHY}ни{SHY}ро{SHY}ва{SHY}ния по X, мм",
            f"НО / \nСпо{SHY}соб \nна{SHY}строй{SHY}ки / \nВЭ / \nУси{SHY}ле{SHY}ние, дБ",
            f"№ \nучас{SHY}тка", "Aдеф, дБ / Sдеф, мм²", "Yн:Yк, мм", f"Про{SHY}тя{SHY}жен{SHY}ность Y, мм", "Xн:Xк, мм",
            f"Про{SHY}тя{SHY}жен{SHY}ность X, мм", "Zн:Zк, мм", f"Вы{SHY}со{SHY}та, мм", f"Тип де{SHY}фек{SHY}та",
            f"Оцен{SHY}ка", "ФИО", f"Под{SHY}пись", f"№ \nза{SHY}пи{SHY}си"
        )

    def _conclusion_pdf_col_widths(self, available_width):
        weights = (135, 180, 180, 190, 210, 130, 115, 150, 190, 145, 145, 210,
                   120, 130, 120, 130, 120, 130, 120, 130, 150, 130, 180, 130, 100)
        total = sum(weights)
        return [available_width * w / total for w in weights]

    def _pdf_person_cell(self, value, column_width, style, blank=False, measure_width=None,
                         hr_width="100%"):
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        from reportlab.platypus import Table, TableStyle, Paragraph
        from reportlab.platypus.flowables import HRFlowable
        from reportlab.pdfbase import pdfmetrics

        text = _safe_text(value)
        people = [part.strip() for part in text.split(",") if part.strip()]
        if not people or text == "-":
            people = [""]

        inner_width = max(column_width, 1.0)
        measure_w = measure_width if measure_width is not None else column_width
        measure_inner = max(measure_w, 1.0)

        MIN_FONT_SIZE = 4.5
        FONT_STEP = 0.25
        base_font_size = style.fontSize

        rows = []
        heights = []

        for i, person in enumerate(people):
            if i > 0:
                hr = HRFlowable(width=hr_width, thickness=0.4, color=colors.grey,
                                spaceBefore=2, spaceAfter=2)
                rows.append([hr])
                heights.append(0.4 + 4.0)

            if blank or not person:
                paragraph = Paragraph("", style)
                _w, h = paragraph.wrap(measure_inner, 1_000_000)
                heights.append(max(0.7 * cm, h + 4.0))
                rows.append([paragraph])
                continue

            words = person.split()
            longest_word = ""
            longest_w = 0.0
            if words:
                longest_word = max(
                    words,
                    key=lambda w: pdfmetrics.stringWidth(w, style.fontName, base_font_size)
                )
                longest_w = pdfmetrics.stringWidth(longest_word, style.fontName, base_font_size)

            fit_size = base_font_size
            while longest_w > measure_inner and fit_size > MIN_FONT_SIZE:
                fit_size = max(MIN_FONT_SIZE, fit_size - FONT_STEP)
                longest_w = pdfmetrics.stringWidth(longest_word, style.fontName, fit_size)

            person_style = style.clone(
                f'pdf_person_{fit_size}', fontSize=fit_size, splitLongWords=0
            )
            paragraph = Paragraph(_pdf_escape(person), person_style)
            _w, h = paragraph.wrap(measure_inner, 1_000_000)
            heights.append(max(0.7 * cm, h + 4.0))
            rows.append([paragraph])

        table = Table(rows, colWidths=[inner_width], rowHeights=heights)
        commands = [
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]
        table.setStyle(TableStyle(commands))
        return table

    def _plan_measurement_rows(self, defects, show_objects=True):
        if not defects:
            return [('no_defect_row', None)]

        plan = []
        seen_objects = set()
        has_any_object = show_objects and any(
            (len(d) > 13 and str(d[13] or '').strip()) for d in defects if d is not None
        )

        for d in defects:
            if d is None:
                continue
            obj = str(d[13] or '').strip() if len(d) > 13 else ''
            is_no_defect = _safe_text(d[12]) == "Да"

            if is_no_defect:
                if has_any_object and obj:
                    if obj not in seen_objects:
                        plan.append(('group_header', obj))
                        seen_objects.add(obj)
                plan.append(('no_defect_row', d))
                continue

            if has_any_object and obj:
                if obj not in seen_objects:
                    plan.append(('group_header', obj))
                    seen_objects.add(obj)
            plan.append(('defect_row', d))

        return plan

    def _build_conclusion_full_table(self, report_data, col_widths, styles, page_data_height,
                                     first_page_capacity=None, include_header=True, comment=""):
        from reportlab.platypus import Table, TableStyle, Paragraph
        from reportlab.lib import colors

        def display_value(value):
            value = "" if value is None else str(value).replace("\xa0", " ").strip()
            return value if value else "-"

        def P(text, style):
            return Paragraph(_pdf_escape(text), style)

        group_style = styles['group']
        header_style = styles['header']
        cell_style = styles['cell']

        headers = self._conclusion_pdf_headers()
        group_ranges = (("Общие сведения", 1, 3), ("Оборудование", 3, 5),
                         ("Параметры настройки", 5, 12), ("Результаты контроля", 12, 22))

        first_common = next(iter(report_data.values()))['common']
        first_measurement = next(iter(report_data.values()))['measurement']
        conclusion_record = first_common[2]
        method_is_tofd = str(first_common[11]).strip().upper() == "TOFD"

        channel_converters = {}
        for item in report_data.values():
            measurement = item['measurement']
            channel = measurement[11] or ""
            channel_converters.setdefault(channel, set())
            for converter, serial, prism, prism_serial in (
                (measurement[3], measurement[4], measurement[5], measurement[6]),
                (measurement[7], measurement[8], measurement[9], measurement[10]),
            ):
                if any((converter, serial, prism, prism_serial)):
                    text = f"{display_value(converter)} №{display_value(serial)}\n{display_value(prism)} №{display_value(prism_serial)}"
                    channel_converters[channel].add(text)

        group_row = [""] * 25
        for title, start, _end in group_ranges:
            group_row[start] = title

        second_col_text = (
            f"{display_value(first_common[3])}\n{display_value(first_common[4])}\n{display_value(first_common[5])}\n"
            f"{display_value(first_common[6])}\n{display_value(first_common[7])}\n{display_value(first_common[8])}\n"
            f"{display_value(first_common[9])}"
        )
        if comment:
            second_col_text += "\n\n" + comment

        common_texts = [
            f"№ {display_value(first_common[0])}\n{display_value(first_common[1])}",
            second_col_text,
            f"{display_value(first_common[10])}\n{display_value(first_common[11])}\n{display_value(first_common[12])}",
            f"{display_value(first_measurement[0])}\n{display_value(first_measurement[1])}\n{display_value(first_measurement[2])}",
        ]
        record_text = display_value(conclusion_record)

        max_reserved_height = 0.0
        for col_idx, text in enumerate(common_texts):
            _w, h = P(text, cell_style).wrap(col_widths[col_idx], 1_000_000)
            max_reserved_height = max(max_reserved_height, h)

        items = list(report_data.values())

        all_objects = set()
        for item in items:
            for d in item.get('defects', []):
                if d is not None and len(d) > 13:
                    obj = str(d[13] or '').strip()
                    if obj:
                        all_objects.add(obj)
        show_objects = len(all_objects) > 1

        plan_per_item = []
        block_rows_list = []
        for item in items:
            plan = self._plan_measurement_rows(item['defects'], show_objects=show_objects)
            plan_per_item.append(plan)
            block_rows_list.append(len(plan))
        total_data_rows = sum(block_rows_list)

        equip_texts_list = []
        for item in items:
            measurement = item['measurement']
            equip_texts = [
                "\n".join(sorted(list(channel_converters.get(measurement[11] or "", [])))) or "-",
                f"{display_value(measurement[11])}\n{display_value(measurement[12])}",
                display_value(measurement[13]),
                f"{display_value(measurement[14])}\n{display_value(measurement[15])}",
                f"{display_value(measurement[16])} / {display_value(measurement[17])} / {display_value(measurement[18])}",
                display_value(measurement[19]),
                display_value(measurement[20]),
                f"{display_value(measurement[21])}\n{display_value(measurement[22])}\n"
                f"{display_value(measurement[23])}\n{display_value(measurement[24])}",
            ]
            equip_texts_list.append(equip_texts)
            for col_offset, text in enumerate(equip_texts, start=4):
                _w, h = P(text, cell_style).wrap(col_widths[col_offset], 1_000_000)
                max_reserved_height = max(max_reserved_height, h)

        def _build(include_header, capacity_for_first_segment):
            header_rows = 2 if include_header else 0
            common_row = header_rows
            last_row = common_row + total_data_rows

            data = []
            fixed_span_commands = []
            if include_header:
                tall_cols = (0, 22, 23, 24)
                group_row_cells = list(group_row)
                header_row_cells = list(headers)
                for c in tall_cols:
                    group_row_cells[c] = headers[c]
                    header_row_cells[c] = ""

                data.append([P(text, group_style) for text in group_row_cells])
                data.append([P(h, header_style) for h in header_row_cells])
                fixed_span_commands.extend(
                    ('SPAN', (start, 0), (end - 1, 0)) for _title, start, end in group_ranges if end - start > 1
                )
                for c in tall_cols:
                    fixed_span_commands.append(('SPAN', (c, 0), (c, 1)))

            row_texts = {}
            for col, text in enumerate(common_texts):
                for r in range(common_row, last_row):
                    row_texts[(r, col)] = text
            for r in range(common_row, last_row):
                row_texts[(r, 24)] = record_text

            no_defect_rows = set()
            obj_group_rows = set()
            block_start_rows = set()

            current_row = common_row
            for item, plan, block_rows, equip_texts in zip(
                items, plan_per_item, block_rows_list, equip_texts_list
            ):
                block_start_rows.add(current_row)
                for col_offset, text in enumerate(equip_texts, start=4):
                    for r in range(current_row, current_row + block_rows):
                        row_texts[(r, col_offset)] = text

                for r_index, (kind, payload) in enumerate(plan):
                    row = current_row + r_index

                    if kind == 'group_header':
                        obj_name = payload
                        for c in range(12, 24):
                            row_texts[(row, c)] = ""
                        row_texts[(row, 12)] = obj_name
                        fixed_span_commands.append(('SPAN', (12, row), (23, row)))
                        obj_group_rows.add(row)

                    elif kind == 'defect_row':
                        defect = payload
                        no_defect = _safe_text(defect[12]) == "Да"
                        row_texts[(row, 12)] = display_value(defect[1])
                        if no_defect:
                            fixed_span_commands.append(('SPAN', (13, row), (20, row)))
                            row_texts[(row, 13)] = "Дефектов не обнаружено"
                            row_texts[(row, 21)] = display_value(defect[10] or "уд.")
                            no_defect_rows.add(row)
                        else:
                            amp_parts = (defect[2] or "").split(" / ", 1)
                            amp_value = "-" if method_is_tofd else display_value(
                                amp_parts[0] + (f" / {amp_parts[-1]}" if len(amp_parts) > 1 else "")
                            )
                            row_texts[(row, 13)] = amp_value
                            row_texts[(row, 14)] = display_value(defect[3])
                            row_texts[(row, 15)] = display_value(defect[4])
                            row_texts[(row, 16)] = display_value(defect[5])
                            row_texts[(row, 17)] = display_value(defect[6])
                            row_texts[(row, 18)] = display_value(defect[7])
                            row_texts[(row, 19)] = display_value(defect[8])
                            row_texts[(row, 20)] = display_value(defect[9])
                            row_texts[(row, 21)] = display_value(defect[10])
                        row_texts[(row, 22)] = display_value(defect[11])
                        row_texts[(row, 23)] = ""

                    elif kind == 'no_defect_row':
                        defect = payload
                        fixed_span_commands.append(('SPAN', (13, row), (20, row)))
                        if defect is not None:
                            row_texts[(row, 12)] = display_value(defect[1])
                            row_texts[(row, 21)] = display_value(defect[10] or "уд.")
                            row_texts[(row, 22)] = display_value(defect[11])
                        else:
                            row_texts[(row, 12)] = "-"
                            row_texts[(row, 21)] = "уд."
                            row_texts[(row, 22)] = ""
                        row_texts[(row, 13)] = "Дефектов не обнаружено"
                        row_texts[(row, 23)] = ""
                        no_defect_rows.add(row)

                current_row += block_rows

            centered_style = cell_style.clone('pdf_no_defect', alignment=1)
            centered_obj_style = cell_style.clone('pdf_obj_group', alignment=1)

            horizontally_centered_cols = {12, 13, 15, 17, 19, 21, 24}

            for r in range(common_row, last_row):
                cells = []
                for c in range(25):
                    text = row_texts.get((r, c), "")
                    if c in horizontally_centered_cols:
                        cells.append(P(text, centered_style))
                    else:
                        cells.append(P(text, cell_style))

                if r in no_defect_rows:
                    cells[13] = P(row_texts[(r, 13)], centered_style)
                if r in obj_group_rows:
                    cells[12] = P(row_texts[(r, 12)], centered_obj_style)

                fio = row_texts.get((r, 22), "")
                cells[22] = self._pdf_person_cell(fio, col_widths[22], cell_style)
                cells[23] = self._pdf_person_cell(
                    fio, col_widths[23], cell_style, blank=True,
                    measure_width=col_widths[22], hr_width="95%"
                )
                data.append(cells)

            base_style_commands = [
                ('GRID', (0, 0), (-1, -1), 0.4, colors.grey),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 2),
                ('RIGHTPADDING', (0, 0), (-1, -1), 2),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                ('LEFTPADDING', (22, 0), (23, -1), 0),
                ('RIGHTPADDING', (22, 0), (23, -1), 0),
                ('VALIGN', (0, 0), (0, 1), 'MIDDLE'),
                ('VALIGN', (22, 0), (24, 1), 'MIDDLE'),
            ] + fixed_span_commands + [
                ('VALIGN', (13, r), (20, r), 'MIDDLE') for r in no_defect_rows
            ]
            if include_header:
                base_style_commands = [('BACKGROUND', (0, 0), (-1, 1), colors.white)] + base_style_commands

            merged_cols = set(range(0, 12)) | {24}
            measure_data = [row[:] for row in data]
            for r in range(common_row, last_row):
                for c in merged_cols:
                    measure_data[r][c] = P("", cell_style)

            measure_table = Table(measure_data, colWidths=col_widths)
            measure_table.setStyle(TableStyle(base_style_commands))
            measure_table.wrap(sum(col_widths), 1_000_000)
            row_heights = measure_table._rowHeights

            if include_header:
                header_height = row_heights[0] + row_heights[1]
            else:
                header_data = [
                    [P(text, group_style) for text in group_row],
                    [P(text, header_style) for text in headers],
                ]
                header_table = Table(header_data, colWidths=col_widths)
                header_table.setStyle(TableStyle([
                    ('LEFTPADDING', (0, 0), (-1, -1), 2),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 2),
                    ('TOPPADDING', (0, 0), (-1, -1), 2),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                    *(('SPAN', (start, 0), (end - 1, 0))
                      for _title, start, end in group_ranges),
                ]))
                header_table.wrap(sum(col_widths), 1_000_000)
                header_height = sum(header_table._rowHeights)
            floor_height = row_heights[common_row] if last_row > common_row else 20.0
            first_page_header_height = header_height if include_header else 0.0

            fresh_capacity = page_data_height if include_header else max(page_data_height - header_height, floor_height)
            min_first_capacity = first_page_header_height + max_reserved_height + floor_height
            started_fresh = False
            if (capacity_for_first_segment + 0.1 < fresh_capacity
                    and capacity_for_first_segment < min_first_capacity):
                capacity_for_first_segment = fresh_capacity
                first_page_header_height = header_height if include_header else 0.0
                started_fresh = True

            MAX_RESERVE = 30.0
            reserve_first = min(max_reserved_height, MAX_RESERVE)
            reserve_cont = min(max_reserved_height, 20.0)
            first_capacity = max(capacity_for_first_segment - first_page_header_height - reserve_first, floor_height)
            page_capacity = max(page_data_height - header_height - reserve_cont, floor_height)

            page_break_after = set()
            acc = 0.0
            capacity = first_capacity
            for r in range(common_row, last_row):
                h = row_heights[r]
                if acc and acc + h > capacity:
                    page_break_after.add(r - 1)
                    acc = 0.0
                    capacity = page_capacity
                acc += h

            segments = []
            seg_start = common_row
            for r in range(common_row, last_row):
                if r in page_break_after:
                    segments.append((seg_start, r))
                    seg_start = r + 1
            segments.append((seg_start, last_row - 1))

            continuation_text = (
                f"Продолжение\nк заключению\n№{display_value(first_common[0])} от\n{display_value(first_common[1])}"
            )
            for seg_index, (seg_start, seg_end) in enumerate(segments):
                if seg_index == 0:
                    continue
                for r in range(seg_start, seg_end + 1):
                    row_texts[(r, 1)] = continuation_text
                    data[r][1] = P(continuation_text, cell_style)
                    for c in (0, 2, 3):
                        row_texts[(r, c)] = ""
                        data[r][c] = P("", cell_style)

            span_commands = list(fixed_span_commands)
            blank_on_continuation = []

            def merge_equal_runs(col):
                for seg_start, seg_end in segments:
                    run_start = seg_start
                    run_value = row_texts.get((seg_start, col), "")

                    if (4 <= col <= 11 and seg_start > common_row
                            and row_texts.get((seg_start - 1, col), "") == run_value
                            and seg_start not in block_start_rows):
                        blank_on_continuation.append((seg_start, col))
                    for r in range(seg_start + 1, seg_end + 2):
                        value = row_texts.get((r, col), "") if r <= seg_end else None
                        if r > seg_end or value != run_value or (4 <= col <= 11 and r in block_start_rows):
                            if r - 1 > run_start:
                                span_commands.append(('SPAN', (col, run_start), (col, r - 1)))
                                for rr in range(run_start + 1, r):
                                    data[rr][col] = P("", cell_style)
                            run_start = r
                            run_value = value

            for col in (0, 1, 2, 3, 24, 4, 5, 6, 7, 8, 9, 10, 11):
                merge_equal_runs(col)

            final_style = TableStyle(base_style_commands + span_commands[len(fixed_span_commands):])
            table = Table(data, colWidths=col_widths, repeatRows=header_rows)
            table.setStyle(final_style)
            if blank_on_continuation:
                table.wrap(sum(col_widths), 1_000_000)
                original_heights = list(table._rowHeights)
                for row, col in blank_on_continuation:
                    data[row][col] = P("", cell_style)
                table = Table(data, colWidths=col_widths, rowHeights=original_heights,
                              repeatRows=header_rows)
                table.setStyle(final_style)

            last_seg_start, last_seg_end = segments[-1]
            last_segment_height = sum(row_heights[r] for r in range(last_seg_start, last_seg_end + 1))
            last_page_capacity_used = capacity_for_first_segment if len(segments) == 1 else page_data_height
            last_page_header_height = header_height if include_header or len(segments) > 1 else 0.0
            leftover = last_page_capacity_used - last_page_header_height - last_segment_height
            return table, leftover, segments, started_fresh

        first_capacity = page_data_height if first_page_capacity is None else first_page_capacity
        table, leftover, segments, started_fresh = _build(
            include_header=include_header,
            capacity_for_first_segment=first_capacity
        )
        return table, leftover, segments, started_fresh

    def _pdf_page_grid_commands(self, page_index, last_page):
        from reportlab.lib import colors
        def line(name, start, end):
            return (name, start, end, 0.4, colors.grey)
        if page_index == 0:
            return [
                line('LINEABOVE', (0, 0), (-1, 0)),
                line('LINEBEFORE', (0, 0), (0, -1)),
                line('LINEAFTER', (-1, 0), (-1, -1)),
                line('LINEBELOW', (0, -1), (-1, -1)),
                line('INNERGRID', (0, 0), (-1, -1)),
            ]
        commands = [
            line('LINEABOVE', (0, 0), (-1, 0)),
            line('LINEBEFORE', (0, 0), (0, 1)),
            line('LINEBEFORE', (0, 2), (0, -1)),
            line('LINEAFTER', (-1, 0), (-1, 1)),
            line('LINEAFTER', (-1, 2), (-1, -1)),
        ]
        if last_page:
            commands.extend([
                line('LINEBELOW', (0, -1), (-1, -1)),
                line('INNERGRID', (0, 0), (-1, 1)),
                line('LINEABOVE', (0, 2), (-1, 2)),
            ])
        elif page_index == 1:
            commands.extend([
                line('LINEBELOW', (0, 1), (-1, 1)),
                line('INNERGRID', (0, 0), (-1, 1)),
                line('LINEBELOW', (0, -1), (-1, -1)),
            ])
        else:
            commands.extend([
                line('INNERGRID', (0, 0), (-1, 1)),
                line('LINEABOVE', (0, 2), (-1, 2)),
                line('LINEBELOW', (0, -1), (-1, -1)),
            ])
        commands.append(line('INNERGRID', (0, 2), (-1, -1)))
        return commands

    def _build_pdf_page_tables(self, report_data_list, col_widths, styles, page_data_height,
                               force_split=False):
        from reportlab.platypus import Table, TableStyle, Paragraph
        from reportlab.lib import colors

        def P(text, style):
            return Paragraph(_pdf_escape(text), style)

        headers = self._conclusion_pdf_headers()
        group_ranges = (("Общие сведения", 1, 3), ("Оборудование", 3, 5),
                        ("Параметры настройки", 5, 12), ("Результаты контроля", 12, 22))
        group_row = [""] * 25
        for title, start, _end in group_ranges:
            group_row[start] = title

        tall_cols = (0, 22, 23, 24)
        group_row_cells = list(group_row)
        header_row_cells = list(headers)
        for c in tall_cols:
            group_row_cells[c] = headers[c]
            header_row_cells[c] = ""

        header_rows = [
            [P(text, styles['group']) for text in group_row_cells],
            [P(text, styles['header']) for text in header_row_cells],
        ]
        header_spans = [
            ('SPAN', (start, 0), (end - 1, 0))
            for _title, start, end in group_ranges if end - start > 1
        ] + [('SPAN', (c, 0), (c, 1)) for c in tall_cols]
        header_probe = Table(header_rows, colWidths=col_widths)
        header_probe.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 1), colors.white),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 2),
            ('RIGHTPADDING', (0, 0), (-1, -1), 2),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('VALIGN', (0, 0), (0, 1), 'MIDDLE'),
            ('VALIGN', (22, 0), (24, 1), 'MIDDLE'),
            *header_spans,
        ]))
        header_probe.wrap(sum(col_widths), 1_000_000)
        header_height = sum(header_probe._rowHeights)
        full_body_capacity = max(page_data_height - header_height, 1.0)
        layout_page_height = page_data_height + 12.0
        layout_body_capacity = max(layout_page_height - header_height, 1.0)

        pages = []
        page_rows = None
        page_spans = None
        page_row_heights = None
        body_rows_count = 0
        actual_body_used = 0.0

        def start_page():
            nonlocal page_rows, page_spans, page_row_heights, body_rows_count, actual_body_used
            page_rows = [row[:] for row in header_rows]
            page_spans = list(header_spans)
            page_row_heights = list(header_probe._rowHeights)
            body_rows_count = 0
            actual_body_used = 0.0

        def finish_page():
            nonlocal page_rows, page_spans, body_rows_count
            if not page_rows or body_rows_count == 0:
                return
            table = Table(page_rows, colWidths=col_widths,
                          rowHeights=list(page_row_heights))
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 1), colors.white),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 2),
                ('RIGHTPADDING', (0, 0), (-1, -1), 2),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                ('VALIGN', (0, 0), (0, 1), 'MIDDLE'),
                ('VALIGN', (22, 0), (24, 1), 'MIDDLE'),
                *page_spans,
            ]))
            pages.append(table)
            page_rows = None
            page_spans = None
            body_rows_count = 0

        def append_segment(source_table, seg_start, seg_end):
            nonlocal body_rows_count
            row_offset = len(page_rows)
            segment_rows = source_table._cellvalues[seg_start:seg_end + 1]
            page_rows.extend([row[:] for row in segment_rows])
            page_row_heights.extend(source_table._rowHeights[seg_start:seg_end + 1])
            body_rows_count += len(segment_rows)

            for command in source_table._spanCmds:
                x1, y1 = command[1]
                x2, y2 = command[2]
                if y1 < seg_start or y2 > seg_end:
                    continue
                page_spans.append((
                    command[0],
                    (x1, row_offset + y1 - seg_start),
                    (x2, row_offset + y2 - seg_start),
                    *command[3:],
                ))
                if x1 == 13 and x2 == 20 and y1 == y2:
                    dest_row = row_offset + y1 - seg_start
                    page_spans.append(('VALIGN', (13, dest_row), (20, dest_row), 'MIDDLE'))

        start_page()
        remaining_body = layout_body_capacity

        for item in report_data_list:
            if isinstance(item, tuple):
                report_data, comment = item
            else:
                report_data, comment = item, ""

            if not report_data:
                continue

            source_table, leftover, segments, started_fresh = self._build_conclusion_full_table(
                report_data, col_widths, styles, layout_page_height,
                first_page_capacity=remaining_body, include_header=False, comment=comment
            )

            source_table.wrap(sum(col_widths), 1_000_000)
            segment_heights = [
                sum(source_table._rowHeights[seg_start:seg_end + 1])
                for seg_start, seg_end in segments
            ]

            if started_fresh and body_rows_count:
                finish_page()
                start_page()
                remaining_body = layout_body_capacity

            if (segments and body_rows_count and not started_fresh
                    and actual_body_used + segment_heights[0] > full_body_capacity + 0.1):
                finish_page()
                start_page()
                remaining_body = layout_body_capacity
                source_table, leftover, segments, _started_fresh = self._build_conclusion_full_table(
                    report_data, col_widths, styles, layout_page_height,
                    first_page_capacity=remaining_body, include_header=False, comment=comment
                )
                source_table.wrap(sum(col_widths), 1_000_000)
                segment_heights = [
                    sum(source_table._rowHeights[seg_start:seg_end + 1])
                    for seg_start, seg_end in segments
                ]

            for seg_index, ((seg_start, seg_end), seg_height) in enumerate(zip(segments, segment_heights)):
                if body_rows_count and actual_body_used + seg_height > full_body_capacity + 0.1:
                    finish_page()
                    start_page()
                    remaining_body = layout_body_capacity

                if seg_height > full_body_capacity + 0.1:
                    if not force_split:
                        first_common = next(iter(report_data.values()))['common']
                        report_num = first_common[0] if first_common else "—"
                        raise PDFExportTooLargeError(
                            f"Часть заключения №{report_num} не помещается на страницу.",
                            report_num=report_num,
                            seg_height=seg_height,
                            capacity=full_body_capacity,
                        )

                append_segment(source_table, seg_start, seg_end)
                actual_body_used += seg_height

                if seg_index < len(segments) - 1:
                    finish_page()
                    start_page()
                    remaining_body = layout_body_capacity

            remaining_body = max(leftover, 0.0)

        finish_page()
        for index, table in enumerate(pages):
            table.setStyle(TableStyle(self._pdf_page_grid_commands(
                page_index=index, last_page=index == len(pages) - 1
            )))
        return pages

    def export_journal_to_pdf(self, journal_name, report_ids=None):
        """Экспортирует журнал (или выбранные id строк) в один PDF."""
        from .journal_repo import get_latest_conclusion_ids

        conn = self._connect()
        try:
            if report_ids is None:
                report_ids = get_latest_conclusion_ids(conn, journal_name)
            else:
                report_ids = list(report_ids)
        finally:
            conn.close()

        if not report_ids:
            self.ui.warn("Внимание", "В журнале нет заключений для экспорта.")
            return

        try:
            from reportlab.lib import colors
            from reportlab.platypus import SimpleDocTemplate, PageBreak
            from reportlab.lib.styles import ParagraphStyle
        except ImportError:
            self.ui.error("Ошибка", "Библиотека reportlab не установлена.\nВыполните: pip install reportlab")
            return

        if not self._register_pdf_fonts():
            return

        default_name = f"Журнал_{journal_name}_{datetime.date.today().strftime('%d.%m.%Y')}.pdf"
        file_path = self.ui.save_pdf_path("Сохранить журнал в PDF", default_name)
        if not file_path:
            return

        page_size, left_margin, right_margin, top_margin, bottom_margin = self._pdf_page_setup()
        available_width = page_size[0] - left_margin - right_margin
        page_data_height = page_size[1] - top_margin - bottom_margin
        col_widths = self._conclusion_pdf_col_widths(available_width)

        styles = {
            'group': ParagraphStyle('journal_group', fontName='PDFFont-Bold', fontSize=8, leading=10, textColor=colors.black, alignment=1),
            'header': ParagraphStyle('journal_colheader', fontName='PDFFont-Bold', fontSize=6.5, leading=8, textColor=colors.black, alignment=1),
            'cell': ParagraphStyle('journal_cell', fontName='PDFFont', fontSize=6.5, leading=8),
        }

        try:
            conn = self._connect()
            report_iter = iter_conclusion_report_data(conn, report_ids, batch_size=100)

            usable_page_height = max(page_data_height - 12.0, 1.0)

            auto_was_used = False
            try:
                page_tables = self._build_pdf_page_tables(
                    report_iter, col_widths, styles, usable_page_height, force_split=False
                )
            except PDFExportTooLargeError as e:
                choice = self.ui.show_oversized_dialog(e)
                if choice == "auto":
                    auto_was_used = True
                    conn2 = self._connect()
                    report_iter = iter_conclusion_report_data(conn2, report_ids, batch_size=100)
                    page_tables = self._build_pdf_page_tables(
                        report_iter, col_widths, styles, usable_page_height, force_split=True
                    )
                else:
                    return

            if not page_tables:
                self.ui.warn("Внимание", "Нет данных для экспорта.")
                return

            elements = []
            for page_index, table in enumerate(page_tables):
                if page_index:
                    elements.append(PageBreak())
                elements.append(table)

            doc = SimpleDocTemplate(
                file_path, pagesize=page_size,
                leftMargin=left_margin, rightMargin=right_margin, topMargin=top_margin, bottomMargin=bottom_margin
            )
            try:
                doc.build(elements)
            except Exception as build_err:
                if auto_was_used:
                    self.ui.error(
                        "Автоматический перенос не справился",
                        "Программа попробовала перенести часть строк на следующую "
                        "страницу, но ReportLab не смог уложить данные — в одном "
                        "заключении слишком много текста в одной ячейке.\n\n"
                        "Обычно это:\n"
                        "  •  длинный комментарий к заключению;\n"
                        "  •  очень длинные значения в столбце «Изделие / Деталь / "
                        "Заказ / Объект / Материал»;\n"
                        "  •  слишком много преобразователей в столбце «Оборудование».\n\n"
                        "Сократите эти данные и повторите экспорт журнала."
                    )
                else:
                    raise
                return
        except PDFExportTooLargeError:
            return
        except Exception as e:
            self.ui.error("Ошибка экспорта", str(e))
            return

        self.ui.log_action("EXPORT_PDF", f"Экспорт журнала '{journal_name}' в PDF: {os.path.basename(file_path)}")
        if self.ui.ask_yes_no("Готово", f"Журнал экспортирован в файл:\n{file_path}\n\nОткрыть файл?"):
            self.ui.open_file(file_path)

    def export_conclusion_to_pdf(self, report_data, comment=""):
        if not report_data:
            self.ui.error("Ошибка", "Нет данных для экспорта.")
            return

        try:
            from reportlab.lib import colors
            from reportlab.platypus import SimpleDocTemplate, PageBreak
            from reportlab.lib.styles import ParagraphStyle
        except ImportError:
            self.ui.error("Ошибка", "Библиотека reportlab не установлена.\nВыполните: pip install reportlab")
            return

        if not self._register_pdf_fonts():
            return

        first_common = next(iter(report_data.values()))['common']
        report_num = first_common[0]

        default_name = f"Заключение_№{report_num}_{datetime.date.today().strftime('%d.%m.%Y')}.pdf"
        file_path = self.ui.save_pdf_path("Сохранить заключение в PDF", default_name)
        if not file_path:
            return

        page_size, left_margin, right_margin, top_margin, bottom_margin = self._pdf_page_setup()
        available_width = page_size[0] - left_margin - right_margin
        page_data_height = page_size[1] - top_margin - bottom_margin
        col_widths = self._conclusion_pdf_col_widths(available_width)

        styles = {
            'group': ParagraphStyle('concl_group', fontName='PDFFont-Bold', fontSize=8, leading=10, textColor=colors.black, alignment=1),
            'header': ParagraphStyle('concl_colheader', fontName='PDFFont-Bold', fontSize=6.5, leading=8, textColor=colors.black, alignment=1),
            'cell': ParagraphStyle('concl_cell', fontName='PDFFont', fontSize=6.5, leading=8),
        }

        try:
            usable_page_height = max(page_data_height - 12.0, 1.0)

            auto_was_used = False
            try:
                page_tables = self._build_pdf_page_tables(
                    [(report_data, comment)], col_widths, styles, usable_page_height,
                    force_split=False
                )
            except PDFExportTooLargeError as e:
                choice = self.ui.show_oversized_dialog(e)
                if choice == "auto":
                    auto_was_used = True
                    page_tables = self._build_pdf_page_tables(
                        [(report_data, comment)], col_widths, styles, usable_page_height,
                        force_split=True
                    )
                else:
                    return

            elements = []
            for page_index, table in enumerate(page_tables):
                if page_index:
                    elements.append(PageBreak())
                elements.append(table)
            doc = SimpleDocTemplate(
                file_path, pagesize=page_size,
                leftMargin=left_margin, rightMargin=right_margin, topMargin=top_margin, bottomMargin=bottom_margin
            )
            try:
                doc.build(elements)
            except Exception as build_err:
                if auto_was_used:
                    self.ui.error(
                        "Автоматический перенос не справился",
                        "Программа попробовала перенести часть строк на следующую "
                        "страницу, но ReportLab не смог уложить данные — в заключении "
                        "слишком много текста в одной ячейке.\n\n"
                        "Обычно это:\n"
                        "  •  длинный комментарий к заключению;\n"
                        "  •  очень длинные значения в столбце «Изделие / Деталь / "
                        "Заказ / Объект / Материал»;\n"
                        "  •  слишком много преобразователей в столбце «Оборудование».\n\n"
                        "Сократите эти данные и повторите экспорт."
                    )
                else:
                    raise
                return
        except PDFExportTooLargeError:
            return
        except Exception as e:
            self.ui.error("Ошибка экспорта", str(e))
            return

        self.ui.log_action("EXPORT_PDF", f"Экспорт заключения №{report_num} в PDF: {os.path.basename(file_path)}")
        if self.ui.ask_yes_no("Готово", f"Заключение экспортировано в файл:\n{file_path}\n\nОткрыть файл?"):
            self.ui.open_file(file_path)