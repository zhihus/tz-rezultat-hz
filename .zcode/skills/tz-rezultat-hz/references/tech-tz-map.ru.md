# Object Map — the tech-ТЗ Method

> Status: draft · Type: document · Version 1.0.0 · Updated 2026-11-16
> A machine-checkable artifact between the change description and the tech-ТЗ text: the model assembles a backend/frontend map (DB objects, forms, algorithms, roles), a script gate checks it against the config export and a subset of 1С standards, and only then is the draft written FROM THE MAP.

## 1. Why (root of defects)
Text written straight from the description copies the business-ТЗ structure: algorithms as narrative, approximate types, source order instead of dependency order. The map removes this: the model first assembles the FULL list of affected objects with their EXACT properties (names/synonyms/types — ONLY from the configuration via Unica or export), the gate filters out inventions, then draft = map in dependency order + writer profile §4.

## 2. The map (obj-map.json, schema references/obj-map.schema.json)
A weak model only fills flat lists:

```json
{
  "doc_code": "ФР.000.00.00.0-62",
  "objects": [
    {"id": "рткСостояниеМесяцаРаспределенияВыработки",
     "kind": "РегистрСведений", "status": "новый",
     "synonym": "Состояние месяца распределения выработки",
     "attrs": [{"name": "Месяц", "synonym": "Месяц",
                "type": "Дата (состав даты — «Дата»)"}]}
  ],
  "forms": [
    {"owner": "Обработка.рткАРМРаспределениеВыработкиПоОперациям",
     "name": "Форма", "status": "доработка",
     "elements": ["поле «Период»", "кнопка «Рассчитать данные»"],
     "new_elements": ["гиперссылка «Открыть месяц для корректировки»"]}
  ],
  "backend": [
    {"trigger": "форма", "target": "Обработка.рткАРМРаспределениеВыработкиПоОперациям",
     "what": "фиксация выполнения операции в регистре",
     "scenario": ["Дано: форма АРМ с выбранным месяцем",
                  "Когда пользователь нажал кнопку «Рассчитать данные»",
                  "Тогда в регистре «Состояние месяца распределения выработки» создаётся запись с РасчетВыполнен = Истина",
                  "И кнопки «Рассчитать данные» и «Распределить по операциям» недоступны"]}
  ],
  "roles": ["Использование обработки рабочий стол производства (РТК)"],
  "decisions": [
    {"question": "имя нового регистра", "chosen": "рткСостояниеМесяцаРаспределенияВыработки",
     "alternative": "рткСостояниеРаспределения",
     "reason": "имя отражает предмет (состояние месяца), префикс ртк — по стандарту именования расширения"}
  ]
}
```

Rules:
- **types — as in the configurator**: «Дата (состав даты — „Дата“)», «Булево», «СправочникСсылка.X» — qualifiers in brackets; NEVER «дата-месяц», NEVER «флажок».
- **status**: «новый» | «доработка» | «существующий» (engaged unchanged); for forms — «новая» | «доработка» | «существующая».
- **NEW OBJECT IN REFERENCES — WITHOUT KIND PREFIX** (Б8, 2026-11-21): in structured fields (forms.owner, backend.target, deps) a new object is referenced bare-id («рткНовыйРегистр»), not «РегистрСведений.рткНовыйРегистр» — a new object has no kind yet; in DIFF TEXT a new object is also mentioned by name (G6/G9 pass new objects with or without a prefix).
- **backend triggers** (not everything is form-bound): «форма» | «расписание» | «проведение» | «событие»; for «расписание» — periodicity in `what`.
- **backend `what` — a short noun phrase** (≤12 words): no algorithm retelling, no conditions; check_map [G20] FAILs when `what` is longer than 12 words or starts with «если/когда/при…» — rephrase as a noun phrase (e.g. «Проведение документа Заказ», not «Если сумма превышает лимит, провести…»).
- **decisions — ADR in miniature** (Nygard): every design decision (new object name, existing-object choice, register structure) — question, chosen, rejected alternative, reason. A decision without an alternative is a red flag: the model is inventing, not choosing; unknown → ask the user.
- Mutual references are described ONCE — at the point of creation; afterwards — the point metadata path.

## 3. Map gate — scripts/check_map.py

`python.exe scripts/check_map.py obj-map.json --spec spec.json --config ext=<cfe> --config main=<cf> [--prefix ртк]`

Checks (G7…G10 — one series with the draft lint):
- **G7 v8std names**: a new/modified object's name is a 1С identifier (no spaces, `[А-Яа-яёЁA-Za-z0-9_]+`); with `--prefix` — starts with the extension prefix (extension object naming standard); synonym mandatory and human (≠ name).
- **G8 existing vs export**: every object/form with status «доработка»/«существующий» is found in cf/cfe (same logic as lint G6); «новый» — the reverse, must NOT exist (otherwise it is a modification).
- **G9 dependencies**: metadata paths used in scenarios exist; the «object → object» graph is acyclic; a «новый» object does not reference anything undescribed.
- **G10 completeness vs spec**: document code matches; map roles are in spec.roles or declared as new in decisions.

G8/G9 reuse the lint's `_config_lookup` — one source of truth over the export. [FAIL] → the model fixes the map (or asks the user) → re-run. NO TEXT until the map PASSes — a hard gate, like the question pack.

## 4. Draft BY PLAN — the skeleton is generated by the pipeline (E-55)
A ТЗ reads top-down: an element cannot be described before it exists. Structural decisions belong to the SCRIPT, not the model (tech-3 run lesson: a small model takes the spec H1 list as the authoritative order). After map PASS — ONE call:

`python.exe scripts/plan_sections.py --map obj-map.json --spec spec.json --out <version folder>`

The script: spec sets the SET of sections, the plan ORDERS it by dependencies («dependency before dependent»): source → new objects → new data → forms → business logic → roles → constraints. IMPORTANT (V9 lesson, live run 2026-11-19): the samples' second H1 («Описание бизнес-логики») is a narrative process OVERVIEW in prose; the samples' HEADING ORDER is deceptive; У/С/А/Р scenarios in -10 live in the section «Описание работы алгоритмов…» AFTER the new objects.
From the map it generates subsections (H2 per form, H2 «Событие: …» per backend scenario) and «[ЗАПОЛНИТЬ]» marks. The model fills plan.md bodies with oneshots — NEVER change headings, order, numbering. Output: plan.md (for the model) + plan.json (for final_gate: F4 cross-checks the result against the plan, F10 — «first mention = creation section», F11 — figures).

Plan section ranks:
1. Источник информации для написания ТЗ;
2. Новые объекты системы (данные);
3. Доработки существующих объектов (новые реквизиты/измерения);
4. Формы (new before modified; only what the user sees);
5. Алгоритмы бэкенда (map scenarios; «расписание»/«проведение» triggers — a form is NOT mandatory);
6. Роли и права;
7. Ограничения и риски.

An empty section — «… не предполагается.» (the legal empty form).

### Tech-ТЗ screenshots (E-55, user rule)
Few, only AFFECTED things; source — the map, NOT business-ТЗ (its screenshots show current forms without the new elements). Goal — show the FORM and PLACEMENT of new/changed elements (where the button, where the hyperlink); no need to describe every element by screenshot — the developer knows what an element looks like. ALGORITHM (backend) sections — NO screenshots. Every element from a form's new_elements/changed_elements is shown next to its description: «(Рисунок - N)» in the text + caption «Рисунок - N <what is shown>». Check — F11 of final_gate; tech samples confirm (-10: «Рисунок - Форма АРМ …»).

## 5. Algorithms — Gherkin in the Vanessa Automation dialect
Map and draft scenarios — Russian Gherkin («Дано / Когда / Тогда / И») — the same format as Vanessa Automation features: a ТЗ scenario becomes an acceptance-test basis without rewriting. Rules:
- one scenario = one operation (button, scheduled job, posting);
- steps start with a perfective verb («нажал», «создаётся»);
- concrete values — point paths and types from the map («РасчетВыполнен = Истина»), not words like «флажок установлен»;
- branching — separate scenarios or a «Тогда если … иначе …» step per writer-profiles §4.2.

## 6. 1С standards at the ТЗ stage (its.1c.ru/v8std, subset)
Checked before code — on the map and in the lint; the rest (module structure, НСтр, etc.) is the development stage, handled by BSL Language Server, not the ТЗ:
- configuration object names (identifier, extension prefix) — G7;
- synonyms (human, in quotes in text) — G7 + profile §4;
- roles — real metadata, never invented — G10;
- metadata paths — exact, per export — G8/G9 (+ G6 in the lint).

## 7. Boundaries
- The map does NOT change the template structure: sections are set by spec (samples).
- On a live run, a NEW object's name/structure and non-trivial decisions → question to the user (pack §5); the map only prepares the question with concrete options (chosen/alternative).
- Unica (meta-info, unica.search/view) — the property source in chat; the cf/cfe export — the source for scripts. Inventing is forbidden everywhere.
