# -*- coding: utf-8 -*-
"""check_progress.py — «где я в процессе» (process-flow, 2026-11-23).

прогресс.json в рабочей папке пишут ТОЛЬКО скрипты-гейты (никогда —
модель). Скрипт сверяет записи с файлами на диске и печатает по-русски:
что сделано + ПЕРВЫЙ незакрытый шаг + чего не хватает. Вызов: перед
началом каждого шага, после любой остановки и при возобновлении
(в т.ч. в новой сессии) — продолжение только по его выводу, не по памяти.

Exit 1 — вход следующего шага не выполнен (или расхождение: запись
«готово», а файла на диске нет), 0 — все 8 шагов закрыты.
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tz_common import setup_utf8_stdout

# DAG шагов (process.md / SKILL.md Steps 1–8): для каждого шага —
# относительные артефакты-выходы (glob относительно --work). Нуль
# артефактов = шаг закрыт только записью гейта. Шаг 6: бизнес-ТЗ
# обходится без obj-map.json (doc_type из проекта).
_STEPS = [
    ("1", "preflight (окружение, связка конфигурации)",
     ["settings.yaml", "projects/*.yaml"]),
    ("2", "диалог: скан → исследование → пакеты вопросов → гейт §6",
     ["projects/*/версии/*/вопросы_ответы_*.md"]),
    ("3", "образцы и проект (init_project)",
     ["projects/*/references"]),
    ("4", "разбор образцов (spec.json)",
     ["projects/*/версии/*/версия-*/spec.json"]),
    ("5", "сборка шаблона (гейты 1–2)",
     ["projects/*/версии/*/версия-*/шаблон_ТЗ_1С.docx"]),
    ("6", "карта объектов (check_map)",
     ["projects/*/версии/*/версия-*/obj-map.json"]),
    ("7", "текст: минипрофили → черновик → линт → рендер",
     ["projects/*/версии/*/версия-*/draft.md"]),
    ("8", "завершение (final_gate, раскладка, итог)",
     ["projects/*/тз/*/*.docx"]),
]
_BUSINESS_SKIP_STEP = "6"  # бизнес-ТЗ: карта lite, без obj-map.json


def _load_records(path):
    """прогресс.json → список записей; файл пишут только скрипты."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("records") or []
    except (json.JSONDecodeError, OSError):
        return []


def _is_business(work):
    for p in glob.glob(os.path.join(work, "projects", "*.yaml")):
        try:
            txt = open(p, encoding="utf-8").read()
        except OSError:
            continue
        if "doc_type" in txt and "бизнес" in txt:
            return True
    return False


def check_progress(work):
    """→ (exit_code, строка сводки). Записи сверяются с диском."""
    records = _load_records(os.path.join(work, "прогресс.json"))
    business = _is_business(work)
    done_steps = set()
    mismatches = []
    if records:
        for r in records:
            step = str(r.get("step"))
            arts = r.get("artifacts") or []
            missing = [a for a in arts if not os.path.exists(a)]
            if r.get("verdict") == "PASS" and not missing:
                done_steps.add(step)
            elif missing:
                mismatches.append((step, missing))

    lines = []
    all_ok = True
    next_info = None
    for sid, title, pats in _STEPS:
        if business and sid == _BUSINESS_SKIP_STEP:
            lines.append(f"Шаг {sid} ({title}) — не требуется (бизнес-ТЗ)")
            continue
        arts = sorted({a for pat in pats for a in
                       glob.glob(os.path.join(work, *pat.split("/")))})
        art_missing = not arts
        rec_missing = sid not in done_steps
        if not rec_missing and not art_missing:
            lines.append(f"Шаг {sid} ({title}) — сделано")
            continue
        all_ok = False
        if next_info is None:
            next_info = (sid, title, art_missing, rec_missing)

    if mismatches:
        for sid, missing in mismatches:
            lines.append(f"[РАСХОЖДЕНИЕ] запись шага {sid} говорит «готово», "
                         f"но файла на диске нет: {missing[0]} — шаг НЕ закрыт")
        all_ok = False

    if next_info is None and all_ok:
        print("\n".join(lines))
        print("[ИТОГ] все шаги закрыты — процесс завершён.")
        return 0

    print("\n".join(lines))
    if next_info:
        sid, title, art_missing, rec_missing = next_info
        why = []
        if art_missing:
            pats = dict((s, p) for s, _, p in _STEPS)[sid]
            why.append("нет артефакта на диске (" + ", ".join(pats) + ")")
        if rec_missing:
            why.append("нет записи гейта в прогресс.json")
        print(f"[ИТОГ] exit 1 — следующий незакрытый шаг {sid} ({title}); "
              f"не хватает: {'; '.join(why)}. Продолжать только с него.")
    return 1


def main():
    setup_utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True, help="рабочая папка проекта")
    args = ap.parse_args()
    sys.exit(check_progress(os.path.abspath(args.work)))


if __name__ == "__main__":
    main()
