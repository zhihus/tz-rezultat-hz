# -*- coding: utf-8 -*-
"""gen_miniprofiles.py — каркас минипрофилей писателя (Шаг 7 п.1, E-37).

Скрипт вынимает из spec.json всё механическое (факты, счётчики,
таблицы, роли, глоссарий) и пишет КАРКАС: модель дописывает только
формулировки (canonical_patterns с доказательством, lexicon, rules).
Гейт E-37 остаётся: текст НЕ писать, пока заполненный профиль не
сохранён в profiles/.

Использование:
  python gen_miniprofiles.py --spec <spec.json> --out <profiles папка>
                             [--doc-type бизнес-ТЗ]

Результат: <out>/каркас-минипрофилей.md — модель заполняет секции
«ФОРМУЛИРОВКИ (заполнить моделью)» и сохраняет итог как
минипрофили.md рядом (НЕ перезаписывая каркас).
"""

import argparse
import json
import os
import sys
from datetime import datetime


def walk(node, depth, lines, M):
    title = node.get("title", "")
    n = node.get("in_samples")
    ev = f"в {n} из {M} образцов" if n is not None else "вариация (не в большинстве)"
    lines.append(f"### {title or '[БЕЗ ЗАГОЛОВКА]'}")
    lines.append(f"- Присутствие: {ev}; уровень H{node.get('level', '?')}; "
                 f"page_break={bool(node.get('page_break'))}.")
    src = node.get("src")
    if src:
        # T5 (план п.1.4): происхождение раздела — файлы-образцы
        lines.append(f"- источники: {', '.join(src)}")
    shots = sum(1 for b in node.get("body", []) if b["type"] == "screenshot")
    if shots:
        lines.append(f"- Скриншотов в разделе: {shots} (места из образцов).")
    for b in node.get("body", []):
        if b["type"] == "table":
            cb = b.get("col_bold") or []
            bold_cols = [c for i, c in enumerate(b.get("columns", []))
                         if i < len(cb) and cb[i]]
            lines.append(f"- Таблица {b.get('columns', [])} — строк: {b.get('rows')}; "
                         f"подпись: {'есть' if b.get('has_caption') else 'нет'}; "
                         f"жирные колонки: {bold_cols or 'нет'}.")
            if b.get("example_row"):
                lines.append(f"  Пример строки: {b['example_row']}")
    variants = node.get("formulation_variants") or []
    if len(variants) >= 2:
        # T6 (аудит Г3): спорный выбор формулировки — НЕ эвристики размера
        # (вода >400 симв., «больше таблиц»), а сравнение по критериям;
        # недостаточно данных → вопрос пользователю, не авто-выбор
        lines.append("- АЛЬТЕРНАТИВЫ формулировок (выбрать ОДНУ — модель "
                     "сравнивает строго по критериям и фиксирует выбор с "
                     "обоснованием):")
        for v in variants:
            lines.append(f"  * {v}")
        lines.append("  Критерии сравнения: полнота требований; "
                     "однозначность; логическая последовательность; наличие "
                     "условий «если — то»; отсутствие повторов; достаточность "
                     "информации для разработчика. Критерии не дают "
                     "однозначного выбора → вопрос пользователю "
                     "(Четвёртое правило), не авто-выбор; данных "
                     "недостаточно — пометка «уточнить по конфигурации».")
    if node.get("hint"):
        lines.append(f"- {node['hint']}")
    lines.append("- ФОРМУЛИРОВКИ (заполнить моделью): канонические шаблоны строк "
                 "с доказательством «в N из M»; лексика; правила письма (3–7).")
    lines.append("")
    for c in node.get("children", []):
        walk(c, depth + 1, lines, M)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--doc-type", default="бизнес-ТЗ")
    args = ap.parse_args()

    with open(args.spec, encoding="utf-8") as f:
        spec = json.load(f)
    M = spec.get("meta", {}).get("samples_count") or 1

    L = [f"# Каркас минипрофилей — {args.doc_type}",
         f"Сгенерировано из spec.json {datetime.now().isoformat(timespec='seconds')}; "
         f"образцов: {M}. Заполнять ТОЛЬКО секции «ФОРМУЛИРОВКИ»; "
         "доказательства — парами «в N из M образцов», не выдумывать. "
         "Готовый профиль сохранить как минипрофили.md в этой же папке.", ""]

    # правила и ваншоты пользователя — ВЫШЕ образцовых (урок 2026-11-19)
    for name in sorted(os.listdir(os.path.dirname(args.out) or "."))             if os.path.isdir(os.path.dirname(args.out) or ".") else []:
        if name.startswith("user-"):
            L.append(f"## ВАНШОТЫ ПОЛЬЗОВАТЕЛЯ: profiles/{name} — ПРИОРИТЕТ над "
                     "образцовыми семьями своей темы: конфликт решается в пользу "
                     "пользовательского ваншота; образцовый действует там, где "
                     "пользовательский не задан.")
            break
    if spec.get("meta", {}).get("user_rules"):
        L.append("## ПРАВИЛА ПОЛЬЗОВАТЕЛЯ (постоянные, для ВСЕХ ТЗ проекта):")
        for r in spec["meta"]["user_rules"]:
            L.append(f"- {r}")
    if spec.get("roles"):
        L.append(f"## Словарь ролей (жирный префикс в тестировании): "
                 f"{', '.join(spec['roles'])}")
    if "техническое" in args.doc_type:
        L.append("## ВАНШОТЫ (заполнить моделью) — жёсткие паттерны тех-ТЗ, "
                 "перечень семей: references/oneshots-tech.ru.md. По КАЖДОЙ "
                 "семье O1–O10 вывести ваншот (слоты дословно по перечню) с "
                 "доказательством «в N из M» или пометку «в образцах не "
                 "встречается»; текст черновика писать ТОЛЬКО ваншотами "
                 "попадающих семей, слоты — точечными путями из карты "
                 "объектов (check_map PASS). Реквизиты/измерения/ресурсы — "
                 "слотами списка «имя – X, / синоним – Y, / тип – Z» (образец 47) "
                 "ИЛИ таблицей «Имя | Синоним | Тип» (образец 10); триада в одну "
                 "строку запрещена (линт G11). Готовый каталог ваншотов "
                 "сохранить как profiles/oneshots/v<N>.md (версионирование: "
                 "oneshots-tech.ru.md §«Хранение») — НЕ удалять прежние "
                 "версии; несколько вариантов одной семьи — норма.")
    if spec.get("glossary_terms"):
        L.append(f"## Термины глоссариев образцов (ЕДИНСТВЕННЫЙ источник "
                 f"глоссария нового ТЗ): {', '.join(spec['glossary_terms'])}")
    L.append("")

    for s in spec.get("sections", []):
        walk(s, 0, L, M)

    os.makedirs(args.out, exist_ok=True)
    dst = os.path.join(args.out, "каркас-минипрофилей.md")
    with open(dst, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"[OK] каркас: {dst}")
    print("[ИТОГ] модель: заполнить «ФОРМУЛИРОВКИ» → сохранить минипрофили.md "
          "рядом → только потом писать текст этапа 2 (гейт E-37).")


if __name__ == "__main__":
    main()
