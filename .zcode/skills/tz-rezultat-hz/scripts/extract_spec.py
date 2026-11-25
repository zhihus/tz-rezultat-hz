# -*- coding: utf-8 -*-
"""
extract_spec.py — шаг 1 конвейера.

Читает образец ТЗ (DOCX) и выводит spec.json — источник правды
для build_from_spec.py. Ничего не захардкожено под конкретный документ:
структура, плотность (число строк таблиц, число скриншотов, число
подфункций), нумерация и оформление измеряются из образца.

Использование:
    python extract_spec.py <образец.docx> [-o spec.json]
    python extract_spec.py --folder <папка_образцов> [-o spec.json]
        (--folder: шаблон = ПЕРЕСЕЧЕНИЕ всех образцов — только разделы,
        таблицы и плотность, присутствующие во ВСЕХ образцах; в spec.meta
        записывается папка образцов для сверки в verify_template.py)
"""
import argparse
import base64
import glob
import math
import io
import json
import os
import collections
from collections import Counter
import re
import sys
from datetime import datetime

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from lxml import etree as _lxml_etree

# маркер раздела алгоритмов (место сценариев в образце): «Описание
# работы алгоритмов АРМ…» и любая форма слова «алгоритм»
_ALGO_RX = re.compile(r"\bалгоритм", re.I)


def _split_marker_variations(excluded):
    """Разделить список исключений на маркерные (место алгоритмов) и
    рядовые. Урок V9 (2026-11-19): маркер не должен смешиваться с
    обычными вариациями — это структурный сигнал, а не шум."""
    markers = [s for s in excluded if _ALGO_RX.search(s)]
    rest = [s for s in excluded if not _ALGO_RX.search(s)]
    return markers, rest


def _el_xml(el):
    """XML-текст ЛЮБОГО элемента тела: у «голых» lxml-элементов
    (w:sectPr, w:bookmarkStart — тех-документы с разрывами секций, E-50)
    нет свойства .xml у BaseOxmlElement."""
    if el is None:
        return ""
    return _lxml_etree.tostring(el, encoding="unicode")

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))  # portable python: папка скрипта не в sys.path
from tz_common import setup_utf8_stdout

setup_utf8_stdout()

# --- Стили заголовков: fallback-набор (универсальный детект — по нумерации) ---
# Основной источник уровня — numPr в многоступенчатой decimal-схеме (ilvl),
# НЕ имя стиля. Имя стиля — запасной вариант для документов, где заголовки
# нумерацией не помечены. Набор расширяется автодетектом (см. main()).
HEADING_STYLES = {
    1: {"Heading 1", "Заголовок 1", "Заголовок: 1", "Heading1"},
    2: {"Heading 2", "Заголовок 2", "Заголовок: 2", "Heading2"},
    3: {"Heading 3", "Заголовок 3", "Заголовок: 3", "Heading 4", "Заголовок 4", "Heading4"},
}
CAPTION_STYLES = {"Caption", "Текст выноски", "Рисунок"}
LIST_STYLES = {"List Paragraph"}
# Имена стилей, которые никогда не являются заголовками/капшенами/списками
NON_CONTENT_STYLES = {"Normal", "Обычный", "Default Paragraph Font", "Normal (Web)",
                      "Body Text", "Текст документа", "Footer", "Header", "Footnote Text"}
# TOC-параметры по умолчанию (v6: оглавление в шаблоне всегда, даже если в
# конкретном образце его нет — факт наличия фиксируется в in_source)
TOC_DEFAULT_INSTR = 'TOC \\o "1-3" \\z \\u'


def is_heading_style(style_name, head_styles=None):
    hs = head_styles if head_styles is not None else HEADING_STYLES
    return any(style_name in names for names in hs.values())


def detect_level(style_name, ilvl, head_styles=None):
    """Уровень: в первую очередь из ilvl нумерации (0->1, 1->2, 2->3),
    иначе по имени стиля. head_styles — наборы стилей по уровням
    (fallback-набор + обнаруженные в ЭТОМ документе)."""
    if ilvl is not None:
        try:
            il = int(ilvl)
            if 0 <= il <= 8:
                return il + 1
        except (TypeError, ValueError):
            pass
    hs = head_styles if head_styles is not None else HEADING_STYLES
    for lvl, names in hs.items():
        if style_name in names:
            return lvl
    return None


def emu_to_pt(emu):
    return round(emu / 12700, 2)


def is_image(p_el):
    return len(p_el.findall(".//" + qn("a:blip"))) > 0


def is_image_any(p_el):
    """Картинка ЛЮБОГО формата: DrawingML (a:blip) или старый VML
    (w:pict/v:imagedata) — в тех-образцах терялись 4 из 6 картинок
    (E-50). Для детекта стиля подписей НЕ использовать (абзацы перед
    мелкими VML-вставками у «Протокола №…» ломали styles.caption)."""
    return (is_image(p_el)
            or len(p_el.findall(".//{urn:schemas-microsoft-com:vml}imagedata")) > 0)


def num_info(p_el):
    numpr = p_el.find(".//" + qn("w:numPr"))
    if numpr is None:
        return None, None
    n = numpr.find(qn("w:numId"))
    l = numpr.find(qn("w:ilvl"))
    numid = n.get(qn("w:val")) if n is not None else None
    ilvl = l.get(qn("w:val")) if l is not None else None
    return numid, ilvl


def style_font(doc, style_name):
    """Извлечь шрифт/размер/цвет из стиля (если он есть)."""
    try:
        st = doc.styles[style_name]
        f = st.font
        color = None
        try:
            if f.color and f.color.type is not None and f.color.rgb is not None:
                color = str(f.color.rgb)
        except Exception:
            color = None
        return {
            "font": f.name,
            "size_pt": emu_to_pt(f.size) if f.size else None,
            "bold": f.bold,
            "italic": f.italic,
            "color": color,
        }
    except Exception:
        return {"font": None, "size_pt": None, "bold": None, "italic": None, "color": None}


# --- Плейсхолдеры: замена конкретного содержания на [ИМЯ | пример: ...] ---
def to_placeholder(text):
    """Возвращает (текст_с_плейсхолдерами, список_плейсхолдеров).

    Каждый плейсхолдер несёт пример заполнения, взятый из самого образца:
    [ИМЯ | пример: ...]. Заполняющий агент замещает весь токен конечным
    текстом (пример удаляется вместе с токеном).
    """
    # keep: известные значения уже подставлены substitute_keep и должны
    # остаться literal'ами; повторная плейсхолдеризация возвращала бы
    # подставленное имя организации → обратно в плейсхолдер (дефект из Прогона #8).
    # Неизвестное в keep остаётся токеном в самом тексте образца.
    if _PII_MODE == "keep":
        return text.strip(), []

    t = text.strip()
    ph = []
    # персональные контакты (ПДн): телефон и email — до прочих паттернов
    t = _PHONE_RE.sub(lambda m: _ph(ph, "ТЕЛЕФОН", m.group(0)), t)
    t = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+",
               lambda m: _ph(ph, "EMAIL", m.group(0)), t)
    # даты
    t = re.sub(r"\b\d{2}\.\d{2}\.\d{4}\b",
               lambda m: _ph(ph, "ДД.ММ.ГГГГ", m.group(0)), t)
    # номер договора
    t = re.sub(r"(договора\s*№\s*)(\d+)",
               lambda m: m.group(1) + _ph(ph, "НОМЕР", m.group(2)), t, flags=re.I)
    # организация — универсальный паттерн, имя не захардкожено. Два случая:
    #   (1) тип внутри кавычек:  «ООО ПримерОрг»  → «[НАИМЕНОВАНИЕ | пример: …]»
    #   (2) тип вне кавычек:     ООО «ПримерОрг»  → ООО «[НАИМЕНОВАНИЕ | пример: …]»
    t = re.sub(r"«((?:ООО|АО|ПАО|ЗАО|ОАО|ИП)\b[^\»]*)»",
               lambda m: "«" + _ph(ph, "НАИМЕНОВАНИЕ", m.group(1)) + "»", t, flags=re.I)
    t = re.sub(r"((?:ООО|АО|ПАО|ЗАО|ОАО|ИП)\s*)«([^\»]*)»",
               lambda m: m.group(1) + "«" + _ph(ph, "НАИМЕНОВАНИЕ", m.group(2)) + "»",
               t, flags=re.I)
    # код ТЗ (универсально: буквенный префикс + цифры, вида «ПР.01.04.1-10» —
    # частный случай)
    t = re.sub(r"\b([А-ЯЁA-Z]{1,8}(?:\.[А-ЯЁA-Z]{1,8})*\.\d{2}(?:\.\d+)*-\d+)\b",
               lambda m: _ph(ph, "КОД", m.group(1)), t)
    # функциональный блок: «NN.NN_текст» или «NN_текст» в кавычках
    t = re.sub(r"«(\d{2}(?:\.\d{2})?_[^»]+)»",
               lambda m: "«" + _ph(ph, "ФУНКЦИОНАЛЬНЫЙ БЛОК", m.group(1)) + "»", t)
    # версия
    t = re.sub(r"(Версия\s*:\s*)(\d+)",
               lambda m: m.group(1) + _ph(ph, "N", m.group(2)), t, flags=re.I)
    return t, ph


def _ph(lst, name, example=None):
    """Плейсхолдер с примером заполнения: [ИМЯ | пример: ...].
    Пример — ТОЛЬКО вымышленные данные (правило протокола п. 16)."""
    if name not in lst:
        lst.append(name)
    if example is None:
        return "[" + name + "]"
    return f"[{name} | пример: {_sanitize_example(example)}]"


# Реальные данные образцов в примерах запрещены: заменяются на вымышленные.
# Реестр замен заполняется ДИНАМИЧЕСКИ при extract (организации и ФИО
# детектятся паттернами из документа) — никаких списков конкретных образцов.
_GENERIC_ORGS = ["Ромашка", "ПримерТекс", "ПримерОрг"]
_generic_org_i = [0]
_DYNAMIC_SUBS = {}  # lower(real) -> generic
# код ФР в примере → вымышленный шаблон
# код ТЗ: буквенный префикс (1-3 группы) + цифры с точками и хвостовым дефисом;
# пример — частный случай, универсально для нумераций заказчика
_CODE_RE = re.compile(r"\b[А-ЯЁA-Z]{1,8}(?:\.[А-ЯЁA-Z]{1,8})*\.\d{2}(?:\.\d+)*-\d+\b", re.I)
# телефоны и email — ПДн, примеры всегда вымышленные (санитизация);
# разделители (пробел/дефис/скобки) — в любом сочетании
_PHONE_RE = re.compile(r"(?:\+7|8)[\s\-(]*\d{3}[\s\)-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}\b")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_GENERIC_PHONE = "+7 (999) 123-45-67"
_GENERIC_EMAIL = "info@example.com"
# режим персональных данных: sanitize (по умолчанию) — примеры вымышленные,
# логотипы-заглушки; keep — реальные значения и логотипы копируются как есть
def _config_arg_paths(config_args):
    """«метка=путь» → [(метка, путь)]; расширение (ext) первым."""
    paths = []
    for c in config_args or []:
        label, _, path = c.partition("=")
        paths.append((label or "main", path))
    return sorted(paths, key=lambda kv: 0 if kv[0] == "ext" else 1)


def _derive_naming(config_paths):
    """Конвенция имён из выгрузки (naming-and-emphasis-universal):
    мажоритарный строчный префикс OWNED-объектов расширения (cfe).
    Нет cfe/объектов/мажориты → None (имена новых объектов — USER-ONLY
    вопрос; вопрос пользователю не подавляется). config_paths:
    [(label, base)] — расширение ПЕРВЫМ, как в lint/check_map."""
    import glob
    from lxml import etree
    names = []
    for label, base in (config_paths or []):
        d = os.path.join(base, "Documents")
        if not os.path.isdir(d):
            continue
        for f in glob.glob(os.path.join(d, "*.xml")):
            try:
                tree = etree.parse(f)
            except etree.XMLSyntaxError:
                continue
            obj = next((c for c in tree.getroot()
                        if etree.QName(c).localname == "Document"), None)
            if obj is None:
                continue
            belonging = ""
            name = ""
            for el in obj.iter():
                ln = etree.QName(el).localname
                if ln == "ObjectBelonging" and el.text:
                    belonging = el.text.strip()
                if ln == "Name" and el.text and not name:
                    name = el.text.strip()
            if belonging == "Owned" and name:
                names.append(name)
        if names:
            break  # cfe первым: основная конфигурация не задаёт префикс расширения
    counts = {}
    for n in names:
        m = re.match(r"^([а-яёa-z0-9_]+)", n)
        if m and m.group(1) and len(m.group(1)) < len(n):
            counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    if not counts:
        return None
    best, cnt = max(counts.items(), key=lambda kv: (kv[1], len(kv[0])))
    if cnt * 2 < len(names):  # мажорита ≥50%
        return None
    return {"prefix": best, "role_pattern": best}


_CONFIG_PATHS: list = []  # выгрузки: [(label, base)], расширение первым
_PII_MODE = "sanitize"


def _derive_message_emphasis(doc):
    """Конвенция выделения сообщений пользователю из образцов
    (naming-and-emphasis-universal): candidate — run с курсивом и/или
    цветом ≠ auto/чёрный в абзацах ТЕЛА (не заголовки, не подписи
    «Рисунок - N»/«Таблица - N»). Мажоритарный курсив/цвет кандидатов →
    spec.meta.message_emphasis; кандидатов нет → None (маркер
    [СООБЩЕНИЕ: …] запрещён — G18 линта)."""
    from collections import Counter as _C
    cand_i, cand_c = [], []
    for p in doc.paragraphs:
        st = (p.style.name if p.style else "")
        if st.startswith("Heading") or st in ("Title", "Caption"):
            continue
        t = p.text.strip()
        if re.match(r"^(Рисунок|Таблица)\s*-?\s*\d", t):
            continue  # подписи иллюстраций — другой элемент каталога
        for r in p.runs:
            if not (r.text or "").strip():
                continue
            ital = bool(r.italic)
            color = None
            try:
                if r.font.color and r.font.color.type is not None \
                        and r.font.color.rgb is not None:
                    color = str(r.font.color.rgb)
            except Exception:
                color = None
            black = color is None or color.upper() in ("000000", "AUTO")
            if ital or not black:
                cand_i.append(ital)
                cand_c.append(None if black else color)
    if not cand_i:
        return None
    conv = {"italic": sum(cand_i) * 2 >= len(cand_i)}
    colors = [c for c in cand_c if c]
    if colors and len(colors) * 2 >= len(cand_i):
        conv["color"] = _C(colors).most_common(1)[0][0]
    else:
        conv["color"] = None
    return conv


def _register_sub(real, generic):
    if real and real.strip():
        _DYNAMIC_SUBS.setdefault(real.strip().lower(), generic)


def _scan_sensitive(doc):
    """Зарегистрировать реальные данные документа (организации, ФИО)
    для последующей санитизации примеров. Сканирует ВЕСЬ XML документа,
    включая вложенные таблицы и колонтитулы."""
    texts = [t.text or "" for t in
             doc.element.body.iter(qn("w:t"))]
    for sec in doc.sections:
        for part in (sec.header, sec.footer, sec.first_page_header,
                     sec.first_page_footer):
            try:
                texts += [t.text or "" for t in part._element.iter(qn("w:t"))]
            except Exception:
                pass
    for t in texts:
        for m in re.finditer(r"(?:ООО|АО|ПАО|ЗАО|ОАО|ИП)\s*«([^»]+)»|«((?:ООО|АО|ПАО|ЗАО|ОАО|ИП)\b[^»]*)»",
                             t, re.I):
            real = m.group(1) or m.group(2)
            org = _GENERIC_ORGS[_generic_org_i[0] % len(_GENERIC_ORGS)]
            _generic_org_i[0] += 1
            _register_sub(real, org)
            _register_sub("ООО " + real, "ООО «" + org + "»")
            _register_sub("ООО «" + real + "»", "ООО «" + org + "»")
        for m in re.finditer(r"\b([А-Я]\.\s?[А-Я]\.\s?[А-Я][а-я]+)\b", t):
            _register_sub(m.group(1), "И.И. Иванов")
        # телефоны и email — ПДн (регистрируются для санитизации примеров)
        for m in _PHONE_RE.finditer(t):
            _register_sub(m.group(0), _GENERIC_PHONE)
        for m in _EMAIL_RE.finditer(t):
            _register_sub(m.group(0), _GENERIC_EMAIL)
    # функциональный блок: «NN.NN_…» → вымышленный пример
    for t in texts:
        for m in re.finditer(r"«(\d{2}(?:\.\d{2})?_[^»]+)»", t):
            _register_sub(m.group(1), "01.00_ПРИМЕР. ПРОИЗВОДСТВО")


def _sanitize_example(text):
    if _PII_MODE == "keep":
        return text
    t = text
    for real, generic in _DYNAMIC_SUBS.items():
        t = re.sub(re.escape(real), generic, t, flags=re.I)
    t = _PHONE_RE.sub(_GENERIC_PHONE, t)
    t = _EMAIL_RE.sub(_GENERIC_EMAIL, t)
    t = re.sub(r"\b\d{8}\b", "123456", t)  # слитные даты в номерах договоров
    t = _CODE_RE.sub("ФР.000.00.00.0-00", t)
    return t



def used_numids(doc):
    """Множество numId, реально ссылаемых абзацами тела (любыми)."""
    body = doc.element.body
    ids = set()
    for numpr in body.findall(".//" + qn("w:numPr")):
        n = numpr.find(qn("w:numId"))
        if n is not None:
            ids.add(n.get(qn("w:val")))
    return ids


def numfmt_map(doc):
    """numId -> {ilvl: numFmt} по всем abstractNum (универсальный детект уровней)."""
    numbering = doc.part.numbering_part.element
    V = qn("w:val")
    num_to_abs = {}
    for num in numbering.findall(qn("w:num")):
        nid = num.get(qn("w:numId"))
        aref = num.find(qn("w:abstractNumId"))
        num_to_abs[nid] = aref.get(V) if aref is not None else None
    abs_fmts = {}
    for an in numbering.findall(qn("w:abstractNum")):
        anid = an.get(qn("w:abstractNumId"))
        fmts = {}
        for i, lvl in enumerate(an.findall(qn("w:lvl"))):
            fmt = lvl.find(qn("w:numFmt"))
            fmts[i] = fmt.get(V) if fmt is not None else None
        abs_fmts[anid] = fmts
    return {nid: abs_fmts[aid] for nid, aid in num_to_abs.items() if aid in abs_fmts}


def is_heading_para(style, numid, ilvl, numfmts, head_styles=None):
    """Универсальный детект заголовка:
      (a) имя стиля из набора заголовочных стилей, ИЛИ
      (b) numPr с decimal-форматом на уровне ilvl (0–2), при этом стиль
          не служебный и не список.
    Уровень берётся из ilvl (первичен), имя стиля — fallback."""
    if is_heading_style(style, head_styles):
        return True
    if numid is None or ilvl is None:
        return False
    try:
        il = int(ilvl)
    except (TypeError, ValueError):
        return False
    if not (0 <= il <= 2):
        return False
    if style in LIST_STYLES or style in NON_CONTENT_STYLES:
        return False
    return numfmts.get(numid, {}).get(il) == "decimal"


def autodetect_styles(doc, numfmts):
    """Возвращает (det_head, det_cap) по реальному использованию в документе.

    det_head: {level: style_name} — первый найденный стиль на каждом уровне
      (заголовки = абзацы, классифицированные is_heading_para; универсально,
      не зависит от имён стилей).
    det_cap:  список стилей абзацев, идущих сразу после изображения,
      отсортированный по частоте (set → next(iter()) выбирал СЛУЧАЙНЫЙ
      стиль при каждом запуске — spec «плавал» между прогонами; E-50).
    """
    body = doc.element.body
    children = list(body.iterchildren())
    det_head = {}
    cap_votes = collections.Counter()
    for i, child in enumerate(children):
        if child.tag != qn("w:p"):
            continue
        p = Paragraph(child, doc)
        style = p.style.name
        if style in NON_CONTENT_STYLES:
            continue
        numid, ilvl = num_info(child)
        if is_heading_para(style, numid, ilvl, numfmts):
            try:
                il = int(ilvl) if ilvl is not None else None
            except (TypeError, ValueError):
                il = None
            if il is None and is_heading_style(style):
                # заголовок по имени стиля без numPr — уровень из detect_level
                lvl = detect_level(style, None)
                il = lvl - 1 if lvl else None
            if il is not None and 0 <= il <= 2 and (il + 1) not in det_head:
                det_head[il + 1] = style
        if (i + 1 < len(children) and children[i + 1].tag == qn("w:p")
                and is_image(children[i + 1]) and p.text.strip()):
            # стиль абзаца перед картинкой — кандидат в подписи; заголовки,
            # списки и служебные стили подписями не являются (иначе заголовок
            # подфункции, стоящий прямо перед скриншотом, «съедается» как
            # подпись и подфункция исчезает из дерева)
            if not (is_heading_style(style) or style in det_head.values()
                    or style in LIST_STYLES or style in NON_CONTENT_STYLES):
                cap_votes[style] += 1
    det_cap = [s for s, _ in cap_votes.most_common()]
    return det_head, det_cap


def extract_numbering(doc):
    """Извлечь многоступенчатую нумерацию заголовков и нормализовать start→1.

    Универсально: не зависит от точного формата lvlText. Выбирает
    «самую иерархическую» decimal-схему (предпочитает %1.%2.%3, но принимает
    и %1, «1 %2», «1.%2» и т.п.). Тир-брейкер — реально ли abstractNum
    ссылается на numId, использованный в теле документа."""
    numbering = doc.part.numbering_part.element
    V = qn("w:val")
    # numId -> abstractNumId
    mapping = {}
    for num in numbering.findall(qn("w:num")):
        nid = num.get(qn("w:numId"))
        aref = num.find(qn("w:abstractNumId"))
        mapping[nid] = aref.get(V) if aref is not None else None

    used = used_numids(doc)

    candidates = []
    for an in numbering.findall(qn("w:abstractNum")):
        anid = an.get(qn("w:abstractNumId"))
        lvls = an.findall(qn("w:lvl"))
        if len(lvls) < 3:
            continue
        texts, fmts, starts = [], [], []
        for lvl in lvls[:3]:
            txt = lvl.find(qn("w:lvlText"))
            fmt = lvl.find(qn("w:numFmt"))
            start = lvl.find(qn("w:start"))
            texts.append(txt.get(V) if txt is not None else "")
            fmts.append(fmt.get(V) if fmt is not None else "")
            starts.append(int(start.get(V)) if start is not None else 1)
        if fmts[0] != "decimal":
            continue
        # скоринг иерархичности
        score = 0
        if "%1" in texts[0]:
            score += 2
        if "%1" in texts[1] and "%2" in texts[1]:
            score += 3
        if "%1" in texts[2] and "%2" in texts[2] and "%3" in texts[2]:
            score += 4
        if all(f == "decimal" for f in fmts):
            score += 1
        # реально ли схема используется в теле
        if any(mapping.get(nid) == anid for nid in used):
            score += 5
        candidates.append({
            "abstract_id": anid,
            "formats": texts,
            "detected_start": starts,
            "score": score,
        })

    if not candidates:
        return None
    candidates.sort(key=lambda c: c["score"], reverse=True)
    cand = candidates[0]
    normalized = [1, 1, 1]
    note = "start нормализован к 1: detected_start={} → normalized_start={}".format(
        cand["detected_start"], normalized)
    return {
        "levels": 3,
        "formats": cand["formats"],
        "detected_start": cand["detected_start"],
        "normalized_start": normalized,
        "abstract_id": cand["abstract_id"],
        "note": note,
    }


# --- Нормализация и пересечение образцов (шаблон = только общее для ВСЕХ) ---
_FILE_CODE_RE = re.compile(r"[А-ЯЁ]{2,4}(?:\.[А-ЯЁ0-9]+)+-\d+")


def _naming_pattern(names, majority_ratio=0.75):
    """Шаблон имени файла ТЗ из имён ОБРАЗЦОВ (факты, не выдумка):
    код(ы) ТЗ → {КОД} (несколько через запятую сворачиваются в один
    слот), версия V<цифры> → V{ВЕРСИЯ}; слово «финал» ИЗСЕКАЕТСЯ —
    его ставит только пользователь вручную после нескольких версий.
    Остальные части — литералы (заказчик, «ТЗ», «Приложение к ТЗ»).
    Шаблон берётся большинством; нет большинства → None (не выдумывать)."""
    pats = Counter()
    for name in names:
        s = _FILE_CODE_RE.sub("{КОД}", name)
        s = re.sub(r"(?<![0-9A-Za-z])V\d+", "V{ВЕРСИЯ}", s)
        s = re.sub(r"\s*финал\s*$", "", s, flags=re.I)
        s = re.sub(r"\{КОД\}(?:\s*,\s*\{КОД\})+", "{КОД}", s)
        s = s.rstrip("_ .")
        pats[s] += 1
    if not pats:
        return None
    pat, n = pats.most_common(1)[0]
    return pat if n >= max(2, math.ceil(majority_ratio * len(names))) else None


def norm_title(title):
    """Сигнатура заголовка для сопоставления между образцами:
    убирает конкретные коды (ФР.000.00.00.0-00), плейсхолдерные токены
    ([КОД | пример: ...]) вместе с примерами, «ТЗ», номера; lower+collapse."""
    t = title.strip()
    # ведущая нумерация («1.», «4.3.1.») — не часть сигнатуры: часть
    # тех-образцов нумерует разделы, часть нет (E-50, ложный fallback)
    t = re.sub(r"^\s*\d+(\.\d+)*[.)]?\s+", "", t)
    t = re.sub(r"\[[^\]]*\]", "", t)  # плейсхолдеры с примерами — целиком
    t = _CODE_RE.sub("", t)  # коды ТЗ любого формата заказчика
    t = re.sub(r"\bТЗ\b", "", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip()
    t = t.rstrip(".").strip()  # убрать хвостовые точки И пробел, который они оставляют
    return t.lower()


def _has_page_break(p_el):
    """Разрыв страницы перед абзацем: pageBreakBefore или явный
    w:br type=page перед ним (два источника — один ответ)."""
    if p_el is None:
        return False
    pPr = p_el.find(qn("w:pPr"))
    if pPr is not None and pPr.find(qn("w:pageBreakBefore")) is not None:
        return True
    prev = p_el.getprevious()
    return prev is not None and 'w:type="page"' in _el_xml(prev)


def _count_shots_subtree(node):
    """Число скриншотов в поддереве раздела (body + дети)."""
    n = sum(1 for b in node["body"] if b["type"] == "screenshot")
    for c in node["children"]:
        n += _count_shots_subtree(c)
    return n


def _count_h3_subtree(node):
    """Число подфункций (H3) в поддереве раздела."""
    n = sum(1 for c in node["children"] if c["level"] == 3)
    for c in node["children"]:
        n += _count_h3_subtree(c)
    return n


# --- Детект «action»-абзацев (п.5): текст описывает действие на форме —
# туда в шаблоне ставится место скриншота (графическое пояснение). ---
ACTION_KEYWORDS = (
    "кнопк", "открыт", "окон", "вкладк", "отбор", "заполнит", "нажат",
    "выбер", "режим", "отчет", "арм", "реквизит", "создан", "выполнит",
    "установит", "вставит", "запуст", "перейт", "вызват",
)


def is_action_text(text):
    """Абзац описывает действие на форме (кнопка/окно/вкладка/отбор/…)?"""
    t = text.lower()
    return any(k in t for k in ACTION_KEYWORDS)


HINTS = None  # [(ключ, текст)] из каталога hints — данные, не код


def _load_hints(catalog_path=None):
    """Загрузить подсказки разделов из каталога (блок hints)."""
    global HINTS
    if HINTS is not None:
        return HINTS
    import yaml as _yaml
    HINTS = []
    cp = catalog_path or _find_catalog()
    try:
        with open(cp, encoding="utf-8") as fh:
            cat = _yaml.safe_load(fh) or {}
        for k, v in (cat.get("hints") or {}).items():
            HINTS.append((str(k).lower(), str(v)))
    except Exception:
        pass
    return HINTS


def _hint_for(node):
    """Серая подсказка для раздела: ключи — из каталога (hints),
    не из кода. Fallback — общий текст."""
    t = node["title"].lower()
    if node["level"] == 3:
        return ("ПОДСКАЗКА: опишите подфункцию — кто и что делает, "
                "какие документы/регистры задействованы; вставьте скриншот.")
    for key, text in _load_hints():
        if key in t:
            return text
    return "ПОДСКАЗКА: заполните раздел."


def _hint_from_src(src, node):
    """Подсказка раздела: первый абзац из образца (до 200 симв.),
    иначе — текст по каталогу (_hint_for)."""
    if src:
        return "ПОДСКАЗКА: " + (src if len(src) <= 200 else src[:200] + "…")
    return _hint_for(node)


def _tbl_match(nc, hdrs, ncols, tokens):
    """Таблица совпала: та же ширина и перекрытие заголовков ≥ 50%."""
    return (nc == ncols
            and len(tokens & set(hdrs)) >= 0.5 * min(len(tokens), len(set(hdrs))))


def _norm_header_tokens(headers):
    """Множество слов нормализованных заголовков (перекрытие считаем по
    словам: «Термин/сокращение» и «Термин» дают общий токен «термин»)."""
    words = set()
    for h in headers:
        for w in norm_title(h).replace("/", " ").split():
            words.add(w)
    return words


def _section_sigs(node, acc):
    """Собрать {сигнатура: {level, title, tables, shots, h3}} по поддереву.

    tables — таблицы body раздела: (число колонок, кортеж нормализованных
    заголовков, columns, rows) — матчинг таблиц по содержимому заголовков,
    не только по ширине (таблица одного ТЗ не должна протекать в шаблон).
    shots/h3 — рекурсивно по поддереву.
    При дубликате сигнатуры (редко) — объединение списков, max shots/h3.
    """
    sig = norm_title(node["title"])
    tables = [(len(b["columns"]), _norm_header_tokens(b["columns"]),
               b["columns"], b["rows"], b.get("example_row"),
               b.get("col_bold"), b.get("col_lead"),
               b.get("has_caption"))
              for b in node["body"] if b["type"] == "table"]
    shots = _count_shots_subtree(node)
    h3 = _count_h3_subtree(node)
    if sig in acc:
        acc[sig]["tables"].extend(tables)
        acc[sig]["shots"] = max(acc[sig]["shots"], shots)
        acc[sig]["h3"] = max(acc[sig]["h3"], h3)
    else:
        acc[sig] = {"level": node["level"], "title": node["title"],
                    "tables": tables, "shots": shots, "h3": h3,
                    "page_break": bool(node.get("page_break"))}
    for c in node["children"]:
        _section_sigs(c, acc)


def _stem5(tok):
    """Дешёвое отсечение окончаний: первые 5 букв (без новых зависимостей;
    T3a — план доработки v2)."""
    tok = tok.lower().replace("ё", "е")
    return tok[:5] if len(tok) >= 4 else tok


def _sig_stems(sig):
    return {t for t in (_stem5(w) for w in re.split(r"[^\w]+", sig))
            if len(t) >= 4}


def _walk_titles(node):
    """Плоский обход дерева секций: (узел, родительская цепочка)."""
    stack = [(node, [])]
    while stack:
        n, ch = stack.pop()
        yield n, ch
        for c in n.get("children", []):
            stack.append((c, ch + [n.get("title", "")]))


def _sig_context(specs, sig):
    """T3b-контекст сигнатуры: родительский раздел + короткий пример
    содержания (первый непустой абзац тела)."""
    def walk(node, chain):
        s = norm_title(node.get("title", ""))
        if s == sig:
            first = next((b.get("text", "") for b in node.get("body", [])
                          if b.get("type") == "paragraph" and b.get("text")),
                         "")
            return chain[-1] if chain else "(корень)", first[:120]
        for c in node.get("children", []):
            r = walk(c, chain + [node.get("title", "")])
            if r:
                return r
        return None

    for sp in specs:
        for s in sp.get("sections", []):
            r = walk(s, [])
            if r:
                return r
    return "(не найден)", ""


def _sig_parent(sig):
    """Родительский раздел по номеру заголовка: «4.3.1 X» → «4.3».
    Без номера — None."""
    m = re.match(r"^(\d+(?:\.\d+)*)\s", sig)
    if not m:
        return None
    num = m.group(1)
    return num.rsplit(".", 1)[0] if "." in num else None


def _svarka_candidates(variations):
    """T3a: пары необщих сигнатур с высокой лексической близостью
    (жаккар по стемам ≥ 0.6) — ТОЛЬКО список кандидатов, слияния нет.
    D7 (прогон -59): пары из РАЗНЫХ родительских разделов отсеиваются —
    близость на общих словах («Описание изменения…») давала 22 пары
    шума."""
    cands = []
    vlist = sorted(variations)
    for i in range(len(vlist)):
        for j in range(i + 1, len(vlist)):
            pa, pb = _sig_parent(vlist[i]), _sig_parent(vlist[j])
            if pa is not None and pb is not None and pa != pb:
                continue
            si, sj = _sig_stems(vlist[i]), _sig_stems(vlist[j])
            if not si or not sj:
                continue
            # близость = покрытие меньшего набора стемов пересечением
            # (одна сигнатура — подмножество слов другой — тоже кандидат)
            jac = len(si & sj) / max(len(si), len(sj))
            if jac >= 0.6:
                cands.append((vlist[i], vlist[j], round(jac, 2)))
    return cands


def _razvodka_split(pairs):
    """D8 (прогон -59): разводка на (вопросы, информация). Вариативность
    ПЛОТНОСТИ («скриншоты …») — норма (Пятое правило) → [РАЗВОДКА-OK]
    информация; контентное расхождение (таблицы: разные заголовки) —
    вопрос пользователю."""
    questions, infos = [], []
    for sig, why in pairs:
        if why.startswith("скриншоты"):
            infos.append((sig, why))
        else:
            questions.append((sig, why))
    return questions, infos


def _razvodka_pairs(per_sample, common):
    """T3c: общий раздел с сильным расхождением профиля между образцами
    (заголовки таблиц: жаккар < 0.4 при 2+ образцах с таблицами;
    скриншоты: расхождение > 2 И ratio > 2). Возвращает список
    (сигнатура, причина)."""
    out = []
    for sig in sorted(common):
        tbl_hdrs, shots = [], []
        for acc in per_sample:
            if sig not in acc:
                continue
            hdrs = set()
            for _nc, h, *_rest in acc[sig]["tables"]:
                hdrs |= _norm_header_tokens(h)
            tbl_hdrs.append(hdrs)
            shots.append(acc[sig]["shots"])
        with_tbl = [h for h in tbl_hdrs if h]
        if len(with_tbl) >= 2:
            worst = 1.0
            for i in range(len(with_tbl)):
                for j in range(i + 1, len(with_tbl)):
                    u = with_tbl[i] | with_tbl[j]
                    if u:
                        worst = min(worst,
                                    len(with_tbl[i] & with_tbl[j]) / len(u))
            if worst < 0.4:
                out.append((sig, "таблицы (жаккар %.2f)" % worst))
                continue
        if len(shots) >= 2 and max(shots) - min(shots) > 2 \
                and (min(shots) == 0 or max(shots) / min(shots) > 2):
            out.append((sig, "скриншоты %s" % shots))
    return out


def _hf_majority(specs):
    """Колонтитулы по БОЛЬШИНСТВУ образцов (Б2, дефект 2026-11-21):
    если у большинства есть header_footer — берётся самый содержательный
    не-None (больше ячеек/абзацев/сеток), а не только источник титула
    (у тех-ТЗ титульный образец нередко без колонтитулов → spec None,
    гейт «Колонтитулы воспроизведены» проходил впустую). Меньшинство →
    None (старое поведение)."""
    def _present(h):
        return bool(h and (h.get("header") or h.get("footer")))

    non_none = [sp.get("header_footer") for sp in specs if _present(sp.get("header_footer"))]
    if len(non_none) * 2 <= len(specs):
        return None

    def _score(h):
        # cells/paras/grids живут внутри header/footer (верхний уровень
        # — {'header': …, 'footer': …})
        return sum(len(part.get(k, []))
                   for part in (h.get("header") or {}, h.get("footer") or {})
                   for k in ("cells", "paras", "grids"))

    return max(non_none, key=_score)


def _tokenize_code_title(tb):
    """Титульный блок (Б5, дефект 2026-11-21): литеральный код
    референса («Приложение к ТЗ ФР.000.00.00.0-10») → токен [КОД];
    иначе шаблон наследует чужой код, а render_md --set подставляет
    только токены. Копия: вход не мутируется. Код в подписях/именах
    (не matching _CODE_RE) не трогается."""
    def _tok(s):
        return _CODE_RE.sub("[КОД]", s)

    out = []
    for item in tb:
        if "sig_rows" in item:
            it = dict(item)
            it["sig_rows"] = [[_tok(c) for c in row]
                              for row in item["sig_rows"]]
            out.append(it)
        elif "text" in item:
            it = dict(item)
            it["text"] = _tok(item["text"])
            if item.get("example_line"):
                it["example_line"] = _tok(item["example_line"])
            out.append(it)
        else:
            out.append(item)
    return out


def intersect_specs(specs, majority_ratio=0.75, synonyms=None):
    """Присутствие элемента — по правилу большинства (методика 7.1.3).

    - раздел: сигнатура (нормализованный заголовок) есть в >= majority_ratio
      образцов; образцы-исключения фиксируются как вариация (variations);
    - таблица: достаточно совпадения в том же большинстве образцов,
      содержащих раздел;
    - скриншоты/подфункции: общий «пол» среди образцов с разделом.
    Оформление (стили, нумерация, страница) наследуется от референс-образца —
    референс выбирается по максимуму «большинственных» разделов.

    T3 (аудит Г2): synonyms — {'merge': {B: A}, 'insufficient': [[A, B]]}
    из spec_synonyms.json (подтверждение LLM/пользователя). merge
    переименовывает сигнатуры ДО пересечения (детерминированный повтор);
    insufficient уводит обе сигнатуры в variations + вопрос пользователю.
    Похожие необщие сигнатуры печатаются блоком [СВЕРКА] (только
    кандидаты, слияния нет), одноимённые с расхождением профиля —
    блоком [РАЗВОДКА].
    """
    synonyms = synonyms or {}

    def _apply_merge(sig):
        seen = set()
        while sig in synonyms.get("merge", {}) and sig not in seen:
            seen.add(sig)
            sig = synonyms["merge"][sig]
        return sig

    per_sample = []
    for sp in specs:
        acc = {}
        for s in sp["sections"]:
            _section_sigs(s, acc)
        if synonyms.get("merge"):
            acc = {_apply_merge(k): v for k, v in acc.items()}
        per_sample.append(acc)
    if not per_sample:
        return specs[0] if specs else {}

    # порог большинства: сигнатура шаблонная, если в >= ratio образцов
    def _need(n):
        # большинство: минимум 2 голоса (защита от пары почти-одинаковых)
        return max(2, math.ceil(majority_ratio * n))

    need = _need(len(specs))
    counts = Counter()
    for acc in per_sample:
        counts.update(acc.keys())
    common = {sig for sig, n in counts.items() if n >= need}

    # ДОКУМЕНТ-МЕТОДИКА §7.1.3a: уровень 1 — жёсткое большинство по ВСЕМ
    # образцам, всегда первым. Если консенсуса нет (методика 7.1.3a:
    # совпавших сигнатур мало) — уровень 2: база = наиболее полный
    # образец, остальные сверяются с базой тем же жёстким большинством.
    # Порог детерминирован и считается по разделам ВЕРХНЕГО уровня (H1):
    # подразделы/подфункции всегда уникальны для конкретной доработки —
    # по ним консенсуса не бывает и в здоровом пересечении (иначе
    # уровень 2 ложно срабатывал на бизнес-ветке). Мера — МЕДИАНА числа
    # H1 по образцам (не максимум: один образец с шумовыми H1 —
    # misdetect нумерованных абзацев — ломал порог). Уровень 1 «не
    # определим», если common покрывает меньше половины типичного H1-набора.
    _h1_sorted = sorted(sum(1 for v in acc.values() if v["level"] == 1)
                        for acc in per_sample)
    _n = len(_h1_sorted)
    median_h1 = (_h1_sorted[_n // 2] if _n % 2
                 else (_h1_sorted[_n // 2 - 1] + _h1_sorted[_n // 2]) / 2)
    h1_common = sum(1 for sig in common
                    if any(sig in acc and acc[sig]["level"] == 1
                           for acc in per_sample))
    level2 = h1_common < max(1, math.ceil(0.5 * median_h1))
    presence_meta = {"presence_level": 1, "base_sample": None}
    if level2:
        def base_score(i_acc):
            # T6 (аудит Г3): «больше таблиц = лучше» УДАЛЕНО — длина и
            # количество таблиц не критерии качества; база — структурный
            # размер (число разделов)
            acc = i_acc[1]
            return (len(acc),)
        bi, base_acc = max(enumerate(per_sample), key=base_score)
        others = [acc for j, acc in enumerate(per_sample) if j != bi]
        if others:
            need_others = max(1, math.ceil(majority_ratio * len(others)))
            confirmed = {sig for sig in base_acc
                         if sum(1 for acc in others if sig in acc) >= need_others}
        else:
            # единственный образец: подтверждать нечем, база и есть
            # структура (иначе «сумма по пустому списку» обнуляла скелет)
            confirmed = set(base_acc)
        presence_meta = {
            "presence_level": 2,
            "base_sample": os.path.basename(specs[bi].get("meta", {}).get("source_file", "")),
            "level1_reason": (f"уровень 1: H1 в common {h1_common} < половины "
                              f"медианы H1 ({median_h1}) — методика 7.1.3a, уровень 2"),
        }
        common = confirmed

    # вариации: разделы-исключения (в части образцов, но не в большинстве)
    variations = sorted(
        sig for sig, n in counts.items() if 0 < n < need
    )
    if level2:
        # неподтверждённые базой разделы — НЕ выбрасывать молчаливо (7.1.3a)
        variations = sorted(set(variations)
                            | {sig for sig in counts if sig not in common})
    # маркерные разделы (место алгоритмов) не тонут в рядовых исключениях
    # (урок V9, 2026-11-19): «Описание работы алгоритмов АРМ…» из -10 —
    # сигнал «сценарии идут после объектов»; выносятся в marker_sections
    marker_secs, ordinary_secs = _split_marker_variations(variations)
    variations = ordinary_secs

    # T3 (аудит Г2): сверка похожих сигнатур и разводка одноимённых.
    # Поиск — алгоритм, подтверждение — LLM/пользователь; автоматическое
    # слияние по проценту сходства ЗАПРЕЩЕНО (план доработки v2).
    _insufficient = [tuple(p) for p in (synonyms.get("insufficient") or [])]
    if _insufficient:
        _ins_set = {s for p in _insufficient for s in p}
        common -= _ins_set
        variations = sorted(set(variations) | _ins_set)
        print("[СВЕРКА] недостаточно данных для пар (вопрос пользователю):",
              file=sys.stderr)
        for _p in _insufficient:
            print("  ? %s <-> %s" % _p, file=sys.stderr)
    else:
        _cands = _svarka_candidates(variations)
        if _cands:
            # печать — ОРИГИНАЛЬНЫМИ заголовками (для LLM/пользователя)
            _orig = {}
            for _sp in specs:
                for _s in _sp.get("sections", []):
                    for _node, _chain in _walk_titles(_s):
                        _orig.setdefault(norm_title(_node.get("title", "")),
                                         _node.get("title", ""))
            print("[СВЕРКА] похожие сигнатуры — кандидаты на слияние "
                  "(проверить LLM/пользователем, не сливать автоматически):",
                  file=sys.stderr)
            for _a, _b, _jac in _cands:
                print("  - «%s» <-> «%s» (жаккар %.2f)"
                      % (_orig.get(_a, _a), _orig.get(_b, _b), _jac),
                      file=sys.stderr)
                # T3b-контекст: родительский раздел + пример содержания
                for _sig in (_a, _b):
                    _ctx = _sig_context(specs, _sig)
                    print("    · «%s»: раздел «%s», пример: %s"
                          % (_orig.get(_sig, _sig), _ctx[0], _ctx[1]),
                          file=sys.stderr)
    _razv_q, _razv_i = _razvodka_split(_razvodka_pairs(per_sample, common))
    if _razv_q:
        print("[РАЗВОДКА] одноимённые сигнатуры с КОНТЕНТНЫМ расхождением "
              "(решение — пользователю, молчаливого слияния нет):",
              file=sys.stderr)
        for _sig, _why in _razv_q:
            print("  - «%s»: %s" % (_sig, _why), file=sys.stderr)
    if _razv_i:
        print("[РАЗВОДКА-OK] вариативность плотности — норма (Пятое "
              "правило), вопрос не требуется:", file=sys.stderr)
        for _sig, _why in _razv_i:
            print("  - «%s»: %s" % (_sig, _why), file=sys.stderr)

    # «большинственный» уровень каждого общего раздела (моду по образцам)
    def majority_level(sig):
        lv = [acc[sig]["level"] for acc in per_sample if sig in acc]
        return Counter(lv).most_common(1)[0][0]

    # референс — образец, где больше всего «большинственных» разделов на
    # большинственном уровне
    def score(sp):
        acc = per_sample[specs.index(sp)]
        return sum(1 for sig in common
                   if sig in acc and acc[sig]["level"] == majority_level(sig))
    ref = max(specs, key=score)
    ref_acc = per_sample[specs.index(ref)]

    # собственные скриншоты раздела (по СОБСТВЕННОМУ дереву образца) =
    # body-скриншоты + скриншоты НЕобщих детей. Общие дети учитываются
    # отдельно (у себя), чтобы не считать дважды. Скриншоты под подфункциями
    # (необщие дети) «выпадают» в тело раздела — и учитываются здесь.
    def own_shots(node, common):
        """Скриншоты, принадлежащие ЭТОМУ общему разделу:
        body-скриншоты + subtree-скриншоты НЕобщих детей (они не входят в
        пересечение, их скриншоты «выпадают» сюда). Общие дети не считаем —
        они учитывают себя сами (каждый скриншот — ровно один раз)."""
        sig = norm_title(node["title"])
        if sig not in common:
            return _count_shots_subtree(node)
        total = sum(1 for b in node["body"] if b["type"] == "screenshot")
        for c in node["children"]:
            if norm_title(c["title"]) not in common:
                total += _count_shots_subtree(c)
        return total

    # по каждому образцу: {сигнатура: собственные скриншоты} для ВСЕХ общих
    # разделов (рекурсивно по дереву)
    def collect_own(node, m):
        sig = norm_title(node["title"])
        if sig in common:
            # суммируем: дубликат сигнатуры (редко) вносит свой вклад
            m[sig] = m.get(sig, 0) + own_shots(node, common)
        for c in node["children"]:
            collect_own(c, m)

    own_shots_per = []
    for sp in specs:
        m = {}
        for s in sp["sections"]:
            collect_own(s, m)
        own_shots_per.append(m)

    # T6 (аудит Г3): варианты формулировок общих разделов — первый
    # содержательный абзац тела раздела в КАЖДОМ образце; 2+ разных
    # варианта → каркас минипрофилей печатает блок «АЛЬТЕРНАТИВЫ»
    def collect_first_para(node, m):
        sig = norm_title(node["title"])
        if sig in common:
            first = next((b.get("text") for b in node.get("body", [])
                          if b.get("type") == "paragraph" and b.get("text")),
                         None)
            if first:
                m.setdefault(sig, set()).add(first)
        for c in node.get("children"):
            collect_first_para(c, m)

    first_para_per = []
    for sp in specs:
        m = {}
        for s in sp["sections"]:
            collect_first_para(s, m)
        first_para_per.append(m)

    # прямые дети уровня 3 (подфункции) по сигнатурам: плейсхолдеры
    # подфункций создаются там же, где они стоят в образце — вложенными
    # в свой раздел (иначе нумерация даёт «N.0.K» на уровне выше)
    def collect_h3(node, m):
        sig = norm_title(node["title"])
        m[sig] = m.get(sig, 0) + sum(1 for c in node["children"]
                                     if c["level"] == 3)
        for c in node["children"]:
            collect_h3(c, m)

    h3_per = []
    for sp in specs:
        m = {}
        for s in sp["sections"]:
            collect_h3(s, m)
        h3_per.append(m)

    # миноритарные контентные таблицы (E-52; T1, аудит Г1): таблица не
    # дотянула до большинства (3/4) — как таблицы реквизитов
    # «Имя|Синоним|Тип» тех-образцов (они живут в НЕобщих разделах, поэтому
    # сканируем per_sample ЦЕЛИКОМ, а не тело общих разделов). НЕ
    # выбрасывать НИ ПРИ КАКОМ числе источников, включая единственный
    # (порог n>=1, решение T1 2026-11-20 — таблицы образца «-10» терялись):
    # профиль самой полной вариации идёт в spec.variations.tables (модель
    # и рендер оформляют реквизиты таблицей, а не списком). Запись из
    # единственного образца помечается sole_source + source_file.
    _var_groups = {}
    for _i, _acc in enumerate(per_sample):
        _src = os.path.basename(
            (specs[_i].get("meta") or {}).get("source_file", ""))
        _seen_here = set()
        for _sig, _a in _acc.items():
            for _nc, _hdrs, _cols, _nrows, _er, _cb, _cl, _hc in _a["tables"]:
                _key = frozenset(_hdrs)
                if _key in _seen_here:
                    continue
                _seen_here.add(_key)
                _g = _var_groups.setdefault(_key, {"n": 0, "cands": []})
                _g["n"] += 1
                _g["cands"].append({"columns": _cols, "rows": _nrows,
                                    "widths": None, "example_row": _er,
                                    "col_bold": _cb, "col_lead": _cl,
                                    "has_caption": _hc,
                                    "source_file": _src})
    var_tables = []
    for _g in _var_groups.values():
        if _g["n"] >= 1:  # T1: даже таблица из ОДНОГО образца не теряется
            _best = max(_g["cands"], key=lambda c: len(c["columns"]))
            # T5: полный список источников таблицы-вариации
            _rec = dict(_best, in_samples=_g["n"],
                        src=[c["source_file"] for c in _g["cands"]])
            if _g["n"] == 1:
                _rec["sole_source"] = True
            var_tables.append(_rec)

    def build(node):
        sig = norm_title(node["title"])
        if sig not in common:
            return None
        # T5 (план п.1.4): происхождение — полный список файлов-образцов,
        # где сигнатура присутствует; in_samples = len(src) (факт)
        _src = [os.path.basename((specs[_i].get("meta") or {})
                                 .get("source_file", ""))
                for _i, _acc in enumerate(per_sample) if sig in _acc]
        # общий «пол» собственных скриншотов и подфункций
        shots = min(m[sig] for m in own_shots_per if sig in m)
        h3 = min(m[sig] for m in h3_per if sig in m)
        pb_votes = [acc[sig].get("page_break", False)
                    for acc in per_sample if sig in acc]
        new = {"level": node["level"], "title": node["title"],
               # в скольких образцах присутствует элемент (факт) —
               # генминипрофиль печатает «в N из M образцов» без чтения DOCX
               "in_samples": len(_src),
               # T5: полный список файлов-источников элемента
               "src": _src,
               # T6 (аудит Г3): варианты формулировок раздела по образцам
               "formulation_variants": sorted(set().union(
                   *(first_para_per[_i][sig] for _i, _acc
                     in enumerate(per_sample)
                     if sig in _acc and sig in first_para_per[_i]))),
               "page_break": sum(bool(v) for v in pb_votes)
               >= _need(len(pb_votes))
               if pb_votes else False,
               "body": [], "children": []}
        # тело: восстановление позиций из референса (п.5). Скриншоты в образцах
        # стоят там, где текст описывает действие (кнопка/окно/вкладка/отбор) —
        # сохраняем эти позиции: [ТЕКСТ] → [СКРИНШОТ]. Бюджет = общий «пол».
        budget = shots
        pending = False  # перед скриншотом был абзац → нужен [ТЕКСТ]
        for b in node["body"]:
            if b["type"] == "table":
                # контентный матчинг: у каждого образца в этой секции должна
                # быть таблица той же ширины с перекрытием заголовков ≥ 50%
                tokens = set(_norm_header_tokens(b["columns"]))
                # таблица шаблонная, если совпадает в большинстве образцов,
                # содержащих раздел (не обязательно во всех)
                have = [acc for acc in per_sample if sig in acc]
                ok = sum(
                    1 for acc in have
                    if any(_tbl_match(nc, hdrs, len(b["columns"]), tokens)
                           for nc, hdrs, _, _, _, _, _, _ in acc[sig]["tables"])
                ) >= _need(len(have))
                if ok:
                    # профиль таблицы — САМЫЙ ПОЛНЫЙ вариант среди
                    # совпавших (урок Прогона #8: референс мог дать
                    # урезанную таблицу, когда в соседнем образце та же
                    # таблица описана полнее — больше колонок/заголовков)
                    best = b
                    best_key = len(tokens)
                    for acc in have:
                        for nc, hdrs, cols, nrows, _er, _cb, _cl, _hc in acc[sig]["tables"]:
                            if (_tbl_match(nc, hdrs, len(b["columns"]), tokens)
                                    and len(hdrs) > best_key):
                                best_key = len(hdrs)
                                best = {"columns": cols, "rows": nrows,
                                        "headers": hdrs, "col_bold": _cb, "col_lead": _cl,
                                        "has_caption": _hc}
                    if best is not b:
                        if set(_norm_header_tokens(best["columns"])) == tokens:
                            # тот же состав заголовков → ширины референса валидны
                            b = dict(best, widths=b.get("widths"))
                        else:
                            # состав другой (таблица полнее) → ширины
                            # референса неверны, не переносим
                            b = dict(best, widths=None)
                    tokens = set(_norm_header_tokens(b["columns"]))
                    # example_row: большинство по всем совпавшим таблицам
                    # образцов; при ничьей — самая информативная строка
                    # (урок Прогона #7: референс мог дать «голый» код ФР
                    # вместо реального примера из соседнего образца)
                    cands = []
                    for acc in have:
                        for nc, hdrs, _, _, er, _cb, _cl, _hc in acc[sig]["tables"]:
                            if (_tbl_match(nc, hdrs, len(b["columns"]), tokens)
                                    and er):
                                cands.append(er)
                    er = b.get("example_row")
                    if cands:
                        # предпочитаем содержательные примеры («Кладовщик…»,
                        # а не «голый» код ФР); большинство — среди них
                        def _info_len(row):
                            # содержательность без плейсхолдеров: «[КОД |
                            # пример: …]» считается одним символом
                            return sum(len(re.sub(r"\[[^\]]*\]", "#",
                                                  str(v))) for v in row)
                        informative = [c for c in cands if _info_len(c) >= 40]
                        pool_src = informative or cands
                        norm = Counter(tuple(str(c) for c in x) for x in pool_src)
                        top = norm.most_common()
                        best_n = top[0][1]
                        pool = [c for c, n in top if n == best_n]
                        er = max(pool, key=_info_len)
                    # жирность колонок — только при СОГЛАСОВАННОСТИ образцов
                    # (урок E-40): авторы иногда жирнят ячейки экспромтом —
                    # колонка «жирная» лишь если все совпавшие образцы
                    # единодушны по колонке; иначе признак сбрасывается
                    def _col_votes(key):
                        votes = []
                        for acc in have:
                            for nc, hdrs, _, _, _, cb, cl, _hc in acc[sig]["tables"]:
                                if (_tbl_match(nc, hdrs, len(b["columns"]), tokens)
                                        and isinstance(cb, list)):
                                    votes.append(cb if key == "bold" else cl)
                        if not votes:
                            return None
                        ncol = len(b["columns"])
                        return [all(len(v) > j and v[j] for v in votes)
                                for j in range(ncol)]
                    # has_caption — большинство по совпавшим таблицам
                    hc = [hc2 for acc in have
                          for nc, hdrs, _, _, _, _, _, hc2 in acc[sig]["tables"]
                          if _tbl_match(nc, _norm_header_tokens(hdrs),
                                        len(b["columns"]), tokens)]
                    new["body"].append({"type": "table", "columns": b["columns"],
                                        "rows": b["rows"],
                                        "widths": b.get("widths"),
                                        "example_row": er,
                                        "col_bold": _col_votes("bold"),
                                        "col_lead": _col_votes("lead"),
                                        "has_caption": (sum(1 for v in hc if v)
                                                        >= _need(len(hc))
                                                        if hc else False),
                                        "header_repeat": True,
                                        # T5: образцы, чьи таблицы совпали
                                        "src": [os.path.basename(
                                            (specs[_i].get("meta") or {})
                                            .get("source_file", ""))
                                            for _i, _acc in enumerate(per_sample)
                                            if sig in _acc
                                            and any(_tbl_match(nc, hdrs,
                                                               len(b["columns"]),
                                                               tokens)
                                                    for nc, hdrs, _, _, _, _, _, _
                                                    in _acc[sig]["tables"])]})
                else:
                    # T1 (аудит Г1): миноритарная таблица ВНУТРИ общего
                    # раздела не теряется молча — лучший кандидат из
                    # образцов с этим разделом идёт в шаблон (пример-строка,
                    # пометка единственного источника; оформление ставит
                    # конвейер, а не LLM-ваншоты)
                    _cands = []
                    for _acc in have:
                        for nc, hdrs, cols, nrows, _er, _cb, _cl, _hc in _acc[sig]["tables"]:
                            if _tbl_match(nc, hdrs, len(b["columns"]), tokens):
                                _cands.append({"columns": cols, "rows": nrows,
                                               "example_row": _er,
                                               "headers": hdrs})
                    if _cands:
                        _best = max(_cands, key=lambda c: len(c["headers"]))
                        new["body"].append({
                            "type": "table", "columns": _best["columns"],
                            "rows": _best["rows"], "widths": None,
                            "example_row": _best["example_row"],
                            "col_bold": None, "col_lead": None,
                            "has_caption": False, "header_repeat": True,
                            "minority": True,
                            "sole_source": len(_cands) == 1,
                            "source_file": os.path.basename(
                                next((sp.get("meta", {}).get("source_file", "")
                                      for sp, acc in zip(specs, per_sample)
                                      if any(_tbl_match(nc, hdrs, len(b["columns"]), tokens)
                                             for nc, hdrs, _, _, _, _, _, _
                                             in acc[sig]["tables"])),
                                      ""))})
            elif b["type"] == "list":
                # списки референса переносятся целиком (маркеры/нумерация
                # образца; до этого исправления списки терялись в пересечении)
                if b.get("items"):
                    new["body"].append({"type": "list", "items": b["items"],
                                        "fmt": b.get("fmt")})
            elif b["type"] == "caption":
                # подписи (Caption, «Таблица N. …») — структурный элемент,
                # как шапка таблицы; переносятся из референса (D-2: раньше
                # терялись в пересечении всегда). Номер таблицы в шаблоне —
                # пример, на этапе заполнения заменяется реальным.
                if b.get("text"):
                    new["body"].append({"type": "caption",
                                        "text": b["text"],
                                        "size_pt": b.get("size_pt")})
            elif b["type"] == "screenshot":
                if budget > 0:
                    if pending:
                        new["body"].append({"type": "paragraph",
                                            "text": "[ТЕКСТ: опишите действие/результат]"})
                        pending = False
                    new["body"].append({"type": "screenshot", "caption": None})
                    budget -= 1
            elif b["type"] == "paragraph":
                pending = True
        # подфункции: общий пол; в образцах каждая подфункция снабжена
        # скриншотом (рисунок — графическое пояснение действия пользователя),
        # поэтому каждой плейсхолдерной подфункции — своё место под скриншот
        # из общего бюджета (остаток уходит в тело раздела)
        h3_shots = min(h3, budget)
        budget -= h3_shots
        for i in range(h3):
            new["children"].append({
                "level": 3, "title": "[ПОДФУНКЦИЯ]",
                "body": [{"type": "screenshot", "caption": None}] if i < h3_shots else [],
                "children": [],
                "hint": _hint_for({"level": 3, "title": ""}),
            })
        # остаток бюджета (если в референсе меньше связанных скриншотов, чем «пол»)
        for _ in range(budget):
            new["body"].append({"type": "screenshot", "caption": None})
        # подсказка (п.4): из образца — первый абзац раздела (с плейсхолдерами)
        new["hint"] = _hint_from_src(node.get("hint_src"), node)
        # дети: рекурсия по структуре референса (подфункции уже добавлены выше)
        for c in node["children"]:
            if c["level"] == 3:
                continue
            sub = build(c)
            if sub is not None:
                new["children"].append(sub)
        return new

    out_sections = []
    for s in ref["sections"]:
        sub = build(s)
        if sub is not None:
            out_sections.append(sub)

    # «большинственные» разделы, отсутствующие в референсе: берём из образца,
    # где они есть (иначе референс молча терял бы контент большинства)
    produced = set()

    def collect_sig(node):
        produced.add(norm_title(node["title"]))
        for c in node["children"]:
            collect_sig(c)

    for s in out_sections:
        collect_sig(s)

    def _find_by_sig(node, want):
        if norm_title(node["title"]) == want:
            return node
        for c in node["children"]:
            f = _find_by_sig(c, want)
            if f is not None:
                return f
        return None

    def find_parent_sig(sp, want):
        for s in sp["sections"]:
            def walk(node, parent):
                if norm_title(node["title"]) == want:
                    return parent
                for c in node["children"]:
                    r = walk(c, norm_title(node["title"]))
                    if r is not None:
                        return r
            r = walk(s, None)
            if r is not None:
                return r
        return None

    def insert_into(out_list, parent_sig, section):
        if parent_sig is None:
            out_list.append(section)
            return
        def walk(lst):
            for it in lst:
                if norm_title(it["title"]) == parent_sig:
                    it["children"].append(section)
                    return True
                if walk(it["children"]):
                    return True
            return False
        walk(out_list)

    missing = [sig for sig in common if sig not in produced]
    for sig in missing:
        src = None
        for sp in specs:
            for s in sp["sections"]:
                f = _find_by_sig(s, sig)
                if f is not None:
                    src = (sp, f)
                    break
            if src:
                break
        if src is None:
            continue
        sp, node = src
        have = [acc for acc in per_sample if sig in acc]
        lvl = majority_level(sig)
        tables_out = []
        for b in node["body"]:
            if b["type"] != "table":
                continue
            tokens = set(_norm_header_tokens(b["columns"]))
            if sum(1 for acc in have
                   if any(_tbl_match(nc, hdrs, len(b["columns"]), tokens)
                          for nc, hdrs, _, _, _, _, _, _ in acc[sig]["tables"])
                   ) >= _need(len(have)):
                tables_out.append({"type": "table", "columns": b["columns"],
                                   "rows": b["rows"], "widths": b.get("widths"),
                                   "example_row": b.get("example_row"),
                                   "col_bold": b.get("col_bold"),
                                        "col_lead": b.get("col_lead"),
                                        "has_caption": b.get("has_caption"),
                                   "header_repeat": True})
        shots = min((acc[sig]["shots"] for acc in have if sig in acc),
                    default=0)
        pb_votes = [acc[sig].get("page_break", False)
                    for acc in per_sample if sig in acc]
        sec = {"level": lvl, "title": node["title"],
               "in_samples": int(counts[sig]),
               "page_break": sum(bool(v) for v in pb_votes)
               >= max(2, math.ceil(majority_ratio * len(pb_votes)))
               if pb_votes else False,
               "body": tables_out,
               "children": [],
               "hint": _hint_from_src(node.get("hint_src"), node)}
        for _ in range(shots):
            sec["body"].append({"type": "screenshot", "caption": None})
        insert_into(out_sections, find_parent_sig(sp, sig), sec)
        collect_sig(sec)

    # пересечение наследует оформление/нумерацию/страницу от референса
    # (подсказки уже проставлены в build() — из образца, не общими)
    out = dict(ref)
    out["sections"] = out_sections
    # meta — копия референса (не мутировать общий dict!): фактическое
    # число образцов нужно генминипрофилю («в N из M образцов»)
    out["meta"] = dict(out.get("meta") or {})
    out["meta"]["samples_count"] = len(specs)
    out["meta"].update(presence_meta)  # уровень присутствия §7.1.3a
    # вариации: «большинственные» разделы, отсутствующие в части образцов,
    # и разделы-исключения — выносятся пользователю (методика 7.1.3/7.1.6)
    out["variations"] = {
        "presence_rule": f"majority >= {need}/{len(specs)}",
        "excluded_sections": variations,
        # маркерные разделы (урок V9): место алгоритмов, не рядовая вариация
        "marker_sections": marker_secs,
        # миноритарные контентные таблицы (E-52): реквизиты тех-ТЗ —
        # таблица «Имя|Синоним|Тип» в части образцов; шаблонные
        # (мажоритарные) таблицы исключаются — они уже в секциях
        "tables": [t for t in var_tables
                   if frozenset(_norm_header_tokens(t["columns"]))
                   not in {frozenset(_norm_header_tokens(c["columns"]))
                           for c in _collect_tables(out_sections)}],
    }
    # TOC / H1-разрыв: enabled/present — требование вёрстки (v6, константа
    # параметра); in_samples — сколько образцов содержат признак (факт)
    out["toc"] = dict(ref.get("toc") or {"present": True, "instr": TOC_DEFAULT_INSTR})
    out["toc"]["in_samples"] = sum(1 for sp in specs if sp.get("toc", {}).get("in_source"))
    out["h1_page_break"] = dict(ref.get("h1_page_break") or {"enabled": False})
    out["h1_page_break"]["in_samples"] = sum(
        1 for sp in specs if sp.get("h1_page_break", {}).get("in_source"))
    # титульный лист — из образца с блоком подписей (есть не у всех)
    tb_src = next((sp for sp in specs
                   if any("sig_rows" in it for it in sp["title_block"])), None)
    if tb_src is not None:
        out["title_block"] = _tokenize_code_title(tb_src["title_block"])
    # колонтитулы — по большинству образцов (Б2), не только из tb_src;
    # fallback на титульный источник, если большинство пусто
    out["header_footer"] = (_hf_majority(specs)
                            or (tb_src.get("header_footer")
                                if tb_src is not None else None))
    # тип документа (E-50, уточнение пользователя): ГЛАВНЫЙ признак тех-ТЗ —
    # большой объём технического описания ОБЪЕКТОВ И РЕКВИЗИТОВ:
    # элементы списков «имя – X / синоним – Y / тип – Z …» и таблицы
    # «реквизит/тип/заполнение», «имя/синоним/тип». Бизнес-ТЗ таких
    # описаний не содержит. Голосование по КАЖДОМУ образцу (в
    # пересечении тексты списков не сохраняются); дефолт — бизнес
    # (существующая ветка не меняется).
    def _attr_votes(sp):
        v = 0
        def walk(node):
            nonlocal v
            for b in node.get("body", []):
                bt = b.get("type")
                if bt == "table":
                    hdr = norm_title(" ".join(b.get("columns", [])))
                    if ("реквизит" in hdr and "тип" in hdr) or \
                            ("имя" in hdr and "синоним" in hdr and "тип" in hdr):
                        v += 2
                elif bt == "list":
                    for it in b.get("items", []):
                        t = norm_title(it if isinstance(it, str) else str(it))
                        if re.match(r"^(имя|синоним|тип|реквизит|заполнение|"
                                    r"отбор|видимость|размещение)\b", t):
                            v += 1
                elif bt == "paragraph":
                    t = norm_title(str(b.get("text", "")))
                    if re.match(r"^(имя|синоним|тип|реквизит|заполнение|"
                                r"отбор|видимость|размещение)\b", t):
                        v += 1
            for c in node.get("children", []):
                walk(c)
        for s in sp.get("sections", []):
            walk(s)
        return v
    _votes = [_attr_votes(sp) for sp in specs]
    # шаблон имени файла — из имён образцов (бизнес: «Заказчик_ТЗ_…»,
    # тех: «Приложение к ТЗ …»); рендер формирует имя по нему, гейт
    # запрещает выдуманные имена (E-50, прогон тех-1)
    _pat = _naming_pattern([os.path.splitext(os.path.basename(sp["meta"].get("source_file", "")))[0]
                            for sp in specs])
    if _pat:
        out["meta"]["file_name_pattern"] = _pat
    out["meta"]["doc_type"] = ("техническое ТЗ" if max(_votes, default=0) >= 6
                               else "бизнес-ТЗ")
    out["meta"]["attr_votes"] = _votes
    # TOC — требование вёрстки v6 для БИЗНЕС-ТЗ. Тех-ТЗ: оглавления в
    # образцах нет → не вставлять (пустая страница-оглавление — дефект
    # гейта 2 тех-прогона E-50). Единственное место решения — здесь.
    if out["meta"]["doc_type"] == "техническое ТЗ" and not out["toc"]["in_samples"]:
        out["toc"]["present"] = False
    # плотность пересечения (счётчики общие с _recompute_density)
    out["density"] = {
        "screenshots_total": sum(_count_shots_subtree(s) for s in out_sections),
        "business_logic_subfunctions": sum(_count_h3_subtree(s) for s in out_sections),
        "tables": _collect_tables(out_sections),
    }
    # словарь ролей — объединение по всем образцам (для границы
    # жирного префикса в таблице тестирования, E-41). T2 (аудит Г4):
    # мусор из колонки «Роль» не попадает в roles:
    #  (а) 1С-роль — токен префикс+CamelCase (рткЧтение…, ккЧтение…);
    #  (б) бизнес-роль — именная группа ≤5 значимых слов (предлоги/союзы
    #      не считаются) без глагольных форм; ячейка через запятую —
    #      несколько ролей;
    #  (в) мусор («Пока такой роли нет…», функциональные строки,
    #      совпадающие с H3) → variations.notes + печать в отчёте
    #      extract (подтверждение пользователем, контракт Шага 2).
    _STOP_WORDS = {"к", "и", "в", "на", "по", "с", "со", "для", "при", "о",
                   "от", "до", "из", "у", "за"}
    _VERB_HINTS = ("нет", "нужна", "нужен", "нужны", "нужно", "будет",
                   "есть", "пока", "требуется", "добавить", "создать")

    def _classify_role(v, known_sigs):
        """('role', каноническое имя) | ('note', исходная строка)"""
        v = v.strip()
        if not v:
            return None
        # (а) 1С-роль: строчный префикс + CamelCase (рткЧтение…)
        if re.match(r"^[а-яё]{2,10}[А-ЯЁ]", v):
            return ("role", v)
        low = norm_title(v)
        # (в) функциональная строка, совпадающая с заголовком раздела
        if low in known_sigs:
            return ("note", v)
        # (в) глагольные/оценочные формулировки («Пока такой роли нет…»)
        toks = [t.strip(",;.!«»\"'()") for t in v.split()]
        if any(t.lower() in _VERB_HINTS for t in toks if t):
            return ("note", v)
        # (б) именная группа(ы): запятая разделяет несколько ролей;
        # значимые слова — без предлогов/союзов; сокращение в скобках
        # («(РТК)») прикрепляется к предыдущему слову
        for part in v.split(","):
            words = [t for t in part.split()
                     if t.lower().strip(",;.!«»\"'") not in _STOP_WORDS
                     and not re.fullmatch(r"\([А-ЯЁA-Z]{2,10}\)", t)]
            if not words or len(words) > 5:
                return ("note", v)
            if any(re.search(r"[а-яё](ть|ла|ло|ли|ет|ют|ит|ат|ят)$", w.lower())
                   for w in words):
                return ("note", v)
        return ("role", v)

    _roles = set()
    _role_notes = set()
    for _sp in specs:
        for _r in (_sp.get("roles") or []):
            _parts = [_r] + ([p.strip() for p in _r.split(",") if p.strip()]
                             if "," in _r else [])
            for _part in _parts:
                _cls = _classify_role(_part, counts)
                if _cls is None:
                    continue
                _kind, _val = _cls
                (_roles if _kind == "role" else _role_notes).add(_val)
    if _roles:
        out["roles"] = sorted(_roles)
    # T5 (план п.1.4): происхождение УСЛОВНЫХ разделов (вариаций) —
    # сигнатура → список файлов-образцов, где раздел присутствует
    out["variations"]["sections_src"] = {
        _sig: [os.path.basename((specs[_i].get("meta") or {})
                                .get("source_file", ""))
               for _i, _acc in enumerate(per_sample) if _sig in _acc]
        for _sig in set(out["variations"].get("excluded_sections") or [])
        | set(out["variations"].get("marker_sections") or [])
        if any(_sig in _acc for _acc in per_sample)}
    out["variations"]["notes"] = sorted(_role_notes)
    if _role_notes:
        print("[РОЛИ] отвергнуто (подтвердите на Шаге 2): %s"
              % "; ".join(sorted(_role_notes)), file=sys.stderr)
    # термины глоссариев ВСЕХ образцов (lint_draft: термин вне этого
    # списка и вне описания доработки — кандидат «выдумано», E-48)
    _gl = set()
    for _sp in specs:
        _gl.update(_sp.get("glossary_terms") or [])
    out["glossary_terms"] = sorted(_gl)
    return out


def substitute_keep(obj):
    """Режим pii=keep: известные значения подставляются СРАЗУ —
    «[НАИМЕНОВАНИЕ | пример: X]» → «X»; плейсхолдеры без примера
    (неизвестное) остаются токенами; example_line удаляется
    (дублировал бы уже подставленную строку)."""
    if isinstance(obj, dict):
        return {k: (None if k == "example_line" else substitute_keep(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [substitute_keep(v) for v in obj]
    if isinstance(obj, str):
        def _sub(m):
            # Б5: код референса НЕ разворачивается (в keep-режиме литеральный
            # «чужой» код протекал в титул шаблона) — остаётся токеном [КОД];
            # фактический код подставляет render_md --set КОД=…
            if m.group(0).startswith("[КОД"):
                return m.group(0).split("|")[0].strip() + "]"
            return m.group(1)
        return _EXAMPLE_TOKEN_RE.sub(_sub, obj)
    return obj


_UI_LANG = {"ru": "ru-RU", "en": "en-US"}


def _apply_lang(spec):
    """fonts.lang — из ЯЗЫКА ТЕКСТА (meta.language), не из docDefaults
    w:lang: там язык машины автора (в образцах it-IT при русском
    тексте) — с ним Word краснит русский текст как иностранный."""
    lang = (spec.get("meta") or {}).get("language")
    if lang in _UI_LANG:
        spec.setdefault("fonts", {})["lang"] = _UI_LANG[lang]


def _detect_language(paths):
    """Язык образцов по соотношению кириллицы и латиницы в тексте
    (meta.language — задел под будущие языковые пакеты каталога;
    на механику парсинга не влияет)."""
    cyr = lat = 0
    for p in paths:
        try:
            d = Document(p)
        except Exception:
            continue
        for para in d.paragraphs:
            for ch in para.text:
                low = ch.lower()
                if "а" <= low <= "я" or ch in "ёЁ":
                    cyr += 1
                elif "a" <= low <= "z":
                    lat += 1
    if cyr >= lat and cyr > 0:
        return "ru"
    if lat > cyr:
        return "en"
    return "und"


def _find_catalog(explicit=None):
    """Путь к document-model.ru.yaml: --catalog → env TZ_CATALOG →
    стандартные расположения (рядом со скриптом / в скилле)."""
    cands = []
    if explicit:
        cands.append(explicit)
    if os.environ.get("TZ_CATALOG"):
        cands.append(os.environ["TZ_CATALOG"])
    here = os.path.dirname(os.path.abspath(__file__))
    cands += [
        os.path.join(here, "references", "document-model.ru.yaml"),
        os.path.join(here, "..", "references", "document-model.ru.yaml"),
        os.path.join(here, "..", ".zcode", "skills", "tz-rezultat-hz",
                     "references", "document-model.ru.yaml"),
    ]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


_PAGE_LEVEL = {"header", "footer", "page-number", "page-geometry",
               "first-page-diff", "toc", "title-page"}


def _apply_page_elements(spec, elements):
    """Класс A (постраничные): выборка уже разобранных полей spec.
    header → spec.header_footer.header; footer/page-number → .footer
    (номер страницы — часть footer); title-page/first-page-diff →
    first_page (логотипы титула); page-geometry — свойство страницы,
    сохраняется всегда (не контент)."""
    hf = spec.get("header_footer")
    if hf:
        if "header" not in elements:
            hf["header"] = None
        if "footer" not in elements and "page-number" not in elements:
            hf["footer"] = None
        if "title-page" not in elements and "first-page-diff" not in elements:
            hf.pop("first_page", None)
            hf.pop("first_page_images", None)


def _walk_blocks(node):
    """Все body-блоки поддерева секций в порядке документа."""
    for b in node["body"]:
        yield b
    for c in node["children"]:
        yield from _walk_blocks(c)


def _tbl_header_tokens(tbl_block):
    toks = set()
    for col in tbl_block.get("columns", []):
        for w in re.split(r"[^\w]+", re.sub(r"\[[^\]]*\]", "", col).lower()):
            if w:
                toks.add(w.strip(".,"))
    return toks


def _specimen_blocks(spec, eid, spec_list=None):
    """Фрагменты образца для specimen-режима (класс C, протокол §1.3):
    первый фрагмент, где элемент встречается, по признакам detection.
    Поиск по референсу И по всем образцам (элемент может быть в одном
    образце и не попасть в большинство-пересечение).
    Пусто → элемента нет в образцах (честная ошибка, не пустой шаблон)."""
    blks = [b for s in spec["sections"] for b in _walk_blocks(s)]
    for extra in (spec_list or []):
        blks += [b for s in extra["sections"] for b in _walk_blocks(s)]
    heads = [b for b in blks if b["type"] == "heading"]
    if eid == "figure":
        return [b for b in blks if b["type"] == "screenshot"][:1]
    if eid == "figure-caption":
        for b in blks:
            if b["type"] == "screenshot" and b.get("caption"):
                return [b]
        shots = [b for b in blks if b["type"] == "screenshot"]
        return [{**shots[0], "caption": None}] if shots else []
    if eid == "table":
        return [b for b in blks if b["type"] == "table"][:1]
    if eid == "table-rights":
        for b in blks:
            if b["type"] == "table" and \
                    {"прав", "права", "роль", "роли", "доступ"} & _tbl_header_tokens(b):
                return [b]
        return []
    if eid == "table-testing":
        for b in blks:
            if b["type"] == "table" and \
                    {"тест", "тестирования", "шаг", "действие", "результат"} & _tbl_header_tokens(b):
                return [b]
        return []
    if eid == "bulleted-list":
        return [b for b in blks if b["type"] == "list" and b.get("fmt") == "bullet"][:1]
    if eid == "numbered-list":
        return [b for b in blks if b["type"] == "list" and b.get("fmt") == "decimal"][:1]
    if eid == "term-definition-list":
        # глоссарная таблица (2 колонки) или пары «термин — текст»
        for b in blks:
            if b["type"] == "table" and \
                    {"термин", "сокращение", "описание"} & _tbl_header_tokens(b):
                return [b]
        for b in blks:
            if b["type"] == "paragraph" and re.match(r"^\S[^—-]{0,60}[—-]\s+\S", b.get("text", "")):
                return [b]
        return []
    if eid == "note-block":
        return [b for b in blks if b["type"] == "paragraph"
                and b.get("text", "").lower().startswith("примечание")][:1]
    if eid == "callout":
        return [b for b in blks if b["type"] == "paragraph"
                and re.match(r"^(важно|внимание|опасно)\b", b.get("text", "").lower())][:1]
    if eid == "user-message-emphasis":
        # naming-and-emphasis-universal: абзац ТЕЛА с run-ом курсивом
        # и/или цветом ≠ auto/чёрный (шаблон выделения сообщений)
        for b in blks:
            if b["type"] != "paragraph" or b.get("_el") is None:
                continue
            for r in b["_el"].findall(".//" + qn("w:r")):
                rPr = r.find(qn("w:rPr"))
                if rPr is None:
                    continue
                if rPr.find(qn("w:i")) is not None:
                    return [b]
                _c = rPr.find(qn("w:color"))
                if _c is not None and (_c.get(qn("w:val")) or "").upper() \
                        not in ("AUTO", "000000"):
                    return [b]
        return []
    if eid in ("heading", "numbered-heading"):
        # по одному узлу уровней 1–3: specimen показывает 1 → 1.1 → 1.1.1
        out, got = [], set()
        for s in spec["sections"]:
            def pick(node):
                if node["level"] not in got:
                    out.append(node)
                    got.add(node["level"])
                if len(got) == 3:
                    return
                for c in node["children"]:
                    pick(c)
            pick(s)
            if len(got) == 3:
                break
        return out
    return []


def _specimen_sections(spec, eid, by_id, spec_list=None):
    """Синтетическая секция-образец из фрагментов элемента."""
    label = (by_id.get(eid, {}).get("description") or eid)
    label = re.split(r"[:—-]", label)[0].strip() or eid
    blocks = _specimen_blocks(spec, eid, spec_list)
    if not blocks:
        raise SystemExit(
            f"[extract_spec] элемент «{eid}» не найден в образцах — specimen "
            f"невозможен (признаки detection не сработали)")
    # заголовки уровней — секционным деревом; контент — одной секцией
    if eid in ("heading", "numbered-heading"):
        secs = []
        for node in blocks:
            t, _ph = to_placeholder(node["title"])
            secs.append({"level": node["level"], "title": t, "placeholder": _ph,
                         "body": [], "children": [],
                         "hint": f"ПОДСКАЗКА: образец заголовка уровня {node['level']}"})
        # вложить уровни: 1 → 2 → 3
        root = secs[0]
        parent = root
        for s in secs[1:]:
            if s["level"] > parent["level"]:
                parent["children"].append(s)
            else:
                root["children"].append(s)
            parent = s
        return [root]
    sec = {"level": 1, "title": f"[ЭЛЕМЕНТ | пример: {eid}]",
           "placeholder": ["ЭЛЕМЕНТ"], "body": blocks, "children": [],
           "hint": f"ПОДСКАЗКА: образец элемента «{label}» из ваших образцов"}
    return [sec]


def _collect_tables(sections):
    """Профили всех таблиц дерева секций (для spec.density.tables)."""
    tables = []

    def _coll(node):
        for blk in node["body"]:
            if blk["type"] == "table":
                tables.append({"columns": blk["columns"], "rows": blk["rows"],
                               "widths": blk.get("widths"),
                               "col_bold": blk.get("col_bold"),
                               "col_lead": blk.get("col_lead"),
                               "has_caption": blk.get("has_caption")})
        for c in node["children"]:
            _coll(c)

    for s in sections:
        _coll(s)
    return tables


def _recompute_density(spec):
    """Плотность по ТЕКУЩИМ секциям spec (после сегментации/specimen) —
    иначе гейт сверяет шаблон с полным документом."""
    spec["density"] = {
        "screenshots_total": sum(_count_shots_subtree(s) for s in spec["sections"]),
        "business_logic_subfunctions": sum(_count_h3_subtree(s) for s in spec["sections"]),
        "tables": _collect_tables(spec["sections"]),
    }


def apply_elements(spec, elements, catalog_path, specimen=None,
                   spec_list=None):
    """Сегментация по каталогу: оставить в spec только запрошенные элементы.
    Универсально — признаки берутся из document-model.ru.yaml, не из кода:
    - title-page: title_block (+ страница/шрифты/колонтитулы), секции и TOC
      вырезаются;
    - toc: оглавление;
    - прочие: шаблоны заголовков — кавычки «...» из поля detection каталога;
      секция остаётся, если её заголовок или заголовок потомка совпадает
      хотя бы с одним шаблоном. Нет шаблонов → ошибка (не молчать).
    title-page не запрошен → title_block вырезается (объём = ровно
    запрошенное)."""
    import yaml
    with open(catalog_path, encoding="utf-8") as fh:
        cat = yaml.safe_load(fh)
    if isinstance(cat, dict):
        cat = cat.get("elements") or cat.get("catalog")
    entries = cat if isinstance(cat, list) else None
    if not entries:
        raise SystemExit("[extract_spec] неожидаемая структура каталога "
                         "(нужен список элементов)")
    by_id = {e["id"]: e for e in entries}
    unknown = [e for e in elements if e not in by_id]
    if specimen:
        unknown += [specimen] if specimen not in by_id else []
    if unknown:
        raise SystemExit(f"[extract_spec] нет в каталоге: {unknown}")
    not_sel = [e for e in elements + ([specimen] if specimen else [])
               if by_id[e].get("selectable") is False]
    if not_sel:
        raise SystemExit(
            f"[extract_spec] элементы {not_sel} — свойства документа/текста, "
            f"отдельно не выбираются (catalog selectable: false)")

    if "title-page" not in elements and not specimen:
        spec["title_block"] = []
    if "toc" in elements:
        spec["toc"]["present"] = True
    else:
        spec["toc"]["present"] = False

    if specimen:
        spec["sections"] = _specimen_sections(spec, specimen, by_id,
                                               spec_list)
        spec["title_block"] = []
        spec.pop("variations", None)
        spec["meta"]["specimen"] = specimen
    else:
        section_elems = [e for e in elements if e not in ("title-page", "toc")
                         and e not in _PAGE_LEVEL]
        if not section_elems:
            spec["sections"] = []
        else:
            pats = []
            for e in section_elems:
                d = by_id[e].get("detection") or ""
                pats += [p.strip().lower() for p in re.findall(r"«([^»]+)»", d)]
            if not pats:
                raise SystemExit(
                    f"[extract_spec] в detection каталога нет шаблонов заголовков "
                    f"для: {section_elems} — сегментация невозможна")

            def matches(title):
                t = re.sub(r"\[[^\]]*\]", "", title).strip().lower()
                return any(p in t for p in pats)

            def prune(node):
                kids = [k for k in (prune(c) for c in node["children"]) if k]
                if matches(node["title"]) or kids:
                    n = dict(node)
                    n["children"] = kids
                    return n
                return None

            spec["sections"] = [s for s in (prune(s) for s in spec["sections"]) if s]
            if not spec["sections"]:
                print(f"[extract_spec] ПРЕДУПРЕЖДЕНИЕ: элементы {section_elems} "
                      f"не найдены в образцах по шаблонам каталога — шаблон "
                      f"будет пустым", file=sys.stderr)
            spec.pop("variations", None)  # правило большинства к выборке неприменимо
    _apply_page_elements(spec, elements)
    _recompute_density(spec)

    spec["meta"]["elements"] = elements
    spec["meta"]["pii_mode"] = _PII_MODE
    spec["meta"]["catalog"] = os.path.basename(catalog_path)
    # naming-and-emphasis-universal: конвенция имён из выгрузки cfe
    spec["meta"]["naming"] = _derive_naming(_CONFIG_PATHS)
    return spec


def main():
    global _PII_MODE
    ap = argparse.ArgumentParser()
    ap.add_argument("sample", nargs="?", help="путь к образцу DOCX")
    ap.add_argument("--folder", help="папка с образцами (присутствие = большинство)")
    ap.add_argument("--majority-ratio", type=float, default=0.75,
                    help="порог присутствия раздела (0.75 = 3 из 4)")
    ap.add_argument("--elements", help="только эти элементы каталога "
                    "(id через запятую, напр. title-page; сегментация — "
                    "по detection из document-model.ru.yaml)")
    ap.add_argument("--specimen", help="лист-образец одного внутритекстового "
                    "элемента (класс C: figure, table, bulleted-list, "
                    "note-block, heading...)")
    ap.add_argument("--synonyms", default=None,
                    help="spec_synonyms.json (T3b): {'merge': {B: A}, "
                         "'insufficient': [[A, B]]} — подтверждённые LLM/"
                         "пользователем слияния; повторный прогон читает "
                         "файл, без повторных LLM-вызовов")
    ap.add_argument("--config", action="append", default=[],
                    help="выгрузка 1С «метка=путь» (ext|main); расширение ПЕРВЫМ — источник конвенции имён")
    ap.add_argument("--pii", choices=["sanitize", "keep"], default="sanitize",
                    help="персональные данные: sanitize — вымышленные примеры "
                    "и логотипы-заглушки (по умолчанию); keep — копировать "
                    "реальные данные и логотипы")
    ap.add_argument("--catalog", help="путь к document-model.ru.yaml "
                    "(по умолчанию — поиск рядом со скриптом и в скилле)")
    ap.add_argument("-o", "--out", default="spec.json")
    args = ap.parse_args()
    _PII_MODE = args.pii
    global _CONFIG_PATHS
    _CONFIG_PATHS = _config_arg_paths(args.config)

    if args.folder:
        files = sorted(glob.glob(os.path.join(args.folder, "*.docx")))
        files = [f for f in files if not os.path.basename(f).startswith("~$")]
        if not files:
            ap.error(f"в папке {args.folder} нет образцов DOCX")
        specs = [extract_one(f) for f in files]
        print(f"[extract_spec] образцов: {len(files)} "
              f"(присутствие = большинство >= {args.majority_ratio})", file=sys.stderr)
        _syn = None
        if args.synonyms and os.path.isfile(args.synonyms):
            with open(args.synonyms, encoding="utf-8") as _fh:
                _syn = json.load(_fh)
            print(f"[extract_spec] synonyms: {args.synonyms} "
                  f"(merge: {len(_syn.get('merge') or {})}, "
                  f"insufficient: {len(_syn.get('insufficient') or [])})",
                  file=sys.stderr)
        spec = intersect_specs(specs, majority_ratio=args.majority_ratio,
                               synonyms=_syn)
        spec["meta"]["samples_dir"] = os.path.abspath(args.folder)
        spec["meta"]["majority_ratio"] = args.majority_ratio
        spec["meta"]["samples"] = [os.path.basename(f) for f in files]
        spec["meta"]["language"] = _detect_language(files)
        _apply_lang(spec)
    elif args.sample:
        spec = extract_one(args.sample)
        spec["meta"]["sample_path"] = os.path.abspath(args.sample)
        spec["meta"]["language"] = _detect_language([args.sample])
        _apply_lang(spec)
    else:
        ap.error("нужен sample или --folder")

    # naming-and-emphasis-universal: конвенция выделения сообщений —
    # мажорита по образцам; нет шаблона → None (маркер [СООБЩЕНИЕ: …]
    # запрещён G18 линта)
    _vals = [((s.get("meta") or {}).get("message_emphasis"))
             for s in (specs if args.folder else [spec])]
    _nonull = [v for v in _vals if v]
    if _nonull and len(_nonull) * 2 >= len(_vals):
        spec.setdefault("meta", {})["message_emphasis"] = {
            "italic": sum(1 for v in _nonull if v.get("italic")) * 2 >= len(_nonull),
            "color": next((c for c in (v.get("color") for v in _nonull) if c), None),
        }
    else:
        spec.setdefault("meta", {})["message_emphasis"] = None

    if args.elements:
        cat = _find_catalog(args.catalog)
        if cat is None:
            ap.error("document-model.ru.yaml не найден (--catalog или TZ_CATALOG)")
        spec = apply_elements(
            spec, [e.strip() for e in args.elements.split(",") if e.strip()], cat,
            specimen=args.specimen)
        print(f"[extract_spec] элементы: {args.elements} "
              f"(pii={_PII_MODE})", file=sys.stderr)
    elif args.specimen:
        cat = _find_catalog(args.catalog)
        if cat is None:
            ap.error("document-model.ru.yaml не найден (--catalog или TZ_CATALOG)")
        spec = apply_elements(spec, [], cat, specimen=args.specimen,
                              spec_list=specs if args.folder else None)
        print(f"[extract_spec] specimen: {args.specimen} "
              f"(pii={_PII_MODE})", file=sys.stderr)

    spec.setdefault("meta", {})["pii_mode"] = _PII_MODE

    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    def _strip_el(o):
        """Служебные XML-ссылки в JSON не попадают (прежде падал
        одиночный режим — режим --folder вычищал их пересечением, E-50)."""
        if isinstance(o, dict):
            return {k: _strip_el(v) for k, v in o.items()
                    if k not in ("_el", "_heading_el")}
        if isinstance(o, list):
            return [_strip_el(v) for v in o]
        return o

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(_strip_el(spec), fh, ensure_ascii=False, indent=2)
    d = spec["density"]
    print(f"[extract_spec] spec.json -> {args.out}", file=sys.stderr)
    print(f"[extract_spec] плотность: {d['screenshots_total']} скриншотов, "
          f"{d['business_logic_subfunctions']} подфункций, {len(d['tables'])} таблиц", file=sys.stderr)


_EXAMPLE_TOKEN_RE = re.compile(r"\[[^\[\]|]+\|\s*пример:\s*([^\]]+)\]")
_ORG_RE = re.compile(r"(ООО|АО|ПАО|ЗАО|ОАО|ИП)\s*«([^»]*)»", re.I)
_SIG_FIO_RE = re.compile(r"^_{2,}\s*/\s*(.+?)\s*/\s*$")
_SIG_YEAR_RE = re.compile(r"^(«_+»\s*_+)\s*(\d{4})\s*г", re.S)


def _sig_placeholder(cell, side):
    """Плейсхолдер ячейки блока подписей по СТРУКТУРЕ строки, без имён из
    образца. side: «ЗАКАЗЧИКА»/«ИСПОЛНИТЕЛЯ» — по колонке (0 — заказчик,
    1 — исполнитель)."""
    m = _ORG_RE.search(cell)
    if m:
        return (f"{m.group(1)} «[НАИМЕНОВАНИЕ {side} "
                f"| пример: {_sanitize_example(m.group(2))}]»")
    m = _SIG_FIO_RE.match(cell)
    if m:
        return f"________ / [ФИО {side} | пример: {_sanitize_example(m.group(1))}] /"
    m = _SIG_YEAR_RE.match(cell)
    if m:
        return f"{m.group(1)} [ГОД | пример: {m.group(2)}] г."
    return cell


def _title_sig_rows(doc, el):
    """Строки блока подписей из таблицы титульного листа. Подписи живут в
    ВОЛОЖЕННЫХ таблицах внутри ячеек (cell.text их не показывает).
    Строка на всю ширину (gridSpan-объединение: «Генеральный директор»,
    заголовок «ЗАКАЗЧИК») после дедупа соседей даёт ОДНУ ячейку — такая
    непустая строка трактуется как объединённая пара [текст, текст].
    Возвращает ({rows, widths} | None): rows = [[лево, право], ...],
    widths = ширины колонок вложенной таблицы (twips)."""
    from docx.table import Table

    rows = []
    widths = []
    bolds_all = []
    heights = []
    tbl_props = {}  # tblW + поля ячеек первой таблицы с данными

    def _grab_props(tbl):
        """Ширина таблицы и поля ячеек — из tblPr образца (данные,
        не константы: у другого заказчика геометрия своя)."""
        pr = tbl._tbl.find(qn('w:tblPr'))
        if pr is None:
            return
        tw = pr.find(qn('w:tblW'))
        if tw is not None and tw.get(qn('w:type')) == 'dxa':
            tbl_props["w"] = int(tw.get(qn('w:w')))
        mar = pr.find(qn('w:tblCellMar'))
        if mar is not None:
            for tag, key in (("left", "mar_l"), ("right", "mar_r")):
                el = mar.find(qn('w:' + tag))
                if el is not None:
                    tbl_props[key] = int(el.get(qn('w:w')))

    def _row_height(r):
        trPr = r._tr.find(qn('w:trPr'))
        if trPr is None:
            return None
        th = trPr.find(qn('w:trHeight'))
        return int(th.get(qn('w:val'))) if th is not None else None

    def _logical_widths(tbl):
        """Ширины ЛОГИЧЕСКИХ колонок (twips) таблицы подписей: gridCol
        группируются по уникальным tc первой строки с >=2 уникальными
        ячейками (gridSpan-объединения суммируются)."""
        g = [int(x.get(qn("w:w")))
             for x in tbl._tbl.findall(qn("w:tblGrid") + "/" + qn("w:gridCol"))]
        if len(g) < 2:
            return None
        for r in tbl.rows:
            seen = []
            for c in r.cells:
                if not seen or id(seen[-1]._tc) != id(c._tc):
                    seen.append(c)
            if len(seen) >= 2:
                out, i = [], 0
                for c in seen:
                    span = getattr(c, "grid_span", 1) or 1
                    out.append(sum(g[i:i + span]))
                    i += span
                if len(out) >= 2 and all(out):
                    return out[:2]
        return None

    def _collect(tbl):
        nonlocal widths
        t_el = tbl._tbl

        def _run_bold(rr):
            """Прямая жирность рана (как в абзацах титула): w:b есть и
            val не «0/false». Жирность из стиля не ловим — та же
            семантика, что у абзацев title_block."""
            rPr = rr._element.find(qn('w:rPr'))
            if rPr is None:
                return False
            b = rPr.find(qn('w:b'))
            if b is None:
                return False
            return b.get(qn('w:val')) not in ("0", "false", "none")

        def _cell_bold(c):
            runs = [rr for p in c.paragraphs for rr in p.runs
                    if rr.text.strip()]
            return bool(runs) and all(_run_bold(rr) for rr in runs)

        def _cell_full_text(c):
            """Текст ячейки ВКЛЮЧАЯ вложенные таблицы (Б3: c.text
            python-docx вложенные таблицы не читает — текст шапки
            «Техническое задание / на разработку…» терялся). Тексты
            ячеек вложенных таблиц — с новой строки, в порядке документа,
            рекурсивно."""
            parts = [p.text for p in c.paragraphs if p.text.strip()]
            for nt in c.tables:
                for nr in nt.rows:
                    for nc in nr.cells:
                        sub = _cell_full_text(nc)
                        if sub.strip():
                            parts.append(sub)
            return "\n".join(parts)

        for r in tbl.rows:
            # горизонтально объединённые ячейки дублируются — дедуп соседей
            # (текст + жирность ячейки — жирность нужна в шаблоне: ЗАКАЗЧИК)
            raw = []
            for c in r.cells:
                raw.append((_cell_full_text(c).strip(), _cell_bold(c)))
            cells = []
            for tb in raw:
                if not cells or cells[-1][0] != tb[0]:
                    cells.append(tb)
            texts = [x[0] for x in cells]
            bolds = [x[1] for x in cells]
            if len(texts) >= 2 and any(texts):
                if not widths:
                    widths = _logical_widths(tbl) or []
                    _grab_props(tbl)
                rows.append(texts[:2])
                bolds_all.append(bolds[:2])
                heights.append(_row_height(r))
            elif texts and not any(texts):
                # пустая строка: спуск во вложенные таблицы прежде всего
                nested = [nt for c in r.cells for nt in c.tables]
                if nested:
                    for nt in nested:
                        _collect(nt)
                else:
                    # ПУСТАЯ строка-отступ — часть вертикального ритма
                    # блока подписей (E-44)
                    if not widths:
                        widths = _logical_widths(tbl) or []
                        _grab_props(tbl)
                    rows.append(["", ""])
                    bolds_all.append([False, False])
                    heights.append(_row_height(r))
            elif len(texts) == 1 and texts[0]:
                # объединённая на всю ширину строка (должность подписанта,
                # общий заголовок) — одна логическая пара
                if not widths:
                    widths = _logical_widths(tbl) or []
                    _grab_props(tbl)
                rows.append([texts[0], texts[0]])
                bolds_all.append([bolds[0], bolds[0]])
                heights.append(_row_height(r))
            else:
                for c in r.cells:
                    for nt in c.tables:
                        _collect(nt)

    _collect(Table(el, doc))
    if len(rows) < 4:
        return None

    out = []
    out_bold = []
    prev = None
    for i, row in enumerate(rows):
        pair = [
            _sig_placeholder(row[0], "ЗАКАЗЧИКА"),
            _sig_placeholder(row[1], "ИСПОЛНИТЕЛЯ") if len(row) > 1 else "",
        ]
        if pair == prev and pair != ["", ""]:
            # вложенные таблицы могут дублировать строки; подряд идущие
            # ПУСТЫЕ не склеивать — это отступы (E-44)
            continue
        out.append(pair)
        out_bold.append(bolds_all[i] if i < len(bolds_all)
                        else [False, False])
        prev = pair
    if not out:
        return None
    res = {"rows": out, "bolds": out_bold, "widths": widths or None}
    if tbl_props:
        res["tbl_props"] = tbl_props
    if any(h for h in heights):
        res["heights"] = heights
    return res


def _tbl_grids(part):
    """Ширины колонок (twips) каждой таблицы части колонтитула."""
    grids = []
    for t in part.tables:
        grids.append([int(g.get(qn("w:w")))
                      for g in t._tbl.findall(qn("w:tblGrid") + "/" + qn("w:gridCol"))])
    return grids


def _hf_items(part):
    """Элементы верхнего уровня части колонтитула: ('p', el) / ('tbl', el),
    ВКЛЮЧАЯ содержимое <w:sdt> (подвал образцов тех-ТЗ обёрнут в sdt
    «Page Numbers»; part.tables/part.paragraphs python-docx его не видят).
    Дедупликация не нужна: sdt ЗАМЕНЯЕТ элементы, а не дублирует."""
    items = []

    def walk(el):
        for ch in el.iterchildren():
            if ch.tag == qn("w:p"):
                items.append(("p", ch))
            elif ch.tag == qn("w:tbl"):
                items.append(("tbl", ch))
            elif ch.tag == qn("w:sdt"):
                cont = ch.find(qn("w:sdtContent"))
                if cont is not None:
                    walk(cont)

    walk(part._element)
    return items


def extract_header_footer(sec):
    """Колонтитулы референса: таблицы — ячейками, абзацы — списком.
    Тексты прогоняются через плейсхолдеры (организации/даты → токены,
    примеры санитизируются) — реальные данные образца не протекают в spec.
    Геометрия (ширины колонок tblGrid) фиксируется параметром grids.
    Поля PAGE/NUMPAGES в тексте ячеек не видны (docx отдаёт кэш значения),
    поэтому факт их наличия фиксируется отдельно маркером [PAGE]/[NUMPAGES]
    на этапе build. None, если колонтитул пуст."""
    def _imgs_of(part):
        """Картинки части колонтитула (логотипы): sanitize → заглушки,
        keep → блобы. None, если картинок нет."""
        blips = part._element.findall('.//' + qn('a:blip'))
        if not blips:
            return None
        imgs, extents = [], []
        for b in blips:
            embed = b.get(qn('r:embed'))
            imgs.append(base64.b64encode(part.part.related_parts[embed].blob).decode())
        for e in part._element.findall('.//' + qn('wp:extent')):
            extents.append((e.get('cx'), e.get('cy')))
        if _PII_MODE == "sanitize":
            return {"placeholder": True, "extents": extents}
        return {"blobs": imgs, "extents": extents}

    def grab(part):
        cells = []
        rich = []
        # таблицы и абзацы ВКЛЮЧАЯ <w:sdt> (Б1: подвал «Page Numbers»)
        items = _hf_items(part)
        tbls = [Table(el, part) for kind, el in items if kind == "tbl"]
        for t in tbls:
            for r in t.rows:
                cells.append([to_placeholder(c.text.strip())[0] or c.text.strip()
                              for c in r.cells])
                # жирность по АБЗАЦАМ колонтитула (Прогон #7: строки
                # «Техническое задание…» — целиком жирные/нежирные);
                # [текст абзаца, bold] — bold, если все непустые run жирные
                cell_rich = []
                for c in r.cells:
                    para_rich = []
                    for para in c.paragraphs:
                        txt = para.text.strip()
                        if not txt:
                            continue
                        bolds = [r.font.bold for r in para.runs
                                 if r.text.strip()]
                        para_rich.append([txt, bool(bolds) and all(bolds)])
                    cell_rich.append(para_rich)
                rich.append(cell_rich)
        paras = [to_placeholder(Paragraph(el, part).text.strip())[0]
                 for kind, el in items if kind == "p"
                 if Paragraph(el, part).text.strip()]
        grids = _tbl_grids(part)
        if not cells and not paras and not grids:
            return None
        out = {"cells": cells, "paras": paras}
        if any(any(seg for seg in cr) and any(b for segs in cr for _, b in segs)
               for cr in rich):
            out["cells_rich"] = rich
        if grids:
            out["grids"] = grids
        # поля Word в колонтитуле (PAGE/NUMPAGES/...) — параметр spec
        fields = sorted({(it.text or "").strip().split()[0]
                         for it in part._element.findall('.//' + qn('w:instrText'))
                         if (it.text or "").strip()})
        if fields:
            out["fields"] = fields
        try:
            imgs = _imgs_of(part)
            if imgs:
                out["images"] = imgs
        except Exception:
            pass
        return out

    out = {}
    for name in ("header", "footer"):
        try:
            out[name] = grab(getattr(sec, name))
        except Exception:
            out[name] = None
    # титульный колонтитул: та же таблица логотипов (лево/право), текста нет
    try:
        fpg = _tbl_grids(sec.first_page_header)
        if fpg:
            out["first_page"] = {"grids": fpg}
    except Exception:
        pass
    # логотипы титульного листа (first page header). sanitize → не копировать
    # реальные изображения (ПДн организации), фиксировать позиции заглушками;
    # keep → копировать как есть
    try:
        imgs = _imgs_of(sec.first_page_header)
        if imgs:
            out['first_page_images'] = imgs
    except Exception:
        pass
    return out


def _run_has_b(r_el):
    """У рана есть явный w:b (жирность; val не проверяем — в таблицах
    тела важен сам признак)."""
    rPr = r_el.find(qn('w:rPr'))
    return rPr is not None and rPr.find(qn('w:b')) is not None


def _table_col_bold(t):
    """Жирность по колонкам таблицы тела (данные образца, не константа):
    колонка «жирная», если в БОЛЬШИНСТВЕ её непустых ячеек данных все
    раны жирные (в таблице тестирования колонка роли — жирная, у
    результата — нет). Пустые/заголовочные ячейки не учитываются."""
    out = []
    for j in range(len(t.columns)):
        nonempty = bold = 0
        for row in t.rows[1:]:
            if j >= len(row.cells):
                continue
            cell = row.cells[j]
            if not cell.text.strip():
                continue
            nonempty += 1
            runs = [r for p in cell.paragraphs for r in p.runs
                    if r.text.strip()]
            bold += bool(runs) and all(_run_has_b(r._element) for r in runs)
        out.append(bool(nonempty) and bold >= 0.5 * nonempty)
    return out


def _table_col_lead(t):
    """Жирный ПРЕФИКС-роль в колонке (данные образца): колонка помечена,
    если в большинстве непустых ячеек данных текст начинается жирным
    раном и продолжается нежирным (в таблице тестирования «Кладовщик
    производства. Нажать…» — жирна только роль с точкой)."""
    out = []
    for j in range(len(t.columns)):
        nonempty = lead = 0
        for row in t.rows[1:]:
            if j >= len(row.cells):
                continue
            cell = row.cells[j]
            if not cell.text.strip():
                continue
            nonempty += 1
            runs = [r for p in cell.paragraphs for r in p.runs
                    if r.text.strip()]
            if len(runs) < 2:
                continue

            first_b = _run_has_b(runs[0]._element)
            has_nonbold_after = any(not _run_has_b(r._element) for r in runs[1:])
            lead += bool(first_b and has_nonbold_after)
        out.append(bool(nonempty) and lead >= 0.5 * nonempty)
    return out


def _style_el_by_id(doc, st_id):
    """w:style по style_id напрямую из XML (doc.styles[st_id] устарел)."""
    if not st_id:
        return None
    for el in doc.styles.element.findall(qn('w:style')):
        if el.get(qn('w:styleId')) == st_id:
            return el
    return None


def _style_xml_name(doc, st_id):
    """Имя стиля (w:name) по style_id, '' если не найден."""
    el = _style_el_by_id(doc, st_id)
    if el is None:
        return ''
    name = el.find(qn('w:name'))
    return name.get(qn('w:val')) if name is not None else ''


def _style_xml_size(doc, st_id):
    """Кегль стиля (w:rPr/w:sz) по style_id, в pt или None."""
    el = _style_el_by_id(doc, st_id)
    if el is None:
        return None
    sz = el.find(f'{qn("w:rPr")}/{qn("w:sz")}')
    if sz is None:
        return None
    try:
        return int(sz.get(qn('w:val'))) / 2
    except (TypeError, ValueError):
        return None


def _para_spacing(el):
    """Абзацные параметры титула из образца (данные, не константы):
    space_before/after, first_line_indent (pt, может быть отрицательным —
    висячий отступ-центровка строк шапки)."""
    pPr = el.find(qn('w:pPr'))
    out = {}
    if pPr is None:
        return out
    for tag, key in (("w:spacing", "spacing"), ("w:ind", "ind")):
        el2 = pPr.find(qn(tag))
        if el2 is None:
            continue
        for a, k in (("before", "sb"), ("after", "sa")):
            if tag == "w:spacing" and el2.get(qn('w:' + a)):
                out[key + a] = int(el2.get(qn('w:' + a))) / 20
        if tag == "w:ind" and el2.get(qn('w:firstLine')):
            out["fli"] = int(el2.get(qn('w:firstLine'))) / 20
        if tag == "w:ind" and el2.get(qn('w:hanging')):
            out["fli"] = -int(el2.get(qn('w:hanging'))) / 20
    return out


def _build_title_block(doc, blocks):
    """Титульный блок: абзацы/таблицы до первого заголовка уровня 1.
    Возвращает (title_block, индекс первого H1)."""
    first_h1 = None
    for i, b in enumerate(blocks):
        if b["type"] == "heading" and b["level"] == 1:
            first_h1 = i
            break
    if first_h1 is None:
        first_h1 = len(blocks)

    title_block = []
    for b in blocks[:first_h1]:
        child_el = b.get("_el")
        sp = _para_spacing(child_el)
        if b["type"] == "spacer":
            # пустой абзац-разделитель — часть вертикального ритма титульника
            title_block.append({"text": "", "placeholder": [],
                                "bold": False, "caps": False, "size_pt": None,
                                "spacing": sp})
        elif b["type"] == "paragraph":
            # опечатки исходных образцов НЕ исправляются молча (универсальность):
            # текст переносится как есть
            t, ph = to_placeholder(b["text"])
            runs = [r for r in child_el.findall('.//' + qn('w:r')) if r.find(qn('w:t')) is not None]
            bold = bool(runs) and all(
                (r.find('.//' + qn('w:b')) is not None) for r in runs)
            caps = 'w:caps' in child_el.xml
            size = None
            sz = child_el.find('.//' + qn('w:sz'))
            if sz is not None:
                size = int(sz.get(qn('w:val'))) / 2
            item = {"text": t, "placeholder": ph,
                    "bold": bold, "caps": caps, "size_pt": size,
                    "spacing": sp}
            if ph:
                # пример = отрендеренная строка ЦЕЛИКОМ («ВЕРСИЯ: 2», а не «2»):
                # токены плейсхолдеров заменяются их примерами
                item["example_line"] = _EXAMPLE_TOKEN_RE.sub(
                    lambda m: m.group(1), t)
            title_block.append(item)
        elif b["type"] == "table":
            sig = _title_sig_rows(doc, child_el)
            if sig:
                item = {"sig_rows": sig["rows"]}
                if sig.get("widths"):
                    item["sig_widths"] = sig["widths"]
                if sig.get("bolds"):
                    item["sig_bold"] = sig["bolds"]
                if sig.get("tbl_props"):
                    item["sig_tbl"] = sig["tbl_props"]
                if sig.get("heights"):
                    item["sig_heights"] = sig["heights"]
                title_block.append(item)
    return title_block, first_h1


def _build_sections(blocks, first_h1):
    """Дерево секций из блоков после титула. Заголовок плейсхолдеризуется:
    конкретика образца (код ТЗ и т.п.) не должна попадать в шаблон."""
    sections = []  # список секций уровня 1
    stack = []  # стек (section, level)
    for b in blocks[first_h1:]:
        if b["type"] == "heading":
            lvl = b["level"]
            t, ph = to_placeholder(b["text"])
            node = {"level": lvl, "title": t, "placeholder": ph,
                    "_heading_el": b["_el"],
                    "body": [], "children": []}
            # поднимемся до родителя
            while stack and stack[-1]["level"] >= lvl:
                stack.pop()
            if stack:
                stack[-1]["children"].append(node)
            else:
                sections.append(node)
            stack.append(node)
        else:
            target = stack[-1] if stack else None
            if target is None:
                # блок до первой секции (не должен быть)
                continue
            if b["type"] == "table":
                target["body"].append({
                    "type": "table",
                    "columns": b["columns"],
                    "rows": b["rows"],
                    "widths": b.get("widths"),
                    "example_row": b.get("example_row"),
                    "col_bold": b.get("col_bold"),
                    "col_lead": b.get("col_lead"),
                    "has_caption": b.get("has_caption"),
                    "header_repeat": True,
                })
            elif b["type"] == "image":
                target["body"].append({"type": "screenshot", "caption": None})
            elif b["type"] == "caption":
                # подпись скриншота: привязать к последнему screenshot
                for blk in reversed(target["body"]):
                    if blk["type"] == "screenshot" and blk["caption"] is None:
                        blk["caption"] = b["text"]
                        break
                else:
                    target["body"].append({"type": "caption", "text": b["text"],
                                           "size_pt": b.get("size_pt")})
            elif b["type"] == "list_item":
                # собрать последовательность list_item в один list
                if target["body"] and target["body"][-1].get("type") == "list":
                    target["body"][-1]["items"].append(b["text"])
                else:
                    target["body"].append({"type": "list", "items": [b["text"]],
                                           "fmt": b.get("fmt")})
            elif b["type"] == "paragraph":
                t, ph = to_placeholder(b["text"])
                target["body"].append({"type": "paragraph", "text": t,
                                       "placeholder": ph, "action": b.get("action", False)})
    return sections


def _first_para(node):
    """Первый абзац раздела (в глубину) — источник подсказки."""
    for blk in node["body"]:
        if blk["type"] == "paragraph":
            return blk["text"]
    for c in node["children"]:
        t = _first_para(c)
        if t:
            return t
    return None


def _add_hints(sections):
    """Подсказки (п.4): из образца — первый абзац раздела (с плейсхолдерами);
    fallback — общая по названию. hint_src — исходник для пересечения."""

    def _walk(node):
        node["hint_src"] = _first_para(node)
        node["hint"] = _hint_from_src(node["hint_src"], node)
        for c in node["children"]:
            _walk(c)

    for s in sections:
        _walk(s)


def _heading_colors(blocks, styles):
    """Эффективный цвет заголовка — из прогонов текста (визуальный), а не из
    определения стиля: у образцов стиль Heading 3 несёт 243F60, но рендер
    чёрный (цвет перекрыт). Прогон без явного цвета → None (чёрный)."""
    run_colors = {1: Counter(), 2: Counter(), 3: Counter()}
    for blk in blocks:
        if blk["type"] != "heading":
            continue
        for r in blk["_el"].findall('.//' + qn('w:r')):
            t = r.find(qn('w:t'))
            if t is None or not (t.text or "").strip():
                continue
            c = r.find('.//' + qn('w:color'))
            val = c.get(qn('w:val')) if c is not None else None
            if val not in (None, "auto"):
                run_colors[blk["level"]][val] += 1
            else:
                run_colors[blk["level"]]["<none>"] += 1
    for lvl, cnt in run_colors.items():
        if cnt:
            top, n = cnt.most_common(1)[0]
            if top == "<none>" or n < sum(cnt.values()) / 2:
                styles[f"heading_{lvl}"]["color"] = None  # визуально чёрный
            else:
                styles[f"heading_{lvl}"]["color"] = top


def _detect_toc(doc, body):
    """TOC (параметр spec): поле оглавления в теле образца + заголовок
    оглавления (стиль TOC Heading или текст «Оглавление/Содержание»);
    кегль — run → стиль → docDefaults (Прогон #7: TOC Heading 16pt)."""
    toc_instr = None
    for it in body.findall('.//' + qn('w:instrText')):
        t = (it.text or "").strip()
        if t.upper().startswith("TOC"):
            toc_instr = t
            break
    toc_title, toc_title_size = None, None
    for p_el in doc.element.body.findall('.//' + qn('w:p')):
        txt = ''.join(t.text or '' for t in p_el.findall('.//' + qn('w:t'))).strip()
        pstyle = p_el.find('.//' + qn('w:pStyle'))
        st_id = pstyle.get(qn('w:val')) if pstyle is not None else ''
        st_name = _style_xml_name(doc, st_id)
        if txt and (st_id.lower() == 'tocheading' or 'toc heading' in st_name.lower()
                    or txt.lower() in ('оглавление', 'содержание')):
            toc_title = txt
            szs = [int(x.get(qn('w:val'))) for x in p_el.findall('.//' + qn('w:sz'))
                   if x.get(qn('w:val'))]
            if szs:
                toc_title_size = szs[0] / 2
            else:
                sz2 = _style_xml_size(doc, st_id)
                if sz2:
                    toc_title_size = sz2
            break
    return {
        "present": True,  # v6: оглавление в шаблоне всегда (требование вёрстки)
        "instr": toc_instr or TOC_DEFAULT_INSTR,
        "in_source": toc_instr is not None,
        "title": toc_title or "Оглавление",
        "title_size_pt": toc_title_size,
    }


def _set_page_breaks(sections):
    """Разрыв страницы перед разделом — из образца, пофаздельно.
    page_break=True: заголовок в образце начинается с новой страницы
    (Прогон #9: «Источники → Глоссарий → Задание» идут подряд)."""

    def _walk(node):
        node["page_break"] = _has_page_break(node.get("_heading_el"))
        for c in node.get("children", []):
            _walk(c)

    for s in sections:
        _walk(s)


def _density_of(sections):
    """Плотность по дереву секций (счётчики общие с _recompute_density)."""
    return {
        "screenshots_total": sum(_count_shots_subtree(s) for s in sections),
        "business_logic_subfunctions": sum(_count_h3_subtree(s) for s in sections),
        "tables": _collect_tables(sections),
    }


def _paragraph_rhythm(doc, blocks):
    """Абзац тела: отступ первой строки и выравнивание (визуальный ритм)."""
    ind_c, al_c = Counter(), Counter()
    try:
        nst = doc.styles["Normal"]
        nind = nst.element.find(qn("w:pPr") + "/" + qn("w:ind"))
    except Exception:
        nind = None
    base_ind = nind.get(qn("w:firstLine")) if nind is not None else None
    for blk in blocks:
        if blk["type"] not in ("paragraph", "list_item"):
            continue
        pPr = blk["_el"].find(qn("w:pPr"))
        ind = pPr.find(qn("w:ind")) if pPr is not None else None
        ind_c[ind.get(qn("w:firstLine")) if ind is not None else base_ind] += 1
        jc = pPr.find(qn("w:jc")) if pPr is not None else None
        al_c[jc.get(qn("w:val")) if jc is not None else "left"] += 1
    top_ind, n_ind = ind_c.most_common(1)[0] if ind_c else (None, 0)
    top_al, n_al = al_c.most_common(1)[0] if al_c else ("left", 0)
    return {
        "first_line_indent": int(top_ind) if top_ind and n_ind >= len(ind_c) // 2 + 1 and top_ind not in ("0", None) else None,
        "align": top_al if n_al >= len(al_c) // 2 + 1 and top_al != "left" else None,
        "note": "отступ первой строки и выравнивание абзацев тела (визуальный ритм образца)",
    }


def extract_one(sample):
    """Извлечь spec из одного образца DOCX (структура + плотность + оформление)."""
    doc = Document(sample)
    _scan_sensitive(doc)  # динамическая санитизация: реальные данные → вымышленные

    # --- страница ---
    sec = doc.sections[0]
    header_footer = extract_header_footer(sec)
    page = {
        "width_emu": sec.page_width,
        "height_emu": sec.page_height,
        "margin_left_emu": sec.left_margin,
        "margin_right_emu": sec.right_margin,
        "margin_top_emu": sec.top_margin,
        "margin_bottom_emu": sec.bottom_margin,
        "header_distance_emu": sec.header_distance,
        "footer_distance_emu": sec.footer_distance,
    }

    # --- шрифт по умолчанию (имя и размер — из docDefaults, не из кода) ---
    fonts = {"default_ascii": "Times New Roman", "default_size_pt": 12}
    try:
        styles_el = doc.styles.element
        dd = styles_el.find(qn("w:docDefaults"))
        if dd is not None:
            rf = dd.find(".//" + qn("w:rFonts"))
            if rf is not None:
                fonts["default_ascii"] = rf.get(qn("w:ascii")) or fonts["default_ascii"]
            szel = dd.find(".//" + qn("w:sz"))
            if szel is not None and szel.get(qn("w:val")):
                fonts["default_size_pt"] = int(szel.get(qn("w:val"))) / 2
            lg = dd.find(".//" + qn("w:lang"))
            if lg is not None and lg.get(qn("w:val")):
                fonts["lang"] = lg.get(qn("w:val"))
    except Exception:
        pass

    # E-60: фактический шрифт ТЕЛА — голосование по ЯВНЫМ прогонам
    # (rFonts/sz в run'ах абзацев тела). docDefaults может не совпадать
    # с реальным набором (ЧЭАЗ: docDefaults иной, тело Cambria 12) —
    # рендер «по умолчанию» тогда даёт чужой шрифт другого проекта.
    try:
        from collections import Counter as _Counter
        _f_cnt, _s_cnt = _Counter(), _Counter()
        for _p in doc.paragraphs:
            _st = (_p.style.name if _p.style else "")
            if _st.startswith("Heading") or _st in ("Title", "Caption"):
                continue
            if len(_p.text.strip()) < 20:
                continue
            for _r in _p.runs:
                _rPr = _r._element.find(qn("w:rPr"))
                if _rPr is None:
                    continue
                _rf = _rPr.find(qn("w:rFonts"))
                if _rf is not None and _rf.get(qn("w:ascii")):
                    _f_cnt[_rf.get(qn("w:ascii"))] += 1
                _sz = _rPr.find(qn("w:sz"))
                if _sz is not None and _sz.get(qn("w:val")):
                    _s_cnt[int(_sz.get(qn("w:val"))) / 2] += 1
        if _f_cnt and _f_cnt.most_common(1)[0][1] >= 5:
            fonts["default_ascii"] = _f_cnt.most_common(1)[0][0]
        if _s_cnt and _s_cnt.most_common(1)[0][1] >= 5:
            fonts["default_size_pt"] = _s_cnt.most_common(1)[0][0]
    except Exception:
        pass

    # --- нумерация ---
    numbering = extract_numbering(doc)
    numfmts = numfmt_map(doc)
    # --- автодетект стилей заголовков/капшенов по реальному использованию ---
    det_head, det_cap = autodetect_styles(doc, numfmts)
    # наборы стилей ЛОКАЛЬНЫ для этого образца: глобальные fallback-наборы
    # не мутируются, чтобы детекты одного образца не влияли на разбор
    # соседних (режим --folder обрабатывает образцы в одном процессе)
    head_styles = {lvl: set(names) for lvl, names in HEADING_STYLES.items()}
    for _lvl, _s in det_head.items():
        head_styles.setdefault(_lvl, set()).add(_s)
    cap_styles = set(CAPTION_STYLES) | set(det_cap)

    # --- стили заголовков/капшенов (приоритет — обнаруженный стиль, не захардкоженные имена) ---
    def _hfont(lvl):
        if lvl in det_head:
            return style_font(doc, det_head[lvl])
        # фолбэк — детерминированный: каноничное имя первым, остальные
        # алиасы по алфавиту (set → next(iter()) выбирал СЛУЧАЙНЫЙ стиль
        # при каждом запуске — spec «плавал» между прогонами, как det_cap)
        canon = f"Heading {lvl}"
        names = [canon] + sorted(HEADING_STYLES.get(lvl, set()) - {canon})
        return style_font(doc, names[0])
    styles = {
        "heading_1": _hfont(1),
        "heading_2": _hfont(2),
        "heading_3": _hfont(3),
        "caption": style_font(doc, det_cap[0] if det_cap else "Caption"),
    }

    # --- проходим тело по порядку ---
    body = doc.element.body

    # кегль подписей рисунков (det_cap — стили абзацев сразу после
    # изображения): мода размеров; уходит в screenshot_box (билдер
    # рендерит подпись-плейсхолдер этим кеглем, а не дефолтным 10)
    def _real_para_font_size_pt(par, _seen=None):
        for r in par.runs:
            if r.text.strip() and r.font.size:
                return r.font.size.pt
        st, seen = par.style, set()
        while st is not None and st.style_id not in seen:
            seen.add(st.style_id)
            try:
                if st.font.size:
                    return st.font.size.pt
            except Exception:
                pass
            st = st.base_style
        # фолбэк: docDefaults (10pt образцов живёт именно там, не в стиле)
        try:
            szel = styles_el.find(".//" + qn("w:docDefaults") + "/"
                                  + qn("w:rPrDefault") + "/" + qn("w:rPr")
                                  + "/" + qn("w:sz"))
            if szel is not None and szel.get(qn("w:val")):
                return int(szel.get(qn("w:val"))) / 2
        except Exception:
            pass
        return None

    fig_sizes = []
    for child in body.iterchildren():
        if child.tag != qn("w:p"):
            continue
        p = Paragraph(child, doc)
        if p.style.name in det_cap and p.text.strip():
            s = _real_para_font_size_pt(p)
            if s:
                fig_sizes.append(s)
    if fig_sizes:
        screenshot_box = {"caption_size_pt": Counter(fig_sizes).most_common(1)[0][0]}
    else:
        screenshot_box = None

    roles_found = set()
    glossary_terms = set()  # термины глоссарных таблиц образца (lint_draft: «выдумано?»)
    # blocks: плоский список блоков тела по порядку; "_el" — XML-элемент
    # абзаца/таблицы (нужен позже: цвета заголовков, разрывы, ритм)
    blocks = []
    tidx = 0
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            p = Paragraph(child, doc)
            style = p.style.name
            txt = p.text.strip()
            has_img = is_image_any(child)
            numid, ilvl = num_info(child)
            # заголовок: имя стиля ИЛИ numPr с decimal-форматом на ilvl (универсально)
            is_h = is_heading_para(style, numid, ilvl, numfmts, head_styles)
            lvl = detect_level(style, ilvl, head_styles) if is_h else None
            if has_img:
                blocks.append({"type": "image", "_el": child})
            elif lvl is not None and txt:
                # ЗАГОЛОВОК проверяется до капшена: подфункция, стоящая прямо
                # перед скриншотом, не должна превращаться в подпись
                blocks.append({"type": "heading", "level": lvl, "text": txt, "style": style, "_el": child})
            elif style in cap_styles and txt:
                blocks.append({"type": "caption", "text": txt, "_el": child,
                               "size_pt": _real_para_font_size_pt(p)})
            elif style in LIST_STYLES and txt:
                # формат списка (bullet/decimal) — для различения
                # маркированных и нумерованных списков (specimen)
                fmt = numfmts.get(numid, {}).get(int(ilvl)) \
                    if numid is not None and ilvl is not None and str(ilvl).isdigit() else None
                blocks.append({"type": "list_item", "text": txt, "_el": child,
                               "fmt": fmt})
            elif txt:
                blocks.append({"type": "paragraph", "text": txt,
                               "action": is_action_text(txt), "_el": child})
            else:
                # пустой абзац-разделитель: значим на титульнике (вертикальный
                # ритм); в теле секций игнорируется
                blocks.append({"type": "spacer", "_el": child})

        elif child.tag == qn("w:tbl"):
            t = Table(child, doc)
            # подпись «Таблица N …» перед таблицей есть не у всех таблиц
            # (в образцах — только глоссарий): признак
            # переносим, рендер без него подпись не вставляет (E-46)
            has_caption = any(
                b["type"] == "caption" and re.match(r"^Таблица\s*-?\s*\d",
                                                     b["text"].strip())
                for b in blocks[-2:] if b.get("type") == "caption")
            header = [c.text.strip() for c in t.rows[0].cells]
            widths = [int(g.get(qn("w:w")))
                      for g in child.findall(qn("w:tblGrid") + "/" + qn("w:gridCol"))]
            col_bold = _table_col_bold(t)
            col_lead = _table_col_lead(t)
            # словарь ролей: значения колонок «Роль»/«Должность» —
            # потом граница жирного префикса в таблице тестирования
            for _j, _h in enumerate(header):
                _hl = norm_title(_h)
                if "роль" in _hl or "должност" in _hl:
                    for _row in t.rows[1:]:
                        if _j < len(_row.cells):
                            _v = _row.cells[_j].text.strip()
                            if _v:
                                roles_found.add(_v)
            # термины глоссария: таблица с колонкой «Термин»/«Сокращение» —
            # первый столбец (lint_draft сверяет черновик с этими терминами, E-48)
            if {"термин", "сокращение"} & {norm_title(h) for h in header}:
                for _row in t.rows[1:]:
                    _v = _row.cells[0].text.strip() if _row.cells else ""
                    if _v:
                        glossary_terms.add(_v)
            # пример первой строки данных: репрезентативное заполнение из
            # образца (плейсхолдеры с примерами, ПДн санитизируются) —
            # попадает в шаблон серым курсивом, остальные строки пустые
            example_row = None
            if len(t.rows) > 1:
                cells = [to_placeholder(c.text.strip())[0] for c in t.rows[1].cells]
                if any(cells):
                    example_row = cells
            blocks.append({
                "type": "table",
                "columns": header,
                "rows": len(t.rows),  # включая строку заголовка
                "cols": len(t.columns),
                "widths": widths,
                "example_row": example_row,
                "col_bold": col_bold,
                "col_lead": col_lead,
                "has_caption": has_caption,
                "_el": child,
            })
            tidx += 1

    # --- размеры шрифта таблиц и блока подписей — из образцов ---
    try:
        _tbl_sizes, _sig_sizes = [], []

        def _walk_tbl(t, is_sig):
            hdr = " ".join(c.text for c in t.rows[0].cells) if t.rows else ""
            if "ЗАКАЗЧИК" in hdr and "ИСПОЛНИТЕЛЬ" in hdr:
                is_sig = True
            for row in t.rows:
                for c in row.cells:
                    if c.text.strip():
                        for par in c.paragraphs:
                            v = _real_para_font_size_pt(par)
                            if v:
                                (_sig_sizes if is_sig else _tbl_sizes).append(v)
                    for nt in c.tables:  # блок подписей — ВЛОЖЕННАЯ таблица
                        _walk_tbl(nt, is_sig)

        for t in doc.tables:
            _walk_tbl(t, False)
        if _tbl_sizes:
            fonts["table_size_pt"] = collections.Counter(_tbl_sizes).most_common(1)[0][0]
        if _sig_sizes:
            fonts["sig_size_pt"] = collections.Counter(_sig_sizes).most_common(1)[0][0]
    except Exception:
        pass

    # --- разбиваем на title_block + дерево секций ---
    # title_block: абзацы до первого заголовка уровня 1
    first_h1 = None
    for i, b in enumerate(blocks):
        if b["type"] == "heading" and b["level"] == 1:
            first_h1 = i
            break

    title_block = []
    if first_h1 is None:
        first_h1 = len(blocks)
    def _para_spacing(el):
        """Абзацные параметры титула из образца (данные, не константы):
        space_before/after, first_line_indent (pt, может быть
        отрицательным — висячий отступ-центровка строк шапки)."""
        pPr = el.find(qn('w:pPr'))
        out = {}
        if pPr is None:
            return out
        for tag, key in (("w:spacing", "spacing"), ("w:ind", "ind")):
            el2 = pPr.find(qn(tag))
            if el2 is None:
                continue
            for a, k in (("before", "sb"), ("after", "sa")):
                if tag == "w:spacing" and el2.get(qn('w:' + a)):
                    out[key + a] = int(el2.get(qn('w:' + a))) / 20
            if tag == "w:ind" and el2.get(qn('w:firstLine')):
                out["fli"] = int(el2.get(qn('w:firstLine'))) / 20
            if tag == "w:ind" and el2.get(qn('w:hanging')):
                out["fli"] = -int(el2.get(qn('w:hanging'))) / 20
        return out

    for b in blocks[:first_h1]:
        child_el = b.get("_el")
        sp = _para_spacing(child_el)
        if b["type"] == "spacer":
            # пустой абзац-разделитель — часть вертикального ритма титульника
            title_block.append({"text": "", "placeholder": [],
                                "bold": False, "caps": False, "size_pt": None,
                                "spacing": sp})
        elif b["type"] == "paragraph":
            # опечатки исходных образцов НЕ исправляются молча (универсальность):
            # текст переносится как есть
            t, ph = to_placeholder(b["text"])
            runs = [r for r in child_el.findall('.//' + qn('w:r')) if r.find(qn('w:t')) is not None]
            bold = bool(runs) and all(
                (r.find('.//' + qn('w:b')) is not None) for r in runs)
            caps = 'w:caps' in child_el.xml
            size = None
            sz = child_el.find('.//' + qn('w:sz'))
            if sz is not None:
                size = int(sz.get(qn('w:val'))) / 2
            item = {"text": t, "placeholder": ph,
                    "bold": bold, "caps": caps, "size_pt": size,
                    "spacing": sp}
            if ph:
                # пример = отрендеренная строка ЦЕЛИКОМ («ВЕРСИЯ: 2», а не «2»):
                # токены плейсхолдеров заменяются их примерами
                item["example_line"] = _EXAMPLE_TOKEN_RE.sub(
                    lambda m: m.group(1), t)
            title_block.append(item)
        elif b["type"] == "table":
            sig = _title_sig_rows(doc, child_el)
            if sig:
                item = {"sig_rows": sig["rows"]}
                if sig.get("widths"):
                    item["sig_widths"] = sig["widths"]
                if sig.get("bolds"):
                    item["sig_bold"] = sig["bolds"]
                if sig.get("tbl_props"):
                    item["sig_tbl"] = sig["tbl_props"]
                if sig.get("heights"):
                    item["sig_heights"] = sig["heights"]
                title_block.append(item)

    # дерево секций
    sections = []  # список секций уровня 1
    stack = []  # стек (section, level)
    for b in blocks[first_h1:]:
        if b["type"] == "heading":
            lvl = b["level"]
            # заголовок раздела тоже плейсхолдеризуется: конкретика образца
            # (код ТЗ и т.п.) не должна попадать в универсальный шаблон
            t, ph = to_placeholder(b["text"])
            node = {"level": lvl, "title": t, "placeholder": ph,
                    "_heading_el": b["_el"],
                    "body": [], "children": []}
            # поднимемся до родителя
            while stack and stack[-1]["level"] >= lvl:
                stack.pop()
            if stack:
                stack[-1]["children"].append(node)
            else:
                sections.append(node)
            stack.append(node)
        else:
            target = stack[-1] if stack else None
            if target is None:
                # блок до первой секции (не должен быть)
                continue
            if b["type"] == "table":
                target["body"].append({
                    "type": "table",
                    "columns": b["columns"],
                    "rows": b["rows"],
                    "widths": b.get("widths"),
                    "example_row": b.get("example_row"),
                    "col_bold": b.get("col_bold"),
                                        "col_lead": b.get("col_lead"),
                                        "has_caption": b.get("has_caption"),
                    "header_repeat": True,
                })
            elif b["type"] == "image":
                target["body"].append({"type": "screenshot", "caption": None})
            elif b["type"] == "caption":
                # подпись скриншота: привязать к последнему screenshot
                for blk in reversed(target["body"]):
                    if blk["type"] == "screenshot" and blk["caption"] is None:
                        blk["caption"] = b["text"]
                        break
                else:
                    target["body"].append({"type": "caption", "text": b["text"],
                                           "size_pt": b.get("size_pt")})
            elif b["type"] == "list_item":
                # собрать последовательность list_item в один list
                if target["body"] and target["body"][-1].get("type") == "list":
                    target["body"][-1]["items"].append(b["text"])
                else:
                    target["body"].append({"type": "list", "items": [b["text"]],
                                           "fmt": b.get("fmt")})
            elif b["type"] == "paragraph":
                t, ph = to_placeholder(b["text"])
                target["body"].append({"type": "paragraph", "text": t,
                                       "placeholder": ph, "action": b.get("action", False)})

    _add_hints(sections)
    _heading_colors(blocks, styles)
    toc = _detect_toc(doc, body)

    # --- разрыв страницы перед H1 (параметр spec): из стиля H1 или ручных
    # разрывов перед заголовками уровня 1 ---
    h1_pb = any(_has_page_break(b.get("_el"))
                for b in blocks
                if b["type"] == "heading" and b["level"] == 1)
    h1_page_break = {
        # v8: глобального «каждый H1 с новой страницы» больше нет —
        # разрыв задаётся ПОРАЗДЕЛЬНО из образцов (см. page_break ниже)
        "enabled": False,
        "in_source": h1_pb,
    }

    _set_page_breaks(sections)
    density = _density_of(sections)
    paragraph_spec = _paragraph_rhythm(doc, blocks)

    spec = {
        "meta": {
            "source_file": os.path.basename(sample),
            "extracted_at": datetime.now().isoformat(timespec="seconds"),
            "note": "spec.json — источник правды; генерируется extract_spec.py",
            "samples_count": 1,  # фактическое число перезаписывается в build_spec
        },
        "header_footer": header_footer,
        "page": page,
        "fonts": fonts,
        "styles": styles,
        "screenshot_box": screenshot_box,
        "paragraph": paragraph_spec,
        "roles": sorted(roles_found),
        "glossary_terms": sorted(glossary_terms),
        "title_block": title_block,
        "numbering": numbering,
        "toc": toc,
        "h1_page_break": h1_page_break,
        "density": density,
        "sections": sections,
    }

    # P1 (D1, прогон ФР.000.00.00.0-59): токенизация титула на ОБОИХ
    # путях extract — код референса → [КОД] и в одиночном extract_one
    # (раньше только в intersect_specs); в keep-режиме тоже.
    spec["title_block"] = _tokenize_code_title(spec["title_block"])
    # naming-and-emphasis-universal: конвенция выделения сообщений —
    # по этому образцу (мажорита по выборке — в main)
    spec.setdefault("meta", {})["message_emphasis"] = _derive_message_emphasis(doc)
    return spec


if __name__ == "__main__":
    main()