# -*- coding: utf-8 -*-
"""lint_draft.py — детерминированный линт черновика ДО render_md (Шаг 7).

Скрипт проверяет Markdown-черновик модели против spec.json и печатает
список нарушений с подсказками. Модель правит черновик и перезапускает.
Проверки (правила E-46…E-48):

  G1 глоссарий: термин в таблице Глоссария черновика, которого нет в
     glossary_terms образцов и в описании доработки → «выдумано»;
  G2 «Профиль»: «Типовой» и «Новый» в одной ячейке/строке → ошибка
     (взаимоисключающие, #13);
  G3 роли в таблице прав, отсутствующие в spec.roles → предупреждение
     (реальные роли 1С — из образцов/выгрузки, не придумывать);
  G4 рисунки: «(Рисунок - N)» без парной подписи «Рисунок - N …» и
     подпись без ссылки;
  G5 самодельная разметка: HTML-теги, {{шаблоны}}, \pagebreak и пр.
     (вёрстку ставит конвейер).

Код возврата 0 всегда; решение «править → перегнать» — по строкам.
"""

import argparse
import glob
import json
import os
import re
import sys


# маркер сообщения пользователю в черновике (naming-and-emphasis-universal)
_MSG_MARKER_RE = re.compile(r"\[СООБЩЕНИЕ:\s*[^\[\]]+\]")


def _md_tables(text):
    """Строки таблиц Markdown → список таблиц (списки строк ячеек)."""
    tables, cur = [], []
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                continue  # разделитель
            cur.append(cells)
        else:
            if len(cur) >= 2:
                tables.append(cur)
            cur = []
    if len(cur) >= 2:
        tables.append(cur)
    return tables


def lint(md_path, spec_path, description=None, config_paths=None, figs=None,
         map_path=None, progress=None):
    with open(md_path, encoding="utf-8") as f:
        text = f.read()
    spec = json.load(open(spec_path, encoding="utf-8")) if os.path.exists(spec_path) else {}
    problems = []
    desc = (description or "") + (os.environ.get("TZ_DESCRIPTION") or "")
    tables = _md_tables(text)

    # G1 глоссарий — ТОЛЬКО бизнес-ТЗ (урок 2026-11-20, sess_54d8495b):
    # в тех-ТЗ глоссария нет (SKILL.md §440), G1 сыпал ложными в тех-драфте
    if (spec.get("meta") or {}).get("doc_type", "") != "техническое ТЗ":
        sample_terms = set(spec.get("glossary_terms") or [])
        draft_terms = set()
        for t in tables:
            hdr = {c.lower().strip() for c in t[0]}
            if {"термин", "сокращение"} & hdr:
                for row in t[1:]:
                    if row and row[0]:
                        draft_terms.add(row[0])
        for term in sorted(draft_terms):
            if sample_terms and term not in sample_terms and term not in desc:
                problems.append(f"[G1] Глоссарий: «{term}» нет в образцах и нет в описании "
                                f"→ удалить или задать вопрос пользователю (E-48).")
        for term in sorted(sample_terms - draft_terms):
            if term in text:
                problems.append(f"[G1] Глоссарий: «{term}» из образцов задействован в тексте, "
                                f"но отсутствует в таблице Глоссария → добавить (если объект "
                                f"задействован) или убрать упоминание.")

    # G2 Профиль Типовой/Новый (взаимоисключающие, #13): в любой строке
    # любой таблицы оба слова вместе — ошибка
    for t in tables:
        for row in t[1:]:
            joined = " ".join(row).lower()
            if "типовой" in joined and "новый" in joined:
                problems.append("[G2] «Типовой» и «Новый» в одной строке — "
                                "ВЗАИМОИСКЛЮЧАЮЩИЕ («Типовой» = скопирован из типовой, "
                                "«Новый» = создан с нуля), оставить одно или вопрос (E-48).")

    # G3 роли: колонки «Роль»/«Должность» таблиц прав (реальные роли 1С
    # живут там; первая колонка была недостаточна — роль во второй
    # колонке уходила незамеченной)
    roles = set(spec.get("roles") or [])
    for i, t in enumerate(tables):
        hdr_l = [c.lower() for c in t[0]]
        if any("роль" in h or "права" in h or "доступ" in h for h in hdr_l):
            role_cols = [j for j, h in enumerate(hdr_l)
                         if "роль" in h or "должность" in h]
            for row in t[1:]:
                for j in role_cols:
                    c = row[j] if j < len(row) else ""
                    hit = False
                    for cand in re.findall(r"[А-Яа-яA-Za-z][\w\- ]{1,40}", c):
                        cand = cand.strip()
                        if cand and roles and cand not in roles and \
                                any(r.split()[0] == cand.split()[0] for r in roles) is False and \
                                len(cand.split()) <= 3 and re.match(r"^[А-Яа-я]", cand):
                            problems.append(f"[G3] Роль «{cand}» отсутствует в ролях образцов "
                                            f"({', '.join(sorted(roles))}) → реальные роли 1С "
                                            f"из образцов/выгрузки; незнакомая — вопрос/«уточнить "
                                            f"по конфигурации».")
                            hit = True
                            break
                    if hit:
                        break  # одна жалоба на строку

    # G4 рисунки. Тех-конвейер: подпись ставит render_md из --figs
    # (в draft она НЕ пишется — иначе дубль при рендере), поэтому ссылка,
    # покрытая figs.json, подписи в черновике не требует (E-57).
    fig_nums = set()
    try:
        fig_nums = set(str(k) for k in (figs or {}).keys())
    except Exception:
        pass
    refs = set(int(n) for n in re.findall(r"\(Рисунок\s*-\s*(\d+)\)", text))
    caps = set(int(n) for n in re.findall(r"^Рисунок\s*-\s*(\d+)\s", text, re.M))
    for n in sorted(refs - caps):
        if str(n) in fig_nums:
            continue
        problems.append(f"[G4] «(Рисунок - {n})» без подписи «Рисунок - {n} Название» → "
                        f"в тех-ТЗ: описание рисунка в figs.json для render_md --figs "
                        f"(в draft подпись не писать); в бизнес-ТЗ — добавить подпись.")
    for n in sorted(caps - refs):
        problems.append(f"[G4] Подпись «Рисунок - {n}» без ссылки «(Рисунок - {n})» → добавить ссылку в текст.")

    # G5 самодельная разметка
    if re.search(r"<\w+>|{{|\{\\\\pagebreak|\\\\page\s*break", text, re.I):
        problems.append("[G5] Самодельная разметка (HTML/шаблоны/разрывы) — вёрстку ставит "
                        "конвейер; убрать (E-46).")

    # G6 метаданные против выгрузки конфигурации (E-50, тех-ТЗ):
    # каждый путь вида Документ.X.Y / Обработка.X.Форма.Y и реквизит из
    # пары «имя – Z» сверяется с выгрузкой (cf И cfe, источник указывается).
    # Скрипт читает XML сам (MCP-плагин Юник из скрипта недоступен);
    # агент в чате метаданные смотрит через Юник — это другое место.
    if config_paths:
        # объекты «новый» из карты — не в выгрузке по определению (G8 карты
        # гарантирует); урок 2026-11-20, sess_54d8495b
        _new_ids = set()
        if map_path and os.path.exists(map_path):
            with open(map_path, encoding="utf-8") as _fh:
                _m = json.load(_fh)
            _new_ids = {o.get("id", "") for o in (_m.get("objects") or [])
                        if o.get("status") == "новый"}
        for obj, attr in _draft_metadata_refs(text, desc):
            if obj.split(".")[1] in _new_ids if "." in obj else obj in _new_ids:
                continue
            hit = _config_lookup(config_paths, obj, attr)
            if hit is None:
                problems.append(
                    f"[G6] «{obj}»"
                    + (f".{attr}" if attr else "")
                    + " отсутствует И в расширении, И в основной конфигурации → "
                      "выдумано или опечатка; проверить через Юник или вопрос (E-50).")
            elif attr and not hit.get("attr"):
                problems.append(
                    f"[G6] у объекта «{obj}» нет реквизита «{attr}» "
                    f"(объект есть в «{hit['source']}») → опечатка; вопрос.")
    # G11 реквизиты — ТАБЛИЦЕЙ (E-52): «Реквизиты/Измерения/Ресурсы …:» +
    # список «a – b – c» вместо markdown-таблицы (в тех-образцах это
    # таблица «Имя|Синоним|Тип», вариация в spec.variations.tables)
    _lines = text.splitlines()
    for _i, _ln in enumerate(_lines):
        _s = _ln.strip()
        if re.match(r"^(Реквизиты|Измерения|Ресурсы)\b[^\n]*:\s*$", _s):
            _win = "\n".join(_lines[_i + 1:_i + 8])
            if "|" not in _win and re.search(
                    r"^\s*[-•*]\s*[А-Яа-яёЁA-Za-z0-9_]+\s*–\s*"
                    r"[А-Яа-яёЁA-Za-z0-9_]+\s*–\s*[А-Яа-яёЁA-Za-z0-9_]+",
                    _win, re.M):
                problems.append(
                    "[G11] после «" + _s + "» реквизиты «триадой» в одну строку "
                    "(«имя – синоним – тип») — так в образцах НЕ пишут: либо "
                    "слотами списка «имя – X, / синоним – Y, / тип – Z» (образец 47, "
                    "§4.2), либо таблицей «Имя | Синоним | Тип» (образец 10).")

    # G13–G15 — ТОЛЬКО тех-ТЗ (уроки сессии 2026-11-19): в бизнес-образцах
    # «Система проверяет…» и Дано — легитимный стиль, там не применяются.
    if (spec.get("meta") or {}).get("doc_type") == "техническое ТЗ":
        g13 = g14 = False
        for ln in text.splitlines():
            g13 = g13 or bool(re.match(r"\s*(Дано|Когда|Тогда)(:|\s)", ln))
            g14 = g14 or bool(re.match(r"\s*Система\s+(выполняет|сбрасывает|создаёт|"
                                       r"формирует|удаляет|пересоздаёт|проверяет|"
                                       r"обновляет)\b", ln, re.I))
        if g13:
            problems.append("[G13] шаги «Дано/Когда/Тогда» в итоговом тех-ТЗ "
                            "ЗАПРЕЩЕНЫ — человеческая форма: Условие / Событие / "
                            "Алгоритм / Результат (пользовательский ваншот O5u).")
        if g14:
            problems.append("[G14] отчётная форма «Система …» — тех-ТЗ пишется "
                            "ДЕКЛАРАТИВНО, задачей разработчику: «должна быть "
                            "добавлена», «добавляется», «блокируется».")
        for m in re.finditer(r"^#{2,4}\s+.*?(\w+При(?:Изменении|Создании|Выборе|"
                             r"Открытии|Закрытии)|ОбработкаОжидания|ПередЗаписью)\b",
                             text, re.M):
            problems.append(f"[G15] заголовок-идентификатор «{m.group(1)}» — заголовок "
                            f"события: СУТЬ ситуации словами (как в образцах), "
                            f"имя обработчика — в тело.")
    # G16 квадратные скобки в теле черновика (D9, прогон -59): «[X]»
    # превращается в плейсхолдер DOCX и ловится только final_gate —
    # полный перегон. Разрешены: подписи «Рисунок - N …», ссылки
    # «(Рисунок - N)», inline «[уточнить по конфигурации: …]», токены
    # [КОД]/[ВЕРСИЯ], маркер сообщения [СООБЩЕНИЕ: …] (naming-and-
    # emphasis-universal — рендерится по конвенции, см. G18). FAIL
    # с номером строки.
    _msg_emph = ((spec.get("meta") or {}).get("message_emphasis") or None)
    for _i, _ln in enumerate(text.splitlines(), 1):
        if _ln.lstrip().startswith("Рисунок") or "(Рисунок" in _ln:
            continue
        for _m in re.finditer(r"\[([^\[\]]+)\]", _ln):
            _inner = _m.group(1).strip()
            if _inner in ("КОД", "ВЕРСИЯ"):
                continue
            if _inner.lower().startswith("уточнить по конфигурации"):
                continue
            if _inner.startswith("СООБЩЕНИЕ:"):
                continue  # маркер сообщения — правило G18 ниже
            problems.append(f"[G16] строка {_i}: «{_m.group(0)}» — квадратные "
                            f"скобки в тексте станут плейсхолдером DOCX; "
                            f"убрать скобки или оформить иначе.")
    # G18 маркер сообщения [СООБЩЕНИЕ: …] (naming-and-emphasis-universal):
    # конвенция выделения сообщений в образцах не выведена
    # (spec.meta.message_emphasis = null) → маркер нечем отрендерить.
    if _MSG_MARKER_RE.search(text) and not _msg_emph:
        problems.append("[G18] в черновике есть маркер [СООБЩЕНИЕ: …], но в образцах "
                        "не найден шаблон выделения сообщений (spec.meta.message_emphasis "
                        "= null) → убрать маркер (обычный текст) или вопрос пользователю.")
    # G12 дубль описания в событиях (урок 2026-11-18): пары
    # «имя – …»/«синоним – …» описывают элемент формы в разделе форм
    # ОДИН раз; в секциях «Событие: …» (H2/H3) они запрещены — событие
    # описывает поведение, не повторяя реквизиты элемента.
    _cur_event = None
    for _ln in text.splitlines():
        # Б6: сброс на заголовке ЛЮБОГО уровня (#{1,4}): H1 «# Создать
        # новые роли» после секции «Событие» не сбрасывал трекер — ложный
        # G12 на «Имя – …» в разделе новых ролей
        _h = re.match(r"^(#{1,4})\s+(.*)$", _ln)
        if _h:
            _cur_event = "Событие" in _h.group(2)
            continue
        if _cur_event and re.match(
                r"^\s*(?:[-•*]\s*)?(?:имя|синоним)\s*[–—-]\s*\S", _ln, re.I):
            problems.append(
                "[G12] пара «имя/синоним» внутри секции «Событие: …» — "
                "элемент формы описывается ОДИН раз в разделе форм; "
                "событие описывает поведение, не повторяя имя/синоним "
                "(урок итога -62_V5).")

    # G19 табличная часть (run-59): имя табличной части, упомянутое в
    # черновике («табличная часть X» / «по табличной части X»), MUST
    # совпадать с Name или Synonym TabularSection в выгрузке; выдуманная →
    # FAIL. ТОЛЬКО тех-ТЗ и только при наличии выгрузки (иначе нечего
    # проверять).
    if ((spec.get("meta") or {}).get("doc_type") == "техническое ТЗ"
            and config_paths):
        _tab_names = _export_tabular_sections(config_paths)
        if _tab_names:
            for _m in re.finditer(r"табличн\w*\s+част\w*\s*«([^»]+)»", text):
                _tn = _m.group(1).strip().lower()
                if _tn not in _tab_names:
                    problems.append(f"[G19] табличная часть «{_m.group(1)}» "
                                    f"отсутствует в выгрузке (нет TabularSection "
                                    f"с таким Name или Synonym) → выдумана.")

    if not problems and progress:
        from tz_common import record_progress
        record_progress(progress, "7", "lint_draft", "PASS", [md_path])

    return problems


def _draft_metadata_refs(text, desc):
    """Точечные пути метаданных и реквизиты из черновика → [(obj, attr|None)].
    Паттерны: «Документ.X.Y», «Обработка.X.Форма.Y», «Справочник.X»;
    пары «имя – Z» после описания реквизита дают attr=None (объект
    проверяется при поиске по контексту отдельно)."""
    refs = []
    seen = set()
    for m in re.finditer(
            r"(Документ|Справочник|Обработка|Отчет|РегистрСведений|"
            r"РегистрНакопления)\.([А-Яа-яёЁA-Za-z0-9_]+)"
            r"(?:\.([А-Яа-яёЁA-Za-z0-9_]+))?", text):
        obj = f"{m.group(1)}.{m.group(2)}"
        attr = m.group(3)
        # Форма.Y — часть пути формы, не реквизит объекта
        if attr and attr.lower().startswith("форм"):
            attr = None
        key = (obj, attr)
        if key not in seen:
            seen.add(key)
            refs.append(key)
    return refs


_KIND_DIRS = {
    "документ": "Documents", "справочник": "Catalogs",
    "обработка": "DataProcessors", "отчет": "Reports",
    "регистрсведений": "InformationRegisters",
    "регистрнакопления": "AccumulationRegisters",
    "регистррасчета": "CalculationRegisters", "роль": "Roles",
    "перечисление": "Enums",
    "планвидовхарактеристик": "ChartsOfCharacteristicTypes",  # ПВХ (D5)
}
_TYPE_TAG = {
    "Documents": "Document", "Catalogs": "Catalog",
    "DataProcessors": "DataProcessor", "Reports": "Report",
    "InformationRegisters": "InformationRegister",
    "AccumulationRegisters": "AccumulationRegister",
    "CalculationRegisters": "CalculationRegister", "Roles": "Role",
    "Enums": "Enum",
    "ChartsOfCharacteristicTypes": "ChartOfCharacteristicType",  # ПВХ (D5)
}


_KIND_NS = "http://v8.1c.ru/8.3/MDClasses"  # Designer XML: элементы без префикса


def _type_tags(kind_dir):
    """Множество допустимых тегов объекта в выгрузке.
    run-59: ПВХ — и одиночный тег ChartOfCharacteristicType, И обёртка
    MetaDataObject → ChartOfCharacteristicTypes (plural), как в Designer."""
    tags = {_TYPE_TAG[kind_dir]}
    if kind_dir == "ChartsOfCharacteristicTypes":
        tags.add("ChartOfCharacteristicTypes")  # обёртка Designer (plural)
    return tags


def _config_lookup(config_paths, obj, attr):
    """Объект/реквизит в выгрузках → {'source': …, 'attr': bool} | None.
    config_paths: [(label, path), …] — расширение ПЕРВЫМ (E-50).
    Заимствованный объект расширения (ObjectBelonging=Adopted) XML
    реквизитов НЕ содержит — они в основной конфигурации: реквизит
    проверяется по ВСЕМ выгрузкам, где объект найден."""
    from lxml import etree
    kind_ru, name = obj.split(".", 1)
    kind_dir = _KIND_DIRS.get(kind_ru.lower())
    if kind_dir is None:
        return None
    tags = _type_tags(kind_dir)
    target = name.lower()
    seen_source, has_attr = None, None
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
        if seen_source is None:
            seen_source = label
        if attr is None:
            return {"source": seen_source, "attr": True}
        if has_attr:
            continue
        # Designer XML: реквизиты — ChildObjects/Attribute (+ измерения,
        # ресурсы); заимствованный объект расширения ChildObjects пуст.
        # Все элементы в MDClasses-namespace — find только с {ns}-префиксом.
        P = f"{{{_KIND_NS}}}"
        has_attr = any(
            etree.QName(a).localname in ("Attribute", "Dimension", "Resource")
            and (a.findtext(f"{P}Properties/{P}Name") or "").lower() == attr.lower()
            for cont in obj_el if etree.QName(cont).localname == "ChildObjects"
            for a in cont)
    if seen_source is None:
        return None
    return {"source": seen_source, "attr": bool(has_attr)}


def _export_tabular_sections(config_paths):
    """Множество имён табличных частей (Name + Synonym) из выгрузок.
    run-59 G19: имя табличной части в черновике MUST совпадать с Name или
    Synonym TabularSection в выгрузке (документы и т.п.)."""
    from lxml import etree
    names = set()
    for label, base in config_paths or []:
        for kind_dir, tag in _TYPE_TAG.items():
            d = os.path.join(base, kind_dir)
            if not os.path.isdir(d):
                continue
            for f in glob.glob(os.path.join(d, "*.xml")):
                try:
                    tree = etree.parse(f)
                except etree.XMLSyntaxError:
                    continue
                obj_el = next((c for c in tree.getroot()
                               if etree.QName(c).localname in _type_tags(kind_dir)),
                              None)
                if obj_el is None:
                    continue
                P = f"{{{_KIND_NS}}}"
                for cont in obj_el:
                    if etree.QName(cont).localname != "ChildObjects":
                        continue
                    for a in cont:
                        if etree.QName(a).localname != "TabularSection":
                            continue
                        props = a.find(f"{P}Properties")
                        if props is None:
                            continue
                        nm = (props.findtext(f"{P}Name") or "").strip()
                        syn_el = props.find(f"{P}Synonym")
                        syn = ""
                        if syn_el is not None:
                            syn = (syn_el.findtext(f"{{http://www.1c.ru/v8}}item/"
                                                   f"{{http://www.1c.ru/v8}}content")
                                   or "").strip()
                        if nm:
                            names.add(nm.lower())
                        if syn:
                            names.add(syn.lower())
    return names


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("draft")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--description", default="", help="текст описания доработки (для G1)")
    ap.add_argument("--config", action="append", default=[],
                    help="выгрузка 1С «метка=путь» (метка: ext|main); "
                         "расширение — ПЕРВЫМ. Тех-ТЗ: обязательно.")
    ap.add_argument("--map", default=None,
                    help="obj-map.json: G6 пропускает объекты со статусом «новый»")
    ap.add_argument("--figs", default=None,
                    help="JSON {номер: описание} рисунков (как --figs "
                         "render_md): подпись «Рисунок - N» ставится "
                         "конвейером при рендере, в черновике её быть НЕ "
                         "должно — G4 не требует её в draft (E-57)")
    ap.add_argument("--progress", default=None,
                    help="прогресс.json — записать вердикт шага 7 при чистом линте")
    args = ap.parse_args()
    config_paths = []
    for c in args.config:
        label, _, path = c.partition("=")
        config_paths.append((label or "main", path))
    figs = None
    if args.figs and os.path.exists(args.figs):
        import json as _json
        with open(args.figs, encoding="utf-8") as fh:
            figs = _json.load(fh)
    problems = lint(args.draft, args.spec, args.description,
                    config_paths=config_paths, figs=figs, map_path=args.map,
                    progress=args.progress)
    if problems:
        print(f"[ЛИНТ] нарушений: {len(problems)}")
        for p in problems:
            print(p)
        print("[ИТОГ] править черновик → перезапустить lint → только потом render_md.")
    else:
        print("[ЛИНТ] нарушений нет → render_md разрешён.")


if __name__ == "__main__":
    main()
