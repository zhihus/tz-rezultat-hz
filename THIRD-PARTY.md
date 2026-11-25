# Third-party components

This repository is licensed under **MIT** (see [`LICENSE`](LICENSE)).
It uses the third-party components below. Nothing here is vendored: the
runtime dependencies are installed by the skill's `bootstrap.ps1` /
`bootstrap.sh` on first use and are **not** redistributed by this
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

## Optional / external components (not part of this repository)

| Component | License | Note |
|-----------|---------|------|
| `format-agent-skill` | PolyForm Noncommercial 1.0.0 | Not redistributable here; the skill's bootstrap fetches it from the pinned upstream commit at first use |
| `grilling` | third-party | Not redistributed; optional (the Step 2 «прожарка» stage) — absent → `[WARN]`, main steps work without it |

The bundled `bundle/tz-1c-style/` style layer is part of this project
(MIT).

## Notes

- `.zcode/skills/tz-rezultat-hz/scripts/requirements.txt` pins exact
  versions so a setup run is reproducible.
- No third-party binary larger than 50 MB is tracked; the Python runtime
  is downloaded on demand by the skill's bootstrap.
