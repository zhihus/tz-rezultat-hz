# Per-Element Parsing Protocol

> Status: approved · Type: protocol · Version 1.0.0 · Updated 2026-11-15
> How to add extraction/parsing of any `document-model.ru.yaml` catalog element — including one absent from current samples. Audience: the model extending the pipeline. Principle: the parser binds to the CATALOG (universal markers), never to specific samples.

## 1. Element classes (determine first)
1.1. Class A — page/document-level (header, footer, page-number, page-geometry, first-page-diff, toc, title-page). Already handled by extract mechanics into spec fields; do NOT write a new parser — only extraction in `apply_elements` (extract_spec.py): toggle the spec field.
1.2. Class B — section-level (introduction, abbreviations, terms, normative references, sources, conclusion, appendices, change/approval sheets, lists). Segmentation by heading: templates — «...» quotes in the catalog's `detection` field; matching — normalized substring entry in the section heading; the section tree is pruned to matched nodes + ancestors. No section-name code — catalog only.
1.3. Class C — in-text (headings, lists, tables, figures, captions, notes, breaks…). Live inside sections; specimen mode: extract fragments containing the element from samples by `detection` markers (style, numPr, row structure), assemble a template fragment with stubs. Result fields — from catalog `attributes`.

## 2. Work order (any model)
2.1. Already in spec? (class A) → extraction only, no parsing.
2.2. Class B → extend `detection` with heading templates (if missing), verify matching on samples; add nothing to code.
2.3. Class C → `detection` markers in machine-readable form (style name, numPr/ilvl, row regex, position relative to a figure); implementation — in extract_spec as a specimen strategy; `attributes` sets the result fields.
2.4. Element ABSENT from samples → write markers from standards (ГОСТ Р 7.0.97-2016, ГОСТ 7.32-2017, ГОСТ 2.104/2.301, DITA 1.3 bookmap) with the note «источник: стандарт, образцами не подтверждено»; when a sample appears — verify and confirm. Never derive behavior from one dubious example.
2.5. The catalog `parser` field is the source of the method (what and how to extract); code is implementation only. They diverge → fix the catalog, not the code.
2.6. Completion — two checks: the verify_template gate (element mode reads spec.meta.elements); visual render comparison against sample/standard.

## 3. Extraction mechanics (--elements)
3.1. `tz_tool.py run --folder <folder> --elements id1,id2 [--pii sanitize|keep]` — ids from the catalog.
3.2. Unknown id → error. Section elements not found in samples → WARNING (empty template, not silent success).
3.3. spec.meta records elements/pii_mode/catalog — the gate and journal read the mode from there.
3.4. title-page not requested → title_block is cut (scope = exactly what was requested); page-geometry is always kept (a page property, not content).

## 4. Safety rules
4.1. Any change in the header/footer/title branch → a FULL verification run of ALL elements via the verify_template gate (E-11 lesson: spot checks missed an early return).
4.2. Every fix — an entry in an error journal (symptom → cause → fix → check → regression risks).
4.3. ПДн: new elements inherit --pii (phones/email/names/organizations/logos — sanitize by default).
4.4. format-agent — the rule lives in SKILL.md Step 1 (copies ITSELF, no question, E-13 lesson); not duplicated here.
4.5. Copies/mirrors — mirror the STRUCTURE: cp of changed files does not carry new/moved folders (the second install was left without bundle/, E-63). After sync — `diff -rq` (empty = in sync).
4.6. One script canon — the skill's `scripts/`.
4.7. A placeholder/token shape change → update ALL consumers in the same commit: build/render, verify_template, judge briefing.
4.8. A rule written for a particular sample layout — verify on real column/heading layouts (G3 looked at the first column, roles in the second; an unknown role passed silently).
4.9. Heading/name matching — by semantic substring, not exact equality: users abbreviate («Источники для разработки» → «Источники»). Check false positives (the tech skeleton «Источник информации…» must not match).
4.10. Verify every mechanism on EDGE cases: one sample, empty densities, degenerate spec — class E-59 is invisible on two+ samples.
4.11. Word with samples open blocks COM rendering (~$ lock files): close before runs; a hang is cured by taskkill WINWORD + re-run.
4.12. A CONTRADICTION BETWEEN TWO PIPELINE SCRIPTS = A DEFECT SIGNAL, not a «false positive» (E-66/V9 lesson: plan and final_gate encoded different section orders — the contradiction had to be resolved, not the check explained). Derive order from CONTENT across all samples, not from heading order.
4.13. Body font — from ACTUAL body-paragraph runs, not docDefaults (E-60/ЧЭАЗ lesson: the sample's docDefaults differ; vote over explicit rFonts/sz in body runs, threshold ≥5 runs). Know edge cases (one sample, empty densities — E-59) upfront; test them deliberately.

## 5. Universality (the main rule)
5.1. The no-sample-binding canon — SKILL.md Rule 1; protocol addition: generalized regexes — any letter code prefix, not «ФР».
5.2. Catalog field `confirmed`: `samples` — detection templates confirmed by real samples; absent/`standard` — written from ГОСТ/DITA, unconfirmed (§2.4).
5.3. Documented limitation: the caption block targets a two-party title (ЗАКАЗЧИК/ИСПОЛНИТЕЛЬ); a title with ЕСКД frame/stamp is separate catalog elements (eskd-frame, stamp), never in sig_rows.
5.4. Organizations are recognized in Russian forms (ООО/АО/ПАО/ЗАО/ОАО/ИП) — project scope (1С ТЗ, Russian-language documents).

## 6. Element dependencies (requires)
6.1. Catalog elements may have `requires: [id, …]` — other elements without which this one is empty/meaningless (e.g. `toc` requires `numbered-heading` — the TOC is generated from headings).
6.2. Execution rule: an element with dependencies is requested → scope AUTOMATICALLY extends to the minimal dependency skeleton; this is NOT initiative (a dependency is catalog fact) and NOT a question. Report the extension explicitly in the first message («Оглавление требует заголовков — добавил каркас разделов»).
6.3. Forbidden: silent extension; refusal («order the full template»); asking about an obvious dependency. A disputed dependency (not in the catalog) → ask the user — a scope question, skill Step 2.
6.4. A «property» element (selectable: false, e.g. heading styles) pulls no content: «just a heading» is self-sufficient.

## 7. Weak-model contract
Canon — SKILL.md Rule 2 (3B–27B, model-agnostic; flat text + Да/Нет/Пропустить; mechanics set by the pipeline; adaptation forbidden). Not duplicated here.
