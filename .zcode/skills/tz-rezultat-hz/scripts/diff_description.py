# -*- coding: utf-8 -*-
"""diff_description.py — доработка описания после первой приёмки (run-59).

Дефект прогона -59: после правок аналитик повторно вставлял ЦЕЛОЕ описание
в чат — модель теряла контекст, что именно изменилось. Скрипт печатает
ТОЛЬКО изменённые фрагменты (строки: «+ добавлено» / «- удалено»), чтобы
модель видела дельту, а не документ целиком.

Вызов:
  python diff_description.py <old.md> <new.md>
  python diff_description.py --old <файл> (--new <файл> | --new-text «<текст>»)

Код возврата: 0 — дельта напечатана (включая «Изменений нет»).
"""

import argparse
import difflib
import os
import sys


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    # позиционные (официальный тест test_run59_new_scripts.py)
    ap.add_argument("old_pos", nargs="?", default=None,
                    help="файл утверждённого описания (старая версия)")
    ap.add_argument("new_pos", nargs="?", default=None,
                    help="файл нового описания")
    # флаги (альтернативный интерфейс)
    ap.add_argument("--old", default=None, help="файл утверждённого описания")
    ap.add_argument("--new", default=None, help="файл нового описания")
    ap.add_argument("--new-text", default=None,
                    help="новое описание текстом (вместо --new)")
    args = ap.parse_args()

    old_path = args.old or args.old_pos
    new_path = args.new or args.new_pos

    if not old_path:
        print("нужен old: позиционный аргумент или --old")
        sys.exit(1)
    if args.new and args.new_text is not None:
        print("[FAIL diff_description] задано и --new, и --new-text — нужен один")
        sys.exit(1)
    if new_path:
        new_text = _read(new_path)
    elif args.new_text is not None:
        new_text = args.new_text
    else:
        print("нужен new: позиционный аргумент, --new или --new-text")
        sys.exit(1)

    old_text = _read(old_path)
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    changed = [ln for ln in difflib.unified_diff(old_lines, new_lines,
                                                  n=0, lineterm="")
               if ln.startswith("+") or ln.startswith("-")]
    if not changed:
        print("Изменений нет — описание не менялось")
        sys.exit(0)
    print("Изменённые фрагменты: «+» добавлено, «-» удалено")
    for ln in changed:
        print(ln)
    sys.exit(0)


if __name__ == "__main__":
    main()