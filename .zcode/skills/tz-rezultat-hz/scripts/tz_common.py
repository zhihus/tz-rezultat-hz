"""Общие помощники скриптов конвейера (единая точка, не дублировать).

Импорт безопасен из любого скрипта: tz_tool.py добавляет папку scripts/
в sys.path; при прямом запуске скрипта его папка и так в sys.path[0].
"""
import io
import os
import re
import sys


def setup_utf8_stdout():
    """stdout в UTF-8 (консоль Windows по умолчанию CP866 — кириллица
    в отчётах превращалась в кракозябры). Идемпотентно."""
    if not getattr(sys.stdout, "_tz_utf8", False):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        sys.stdout._tz_utf8 = True


# «Стр. N из M» в колонтитулах: кэш числа проверяем по метке, не по значению
PAGE_NUM_RE = re.compile(r"^(.*?)\s*\d+\s+из\s+\d+\s*$", re.S)


def collect_hf_texts(sec):
    """Все тексты колонтитула секции: абзацы + ячейки таблиц (по \n)."""
    out = []
    for part in (sec.header, sec.footer):
        txt = "\n".join(p.text for p in part.paragraphs)
        for t in part.tables:
            for row in t.rows:
                for cell in row.cells:
                    txt += "\n" + cell.text
        out.append(txt)
    return out


# --- Прогресс процесса (process-flow, 2026-11-23) --------------------------
def record_progress(progress_path, step, gate, verdict, artifacts):
    """Дописать запись гейта в прогресс.json (append-only). Файл пишут
    ТОЛЬКО скрипты; progress_path=None → no-op. Артефакты — абсолютные
    пути выходов шага; check_progress.py сверит их с диском."""
    import json as _json
    import os as _os
    from datetime import datetime as _dt
    if not progress_path:
        return
    rec = {"step": str(step), "gate": gate, "verdict": verdict,
           "artifacts": [_os.path.abspath(a) for a in (artifacts or [])],
           "ts": _dt.now().isoformat(timespec="seconds")}
    data = {"records": []}
    try:
        with open(progress_path, encoding="utf-8") as fh:
            data = _json.load(fh) or {"records": []}
    except (OSError, ValueError):
        data = {"records": []}
    data.setdefault("records", []).append(rec)
    with open(progress_path, "w", encoding="utf-8") as fh:
        _json.dump(data, fh, ensure_ascii=False, indent=1)


# --- Язык документа: проверка правописания (2026-11-25) --------------------
# Word и PowerPoint проверяют текст словарём ТОГО языка, который стоит на
# тексте. Образцы заказчика несут чужой язык (it-IT в docDefaults, en-US в
# themeFontLang), а текстовые свойства, созданные скриптами, языка не несут
# вовсе → русский текст подчёркивается красным и правка документа
# превращается в мусор из ложных ошибок. Здесь — единая точка проверки и
# правки: пакет целиком (части word/* и ppt/*), язык по умолчанию + все
# явные теги.
RU_LANG = "ru-RU"

# части пакета, где живёт язык (тело, стили и их копия stylesWithEffects,
# настройки, нумерация, сноски, колонтитулы)
_DOCX_PART = re.compile(r"^word/[^/]+\.xml$")
_PPTX_PART = re.compile(
    r"^ppt/(presentation\.xml|(slides|slideLayouts|slideMasters"
    r"|notesSlides|notesMasters)/.*\.xml)$")

_W_LANG = re.compile(r"<w:lang\b[^>]*/>")
_A_TEXT_PROP = re.compile(r"<(a:(?:rPr|endParaRPr|defRPr))\b([^>]*?)(/?)>")
_A_DEFRPR = re.compile(r"<a:defRPr\b[^>]*?/?>")


def lang_tag(meta_language):
    """meta.language образцов («ru»/«en») → тег языка BCP-47 для документа."""
    return {"ru": "ru-RU", "en": "en-US"}.get((meta_language or "").lower(),
                                               RU_LANG)


def _kind(path):
    ext = os.path.splitext(path)[1].lower()
    return {".docx": "docx", ".pptx": "pptx"}.get(ext)


def _is_lang_part(name, kind):
    return bool(_DOCX_PART.match(name) if kind == "docx"
                else _PPTX_PART.match(name))


def _snippet(xml, pos):
    """Ближайший текст после тега — чтобы дефект был узнаваем в отчёте."""
    m = re.search(r"<(?:w|a):t[^>]*>([^<]{1,80})<", xml[pos:pos + 800])
    return (m.group(1).strip()[:40] if m else "")


def _ru_w_lang(tag, lang=RU_LANG):
    """<w:lang …/> → русский: w:val и w:eastAsia (w:bidi не трогаем)."""
    out = re.sub(r'w:val="[^"]*"', f'w:val="{lang}"', tag, count=1)
    if 'w:eastAsia="' in out:
        out = re.sub(r'w:eastAsia="[^"]*"', f'w:eastAsia="{lang}"', out, count=1)
    return out


def _fix_text_props(xml, lang=RU_LANG):
    """Явный lang на текстовых свойствах DrawingML: есть — заменить, нет —
    добавить (иначе при наборе текста редактор берёт язык приложения)."""
    def repl(m):
        tag, attrs, close = m.group(1), m.group(2), m.group(3)
        if "lang=" in attrs:
            attrs = re.sub(r'lang="[^"]*"', f'lang="{lang}"', attrs)
        else:
            attrs = f' lang="{lang}"' + attrs
        return f"<{tag}{attrs}{close}>"
    return _A_TEXT_PROP.sub(repl, xml)


def _fix_docx_defaults(styles, settings, lang=RU_LANG):
    """Язык по умолчанию (docDefaults) и themeFontLang — русские.
    Тега нет — добавить: без него Word берёт язык приложения."""
    tag = f'<w:lang w:val="{lang}" w:eastAsia="{lang}" w:bidi="ar-SA"/>'
    block = re.search(r"<w:docDefaults>.*?</w:docDefaults>", styles, re.S)
    if block:
        b = block.group(0)
        if _W_LANG.search(b):
            b2 = _W_LANG.sub(lambda m: _ru_w_lang(m.group(0), lang), b)
        else:
            rpr = re.search(r"<w:rPrDefault>\s*<w:rPr\s*/>", b) or \
                re.search(r"<w:rPrDefault>\s*<w:rPr\b[^>]*>", b)
            if rpr:
                old = rpr.group(0)
                new = (old[:-2] + f">{tag}</w:rPr>") if old.endswith("/>") \
                    else old + tag
                b2 = b.replace(old, new, 1)
            else:
                b2 = b.replace("<w:docDefaults>",
                               "<w:docDefaults><w:rPrDefault><w:rPr>" + tag +
                               "</w:rPr></w:rPrDefault>", 1)
        styles = styles[:block.start()] + b2 + styles[block.end():]
    m = re.search(r"<w:themeFontLang\b[^>]*/>", settings)
    if m:
        t = re.sub(r'w:val="[^"]*"', f'w:val="{lang}"', m.group(0), count=1)
        t = re.sub(r'w:eastAsia="[^"]*"', f'w:eastAsia="{lang}"', t, count=1)
        settings = settings[:m.start()] + t + settings[m.end():]
    elif "</w:settings>" in settings:
        t = f'<w:themeFontLang w:val="{lang}" w:eastAsia="{lang}"/>'
        settings = settings.replace("</w:settings>", t + "</w:settings>", 1)
    return styles, settings


def scan_language(path, lang=RU_LANG):
    """Проверка языка документа. Возвращает отчёт:
    {kind, parts, tags, foreign:[(часть, тег, текст)], defaults:[(часть, тег, что)]}."""
    import zipfile
    kind = _kind(path)
    rep = {"kind": kind, "parts": 0, "tags": 0, "foreign": [], "defaults": [],
           "lang": lang}
    if not kind:
        rep["defaults"].append(("", "", "формат не поддержан (нужен DOCX/PPTX)"))
        return rep
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not _is_lang_part(name, kind):
                continue
            xml = z.read(name).decode("utf-8", "ignore")
            rep["parts"] += 1
            if kind == "docx":
                for m in _W_LANG.finditer(xml):
                    rep["tags"] += 1
                    v = re.search(r'w:val="([^"]*)"', m.group(0))
                    if (v.group(1) if v else "") != lang:
                        rep["foreign"].append(
                            (name, m.group(0), _snippet(xml, m.end())))
            else:
                for m in _A_TEXT_PROP.finditer(xml):
                    if "lang=" not in m.group(2):
                        continue
                    rep["tags"] += 1
                    v = re.search(r'lang="([^"]*)"', m.group(2))
                    if v.group(1) != lang:
                        rep["foreign"].append(
                            (name, m.group(0), _snippet(xml, m.end())))
            if kind == "docx" and name == "word/styles.xml":
                blk = re.search(r"<w:docDefaults>.*?</w:docDefaults>", xml, re.S)
                lm = _W_LANG.search(blk.group(0)) if blk else None
                if not lm:
                    rep["defaults"].append((name, "", "язык по умолчанию "
                                           "(docDefaults) не задан"))
                elif not re.search(rf'w:val="{re.escape(lang)}"', lm.group(0)):
                    rep["defaults"].append((name, lm.group(0),
                                            "язык по умолчанию не русский"))
            if kind == "docx" and name == "word/settings.xml":
                tm = re.search(r"<w:themeFontLang\b[^>]*/>", xml)
                if not tm:
                    rep["defaults"].append((name, "", "themeFontLang не задан"))
                elif not re.search(rf'w:val="{re.escape(lang)}"', tm.group(0)):
                    rep["defaults"].append((name, tm.group(0),
                                            "themeFontLang не русский"))
            if kind == "pptx":
                containers = []
                if name == "ppt/presentation.xml":
                    containers += re.findall(
                        r"<p:defaultTextStyle>.*?</p:defaultTextStyle>", xml, re.S)
                if name.startswith("ppt/slideMasters/"):
                    containers += re.findall(r"<p:txStyles>.*?</p:txStyles>",
                                             xml, re.S)
                for c in containers:
                    for d in _A_DEFRPR.finditer(c):
                        if not re.search(rf'lang="{re.escape(lang)}"', d.group(0)):
                            rep["defaults"].append(
                                (name, d.group(0)[:60],
                                 "язык по умолчанию (стили) не ru-RU"))
                            break
    return rep


def normalize_language(src, dst=None, lang=RU_LANG):
    """Записать документ с русским языком проверки правописания.
    dst=None — на месте (вызов конвейера после сохранения); dst — новый
    файл (агент правит документ ТОЛЬКО новой версией)."""
    import shutil
    import zipfile
    kind = _kind(src)
    if not kind:
        raise ValueError("нужен DOCX/PPTX: " + src)
    dst = dst or src
    tmp = dst + ".tmp"
    with zipfile.ZipFile(src) as zin, \
            zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in zin.namelist():
            data = zin.read(name)
            if _is_lang_part(name, kind):
                xml = data.decode("utf-8", "ignore")
                if kind == "docx":
                    xml = _W_LANG.sub(lambda m: _ru_w_lang(m.group(0), lang), xml)
                    if name == "word/styles.xml":
                        xml, _ = _fix_docx_defaults(xml, "", lang)
                    if name == "word/settings.xml":
                        _, xml = _fix_docx_defaults("", xml, lang)
                else:
                    xml = _fix_text_props(xml, lang)
                data = xml.encode("utf-8")
            zout.writestr(name, data)
    if dst == src:
        shutil.move(tmp, dst)
    else:
        shutil.move(tmp, dst)
    return scan_language(dst, lang)


def set_language_ru(path, lang=RU_LANG):
    """Конвейер: после doc.save() — русский язык проверки правописания."""
    return normalize_language(path, None, lang)

