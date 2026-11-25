# -*- coding: utf-8 -*-
"""sync_check.py — дисциплина зеркал скилла (урок 2026-11-19: вторая
установка отстала на 15 коммитов, конвейер README — на один; «если
забываешь — сделай скрипт, который поможет не забывать»).

Скилл — источник истины. Два зеркала:
  1. ~/.agents/skills/tz-rezultat-hz  — СТРУКТУРНОЕ: точная копия всех
     файлов/папок (SKILL.md, references/, scripts/, bundle/), оба
     направления (лишнее и отсутствующее — FAIL);
  2. конвейер/                    — ПЛОСКОЕ: superset (там свой
     tz_tool.py, build_binary и пр.), но каждый общий файл обязан быть
     бит-в-бит равен канону.

Игнор: __pycache__, temp. Вызов без аргументов — проверить сами зеркала
скилла (дефолты); --skill/--mirror/--flat|--tree — для тестов.

Вызов: python sync_check.py
"""

import argparse
import filecmp
import os
import sys

# Игнор: __pycache__, temp; portable — рантайм, восстанавливается
# setup_portable.bat|sh и в публикуемом дереве отсутствует; runtime —
# версионный рантайм Bootstrap, восстанавливается bootstrap.ps1/.sh|py
# (аналогично portable); сторонние бандлы (format-agent — PolyForm
# Noncommercial, grilling) не распространяются и в клоне отсутствуют.
IGNORE = {"__pycache__", "temp", "portable", "runtime",
          "format-agent-skill", "grilling"}
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL_DIR = os.path.expanduser("~/.agents/skills/tz-rezultat-hz")
ZCODE_DIR = os.path.expanduser("~/.zcode/skills/tz-rezultat-hz")  # третья установка (дефект 2026-11-22: сессии читают её, а она не зеркалилась)
CONVEYOR_DIR = os.path.normpath(os.path.join(SKILL_DIR, "..", "..",
                                             "..", "конвейер"))
OUT = []


def _line(tag, msg):
    ln = f"[{tag:6}] {msg}"
    OUT.append(ln)
    return ln


def _files(root):
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE]
        for f in filenames:
            p = os.path.join(dirpath, f)
            out[os.path.relpath(p, root).replace(os.sep, "/")] = p
    return out


def check_tree(canonical, mirror, tag):
    """СТРУКТУРНОЕ зеркало: rel → путь, совпадение множеств + контент."""
    a, b = _files(canonical), _files(mirror)
    ok = True
    for rel in sorted(set(a) - set(b)):
        _line("FAIL", f"{tag}: отсутствует {rel} — скопировать из скилла")
        ok = False
    for rel in sorted(set(b) - set(a)):
        _line("FAIL", f"{tag}: лишний {rel} — в скилле его нет, удалить/перенести")
        ok = False
    for rel in sorted(set(a) & set(b)):
        if not filecmp.cmp(a[rel], b[rel], shallow=False):
            _line("FAIL", f"{tag}: {rel} отличается — зеркально переписать")
            ok = False
    return ok


def check_flat(canonical, mirror, tag):
    """ПЛОСКОЕ зеркало (superset): каждый общий файл — бит-в-бит равен;
    файлы скилла, у которых в зеркале нет пары — FAIL (канон обязан
    присутствовать)."""
    a, b = _files(canonical), _files(mirror)
    # канон может передаваться корнем скилла — плоское зеркало держит
    # файлы scripts/ на верхнем уровне, префикс снимаем
    a = {rel.split("scripts/", 1)[-1]: p for rel, p in a.items()}
    ok = True
    for rel, p in sorted(a.items()):
        q = b.get(rel)
        if q is None:
            _line("FAIL", f"{tag}: отсутствует {rel} — скопировать из скилла")
            ok = False
        elif not filecmp.cmp(p, q, shallow=False):
            _line("FAIL", f"{tag}: {rel} отличается — зеркально переписать")
            ok = False
    return ok


def _check_single_install(extra_dirs=None):
    """ЕДИНСТВЕННАЯ установка скилла (2026-11-22): установленная копия
    всегда одна — ~/.agents/skills/tz-rezultat-hz. Вторая копия
    (например ~/.zcode/skills/...) рассинхронизирует сессии: сессия
    читает не ту копию, работает по устаревшим правилам (дефект:
    «опять просит перезапустить»). Возвращает (lines, ok)."""
    lines = []
    known = {os.path.normpath(INSTALL_DIR), os.path.normpath(SKILL_DIR),
             os.path.normpath(CONVEYOR_DIR)}
    bad = []
    for d in list(extra_dirs or []) + [ZCODE_DIR]:
        if d and os.path.isdir(d) and os.path.normpath(d) not in known:
            bad.append(d)
    if bad:
        for d in bad:
            lines.append(_line("FAIL", f"лишняя копия скилла: {d} — "
                               f"установка всегда ОДНА ({INSTALL_DIR}); "
                               "перенести в temp/ или удалить"))
        return lines, False
    lines.append(_line("OK", f"одна установка скилла: {INSTALL_DIR}"))
    return lines, True


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", default=SKILL_DIR)
    ap.add_argument("--mirror", default=None)
    ap.add_argument("--flat", action="store_true")
    ap.add_argument("--tree", action="store_true")
    args = ap.parse_args()
    checks = []
    if args.mirror:
        mode = "плоское" if args.flat else "структурное"
        fn = check_flat if args.flat else check_tree
        checks.append((f"зеркало {args.mirror} ({mode})",
                       args.skill, args.mirror, fn))
    else:
        # дефолт: сами зеркала скилла
        checks.append(("вторая установка ~/.agents/skills/tz-rezultat-hz",
                       args.skill, INSTALL_DIR, check_tree))
        checks.append(("зеркало конвейер/ (плоское)",
                       os.path.join(args.skill, "scripts"), CONVEYOR_DIR,
                       check_flat))
    bad = 0
    _si_lines, si_ok = _check_single_install()
    if not si_ok:
        bad += 1
    for name, canon, mir, fn in checks:
        if not os.path.isdir(mir):
            _line("FAIL", f"{name}: зеркало не найдено: {mir}")
            bad += 1
            continue
        if not fn(canon, mir, name):
            bad += 1
        else:
            _line("OK", f"{name}: синхронизировано")
    for ln in OUT:
        print(ln)
    print(f"[ИТОГ sync_check] "
          f"{'FAIL ' + str(bad) + ' — выполнить действия' if bad else 'чисто'}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
