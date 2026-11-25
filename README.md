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

No Python ships with the repository. On first use the agent runs
`bootstrap.ps1` (Windows) or `bootstrap.sh` (Linux) **without a mode flag**:
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
refusal (`bootstrap.ps1 -NoGrilling` / `bash bootstrap.sh --no-grilling`) and
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

- `.zcode/skills/tz-rezultat-hz/SKILL.md` — the skill's route and rules.
- `bootstrap.ps1` / `bootstrap.sh` / `bootstrap.py` — runtime install.
- `components.ru.md` — the component list printed on first run.
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

Everything is installed at first use by the skill's bootstrap and is **not**
redistributed here: Python and the libraries (python-docx, PyMuPDF, lxml,
pywin32), `format-agent` (pinned upstream commit) and `grilling` (pinned
upstream commit, MIT). Licenses and provenance — [`THIRD-PARTY.md`](THIRD-PARTY.md).

## License

MIT — see [`LICENSE`](LICENSE). Third-party components and their
licenses are listed in [`THIRD-PARTY.md`](THIRD-PARTY.md).
