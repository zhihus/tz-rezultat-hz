# -*- coding: utf-8 -*-
"""find_config.py — поиск связки 1С (Шаг 1 п.4; дефект E-38).

Путь назван → скрипт ищет САМ, включая подкаталоги; не нашёл → печатает
ГОТОВУЮ формулировку отчёта, чтобы модель НЕ переспрашивала тем же
вопросом (E-38).

Признаки связки: v8project.yaml, v8project.local.yaml, *.cf, *.cfe.

Использование:
  python find_config.py --path <папка> [--max-depth 4]
"""

import argparse
import os
import sys

_MARKERS = ("v8project.yaml", "v8project.local.yaml")


def _require_yaml(where):
    """PyYAML — обязательная зависимость конвейера (scripts/requirements.txt;
    жёстко импортируется preflight/find_config/verify_template/init_project/
    extract_spec). Отсутствие → понятная диагностика и ненулевой код, без
    необработанного traceback."""
    try:
        import yaml
        return yaml
    except ImportError:
        print("[FAIL] PyYAML не установлен — обязательная зависимость "
              "конвейера (%s)." % where)
        print("[ДЕЙСТВИЕ] агент: запустите Bootstrap --rebuild")
        sys.exit(1)


def _derive_main_ext(hits):
    """Каталоги main (cf) и ext (cfe) из находок — та же логика, что в
    _persist (каталог узнаётся по компоненту пути «cf»/«cfe», а не по
    родителю файла). Возвращает (main, ext) — абсолютные пути или None."""
    main = ext = None
    for h in hits:
        d = h if os.path.isdir(h) else os.path.dirname(h)
        parts = os.path.normpath(d).split(os.sep)
        for i, comp in enumerate(parts):
            base = comp.lower()
            if base == "cfe" or (base.endswith("cfe") and len(base) <= 6):
                if ext is None:
                    cand = os.sep.join(parts[:i + 1])
                    if os.path.isdir(cand):
                        ext = os.path.abspath(cand)
                break
            if base == "cf":
                if main is None:
                    cand = os.sep.join(parts[:i + 1])
                    if os.path.isdir(cand):
                        main = os.path.abspath(cand)
    # выгрузка расширения обычно рядом с cf: <родитель>/cfe
    if main and not ext:
        sib = os.path.join(os.path.dirname(main), "cfe")
        if os.path.isdir(sib):
            ext = os.path.abspath(sib)
    return main, ext


def _v8project_yaml(main, ext):
    """Содержимое v8project.yaml (шаблон эталонных проектов). Пути —
    абсолютные, в forward-slash (YAML/1С принимают оба варианта)."""
    lines = ["workPath: 'build'", "format: DESIGNER", "source-set:"]
    if main:
        lines += ["  - name: main", "    type: CONFIGURATION",
                  "    path: '%s'" % main.replace(os.sep, "/")]
    if ext:
        lines += ["  - name: cfe", "    type: EXTENSION",
                  "    path: '%s'" % ext.replace(os.sep, "/")]
    return "\n".join(lines) + "\n"


def _v8project_paths_match(text, main, ext):
    """Совпадают ли пути в существующем v8project.yaml с ожидаемыми."""
    safe_load = _require_yaml("сверка v8project.yaml").safe_load
    try:
        data = safe_load(text) or {}
    except Exception:
        return False
    got = {}
    for ss in (data.get("source-set") or []):
        if isinstance(ss, dict):
            got[ss.get("name")] = ss.get("path")
    norm = lambda p: os.path.normpath(p.replace("/", os.sep)).lower() if p else None
    want = {"main": main, "cfe": ext}
    for name, wp in want.items():
        if wp is None:
            if got.get(name):
                return False
        elif norm(got.get(name)) != norm(wp):
            return False
    return True


def _gen_v8project(work, hits):
    """Генерация v8project.yaml в корне рабочей папки (идемпотентно):
    пути совпадают → не переписываю; изменились → обновляю и докладываю;
    cfe отсутствует → раздел cfe не пишу (только main).
    Возвращает "actual" | "updated" | "created" | None (нет work/hits)."""
    if not work or not os.path.isdir(work):
        return None
    main, ext = _derive_main_ext(hits)
    if not main and not ext:
        return None
    path = os.path.join(work, "v8project.yaml")
    desired = _v8project_yaml(main, ext)
    if os.path.isfile(path):
        existing = open(path, encoding="utf-8").read()
        if _v8project_paths_match(existing, main, ext):
            print("[V8PROJECT] v8project.yaml актуален (пути совпадают) — не переписываю.")
            return "actual"
        with open(path, "w", encoding="utf-8") as f:
            f.write(desired)
        print("[V8PROJECT] v8project.yaml обновлён (пути изменились): "
              "main=%s, ext=%s" % (main, ext))
        return "updated"
    with open(path, "w", encoding="utf-8") as f:
        f.write(desired)
    print("[V8PROJECT] v8project.yaml создан: main=%s, ext=%s" % (main, ext))
    return "created"


# Решение 2026-11-20: MCP-сервер Юники подключается ТОЛЬКО на старте
# сессии — после создания/обновления v8project.yaml сессия бесполезна
# для unica.*. Код 42 = «перезапуск»; модель анализировать ничего не
# должна: скрипт уже напечатал сообщение пользователю.
_HARNESS_NAME = {"zcode": "ZCode", "claude-code": "Claude Code",
                 "codex": "Codex", "other": "ваш харнесс"}
EXIT_RESTART = 42


def _print_restart(harness):
    print("[ПЕРЕЗАПУСК СЕССИИ ОБЯЗАТЕЛЕН] v8project.yaml создан/обновлён "
          "в ЭТОЙ сессии — MCP-сервер Юники подключается только на старте "
          "сессии; инструменты unica.* в текущей сессии не появятся.")
    print("Чтобы продолжить составление ТЗ, перезапустите %s."
          % _HARNESS_NAME.get(harness, harness))


def find(path, max_depth):
    """Связка 1С: файлы .cf/.cfe, v8project*.yaml ИЛИ каталоги-выгрузки
    Designer — cf/cfe, содержащие Configuration.xml (решение 2026-11-20:
    копия конфигурации в корне рабочей папки обычно лежит именно
    выгрузкой). В выгрузку не спускаемся (десятки тысяч файлов)."""
    hits = []
    for dirpath, dirnames, filenames in os.walk(path):
        depth = dirpath[len(path):].count(os.sep)
        if depth >= max_depth:
            dirnames[:] = []
        lows = [fn.lower() for fn in filenames]
        base = os.path.basename(dirpath).lower()
        if base in ("cf", "cfe") and "configuration.xml" in lows:
            hits.append(os.path.abspath(dirpath))
            dirnames[:] = []  # в выгрузку не спускаться
            continue
        for fn in filenames:
            low = fn.lower()
            if fn in _MARKERS or low.endswith((".cf", ".cfe")):
                hits.append(os.path.abspath(os.path.join(dirpath, fn)))
    return hits


def _persist(work, name, hits):
    """E-56: связка 1С в манифест проекта (projects.yaml), чтобы новая
    сессия не переспрашивала: main/ext выводятся из найденных путей
    (каталог …cfe → ext, иначе main). Ответ пользователя живёт в
    проекте, а не в переписке."""
    if not work:
        return
    _yaml = _require_yaml("фиксация связки в projects.yaml")
    safe_load, safe_dump = _yaml.safe_load, _yaml.safe_dump
    # манифест рядом с work ИЛИ в work/projects/ (обе раскладки)
    manifest = next((p for p in (os.path.join(work, "projects.yaml"),
                                 os.path.join(work, "projects", "projects.yaml"))
                     if os.path.exists(p)), None)
    if not manifest:
        print("[ФИКСАЦИЯ] манифеста projects.yaml нет — путь не зафиксирован; "
              "сохранить после init_project.")
        return
    with open(manifest, encoding="utf-8") as f:
        data = safe_load(f) or {}
    projects = [p for p in (data.get("projects") or []) if isinstance(p, dict)]
    entry = next((p for p in projects if p.get("name") == name), None) if name else None
    if entry is None and len(projects) == 1:
        entry = projects[0]
    if entry is None:
        print("[ФИКСАЦИЯ] проект в манифесте неоднозначен — связка не записана; "
              "перечислите проекты или укажите --name.")
        return
    cfg = entry.setdefault("config", {})
    for h in hits:
        d = h if os.path.isdir(h) else os.path.dirname(h)
        # каталог выгрузки узнаём по компоненту пути «cf»/«cfe» (дампы
        # Designer), а не по родителю файла — внутри выгрузки есть
        # вложенные каталоги (Ext/ParentConfigurations и пр.)
        parts = os.path.normpath(d).split(os.sep)
        key_dir, key = d, "main"
        for i, comp in enumerate(parts):
            base = comp.lower()
            if base == "cfe" or (base.endswith("cfe") and len(base) <= 6):
                key_dir, key = os.sep.join(parts[:i + 1]), "ext"
                break
            if base == "cf":
                key_dir, key = os.sep.join(parts[:i + 1]), "main"
        if not cfg.get(key) and os.path.isdir(key_dir):
            cfg[key] = os.path.abspath(key_dir)
    # выгрузка расширения обычно рядом с cf: <родитель>/cfe
    if cfg.get("main") and not cfg.get("ext"):
        sib = os.path.join(os.path.dirname(cfg["main"]), "cfe")
        if os.path.isdir(sib):
            cfg["ext"] = os.path.abspath(sib)
    if cfg.get("main") or cfg.get("ext"):
        with open(manifest, "w", encoding="utf-8") as f:
            safe_dump(data, f, allow_unicode=True, sort_keys=False)
        print(f"[ФИКСАЦИЯ] связка записана в {manifest} "
              f"(проект «{entry.get('name')}»): ext={cfg.get('ext')}, "
              f"main={cfg.get('main')} — последующие сессии читают её из "
              f"манифеста, НЕ переспрашивая.")
    else:
        print("[ФИКСАЦИЯ] не удалось вывести каталоги ext/main из находок — "
              "путь не записан.")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True)
    ap.add_argument("--max-depth", type=int, default=4)
    ap.add_argument("--work", default=None,
                    help="рабочая папка с projects.yaml — найденная связка "
                         "ЗАФИКСИРУЕТСЯ в манифесте (E-56: ответ «путь "
                         "конфигурации» живёт в проекте, не в переписке)")
    ap.add_argument("--name", default=None,
                    help="имя проекта в манифесте; по умолчанию — единственный проект")
    ap.add_argument("--harness", default="zcode",
                    choices=["zcode", "claude-code", "codex", "other"],
                    help="имя харнесса для сообщения о перезапуске (код 42)")
    args = ap.parse_args()

    if not os.path.isdir(args.path):
        print(f"[ИТОГ] папка не существует: {args.path}")
        print("[ОТЧЁТ ПОЛЬЗОВАТЕЛЮ] путь не существует — уточнить у пользователя другой путь "
              "(переформулировать, не повторять тот же вопрос).")
        return

    hits = find(args.path, args.max_depth)
    for h in hits[:20]:
        print(f"[НАЙДЕНО] {h}")
    if len(hits) > 20:
        print(f"[НАЙДЕНО] … всего {len(hits)} файлов")

    if hits:
        print("[ИТОГ] связка найдена — путь использовать на этапе заполнения; НЕ переспрашивать.")
        _persist(args.work, args.name, hits)
        status = _gen_v8project(args.work, hits)
        if status in ("created", "updated"):
            _print_restart(args.harness)
            sys.exit(EXIT_RESTART)
    else:
        print("[ОТЧЁТ ПОЛЬЗОВАТЕЛЮ] в <%s> связки 1С нет — работаю по описанию доработки, "
              "с пометками «уточнить по конфигурации»." % args.path)
        print("[ИТОГ] другой путь — ТОЛЬКО если пользователь сам предложит (E-38: не переспрашивать).")


if __name__ == "__main__":
    main()
