# -*- coding: utf-8 -*-
"""check_description.py — гейт описания доработки перед Шагом 2
(openspec description-gate-script, 2026-11-22).

Дефект sess_b6a7f172: агент начал исследование без реального описания
доработки — сам выбрал её по скану. Текстовые инструкции не работают;
механизм — скрипт по образцу find_config.py: код 42 = «остановиться и
выполнить дословное предписание».

Проверяет `описание_доработки.md` в корне рабочей папки:
  нет файла / маркер-заполнитель / короче DESC_MIN_LEN → код 42 +
  дословное предписание (задать аналитику РОВНО ОДИН вопрос и ждать).
  реальное описание → «описание есть», код 0.

Вызов: python check_description.py --work <рабочая папка>
"""

import argparse
import os
import sys

DESC_FILE = "описание_доработки.md"
DESC_MIN_LEN = 200  # ≈ одно осмысленное предложение (правка при ложном срабатывании)
PLACEHOLDER_MARKERS = ("впишите сюда", "шаблонное", "<впишите", "<описание")

VERBATIM = (
    "СТОП (код 42). Описание доработки отсутствует или не является "
    "реальным (файл %s в корне рабочей папки).\n"
    "ДЕЙСТВИЕ (обязательное, без продолжения Шага 2):\n"
    "1. Задай аналитику РОВНО ОДИН вопрос: «Опишите доработку, для "
    "которой готовим ТЗ» — и жди ответа.\n"
    "2. Запиши ответ в %s в корне рабочей папки.\n"
    "3. Повтори этот скрипт.\n"
    "Выбор доработки — решение аналитика, не модели. Модель НЕ выбирает "
    "доработку по скану."
)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--text", default=None,
                    help="описание доработки текстом: скрипт сам запишет его в "
                         "%s в рабочей папке и запустит обычный поток" % DESC_FILE)
    args = ap.parse_args()
    path = os.path.join(args.work, DESC_FILE)
    if args.text is not None:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(args.text)
    text = ""
    if os.path.isfile(path):
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError as e:
            print(VERBATIM % (DESC_FILE, DESC_FILE))
            print("[check_description] файл не читается: %s" % str(e)[:120])
            sys.exit(42)
    low = text.lower()
    bad = (not text.strip()
           or len(text.strip()) < DESC_MIN_LEN
           or any(m in low for m in PLACEHOLDER_MARKERS))
    if bad:
        print(VERBATIM % (DESC_FILE, DESC_FILE))
        sys.exit(42)
    print("[OK check_description] описание есть (%d символов) — Шаг 2 разрешён"
          % len(text.strip()))
    sys.exit(0)


if __name__ == "__main__":
    main()
