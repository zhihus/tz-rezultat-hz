# -*- coding: utf-8 -*-
"""
render_md.py — шаг конвейера (v6 §17): Markdown → DOCX через шаблон.

Строгий диалект (детерминированный парсер, без внешних md-библиотек):
  - заголовки '#'–'####' → стили Heading 1–4;
  - pipe-таблицы (первая строка — заголовки, повтор на новых страницах);
  - списки '-' и '1.' → стиль List Paragraph;
  - абзацы; инлайн — только **жирный**.

Шаблон DOCX даёт стили заголовков, многоступенчатую нумерацию, параметры
страницы, шрифт и титульный блок (всё до первого Heading 1 остаётся как есть);
содержимое шаблона после первого Heading 1 заменяется содержимым Markdown.

Использование:
    python render_md.py текст.md --template шаблон.docx -o выход.docx
"""
import argparse
import io
import json
import os
import re
import sys

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Twips

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))  # portable python: папка скрипта не в sys.path
from tz_common import setup_utf8_stdout, lang_tag, set_language_ru

setup_utf8_stdout()


def _norm_tokens(headers):
    words = set()
    for h in headers:
        for w in re.sub(r"\[[^\]]*\]", "", h).lower().replace("/", " ").split():
            words.add(w)
    return words


def _widths_for(columns, spec_tables):
    """Ширины колонок из spec (tblGrid образца): матчинг по числу колонок
    и перекрытию слов заголовков ≥ 50%. Нет матча — None (поровну)."""
    tokens = _norm_tokens(columns)
    for st in spec_tables:
        if len(st.get("columns", [])) != len(columns):
            continue
        st_tokens = _norm_tokens(st.get("columns", []))
        overlap = len(tokens & st_tokens)
        if overlap >= 0.5 * max(1, min(len(tokens), len(st_tokens))):
            if st.get("widths"):
                return st["widths"]
    return None


def _colbold_for(columns, spec_tables):
    """Жирность колонок данных из spec (образца): колонка, жирная в
    образце (напр. роль в таблице тестирования), рендерится жирной.
    Матчинг таблицы — как в _widths_for."""
    tokens = _norm_tokens(columns)
    for st in spec_tables:
        if len(st.get("columns", [])) != len(columns):
            continue
        st_tokens = _norm_tokens(st.get("columns", []))
        overlap = len(tokens & st_tokens)
        if overlap >= 0.5 * max(1, min(len(tokens), len(st_tokens))):
            cb = st.get("col_bold")
            if cb:
                return cb
    return None


def _match_table(columns, spec_tables):
    """Таблица spec по заголовкам → has_caption (True/False); None —
    таблицы нет в spec (старое поведение: подпись обязательна).
    E-59: если в spec НЕТ НИ ОДНОЙ таблицы с подписью — в образцах
    подписей таблиц не существует вовсе: неизвестная таблица НЕ
    получает плейсхолдер «Таблица - [НОМЕР]» (гейт «Плейсхолдеры
    заполнены» ловил вечный FAIL на одно-образцовых проектах)."""
    if not spec_tables:
        return False
    tokens = _norm_tokens(columns)
    for st in spec_tables:
        if len(st.get("columns", [])) != len(columns):
            continue
        st_tokens = _norm_tokens(st.get("columns", []))
        overlap = len(tokens & st_tokens)
        if overlap >= 0.5 * max(1, min(len(tokens), len(st_tokens))):
            hc = st.get("has_caption")
            return hc if hc is not None else True
    return True


def _collead_for(columns, spec_tables):
    """Колонки с жирным префиксом-ролью из spec (образца): в ячейках
    таких колонок жирным рендерится префикс до первой «.«/»,» включительно
    (в таблице тестирования «Кладовщик производства. Нажать…»)."""
    tokens = _norm_tokens(columns)
    for st in spec_tables:
        if len(st.get("columns", [])) != len(columns):
            continue
        st_tokens = _norm_tokens(st.get("columns", []))
        overlap = len(tokens & st_tokens)
        if overlap >= 0.5 * max(1, min(len(tokens), len(st_tokens))):
            cl = st.get("col_lead")
            if cl:
                return cl
    return None


def _lead_split(text, roles=()):
    """Текст → (жирный префикс, остаток). Граница — РОЛЬ из словаря
    образцов (колонки «Роль»/«Должность»), два уровня:
    1) ячейка начинается с известной роли целиком — жирный до конца
       роли (+ знак препинания);
    2) иначе первое слово ячейки совпадает с первым словом какой-либо
       роли («Кладовщик производства» ↔ «Кладовщик склада») — жирный
       до первой «.»/«,» включительно;
    3) иначе ничего не жирнить (E-41: «до первой точки» жирнил и
       текст после роли, напр. «Пользователь с установленной…»)."""
    low = text.lower()
    best = None
    for r in roles:
        rl = str(r).strip().lower()
        if rl and low.startswith(rl) and (best is None or len(r) > len(best)):
            best = str(r).strip()
    if best:
        end = len(best)
        if end < len(text) and text[end] in ".,;":
            end += 1
        return text[:end], text[end:]
    first = re.split(r"[\s]+", text.strip(), 1)[0].lower().strip("«»")
    if len(first) > 3 and any(str(r).strip().lower().startswith(first)
                              for r in roles):
        m = re.search(r"[.,]", text)
        if m:
            return text[:m.end()], text[m.end():]
    # 3) короткая фраза до «:» — роль в форме модели
    #    («Руководитель производства: нажать…»): ≤4 слов → жирная,
    #    повествование длиннее — не жирным (E-41, случай Прогона #11)
    m = re.match(r"^([^.:,]{1,60}?):\s", text)
    if m and len(m.group(1).split()) <= 4:
        return text[:m.end()], text[m.end():]
    return None, text


def strip_inline(text):
    """Инлайн-разметка → runs. Диалект: **жирный**."""
    parts = re.split(r"\*\*(.+?)\*\*", text)
    out = []
    for i, part in enumerate(parts):
        if part:
            out.append((part, i % 2 == 1))
    return out


def _add_bookmark(paragraph, name, _ids=[0]):
    """Закладка Word на абзаце (якорь для внутренних ссылок «(Рисунок - N)»)."""
    _ids[0] += 1
    start = paragraph._p.makeelement(qn("w:bookmarkStart"), {})
    start.set(qn("w:id"), str(_ids[0]))
    start.set(qn("w:name"), name)
    end = paragraph._p.makeelement(qn("w:bookmarkEnd"), {})
    end.set(qn("w:id"), str(_ids[0]))
    paragraph._p.insert(0, start)
    paragraph._p.append(end)


def _add_ref_run(paragraph, text, font, size_pt):
    """«(Рисунок - N)» как ВНУТРЕННЯЯ гиперссылка на закладку Рисунок_N —
    как в образцах: пользователь кликает и попадает к скриншоту
    (Прогон #9). Для локальной модели прозрачно: она пишет обычный текст."""
    hl = paragraph._p.makeelement(qn("w:hyperlink"), {})
    m = re.search("(\d+)", text)
    num = m.group(1) if m else "0"
    hl.set(qn("w:anchor"), "Рисунок_" + num)
    r = paragraph._p.makeelement(qn("w:r"), {})
    rPr = paragraph._p.makeelement(qn("w:rPr"), {})
    rf = paragraph._p.makeelement(qn("w:rFonts"), {})
    if font:
        for a in ("w:ascii", "w:hAnsi", "w:cs"):
            rf.set(qn(a), font)
    rPr.append(rf)
    if size_pt:
        sz = paragraph._p.makeelement(qn("w:sz"), {})
        sz.set(qn("w:val"), str(int(size_pt * 2)))
        rPr.append(sz)
    r.append(rPr)
    t = paragraph._p.makeelement(qn("w:t"), {})
    t.text = text
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    r.append(t)
    hl.append(r)
    paragraph._p.append(hl)


def add_runs(p, text, *, font=None, size_pt=None):
    for chunk, bold in strip_inline(text):
        r = p.add_run(chunk)
        r.bold = bold if bold else None
        if font:
            r.font.name = font
            rPr = r._element.get_or_add_rPr()
            rf = rPr.find(qn("w:rFonts"))
            if rf is None:
                rf = r._element.makeelement(qn("w:rFonts"), {})
                rPr.append(rf)
            for a in ("w:ascii", "w:hAnsi", "w:cs"):
                rf.set(qn(a), font)
        if size_pt:
            r.font.size = Pt(size_pt)


def add_para(doc, text, *, style=None, font=None, size_pt=None,
             align=None, italic=None, color=None):
    p = doc.add_paragraph(style=style)
    if align is not None:
        p.alignment = align
    add_runs(p, text, font=font, size_pt=size_pt)
    if italic:
        for r in p.runs:
            r.italic = True
    if color:
        for r in p.runs:
            r.font.color.rgb = RGBColor.from_string(color)
    return p


def add_table(doc, rows, font, widths=None, col_bold=None, col_lead=None,
              roles=(),
              size_pt=None):
    """Pipe-таблица: строки уже разделены; первая — заголовки.
    Ширины колонок (twips) и жирность колонок данных — из spec
    (tblGrid образца), не «поровну»."""
    n_cols = len(rows[0])
    t = doc.add_table(rows=len(rows), cols=n_cols)
    t.style = "Table Grid"
    # E-59: строка таблицы не разрывается между страницами (визуальный
    # судья ловил «сироту» — остаток переноса строки на следующей
    # странице); вся строка переносится целиком
    from docx.oxml import OxmlElement
    for _row in t.rows:
        _trPr = _row._tr.get_or_add_trPr()
        if _trPr.find(qn("w:cantSplit")) is None:
            _trPr.append(OxmlElement("w:cantSplit"))
    grid_cols = t._tbl.find(qn("w:tblGrid")).findall(qn("w:gridCol"))
    for j, gc in enumerate(grid_cols):
        if widths and j < len(widths):
            gc.set(qn("w:w"), str(widths[j]))
    for i, row in enumerate(rows):
        for j, cell in enumerate(row):
            if widths and j < len(widths):
                t.rows[i].cells[j].width = Twips(widths[j])
            p = t.rows[i].cells[j].paragraphs[0]
            if i > 0 and col_lead and j < len(col_lead) and col_lead[j]:
                # жирный префикс — только РОЛЬ из словаря образцов
                # (колонки «Роль»/«Должность»); не роль → без жирного
                pre, rest = _lead_split(cell, roles)
                if pre:
                    add_runs(p, "**" + pre.strip() + "**", font=font,
                             size_pt=size_pt or 10)
                    add_runs(p, " " + rest.strip() if rest.strip() else "",
                             font=font, size_pt=size_pt or 10)
                    continue
            add_runs(p, cell, font=font, size_pt=size_pt or 10)
            if i == 0:
                for r in p.runs:
                    r.bold = True
            elif col_bold and j < len(col_bold) and col_bold[j]:
                # жирная колонка данных — из образца
                for r in p.runs:
                    r.bold = True
    hdr = t.rows[0]
    trPr = hdr._tr.get_or_add_trPr()
    tbl_header = hdr._tr.makeelement(qn("w:tblHeader"), {})
    trPr.append(tbl_header)
    return t


def parse_md(lines):
    """Строгий диалект → блоки: ('h', lvl, text) | ('p', text) | ('li', text) |
    ('table', [[cell,...],...])."""
    blocks = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i].rstrip()
        if not ln.strip() or ln.strip() == "---":
            i += 1
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", ln)
        if m:
            blocks.append(("h", len(m.group(1)), m.group(2).strip()))
            i += 1
            continue
        if ln.lstrip().startswith("|"):
            rows = []
            while i < n and lines[i].lstrip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                blocks.append(("table", rows))
            continue
        m = re.match(r"^\s*[-•]\s+(.*)$", ln)
        if m:
            # List Paragraph сам не даёт буллита — маркер сохраняем в тексте
            blocks.append(("li", "• " + m.group(1).strip()))
            i += 1
            continue
        m = re.match(r"^\s*(\d+\.)\s+(.*)$", ln)
        if m:
            blocks.append(("li", m.group(1) + " " + m.group(2).strip()))
            i += 1
            continue
        blocks.append(("p", ln.strip()))
        i += 1
    return blocks



# Ссылка на рисунок в тексте — конвенция стиля ТЗ (writer-profiles);
# переопределяется spec.figure_ref_pattern (данные, не код)
FIGURE_REF_RE = r"\(\s*Рис(?:унок|\.)?\s*-?\s*(\d+)\s*\)"

# шаг смещения заголовка вправо на уровень (~0.6 см): «немножко вправо»
HEADING_STEP = 340

# маркер сообщения пользователю в черновике (naming-and-emphasis-universal):
# рендерится по конвенции spec.meta.message_emphasis (G18 линта — при null)
_MSG_MARK_RE = re.compile(r"^\[СООБЩЕНИЕ:\s*([^\[\]]+)\]$")


def _split_figure_refs(text, pat):
    """Разбить абзац на сегменты: (текст, номер рисунка|None).
    Сегмент-ссылка рендерится гиперссылкой, обычный текст — рантами."""
    out, last = [], 0
    for m in re.finditer(pat, text):
        if m.start() > last:
            out.append((text[last:m.start()], None))
        out.append((m.group(0), m.group(1)))
        last = m.end()
    if last < len(text):
        out.append((text[last:], None))
    return out or [(text, None)]

def render(doc, blocks, font, spec=None):
    """Рендер блоков в DOCX. Ритм абзацев тела (отступ первой строки,
    выравнивание) и ширины таблиц — из spec образца, не «в лоб»."""
    pspec = (spec or {}).get("paragraph") or {}
    indent = pspec.get("first_line_indent")
    align = pspec.get("align")
    dsize = ((spec or {}).get("fonts") or {}).get("default_size_pt") or 12
    # ширины/жирность: таблицы шаблона + миноритарные вариации (E-52,
    # реквизиты тех-ТЗ); density.tables — ТОЛЬКО шаблонные (гейт сверяет
    # его с шаблоном), вариации живут в spec.variations.tables
    spec_tables = (((spec or {}).get("density") or {}).get("tables") or [])
    spec_tables += [t for t in ((spec or {}).get("variations") or {}).get("tables") or []
                    if isinstance(t, dict)]
    for blk in blocks:
        kind = blk[0]
        if kind == "h":
            lvl = min(blk[1], 4)
            p = add_para(doc, blk[2], style=f"Heading {lvl}", font=font)
            # иерархия видна: подчинённые заголовки смещены вправо
            # относительно головного (урок 2026-11-19); H1 — без отступа
            p.paragraph_format.left_indent = Twips(HEADING_STEP * (lvl - 1))
        elif kind == "p":
            # маркер сообщения пользователю (naming-and-emphasis-universal):
            # [СООБЩЕНИЕ: текст] → абзац по конвенции spec.meta.message_emphasis
            # (курсив/цвет — как выделены сообщения в образцах)
            _mm = _MSG_MARK_RE.match(blk[1].strip())
            if _mm and ((spec or {}).get("meta") or {}).get("message_emphasis"):
                _me = spec["meta"]["message_emphasis"]
                p = add_para(doc, _mm.group(1).strip(), font=font, size_pt=dsize,
                             italic=bool(_me.get("italic")),
                             color=_me.get("color") or None)
                if indent:
                    p.paragraph_format.first_line_indent = Twips(indent)
                continue
            pat = (spec or {}).get("figure_ref_pattern") or FIGURE_REF_RE
            parts = _split_figure_refs(blk[1], pat)
            p = doc.add_paragraph()
            for seg, ref in parts:
                if ref:
                    _add_ref_run(p, seg, font, 12)
                else:
                    add_runs(p, seg, font=font, size_pt=dsize)
            if indent:
                p.paragraph_format.first_line_indent = Twips(indent)
            if align == "both":
                p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            # после абзаца с ссылкой — место под скриншот и подпись
            # с ЗАКЛАДКОЙ: клик по «(Рисунок - N)» ведёт сюда
            for num in [r for _, r in parts if r]:
                ph = add_para(doc, "[СКРИНШОТ: вставьте изображение]",
                              align=WD_ALIGN_PARAGRAPH.CENTER, italic=True,
                              size_pt=11, color="808080", font=font)
                # пара «заглушка + подпись» не рвётся между страницами
                # (урок V9: судья поймал разрыв на границе страниц)
                ph.paragraph_format.keep_with_next = True
                cap = add_para(
                    doc, f"Рисунок - {num} [ОПИСАНИЕ ИЗОБРАЖЕНИЯ]",
                    align=WD_ALIGN_PARAGRAPH.CENTER, italic=True,
                    size_pt=dsize, font=font)
                _add_bookmark(cap, f"Рисунок_{num}")
        elif kind == "li":
            add_para(doc, blk[1], style="List Paragraph", font=font, size_pt=dsize)
        elif kind == "table":
            # подпись таблицы обязательна (Прогон #8): берём из
            # предшествующего абзаца «Таблица N. …», иначе ставим
            # плейсхолдер; оформляем КАК ПОДПИСЬ РИСУНКА — тот же стиль
            # образца (центр, курсив, интервалы 12pt) + ЗАКЛАДКА
            # Таблица_N (E-42: была простым текстом)
            tbl_spec = _match_table(blk[1][0], spec_tables)
            if tbl_spec is False and _prev_is_caption(doc):
                # в образцах у этой таблицы подписи нет — убрать модельную
                for _q in reversed(doc.paragraphs):
                    if re.match(r"^\s*Таблица", _q.text.strip()):
                        _q._p.getparent().remove(_q._p)
                        break
            elif tbl_spec is not False and _prev_is_caption(doc):
                _style_table_caption(doc, font, dsize)
            elif tbl_spec:
                add_para(doc, "Таблица - [НОМЕР]. [НАЗВАНИЕ ТАБЛИЦЫ]",
                         align=WD_ALIGN_PARAGRAPH.CENTER, italic=True,
                         size_pt=dsize, font=font)
                _style_table_caption(doc, font, dsize)
            add_table(doc, blk[1], font, _widths_for(blk[1][0], spec_tables),
                       _colbold_for(blk[1][0], spec_tables),
                       _collead_for(blk[1][0], spec_tables),
                       roles=(spec or {}).get("roles") or (),
                       size_pt=(spec or {}).get("fonts", {}).get("table_size_pt"))
            add_para(doc, "", font=font, size_pt=6)

    # раздел «Источники» — детерминированно к форме образцов (E-45)
    _fix_sources_section(doc, font, dsize)


def _style_table_caption(doc, font, dsize):
    """Последний абзац «Таблица …» → оформление подписи как у рисунков
    (центр, курсив, интервалы 12pt из стиля образца) + закладка
    Таблица_N по номеру из текста (нет номера — счётчик)."""
    body = doc.element.body
    for child in reversed(list(body.iterchildren())):
        if child.tag == qn("w:p"):
            txt = "".join(t.text or "" for t in child.findall(".//" + qn("w:t")))
            if not re.match(r"^\s*Таблица", txt.strip()):
                return
            from docx.text.paragraph import Paragraph
            par = Paragraph(child, doc)
            par.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for r in par.runs:
                r.italic = True
                if r.font.size is None:
                    r.font.size = Pt(dsize)
            par.paragraph_format.space_before = Pt(12)
            par.paragraph_format.space_after = Pt(12)
            par.paragraph_format.keep_with_next = True
            m = re.search(r"Таблица\s*-?\s*(\d+)", txt)
            num = m.group(1) if m else str(
                sum(1 for b in body.iterchildren()
                    if b.tag == qn("w:p")
                    and re.match(r"^\s*Таблица", "".join(
                        t.text or "" for t in b.findall(".//" + qn("w:t"))))))
            _add_bookmark(par, f"Таблица_{num}")
            return
        if child.tag == qn("w:tbl"):
            return


_SRC_RE = re.compile(r"^\s*(Протокол|Функциональная модель|Регламент|"
                     r"Постановка задачи|Ссылка на)", re.I)


def _fix_sources_section(doc, font, dsize):
    """Раздел «Источники для разработки» — к форме ОБРАЗЦОВ детерминированно
    (E-45: модель трижды писала описание раньше источника):
    1) первый абзац раздела — указание источника; если модель его не
       написала, вставляется плейсхолдер «Протокол №[НОМЕР ПРОТОКОЛА]
       от [ДАТА ПРОТОКОЛА]» (заполняет пользователь, не выдумка);
    2) описание доработки оформляется как «Описание [КОД]: …».
    Порядок и форма — код, модели писать их не нужно."""
    body = doc.element.body
    paras = doc.paragraphs
    start = None
    for i, p in enumerate(paras):
        # «Источники» в любой форме заголовка («Источники», «Источники
        # для разработки») — модель сокращает; тех-скелет «Источник
        # информации…» не матчится («Источник» ≠ «Источники»)
        if "Источники" in p.text and (p.style.name or "").startswith("Heading"):
            start = i + 1
            break
    if start is None:
        return
    content = []
    for p in paras[start:]:
        if (p.style.name or "").startswith("Heading") and p.text.strip():
            break
        if p.text.strip():
            content.append(p)
    if not content:
        return
    first = content[0]
    if not _SRC_RE.match(first.text):
        new = doc.add_paragraph()
        r = new.add_run("Протокол №[НОМЕР ПРОТОКОЛА] от [ДАТА ПРОТОКОЛА]")
        r.bold = True
        r.font.size = Pt(dsize)
        r.font.name = font
        new.paragraph_format.space_after = Pt(6)
        first._p.addprevious(new._p)
    # описание: первый абзац после источника получает форму
    # «Описание [КОД]: …» (если модель сама так не написала)
    after = [q for q in content if q._p is not first._p]
    desc = None
    for q in ([first] + after) if _SRC_RE.match(first.text) is None else after:
        if not _SRC_RE.match(q.text):
            desc = q
            break
    if desc is not None and not desc.text.strip().lower().startswith("описание"):
        t = desc.text.strip()
        for r in list(desc.runs):
            r._element.getparent().remove(r._element)
        r = desc.add_run(f"Описание [КОД]: {t}")
        r.font.size = Pt(dsize)
        r.font.name = font


def _prev_is_caption(doc):
    """True, если последний абзац тела — подпись «Таблица …»."""
    body = doc.element.body
    for child in reversed(list(body.iterchildren())):
        if child.tag == qn("w:p"):
            txt = "".join(t.text or "" for t in child.findall(".//" + qn("w:t")))
            return bool(re.match(r"^\s*Таблица\s*-?\s*\d?", txt))
        if child.tag == qn("w:tbl"):
            return False
    return False


def trim_after_first_h1(doc):
    """Удалить из тела шаблона всё после титульного блока (до первого Heading 1
    включительно) — стили/нумерация/шапка сохраняются."""
    body = doc.element.body
    first_h1 = None
    for i, child in enumerate(list(body.iterchildren())):
        if child.tag == qn("w:p"):
            style = child.find(".//" + qn("w:pStyle"))
            if style is not None and style.get(qn("w:val")) in ("Heading1", "1", "Заголовок1"):
                first_h1 = i
                break
    if first_h1 is None:
        return
    children = list(body.iterchildren())[first_h1:]
    for child in children:
        # sectPr (свойства секции) обязателен — не удалять
        if child.tag == qn("w:sectPr"):
            continue
        body.remove(child)


def _resolve_out(out_arg, pattern, vals):
    """D4 (прогон -59): семантика -o однозначна — существующая папка →
    файл ВНУТРИ неё; путь к файлу → как есть; несуществующая папка →
    ошибка (раньше файл тихо писался в родителя)."""
    name = pattern.replace("{КОД}", vals["КОД"]).replace(
        "{ВЕРСИЯ}", vals.get("ВЕРСИЯ", "1")) + ".docx"
    if os.path.isdir(out_arg):
        return os.path.join(out_arg, name)
    d = os.path.dirname(out_arg)
    if not os.path.isdir(d):
        raise SystemExit(f"[render_md] -o: папка «{d}» не существует — "
                         f"создай её или укажи существующую папку/файл")
    return os.path.join(d, os.path.basename(out_arg)
                        if out_arg.lower().endswith(".docx")
                        else os.path.basename(out_arg))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("md", help="путь к Markdown-файлу ТЗ")
    ap.add_argument("--template", required=True, help="шаблон DOCX (стили/нумерация/шапка)")
    ap.add_argument("--spec", help="spec.json (ширины таблиц, ритм абзацев)")
    ap.add_argument("--figs", help="JSON {номер: описание} — замена [ОПИСАНИЕ ИЗОБРАЖЕНИЯ]")
    ap.add_argument("--set", dest="sets", action="append", default=[],
                    help="КЛЮЧ=ЗНАЧЕНИЕ — замена титульных плейсхолдеров (напр. КОД=ФР.X-62)")
    ap.add_argument("-o", "--out", default="ТЗ.docx", help="полный путь к выходному DOCX")
    args = ap.parse_args()

    font = None  # шрифт наследуется из стилей шаблона (docDefaults)
    spec = None
    if args.spec:
        with open(args.spec, encoding="utf-8") as fh:
            spec = json.load(fh)

    with open(args.md, encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    doc = Document(args.template)
    # защита от «сползающего» шрифта (Прогон #8): если docDefaults
    # шаблона без явного w:ascii (только theme) — шрифт уходит в Calibri
    from docx.oxml.ns import qn as _qn
    _rf = doc.styles.element.find(
        _qn("w:docDefaults") + "/" + _qn("w:rPrDefault") + "/"
        + _qn("w:rPr") + "/" + _qn("w:rFonts"))
    if _rf is None or _rf.get(_qn("w:ascii")) is None:
        from build_from_spec import setup_default_font
        setup_default_font(doc, (spec or {}).get("fonts", {}))
    trim_after_first_h1(doc)
    render(doc, parse_md(lines), font, spec)

    # --figs: описания рисунков → замена [ОПИСАНИЕ ИЗОБРАЖЕНИЯ]
    # (штатно, без самодельных DOCX-скриптов — E-46)
    if args.figs:
        with open(args.figs, encoding="utf-8") as fh:
            figs = json.load(fh)
        for par in doc.paragraphs:
            m = re.match(r"^\s*Рисунок\s*-\s*(\d+)\s+\[ОПИСАНИЕ ИЗОБРАЖЕНИЯ\]", par.text)
            if m and m.group(1) in figs:
                t = par.text
                t = re.sub(r"\[ОПИСАНИЕ ИЗОБРАЖЕНИЯ\]",
                           str(figs[m.group(1)]), t, count=1)
                for r in list(par.runs):
                    r._element.getparent().remove(r._element)
                r = par.add_run(t)
                r.italic = True

    # --set КЛЮЧ=ЗНАЧЕНИЕ: замена титульных плейсхолдеров (титул не
    # мапится из Markdown — заполняется штатной заменой, E-46).
    # Заполнено → пример-строка-спутник «[пример: …]» удаляется
    # (шаблон ставит её серой парой под токеном; в заполненном ТЗ ей
    # не место — E-50, тех-прогон, судья и гейт пример-строк не ловили).
    for kv in args.sets:
        key, _, val = kv.partition("=")
        key = key.strip()
        if not key:
            continue
        # E-59: титульные плейсхолдеры живут и в ТАБЛИЦАХ (лист
        # согласования «АО «[НАИМЕНОВАНИЕ ЗАКАЗЧИКА ]»») — обходим
        # абзацы таблиц вместе с абзацами тела; пример-строки-спутники
        # в ячейках тоже удаляются.
        _cell_pars = []
        for _tbl in doc.tables:
            for _row in _tbl.rows:
                for _cell in _row.cells:
                    _cell_pars.extend(_cell.paragraphs)
        # E-59: плейсхолдеры живут и в КОЛОНТИТУЛАХ (EMAIL/ТЕЛЕФОН,
        # НАИМЕНОВАНИЕ) — обходим их абзацы и таблицы всех секций
        for _sec in doc.sections:
            for _part in (_sec.header, _sec.footer,
                          _sec.first_page_header, _sec.first_page_footer):
                _cell_pars.extend(_part.paragraphs)
                for _tbl in _part.tables:
                    for _row in _tbl.rows:
                        for _cell in _row.cells:
                            _cell_pars.extend(_cell.paragraphs)
        for par in list(doc.paragraphs) + _cell_pars:
            if f"[{key}" in par.text:
                t = par.text
                t = re.sub(r"\[" + re.escape(key) + r"[^\]]*\]", val, t)
                for r in list(par.runs):
                    r._element.getparent().remove(r._element)
                r2 = par.add_run(t)
                r2.bold = par.runs[0].bold if par.runs else None
                nxt = par._p.getnext()
                from docx.text.paragraph import Paragraph as _P
                while nxt is not None and nxt.tag.endswith('}p'):
                    np = _P(nxt, par._parent)
                    if np.text.strip().startswith("[пример:"):
                        nxt.getparent().remove(nxt)
                        break
                    if np.text.strip():
                        break
                    nxt = nxt.getnext()

    out_path = os.path.abspath(args.out)
    # Имя файла — по шаблону из образцов (spec.meta.file_name_pattern),
    # если задан КОД: агент не придумывает имена (E-50, прогон тех-1).
    # «финал» в имя не включается — его ставит пользователь вручную.
    _pattern = ((spec or {}).get("meta") or {}).get("file_name_pattern")
    _vals = {}
    for kv in args.sets:
        k, _, v = kv.partition("=")
        if k.strip():
            _vals[k.strip()] = v.strip()
    if _pattern and "КОД" in _vals:
        out_path = _resolve_out(out_path, _pattern, _vals)
        print(f"[render_md] итог: {out_path}", file=sys.stderr)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    doc.save(out_path)
    # язык проверки правописания — как у текста ТЗ: правка итогового
    # документа в Word не должна превращаться в красный ковёр
    _lang = lang_tag(((spec or {}).get("meta") or {}).get("language"))
    _lrep = set_language_ru(out_path, _lang)
    if _lrep["foreign"] or _lrep["defaults"]:
        print(f"[render_md] ВНИМАНИЕ: язык документа не {_lang} "
              f"(чужеродных тегов {len(_lrep['foreign'])}, "
              f"дефектов по умолчанию {len(_lrep['defaults'])})",
              file=sys.stderr)
    print(f"[render_md] DOCX -> {out_path} (язык {_lang})", file=sys.stderr)


if __name__ == "__main__":
    main()
