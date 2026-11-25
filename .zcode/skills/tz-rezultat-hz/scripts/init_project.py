# -*- coding: utf-8 -*-
"""init_project.py — создание проекта и перенос образцов (Шаг 3, п.4).

Один вызов вместо цепочки mkdir/mv/правки манифеста. Идемпотентен:
повторный запуск дубль НЕ создаёт (манифест — источник правды).

Использование:
  python init_project.py --work <рабочая папка> --name <имя проекта> \
      --samples <папка с подтверждёнными образцами> [--customer <заказчик>]

Действия: projects.yaml (создать/дописать) → projects/<имя>/{references,
версии, profiles} → ПЕРЕМЕСТИТЬ *.docx из --samples в references/.
"""

import argparse
import os
import shutil
import sys

try:
    from yaml import safe_dump, safe_load
except ImportError:
    print("[FAIL] pyyaml не установлен — pip install pyyaml (спросить пользователя)")
    sys.exit(0)


def _line(status, msg):
    print(f"[{status}] {msg}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--name", required=True, help="имя проекта КАК В ДОКУМЕНТАХ")
    ap.add_argument("--samples", required=True, help="папка с подтверждёнными образцами")
    ap.add_argument("--customer", default="")
    args = ap.parse_args()

    proj_dir = os.path.join(args.work, "projects", args.name)
    ref_dir = os.path.join(proj_dir, "references")
    manifest = os.path.join(args.work, "projects.yaml")
    settings_path = os.path.join(args.work, "settings.yaml")

    for d in (ref_dir, os.path.join(proj_dir, "версии"),
              os.path.join(proj_dir, "тз"), os.path.join(proj_dir, "profiles")):
        os.makedirs(d, exist_ok=True)
    _line("OK", f"структура: {proj_dir} (+references, версии, тз, profiles)")

    # settings.yaml — пользовательские настройки конвейера (off по умолчанию)
    if not os.path.exists(settings_path):
        with open(settings_path, "w", encoding="utf-8") as f:
            f.write("settings:"
                    + chr(10)
                    + "  verify_report: off   # отчёт_проверки.md рядом с результатом (on/off)"
                    + chr(10))
        _line("OK", "settings.yaml создан (verify_report: off)")

    data = {"projects": []}
    if os.path.exists(manifest):
        with open(manifest, encoding="utf-8") as f:
            data = safe_load(f) or {"projects": []}
    projects = data.setdefault("projects", [])
    entry = next((p for p in projects if isinstance(p, dict) and p.get("name") == args.name), None)
    if entry is None:
        entry = {"name": args.name, "customer": args.customer, "created": ""}
        projects.append(entry)
        _line("OK", "запись в projects.yaml добавлена")
    else:
        _line("OK", "проект уже в манифесте — дубль не создан")
    if args.customer:
        entry["customer"] = args.customer
    with open(manifest, "w", encoding="utf-8") as f:
        safe_dump(data, f, allow_unicode=True, sort_keys=False)

    moved = skipped = 0
    biz_dir = os.path.join(ref_dir, "business")
    tech_dir = os.path.join(ref_dir, "tech")
    os.makedirs(biz_dir, exist_ok=True)
    os.makedirs(tech_dir, exist_ok=True)
    # РЕКУРСИВНЫЙ обход --samples (дефект 2026-11-20: сканировался
    # только верхний уровень — эталонная раскладка references/business/
    # + references/tech/ не находилась вовсе, в проект переезжала часть)
    for dirpath, dirnames, filenames in os.walk(args.samples):
        dirnames[:] = [d for d in dirnames
                       if d not in ("temp", ".zcode", ".git", "__pycache__")
                       and not d.startswith(".")]
        for fn in sorted(filenames):
            src = os.path.join(dirpath, fn)
            if (not os.path.isfile(src)
                    or os.path.splitext(fn)[1].lower() != ".docx"
                    or fn.startswith("~$")):
                continue
            # раскладка-эталон: references/business/ — бизнес-ТЗ,
            # references/tech/ — тех-ТЗ (решение 2026-11-20)
            dst = os.path.join(
                tech_dir if fn.startswith("Приложение к ТЗ ") else biz_dir, fn)
            if os.path.exists(dst):
                skipped += 1
                continue
            shutil.move(src, dst)
            moved += 1
    _line("OK", f"образцы перемещены в references/ (business/tech): {moved}; уже там: {skipped}")

    # Детект КОД из имён образцов (Заказчик_ТЗ_КОД_V…, Приложение к ТЗ КОД_V…,
    # КОД_V…) → новые КОДы (нет папки тз/<КОД>) — вопрос пользователю:
    # «такого ТЗ ещё нет в библиотеке — это новое ТЗ?»
    import re as _re
    codes = []
    for sub in ("business", "tech"):
        sub_dir = os.path.join(ref_dir, sub)
        for fn in sorted(os.listdir(sub_dir)) if os.path.isdir(sub_dir) else []:
            m = (_re.match(r".*_ТЗ_(.+?)_V\d", fn)
                 or _re.match(r"Приложение к ТЗ (.+?)_V\d", fn)
                 or _re.match(r"(.+?)_V\d", fn))
            if m and not fn.startswith("~$") and m.group(1) not in codes:
                codes.append(m.group(1))
    tz_dir = os.path.join(proj_dir, "тз")
    # D10 (прогон -59): коды из имён ОБРАЗЦОВ — это существующие ТЗ
    # библиотеки, НЕ новое ТЗ доработки; «НОВОЕ ТЗ» по ним не печатается
    # (шум вводил в заблуждение). КОД нового ТЗ — вопрос мегапакета §2 п.4.
    for code in codes:
        if os.path.isdir(os.path.join(tz_dir, code)):
            _line("OK", f"ТЗ {code} — есть в тз/")

    if os.path.isdir(args.samples) and not any(os.scandir(args.samples)):
        os.rmdir(args.samples)
        _line("OK", "исходная папка образцов пуста — удалена")
    _line("ИТОГ", "разбор образцов вести из projects/<имя>/references/")


if __name__ == "__main__":
    main()
