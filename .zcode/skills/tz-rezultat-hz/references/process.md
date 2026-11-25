# Process — canonical step map (EN)

The single source of truth for the production flow: 8 steps, fixed
order. SKILL.md step headings reference this file
(`→ process.md §N`). The user-facing mirror is `docs/process-ru.md`
(same numbering; a change to a step = BOTH files changed in one commit).

## Ordering rule

The agent MUST NOT start Step N+1 until the Step N exit condition is
met (the exit artifact exists on disk). Verify with
`scripts/check_progress.py --work <work>` BEFORE starting each step,
after any stop, and on resume — continue only from its output, never
from memory. `прогресс.json` is written ONLY by scripts/gates; the
agent NEVER edits it.

## Stop/resume

- **Stop signal from the user**: finish the current atomic action, run
  `check_progress.py`, report the current step and the next step, wait.
- **Resume (possibly a new session, next day)**: run `check_progress.py`
  FIRST and continue from the reported first unfinished step — never
  from memory.

## Steps 1–8

### Step 1 — Preflight

| | |
|---|---|
| Purpose | Environment check, configuration bind (cf/cfe), unica setup. |
| Entry | Work folder exists; settings/configurable inputs provided by the user. |
| Exit | `settings.yaml` + `projects/*.yaml` on disk. |
| Gates | preflight (path guard for cf/cfe). |
| Packs | — |

### Step 2 — Single dialog

| | |
|---|---|
| Purpose | Full scan → deep research → Self-Grill → ALL questions → §6 gate. |
| Entry | Step 1 exit artifacts on disk. |
| Exit | `projects/*/версии/*/вопросы_ответы_*.md` (question ledger). |
| Gates | check_questions (journal clean). |
| Packs | CONTENT PACK (before the §6 gate): all ledger questions issued consecutively; «вопросов больше нет» precedes «Могу ли я начинать?». |

### Step 3 — Samples

| | |
|---|---|
| Purpose | Sample ТЗ documents into the project; init_project. |
| Entry | Step 2 exit artifact on disk. |
| Exit | `projects/*/references` populated. |
| Gates | — |
| Packs | — |

### Step 4 — Parsing

| | |
|---|---|
| Purpose | Parse samples into spec.json (extract_spec / tz_tool extract). |
| Entry | Step 3 exit artifact on disk. |
| Exit | `projects/*/версии/*/версия-*/spec.json`. |
| Gates | — (record step 4 via `--progress`). |
| Packs | — |

### Step 5 — Template

| | |
|---|---|
| Purpose | Build the DOCX template (build_from_spec / tz_tool build); gates 1–2. |
| Entry | Step 4 exit artifact on disk. |
| Exit | `projects/*/версии/*/версия-*/шаблон_ТЗ_1С.docx`. |
| Gates | verify_template (гейты 1–2); record step 5 via `--progress`. |
| Packs | SAMPLES PACK (BEFORE the first build): samples choice, doc code, PII mode (sanitize/keep — asked BEFORE extract_spec), template scope (full ТЗ vs single element). |

### Step 6 — Object map

| | |
|---|---|
| Purpose | Object map (check_map) and reconciliation. Skipped for бизнес-ТЗ. |
| Entry | Step 5 exit artifact on disk. |
| Exit | `projects/*/версии/*/версия-*/obj-map.json`. |
| Gates | check_map (record step 6 via `--progress`). |
| Packs | MAP PACK (if check_map finds problems): ALL questions from ALL violations in ONE batch, then ONE re-run. |

### Step 7 — Text

| | |
|---|---|
| Purpose | Mini-profiles → draft.md → lint → render. |
| Entry | Step 5 exit artifact (Step 6 for тех-ТЗ) on disk. |
| Exit | `projects/*/версии/*/версия-*/draft.md`. |
| Gates | lint_draft clean (record step 7 via `--progress`). |
| Packs | — |

### Step 8 — Completion

| | |
|---|---|
| Purpose | final_gate, layout, result document. |
| Entry | Step 7 exit artifact on disk. |
| Exit | `projects/*/тз/*/*.docx`. |
| Gates | final_gate (cross-checks progress records for steps 1–7; records step 8). |
| Packs | — |

## Restate-the-answer

After each answered pack the agent MUST restate each answer in its own
words grounded in configuration terms (CLAMBER answer-in-context).
Inability to restate concretely = the answer is insufficient → follow-up
question. Self-Grill dialog rounds are exempt.
