# tz-rezultat-hz — 1С Specification (ТЗ) Template Skill

A skill for 1С analysts: a data-driven pipeline — TZ samples →
`spec.json` → dense DOCX template → two gates (structural + visual);
stage 2 fills the template with business-ТЗ text from a retouch
description. The skill lives in
[`.zcode/skills/tz-rezultat-hz/`](.zcode/skills/tz-rezultat-hz/SKILL.md).

## Install

A skill is just a folder. Copy `.zcode/skills/tz-rezultat-hz/` into your
agent's skills directory, for example:

```
~/.agents/skills/tz-rezultat-hz/
```

No Python ships with the repository: on first use the agent runs
`bootstrap.ps1` (Windows) or `bootstrap.sh` (Linux) from the skill
folder. It downloads a pinned python-build-standalone, installs the
dependencies (`scripts/requirements.txt`) and the pinned minimal
`format-agent` set from the official upstream commit, then
`scripts/preflight.py` verifies the environment and deploys the
`tz-1c-style` style layer from `bundle/`.

## Use

Work goes through the agent: describe the 1С change — the skill builds
the ТЗ template and fills it. Entry point and step-by-step protocol —
`SKILL.md`.

## Contents

- `.zcode/skills/tz-rezultat-hz/SKILL.md` — the skill's route and rules.
- `bootstrap.ps1` / `bootstrap.sh` / `bootstrap.py` — runtime install.
- `scripts/` — the pipeline (extraction, build, gates, render).
- `references/` — document model and method.
- `bundle/tz-1c-style/` — base tone layer (MIT).

## Documentation

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

- `grilling` — an optional third-party skill (the Step 2 «прожарка» /
  self-grill stage). It is not shipped here; when absent, preflight
  reports `[WARN]` and the main steps work without it.
- Runtime deps (python-docx, PyMuPDF, lxml, pywin32) are installed at
  first use by the skill's bootstrap, not redistributed here.

## License

MIT — see [`LICENSE`](LICENSE). Third-party components and their
licenses are listed in [`THIRD-PARTY.md`](THIRD-PARTY.md).
