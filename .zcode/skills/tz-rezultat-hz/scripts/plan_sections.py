# -*- coding: utf-8 -*-
"""plan_sections.py — каркас разделов из карты (E-55).

Модель НЕ решает структуру: spec задаёт НАБОР разделов (образцы),
скрипт упорядочивает его по зависимостям (tech-tz-map.ru.md §4) и
генерирует каркас с подразделами из карты (H3 на каждый сценарий
бэкенда, пометки рисунков для затронутых элементов форм). Модель
заполняет тело каждого пункта — ваншотами, значениями из карты.

Порядок разделов — канон СОДЕРЖАНИЯ (урок живого прогона V9, 2026-11-19;
совпадает с final_gate F10/F11): источник → новые объекты → новые данные
в существующих → формы → бизнес-логика (сценарии/алгоритмы ВНУТРИ неё) →
роли → ограничения. Второй H1 образцов («Описание бизнес-логики») —
повествовательный ОБЗОР процесса; по заголовкам он вторым, но сценарии
У/С/А/Р в образцах идут после разделов создания/доработки. Разделы spec,
не опознанные по ключевым словам, сохраняют свой относительный порядок
в конце ранга 10 (не теряются, докладываются).

Выход:
  <out>/plan.md   — каркас для модели (заполнять тела, заголовки не менять);
  <out>/plan.json — тот же каркас машиночитаемо: final_gate сверяет
                    итоговый DOCX с планом (F4-порядок) и проверяет
                    «первое упоминание = раздел создания» (F10).

Использование:
  python plan_sections.py --map obj-map.json --spec spec.json
                          --out <папка версии>
"""

import argparse
import json
import os
import re
import sys


_RANKS = [
    # \b ОБЯЗАТЕЛЕН: без него «контрОЛь» ловился как «роли», а
    # «инфОрмации» и «фОрмулировки» — как «формы» (универсальность
    # для любого проекта, урок 2026-11-18).
    # Канон порядка СОДЕРЖАНИЯ (урок V9, живой прогон 2026-11-19):
    # порядок ЗАГОЛОВКОВ образцов обманчив — второй раздел образцов это
    # ОБЗОР процесса (проза), а сценарии/алгоритмы в -10 идут ПОСЛЕ
    # новых объектов. Канон совпадает с final_gate F10/F11:
    # источник → объекты → данные → формы → бизнес-логика → роли →
    # ограничения.
    (re.compile(r"\bисточник", re.I), 0, "источник"),
    (re.compile(r"\bновых объектов", re.I), 1, "новые объекты"),
    (re.compile(r"\bновых данных", re.I), 2, "новые данные"),
    (re.compile(r"\bформ(?:а|ы|е|ах|ами)?\b", re.I), 3, "формы"),
    (re.compile(r"\bбизнес-логик|\bалгоритм", re.I), 4, "бизнес-логика"),
    (re.compile(r"\bрол", re.I), 5, "роли"),
    (re.compile(r"\bограничени|\bриск", re.I), 6, "ограничения"),
]


def _strip_num(title):
    return re.sub(r"^\s*\d+(?:\.\d+)*\.?\s*", "", title).strip()


def _rank(title, fallback):
    t = _strip_num(title)
    for rx, rank, _ in _RANKS:
        if rx.search(t):
            return rank
    return 10 + fallback  # неопознанный — в конце, относительный порядок


def build_plan(m, spec):
    h1 = [(s.get("title", ""), s) for s in spec.get("sections", [])
          if s.get("level") == 1]
    ordered = sorted(enumerate(h1),
                     key=lambda x: (_rank(x[1][0], x[0]), x[0]))
    plan = []
    for pos, (_, (title, s)) in enumerate(ordered):
        t = _strip_num(title)
        entry = {"level": 1, "title": t, "rank": _rank(title, pos),
                 "body": []}
        rank = entry["rank"]
        if rank == 4 and m:
            # H2, НЕ H3: под H1 «бизнес-логика» нет промежуточного уровня —
            # H3 сразу под H1 Word рендерит как N.1.K (счётчик уровня 2
            # пуст), а гейт нумерации считает N.0.K → вечный FAIL (E-57).
            for b in m.get("backend") or []:
                entry["body"].append({"kind": "h2",
                                      "title": f"Событие: {b.get('what')} "
                                               f"({b.get('trigger')})"})
                entry["body"].append({"kind": "fill",
                                      "text": "Шаги Дано/Когда/Тогда из "
                                              "scenario карты (O5)."})
        elif rank == 1 and m:
            for o in m.get("objects") or []:
                if o.get("status") == "новый":
                    entry["body"].append(
                        {"kind": "fill",
                         "text": f"Добавить новый объект: {o.get('kind')} "
                                 f"«{o.get('synonym')}» (имя: {o.get('id')}) — "
                                 f"ваншоты O1, O2 (реквизиты слотами), O4 (назначение)."})
        elif rank == 2 and m:
            chg = [o for o in m.get("objects") or [] if o.get("status") == "доработка"]
            for o in chg:
                entry["body"].append(
                    {"kind": "fill",
                     "text": f"Новые данные в {o.get('kind')} {o.get('id')}: "
                             f"реквизиты/измерения — слотами (O2)."})
        elif rank == 3 and m:
            for f_ in m.get("forms") or []:
                entry["body"].append({"kind": "h2",
                                      "title": f"Изменение формы «{f_.get('name')}» "
                                               f"объекта {f_.get('owner')}"})
                for el in f_.get("new_elements") or []:
                    entry["body"].append({"kind": "fill",
                                          "text": f"{el} — после описания поставить "
                                                  f"«(Рисунок - N)» и подпись "
                                                  f"«Рисунок - N …» (F11)."})
        entry["body"].append({"kind": "fill", "text": ""})
        plan.append(entry)
    return plan


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", required=True)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    with open(args.map, encoding="utf-8") as fh:
        m = json.load(fh)
    with open(args.spec, encoding="utf-8") as fh:
        spec = json.load(fh)
    plan = build_plan(m, spec)
    os.makedirs(args.out, exist_ok=True)
    L = ["# КАРКАС РАЗДЕЛОВ (план из карты) — заголовки НЕ менять, "
         "заполнять тела ваншотами по картой заданным значениям.", ""]
    for e in plan:
        L.append("# " + e["title"])
        for b in e["body"]:
            if b["kind"] == "h2":
                L.append("## " + b["title"])
            elif b["kind"] == "h3":
                L.append("### " + b["title"])
            elif b["kind"] == "fill" and b["text"]:
                L.append("[ЗАПОЛНИТЬ] " + b["text"])
        L.append("")
    with open(os.path.join(args.out, "plan.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    with open(os.path.join(args.out, "plan.json"), "w", encoding="utf-8") as fh:
        json.dump(plan, fh, ensure_ascii=False, indent=1)
    print(f"[OK] план: {os.path.join(args.out, 'plan.md')} (+ plan.json); "
          f"разделов: {len(plan)} — модель заполняет тела, заголовки/порядок "
          f"заданы конвейером (final_gate F4/F10 сверят итог с планом).")


if __name__ == "__main__":
    main()
