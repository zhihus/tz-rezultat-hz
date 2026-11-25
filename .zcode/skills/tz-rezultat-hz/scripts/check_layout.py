# -*- coding: utf-8 -*-
"""check_layout.py — дисциплина файлов проекта (урок 2026-11-19).

Проверяет раскладку ВСЕХ проектов рабочей папки; исправимое делает САМ:
  - старые версии итога из тз/<КОД>/ → версии/<КОД>/версия-V/;
  - итог DOCX, осевший в версии/<КОД>/версия-N/ → тз/<КОД>/ (дубль — WARN);
  - чужие записи в корне проекта → temp/<имя>/;
  - отсутствующие корневые папки создаёт.
Неисправимое (незнакомые файлы в тз/) — FAIL + ДЕЙСТВИЕ, модель выполняет.
Модель НЕ раскладывает файлы руками — только запускает и делает предписания.

Раскладка-эталон:
  <проект>/references|profiles|версии|тз/
  тз/<КОД>/           — текущий итог (max V) + шаблон_ТЗ_1С.docx, ничего больше
  версии/<КОД>/версия-N/ — кухня (draft/spec/obj-map/plan/figs/miniprofiles/temp)

Вызов: python check_layout.py --work <рабочая папка>   (или --project <путь>)
"""

import argparse
import os
import re
import shutil
import sys

KOOD_RE = re.compile(r"^(?:Приложение к ТЗ |.+?_ТЗ_)(.+?)_V(\d+)")
KITCHEN = {"draft.md", "figs.json", "obj-map.json", "plan.json", "plan.md",
           "spec.json", "miniprofiles.md", "oneshots",
           "шаблон_ТЗ_1С.docx",  # Б10-5.4: шаблон живёт в кухне версии
           "overrides.json",     # Б9: решения рядом со spec.json
           "исследование.md"}    # методология аналитика: фаза исследования Шага 2
ROOT_DIRS = {"references", "profiles", "версии", "тз"}
OUT = []


def _line(tag, where, msg):
    OUT.append(f"[{tag:9}] {where}: {msg}")


def _move(src, dst_dir):
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, os.path.basename(src))
    if os.path.exists(dst):
        return None  # дубль — не перезаписывать
    shutil.move(src, dst)
    return dst


def check_tz_dir(tz, vroot, name):
    """тз/<КОД>: старые версии → кухня, текущая остаётся; чужое — FAIL."""
    files = os.listdir(tz)
    itogi = {}  # v -> filename
    for f in files:
        p = os.path.join(tz, f)
        m = KOOD_RE.match(f)
        if m and os.path.isfile(p):
            itogi[int(m.group(2))] = f
        elif f == "шаблон_ТЗ_1С.docx":
            continue
        elif os.path.isdir(p):
            # D3 (прогон -59): точный путь + честное предписание — скрипт
            # не переносит неизвестное сам
            _line("FAIL", name, f"{os.path.abspath(p)} — папка внутри тз; "
                                f"документы лежат плоско; ДЕЙСТВИЕ: перенеси "
                                f"вручную содержимое в версии/ или temp/")
        else:
            _line("FAIL", name, f"{os.path.abspath(p)} — не итог по шаблону "
                                f"имени и не шаблон; ДЕЙСТВИЕ: перенеси вручную "
                                f"в версии/ или temp/")
    if not itogi:
        return
    cur = max(itogi)
    code = KOOD_RE.match(itogi[cur]).group(1)
    for v, f in sorted(itogi.items()):
        if v == cur:
            continue
        dst = _move(os.path.join(tz, f), os.path.join(vroot, code, f"версия-{v}"))
        _line("ИСПРАВЛЕНО" if dst else "WARN", name,
              f"тз/{f} → версии/{code}/версия-{v}/" + ("" if dst else " (там уже есть — дубль)"))


def check_version_dir(vd, tz, name, rel):
    """версия-N: итог НОВЕЕ текущего в тз → тз; старее — остаётся архивом."""
    cur_v = max([int(m.group(2)) for f in (os.listdir(tz) if os.path.isdir(tz) else [])
                 for m in [KOOD_RE.match(f)] if m] or [0])
    for f in os.listdir(vd):
        p = os.path.join(vd, f)
        if f in KITCHEN or f == "temp" or os.path.isdir(p):
            continue
        m = KOOD_RE.match(f)
        if m and f.lower().endswith(".docx"):
            if int(m.group(2)) <= cur_v:
                continue  # старая версия — архив в кухнях, в тз не переносим
            dst = _move(p, tz)
            _line("ИСПРАВЛЕНО" if dst else "WARN", name,
                  f"{rel}/{f} → тз/" + ("" if dst else " (в тз уже есть — дубль)"))
        else:
            _line("WARN", name, f"{rel}/{f} — не кухонный файл; проверить раскладку")


def check_project(proj, work):
    name = os.path.basename(proj)
    for d in sorted(ROOT_DIRS):
        os.makedirs(os.path.join(proj, d), exist_ok=True)
    # корень проекта: чужие записи → temp/<имя>/
    for entry in sorted(os.listdir(proj)):
        if entry in ROOT_DIRS:
            continue
        dst = _move(os.path.join(proj, entry), os.path.join(work, "temp", name))
        _line("ИСПРАВЛЕНО" if dst else "FAIL", name,
              f"корень/{entry} — не корневая папка проекта → temp/{name}/"
              + ("" if dst else " (не удалось перенести)"))
    tz_root = os.path.join(proj, "тз")
    vroot = os.path.join(proj, "версии")
    for code in sorted(os.listdir(tz_root)):
        d = os.path.join(tz_root, code)
        if os.path.isdir(d):
            check_tz_dir(d, vroot, name)
    for code in sorted(os.listdir(vroot)):
        vd = os.path.join(vroot, code)
        if not os.path.isdir(vd):
            continue
        for sub in sorted(os.listdir(vd)):
            if sub.startswith("версия-"):
                check_version_dir(os.path.join(vd, sub),
                                  os.path.join(tz_root, code), name, f"версии/{code}/{sub}")
            elif (sub == "temp" or sub.startswith("вопросы_ответы_")
                  or sub == "дифф_разделов.md"):
                continue  # штатные записи уровня <КОД>
            else:
                _line("WARN", name, f"версии/{code}/{sub} — не версия-N и не temp")
    _line("OK", name, "раскладка проверена")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=None)
    ap.add_argument("--project", default=None, help="путь к папке проекта")
    args = ap.parse_args()
    if args.project:
        check_project(args.project, os.path.dirname(args.project.rstrip("/\\")))
    else:
        projs = os.path.join(args.work, "projects")
        for name in sorted(os.listdir(projs)) if os.path.isdir(projs) else []:
            if os.path.isdir(os.path.join(projs, name)):
                check_project(os.path.join(projs, name), args.work)
    for ln in OUT:
        print(ln)
    bad = sum(1 for ln in OUT if ln.startswith("[FAIL"))
    print(f"[ИТОГ check_layout] {'FAIL ' + str(bad) + ' — выполнить ДЕЙСТВИЯ' if bad else 'чисто'}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
