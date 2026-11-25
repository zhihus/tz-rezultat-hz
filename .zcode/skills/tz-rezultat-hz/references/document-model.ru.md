# Document Model

> Status: approved · Type: document · Version 1.2.1 · Updated 2026-11-15
> Technical-document model: levels document → page → formatting; element detection, parsing, sample-analysis methodology. (Detection DATA lives in `document-model.ru.yaml` — Russian, machine-read.)

## 1. Definition
1.1. Document — information on a carrier with requisites identifying it (ГОСТ Р 7.0.8-2013, ISO 15489). Three layers: requisites (author, date, number, kind), content, formatting.
1.2. The main element is the requisites (they distinguish a document from "just text"); the main requisite is the signature (unsigned = draft).

## 2. Document level
2.1. Structural elements: title page (organization, kind, code, version, approval marks, city/year); performers sheet; abstract; TOC (generated from headings, mandatory >10 pages — ГОСТ 7.32); figure/table lists (from captions); terms & definitions; abbreviations (at the front); normative references; introduction; body (in a ТЗ: requirements, «если—тогда», figures); conclusion; sources (at the end); appendices («ПРИЛОЖЕНИЕ А», double numbering — sequential + А-1); change-registration sheet; approval sheet («разработал — проверил — согласовал — утвердил»); colophon.
2.2. Cross-cutting layers: metadata (version, status, revision date, language); cross-references («см. п. 4.2», «(Рисунок - 3)»); hierarchical numbering (1 → 1.1 → 1.1.1; codes like ФР.000.00.00.0-00); scope and audience (ISO 82079-1).
2.3. Standards: ГОСТ 7.32-2017 (report element list); DITA bookmap — frontmatter → body → backmatter, typed pages, generated lists; ISO/IEC/IEEE 82079-1; Diátaxis (body typing).

## 3. Page level
3.1. A page = composition of formatting, semantics (type), content. Types: regular (container + body); title (no number, no figures, ~20 lines); TOC («text … number», generated); character pages (change/approval sheets — fixed tables, filled by lifecycle); appendices (double numbering); mandatory blanks (last signature sheet).
3.2. Parsing by type: title — line by line in expected order; TOC — «heading → number» pairs; abbreviations — at the front, «abbreviation — expansion» pairs; sources — at the end, numbered entries. Detection rule: page type → expected structure → unambiguous identification.

## 4. Formatting level
4.1. Text: paragraph, spacing, alignment, hyphenation, non-breaking spaces. Font: family, size, bold/italic/underline, caps, color; styles fix the set.
4.2. Headings: levels 1–4+, numbering 1 → 1.1 → 1.1.1. Lists: bulleted, numbered, multilevel, «term — expansion».
4.3. Tables: header, borders, row striping, cell merge, «Таблица 3 — …» above the table. Graphics: figure in the flow break, caption «Рисунок 5 — …» below, screenshot frame, numbering.
4.4. Formulas (number in brackets, right); modal words «обязательно»/«рекомендуется» highlighted; special characters (guillemets, em dash). References: cross, footnotes, hyperlinks, TOC dot leaders.
4.5. Service zones: headers/footers, logo, page number, ЕСКД frame, stamp. Separators: lines, blank pages («each section starts on a new sheet»), insets, notes.

## 5. Detection and parsing
5.1. Principles
- Repeating elements (title, TOC, headers/footers) are detected deterministically — no errors, no assumptions.
- Variability: `stable` (title ≈ 20 lines, ±30% threshold) or `variable` (ТЗ body — 5–25 sections).
- A universal python-docx parser is the starting point; the model adapts it to the sample.
- Output: a «sample × element» matrix (present/absent); fields — mandatory/optional; absent is skipped explicitly, never inferred.
- A found element yields the reference example: fragment + parsing method (`sample_refs`).
5.2. DOCX markers: header/footer — non-empty `section.header`; heading — style `Heading`/`Заголовок`, level from the number; figure caption — a `Рисунок N` paragraph after an inline image; title — first page, 12–30 paragraphs, approval marks, no number; TOC — TOC field or «text … number» lines; table — `document.tables`, header = first row, caption = preceding `Таблица N`; change/approval sheets — headers «Изм.», «Разраб.», «Лист», «№ докум.».
5.3. Pipeline: catalog (detection + parser) → run over samples → «sample × element» matrix → present fragments → reference examples (`sample_refs`).

## 6. YAML catalog
6.1. `document-model.ru.yaml` — machine-readable element registry. Fields: `id`, `level` (`document|page|formatting`), `text_element`, `variability` (`stable|variable`), `expected_size`, `description`, `detection`, `parser`, `attributes`, `attributes_optional`, `sample_refs`.
6.2. Mandatory fields: `id`, `level`, `variability`, `detection`, `parser`, `attributes`. Flow: `detection` on the DOCX → on «present» run `parser` → fragment into `sample_refs`. Miniprofiles — `writer-profiles.ru.md`; document typing — Process in `references/process.md`.

## 7. Sample-analysis methodology
7.1. Rules
- 7.1.1. A sample is a document, not a message: parse per element, each separately and completely.
- 7.1.2. All samples of a type — together; one sample is an insufficient sample set.
- 7.1.3. Majority decides: a template parameter repeats in the majority; divergences — variations to the user. Presence — majority; formatting — intersection of all.
- 7.1.3a. Two-level presence (same for BUSINESS and TECH ТЗ):
  - Level 1 — always first: a section enters if present in ≥ the majority of ALL samples (hard majority over all).
  - Level 2 — ONLY if the majority is undeterminable (few signature matches, no consensus; the threshold is deterministic, the script prints the verdict, the model never decides «by eye»): pick the base — the most fully described sample (sections/tables/examples/styles); check the OTHERS against the base by the same hard majority; a base section confirmed by the majority enters the template with the fact «в N из M»; unconfirmed → question/variations, never silently dropped.
  - Prerequisite for both levels — heading-signature normalization (leading numbering «1.», «4.3.1.» stripped), otherwise false fallback.
  - One sample / zero matches: the base as is, no «в N из M», disputed → question. Never invent presence (7.1.5).
- 7.1.4. Evidence in pairs: variability — pairs of wordings; templateness — matching in all.
- 7.1.5. Never invent absent elements or formats; unknown → ask the user.
- 7.1.6. Technique: measure → compare across all → classify (template/variable/variation) → record with evidence → disputed → user immediately.
7.2. «Woodpecker» technique (questions → YAML fields): what is it? → `description`; how is it represented? → `attributes`; how to check presence? → `detection`; how to parse (what is a placeholder, what is a constant)? → `parser`; why so?; what happens with different content (long heading, 0 table rows, no screenshot)?
7.3. Visual verification (mandatory): parsing is checked against a picture — XML can lie (element hidden in `w:sdt`, nested table, header/footer, cached field); every key element is confirmed by page-by-page PNG render, a verdict per page; sheet-to-sheet check against the reference («every character in its place»); divergence → fix → re-run until match (a cycle = a commit); when text and picture disagree, the picture is the truth.

## 8. Parameterization and lifecycle
8.1. A value that may differ per customer is a parameter (spec.json), not a code constant. FORBIDDEN in code: names/organizations/years from samples, intro phrases, field instructions (TOC/PAGE), sizes and font sizes, layout flags; geometry is a parameter too.
8.2. Placeholders — fictional only («Ромашка», «И.И. Иванов», «ФР.000.00.00.0-00»); real sample data is sanitized.
8.3. Startup interview before parsing: project identification, data sources, list markers, disputed facts — one pack; answers are recorded, never left in chat.
8.4. New customer/samples: decompose into catalog elements → detection over all at once → matrix «element → template/variable → evidence» → disputed to the user → then spec and template.

## 9. Examples
✅ `id: title-page, level: page, variability: stable, detection: первая страница, 12–30 параграфов`
❌ element without `parser` — the model cannot parse what it found
❌ `detection: обычно это титульный лист` — non-deterministic marker
