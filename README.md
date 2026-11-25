# tz-rezultat-hz — 1С Specification (ТЗ) Template Skill

**A tool for the agent-driven development of technical specifications (ТЗ).**
It is meant to be used together with an AI agent that does most of the work
itself. Русская версия — [`README.ru.md`](README.ru.md).

## How it works

You provide the material; the agent:

- analyses what you have provided;
- studies the ТЗ samples you supplied and uses them as a reference;
- asks you questions when the input data is not enough;
- shapes the structure and the content of the specification;
- runs the checks and reworks the result.

## Your role

You supply what the agent cannot know by itself: ТЗ samples and examples,
answers to clarifying questions, the description of business processes and
requirements — other input data and expert knowledge.

You are not expected to do the analytical or the document work by hand: the
agent does it. You step in where your knowledge, your decisions and your
confirmation of the result are needed.

## What the tool does not do

- It does **not** work fully autonomously: the process cannot be finished
  without your answers and your confirmation of the result.
- The agent does **not** know your enterprise on its own: configuration
  specifics, local rules and exceptions come only from your input.
- The quality of the result depends directly on the samples, descriptions and
  answers you provide — thin input gives a thin specification.

> **Platform support: Windows and Linux.** This release installs and runs on
> Windows (`win-x64`) and Linux (`linux-x64`). Both are first-class: the same
> pinned runtime, the same full set, and the same transactional install
> (candidate dir → validate → swap; the previous working runtime is moved to
> `.staging/previous-*`, never deleted, and restored on any failure). Other
> platforms (arm64, macOS) are not supported: the platform gate in
> `bootstrap.py` stops before anything is downloaded or changed.

## Install

A skill is just a folder. Copy `.zcode/skills/tz-rezultat-hz/` into your
agent's skills directory, for example:

```
~/.agents/skills/tz-rezultat-hz/
```

No Python ships with the repository. On first use the agent runs the platform
entry point **without a mode flag** — `bootstrap.ps1` on Windows or
`bash bootstrap.sh` on Linux:
it prints the list of components of the **full set** — the main and
recommended scenario — with each component's purpose and the consequence of
its absence (see `components.ru.md`), and exits **without downloading
anything**. On your confirmation the same script is run in the full mode:

```
bootstrap.ps1 -Full          # Windows
bash bootstrap.sh --full     # Linux
```

It then downloads, verifies against fixed pins (upstream commits + content
SHA-256) and installs: the pinned `python-build-standalone`, the Python
dependencies (`scripts/requirements.txt`), the pinned minimal `format-agent`
set and the pinned `grilling` skill — the last two from their official
upstream commits. Re-runs verify the already-installed components and do
**not** re-download healthy ones. If a required component cannot be
downloaded or verified, the installation stops with `[FAIL]` and the runtime
and manifest are left unchanged — success is never imitated.

`tz-1c-style` is part of this repository (`bundle/`, MIT); `scripts/preflight.py`
verifies the environment and deploys it.

**Declining `grilling` means incomplete analytics.** The Step 2 self-grill
(«прожарка») is then unavailable and unverified gaps pass into the ТЗ — this
is not normal work. Installing without it is possible only on an explicit
refusal (`bootstrap.ps1 -NoGrilling`) and
is not offered as an equal alternative.

Later checks keep the distinction (they are not interchangeable): a set
declared **full** with `grilling` missing or damaged reports **`[FAIL]`** and
must be restored with the full mode before work; only an explicitly declined
set — or a manifest of the legacy format (schema 1, no install record), whose
set is **unknown** — reports **`[WARN]`** and is never counted as a confirmed
full installation.

## Use

Work goes through the agent: describe the 1С change — the skill builds
the ТЗ template and fills it. Entry point and step-by-step protocol —
`SKILL.md`.

## Contents

- `README.md` / [`README.ru.md`](README.ru.md) — this description (EN / RU).
- `.zcode/skills/tz-rezultat-hz/SKILL.md` — the skill's route and rules.
- `bootstrap.ps1` / `bootstrap.sh` / `bootstrap.py` — runtime install
  (Windows and Linux). `bootstrap.ps1` is the Windows entry point,
  `bootstrap.sh` the Linux entry point; both delegate to `bootstrap.py`
  and build transactionally (candidate dir → validate → swap).
- `components.ru.md` — the component list printed on first run.
- `scripts/` — the pipeline (extraction, build, gates, render).
- `references/` — document model and method.
- `bundle/tz-1c-style/` — base tone layer (MIT).

## Documentation

Technically, the pipeline is: TZ samples → `spec.json` → dense DOCX template →
two gates (structural + visual); stage 2 fills the template with business-ТЗ
text from a retouch description.

- Document model & parsing method:
  [`references/document-model.ru.md`](.zcode/skills/tz-rezultat-hz/references/document-model.ru.md)
  (RU) and machine-readable catalog
  [`document-model.ru.yaml`](.zcode/skills/tz-rezultat-hz/references/document-model.ru.yaml).
- Writer mini-profiles:
  [`references/writer-profiles.ru.md`](.zcode/skills/tz-rezultat-hz/references/writer-profiles.ru.md).
- Process (user-facing): [`docs/process-ru.md`](docs/process-ru.md) (RU).

Documentation and generated artifacts are Russian (the project produces
Russian 1С ТЗ documents).

## Dependencies

Everything is installed at first use by the skill's bootstrap and is **not**
redistributed here: Python and the libraries (python-docx, PyMuPDF, lxml,
pywin32), `format-agent` (pinned upstream commit) and `grilling` (pinned
upstream commit, MIT). Licenses and provenance — [`THIRD-PARTY.md`](THIRD-PARTY.md).

## License

MIT — see [`LICENSE`](LICENSE). Third-party components and their
licenses are listed in [`THIRD-PARTY.md`](THIRD-PARTY.md).
