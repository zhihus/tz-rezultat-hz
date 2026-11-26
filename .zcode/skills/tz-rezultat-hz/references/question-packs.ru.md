# Verbatim Question Packs (tz-rezultat-hz)

Source of truth for question wording. Re-read the relevant section before EVERY pack. Changing wording, order, or options is FORBIDDEN (defects E-03, E-21, E-24, E-26, E-38). Question text and options below are RUSSIAN user-facing content — never translate or paraphrase.

## ZCode representation

Before every ZCode call, follow `references/zcode-harness.ru.md`. Each item
below becomes one `AskUserQuestion` question. Preserve its wording and stated
options. Each call contains at most four questions; larger packs are split
into consecutive calls in the same order, without intervening analysis or work.
Free-text items use the designated text-entry option and the UI's automatic
free-text/Other input; do not omit the required 2–4 options or invent defaults.


ONE CONTENT INTERVIEW (Rule 4 of SKILL.md): model→user questions are §1 (Step 1) and §2 (Step 2) only. After Step 2 — zero questions; §3 and §3а are reactions to the user's own actions, not model initiative.

## §1. Step 1 — preflight pack (one call, after the environment report)

- Question 1: «Пришлите описание доработки, по которой нужно ТЗ» — options «Введу текстом» (text in the input field) / «Положу файл в папку с образцами» — the option description and the question state the CONCRETE path to the samples folder (then «Положил?»: «Готово» — read the file from the samples folder / «Отмена»).

CONFIGURATION — NOT A QUESTION (2026-11-20 decision): a config copy always sits in the work-folder root (cf/cfe or Designer export) — the model finds it ITSELF with one call `find_config.py --path <рабочая> --work <рабочая>`; asking the user for the config location is FORBIDDEN.

The description is input #1; no description → no work. The link is needed at fill time — find it early to avoid breaking work with questions later.

## §2. Step 2 — single dialog: grilling and the megapack

Order: п.0 (grilling) → grilling rounds → structural questions (п.1–3). One tool call = one round; п.1–3 questions may be combined into ONE call (each with its own field — Rule 3).

- п.0: «Провести прожарку?» — «Да, задавай вопросы» (recommended) / «Пропустить». «Да» → self-grilling via the grilling skill: wording is FREE (the only non-verbatim questions) — contradictions, ambiguities, missed cases, scope boundaries; rounds until the pool is exhausted. «Пропустить» → straight to structural questions; unclear later — «уточнить по конфигурации» marks in the ТЗ, the user deals with the consequences. grilling UNAVAILABLE (preflight reports it — `[WARN]`: the full component set was declined, or the set is unknown/legacy; `[FAIL]`: the set is declared FULL but the component is missing or damaged → restore the full set FIRST, never work on a broken full set) → do NOT ask п.0; tell the user the «прожарка» step is unavailable and ANALYTICS IS INCOMPLETE (this is NOT normal work), then go straight to structural questions (п.1–3).
- п.1 (type): «Какой документ нужно подготовить?»
  - «Бизнес-ТЗ» — a filled ТЗ from the change description (samples in references/business/).
  - «Техническое-ТЗ» — a filled tech-ТЗ from the change description (samples in references/tech/).
  - «Шаблон бизнес-ТЗ» — an empty dense template, no filling.
  - «Шаблон технического-ТЗ» — an empty dense template, no filling.
  A separate element (title page, approval sheet, etc.) — NO option: the user types it as TEXT into the input field (Other); the model processes it as «one element» per the catalog (`requires` rule — protocol §6). If type and scope follow unambiguously from request+description — do NOT ask, state the choice in the first message.
- п.2 (ПДн): «Копировать персональные данные (ФИО, названия организаций, телефоны, email, логотипы) из образцов в новый документ?» — «Да, копировать из образца» (recommended) / «Нет, заменить вымышленными примерами». «Нет» → stubs with fictional examples (pii=sanitize); «Да» → examples are NOT inserted: known values are substituted immediately, unknown → placeholder (pii=keep). NOT asked for tech-ТЗ: no signature block, no personal data copied.
- п.2а: «Начинаю?» — «Да» / «Нет».
- п.2б (constraints): «Какие ограничения и допущения, согласованные с заказчиком, зафиксировать в ТЗ?» — «Ограничения отсутствуют» (recommended) / «Введу текстом». The sections «Ограничения и допущения» and «Риски» are filled ONLY by this answer: the model never derives constraints from description, map, or algorithms; no answer → «Ограничения отсутствуют».
- п.3 (tech-ТЗ only): requisites question for one unsupported by samples/scan: «Какой тип у реквизита «X» объекта «Y»?» — «Смотрю в конфигурации сам (Юник)» (recommended) / «Укажу тип текстом» / «Пропустить» (→ requisite placeholder, NEVER invented).

- п.4 (КОД нового ТЗ, D10/A7 — asked ONLY if the КОД is not set by the project manifest or the user): «Какой КОД у нового ТЗ?» — free text input (pattern «ФР.<ПРЕФИКС>.NN.NN.N-NN» from samples; «финал» never enters the name — the user adds it manually).

## §3. Step 3 — references/ question (verbatim)

Not found → question: «Я не нашёл папку с образцами. Вы хотите, чтобы я создал папку references/ в рабочей папке?»
- «Да, создать папку references/» — explanation: «Вам будет нужно положить в эту папку образцы документов в формате DOCX». Create the folder and IMMEDIATELY ask: «Положите образцы DOCX в references/» → «Всё готово, образцы в папке» (continue) / «Отмена» (stop).
- «Нет, создавать папку не нужно» — explanation: «Вы самостоятельно создаёте папку и кладёте в неё образцы документов в формате DOCX».
Never create the folder without an answer; another folder — only the one the user names.

## §3а. Step 3 — new ТЗ (per the «НОВОЕ ТЗ» line from init_project)

- Question: «Я обнаружил, что такого ТЗ ещё нет в нашей библиотеке (тз/<КОД>). Это новое ТЗ?» — «Да, новое» → create тз/<КОД>/, write the КОД into the manifest; «Нет» → «Такое ТЗ уже было?» — show the тз/ folder list and ask which one to continue with.

## §4. Step 2 — content transfer options (attached to every question expecting data)

- «Введу текстом» → input-field text = the section's data.
- «Положу файл в папку с образцами» → the question states the CONCRETE samples path (the ONLY place for user files — never ask for paths), then «Положил?»: «Готово» (read) / «Отмена».
- «Пропустить» → a placeholder instead of the section («[ИСТОЧНИКИ ДЛЯ РАЗРАБОТКИ — заполните]»), hallucination forbidden.

Homemade Recommended options are FORBIDDEN: recommended — verbatim from samples only; an object name from the change description is NOT a source. Gap example: «В образцах таблица прав с ролями А, Б. Для новой доработки какие роли добавить?» — answer text/file → roles into the rights table and testing scenarios; «Пропустить» → sample roles only, placeholders for new ones.

## §5. Step 2, tech-ТЗ (doc_type = «техническое ТЗ» in spec.meta)

Tech-ТЗ is NOT written without a config export (blocker, E-50): no link → Step 2 warns, Step 6 stops with a report, never «by description».

Metadata via Unica only (meta-info, unica.search/view, cf + cfe — changes usually live in the extension); draft check — lint G6 `--config`.

## §6. Step 2 — confirmation gate before writing the ТЗ (verbatim)

After the corrected requirements description (the analyst-methodology research phase): «Описание скорректировано — переходим к написанию ТЗ?» — «Да, переходи к ТЗ» (→ Steps 3–8, zero questions from there) / «Нет, сначала правки» (→ the model clarifies the description; on new dependencies — targeted add-on research via Unica; loop back to the corrected description and repeat §6). Writing the ТЗ before «Да, переходи к ТЗ» is FORBIDDEN.
