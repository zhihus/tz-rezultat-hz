# -*- coding: utf-8 -*-
"""check_map.py — гейт карты объектов ДО черновика тех-ТЗ (E-51).

Карта obj-map.json (схема references/obj-map.schema.json, метод
references/tech-tz-map.ru.md) проверяется ДО написания текста:
выдуманный объект отсеивается на карте, а не в готовом ТЗ.

Проверки (единый ряд с линтом черновика):
  G7 v8std-имена: имя объекта — идентификатор 1С (без пробелов);
     --prefix P — имя нового/дорабатываемого объекта начинается с
     префикса расширения; синоним обязателен и человеческий (не равен
     имени); тип реквизита — как в конфигураторе (не пустой);
  G8 выгрузка: «доработка»/«существующий» — объект НАЙДЕН в cf/cfe
     (та же _config_lookup, что G6 линта); «новый» — НЕ найден (иначе
     это доработка, статус ложный);
  G9 зависимости: пути метаданных из сценариев/целей/форм существуют;
     граф deps ацикличен; конец дуги — id из карты ИЛИ путь из выгрузки;
  G10 полнота: doc_code против spec (если в spec есть код); роли из
     карты — в spec.roles ИЛИ в выгрузке (Roles), иначе «новая роль —
     вопрос пользователю».

Код возврата 1 при нарушениях, 0 если чисто. [ПРЕДУПРЕЖДЕНИЕ] не мешает
проходу, но докладывается.
"""

import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lint_draft import _config_lookup, _KIND_DIRS, _TYPE_TAG, _type_tags  # единая точка правды
from tz_common import record_progress  # progress.json пишет только скрипт

_ID_RE = re.compile(r"^[А-Яа-яёЁA-Za-z0-9_]+$")
_KINDS = {"РегистрСведений", "РегистрНакопления", "Справочник", "Документ",
          "Перечисление", "Отчет", "Обработка", "РегистрРасчета", "Константа",
          "ПланВидовХарактеристик"}  # ПВХ (D5, прогон -59)
_STATUSES = {"новый", "доработка", "существующий"}
_FORM_STATUS = {"новая", "доработка", "существующая"}
_TRIGGERS = {"форма", "расписание", "проведение", "событие"}
_OWNER_RE = re.compile(r"^(Документ|Справочник|Обработка|Отчет|РегистрСведений|"
                       r"РегистрНакопления)\.[А-Яа-яёЁA-Za-z0-9_]+$")
_STEP_RE = re.compile(r"^(Дано|Когда|Тогда|И):?\s+\S")
# G20 (run-59): what — короткая именная фраза; условия («если/когда/при…»)
# живут в шагах сценария, а не в what. Слово — на границе (пробел/конец).
_G20_COND_RE = re.compile(r"^(Если|Когда|При)(\s|$)", re.IGNORECASE)


def _collect_refs(m, new_ids):
    """Пути метаданных карты из структурированных полей (forms.owner,
    backend.target, deps): сценарии — текст, там имена в кавычках, не пути."""
    refs = set()
    for f in m.get("forms") or []:
        if _OWNER_RE.match(f.get("owner", "")):
            refs.add(f["owner"])
    for b in m.get("backend") or []:
        if re.match(r"^(Документ|Справочник|Обработка|Отчет|РегистрСведений|"
                    r"РегистрНакопления)\.", b.get("target", "")):
            refs.add(b["target"])
    for d in m.get("deps") or []:
        for side in (d.get("from"), d.get("to")):
            if re.match(r"^(Документ|Справочник|Обработка|Отчет|РегистрСведений|"
                        r"РегистрНакопления)\.", side or ""):
                refs.add(side)
    # Б8: ссылка на НОВЫЙ объект легитимна и с префиксом вида
    # («РегистрСведений.рткНовый…») — bare-id противоречит стилю полей
    # карты; фильтр — и по id, и по bare-id после точки
    def _is_new(r):
        return r in new_ids or (r.split(".", 1)[1] in new_ids
                                if "." in r else False)
    return sorted(r for r in refs if not _is_new(r))


def _resolve_form_path(config_paths, kind_ru, obj_name, form_name):
    """Форм-путь «Вид.X.Форма.Y» → каталог Forms/<Y> внутри объекта X.
    Расширение ПЕРВЫМ (E-50); возвращает метку выгрузки, где форма найдена."""
    kind_dir = _KIND_DIRS.get(kind_ru.lower())
    if kind_dir is None:
        return None
    target = form_name.lower()
    for label, base in config_paths:
        forms_dir = os.path.join(base, kind_dir, obj_name, "Forms")
        if not os.path.isdir(forms_dir):
            continue
        for f in glob.glob(os.path.join(forms_dir, "*.xml")):
            if os.path.basename(f)[:-4].lower() == target:
                return label
    return None


def _export_synonym(config_paths, obj):
    """Синоним объекта из выгрузки (Properties/Synonym → content) → текст | None.
    run-59: синоним==имя легитимен, только если выгрузка это подтверждает."""
    from lxml import etree
    kind_ru, name = obj.split(".", 1)
    kind_dir = _KIND_DIRS.get(kind_ru.lower())
    if kind_dir is None:
        return None
    tags = _type_tags(kind_dir)
    target = name.lower()
    for label, base in config_paths:
        d = os.path.join(base, kind_dir)
        if not os.path.isdir(d):
            continue
        xml_path = None
        for f in glob.glob(os.path.join(d, "*.xml")):
            if os.path.basename(f)[:-4].lower() == target:
                xml_path = f
                break
        if xml_path is None:
            continue
        try:
            tree = etree.parse(xml_path)
        except etree.XMLSyntaxError:
            continue
        obj_el = next((c for c in tree.getroot()
                       if etree.QName(c).localname in tags), None)
        if obj_el is None:
            continue
        for syn in obj_el.iter():
            if etree.QName(syn).localname != "Synonym":
                continue
            for c in syn.iter():
                if etree.QName(c).localname == "content" and c.text:
                    return c.text.strip()
    return None


def check_map(m, spec, config_paths, prefix=None):
    problems, warnings = [], []
    new_ids = {o["id"] for o in m.get("objects") or [] if o.get("status") == "новый"}

    for o in m.get("objects") or []:
        oid = o.get("id", "")
        if not _ID_RE.match(oid):
            problems.append(f"[G7] имя объекта «{oid}» — не идентификатор 1С "
                            f"(пробелы/недопустимые символы, стандарт именования v8std).")
        if o.get("kind") not in _KINDS:
            problems.append(f"[G7] «{oid}»: вид «{o.get('kind')}» не из списка "
                            f"({_KINDS_LIST}).")
        if o.get("status") not in _STATUSES:
            problems.append(f"[G8] «{oid}»: статус «{o.get('status')}» не из "
                            f"{sorted(_STATUSES)}.")
        syn = o.get("synonym", "")
        if not syn:
            problems.append(f"[G7] «{oid}»: синоним обязателен (стандарт v8std).")
        elif syn.strip() == oid:
            # run-59: синоним==имя легитимен, если выгрузка подтверждает
            # (Synonym в XML равен имени объекта) — «человеческий синоним»
            # к таким объектам не требуется.
            if _export_synonym(config_paths, f"{o['kind']}.{oid}") != oid:
                problems.append(f"[G7] «{oid}»: синоним равен имени — синоним должен "
                                f"быть человеческим («{oid}» vs «{syn}»).")
        # naming-and-emphasis-universal: эффективный префикс — явный
        # --prefix (перекрывает) или выведенный spec.meta.naming.prefix;
        # обоих нет → префиксных FAIL нет (G8-поиск остаётся).
        _eff_prefix = prefix or (((spec.get("meta") or {}).get("naming") or {}).get("prefix"))
        if o.get("status") in ("новый", "доработка") and _eff_prefix and not oid.startswith(_eff_prefix):
            # D6 (прогон -59): заимствованный объект (Adopted — есть в
            # основной конфигурации) расширением не переименовывается:
            # префикс обязателен только для «новый» и объектов,
            # СОЗДАННЫХ в расширении.
            _borrowed = (o.get("status") == "доработка" and
                         _config_lookup(config_paths,
                                        f"{o['kind']}.{oid}", None) is not None
                         and "cf" in str(config_paths))
            if not _borrowed:
                problems.append(f"[G7] «{oid}»: имя объекта расширения должно начинаться "
                                f"с префикса «{_eff_prefix}» (стандарт именования расширения).")
        # run-59: синоним НЕ должен начинаться с префикса — префикс для имён,
        # не для синонимов. Постфикс (spec.meta.naming.synonym_postfix) легитимен
        # и не флагится.
        if _eff_prefix and syn.strip().startswith(_eff_prefix):
            problems.append(f"[G7] «{oid}»: синоним «{syn}» начинается с префикса "
                            f"«{_eff_prefix}» — префикс для имён, не для синонимов.")
        for a in o.get("attrs") or []:
            if not _ID_RE.match(a.get("name", "")):
                problems.append(f"[G7] «{oid}»: имя реквизита «{a.get('name')}» — не "
                                f"идентификатор 1С.")
            if not (a.get("type") or "").strip():
                problems.append(f"[G7] «{oid}.{a.get('name')}»: тип обязателен — как в "
                                f"конфигураторе («Дата (состав даты — „Месяц“)», "
                                f"«Булево», «СправочникСсылка.X», «Строка (10)»).")
        # G8: существование против выгрузки (путь в терминах линта: «Вид.Имя»)
        hit = _config_lookup(config_paths, f"{o['kind']}.{oid}", None) \
            if o.get("kind") in _KINDS and o.get("status") in _STATUSES else None
        if o.get("status") in ("доработка", "существующий"):
            if hit is None:
                problems.append(f"[G8] «{oid}» ({o.get('kind')}, {o.get('status')}) не "
                                f"найден ни в расширении, ни в основной конфигурации → "
                                f"выдуман или статус ложный; проверка через Юник.")
        elif o.get("status") == "новый" and hit is not None:
            problems.append(f"[G8] «{oid}» помечен «новый», но уже существует в «{hit['source']}» "
                            f"→ это доработка, исправить статус.")

    for f in m.get("forms") or []:
        if f.get("status") not in _FORM_STATUS:
            problems.append(f"[G8] форма «{f.get('owner')}.{f.get('name')}»: статус "
                            f"«{f.get('status')}» не из {sorted(_FORM_STATUS)}.")
    for b in m.get("backend") or []:
        # G20 (run-59): what — короткая именная фраза (≤12 слов, без условий).
        _what = b.get("what") or ""
        if _G20_COND_RE.match(_what) or len(_what.split()) > 12:
            problems.append(f"[G20] сценарий «{_what}»: what — короткая именная фраза "
                            f"(≤12 слов, без условий «если/когда/при…» — условия живут "
                            f"в шагах сценария).")
        if b.get("trigger") not in _TRIGGERS:
            problems.append(f"[G9] триггер «{b.get('trigger')}» не из {sorted(_TRIGGERS)} "
                            f"(расписание — отдельный класс бэкенда, не привязан к форме).")
        if b["trigger"] == "расписание" and not b.get("period"):
            problems.append(f"[G9] сценарий с триггером «расписание»: укажи периодичность "
                            f"в поле period («{b.get('what')}»).")
        steps = b.get("scenario") or []
        if not steps or not all(_STEP_RE.match(s) for s in steps):
            problems.append(f"[G9] сценарий «{b.get('what')}»: шаги — «Дано:/Когда:/Тогда:/И:» "
                            f"(Gherkin, диалект Vanessa Automation).")
        elif not any(s.startswith("Когда") for s in steps) or \
                not any(s.startswith("Тогда") for s in steps):
            problems.append(f"[G9] сценарий «{b.get('what')}»: нужны минимум шаги «Когда» и "
                            f"«Тогда».")
    for d in m.get("decisions") or []:
        if not d.get("alternative"):
            warnings.append(f"[G10] решение «{d.get('question')}» без отвергнутой альтернативы — "
                            f"модель выбирает, а не выдумывает; добавь alternative или вопрос "
                            f"пользователю.")

    # G9: пути метаданных карты против выгрузки
    for p in _collect_refs(m, new_ids):
        parts = p.split(".")
        if len(parts) == 4 and parts[2].lower().startswith("форм"):
            # Форм-путь «Вид.X.Форма.Y» → каталог Forms/<Y> внутри X (ext first)
            if _resolve_form_path(config_paths, parts[0], parts[1], parts[3]) is None:
                problems.append(f"[G9] форм-путь «{p}» из карты отсутствует И в "
                                f"расширении, И в основной конфигурации → выдуман "
                                f"или опечатка.")
            continue
        if _config_lookup(config_paths, p, None) is None:
            problems.append(f"[G9] путь «{p}» из карты отсутствует И в расширении, И в "
                            f"основной конфигурации → выдуман или опечатка.")

    # G9: граф deps ацикличен; концы дуг разрешимы
    ids = {o.get("id") for o in m.get("objects") or []}
    edges = {}
    def _known(side):
        """id из карты ИЛИ путь «Вид.Имя» из выгрузки."""
        if side in ids:
            return True
        if re.match(r"^(Документ|Справочник|Обработка|Отчет|РегистрСведений|"
                    r"РегистрНакопления|ПланВидовХарактеристик)\.", side or ""):
            return _config_lookup(config_paths, side, None) is not None
        return False
    for d in m.get("deps") or []:
        a, b = d.get("from"), d.get("to")
        if not _known(a):
            problems.append(f"[G9] зависимость {a} → {b}: начало «{a}» не в карте и не в выгрузке.")
            continue
        if not _known(b):
            problems.append(f"[G9] зависимость {a} → {b}: конец «{b}» не в карте и не в выгрузке.")
            continue
        edges.setdefault(a, []).append(b)
    state = {}
    def _dfs(u):
        state[u] = 1
        for v in edges.get(u, []):
            if state.get(v) == 1:
                return False
            if state.get(v, 0) == 0 and not _dfs(v):
                return False
        state[u] = 2
        return True
    for u in list(edges):
        if state.get(u, 0) == 0 and not _dfs(u):
            problems.append("[G9] граф зависимостей содержит цикл → порядок разделов "
                            "«зависимость до зависимого» невозможен; разорвать цикл.")
            break

    # G10: код документа и роли
    code = m.get("doc_code")
    spec_code = ((spec.get("meta") or {}).get("doc_code")
                 or spec.get("doc_code") or "")
    if code and spec_code and code != spec_code:
        problems.append(f"[G10] doc_code карты «{code}» ≠ коду в spec «{spec_code}».")
    roles_cfg = set()
    for label, base in config_paths:
        d = os.path.join(base, "Roles")
        if os.path.isdir(d):
            roles_cfg |= {os.path.basename(f)[:-4] for f in
                          __import__("glob").glob(os.path.join(d, "*.xml"))}
    # в карте роль — человеческое имя (синоним); сверяем и с синонимами XML
    roles_syn = set()
    if config_paths:
        from lxml import etree
        for label, base in config_paths:
            d = os.path.join(base, "Roles")
            if not os.path.isdir(d):
                continue
            for f in __import__("glob").glob(os.path.join(d, "*.xml")):
                try:
                    t = etree.parse(f)
                except etree.XMLSyntaxError:
                    continue
                # Properties/Synonym/v8:item/v8:content — имена ns разные в cf/cfe,
                # идём по localname
                for syn in t.getroot().iter():
                    if etree.QName(syn).localname != "Synonym":
                        continue
                    for c in syn.iter():
                        if etree.QName(c).localname == "content" and c.text:
                            roles_syn.add(c.text)
    spec_roles = set(spec.get("roles") or [])
    for r in m.get("roles") or []:
        if r not in spec_roles and r not in roles_cfg and r not in roles_syn:
            problems.append(f"[G10] роль «{r}» не из образцов и не из выгрузки → новая "
                            f"роль — вопрос пользователю, не придумывать.")
    # G17 «как устроен» (question-necessity-gate): форма существующая/
    # доработанная без elements и new_elements — уровень «объект есть»,
    # не «как устроен» → вопрос снят бы исследованием. Только формы:
    # пустой attrs объекта легален (заимствованный объект несёт в карте
    # только НОВЫЕ реквизиты).
    for f in m.get("forms") or []:
        if (f.get("status") in ("доработка", "существующая")
                and not (f.get("elements") or f.get("new_elements"))):
            problems.append(f"[G17] форма «{f.get('owner')}.{f.get('name')}» "
                            f"({f.get('status')}) без elements и new_elements — "
                            f"исследование на уровне «объект есть»: добрать элементы "
                            f"формы (Unica/выгрузка) до текста.")
    return problems, warnings


_KINDS_LIST = ", ".join(sorted(_KINDS))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("map", help="obj-map.json")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--config", action="append", default=[],
                    help="выгрузка 1С «метка=путь» (ext|main); расширение — ПЕРВЫМ")
    ap.add_argument("--prefix", default=None,
                    help="префикс имён объектов расширения (напр. ртк)")
    ap.add_argument("--progress", default=None,
                    help="прогресс.json — записать вердикт шага 6 при PASS")
    args = ap.parse_args()
    config_paths = []
    for c in args.config:
        label, _, path = c.partition("=")
        config_paths.append((label or "main", path))
    with open(args.map, encoding="utf-8") as fh:
        m = json.load(fh)
    spec = {}
    if os.path.exists(args.spec):
        with open(args.spec, encoding="utf-8") as fh:
            spec = json.load(fh)
    for key in ("doc_code", "objects", "forms", "backend", "roles"):
        if key not in m:
            print(f"[G9] в карте нет обязательного поля «{key}» "
                  f"(схема references/obj-map.schema.json).")
    problems, warnings = check_map(m, spec, config_paths, args.prefix)
    if problems:
        print(f"[КАРТА] нарушений: {len(problems)}")
        for p in problems:
            print(p)
    for w in warnings:
        print(w)
    if problems:
        print("[ИТОГ] править карту (или вопрос пользователю) → перезапустить check_map "
              "→ только после PASS черновик по карте (tech-tz-map.ru.md §4).")
        sys.exit(1)
    if warnings:
        print("[ИТОГ] карта прошла с предупреждениями (см. выше).")
    else:
        print("[ИТОГ] карта чиста → черновик разрешён.")
    # process-flow: шаг 6 закрыт записью гейта в прогресс.json (не моделью)
    record_progress(args.progress, "6", "check_map", "PASS", [args.map])


if __name__ == "__main__":
    main()
