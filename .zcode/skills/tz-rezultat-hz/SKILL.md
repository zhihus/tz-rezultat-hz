---
name: tz-rezultat-hz
description: 1С ТЗ production pipeline — builds an empty dense DOCX ТЗ template from samples (Step 5) and fills it with text from a change description (Steps 6–8). Use whenever the user asks to create/rebuild a ТЗ шаблон, a title-page or element template, a new version, to write a ТЗ for a 1С доработка, or to fill a template with text — even if the word «конвейер» is absent.
---

# tz-rezultat-hz — 1С ТЗ production

## Entry point and reference map

Read this file in full at session start. It contains the non-negotiable rules,
project boundaries and execution route. Detailed step procedures are loaded
only when the corresponding step is reached.

| File | Purpose | When to read |
|---|---|---|
| `references/process.md` | Canonical 8-step order, entry/exit artifacts and gates. | At start and on resume |
| `references/step-protocol.ru.md` | Full operational instructions for Steps 1–8 and the technical-ТЗ branch. | Read the current step before executing it; do not preload all steps |
| `references/question-packs.ru.md` | Verbatim Russian question wording and option packs. | Before every question batch |
| `references/zcode-harness.ru.md` | ZCode AskUserQuestion contract, batching and no-answer behavior. | Before every ZCode question call |
| `references/unica-setup.ru.md` | Unica (1C MCP) launch chain, failure diagnostics and call discipline. | Step 1; re-read on any Unica failure |
| `references/document-model.ru.md` | Document model and parsing methodology. | Step 4 |
| `references/document-model.ru.yaml` | Machine-readable 54-element catalog; scripts load by filename. Do not rename. | Step 4 / detection work |
| `references/element-parsing-protocol.ru.md` | Protocol for extending parsing to catalog elements. | When extending extraction |
| `references/tech-tz-map.ru.md` and `references/obj-map.schema.json` | Object-map method, technical-ТЗ section canon and schema. | Step 6 and technical Step 7 |
| `references/oneshots-tech.ru.md` and `references/writer-profiles.ru.md` | Technical writing patterns and mini-profile format. | Step 7 |

Scripts are in `scripts/` next to this file; paths are relative to the skill
folder. Do not duplicate reference content here.

## ⚠ RULE 1 — NO SAMPLE HARDCODING ⚠
Parser, build, gates work on ANY DOCX: Word structure only (styles, numPr, gridSpan, tables) + YAML catalog detection. Hardcoded section names, organizations, codes, typos, customer numbering formats are FORBIDDEN in code; such knowledge lives only in document-model.ru.yaml (detection). Code fit to a sample → generalize or move to catalog.

## ⚠ RULE 2 — CONTRACT FOR A WEAK MODEL ⚠
**THE PIPELINE DOES EVERYTHING COMPLEX; THE MODEL WRITES TEXT ONLY.** Executor may be 3B–27B: flat text in, Yes/No/Skip out; layout/links/numbering/placeholders come from sample data via pipeline. Accept new mechanics only if a weak model can follow the text. Adapting to the model is FORBIDDEN.

Follow script reports, do not redo their work by hand (E-49): preflight / find_samples / init_project / find_config / lint_draft / gen_miniprofiles check and act THEMSELVES; the model does only steps marked «модель».

Mirror discipline (source repo with the flat `конвейер/` mirror): after ANY skill file change run `scripts/sync_check.py`; FAIL → follow prescriptions until «чисто». The install is ALWAYS ONE (`~/.agents/skills/tz-rezultat-hz`) — a second copy (e.g. `~/.zcode/skills/...`) = FAIL «лишняя копия»: move to temp/ or delete (sessions read the wrong copy and run stale rules — defect 2026-11-22).


## Harness contract (Step 1)

- **ZCode:** every user question MUST use the exact `AskUserQuestion` tool from the
  active main-agent session. The standalone preflight cannot inspect the live
  session tool pool or ZCode app settings. Verify both manually before the first
  question; see `references/zcode-harness.ru.md`.
- If `AskUserQuestion` is absent, unavailable, rejected, or its schema validation
  fails, STOP and report the exact failure. **Never replace it with a text
  question**, never continue as if the question had been asked.
- Before asking, the user must have disabled ZCode's five-minute
  `askUserQuestionAutoResolutionEnabled` / «提问自动继续» setting. Its default
  is enabled. If the setting is not confirmed OFF, do not start a question batch.
- **Claude Code:** use its interactive question tool.
- **Codex / other:** use the text-question fallback specified by the platform
  protocol; this exception does not apply to ZCode.

## ⚠ RULE 3 — ONE QUESTION = ONE TOPIC ⚠
A question carries EXACTLY ONE value with ONE input field; several values in one question are FORBIDDEN (#13 — a triple question got only the code answered). Several values → several questions; combining into ONE tool call is allowed (each with its own field).

## ⚠ RULE 4 — ONE CONTENT INTERVIEW ⚠
Questions about TZ CONTENT — only in Steps 1–2. After the §6 gate — ZERO questions about TZ CONTENT, ALWAYS: unclear → inline mark «[уточнить по конфигурации: …]» in the ТЗ text at the point of uncertainty + a line in the final summary and исследование.md (the service list is NOT a separate block in draft.md — F2/F9), never a guess or a question. Organizational questions of Step 3 (samples, КОД) are allowed. Exception — reaction to user actions (Step 3). Re-interview only if the USER asks.

## ⚠ RULE 5 — ANALYZE ON ALL SAMPLES ⚠
Any claim about style, structure, «defect», «water» — only after checking ALL samples (parsing scripts / extract_spec / dumps), never one. Generalizing from one file is FORBIDDEN (2026-11-18 lesson: two «defects» turned out to be verbatim sample patterns). Variation is normal.

## ⚠ RULE 6 — NO ANSWER → STOP ⚠
Question asked → work is STOPPED until the answer. Silence → do NOT continue, do NOT infer in any form. Write: «Не смогли получить ответ от вас — остановились и ждём. Задайте вопрос заново или ответьте на предыдущий». (2026-11-20 lesson: on silence the model «inferred» sample classification.)

## Project
Work ALWAYS inside the project folder. Project ≈ customer; agent proposes the name (Step 3).

```
projects/
├─ projects.yaml          ← manifest: name, customer, date, answers
├─ settings.yaml          ← settings (verify_report: off)
└─ <project-name>/
   ├─ references/  ├─ profiles/
   ├─ тз/<КОД>/            ← documents ONLY
   └─ версии/<КОД>/версия-N/  ← spec, draft, obj-map, figs, plan,
                              temp/ (PNG), reports
```

After choosing a project, never leave its folder; don't read foreign projects/samples or the skill's references/. Active project — right after preflight: one in the manifest → «Продолжаем проект X?»; several → list; no manifest → project appears after sample parsing. A re-run creates no duplicate: the manifest is the source of truth.

## Step protocol and progress

The detailed execution rules formerly embedded below this point are preserved
verbatim in `references/step-protocol.ru.md`. Read the matching section before
each step. `references/process.md` remains the compact canonical map.

PROGRESS STATE — `прогресс.json` in the work folder is written ONLY by
scripts/gates (`record_progress`); the agent NEVER edits it by hand. The agent
MUST NOT start Step N+1 until the Step N exit artifact exists on disk. Run
`python.exe scripts/check_progress.py --work <workdir>` BEFORE each step,
after any stop, and on every resume — continue ONLY from its output (the first
unfinished step), never from memory.

STOP/RESUME — on a user stop signal: finish the current atomic action, run
`check_progress.py`, report the current and next step, then wait. On resume
(possibly in a new session or next day): run `check_progress.py` FIRST.
Gates append records on PASS: preflight→1, check_questions→2, extract→4,
build→5, check_map→6, lint_draft (clean)→7, final_gate→8. final_gate also
cross-checks steps 1–7; a claimed-done step without a record fails.

