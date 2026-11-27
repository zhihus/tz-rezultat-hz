# Agent Instructions

This repository contains the independent `tz-rezultat-hz` product. Read
`docs/project-boundaries-and-publication.md` before preparing or changing
public releases.

Do not adapt this project to another project's internal needs. Reuse by other
projects is optional and must remain behind explicit contracts.

All development and integration work is performed on the public `develop`
branch. Do not commit or push changes directly to `main`. After a change is
reviewed, validated, and approved for release, transfer it from `develop` to
`main` through a reviewed pull request. `main` is the release branch.

Local customer-specific or developer-only supporting files must remain local
unless they are demonstrably part of the public product and have been safely
replaced with synthetic examples.

Never publish customer documents, real customer identifiers, personal data,
local paths, secrets, local configuration, temporary files, reports, backups,
or unrelated project materials. Run the applicable product and privacy checks
before publication. If uncertain, keep the file local and ask the user.
