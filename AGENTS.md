# Agent Instructions

This repository contains the independent `tz-rezultat-hz` product. Read
`docs/project-boundaries-and-publication.md` before preparing or changing
public releases.

Do not adapt this project to another project's internal needs. Reuse by other
projects is optional and must remain behind explicit contracts.

Keep `main` unchanged as the existing baseline/release branch. All new work
starts from `develop`, both locally and on GitHub. For each specification,
feature, bug fix, or other independent change, create a dedicated working
branch from the current `develop` (for example `spec/<name>`, `feature/<name>`,
or `fix/<name>`). Do not develop new work directly on `main`.

When a working branch is complete, reviewed, and validated, merge it back
into `develop` through a pull request. Keep local and remote branch histories
aligned; push working branches to GitHub when remote review or backup is
needed. Do not merge or push anything into `main` unless the user explicitly
requests a release transfer.

Local customer-specific or developer-only supporting files must remain local
unless they are demonstrably part of the public product and have been safely
replaced with synthetic examples.

Never publish customer documents, real customer identifiers, personal data,
local paths, secrets, local configuration, temporary files, reports, backups,
or unrelated project materials. Run the applicable product and privacy checks
before publication. If uncertain, keep the file local and ask the user.
