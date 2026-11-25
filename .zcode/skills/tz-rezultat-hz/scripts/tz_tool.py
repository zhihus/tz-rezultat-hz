# -*- coding: utf-8 -*-
"""
tz_tool.py — единая точка входа конвейера (v4 §16).

Подкоманды:
    extract   образец → spec.json
    build     spec.json → шаблон DOCX
    verify    проверка шаблона (pass/fail, единственный гейт приёмки)
    run       полный конвейер: extract → build → verify

Использование (запуск из корня проекта; -o — полный путь к файлу результата):
    python tz_tool.py extract --folder references/business-tz -o версии/версия-4/spec.json
    python tz_tool.py build версии/версия-4/spec.json -o версии/версия-4/шаблон_ТЗ_1С.docx
    python tz_tool.py verify версии/версия-4/spec.json версии/версия-4/шаблон_ТЗ_1С.docx -o версии/версия-4/отчёт_проверки.md
    python tz_tool.py run --folder references/business-tz -o версии/версия-4

Тот же вход используется для сборки one-file бинарника (Nuitka --onefile,
см. build_binary.bat / build_binary.sh):
    tz-tool.exe run --folder references/business-tz -o версии/версия-4
"""
import argparse
import importlib
import io
import os
import sys
import json

if not getattr(sys.stdout, "_tz_utf8", False):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stdout._tz_utf8 = True

# В _pth-режиме portable Python (portable/python/python311._pth) директория
# скрипта НЕ добавляется в sys.path автоматически — добавляем явно, чтобы
# importlib нашёл соседние модули конвейера (extract_spec и др.).
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _dispatch(module_name, argv):
    """Вызывает main() скрипта конвейера в текущем процессе — работает и в
    dev-режиме, и внутри Nuitka-бинарника (где .py-файлы не лежат на диске)."""
    mod = importlib.import_module(module_name)
    old = sys.argv
    sys.argv = [module_name] + argv
    try:
        mod.main()
    finally:
        sys.argv = old


def cmd_extract(args):
    argv = []
    if args.folder:
        argv += ["--folder", args.folder]
    elif args.sample:
        argv += [args.sample]
    else:
        sys.exit("extract: нужен --folder или sample")
    if getattr(args, "elements", None):
        argv += ["--elements", args.elements]
    if getattr(args, "specimen", None):
        argv += ["--specimen", args.specimen]
    if getattr(args, "pii", None):
        argv += ["--pii", args.pii]
    if getattr(args, "catalog", None):
        argv += ["--catalog", args.catalog]
    argv += ["-o", args.out]
    _dispatch("extract_spec", argv)
    if getattr(args, "progress", None):
        from tz_common import record_progress
        record_progress(args.progress, "4", "extract_spec", "PASS",
                        [args.out])


def cmd_build(args):
    argv = [args.spec, "-o", args.out]
    if getattr(args, "pii", None):
        argv += ["--pii", args.pii]
    _dispatch("build_from_spec", argv)
    if getattr(args, "progress", None):
        from tz_common import record_progress
        record_progress(args.progress, "5", "build_from_spec", "PASS",
                        [args.out])


def _work_root_from(spec_path):
    """D2 (прогон -59): корень рабочей папки по пути spec — поднимаемся
    до папки, содержащей «projects» (или до трёх уровней вверх)."""
    d = os.path.dirname(os.path.abspath(spec_path or ""))
    for _ in range(6):
        if os.path.isdir(os.path.join(d, "projects")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def cmd_verify(args):
    argv = [args.spec, args.template, "-o", args.out]
    _wr = _work_root_from(getattr(args, "spec", None))
    if _wr:
        argv += ["--work", _wr]
    if getattr(args, "filled", False):
        argv.append("--filled")
    if getattr(args, "md", None):
        argv += ["--md", args.md]
    _dispatch("verify_template", argv)


def cmd_rendermd(args):
    """Б10: --spec/--figs/--set прокидываются в render_md — один вход
    вместо прямого вызова render_md.py."""
    argv = [args.md, "--template", args.template, "-o", args.out]
    if getattr(args, "spec", None):
        argv += ["--spec", args.spec]
    if getattr(args, "figs", None):
        argv += ["--figs", args.figs]
    for kv in getattr(args, "sets", None) or []:
        argv += ["--set", kv]
    _dispatch("render_md", argv)


def apply_overrides(spec_path):
    """Б9: overrides-файл решений пользователя/модели переживает полный
    перегон. Рядом со spec.json (в рабочей версии): overrides.json.
    Формат: {"roles_add": ["рррРоль"],        — union в spec.roles (без дублей)
             "set": {"header_footer": {...}}} — перезапись ключей верхнего
                                                уровня (колонтитулы, титул, …)
    Применяется ПОСЛЕ extract (перегон extract поверх overrides не стирает
    их). Файла нет — no-op."""
    ov_path = os.path.join(os.path.dirname(os.path.abspath(spec_path)),
                           "overrides.json")
    if not os.path.isfile(ov_path):
        return
    with open(ov_path, encoding="utf-8") as fh:
        ov = json.load(fh)
    with open(spec_path, encoding="utf-8") as fh:
        spec = json.load(fh)
    for role in ov.get("roles_add") or []:
        roles = spec.setdefault("roles", [])
        if role not in roles:
            roles.append(role)
    for key, val in (ov.get("set") or {}).items():
        spec[key] = val
    with open(spec_path, "w", encoding="utf-8") as fh:
        json.dump(spec, fh, ensure_ascii=False, indent=1)
    print(f"[tz_tool] overrides применены: {ov_path}", file=sys.stderr)


def cmd_run(args):
    """Полный конвейер: extract → overrides → build → verify. Все артефакты — в -o <dir>."""
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    auto_prog = _work_root_from(os.path.join(out_dir, "spec.json"))
    if auto_prog:
        auto_prog = os.path.join(auto_prog, "прогресс.json")
    spec = os.path.join(out_dir, "spec.json")
    template = os.path.join(out_dir, "шаблон_ТЗ_1С.docx")
    report = os.path.join(out_dir, "отчёт_проверки.md")

    cmd_extract(argparse.Namespace(
        folder=args.folder, sample=args.sample, out=spec,
        elements=getattr(args, "elements", None),
        specimen=getattr(args, "specimen", None),
        pii=getattr(args, "pii", None),
        catalog=getattr(args, "catalog", None),
        progress=auto_prog))
    apply_overrides(spec)
    cmd_build(argparse.Namespace(spec=spec, out=template, progress=auto_prog))
    cmd_verify(argparse.Namespace(spec=spec, template=template, out=report))


def main():
    ap = argparse.ArgumentParser(
        prog="tz-tool", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("extract", help="образец → spec.json")
    p.add_argument("sample", nargs="?", help="путь к образцу DOCX")
    p.add_argument("--folder", help="папка с образцами (шаблон = пересечение всех)")
    p.add_argument("--elements", help="только эти элементы каталога (id через "
                   "запятую, напр. title-page; сегментация по detection каталога)")
    p.add_argument("--specimen", help="лист-образец внутритекстового элемента "
                   "(класс C: figure, table, bulleted-list, note-block...)")
    p.add_argument("--pii", choices=["sanitize", "keep"], default="sanitize",
                   help="ПДн: sanitize — вымышленные примеры, логотипы-заглушки "
                   "(по умолчанию); keep — копировать реальные")
    p.add_argument("--catalog", help="путь к document-model.ru.yaml")
    p.add_argument("-o", "--out", default="spec.json", help="полный путь к spec.json")
    p.add_argument("--progress", help="путь к прогресс.json (запись шага 4 при успехе)")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("build", help="spec.json → шаблон DOCX")
    p.add_argument("spec", help="путь к spec.json")
    p.add_argument("-o", "--out", default="шаблон_ТЗ_1С.docx",
                   help="полный путь к шаблону")
    p.add_argument("--pii", choices=("sanitize", "keep"), default=None,
                   help="ПДн: sanitize (по умолчанию) / keep")
    p.add_argument("--progress", help="путь к прогресс.json (запись шага 5 при успехе)")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("verify", help="проверка шаблона (pass/fail)")
    p.add_argument("spec", help="путь к spec.json")
    p.add_argument("template", help="путь к шаблону DOCX")
    p.add_argument("-o", "--out", default="отчёт_проверки.md",
                   help="полный путь к отчёту")
    p.add_argument("--filled", action="store_true",
                   help="режим заполненного ТЗ: проверки плотности против spec пропускаются")
    p.add_argument("--md", help="путь к Markdown ТЗ (нумерация проверяется по его структуре)")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("rendermd", help="Markdown ТЗ → DOCX через шаблон")
    p.add_argument("md", help="путь к Markdown-файлу ТЗ")
    p.add_argument("--template", required=True, help="шаблон DOCX (стили/нумерация/шапка)")
    p.add_argument("-o", "--out", default="ТЗ.docx", help="полный путь к выходному DOCX")
    p.add_argument("--spec", help="spec.json (ширины таблиц, ритм абзацев)")
    p.add_argument("--figs", help="JSON {номер: описание} — замена [ОПИСАНИЕ ИЗОБРАЖЕНИЯ]")
    p.add_argument("--set", dest="sets", action="append", default=[],
                   metavar="КЛЮЧ=ЗНАЧЕНИЕ",
                   help="замена титульных плейсхолдеров (повторяемо)")
    p.set_defaults(func=cmd_rendermd)

    p = sub.add_parser("run", help="полный конвейер: extract → build → verify")
    p.add_argument("sample", nargs="?", help="путь к образцу DOCX")
    p.add_argument("--folder", help="папка с образцами (шаблон = пересечение всех)")
    p.add_argument("--elements", help="только эти элементы каталога (id через "
                   "запятую, напр. title-page)")
    p.add_argument("--specimen", help="лист-образец внутритекстового элемента")
    p.add_argument("--pii", choices=["sanitize", "keep"], default="sanitize",
                   help="ПДн: sanitize (по умолчанию) / keep")
    p.add_argument("--catalog", help="путь к document-model.ru.yaml")
    p.add_argument("-o", "--out", required=True, help="папка для всех артефактов")
    p.set_defaults(func=cmd_run)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()