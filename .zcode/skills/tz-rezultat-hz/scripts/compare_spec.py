# -*- coding: utf-8 -*-
"""compare_spec.py — дифф версий spec.json с атрибуцией (T4, аудит Г5;
план доработки v2 §3).

Суть: при добавлении образца пересборка шаблона молча меняет spec;
скрипт печатает, что именно изменилось и почему.

Атрибуция СТРОГАЯ:
- «добавлено образцом X» — ТОЛЬКО если элемент есть в `src` нового
  образца X И отсутствовал во всей прежней коллекции (проверка по
  прежнему spec: шаблонные секции + variations.sections_src, не по
  одному имени файла);
- элемент, присутствовавший в прежней коллекции, но не попавший в
  прежний шаблон → «изменение расчёта», НЕ «новый образец».

Использование:
  python compare_spec.py --old <старый spec.json> --new <новый spec.json>
                         [-o дифф_разделов.md]

Код возврата: 0 — изменений нет; 1 — есть изменения.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_spec import norm_title  # соседний модуль канона/зеркала


def _walk(nodes):
    for n in nodes:
        yield n
        yield from _walk(n.get("children") or [])


def _template_sigs(spec):
    """Сигнатура → секция (только шаблонные разделы)."""
    return {norm_title(s.get("title", "")): s
            for s in _walk(spec.get("sections") or [])}


def _tables_of(section):
    return [b for b in section.get("body", []) if b.get("type") == "table"]


def compare(old, new):
    """Возвращает (строки отчёта, есть_ли_изменения)."""
    old_tpl = _template_sigs(old)
    new_tpl = _template_sigs(new)
    # прежняя коллекция: всё, что старый spec ЗНАЛ о своих образцах —
    # шаблонные разделы + variations.sections_src (не имена файлов)
    old_var_src = (old.get("variations") or {}).get("sections_src") or {}
    old_collection = set(old_tpl) | {norm_title(k) for k in old_var_src}

    old_samples = list((old.get("meta") or {}).get("samples") or [])
    new_samples = list((new.get("meta") or {}).get("samples") or [])
    new_files = [s for s in new_samples if s not in old_samples]

    lines = ["# Дифф версий spec.json", "",
             f"- старая коллекция: {', '.join(old_samples) or '(пусто)'}",
             f"- новая коллекция: {', '.join(new_samples) or '(пусто)'}",
             f"- новые образцы: {', '.join(new_files) or '—'}", ""]

    added, recalc, removed, changed = [], [], [], []

    for sig, sec in sorted(new_tpl.items()):
        if sig in old_tpl:
            o, n = old_tpl[sig], sec
            diffs = []
            if (o.get("in_samples") or len(o.get("src") or [])) != \
                    (n.get("in_samples") or len(n.get("src") or [])):
                diffs.append(f"in_samples {o.get('in_samples')} → "
                             f"{n.get('in_samples')}")
            ot = [_norm_hdr(t) for t in _tables_of(o)]
            nt = [_norm_hdr(t) for t in _tables_of(n)]
            if ot != nt:
                diffs.append(f"таблицы {len(ot)} → {len(nt)}"
                             + (f" ({', '.join(nt[len(ot):])})" if len(nt) > len(ot) else ""))
            if diffs:
                changed.append((sec.get("title", sig), "; ".join(diffs)))
            continue
        if sig in old_collection:
            # был в прежней коллекции, но не в прежнем шаблоне
            recalc.append(sec.get("title", sig))
            continue
        # строго: только образцы из src нового элемента среди НОВЫХ файлов
        srcs = set(sec.get("src") or [])
        owners = [x for x in new_files if x in srcs]
        if owners:
            added.append((sec.get("title", sig),
                          "добавлено образцом " + ", ".join(owners)))
        else:
            recalc.append(sec.get("title", sig))

    for sig, sec in sorted(old_tpl.items()):
        if sig not in new_tpl:
            removed.append(sec.get("title", sig))

    # миноритарные таблицы: состав
    old_vt = (old.get("variations") or {}).get("tables") or []
    new_vt = (new.get("variations") or {}).get("tables") or []
    old_vt_keys = {tuple(t.get("columns") or []) for t in old_vt}
    new_vt_keys = {tuple(t.get("columns") or []) for t in new_vt}

    if not (added or recalc or removed or changed
            or new_vt_keys != old_vt_keys):
        lines.append("Изменений нет.")
        return lines, False

    lines.append("## Изменения разделов")
    lines.append("")
    if added:
        lines.append("### Новые разделы")
        for title, why in added:
            lines.append(f"- {title} — {why}")
        lines.append("")
    if recalc:
        lines.append("### Изменение расчёта (были в прежней коллекции)")
        for title in recalc:
            lines.append(f"- {title} — изменение расчёта")
        lines.append("")
    if removed:
        lines.append("### Выбывшие разделы")
        for title in removed:
            lines.append(f"- {title}")
        lines.append("")
    if changed:
        lines.append("### Изменившиеся разделы")
        for title, d in changed:
            lines.append(f"- {title}: {d}")
        lines.append("")
    if new_vt_keys != old_vt_keys:
        lines.append("## Миноритарные таблицы")
        for k in sorted(new_vt_keys - old_vt_keys):
            lines.append(f"- добавлена таблица {list(k)}")
        for k in sorted(old_vt_keys - new_vt_keys):
            lines.append(f"- выбыла таблица {list(k)}")
        lines.append("")
    return lines, True


def _norm_hdr(t):
    return tuple(t.get("columns") or [])


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True, help="старый spec.json")
    ap.add_argument("--new", required=True, help="новый spec.json")
    ap.add_argument("-o", "--out", default="дифф_разделов.md")
    args = ap.parse_args()

    with open(args.old, encoding="utf-8") as f:
        old = json.load(f)
    with open(args.new, encoding="utf-8") as f:
        new = json.load(f)

    lines, has_changes = compare(old, new)
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(lines))
    print(f"[compare_spec] {out} "
          f"({'есть изменения' if has_changes else 'изменений нет'})",
          file=sys.stderr)
    sys.exit(0 if not has_changes else 1)


if __name__ == "__main__":
    main()
