# ZCode interactive-question contract

This reference applies only when `--harness zcode` is selected. It is
mandatory for the main agent; subagents must not ask the user.

## Tool availability

- The exact tool name is `AskUserQuestion` (case-sensitive).
- Check the active **main-agent** session tool list immediately before the
  first question batch. A standalone `preflight.py` process cannot inspect
  that live tool pool and must not claim that the tool is available. Its
  `[WARN]` means **unverified**, not that the tool is missing.
- If the tool is absent, unavailable, denied, or rejects the input schema,
  stop and report the failure. Do not send the same questions as ordinary
  assistant text and do not proceed as if answers had been collected.
- Never delegate user questions to a subagent.

## Input schema

A call has one top-level `questions` array containing **1–4** questions.
Every question must contain:

| Field | Requirement |
|---|---|
| `question` | Complete and specific. Prefer a question mark; fixed question-pack wording and punctuation remain verbatim. |
| `header` | Short chip label, maximum 12 characters. |
| `options` | 2–4 distinct options. Each has `label` and `description`; labels must be unique. |
| `multiSelect` | Boolean. Use `false` unless the choices are independently selectable. |

Additional schema constraints:

- Option labels should be concise (1–5 words); descriptions explain the choice. If the pack has no description, add a short neutral explanation without changing the label.
- Do not add an `Other` option: ZCode supplies it automatically.
- Do not duplicate question texts or option labels within a question.
- Do not add unsupported fields. The input schema is strict.
- Each question represents exactly one topic/value (Rule 3 in `SKILL.md`).

## Mapping question packs

- Preserve the exact Russian question wording and the pack's specified options.
  Do not paraphrase fixed wording to fit the UI.
- Convert each pack item to one schema question. Use a short `header` (≤12
  characters), the pack's 2–4 options, and `multiSelect: false` unless the
  question genuinely permits independent multiple selections.
- Where a pack expects free text, retain its explicit text-entry choice and
  collect the user's text through the question's free-text/notes input or the
  automatically supplied `Other` input. Treat that text as the answer to the
  same question; do not create an extra question or invent a default.
- A pure free-text item with no explicit choice set (for example, the new-ТЗ
  code question in §2 п.4) still needs two schema-valid options: «Указать
  значение» (enter the value in the free-text/notes field) and «Не могу
  указать сейчас» (the agent stops and waits; this is not permission to infer
  or continue). Keep the automatic `Other` input available for arbitrary text.
  Do not invent a default or a third decision.
- Never invent a recommended option. Recommendations must remain exactly
  those stated in the question pack or supported by the samples.

## Batches larger than four

- A single call must never contain more than four questions.
- Split a larger fixed pack into consecutive batches of at most four, preserving
  the original order.
- Self-Grill rounds are logical groups, not individual API calls. If one
  round contains more than four questions, split it into consecutive
  sub-batches; finish all sub-batches and collect all their answers before
  starting the next round. This transport split does not create extra rounds.
- Ask the next batch immediately after receiving the previous batch's answers:
  no analysis, research, file edits, unrelated tool calls or progress to another
  step between batches.
- Do not restate or interpret partial answers between batches. After the final
  batch, restate every answer as required by the pack and Rule 6.
- If the tool interaction cannot continue, stop; do not silently drop remaining
  questions or replace them with text.

## No-answer behavior and ZCode auto-resolution

ZCode's `askUserQuestionAutoResolutionEnabled` setting defaults to `true`.
When enabled, an unanswered ordinary question can be automatically resolved
after five minutes with an empty `answers` object, after which ZCode tells the
model to continue using its best judgment. That behavior conflicts with Rule 6
(no answer → stop).

- The user must turn OFF «提问自动继续» / `askUserQuestionAutoResolutionEnabled`
  in ZCode settings before the first question. The setting is under the
  Agent abilities / Behavior and tools settings group; wording may vary by
  localization.
- The skill cannot inspect or change this application setting. Do not claim it
  is disabled unless the user confirms it.
- If an `AskUserQuestion` result has no answer or an empty `answers` object,
  treat it as **no answer**: stop immediately, do not infer, do not continue,
  and use the exact stop wording from Rule 6.
- Never interpret timeout, cancellation, decline, or empty answers as consent.


## Source references

- AskUserQuestion schema: https://github.com/zai-org/ZCode/blob/main/apps/zcode-cli/packages/contracts/src/tools/ask-user-question.ts
- Five-minute auto-resolution behavior and setting: https://github.com/zai-org/ZCode/blob/main/docs/ask-user-question-auto-resolution.md
