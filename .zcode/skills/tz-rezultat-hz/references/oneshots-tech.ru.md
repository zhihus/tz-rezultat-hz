# Tech-ТЗ Oneshots — hard writer patterns

> Status: draft · Type: document · Version 1.0.0 · Updated 2026-11-16
> A oneshot is a hard line/block pattern the model must follow VERBATIM except for `<slot>` values; shape and order come from samples. After parsing tech samples, the model — while filling miniprofiles (gen_miniprofiles → «ФОРМУЛИРОВКИ» section) — derives for EACH family a oneshot with evidence «в N из M образцов» and writes text ONLY with oneshots (off-oneshot text = plain narrative sentences without markup). Slots are exactly those listed; adding own fields is forbidden; missing data → ask the user. All pattern text and examples below are RUSSIAN generated-document content — keep verbatim.

## O1. Configuration object creation
`Добавить новый <вид>: / Имя – <имя>, синоним – <синоним>[, тип – <свойство>]`
- Examples: «Добавить новую обработку:» + «Имя – рткРаспределениеТрудозатратПоОперациям, синоним – Распределение трудозатрат по операциям» (47); «Добавить новый регистр сведений:» + «Имя – …, синоним – …, тип – периодический.» (47); «Добавить новое регламентное задание:» (47); «Добавить новый отчет.» (47).
- Slots strictly in order «Имя, синоним, [тип/расположение/группа]»; non-default properties continue comma-separated on the same line (67-4: «расположение – подсистема «Склад и доставка», группа «Отчеты»»).

## O2. Requisite / dimension / resource / form element
TWO sample forms exist; a third (triad on one line) does NOT:
- AS LIST SLOTS (the main tech-ТЗ marker, §4.2): a group heading («Реквизиты регистра:», «Измерения регистра:», «Ресурсы регистра:»), then per requisite a slot group, each slot its own list item, comma inside, period at the end: «имя – РабочийЦентр,» / «синоним – Рабочий центр,» / «тип – ссылка на справочник «Рабочие центры»,» / «размещение - вкладка …» / «заполнение – …» (47).
- AS A «Имя | Синоним | Тип» TABLE (no caption, sample-facts §1.7): Дата|Дата|Дата; Количество|Количество|Число (5.3) (10) — a table variation, into spec.variations.tables at ≥2 samples.
- A SINGLE requisite in description text — an inline pair: «Имя – СкладПолучательДляПеремещения, синоним - Склад получатель, тип – ссылка на справочник «Склады», описание – …» (-15).
- TYPE — configurator canon («ссылка на справочник «X»», «Булево», «Дата (состав даты — „Месяц“)», «Число (5.3)», «Строка (2000)»); everyday retellings («флажок», «дата-месяц») forbidden; a month requisite's date composition is «„Месяц“», NOT «„Дата“» (tech-2 run lesson).
- Mechanics: lint G11 catches the triad in a line; render takes variation-table widths from spec.variations.tables.

## O3. Button / form command
`<название кнопки> - <что делает: действие с точечными путями>`
- Example: «Рассчитать данные - запускает расчет …, после выполнении расчета записывает результат расчета в регистр сведений РегистрСведений.рткОтложенноеЗаполнениеПроизводственныхОпераций» (47).
- Command on an existing form: «На форму <путь> добавить команду: имя – <имя>, синоним - <синоним>, действие – <что делает>» (-15).
- A tabular «название⇥действие» record in samples renders as a list; the name is as in the UI, quoted when mentioned in text.

## O4. Object purpose
`<АРМ/объект/регистр> предназначен для <процессная фраза>.`
- Examples: «АРМ предназначен для распределения времени работы сотрудников, внесенного в документ «Ежедневный табель (Производство)», по документам ПроизводственнаяОперация2_2» (47); «Регистр предназначен для хранения информации по …» (47).
- One sentence per object, right after creation (O1) — before requisites.

## Two oneshot tiers (priority rule, 2026-11-19 lesson)
- Tier 1 — SAMPLE families O1–O12: source — samples, evidence «в N из M» (O11/O12 — partially, «в образцах встречается частично»; the missing part is set by a user-ваншот).
- Tier 2 — USER oneshots `profiles/oneshots/user-<N>.md`: source — user rules/examples absent from samples or overriding them; versioned as v<N>, never deleted.
- PRIORITY: a user oneshot OVERRIDES the sample oneshot in its topic; the sample one applies only where no user one is set. Without this rule the model always picks «подтверждено образцами» — and the user mechanism is dead.

## O5u. Event — user format (TIER 2, overrides O5)
`5.K. Событие: <суть ситуации кратко, словами> / Условие: <контекст> / Событие: <действие с точечным путём> / Алгоритм: / • <шаг> / Результат: <должен быть…>`
- Дано/Когда/Тогда is the model's WORKING form (map, scenarios); FORBIDDEN in the final ТЗ (lint G13). Transfer: Дано → «Условие», Когда → «Событие», Тогда → «Результат»; «И» steps → «•» bullets in «Алгоритм».
- The event heading is the SITUATION'S ESSENCE in words (sample 10 exemplar: «Сотрудник отнесен к смене и рабочим центрам»), NO bracketed explanations; the handler name («ПериодПриИзменении») goes into the body, not the heading (lint G15).
- Результат — declarative, a task to the developer: «должна быть добавлена», «блокируется»; the reporting form «Система сбрасывает…» — lint G14.
- Tech-ТЗ is written DECLARATIVELY: every sentence is a task to the developer («должен быть добавлен», «должен быть виден»), not a report of finished behavior.
- Trigger «проведение»: the line «Событие: проведение документа <путь>.» states ONLY the trigger fact — all substance (conditions, actions) lives in the «Алгоритм» steps; repeating a condition or algorithm inside «Событие» is FORBIDDEN (USER-правило, аналитик, прогон -59; priority over the O5 letter).

## O5. Event + algorithm
`Событие: <триггер с точечным путём>. / Алгоритм: <шаги>`
- Example: «Событие: нажатие кнопки «Рассчитать данные» на форме Обработка.рткРаспределениеТрудозатратПоОперациям.» + «Алгоритм:» (47).
- Combined with Gherkin: the map trigger «форма/расписание/проведение/событие» → the line «Событие: …» («расписание» → «Событие: регламентное задание <имя> по расписанию <период>.»), then the Дано/Когда/Тогда scenario steps (tech-tz-map.ru.md §5). The event line shape is hard; steps follow profile §4.

## O6. Scheduled job — action and result
`Действие: <что делает> / В случае успеха <результат> / В случае ошибки <результат>`
- Example (47): «Действие: отобрать записи из РегистрСведений.рткОтложенное…, у которых реквизит «Обработано» = «ЛОЖЬ»»; «В случае успешного выполнения обработки … установить … значение = «ИСТИНА»»; «В случае возникновения ошибки … производить заполнение реквизита регистра «Ошибка …»».
- Schedule/manual run — a separate line: «Регламентное задание срабатывает как по расписанию, так и при обращении к команде «X»» (47).

## O7. Report — sources, groupings, columns
- Sources: «Источником данных для отчета являются:» + a list of point paths (47).
- Groupings: «Отчет содержит группировки согласно макету (Рисунок - N): <перечень>.» + «Отчет содержит колонки.» + per column «<название> – содержит <источник>» (47).
- Conditional coloring/filter: «В случае, если <условие по точечному пути>, тогда <действие с цветом/фильтром>» (47); colors — one «<цвет> — если <условие>» per line (-15).

## O8. Conditions — LEVELS by nesting (USER-правило, аналитик, прогон -59; priority over the old O8 letter)
`Если <точечный путь> = <значение> тогда <действие>.` / «В случае, если …, тогда …»
- Conditions are LEVELS by the nesting of the original condition: level 1 — primary checks, level 2 — branches, level 3 — critical. The level MUST be visible to the reader — numbered sub-subsections per sample (47: 4.3.1, 4.3.2, 4.3.3 — «Сотрудник отнесен к смене и рабочим центрам» / «…но не отнесен…» / «Для смены сотрудника нет выполненных операций») or another level marker; flat «всё на одном уровне» is FORBIDDEN.
- BRANCHING (= Да / = Нет) — a pair of adjacent oneshot lines with the same opening (63), each on its own level marker, NOT nested indentation.
- What the old «вложенное если-в-если» ban means: unreadable verbal nesting crammed into ONE line — NOT the numbered hierarchy above. A numbered level (4.3.1 under 4.3) is the CORRECT form, not a violation.
- Boolean values — «Истина»/«Ложь» (in уточняющие quotes — «ЛОЖЬ»/«ИСТИНА» as in the source sample), never «да/нет» in algorithms.

## O9. Formula and parameter
`{<имя параметра>} = <формула из имён параметров и путей>` + term expansion
- Example (47): «{НормативНаЕдГП} = Норматив * Количество в индивидуальной упаковке * Дополнительный коэффициент…» + «Норматив: получать из РегистрСведений.рткНормыТрудозатратПоТипамПродукции.НормаВремени, где: Вид продукции = …».
- Each formula term — a separate line «<имя> – получать из <точечный путь>[, где: <отбор>]»; a `{…}` parameter defines its name at first mention, afterwards only that name.

## O10. Source and description (document header)
`Функциональная модель: «<модель>» / Описание <КОД>: <текст доработки>`
- Example: «Функциональная модель: «01.04_ОПЕРАТИВНЫЙ КОНТУР…»» + «Описание ФР.000.00.00.0-10. Разработать механизм …» (47).
- The naming requirement from sample 47's header: «Все новые наименования объектов, реквизитов, элементов формы, должны быть понятны и логичны исходя из процесса и функций объектов и элементов форм.» — include in the new-objects section when creating new objects.

## O11. Document movements = mapping table
`<документ> → <регистр> → <вид движения> → <источник данных/условие>`
- Document movements are described as a MAPPING TABLE (документ → регистр → вид движения → источник данных/условие), not as narrative sentences.
- Evidence: «в образцах встречается частично (-15, 10); при отсутствии в образцах форма задаётся user-ваншотом» (Tier 2, `profiles/oneshots/user-<N>.md`).

## O12. Role → available command
`При добавлении роли пользователю в интерфейсе становится доступна команда <X>`
- Interface access by role is described as «при добавлении роли пользователю в интерфейсе становится доступна команда X», not as a rights table.
- Evidence: «в образцах встречается частично (-15, 10); при отсутствии в образцах форма задаётся user-ваншотом» (Tier 2, `profiles/oneshots/user-<N>.md`).

## Application rule
1. Filling miniprofiles for tech-ТЗ, the model derives per O1–O12 family a oneshot with evidence «в N из M» OR the note «в образцах не встречается» / «в образцах встречается частично» (then the family is not used in text / its missing part is set by a user-ваншот; shape per profile §4).
2. In the draft, every line of a matching family follows its oneshot; slots are point paths from the object map (check_map PASS is a precondition).
3. Lint G6 cross-checks paths; any line-shape deviation (slot order, extra fields) — fix the draft before render.

## Storage and versioning (E-54, user rule)
- Oneshots are a PERMANENT versioned project artifact: `projects/<name>/profiles/oneshots/v<N>.md` (version scheme as miniprofiles, writer-profiles §3.5). NEVER deleted: a new version is created alongside, previous ones stay.
- Several VARIANTS per family are normal and valuable: if samples style the same entity differently (requisites as list slots in 47 AND as a «Имя|Синоним|Тип» table in 10), ALL variants enter the catalog with their «в N из M». Seeing several variants of one family, the model derives the "on average correct" shape and does not break on variation — that is the catalog's purpose.
- Correction only on SUBSTANTIAL changes (new samples with a different shape, a user decision): create v<N+1> with a header note of what changed and why; the old version is never rewritten.
- The version-N catalog feeds miniprofile generation and final_gate conformance; miniprofile and SKILL links point to the current (max N) version.
