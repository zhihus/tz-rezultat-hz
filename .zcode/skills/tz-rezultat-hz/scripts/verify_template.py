# -*- coding: utf-8 -*-
"""
verify_template.py — шаг 3 конвейера.

Открывает сгенерированный шаблон и проверяет:
  1. плейсхолдеры: все типы из spec присутствуют в шаблоне;
  2. нумерация рендерится 1/2/3 → 3.1 → 3.1.1 (XML + рендер, по границам);
  3. число строк таблиц = спецификации;
  4. плотность = spec (скриншоты, подфункции, таблицы);
  5. сверка с исходными образцами (независимый пересчёт плотности из
     образцов по путям из spec.meta — ошибки extract не маскируются);
  6. format-agent preflight (0 блокирующих);
  7. рендер PNG (render_to_pdf → pymupdf; Win → Word COM, Linux → LibreOffice headless).

Выводит pass/fail с конкретными расхождениями и список PNG для visual-judge.

Использование (запуск из корня проекта; -o — полный путь к файлу результата):
    python verify_template.py spec.json шаблон_ТЗ_1С.docx -o версии/версия-N/отчёт_проверки.md
"""
import argparse
import glob
import io
import json
import os
import re
import subprocess
import sys

from docx import Document
from docx.oxml.ns import qn

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))  # portable python: папка скрипта не в sys.path
from tz_common import setup_utf8_stdout, PAGE_NUM_RE, collect_hf_texts

setup_utf8_stdout()

def _find_skill_dir(work=None):
    """Найти скилл format-agent: относительно скрипта (dev-режим), от
    КОРНЯ РАБОЧЕЙ папки (D2, прогон -59: префлайт копирует
    <работа>/format-agent-skill; вызов из projects/<имя> по cwd не
    находил), от cwd или корень cwd."""
    here = os.path.dirname(os.path.abspath(__file__))
    # work — ПЕРВЫМ: это рантайм-копия префлайта (D2, прогон -59);
    # каталог скрипта — dev-режим; cwd — запасной.
    bases = [os.path.join(here, ".."), os.getcwd()]
    # work — ПЕРВЫМ, и в ДВУХ местах: <работа>/format-agent-skill (куда
    # копирует префлайт, D2 прогон -59) и <работа>/.zcode/skills/…
    if work:
        for _p in (os.path.join(work, "format-agent-skill"),
                   os.path.join(work, ".zcode", "skills", "format-agent-skill")):
            if os.path.isdir(_p):
                return os.path.normpath(_p)
    for base in bases:
        p = os.path.normpath(os.path.join(base, ".zcode", "skills", "format-agent-skill"))
        if os.path.isdir(p):
            return p
    p = os.path.normpath(os.path.join(os.getcwd(), "format-agent-skill"))
    if os.path.isdir(p):
        return p
    return os.path.normpath(os.path.join(here, "..", ".zcode", "skills", "format-agent-skill"))


class Report:
    def __init__(self):
        self.checks = []  # (name, ok, detail)

    def add(self, name, ok, detail=""):
        self.checks.append((name, ok, detail))

    @property
    def failed(self):
        return [c for c in self.checks if not c[1]]

    def render(self):
        lines = []
        for name, ok, detail in self.checks:
            mark = "PASS" if ok else "FAIL"
            lines.append(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
        status = "FAIL" if self.failed else "PASS"
        lines.append("")
        lines.append(f"ИТОГ: {status} ({len(self.checks) - len(self.failed)}/{len(self.checks)} проверок)")
        if self.failed:
            lines.append("Расхождения:")
            for name, ok, detail in self.failed:
                lines.append(f"  ✗ {name}: {detail}")
        return "\n".join(lines)


def all_text(doc):
    parts = []
    for p in doc.paragraphs:
        parts.append(p.text)
    for t in doc.tables:
        for row in t.rows:
            for c in row.cells:
                parts.append(c.text)
    return "\n".join(parts)


# Имя плейсхолдера: [ИМЯ], [ИМЯ | пример: ...], [ПОДФУНКЦИЯ 3 | пример: ...].
# Токены с «:» сразу после имени ([ТЕКСТ: ...]) и с переменным регистром
# ([Рисунок — ОПИСАНИЕ]) именами не считаются — это внутренние метки build.
PH_NAME = re.compile(r"\[([A-ЯЁA-Z][A-ЯЁA-Z_ 0-9]*?)(?:\s*\||\])")


def _norm_ph(name):
    """Нормализация имени: «ПОДФУНКЦИЯ 3» → «ПОДФУНКЦИЯ»."""
    return re.sub(r"\s*\d+\s*$", "", name).strip()


def _spec_ph_names(spec):
    """Все имена плейсхолдеров, объявленные в spec (кроме meta)."""
    strs = []

    def walk(obj):
        if isinstance(obj, str):
            strs.append(obj)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                if k != "meta":
                    walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(spec)
    return {_norm_ph(n) for s in strs for n in PH_NAME.findall(s)}


def check_language(doc, spec, rep):
    """Язык заголовков/подписей шаблона = язык образцов (spec.meta.language).
    Заголовок (Heading/Заголовок/Title) или подпись (Caption/Подпись/Название),
    которых нет в spec и где есть буква чужого алфавита (латиница при
    ru-образцах, кириллица при en), — дефект сборки (урок Прогона #5:
    модель добавила английский заголовок в русский шаблон)."""
    lang = ((spec or {}).get("meta") or {}).get("language") or "und"
    if lang == "und":
        rep.add("Язык заголовков соответствует образцам", True,
                "не применимо: язык образцов не определён (meta.language)")
        return
    spec_text = json.dumps(spec, ensure_ascii=False)
    _foreign = (re.compile(r"[A-Za-z]{2,}") if lang == "ru"
                else re.compile(r"[А-ЯЁа-яё]{2,}"))
    _stypes = ("Heading", "Заголовок", "Title", "Caption", "Подпись",
               "Название")
    foreign = []
    for p in doc.paragraphs:
        st = (p.style.name if p.style is not None else "") or ""
        if not any(k in st for k in _stypes):
            continue
        t = p.text.strip()
        if t and _foreign.search(t) and t not in spec_text:
            foreign.append(t)
    rep.add("Язык заголовков соответствует образцам", not foreign,
            ("язык образцов: %s; чужие заголовки/подписи: %s" % (lang, foreign))
            if foreign else f"язык образцов: {lang}, чужих нет")


def check_placeholders(doc, spec, rep):
    """Все типы плейсхолдеров из spec присутствуют в шаблоне (тело +
    колонтитулы — плейсхолдеры ПДн живут в footer)."""
    text = all_text(doc)
    sec = doc.sections[0]
    for part in (sec.header, sec.footer, sec.first_page_header,
                 sec.first_page_footer):
        text += "\n" + "\n".join(p.text for p in part.paragraphs)
        for t in part.tables:
            for r in t.rows:
                for c in r.cells:
                    text += "\n" + c.text
    found = {_norm_ph(n) for n in PH_NAME.findall(text)}
    expected = _spec_ph_names(spec)
    missing = sorted(expected - found)
    if not expected:
        # элементный режим без текстовых плейсхолдеров (toc/header/…)
        rep.add("Плейсхолдеры spec присутствуют в шаблоне", True,
                "в spec нет плейсхолдеров — проверка не применима")
        return
    ok = not missing
    rep.add("Плейсхолдеры spec присутствуют в шаблоне", ok,
            ("отсутствуют: " + ", ".join(missing)) if missing
            else f"все {len(expected)} типов на месте "
                 f"(всего токенов {len(PH_NAME.findall(text))})")


def check_numbering_xml(doc, rep):
    """Проверить abstractNum: start=1 на всех уровнях, форматы %1. / %1.%2. / %1.%2.%3."""
    try:
        numbering = doc.part.numbering_part.element
    except Exception as e:
        rep.add("Нумерация (XML)", False, f"нет numbering part: {e}")
        return
    V = qn("w:val")
    found = None
    for an in numbering.findall(qn("w:abstractNum")):
        lvls = an.findall(qn("w:lvl"))
        if len(lvls) < 3:
            continue
        texts = []
        starts = []
        for lvl in lvls[:3]:
            txt = lvl.find(qn("w:lvlText"))
            start = lvl.find(qn("w:start"))
            texts.append(txt.get(V) if txt is not None else "")
            starts.append(int(start.get(V)) if start is not None else 1)
        if texts[0].startswith("%1") and texts[1].startswith("%1.%2") and texts[2].startswith("%1.%2.%3"):
            found = (texts, starts)
            break
    if not found:
        rep.add("Нумерация (XML)", False, "не найдена многоступенчатая decimal-нумерация %1.%2.%3")
        return
    texts, starts = found
    ok = all(s == 1 for s in starts)
    rep.add("Нумерация (XML): start→1", ok,
            f"форматы {texts}, start={starts}")


def _sig_label(spec):
    """Метка блока подписей из spec (первая строка sig_rows), fallback «ЗАКАЗЧИК»."""
    for it in (spec or {}).get("title_block", []):
        if "sig_rows" in it and it["sig_rows"]:
            first = it["sig_rows"][0][0] or ""
            m = re.search(r"[А-ЯЁ ]{4,}", first)
            if m:
                return m.group(0).strip()
    return "ЗАКАЗЧИК"


def _is_signature_table(t, label="ЗАКАЗЧИК"):
    """Таблица блока подписей — не входит в плотность."""
    return t.rows and label in t.rows[0].cells[0].text


def check_table_rows(doc, spec, rep):
    """Число строк каждой таблицы в шаблоне = спецификации."""
    spec_tables = spec["density"]["tables"]
    sig_label = _sig_label(spec)
    doc_tables = [(len(t.rows), len(t.columns)) for t in doc.tables
                  if not _is_signature_table(t, sig_label)]
    # отфильтровать таблицы-плейсхолдеры скриншотов (1x1)
    data_tables = [(r, c) for (r, c) in doc_tables if not (r == 1 and c == 1)]
    # сопоставить по порядку
    ok = True
    details = []
    for i, st in enumerate(spec_tables):
        want_rows = st["rows"]
        want_cols = len(st["columns"])
        if i < len(data_tables):
            got_rows, got_cols = data_tables[i]
            if got_rows != want_rows or got_cols != want_cols:
                ok = False
                details.append(f"таблица {i+1}: ожидалось {want_rows}×{want_cols}, получено {got_rows}×{got_cols}")
        else:
            ok = False
            details.append(f"таблица {i+1}: отсутствует в шаблоне")
    rep.add("Число строк таблиц = спецификации", ok, "; ".join(details) or f"{len(spec_tables)} таблиц совпадает")


def check_density(doc, spec, rep):
    density = spec["density"]
    text = all_text(doc)
    # скриншоты: плейсхолдеры [МЕСТО ДЛЯ СКРИНШОТА]
    shots = text.count("[МЕСТО ДЛЯ СКРИНШОТА]") + text.count("[СКРИНШОТ:")
    ok1 = shots == density["screenshots_total"]
    rep.add("Плотность: скриншоты", ok1,
            f"ожидалось {density['screenshots_total']}, в шаблоне {shots}")
    # подфункции: [ПОДФУНКЦИЯ N], [ПОДФУНКЦИЯ N | пример: ...] и т.п.
    subs = re.findall(r"\[ПОДФУНКЦИЯ (\d+)(?:[^\]]*)?\]", text)
    ok2 = len(subs) == density["business_logic_subfunctions"]
    rep.add("Плотность: подфункции (Heading 3)", ok2,
            f"ожидалось {density['business_logic_subfunctions']}, в шаблоне {len(subs)}")
    # таблицы
    spec_ntables = len(density["tables"])
    data_tables = [(len(t.rows), len(t.columns)) for t in doc.tables
                   if not (len(t.rows) == 1 and len(t.columns) == 1)
                   and not _is_signature_table(t, _sig_label(spec))]
    ok3 = len(data_tables) == spec_ntables
    rep.add("Плотность: число таблиц", ok3,
            f"ожидалось {spec_ntables}, в шаблоне {len(data_tables)}")


def _expected_numbers(levels):
    """Data-driven: ожидаемая последовательность номеров заголовков
    (L1 → «N.», L2 → «N.M.», L3 → «N.M.K.») из потока уровней 1..3.
    Источники: структура spec (_expected_numbers_spec) или Markdown
    (_expected_numbers_md). Не захардкожено."""
    out = []
    c1 = c2 = c3 = 0
    for lvl in levels:
        if lvl == 1:
            c1 += 1; c2 = c3 = 0
            out.append(f"{c1}.")
        elif lvl == 2:
            c2 += 1; c3 = 0
            out.append(f"{c1}.{c2}.")
        elif lvl == 3:
            c3 += 1
            out.append(f"{c1}.{c2}.{c3}.")
    return out


def _expected_numbers_spec(sections):
    """Уровни заголовков в порядке обхода дерева spec."""

    def walk(node, acc):
        acc.append(node["level"])
        for c in node.get("children", []):
            walk(c, acc)

    acc = []
    for s in sections:
        walk(s, acc)
    return acc


def _expected_numbers_md(md_path):
    """Уровни заголовков из Markdown (# → 1, ## → 2, ### → 3), --filled."""
    with open(md_path, encoding="utf-8") as fh:
        return [len(m.group(1)) for ln in fh
                if (m := re.match(r"^(#{1,3})\s+", ln.rstrip()))]


def check_numbering_render(pdf_path, spec, rep):
    """Проверить рендер нумерации: ожидаемые номера — из структуры spec."""
    try:
        import pymupdf
    except ImportError:
        rep.add("Нумерация (рендер)", False, "pymupdf не установлен")
        return
    doc = pymupdf.open(pdf_path)
    text = "\n".join(page.get_text() for page in doc)
    expected = _expected_numbers(_expected_numbers_spec(spec.get("sections", [])))
    # номер должен стоять отдельно: не внутри другого номера (3.1. не
    # засчитывается внутри 3.1.1.) и не в числах/датах
    missing = [e for e in expected
               if not re.search(r"(?<![\d.])" + re.escape(e) + r"(?=\s|$)", text)]
    ok = not missing
    rep.add("Нумерация (рендер): многоступенчатая по структуре", ok,
            f"не найдено: {missing}" if missing else f"все {len(expected)} номеров на месте")


def check_against_samples(doc, spec, rep):
    """Независимая сверка шаблона с ИСХОДНЫМИ образцами: плотность
    (скриншоты/подфункции/таблицы) пересчитывается из образцов заново,
    минуя spec.json — ошибки шага extract не маскируются."""
    meta = spec.get("meta", {})
    try:
        import extract_spec as E
    except ImportError:
        rep.add("Сверка с образцами", False, "extract_spec недоступен для пересчёта")
        return
    try:
        if meta.get("samples_dir"):
            files = [f for f in sorted(glob.glob(os.path.join(meta["samples_dir"], "*.docx")))
                     if not os.path.basename(f).startswith("~$")]
            if not files:
                rep.add("Сверка с образцами", False,
                        f"в {meta['samples_dir']} нет DOCX")
                return
            inter = E.intersect_specs([E.extract_one(f) for f in files])
        elif meta.get("sample_path") and os.path.exists(meta["sample_path"]):
            inter = E.extract_one(meta["sample_path"])
        else:
            rep.add("Сверка с образцами", True,
                    "пути к образцам не записаны в spec.meta — проверка пропущена")
            return
    except Exception as e:
        rep.add("Сверка с образцами", False, f"ошибка пересчёта из образцов: {e}")
        return
    # pii=keep: свежепересчитанные ожидания приводятся к подставленному виду
    if (spec.get("meta") or {}).get("pii_mode") == "keep":
        inter = E.substitute_keep(inter)
    exp = inter["density"]
    text = all_text(doc)
    # скелет большинства: каждый H1/H2 «большинственного» spec обязан быть
    # в шаблоне (ловушка тихих потерь разделов при extract). Сверка — по
    # нормализованному заголовку: build снимает вписанную нумерацию
    # («1. Источник…» → «Источник…»), шаблон нумерует своими числами
    _NUM_RE = re.compile(r"^\s*\d+(?:\.\d+)*[.)]\s+")
    def walk(nodes):
        for n in nodes:
            if n.get("level") in (1, 2) and not n.get("title", "").startswith("["):
                yield _NUM_RE.sub("", n["title"])
            yield from walk(n.get("children", []))
    missing_secs = [t for t in walk(inter.get("sections", []))
                    if _NUM_RE.sub("", t).strip() not in text]
    if missing_secs:
        rep.add("Скелет большинства в шаблоне", False,
                "отсутствуют разделы: " + "; ".join(missing_secs[:5]))
    else:
        rep.add("Скелет большинства в шаблоне", True,
                "все H1/H2 из spec присутствуют")
    got_shots = text.count("[МЕСТО ДЛЯ СКРИНШОТА]") + text.count("[СКРИНШОТ:")
    got_subs = len(re.findall(r"\[ПОДФУНКЦИЯ \d+", text))
    got_tables = len([1 for t in doc.tables
                      if not (len(t.rows) == 1 and len(t.columns) == 1)
                      and not _is_signature_table(t, _sig_label(spec))])
    problems = []
    if got_shots != exp["screenshots_total"]:
        problems.append(f"скриншоты: в шаблоне {got_shots}, из образцов {exp['screenshots_total']}")
    if got_subs != exp["business_logic_subfunctions"]:
        problems.append(f"подфункции: в шаблоне {got_subs}, "
                        f"из образцов {exp['business_logic_subfunctions']}")
    if got_tables != len(exp["tables"]):
        problems.append(f"таблицы: в шаблоне {got_tables}, из образцов {len(exp['tables'])}")
    rep.add("Сверка с образцами (независимый пересчёт)", not problems,
            "; ".join(problems)
            or f"скриншоты={got_shots}, подфункции={got_subs}, "
               f"таблицы={got_tables} — совпадает с образцами")


def run_preflight(docx_path, out_dir, rep, work=None):
    """Запустить format-agent preflight."""
    skill = _find_skill_dir(work=work)
    if not os.path.isdir(skill):
        rep.add("format-agent preflight", False, f"скилл не найден: {skill}")
        return None
    out_docx = os.path.join(out_dir, "preflight_out.docx")
    docx_abs = os.path.abspath(docx_path)  # subprocess работает с cwd=skill
    # В _pth-режиме portable Python (portable/python/python311._pth) директория
    # скрипта не добавляется в sys.path автоматически — бутстрап добавляет её явно.
    bootstrap = (
        "import os, runpy, sys\n"
        f"sys.path.insert(0, {skill!r})\n"
        "sys.argv = ['main.py'] + sys.argv[1:]\n"
        f"runpy.run_path(os.path.join({skill!r}, 'main.py'), run_name='__main__')\n"
    )
    try:
        r = subprocess.run(
            [sys.executable, "-c", bootstrap, "--preflight-only",
             "--target", docx_abs, "--out", out_docx],
            cwd=skill, capture_output=True, timeout=120)
        r.stdout = r.stdout.decode("utf-8", errors="replace")
        r.stderr = r.stderr.decode("utf-8", errors="replace")
    except Exception as e:
        rep.add("format-agent preflight", False, f"ошибка запуска: {e}")
        return None
    report_path = os.path.splitext(out_docx)[0] + "_preflight.json"
    if not os.path.exists(report_path):
        rep.add("format-agent preflight", False,
                f"нет отчёта. stdout: {r.stdout[-300:]}, stderr: {r.stderr[-300:]}")
        return None
    with open(report_path, encoding="utf-8") as fh:
        rep_data = json.load(fh)
    blockers = rep_data.get("blockers", [])
    warnings = rep_data.get("warnings", [])
    ok = rep_data.get("ok", False) and not blockers
    rep.add("format-agent preflight", ok,
            f"ok={rep_data.get('ok')}, блокирующих={len(blockers)}, предупреждений={len(warnings)}")
    return report_path


def _soffice_candidates():
    """Пути к LibreOffice: переменная TZ_SOFFICE → системный PATH →
    папка рядом с проектом (portable/libreoffice — без установки)."""
    cands = []
    env = os.environ.get("TZ_SOFFICE")
    if env:
        cands.append(env)
    cands.append("soffice")
    root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    for rel in (os.path.join("portable", "libreoffice", "program", "soffice.exe"),
                os.path.join("portable", "libreoffice", "soffice")):
        p = os.path.join(root, rel)
        if os.path.exists(p):
            cands.append(p)
    return cands


def render_to_pdf(docx_path, pdf_path):
    """Кросс-платформенный рендер DOCX → PDF. Цепочка:
      1. Word COM (Windows, если установлен) — эталонная вёрстка;
      2. LibreOffice headless (Windows/Linux; TZ_SOFFICE → PATH →
         portable/libreoffice рядом с проектом — без установки).
    Оба пути без прав администратора; результат — PDF для гейта."""
    docx_abs = os.path.abspath(docx_path)
    pdf_abs = os.path.abspath(pdf_path)
    if os.name == "nt":
        for attempt in range(3):
            try:
                import pythoncom
                import win32com.client as w
                pythoncom.CoInitialize()
                try:
                    app = w.Dispatch("Word.Application")
                    app.Visible = False
                    app.DisplayAlerts = 0
                    d = app.Documents.Open(docx_abs)
                    # обновить поля (PAGE/NUMPAGES) во всех story документа;
                    # TOC (type 13) НЕ обновляем: без закладок Word вставит
                    # «Ошибка! Закладка не определена» — оглавление строится
                    # пользователем/агентом в Word (F9)
                    story = d.StoryRanges(1)
                    while story is not None:
                        for i in range(1, story.Fields.Count + 1):
                            fld = story.Fields(i)
                            if fld.Type != 13:
                                fld.Update()
                        story = story.NextStoryRange
                    d.SaveAs(pdf_abs, FileFormat=17)
                    d.Close()
                    app.Quit()
                    return "word-com"
                finally:
                    pythoncom.CoUninitialize()
            except Exception as e:
                last = e
                continue
        raise RuntimeError(f"Word COM недоступен после 3 попыток: {last}")
    outdir = os.path.dirname(pdf_abs)
    last_err = "LibreOffice не найден (TZ_SOFFICE / PATH / portable/libreoffice)"
    for cand in _soffice_candidates():
        try:
            r = subprocess.run(
                [cand, "--headless", "--convert-to", "pdf", "--outdir", outdir, docx_abs],
                capture_output=True, timeout=300)
        except (OSError, subprocess.SubprocessError) as e:
            last_err = str(e)
            continue
        if r.returncode != 0:
            last_err = r.stderr.decode("utf-8", "replace")[-300:]
            continue
        produced = os.path.join(outdir,
                                os.path.splitext(os.path.basename(docx_abs))[0] + ".pdf")
        if os.path.normcase(produced) != os.path.normcase(pdf_abs):
            os.replace(produced, pdf_abs)
        return "libreoffice"
    raise RuntimeError(last_err)


def render_png(docx_path, out_dir, rep):
    """render_to_pdf → pymupdf → PNG. Устаревшие page_*.png удаляются
    перед рендером (иначе смешиваются страницы разных прогонов)."""
    for old in glob.glob(os.path.join(out_dir, "page_*.png")):
        os.remove(old)
    pdf = os.path.join(out_dir, "шаблон_preview.pdf")
    try:
        engine = render_to_pdf(docx_path, pdf)
    except Exception as e:
        rep.add("Рендер PNG", False, f"render_to_pdf: {e}")
        return []
    try:
        import pymupdf
        doc = pymupdf.open(pdf)
        paths = []
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=110)
            p = os.path.join(out_dir, f"page_{i+1}.png")
            pix.save(p)
            paths.append(p)
        rep.add("Рендер PNG", True,
                f"{len(paths)} страниц (движок: {engine}) → {out_dir}")
        return paths
    except Exception as e:
        rep.add("Рендер PNG", False, f"pymupdf: {e}")
        return []


def check_file_name(docx_path, spec, rep):
    """Имя файла — по шаблону из образцов (spec.meta.file_name_pattern):
    рендер формирует его сам; выдуманное агентом имя — FAIL (E-50).
    «финал» в имени недопустим: его ставит только пользователь вручную."""
    pat = ((spec or {}).get("meta") or {}).get("file_name_pattern")
    if not pat:
        rep.add("Имя файла по шаблону образцов", True,
                "шаблона имени в spec нет — проверка пропущена")
        return
    base = os.path.splitext(os.path.basename(docx_path))[0]
    rx = re.escape(pat).replace(re.escape("{КОД}"), ".+?").replace(
        re.escape("V{ВЕРСИЯ}"), r"V\d+")
    ok = re.fullmatch(rx, base) is not None
    rep.add("Имя файла по шаблону образцов", ok,
            f"имя по шаблону: «{pat}»" if ok
            else f"имя «{base}» не по шаблону «{pat}» — переименовать, не выдумывать")
    if "финал" in base.lower():
        rep.add("Имя файла: без «финал»", False,
                "«финал» ставит только пользователь вручную после нескольких версий")
    else:
        rep.add("Имя файла: без «финал»", True, "слово «финал» не используется")


def check_signatures(doc, rep, spec=None):
    """Блок подписей на титульном листе: метка — из spec.sig_rows.
    Блока нет в spec (тех-ТЗ, E-50) — проверка не выполняется:
    отсутствие подписей там — ДИЗАЙН, не дефект."""
    sig_rows = (spec or {}).get("title_block") or []
    if not any("sig_rows" in it for it in sig_rows):
        rep.add("Подписи на титульном листе", True,
                "блока подписей нет в spec (тех-ТЗ) — проверка не требуется")
        return
    label = _sig_label(spec)
    text = all_text(doc)
    ok = label in text and "ИСПОЛНИТЕЛЬ" in text
    rep.add("Подписи на титульном листе", ok,
            f"блок подписей на месте (метка «{label}»)" if ok
            else "подписи не найдены в шаблоне")


def check_toc(doc, rep, spec=None):
    """Оглавление и разрывы: требования из spec.toc / spec.h1_page_break."""
    toc = (spec or {}).get("toc") or {}
    h1pb = (spec or {}).get("h1_page_break") or {}
    xml = doc.element.body.xml
    problems = []
    if not toc.get("present", True):
        rep.add("Оглавление на отдельной странице", True,
                "оглавления нет по образцам (toc.present=False) — не дефект")
        return
    if toc.get("present", True) and ("instrText" not in xml or "TOC" not in xml):
        problems.append("поле TOC отсутствует")
    # разрыв страницы перед оглавлением: явный w:br или pageBreakBefore
    # (пустой абзац-разрыв создаёт пустой лист — pageBreakBefore каноничнее);
    # проверяется только когда оглавление присутствует
    if toc.get("present", True) and ('w:br w:type="page"' not in xml
                                     and 'w:pageBreakBefore' not in xml):
        problems.append("нет разрыва страницы перед оглавлением")
    # v8: глобальный разрыв H1 отменён — разрывы пофаздельно из
    # образцов (node.page_break), отсутствие pageBreakBefore у стиля
    # H1 НЕ дефект
    rep.add("Оглавление на отдельной странице", not problems,
            "; ".join(problems) or "TOC-поле на месте, разрыв перед ним есть")


def check_header_footer(doc, rep, spec=None):
    """Колонтитулы воспроизведены: ожидаемые тексты — из spec (источник
    правды); страница-номер проверяется по метке из spec, не из кода."""
    sec = doc.sections[0]
    h = "\n".join(p.text for p in sec.header.paragraphs)
    for t in sec.header.tables:
        for r in t.rows:
            for c in r.cells:
                h += "\n" + c.text
    f = "\n".join(p.text for p in sec.footer.paragraphs)
    for t in sec.footer.tables:
        for r in t.rows:
            for c in r.cells:
                f += "\n" + c.text
    hf_spec = (spec or {}).get("header_footer") or {}
    if hf_spec:
        from extract_spec import to_placeholder
        problems = []
        for name, rendered in (("header", h), ("footer", f)):
            blk = hf_spec.get(name) or {}
            for row in blk.get("cells", []):
                for cell in row:
                    for ln in (cell or "").split("\n"):
                        ln = ln.strip()
                        if not ln:
                            continue
                        # строка нумерации страниц: проверяем метку, не кэш числа
                        if re.search(r"\d+\s+из\s+\d+", ln):
                            m = PAGE_NUM_RE.match(ln)
                            label = (m.group(1).strip() if m and m.group(1).strip()
                                     else (blk.get("page_number") or {}).get("label", "Стр."))
                            if label not in rendered:
                                problems.append(f"в {name} нет нумерации страниц («{label}»)")
                            continue
                        # тексты ячеек уже плейсхолдеризованы на extract;
                        # в header примеры рендерятся отдельными строками
                        expected = ln
                        if name == "header":
                            from build_from_spec import split_examples
                            expected = "\n".join(split_examples(expected))
                        if expected in rendered:
                            continue
                        # E-59: плейсхолдер мог быть ЗАПОЛНЕН (--set):
                        # «[EMAIL | пример: …]» → «info@example.com».
                        # Сравнение без токенов: литералы вокруг
                        # плейсхолдеров обязаны совпасть.
                        _parts = re.split(r"\[[^\]]*\]", expected)
                        if len(_parts) > 1:
                            _pat = ".{0,120}".join(
                                re.escape(p) for p in _parts)
                            if any(re.search(_pat, _ln)
                                   for _ln in rendered.splitlines()):
                                continue
                        problems.append(f"в {name} нет «{ln[:40]}»")
        rep.add("Колонтитулы воспроизведены (по spec)", not problems,
                "; ".join(problems) or "все строки header/footer из spec на месте")
        return
    # fallback без spec (режим --filled): прежние общие признаки
    problems = []
    if "Техническое задание" not in h:
        problems.append("в header нет «Техническое задание»")
    if "Заказчик" not in h:
        problems.append("в header нет «Заказчик»")
    if "@" not in f:
        problems.append("в footer нет контактов")
    if "Стр." not in f:
        problems.append("в footer нет нумерации страниц")
    rep.add("Колонтитулы воспроизведены", not problems,
            "; ".join(problems) or "header/footer на месте (титул, заказчик, контакты, поля)")


def check_filled_placeholders(doc, rep):
    """Режим --filled: в ИТОГОВОМ документе плейсхолдеров шаблона быть
    не должно. Разрешены только осознанные: место под скриншот и
    заглушки разделов, пропущенных пользователем («Пропустить»)."""
    allowed_pref = ("[СКРИНШОТ:", "[МЕСТО ДЛЯ СКРИНШОТА]",
                    "[ОГРАНИЧЕНИЯ И ДОПУЩЕНИЯ")
    bad = []
    for p in doc.paragraphs:
        for m in re.findall(r"\[[А-ЯЁA-Z][^[\]]{1,60}\]", p.text):
            if not m.startswith(allowed_pref):
                bad.append(m)
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                for m in re.findall(r"\[[А-ЯЁA-Z][^[\]]{1,60}\]", cell.text):
                    if not m.startswith(allowed_pref):
                        bad.append(m)
    bad = sorted(set(bad))
    rep.add("Плейсхолдеры заполнены (итоговый документ)", not bad,
            "заполнены или осознанные заглушки" if not bad
            else f"не заполнено: {bad[:8]}")


def _verify_report_enabled(template_path):
    """settings.yaml (cwd, рядом с шаблоном, уровень выше): verify_report.
    По умолчанию off — отчёт проверки одноразовый, в stdout."""
    import yaml
    cands = [os.path.join(os.getcwd(), "settings.yaml"),
             os.path.join(os.path.dirname(os.path.abspath(template_path)), "settings.yaml"),
             os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(template_path))),
                          "settings.yaml")]
    for c in cands:
        if os.path.exists(c):
            try:
                data = yaml.safe_load(open(c, encoding="utf-8")) or {}
            except Exception:
                continue
            return bool((data.get("settings") or {}).get("verify_report"))
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", nargs="?", help="путь к spec.json (не нужен в --filled)")
    ap.add_argument("template", help="путь к шаблону DOCX")
    ap.add_argument("-o", "--out", default="отчёт_проверки.md")
    ap.add_argument("--filled", action="store_true",
                    help="режим заполненного ТЗ: проверки плотности против spec пропускаются")
    ap.add_argument("--md", help="путь к Markdown ТЗ (нумерация по его структуре)")
    ap.add_argument("--png-only", action="store_true",
                    help="ТОЛЬКО рендер PNG любого DOCX (судье гейта 2: пары "
                         "«образец ↔ шаблон») — гейты не выполняются")
    ap.add_argument("--work", default=None,
                    help="корень рабочей папки (поиск format-agent)")
    args = ap.parse_args()

    _tpl_dir = os.path.dirname(os.path.abspath(args.template))
    if os.path.basename(os.path.dirname(_tpl_dir)) == "тз":
        # шаблон лежит в тз/<КОД> (папка пользователя) → кухня рядом не живёт:
        # temp с PNG — в проекты/<имя>/версии/<КОД>/temp
        _proj = os.path.dirname(os.path.dirname(_tpl_dir))
        out_dir = os.path.join(_proj, "версии", os.path.basename(_tpl_dir), "temp")
    else:
        out_dir = os.path.join(_tpl_dir, "temp")
    if args.png_only:
        out_dir = args.out  # в --png-only -o — папка для PNG
    os.makedirs(out_dir, exist_ok=True)

    if args.png_only:
        rep = Report()
        pngs = render_png(args.template, out_dir, rep)
        print(rep.render())
        print("[PNG] " + ("; ".join(pngs) if pngs else "нет страниц"))
        sys.exit(0 if pngs else 1)

    spec = None
    # --filled: spec не обязателен, но если передан — используется
    # (E-50: тех-ТЗ без TOC/подписей не должен ложить generic-проверки)
    if args.spec:
        with open(args.spec, encoding="utf-8") as fh:
            spec = json.load(fh)
        # pii=keep: шаблон собран с подставленными значениями —
        # ожидания гейта приводятся к тому же виду
        if (spec.get("meta") or {}).get("pii_mode") == "keep":
            from extract_spec import substitute_keep
            spec = substitute_keep(spec)
    doc = Document(args.template)

    rep = Report()
    if args.filled:
        # гейт заполненного ТЗ: нумерация, колонтитулы, оглавление, preflight, рендер
        check_file_name(args.template, spec, rep)
        check_header_footer(doc, rep, spec)
        check_toc(doc, rep, spec)
        check_numbering_xml(doc, rep)
        check_filled_placeholders(doc, rep)
    else:
        # элементный режим (spec.meta.elements): постраничные элементы не
        # несут тела/титула — соответствующие проверки не применимы
        elements = ((spec or {}).get("meta") or {}).get("elements")
        _PAGE = {"title-page", "toc", "header", "footer", "page-number",
                 "page-geometry", "first-page-diff"}
        body_mode = (elements is None
                     or any(e not in _PAGE for e in elements))
        title_mode = elements is None or "title-page" in elements
        check_header_footer(doc, rep, spec)
        if title_mode:
            check_signatures(doc, rep, spec)
        if body_mode:
            check_toc(doc, rep, spec)
        else:
            rep.add("Оглавление на отдельной странице, разделы с новой", True,
                    f"не применимо: тело не запрошено (элементы: {elements})")
        check_placeholders(doc, spec, rep)
        check_language(doc, spec, rep)
        check_numbering_xml(doc, rep)
        if body_mode:
            # Б10: standalone spec без density (None/нет ключа) — проверки
            # плотности пропускаются с пометкой, не падают TypeError/KeyError
            if spec.get("density"):
                check_table_rows(doc, spec, rep)
                check_density(doc, spec, rep)
            else:
                rep.add("Плотность = спецификации", True,
                        "пропущено: в spec нет density (standalone spec)")
            if elements is None:
                check_against_samples(doc, spec, rep)
            else:
                rep.add("Сверка с образцами (независимый пересчёт)", True,
                        f"не применима в элементном режиме (элементы: {elements})")

    # рендер (нужен для проверки нумерации + visual-judge)
    pngs = render_png(args.template, out_dir, rep)
    pdf = os.path.join(out_dir, "шаблон_preview.pdf")
    if os.path.exists(pdf):
        if args.filled:
            if args.md:
                import pymupdf
                pdf_doc = pymupdf.open(pdf)
                text = "\n".join(page.get_text() for page in pdf_doc)
                expected = _expected_numbers(_expected_numbers_md(args.md))
                missing = [e for e in expected
                           if not re.search(r"(?<![\d.])" + re.escape(e) + r"(?=\s|$)", text)]
                ok = not missing
                rep.add("Нумерация (рендер) по структуре Markdown", ok,
                        f"не найдено: {missing}" if missing
                        else f"все {len(expected)} номеров на месте")
        else:
            check_numbering_render(pdf, spec, rep)

    run_preflight(args.template, out_dir, rep, work=args.work)

    report_text = rep.render()
    print(report_text)

    # -o — путь к файлу отчёта. settings.yaml verify_report: off (умолчание) →
    # файл НЕ пишется (вердикт — в stdout, отчёт одноразовый); on → как раньше.
    if _verify_report_enabled(args.template):
        out_path = os.path.abspath(args.out)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write("# Отчёт проверки шаблона\n\n")
            fh.write(f"Шаблон: `{os.path.basename(args.template)}`\n\n")
            fh.write("```\n" + report_text + "\n```\n\n")
            if pngs:
                fh.write("## PNG для visual-judge\n\n")
                for p in pngs:
                    fh.write(f"- {p}\n")
    else:
        print("[ОТЧЁТ] не сохранён: settings.yaml verify_report: off "
              "(вердикт — выше в stdout; включить: verify_report: on)")

    sys.exit(1 if rep.failed else 0)



if __name__ == "__main__":
    main()