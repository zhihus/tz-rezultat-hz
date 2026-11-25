# -*- coding: utf-8 -*-
"""
build_from_spec.py — шаг 2 конвейера.

Читает spec.json (источник правды) и генерирует плотный пустой шаблон ТЗ.
Ничего не захардкожено: структура, порядок разделов, число строк таблиц,
число скриншотов, число подфункций, нумерация и оформление берутся из
spec.json. Плотность воспроизводится автоматически.

Использование:
    python build_from_spec.py spec.json [-o шаблон.docx]
"""
import argparse
import io
import json
import os
import re
import sys
from io import BytesIO

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Emu, Twips

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))  # portable python: папка скрипта не в sys.path
from tz_common import (setup_utf8_stdout, PAGE_NUM_RE, lang_tag,
                       set_language_ru)

setup_utf8_stdout()




def set_run(r, text, *, bold=None, italic=None, size_pt=None, color=None, font=None):
    r.text = text
    if bold is not None:
        r.bold = bold
    if italic is not None:
        r.italic = italic
    if size_pt is not None:
        r.font.size = Pt(size_pt)
    if color is not None:
        r.font.color.rgb = RGBColor.from_string(color)
    if font is not None:
        r.font.name = font
        rPr = r._element.get_or_add_rPr()
        rf = rPr.find(qn("w:rFonts"))
        if rf is None:
            rf = OxmlElement("w:rFonts")
            rPr.append(rf)
        for a in ("w:ascii", "w:hAnsi", "w:cs"):
            rf.set(qn(a), font)


_EXAMPLE_RE = re.compile(r"\[([А-ЯЁA-Z_ 0-9.]+)\s*\|\s*пример:\s*([^\]]+)\]")


def split_examples(text):
    """Пример плейсхолдера — ВСЕГДА с новой строки (правило протокола):
    «ООО «[НАИМЕНОВАНИЕ | пример: ПримерОрг]»» →
    строка 1: «ООО «[НАИМЕНОВАНИЕ]»», строка 2: «[пример: ПримерОрг]».
    Так заполняющему агенту проще удалять примеры — построчно. Возвращает
    список строк: сначала основная, затем по одной на каждый пример."""
    if not text:
        return [""]
    examples = []
    def _sub(m):
        examples.append(f"[пример: {m.group(2)}]")
        return f"[{m.group(1)}]"
    main = _EXAMPLE_RE.sub(_sub, text)
    out = [ln for ln in main.split("\n")]
    out.extend(examples)
    return out


def add_para(doc, text="", *, style=None, align=None, bold=None, italic=None,
             size_pt=None, color=None, font=None, space_before=None, space_after=None):
    p = doc.add_paragraph(style=style)
    if align is not None:
        p.alignment = align
    pf = p.paragraph_format
    if space_before is not None:
        pf.space_before = Pt(space_before)
    if space_after is not None:
        pf.space_after = Pt(space_after)
    if text:
        set_run(p.add_run(), text, bold=bold, italic=italic, size_pt=size_pt,
                color=color, font=font)
    return p


def add_hint(doc, text, font):
    """Серая курсивная подсказка."""
    return add_para(doc, text, italic=True, color="808080", size_pt=10, font=font,
                    space_after=6)


def add_screenshot_placeholder(doc, caption, font, box=None):
    """Место под скриншот: ОДИН абзац-плейсхолдер в скобках + подпись.
    Урок Прогона #7: табличная рамка неудобна — пользователь должен
    выделять таблицу целиком, чтобы удалить; абзац удаляется одним
    нажатием. Кегли — из spec.screenshot_box, не из кода."""
    box = box or {}
    add_para(doc, "[СКРИНШОТ: вставьте изображение]", align=WD_ALIGN_PARAGRAPH.CENTER,
             italic=True, size_pt=box.get("text_size_pt", 11),
             color="808080", font=font, space_before=4, space_after=2)
    cap_text = caption if caption else "[Рисунок — ОПИСАНИЕ]"
    add_para(doc, cap_text, align=WD_ALIGN_PARAGRAPH.CENTER, italic=True,
             size_pt=box.get("caption_size_pt", 10), font=font,
             space_before=2, space_after=8)


def add_table(doc, columns, rows, font, widths=None, example_row=None,
              size_pt=None):
    """Таблица: строка заголовков (из spec) + (rows-1) строк данных.
    Первая строка данных — пример из образца (spec.example_row): серый
    курсив, плейсхолдеры «[ИМЯ | пример: …]» как в подсказках; остальные
    строки данных пустые."""
    n_cols = len(columns)
    t = doc.add_table(rows=rows, cols=n_cols)
    t.style = "Table Grid"
    tblGrid = t._tbl.find(qn("w:tblGrid"))
    grid_cols = tblGrid.findall(qn("w:gridCol"))
    for j, gc in enumerate(grid_cols):
        if widths and j < len(widths):
            gc.set(qn("w:w"), str(widths[j]))
    for row in t.rows:
        for j, cell in enumerate(row.cells):
            if widths and j < len(widths):
                cell.width = Twips(widths[j])
    # повтор строки заголовков на новых страницах
    hdr = t.rows[0]
    trPr = hdr._tr.get_or_add_trPr()
    tblHeader = OxmlElement("w:tblHeader")
    tblHeader.set(qn("w:val"), "true")
    trPr.append(tblHeader)
    for j, col in enumerate(columns):
        cell = hdr.cells[j]
        p = cell.paragraphs[0]
        set_run(p.add_run(), col, bold=True, size_pt=size_pt or 10, font=font)
    # данные (rows-1 строк): первая — пример из образца (серый курсив,
    # токены «[ИМЯ | пример: …]» не разделяются на строки — ячейка одна),
    # остальные — пустые
    for i in range(1, rows):
        for j in range(n_cols):
            cell = t.rows[i].cells[j]
            if i == 1 and example_row and j < len(example_row) \
                    and example_row[j]:
                set_run(cell.paragraphs[0].add_run(), example_row[j],
                        italic=True, size_pt=size_pt or 10, color="808080",
                        font=font)
            else:
                cell.paragraphs[0].add_run("")
    return t


def _field_run(p, instr, font):
    """Поле Word (PAGE/NUMPAGES): begin → instrText → separate →
    текст-заглушка → end (каноническая структура из отдельных runs)."""
    def _fld(kind):
        f = OxmlElement("w:fldChar")
        f.set(qn("w:fldCharType"), kind)
        return f
    r1 = p.add_run(); r1._element.append(_fld("begin"))
    r2 = p.add_run()
    it = OxmlElement("w:instrText")
    it.set(qn("xml:space"), "preserve")
    it.text = instr
    r2._element.append(it)
    r3 = p.add_run(); r3._element.append(_fld("separate"))
    r4 = p.add_run("1")
    r5 = p.add_run(); r5._element.append(_fld("end"))
    set_run(r4, "1", font=font)


def _hf_cell_text(cell, text, font, size_pt=10, page_number=None):
    """Текст ячейки колонтитула; строка с «N из M» → поля PAGE/NUMPAGES.
    Подпись и разделитель берутся из самой строки образца (или из
    spec.header_footer.<name>.page_number), не из кода."""
    pn = page_number or {}
    lines = text.split("\n")
    first = True
    for ln in lines:
        p = cell.paragraphs[0] if first else cell.add_paragraph()
        first = False
        m = PAGE_NUM_RE.match(ln)
        if m:
            label = pn.get("label", (m.group(1).strip() if m and m.group(1).strip() else "Стр."))
            sep = pn.get("sep", " из ")
            set_run(p.add_run(), label + " ", font=font, size_pt=size_pt)
            _field_run(p, pn.get("page_instr", "PAGE  \\* Arabic  \\* MERGEFORMAT"), font)
            set_run(p.add_run(), sep, font=font, size_pt=size_pt)
            _field_run(p, pn.get("numpages_instr", "NUMPAGES  \\* Arabic  \\* MERGEFORMAT"), font)
        else:
            set_run(p.add_run(), ln, font=font, size_pt=size_pt)


def setup_header_footer(doc, hf, fonts):
    """Колонтитулы из spec (п. 17/v5: «колонтитулы, поля» из образца).
    Таблица ячейками с ширинами колонок из spec.grids (tblGrid образца);
    первый колонтитул — таблица логотипов: лево/право, текста нет
    (как в образце). Кегль текста и параметры нумерации — из spec."""
    if not hf:
        return
    font = fonts.get("default_ascii", "Times New Roman")
    size_pt = fonts.get("header_footer_size_pt", 10)
    sec = doc.sections[0]
    # различие первой страницы — только когда есть титульный колонтитул
    # (элемент first-page-diff / title-page); иначе шаблон без титула
    # получил бы пустой первый лист
    sec.different_first_page_header_footer = bool(
        hf.get("first_page") or hf.get("first_page_images"))

    def _apply_grid(t, widths):
        grid_cols = t._tbl.find(qn("w:tblGrid")).findall(qn("w:gridCol"))
        for j, gc in enumerate(grid_cols):
            if j < len(widths):
                gc.set(qn("w:w"), str(widths[j]))

    if hf.get("first_page_images"):
        import base64
        fp = sec.first_page_header
        fp.is_linked_to_previous = False
        grid = (hf.get("first_page") or {}).get("grids", [[0]])[0]
        ncols = len(grid)
        t = fp.add_table(rows=1, cols=ncols, width=Emu(
            (sec.page_width or 0) - (sec.left_margin or 0) - (sec.right_margin or 0)))
        _apply_grid(t, grid)
        for j, cell in enumerate(t.rows[0].cells):
            if j < len(grid):
                cell.width = Twips(grid[j])
        fpi = hf["first_page_images"]
        if fpi.get("placeholder"):
            # режим sanitize: реальные логотипы (ПДн) не копируются —
            # текстовые заглушки по краям (позиции из spec.extents игнорируются)
            slots = sorted({0, ncols - 1})
            for j in slots:
                p = t.rows[0].cells[j].paragraphs[0]
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT if j == 0 else WD_ALIGN_PARAGRAPH.RIGHT
                set_run(p.add_run(),
                        "[ЛОГОТИП ЗАКАЗЧИКА]" if j == 0 else "[ЛОГОТИП ИСПОЛНИТЕЛЯ]",
                        italic=True, size_pt=10, color="808080", font=font)
        else:
            blobs = fpi["blobs"]
            exts = fpi["extents"]
            # образец: логотип в первой колонке (слева) и в последней (справа),
            # середина пустая; картинки раскладываются по краям
            slots = sorted({0, ncols - 1})
            for i, blob in enumerate(blobs):
                j = slots[min(i, len(slots) - 1)]
                p = t.rows[0].cells[j].paragraphs[0]
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT if j == 0 else WD_ALIGN_PARAGRAPH.RIGHT
                ext = exts[i]
                p.add_run().add_picture(
                    BytesIO(base64.b64decode(blob)),
                    width=Emu(int(ext[0])), height=Emu(int(ext[1])))
    from docx.shared import Emu as _Emu
    width = _Emu((sec.page_width or 0) - (sec.left_margin or 0) - (sec.right_margin or 0))
    for name in ("header", "footer"):
        blk = hf.get(name)
        if not blk:
            continue
        part = getattr(sec, name)
        part.is_linked_to_previous = False
        page_number = blk.get("page_number")
        for txt in blk.get("paras", []):
            set_run(part.add_paragraph().add_run(), to_placeholder(txt)[0],
                    font=font, size_pt=size_pt)
        rich = blk.get("cells_rich") or []
        imgs = blk.get("images")
        for gi, row in enumerate(blk.get("cells", [])):
            t = part.add_table(rows=1, cols=len(row), width=width)
            grids = blk.get("grids") or []
            if gi < len(grids):
                _apply_grid(t, grids[gi])
                for j, cell in enumerate(t.rows[0].cells):
                    if j < len(grids[gi]):
                        cell.width = Twips(grids[gi][j])
            # логотипы обычного колонтитула (Прогон #7: в образцах они на
            # всех страницах, не только на первой) — по краям таблицы
            if imgs and len(row) >= 2:
                for j, label in ((0, "[ЛОГОТИП ЗАКАЗЧИКА]"),
                                 (len(row) - 1, "[ЛОГОТИП ИСПОЛНИТЕЛЯ]")):
                    cell = t.rows[0].cells[j]
                    p = cell.paragraphs[0]
                    p.alignment = (WD_ALIGN_PARAGRAPH.LEFT if j == 0
                                   else WD_ALIGN_PARAGRAPH.RIGHT)
                    if imgs.get("placeholder"):
                        set_run(p.add_run(), label, italic=True, size_pt=10,
                                color="808080", font=font)
                    else:
                        idx = 0 if j == 0 else 1
                        exts = imgs.get("extents") or []
                        blobs = imgs.get("blobs") or []
                        if idx < len(blobs) and idx < len(exts):
                            import base64 as _b64
                            ext = exts[idx]
                            p.add_run().add_picture(
                                BytesIO(_b64.b64decode(blobs[idx])),
                                width=Emu(int(ext[0])),
                                height=Emu(int(ext[1])))
            for j, text in enumerate(row):
                cell = t.rows[0].cells[j]
                if gi < len(rich) and j < len(rich[gi]) and rich[gi][j]:
                    # жирность по абзацам образца: [текст, bold]; примеры —
                    # отдельными строками без жирного
                    first = True
                    for para_text, para_bold in rich[gi][j]:
                        if _PII_KEEP:
                            # Б4: keep — значения уже подставлены, НЕ
                            # ретокенизировать и не разрезать на примеры
                            seg = para_text.strip()
                            lines2 = [seg] if seg else []
                        else:
                            seg = to_placeholder(para_text.strip())[0] or para_text.strip()
                            if not seg:
                                continue
                            lines2 = split_examples(seg) if name == "header" else [seg]
                        for k, ln in enumerate(lines2):
                            p = cell.paragraphs[0] if first else cell.add_paragraph()
                            set_run(p.add_run(), ln, bold=para_bold and k == 0,
                                    font=font, size_pt=size_pt)
                            p.alignment = (WD_ALIGN_PARAGRAPH.LEFT if j == 0
                                           else WD_ALIGN_PARAGRAPH.RIGHT
                                           if j == len(row) - 1
                                           else WD_ALIGN_PARAGRAPH.CENTER)
                            first = False
                    continue
                if name == "header":
                    # тексты уже плейсхолдеризованы на extract; примеры —
                    # с новой строки (правило протокола)
                    text = "\n".join(
                        ln for l in text.split("\n")
                        for ln in split_examples(l))
                _hf_cell_text(cell, text, font, size_pt=size_pt,
                              page_number=page_number)
                for p in cell.paragraphs:
                    if j == 0:
                        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                    elif j == len(row) - 1:
                        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                    else:
                        p.alignment = WD_ALIGN_PARAGRAPH.CENTER


def setup_page(doc, page):
    sec = doc.sections[0]
    sec.page_width = Emu(page["width_emu"])
    sec.page_height = Emu(page["height_emu"])
    sec.left_margin = Emu(page["margin_left_emu"])
    sec.right_margin = Emu(page["margin_right_emu"])
    sec.top_margin = Emu(page["margin_top_emu"])
    sec.bottom_margin = Emu(page["margin_bottom_emu"])
    sec.header_distance = Emu(page["header_distance_emu"])
    sec.footer_distance = Emu(page["footer_distance_emu"])


def setup_default_font(doc, fonts):
    """Шрифт по умолчанию (docDefaults)."""
    font_name = fonts.get("default_ascii", "Times New Roman")
    size = fonts.get("default_size_pt", 12)
    styles_el = doc.styles.element
    dd = styles_el.find(qn("w:docDefaults"))
    rprd = dd.find(qn("w:rPrDefault"))
    if rprd is None:
        rprd = OxmlElement("w:rPrDefault")
        dd.append(rprd)
    rpr = rprd.find(qn("w:rPr"))
    if rpr is None:
        rpr = OxmlElement("w:rPr")
        rprd.append(rpr)
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.append(rf)
    for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rf.set(qn(a), font_name)
    # theme-атрибуты перебивают явный шрифт в части сборок Word — снять
    # (урок Прогона #8: заполненный документ уходил в Calibri)
    for a in ("w:asciiTheme", "w:hAnsiTheme", "w:cstheme", "w:eastAsiaTheme"):
        if rf.get(qn(a)) is not None:
            del rf.attrib[qn(a)]
    sz = rpr.find(qn("w:sz"))
    if sz is None:
        sz = OxmlElement("w:sz")
        rpr.append(sz)
    sz.set(qn("w:val"), str(int(size * 2)))
    # язык текста: из spec (docDefaults образца), иначе ru-RU — иначе
    # Word помечает русский текст как орфографические ошибки (красное
    # подчёркивание, Прогон #8)
    lang = rpr.find(qn("w:lang"))
    if lang is None:
        lang = OxmlElement("w:lang")
        rpr.append(lang)
    lang.set(qn("w:val"), fonts.get("lang") or "ru-RU")


def setup_heading_styles(doc, styles_spec, fonts, h1_page_break=None):
    """Настроить стили заголовков 1/2/3 по spec (шрифт, размер, цвет).
    Разрыв страницы перед H1 — параметр spec.h1_page_break.enabled
    (v6: включён; факт наличия в образцах — in_samples)."""
    font = fonts.get("default_ascii", "Times New Roman")
    h1_pb = (h1_page_break or {}).get("enabled", False)
    mapping = {1: "Heading 1", 2: "Heading 2", 3: "Heading 3"}
    for lvl, sname in mapping.items():
        key = f"heading_{lvl}"
        spec = styles_spec.get(key, {})
        try:
            st = doc.styles[sname]
        except KeyError:
            continue
        if lvl == 1 and h1_pb:
            # только если spec явно требует глобальный разрыв (v8: разрыв
            # задаётся пофаздельно из образцов, node["page_break"])
            pPr = st.element.get_or_add_pPr()
            if pPr.find(qn("w:pageBreakBefore")) is None:
                pb = OxmlElement("w:pageBreakBefore")
                pPr.append(pb)
        st.font.name = font
        # ТЕМА СИЛЬНЕЕ ЯВНОГО ШРИФТА: если в rPr стиля остались
        # asciiTheme/hAnsiTheme, Word рисует заголовки Калибри, какие
        # w:ascii ни ставь (E-32). Убрать все theme-ссылки на шрифт.
        rPr = st.element.get_or_add_rPr()
        rFonts = rPr.find(qn("w:rFonts"))
        if rFonts is not None:
            for attr in ("asciiTheme", "hAnsiTheme", "cstheme", "eastAsiaTheme"):
                if rFonts.get(qn("w:" + attr)) is not None:
                    del rFonts.attrib[qn("w:" + attr)]
        st.font.size = Pt(spec.get("size_pt") or 12)
        if spec.get("bold") is not None:
            st.font.bold = spec["bold"]
        color = spec.get("color")
        if color and len(color) == 6 and all(c in "0123456789ABCDEFabcdef" for c in color):
            st.font.color.rgb = RGBColor.from_string(color)
        else:
            # цвет не задан в образце (null) → чёрный; иначе остаётся синий
            # Word-дефолт стилей Heading, которого в оригинале нет
            st.font.color.rgb = RGBColor(0, 0, 0)


NUM_ID = 900
ABS_NUM_ID = 900


def setup_multilevel_numbering(doc, numbering_spec):
    """Создать многоступенчатую нумерацию, привязанную к стилям заголовков."""
    if not numbering_spec:
        return
    formats = numbering_spec.get("formats", ["%1.", "%1.%2.", "%1.%2.%3."])
    starts = numbering_spec.get("normalized_start", [1, 1, 1])
    levels = numbering_spec.get("levels", 3)

    # styleId заголовков в новом документе
    style_ids = {}
    for lvl in range(1, levels + 1):
        try:
            st = doc.styles[f"Heading {lvl}"]
            style_ids[lvl] = st.style_id
        except KeyError:
            style_ids[lvl] = f"Heading{lvl}"

    numbering_part = doc.part.numbering_part
    numbering_el = numbering_part.element

    # схема нумерации: abstractNum (определение) + num (экземпляр)
    abs_num = OxmlElement("w:abstractNum")
    abs_num.set(qn("w:abstractNumId"), str(ABS_NUM_ID))
    mlt = OxmlElement("w:multiLevelType")
    mlt.set(qn("w:val"), "multilevel")
    abs_num.append(mlt)
    for ilvl in range(levels):
        lvl = OxmlElement("w:lvl")
        lvl.set(qn("w:ilvl"), str(ilvl))
        start = OxmlElement("w:start")
        start.set(qn("w:val"), str(starts[ilvl] if ilvl < len(starts) else 1))
        lvl.append(start)
        fmt = OxmlElement("w:numFmt")
        fmt.set(qn("w:val"), "decimal")
        lvl.append(fmt)
        lvltext = OxmlElement("w:lvlText")
        lvltext.set(qn("w:val"), formats[ilvl] if ilvl < len(formats) else f"%{ilvl+1}.")
        lvl.append(lvltext)
        jc = OxmlElement("w:lvlJc")
        jc.set(qn("w:val"), "left")
        lvl.append(jc)
        pstyle = OxmlElement("w:pStyle")
        pstyle.set(qn("w:val"), style_ids[ilvl + 1])
        lvl.append(pstyle)
        suff = OxmlElement("w:suff")
        suff.set(qn("w:val"), "space")
        lvl.append(suff)
        abs_num.append(lvl)
    # по OOXML-схеме все abstractNum должны идти ДО элементов w:num
    first_num = numbering_el.find(qn("w:num"))
    if first_num is not None:
        first_num.addprevious(abs_num)
    else:
        numbering_el.append(abs_num)

    # num — экземпляр, связывающий numId с abstractNum
    num = OxmlElement("w:num")
    num.set(qn("w:numId"), str(NUM_ID))
    aref = OxmlElement("w:abstractNumId")
    aref.set(qn("w:val"), str(ABS_NUM_ID))
    num.append(aref)
    numbering_el.append(num)

    # привязать стили заголовков к num через numPr в pPr стиля
    for lvl in range(1, levels + 1):
        try:
            st = doc.styles[f"Heading {lvl}"]
        except KeyError:
            continue
        pPr = st.element.get_or_add_pPr()
        # удалить существующий numPr
        for old in pPr.findall(qn("w:numPr")):
            pPr.remove(old)
        numPr = OxmlElement("w:numPr")
        ilvl_e = OxmlElement("w:ilvl")
        ilvl_e.set(qn("w:val"), str(lvl - 1))
        numPr.append(ilvl_e)
        numid_e = OxmlElement("w:numId")
        numid_e.set(qn("w:val"), str(NUM_ID))
        numPr.append(numid_e)
        pPr.append(numPr)



def _toc_field(p, font, instr):
    """Поле оглавления (TOC по стилям Heading 1–3) с заглушкой-результатом.
    Инструкция поля — параметр spec.toc.instr."""
    def _fld(kind):
        f = OxmlElement("w:fldChar")
        f.set(qn("w:fldCharType"), kind)
        return f
    r1 = p.add_run(); r1._element.append(_fld("begin"))
    r2 = p.add_run()
    it = OxmlElement("w:instrText")
    it.set(qn("xml:space"), "preserve")
    it.text = instr
    r2._element.append(it)
    r3 = p.add_run(); r3._element.append(_fld("separate"))
    set_run(p.add_run(), "Обновите поле — Ctrl+A, затем F9", font=font, size_pt=12)
    r5 = p.add_run(); r5._element.append(_fld("end"))


def add_toc_page(doc, font, toc_spec=None, styles_spec=None):
    """Оглавление — на отдельной странице, если spec.toc.present
    (v6: всегда; факт в образцах — in_samples). Заголовок «Оглавление» —
    прямой формат (без стиля Heading, чтобы не нумеровался и не попадал
    в TOC); кегль — из spec.styles.heading_1."""
    toc_spec = toc_spec or {}
    if not toc_spec.get("present", True):
        return
    h1_spec = (styles_spec or {}).get("heading_1", {})
    # pageBreakBefore на заголовке «Оглавление» вместо отдельного абзаца-
    # разрыва: пустой абзац-разрыв сам занимает строку и создаёт пустой лист,
    # если титульник заполнен до конца
    p = add_para(doc, toc_spec.get("title") or "Оглавление", bold=True,
                 size_pt=toc_spec.get("title_size_pt")
                 or h1_spec.get("size_pt") or 12,
                 font=font, space_after=12)
    p.paragraph_format.page_break_before = True
    p = doc.add_paragraph()
    _toc_field(p, font, toc_spec.get("instr", 'TOC \\o "1-3" \\z \\u'))
    # разрыв после оглавления не нужен: Heading 1 имеет pageBreakBefore


def _strip_examples(text):
    """«ВЕРСИЯ: [N | пример: 2]» → «ВЕРСИЯ: [N]» (токен без примера)."""
    return _EXAMPLE_RE.sub(r"[\1]", text)


def render_title_block(doc, title_block, fonts):
    """Титульный лист 1:1 с образцом: размер/жирность/КАПС из spec,
    блок подписей (ЗАКАЗЧИК/ИСПОЛНИТЕЛЬ) из вложенных таблиц шапки
    (с ширинами колонок из образца). Пример — строка ЦЕЛИКОМ
    (spec.example_line: «ВЕРСИЯ: 2», а не «2»)."""
    font = fonts.get("default_ascii", "Times New Roman")
    for item in title_block:
        if "sig_rows" in item:
            rows = item["sig_rows"]
            bolds = item.get("sig_bold") or []
            widths = item.get("sig_widths")
            props = item.get("sig_tbl") or {}
            heights = item.get("sig_heights") or []
            t = doc.add_table(rows=len(rows), cols=2)
            # геометрия — из образца (данные, не константы): ширина
            # таблицы, нулевые поля ячеек, высоты строк (E-32)
            tblPr = t._tbl.tblPr
            if props.get("w"):
                tw = tblPr.find(qn("w:tblW"))
                if tw is None:
                    tw = OxmlElement("w:tblW")
                    tblPr.append(tw)
                tw.set(qn("w:type"), "dxa")
                tw.set(qn("w:w"), str(props["w"]))
            if "mar_l" in props or "mar_r" in props:
                mar = tblPr.find(qn("w:tblCellMar"))
                if mar is None:
                    mar = OxmlElement("w:tblCellMar")
                    tblPr.append(mar)
                for tag, key in (("left", "mar_l"), ("right", "mar_r")):
                    if key in props:
                        el = mar.find(qn("w:" + tag))
                        if el is None:
                            el = OxmlElement("w:" + tag)
                            mar.append(el)
                        el.set(qn("w:w"), str(props[key]))
                        el.set(qn("w:type"), "dxa")
            if heights:
                for i, row in enumerate(t.rows):
                    if i < len(heights) and heights[i]:
                        row.height = Twips(heights[i])
            if widths:
                grid_cols = t._tbl.find(qn("w:tblGrid")).findall(qn("w:gridCol"))
                for j, gc in enumerate(grid_cols):
                    if j < len(widths):
                        gc.set(qn("w:w"), str(widths[j]))
            for i, (l, r) in enumerate(rows):
                # без объединения одинаковых ячеек: в образце должность и
                # прочие строки стоят в КАЖДОЙ колонке отдельно (объединение
                # уводит текст в центр таблицы — визуальный дефект, E-14)
                cells = [(t.cell(i, 0), l), (t.cell(i, 1), r)]
                for j, (cell, txt) in enumerate(cells):
                    if widths and j < len(widths):
                        cell.width = Twips(widths[j])
                    # жирность ячейки — из образца (ЗАКАЗЧИК/ИСПОЛНИТЕЛЬ
                    # жирные, должности — нет); у строк-примеров жирности нет
                    bold = bool(bolds and i < len(bolds) and j < len(bolds[i])
                                and bolds[i][j])
                    lines = split_examples(txt)
                    sig_size = fonts.get("sig_size_pt") or 12
                    for k, ln in enumerate(lines):
                        p = cell.paragraphs[0] if k == 0 else cell.add_paragraph()
                        # строки-примеры — мелкий кегль: титул умещается на
                        # одном листе, как в образцах (E-15)
                        set_run(p.add_run(), ln, font=font,
                                bold=bold if (bold and
                                              not ln.startswith("[пример:")) else None,
                                size_pt=9 if ln.startswith("[пример:") else sig_size)
                if i < len(rows) - 1:
                    t.cell(i, 0).paragraphs[0].paragraph_format.space_after = Pt(6)
            # без пустого абзаца после подписей: он переливается на следующий
            # лист и создаёт пустую страницу (разрыв теперь pageBreakBefore)
            continue
        text = item.get("text", "")
        size = item.get("size_pt") or 12
        bold = item.get("bold", False)
        caps = item.get("caps", False)
        example_line = item.get("example_line")
        # абзацные параметры — ИЗ ОБРАЗЦА (E-39): спейсеры/отступы/поля,
        # не константа; нет данных → 0 (стиль Normal), не «на глаз»
        spc = item.get("spacing") or {}
        lines = ([_strip_examples(text), f"[пример: {example_line}]"]
                 if example_line else split_examples(text))
        for ln in lines:
            is_example = ln.startswith("[пример:")
            # строка-пример — без caps/жирности и мелким кеглем: отличается
            # визуально и не распирает титул (E-15)
            p = add_para(doc, ln, align=WD_ALIGN_PARAGRAPH.CENTER,
                         bold=False if is_example else bold,
                         size_pt=9 if is_example else size, font=font,
                         space_after=spc.get("sasa") or 0)
            if spc.get("sasb") and not is_example:
                p.paragraph_format.space_before = Pt(spc["sasb"])
            if spc.get("fli") and not is_example:
                p.paragraph_format.first_line_indent = Pt(spc["fli"])
            if caps and not is_example:
                for r in p.runs:
                    r.font.all_caps = True


def render_section(doc, node, fonts, counters, screenshot_box=None):
    font = fonts.get("default_ascii", "Times New Roman")
    lvl = node["level"]
    # заголовок: L1/L2 — как в образце (с плейсхолдерами); L3 — плейсхолдер
    # [ПОДФУНКЦИЯ N | пример: <название>] (название из образца — пример того,
    # что за подфункция; агент замещает токен и удаляет пример)
    if lvl == 3:
        counters["h3"] += 1
        name = node.get("title", "").strip()
        if name and not name.startswith("["):
            title = f"[ПОДФУНКЦИЯ {counters['h3']} | пример: {name}]"
        else:
            title = f"[ПОДФУНКЦИЯ {counters['h3']}]"
    else:
        title = node.get("title", "")
    # вписанная нумерация заголовка («1.», «4.3.1.») снимается: шаблон
    # даёт СВОЮ многоступенчатую нумерацию — иначе «1. 1. Источник…»
    # (гейт 2 тех-прогона E-50). Бизнес-заголовки чисел не содержат.
    title = re.sub(r"^\s*\d+(?:\.\d+)*[.)]\s+", "", title)
    hp = add_para(doc, title, style=f"Heading {lvl}", font=font)
    if lvl == 1 and node.get("page_break"):
        # разрыв — из образца: не каждый раздел, а те, что в образце
        # начинаются с новой страницы (Прогон #9)
        hp.paragraph_format.page_break_before = True
    # подсказка
    if node.get("hint"):
        add_hint(doc, node["hint"], font)
    for blk in node.get("body", []):
        btype = blk["type"]
        if btype == "paragraph":
            add_para(doc, blk.get("text") or "[ТЕКСТ: опишите действие/результат]",
                     size_pt=fonts.get("default_size_pt") or 12, font=font,
                     space_after=4)
        elif btype == "table":
            add_table(doc, blk["columns"], blk["rows"], font,
                      blk.get("widths"), blk.get("example_row"),
                      size_pt=fonts.get("table_size_pt"))
            add_para(doc, "", size_pt=6, font=font)
        elif btype == "screenshot":
            add_screenshot_placeholder(doc, blk.get("caption"), font, screenshot_box)
        elif btype == "list":
            # формат из spec (extract): bullet → List Bullet, decimal →
            # List Number; без fmt — нейтральный List Paragraph
            lstyle = {"bullet": "List Bullet", "decimal": "List Number"}.get(
                blk.get("fmt"), "List Paragraph")
            for _ in blk.get("items", []):
                add_para(doc, "[ПУНКТ]", style=lstyle, size_pt=12,
                         font=font, space_after=2)
        elif btype == "caption":
            # кегль — из образца (blk.size_pt), фолбэк 10
            add_para(doc, blk.get("text", ""), align=WD_ALIGN_PARAGRAPH.CENTER,
                     italic=True, size_pt=blk.get("size_pt") or 10, font=font)
    for c in node.get("children", []):
        render_section(doc, c, fonts, counters, screenshot_box)


def _trim_trailing_spacers(title_block):
    """Хвостовые пустые абзацы титульника — перед явным разрывом страницы
    они только создают пустой лист (разрыв есть в шаблоне, в образце его нет).
    Внутренние (вертикальный ритм) сохраняются."""
    while title_block:
        last = title_block[-1]
        if "sig_rows" in last or last.get("text"):
            break
        title_block.pop()


from extract_spec import substitute_keep as _substitute_keep, to_placeholder

# pii=keep (Б4): значения подставлены substitute_keep; ретокенизация
# в ветке cells_rich ЗАПРЕЩЕНА (токен и строка-пример возвращались,
# реальное значение терялось)
_PII_KEEP = False


def main():
    global _PII_KEEP
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", help="путь к spec.json")
    ap.add_argument("-o", "--out", default="шаблон_ТЗ_1С.docx")
    ap.add_argument("--pii", choices=("sanitize", "keep"), default=None,
                    help="ПДн: sanitize (по умолчанию) / keep — переопределяет "
                         "pii_mode из spec.json")
    args = ap.parse_args()

    with open(args.spec, encoding="utf-8") as fh:
        spec = json.load(fh)
    pii_mode = args.pii if args.pii else (spec.get("meta") or {}).get("pii_mode")
    if pii_mode == "keep":
        spec = _substitute_keep(spec)
        _PII_KEEP = True

    doc = Document()
    fonts = spec.get("fonts", {})
    setup_page(doc, spec.get("page", {}))
    setup_header_footer(doc, spec.get("header_footer"), fonts)
    setup_default_font(doc, fonts)
    try:
        se = doc.settings.element
        for tag in ("w:hideSpellingErrors", "w:hideGrammaticalErrors"):
            if se.find(qn(tag)) is None:
                se.append(OxmlElement(tag))
    except Exception:
        pass
    setup_heading_styles(doc, spec.get("styles", {}), fonts,
                         spec.get("h1_page_break"))
    setup_multilevel_numbering(doc, spec.get("numbering"))

    title_block = list(spec.get("title_block", []))
    _trim_trailing_spacers(title_block)
    render_title_block(doc, title_block, fonts)
    add_toc_page(doc, fonts.get("default_ascii", "Times New Roman"),
                 spec.get("toc"), spec.get("styles"))

    counters = {"h3": 0}
    screenshot_box = spec.get("screenshot_box")
    for s in spec.get("sections", []):
        render_section(doc, s, fonts, counters, screenshot_box)

    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    doc.save(out_path)
    # язык проверки правописания — как у текста ТЗ (образцы приносят чужой
    # язык Word заказчика: it-IT/en-US → русский текст подчёркивается)
    _lang = lang_tag((spec.get("meta") or {}).get("language"))
    _lrep = set_language_ru(out_path, _lang)
    if _lrep["foreign"] or _lrep["defaults"]:
        print(f"[build_from_spec] ВНИМАНИЕ: язык документа не {_lang} "
              f"(чужеродных тегов {len(_lrep['foreign'])}, "
              f"дефектов по умолчанию {len(_lrep['defaults'])})",
              file=sys.stderr)
    print(f"[build_from_spec] шаблон -> {out_path} (язык {_lang})",
          file=sys.stderr)


if __name__ == "__main__":
    main()