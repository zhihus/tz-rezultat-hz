# -*- coding: utf-8 -*-
"""check_language.py — язык проверки правописания документа (2026-11-25).

Word и PowerPoint проверяют текст словарём того языка, который стоит НА
тексте. Если в документе стоит чужой язык (образцы заказчика приносят
it-IT в docDefaults и en-US в themeFontLang) или языка нет вовсе
(текстовые свойства, созданные скриптами), русский текст подчёркивается
красным: правка документа превращается в мусор из ложных ошибок, и
отличить настоящую опечатку от ложной невозможно.

Что проверяется (весь пакет, не только тело):
  DOCX — word/document.xml, styles.xml (docDefaults), settings.xml
         (themeFontLang), numbering, footnotes/endnotes, колонтитулы:
         каждый <w:lang w:val=…> и язык по умолчанию;
  PPTX — ppt/presentation.xml (defaultTextStyle), слайды, макеты, мастера,
         заметки: атрибут lang на текстовых свойствах (a:rPr / a:defRPr /
         a:endParaRPr) и язык стилей по умолчанию.

Использование:
  python.exe scripts/check_language.py <документ.docx|.pptx> [--lang ru-RU]
  python.exe scripts/check_language.py <документ> --fix --out <новый файл>

Код возврата: 0 — язык русский; 1 — дефекты (список в отчёте); 2 — ошибка
вызова. Правка — ТОЛЬКО в новый файл (--out): документ не правится на
месте, у документа всегда есть предыдущая версия.

Вызывается конвейером: build_from_spec/render_md нормализуют язык
сохранённого документа (tz_common.set_language_ru), final_gate проверяет
его блоком «язык» — шаг 8 без чистой проверки языка не закрывается.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tz_common import (RU_LANG, normalize_language, scan_language,  # noqa: E402
                       setup_utf8_stdout)


def report(path, lang):
    """Печать отчёта; возвращает число дефектов."""
    rep = scan_language(path, lang)
    print(f"[ЯЗЫК] {path}")
    print(f"[ЯЗЫК] частей проверено: {rep['parts']}; тегов языка: {rep['tags']}; "
          f"целевой язык: {lang}")
    n = 0
    for part, tag, txt in rep["foreign"]:
        where = f" на тексте «{txt}»" if txt else ""
        print(f"[FAIL] {part}: {tag}{where} — язык не {lang}")
        n += 1
    for part, tag, what in rep["defaults"]:
        print(f"[FAIL] {part}: {what}" + (f" ({tag})" if tag else ""))
        n += 1
    if n:
        print(f"[ИТОГ ЯЗЫК] FAIL ({n}) — чужой язык или отсутствие языка: "
              f"Word/PowerPoint подчёркивает русский текст красным. "
              f"Правка: check_language.py <документ> --fix --out <новый файл> "
              f"(или пересборка конвейером).")
    else:
        print(f"[ИТОГ ЯЗЫК] OK — язык проверки правописания {lang}")
    return n


def main():
    setup_utf8_stdout()
    ap = argparse.ArgumentParser(
        description="язык проверки правописания DOCX/PPTX")
    ap.add_argument("doc", help="документ .docx или .pptx")
    ap.add_argument("--lang", default=RU_LANG,
                    help=f"целевой язык (по умолчанию {RU_LANG})")
    ap.add_argument("--fix", action="store_true",
                    help="записать исправленный документ (нужен --out)")
    ap.add_argument("--out", default=None,
                    help="новый файл для исправленного документа "
                         "(правка на месте запрещена)")
    args = ap.parse_args()

    if not os.path.exists(args.doc):
        print(f"[ЯЗЫК] нет файла: {args.doc}")
        return 2
    if args.fix:
        if not args.out:
            print("[ЯЗЫК] правка НЕ на месте: укажите --out <новый файл> — "
                  "документ всегда правится новой версией, прежняя остаётся.")
            return 2
        if os.path.abspath(args.out) == os.path.abspath(args.doc):
            print("[ЯЗЫК] --out совпадает с исходным файлом: правка на месте "
                  "запрещена, укажите другой путь.")
            return 2
        normalize_language(args.doc, args.out, args.lang)
        print(f"[ЯЗЫК] исправлено → {args.out}")
        return 1 if report(args.out, args.lang) else 0
    return 1 if report(args.doc, args.lang) else 0


if __name__ == "__main__":
    sys.exit(main())
