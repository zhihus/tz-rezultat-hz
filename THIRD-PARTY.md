# Third-party components

This repository is licensed under **MIT** (see [`LICENSE`](LICENSE)).
It uses the third-party components below. Nothing here is vendored: the
runtime dependencies are installed by the skill's `bootstrap.ps1` on first
use (`bootstrap.sh` is the future Linux entry point, temporarily disabled —
Windows only for now) and are **not** redistributed by this
repository, so their licenses do not apply to the repository's own code.

## Runtime dependencies (installed at first use, not redistributed)

| Component | Version | License | Role |
|-----------|---------|---------|------|
| [python-docx](https://python-docx.readthedocs.io/) | 1.2.0 | MIT | DOCX read/write |
| [lxml](https://lxml.de/) | 6.1.3 | BSD-3-Clause | XML backend for python-docx |
| [PyMuPDF](https://pymupdf.readthedocs.io/) | 1.28.2 | **AGPL-3.0** (or commercial) | PDF rendering for the visual gate |
| [pywin32](https://github.com/mhammond/pywin32) | 311 | PSF-2.0 | Word COM render (Windows only) |
| [python-build-standalone](https://github.com/astral-sh/python-build-standalone) | 20261124 (CPython 3.11.18) | PSF-2.0 | Python runtime (downloaded by the skill's bootstrap) |

⚠ **PyMuPDF is AGPL-3.0.** It is an external `pip` dependency that you
install yourself; this repository does not ship it. If you redistribute
a product that bundles PyMuPDF, AGPL-3.0 obligations apply to that
product. If that is a problem, replace the PDF-rendering step or obtain
a commercial PyMuPDF license.

## External components (fetched at first use, not redistributed)

The skill's bootstrap installs the **full component set** (the main and
recommended scenario). It fetches each external component from its official
upstream strictly at a **pinned commit** and verifies the exact file set and
a content SHA-256 (line-ending-normalized); nothing is fetched from a moving
branch or from an unverified copy. Neither component is redistributed by
this repository.

| Component | Source (pinned) | License | Note |
|-----------|-----------------|---------|------|
| `format-agent-skill` | `github.com/KaguraNanaga/format-agent-skill` @ `8dd726caba43953579d386339765b9613ca6bd58` | PolyForm Noncommercial 1.0.0 | Not redistributable here; the bootstrap fetches the 33-file minimal set and verifies `content_sha256 = 218ee326…96c8ff7f` |
| `grilling` | `github.com/mattpocock/skills` @ `7739eaed7f8f3915437a8def198a6d0d7206dbc7` | MIT (© 2026 Matt Pocock) | Component of the full set (the Step 2 «прожарка» self-grill); the bootstrap fetches 2 files (`skills/productivity/grilling/SKILL.md`, `agents/openai.yaml`) and verifies `content_sha256 = 2c298228…a281ce46`. Declining it means **incomplete analytics** |

The bundled `bundle/tz-1c-style/` style layer is part of this project
(MIT).

## Notes

- `.zcode/skills/tz-rezultat-hz/scripts/requirements.txt` pins exact
  versions so a setup run is reproducible.
- No third-party binary larger than 50 MB is tracked; the Python runtime
  is downloaded on demand by the skill's bootstrap.
