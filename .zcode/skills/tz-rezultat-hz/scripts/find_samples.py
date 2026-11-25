# -*- coding: utf-8 -*-
"""find_samples.py — поиск и классификация образцов DOCX (Шаг 3, п.1–3).

Скрипт сканирует папку и применяет правила исключений скилла сам;
модель читает готовый список кандидатов и задаёт вопрос пользователю.

Использование:
  python find_samples.py --folder <папка поиска> [--work <рабочая папка>]

Правила исключений (всегда НЕ образцы):
  - references/ внутри папки СКИЛЛА (документация скилла);
  - архивы (.zip/.rar/.7z — образцы сначала распаковать отдельно);
  - temp/;
  - projects/ ЧУЖИХ проектов (кроме references/ активного проекта).

Вывод: [КАНДИДАТ] путь  /  [ИСКЛЮЧЁН] путь — причина  /  итог-счётчик.
"""

import argparse
import os
import sys

_EXCLUDE_DIRS = {"temp", ".zcode", ".git", "__pycache__", "node_modules", "portable"}
_ARCHIVE_EXT = {".zip", ".rar", ".7z", ".tar", ".gz"}
_DOCX_EXT = ".docx"
_SKIP_DIRS_NAME = {"references", "версии", "profiles", "тз"}

# Решение 2026-11-20: при известном типе документа вопрос «Это
# образцы?» — только по образцам этого типа (фильтр по имени файла).
_TYPE_HINTS = {
    "business": lambda fn: "_ТЗ_" in fn,            # Заказчик_ТЗ_КОД_V…
    "tech": lambda fn: fn.startswith("Приложение к ТЗ "),
}


def classify(root, folder):
    """True — папку сканируем, False — пропускаем."""
    return folder not in _EXCLUDE_DIRS and not folder.startswith(".")


def scan(folder):
    candidates, excluded = [], []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if classify(dirpath, d)]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            ext = os.path.splitext(fn)[1].lower()
            if ext == _DOCX_EXT and not fn.startswith("~$"):
                candidates.append(os.path.abspath(p))
            elif ext in _ARCHIVE_EXT:
                excluded.append((os.path.abspath(p), "архив — распаковать, образцы отдельно"))
    return candidates, excluded


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True, help="где искать образцы")
    ap.add_argument("--work", default=None, help="рабочая папка (для пометки чужих projects/)")
    ap.add_argument("--type", default=None, choices=["business", "tech"],
                    help="известный тип документа: фильтр образцов по имени "
                         "(business → «*_ТЗ_*», tech → «Приложение к ТЗ *»)")
    args = ap.parse_args()

    if not os.path.isdir(args.folder):
        print(f"[ИТОГ] папка не существует: {args.folder}")
        return

    candidates, excluded = scan(args.folder)
    if args.type:
        check = _TYPE_HINTS[args.type]
        candidates = [p for p in candidates if check(os.path.basename(p))]
        excluded = [x for x in excluded if check(os.path.basename(x[0]))]
        print(f"[ТИП] {args.type} — вопрос «Это образцы?» ТОЛЬКО по этим "
              f"образцам; образцы другого типа НЕ упоминаются.")
    for p in sorted(candidates):
        print(f"[КАНДИДАТ] {p}")
    for p, why in sorted(excluded):
        print(f"[ИСКЛЮЧЁН] {p} — {why}")

    print(f"[ИТОГ] кандидатов: {len(candidates)}; исключено: {len(excluded)}")
    if not candidates:
        print("[ИТОГ] DOCX не найдены → вопрос про references/ ДОСЛОВНО из "
              "references/question-packs.ru.md §3; папку без ответа НЕ создавать.")
    else:
        print("[ИТОГ] модель: задать «Это образцы?» (Да / Нет / Другая папка) — "
              "работать только после подтверждения пользователя.")


if __name__ == "__main__":
    main()
