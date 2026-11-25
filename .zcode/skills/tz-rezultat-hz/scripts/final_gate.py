# -*- coding: utf-8 -*-
"""final_gate.py — ЕДИНЫЙ ФИНАЛЬНЫЙ ГЕЙТ (E-53).

Один вызов в конце работы агента: скрипт сам запускает ВСЕ проверки
конвейера и добавляет сквозные, которых раньше не было, — отчёт
«абсолютно все несоответствия, в любых вариациях», код возврата 0/1.

Запускает (та же папка scripts):
  1. check_map.py  — G7–G10, G17 (если --map дан);
  2. lint_draft.py — G1–G6, G11 (если --draft дан);
  3. verify_template.py --filled — гейты итогового DOCX (если --spec дан);
  4. check_language.py — язык проверки правописания итогового DOCX
     (блок НЕ пропускается: с чужим языком аналитик правит документ
     вслепую — Word подчёркивает русский текст красным);
  5. СОБСТВЕННЫЕ сквозные проверки F1–F11 — итоговый DOCX против
     spec/map/draft (см. ниже).

F-проверки (то, что раньше не проверял никто):
  F1 пример-строки-спутники «[пример: …]» в итоговом DOCX (ЛЮБОЙ регистр —
     гейт плейсхолдеров ловит только заглавные);
  F2 заглушки «Пропустить» и служебные пометки «уточнить по конфигурации»
     в итоговом DOCX (служебное в документ не попадает);
  F3 пустые разделы: H1 без единого абзаца/списка/таблицы под ним и без
     легального «не предполагается»;
  F4 заголовки H1 итогового DOCX = заголовкам spec.sections (состав и
     порядок; потерянный/лишний/переставленный раздел — FAIL);
  F5 карта ↔ DOCX: каждый объект карты (id и синоним) упомянут в тексте
     (потерянный при переносе объект — FAIL);
  F6 карта ↔ DOCX: сценариев бэкенда в карте > 0 → в DOCX есть
     «Событие:» и шаги Дано/Когда/Тогда, причём событий >= сценариев;
  F7 первая строка тела итогового DOCX = «Приложение к ТЗ <КОД>» для
     тех-ТЗ (код из имени файла);
  F8 «Рисунок - N» в итоговом DOCX: ссылка без подписи и подпись без
     ссылки (аналог G4, но по готовому документу);
  F9 черновик ↔ DOCX: каждый непустой абзац черновика присутствует в
     DOCX (ручная правка DOCX в обход рендера — FAIL).

Использование:
  python final_gate.py <итог.docx> --spec <spec.json> --draft <draft.md>
                       [--map <obj-map.json>] [--config ext=<cfe>]
                       [--config main=<cf>]

Код возврата 0 — всё чисто; 1 — есть нарушения (полный список в отчёте).
Визуальную приёмку (гейт 2) скрипт не заменяет: она отдельная.
"""

import argparse
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tz_common import lang_tag  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_PY = sys.executable


def _docx_paragraphs(docx_path):
    """Все непустые абзацы итогового DOCX (таблицы — по \n в ячейках)."""
    from docx import Document
    doc = Document(docx_path)
    paras = []
    for p in doc.paragraphs:
        t = p.text.strip()
        if t:
            paras.append(t)
    return paras, doc


def _f_checks(docx_path, spec, draft_text, m, plan=None):
    problems = []
    paras, doc = _docx_paragraphs(docx_path)
    joined = "\n".join(paras)
    # индексы абзацев-заголовков H1 и границы разделов (для F10/F11)
    h1_idx = [i for i, p in enumerate(doc.paragraphs)
              if (p.style.name or "").lower().startswith(("heading 1", "заголовок 1"))]
    def _sec_of(i):
        for k, s in enumerate(h1_idx):
            if i <= s:
                return k - 1
        return len(h1_idx) - 1
    def _sec_text(k):
        if k < 0 or k >= len(h1_idx):
            return ""
        j = h1_idx[k + 1] if k + 1 < len(h1_idx) else len(doc.paragraphs)
        return "\n".join(p.text for p in doc.paragraphs[h1_idx[k]:j])

    # F1 пример-строки и незаполненные плейсхолдеры (любой регистр)
    for t in paras:
        if re.search(r"\[(пример|ПРИМЕР)\s*:", t) or \
                re.match(r"^\[[А-ЯЁA-Z][А-ЯЁA-Zа-яё ]+\s*\|", t):
            problems.append(f"[F1] пример-строка/плейсхолдер в итоговом DOCX: "
                            f"«{t[:80]}» — рендер обязан был удалить.")

    # F2 заглушки и служебные пометки
    for t in paras:
        if t == "Пропустить" or re.search(r"уточнить по конфигурации", t, re.I):
            problems.append(f"[F2] заглушка/служебная пометка в DOCX: «{t[:80]}».")

    # F4 заголовки H1 против spec.sections
    spec_h1 = [s.get("title", "") for s in spec.get("sections", [])
               if s.get("level") == 1]
    # нумерация в spec уже в заголовке («1. Источник…»); в DOCX берём
    # абзацы со стилем Heading 1
    doc_h1 = []
    for p in doc.paragraphs:
        st = (p.style.name or "").lower()
        if st.startswith("heading 1") or st.startswith("заголовок 1"):
            t = p.text.strip()
            if t:
                doc_h1.append(t)
    def _norm(s):
        s = re.sub(r"^\s*\d+(?:\.\d+)*\.?\s*", "", s)
        return re.sub(r"\s+", " ", s).strip().lower().rstrip(".")
    a = [_norm(x) for x in spec_h1]
    b = [_norm(x) for x in doc_h1]
    if sorted(a) != sorted(b):
        lost = [x for x in a if x not in b]
        extra = [x for x in b if x not in a]
        problems.append(f"[F4] состав разделов H1 не совпадает со spec: "
                        f"потеряны {lost or '—'}, лишние {extra or '—'}.")
    elif plan:
        # план есть: порядок обязан совпадать с планом (E-55)
        pa = [_norm(e["title"]) for e in plan if e.get("level") == 1]
        if pa != b:
            problems.append(f"[F4] порядок/состав H1 не совпадает с планом "
                            f"(plan.json): план {pa}, DOCX {b}.")
    elif a != b:
        # плана нет: состав тот же, порядок другой — предупреждение
        print(f"[F4-ПРЕДУПРЕЖДЕНИЕ] порядок H1 отличается от spec (состав "
              f"совпадает): DOCX {b} — постройте план (plan_sections.py), "
              f"порядок должен задаваться конвейером, не моделью.")

    # F10 «первое упоминание = раздел создания» (E-55): объект со статусом
    # «новый» обязан впервые появиться в разделе создания (ранг 1–2 плана),
    # не позже (в алгоритмах/формах)
    if m and plan:
        ranks = [e.get("rank") for e in plan if e.get("level") == 1]
        create_secs = {k for k, r in enumerate(ranks) if r in (1, 2)}
        # «Источник» (ранг 0) — дословное описание доработки: новый объект
        # упомянут там ВСЕГДА (урок V9, 2026-11-19), это не «первое
        # упоминание» в смысле проверки
        skip_secs = {k for k, r in enumerate(ranks) if r == 0}
        for o in m.get("objects") or []:
            if o.get("status") != "новый":
                continue
            names = [o.get("id", ""), o.get("synonym", "")]
            first = None
            for i, p in enumerate(doc.paragraphs):
                if any(n and n in p.text for n in names) \
                        and _sec_of(i) not in skip_secs:
                    first = _sec_of(i)
                    break
            if first is not None and first not in create_secs:
                problems.append(f"[F10] объект «{o.get('id')}» впервые упоминается "
                                f"вне разделов создания (раздел {first + 1}) — "
                                f"ТЗ читается сверху вниз: сначала создание "
                                f"(rank 1–2 плана), потом логика.")
        # F11 затронутые элементы формы → рисунок (E-55): скрины тех-ТЗ
        # показывает затронутое, немного; источник — карта, не бизнес-ТЗ
        form_ranks = {k for k, r in enumerate(ranks) if r == 3}
        for f_ in m.get("forms") or []:
            touched = (f_.get("new_elements") or []) + (f_.get("changed_elements") or [])
            if not touched:
                continue
            ftext = "\n".join(_sec_text(k) for k in form_ranks)
            if not re.search(r"\(Рисунок\s*-\s*\d+\)", ftext):
                problems.append(f"[F11] затронутые элементы формы «{f_.get('owner')}.{f_.get('name')}» "
                                f"без рисунка — новый/изменённый элемент должен быть "
                                f"показан на скрине («(Рисунок - N)» + подпись в "
                                f"разделе форм).")
            for el in touched:
                if not el:
                    continue
                # матчинг по кавычковым фрагментам («Период», «Открыть месяц…»):
                # строка элемента в карте — свободная формулировка
                frags = [q for q in re.findall(r"«([^»]{3,})»", el)]
                probes = frags or [el]
                # без кавычек в карте — эвристика: достаточно 2 значимых слов
                if not frags:
                    words = [w for w in re.findall(r"[А-Яа-яёЁA-Za-z]{5,}", el)]
                    probes = [f"{a}.*{b}" for a in words[:3] for b in words[:3]
                              if a != b] or [el]
                if not any(re.search(pr, joined) for pr in probes):
                    problems.append(f"[F11] элемент карты «{el}» не описан в DOCX.")


    # F3 пустые разделы (после F4 состав совпадает): между H1 и следующим
    # H1 нет ни одного абзаца
    idx = [i for i, p in enumerate(doc.paragraphs)
           if (p.style.name or "").lower().startswith(("heading 1", "заголовок 1"))]
    for k, i in enumerate(idx):
        j = idx[k + 1] if k + 1 < len(idx) else len(doc.paragraphs)
        body = [p.text.strip() for p in doc.paragraphs[i + 1:j] if p.text.strip()]
        body += [c.text.strip() for t_ in doc.tables for row in t_.rows
                 for c in row.cells if c.text.strip()]
        if not body:
            problems.append(f"[F3] пустой раздел «{doc.paragraphs[i].text.strip()}» — "
                            f"нет ни текста, ни «… не предполагается.»")

    # F5 объекты карты в тексте
    if m:
        for o in m.get("objects") or []:
            if o.get("id") and o["id"] not in joined and \
                    (o.get("synonym") or "") not in joined:
                problems.append(f"[F5] объект карты «{o['id']}» не упомянут в "
                                f"итоговом DOCX ни именем, ни синонимом — "
                                f"потерян при переносе.")
        # F6 сценарии бэкенда
        backend = m.get("backend") or []
        if backend:
            n_events = len(re.findall(r"^\s*Событие\s*:", joined, re.M))
            if n_events < len(backend):
                problems.append(f"[F6] в карте {len(backend)} сценариев бэкенда, "
                                f"в DOCX «Событие:» {n_events} — сценарии потеряны.")
            # Б7: формат O5u — блоки Условие/Событие/Алгоритм/Результат;
            # подстроки «Когда»/«Тогда» НЕ требуем (G13 запрещает строки,
            # начинающиеся с них — требование подстрок вынуждало обходные
            # формулировки «… . Когда … . Тогда …»)
            _blocks = len(re.findall(r"^\s*(?:Условие|Событие|Алгоритм|Результат)\s*:",
                                     joined, re.M))
            if _blocks == 0:
                problems.append("[F6] сценария в формате O5u нет в DOCX — "
                                "алгоритмы должны быть блоками Условие / "
                                "Событие / Алгоритм / Результат (§4.2).")

    # F7 первая строка тела тех-ТЗ
    meta = spec.get("meta") or {}
    if meta.get("doc_type") == "техническое ТЗ" and paras:
        code_m = re.search(r"([А-ЯЁ]{2,4}(?:\.[А-ЯЁ0-9]+)+-\d+)",
                           os.path.basename(docx_path))
        if code_m and f"Приложение к ТЗ {code_m.group(1)}" != paras[0]:
            problems.append(f"[F7] первая строка тела «{paras[0][:60]}» ≠ "
                            f"«Приложение к ТЗ {code_m.group(1)}».")

    # F8 рисунки в DOCX
    refs = set(int(n) for n in re.findall(r"\(Рисунок\s*-\s*(\d+)\)", joined))
    caps = set(int(n) for n in re.findall(r"^Рисунок\s*-\s*(\d+)\s+\S", joined, re.M))
    for n in sorted(refs - caps):
        problems.append(f"[F8] «(Рисунок - {n})» в DOCX без подписи.")
    for n in sorted(caps - refs):
        problems.append(f"[F8] подпись «Рисунок - {n}» в DOCX без ссылки.")

    # F9 черновик → DOCX без потерь (нормализованные абзацы как подстроки)
    if draft_text:
        norm = lambda s: re.sub(r"\s+", " ", s).strip()
        doc_norm = [norm(t) for t in paras]
        doc_join = "\n".join(doc_norm)
        draft_paras = [norm(x) for x in draft_text.splitlines()
                       if norm(x) and not norm(x).startswith("#")
                       and not norm(x).startswith("|")
                       and not norm(x).startswith("-")]
        for dp in draft_paras:
            if len(dp) >= 20 and dp not in doc_join:
                problems.append(f"[F9] абзац черновика отсутствует в DOCX "
                                f"(правка DOCX в обход рендера или потеря?): "
                                f"«{dp[:70]}…».")
    return problems


def check_progress_records(claimed_steps, progress_path):
    """process-flow: кросс-чек «заявлено готово ↔ запись в прогресс.json».
    Шаг из claimed_steps без записи PASS-гейта в прогресс.json → FAIL
    (заявление модели без записи скрипта не существует)."""
    problems = []
    records = []
    try:
        import json as _json
        with open(progress_path, encoding="utf-8") as fh:
            records = (_json.load(fh) or {}).get("records") or []
    except (OSError, ValueError):
        records = []
    done = {str(r.get("step")) for r in records
            if r.get("verdict") == "PASS"}
    for s in claimed_steps:
        if s not in done:
            problems.append(f"[ПРОГРЕСС] шаг {s} заявлен выполненным, но записи "
                            f"гейта в прогресс.json нет → шаг НЕ закрыт.")
    return problems


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("docx", help="итоговый DOCX")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--draft", default=None, help="черновик draft.md")
    ap.add_argument("--map", default=None, help="obj-map.json (если строился)")
    ap.add_argument("--plan", default=None,
                    help="plan.json из plan_sections.py (рекомендуется)")
    ap.add_argument("--config", action="append", default=[],
                    help="выгрузка 1С «метка=путь» (ext|main), расширение ПЕРВЫМ")
    ap.add_argument("--figs", default=None,
                    help="JSON {номер: описание} рисунков — как --figs "
                         "render_md; передаётся в lint (G4 не требует подписи "
                         "в draft — её ставит рендер) (E-57)")
    ap.add_argument("--skip", nargs="*", default=[],
                    help="пропустить блоки: map lint filled fchecks")
    ap.add_argument("--work", default=None,
                    help="рабочая папка: передаётся в verify_template (--work)")
    ap.add_argument("--progress", default=None,
                    help="прогресс.json: кросс-чек шагов 1–7 + запись шага 8 при PASS")
    args = ap.parse_args()

    failures = []  # (блок, кол-во нарушений)

    def run_block(name, cmd):
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        out = (r.stdout or "") + (r.stderr or "")
        if out.strip():
            print(out.strip())
        return r.returncode, out

    base = [_PY, os.path.join(_HERE, "check_map.py")]
    lint_cmd = [_PY, os.path.join(_HERE, "lint_draft.py")]
    filled_cmd = [_PY, os.path.join(_HERE, "verify_template.py"),
                  args.spec, args.docx, "--filled"]
    if args.draft:
        filled_cmd += ["--md", args.draft]
    if args.work:
        filled_cmd += ["--work", args.work]
    for c in args.config:
        lint_cmd += ["--config", c]
        base += ["--config", c]
    if args.figs:
        lint_cmd += ["--figs", args.figs]

    if args.map and "map" not in args.skip:
        rc, _ = run_block("map", base + [args.map, "--spec", args.spec])
        if rc != 0:
            failures.append(("map (G7–G10, G17)", None))
    if args.draft and "lint" not in args.skip:
        lint_args = [args.draft, "--spec", args.spec]
        # карта передаётся линту: G6 пропускает «новые» объекты (урок V9-2,
        # sess_54d8495b 2026-11-20)
        if args.map:
            lint_args += ["--map", args.map]
        rc, out = run_block("lint", lint_cmd + lint_args)
        if rc != 0 or "нарушений нет" not in out:
            failures.append(("lint (G1–G6, G11)", None))
    if "filled" not in args.skip:
        rc, out = run_block("filled", filled_cmd)
        if rc != 0 or re.search(r"ИТОГ:\s*FAIL", out):
            mfail = re.search(r"FAIL \((\d+)/(\d+) проверок\)", out)
            failures.append(("filled (verify_template)",
                             mfail.group(1) if mfail else None))

    # ЯЗЫК ДОКУМЕНТА (2026-11-25) — блок не пропускается: язык проверки
    # правописания итогового DOCX (образцы приносят чужой язык Word
    # заказчика; без проверки аналитик правит документ вслепую).
    try:
        import json as _json
        with open(args.spec, encoding="utf-8") as fh:
            _meta = (_json.load(fh) or {}).get("meta") or {}
    except (OSError, ValueError):
        _meta = {}
    _lang = lang_tag(_meta.get("language"))
    rc, out = run_block("lang", [_PY, os.path.join(_HERE, "check_language.py"),
                                 args.docx, "--lang", _lang])
    if rc != 0:
        mlang = re.search(r"ИТОГ ЯЗЫК\] FAIL \((\d+)\)", out)
        failures.append((f"язык документа (check_language, {_lang})",
                         mlang.group(1) if mlang else None))

    if "fchecks" not in args.skip:
        import json
        with open(args.spec, encoding="utf-8") as fh:
            spec = json.load(fh)
        draft_text = ""
        if args.draft and os.path.exists(args.draft):
            with open(args.draft, encoding="utf-8") as fh:
                draft_text = fh.read()
        m = None
        if args.map and os.path.exists(args.map):
            with open(args.map, encoding="utf-8") as fh:
                m = json.load(fh)
        plan = None
        if args.plan and os.path.exists(args.plan):
            with open(args.plan, encoding="utf-8") as fh:
                plan = json.load(fh)
        problems = _f_checks(args.docx, spec, draft_text, m, plan)
        if problems:
            print(f"[F-ПРОВЕРКИ] нарушений: {len(problems)}")
            for p in problems:
                print(p)
            failures.append(("fchecks (F1–F9)", len(problems)))
        else:
            print("[F-ПРОВЕРКИ] нарушений нет (F1–F9).")

    # раскладка файлов (урок 2026-11-19): итог должен лежать в тз/<КОД>/
    import check_layout
    # итог: projects/<имя>/тз/<КОД>/x.docx (или ещё в версиях) → корень проекта
    _p = os.path.abspath(args.docx)
    _proj = None
    for _up in range(6):
        _p = os.path.dirname(_p)
        if os.path.basename(os.path.dirname(_p)) == "projects":
            _proj = _p
            break
    if _proj:
        check_layout.OUT.clear()
        check_layout.check_project(_proj, os.path.dirname(os.path.dirname(_proj)))
        for ln in check_layout.OUT:
            if not ln.startswith("[OK"):
                print(ln)
                if ln.startswith("[FAIL"):
                    failures.append(("[check_layout]", 1))

    print("=" * 60)
    if failures:
        print(f"[ИТОГ final_gate] БЛОКОВ С НАРУШЕНИЯМИ: {len(failures)}")
        for name, n in failures:
            print(f"  ✗ {name}" + (f" — нарушений {n}" if n else ""))
        print("Править черновик/карту → перегнать рендер → final_gate снова. "
              "Текст НЕ считается готовым до [ИТОГ final_gate] без нарушений.")
        sys.exit(1)
    if args.progress:
        _prog = check_progress_records([str(n) for n in range(1, 8)],
                                       args.progress)
        for _p in _prog:
            print(_p)
        if _prog:
            print("[ИТОГ final_gate] прогресс неполный — заявленный шаг без "
                  "записи гейта; закрыть шаги (check_progress.py) и перезапустить.")
            sys.exit(1)
    print("[ИТОГ final_gate] все блоки чисты: карта, линт, гейты DOCX, "
          "язык документа, сквозные F1–F11. Дальше — только визуальная "
          "приёмка (гейт 2).")
    # process-flow: шаг 8 закрыт записью гейта в прогресс.json (не моделью)
    from tz_common import record_progress
    record_progress(args.progress, "8", "final_gate", "PASS", [args.docx])


if __name__ == "__main__":
    main()
