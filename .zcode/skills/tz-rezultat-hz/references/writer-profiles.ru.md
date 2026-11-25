# Element Writer Profiles

> Status: draft · Type: document · Version 1.1.0 · Updated 2026-11-16
> A miniprofile: the writer profile of ONE catalog text element within ONE document type; generated on the fly from samples.

## 1. Definition
1.1. A miniprofile covers ONE text element (`text_element: true` in document-model.ru.yaml) of ONE document type; business-ТЗ and tech-ТЗ element patterns differ.
1.2. Universal: built from any user samples per document-model.ru.md §7–8; no binding to a specific sample set.

## 2. Schema (fixed fields)
2.1. `element_id` — id from document-model.ru.yaml; `doc_type` — type label from classification; `samples` — samples used.
2.2. `canonical_patterns` — canonical wordings/line templates, each with evidence «в N из M образцов»; `lexicon` — characteristic vocabulary; `syntax` — sentence/block structure; `variability` — what changes vs what is invariant; `rules` — 3–7 writing rules.

## 3. Generation and use
3.1. detection over the type's samples → element fragments from all → repetition analysis (majority decides, evidence in pairs, never invent) → miniprofile → write with it.
3.2. New samples → miniprofiles rebuilt (a profile is a function of current samples); a rebuild creates a NEW version, the old one is kept (§3.5).
3.3. Storage: `projects/<project-name>/profiles/` (project folder — the profile binds to that project's samples, never mix foreign ones); no persistent profile → `temp/` for the run's duration; not committed without an explicit user decision.
3.4. Order: Style Card `bundle/tz-1c-style/` (document tone, lexicon) + the element miniprofile → text. Document typing — Process in `references/process.md`.
3.5. Versioning and reuse:
- File name: `<doc_type>/<element_id>/v<N>.md` (N = 1, 2, 3…); each rebuild increments N; previous versions are NEVER deleted or overwritten.
- The model uses the LATEST version (max N) of each miniprofile by default unless the user says otherwise (names a version or asks for a rebuild).
- Rebuild on new samples — only on user request or clear profile/sample mismatch; new samples existing does not by itself demand a rebuild.
- A version header records: `samples`, rebuild date, what changed vs the previous version.

## 4. Tech-ТЗ (doc_type = «техническое ТЗ» in spec.meta)
4.1. A separate miniprofile set (schema per §2); the `tz-1c-style` Style Card is NOT the tone base here: tech-ТЗ is a technical register.
4.2. Canonical patterns (per tech samples, evidence «в N из M»):
- a requisite — a group of pairs «имя – X», «синоним – Y», «тип – ссылка на …», «размещение – вкладка …», «заполнение – при нажатии …» (list items, the MAIN tech-ТЗ marker);
- conditions — «Если <точечный путь> = Истина тогда …», «если … иначе …»; conditions are LEVELS by nesting (level 1 — primary checks, level 2 — branches, level 3 — critical) with a VISIBLE level marker (numbered sub-subsections 4.3.1/4.3.2 or another marker); flat «всё на одном уровне» is FORBIDDEN (oneshots O8, USER-правило, аналитик, прогон -59);
- algorithms — as Дано/Когда/Тогда scenarios (Russian Gherkin, Vanessa Automation dialect; method — tech-tz-map.ru.md §5), one scenario = one operation, step values as point paths and types from the object map; narrative algorithm description («при нажатии … происходит …») is NOT a tech-ТЗ pattern;
- form actions — «Добавить команду/колонку/параметр …», «Изменить логику формирования …» with a point path (Обработка.X.Форма.Y — WITHOUT reformatting);
- report changes — column/row/parameter composition by groups;
- «X не предполагается» — the legal empty section form («Добавление новых объектов системы не предполагается.»);
- roles — as TEXT (the «Описание новых ролей» section), not a rights table; the section contains ONLY new roles or changes to existing ones (extension/restriction) — standard roles are NOT described there (business-ТЗ subject);
- antil dictionary — a MANDATORY section of the miniprofile skeleton (gen_miniprofiles): «по табличной части X» → «по данным табличной части X» (bare «по табличной части» is an antil); the model applies it when writing tech-ТЗ text.
4.3. TYPES — as in the configurator; the canon list and the ban on everyday retellings — oneshots-tech.ru.md O2. Object/requisite/type names — ONLY from the configuration (Unica plugin), inventing forbidden; the check mechanics — SKILL.md Step 7 п.6 (lint G6 `--config`).
4.4. The 1С link for tech scope is MANDATORY — a blocker (canon and wording: question-packs.ru.md §6).
4.5. Screenshots and «Рисунок - N» captions — as in business-ТЗ; the caption follows the action description.
4.5a. DECLARATIVE FORM (2026-11-19 lesson): tech-ТЗ is a task to the developer («должен быть добавлен», «должен быть виден»), not a behavior report («Система сбрасывает…» — lint G14). Events follow the user oneshot O5u (Условие/Событие/Алгоритм/Результат); Дано/Когда/Тогда in the final text is forbidden (G13); event headings are the essence in words, handler identifiers go into the body (G15).
4.5b. USER RULES: standing wishes for ALL ТЗ live in the manifest (meta.user_rules) and the miniprofiles' «ПРАВИЛА ПОЛЬЗОВАТЕЛЯ» section; the model applies them TOGETHER WITH samples, and user oneshots (profiles/oneshots/user-<N>.md) take PRIORITY over sample families of their topic.
4.6. Oneshots — hard tech-ТЗ line patterns: the O1–O10 family list, application rule, and catalog versioning — references/oneshots-tech.ru.md (the canon); the model derives them into miniprofiles (the skeleton's «ВАНШОТЫ» section) and writes text only with oneshots of matching families.
