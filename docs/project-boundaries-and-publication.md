# Project Boundaries and Publication Rules

## Project independence

This repository is the standalone `tz-rezultat-hz` product. Its purpose,
architecture, implementation, roadmap, and quality criteria are developed
autonomously. Other projects may reuse the skill or its components when useful,
but reuse is optional. Do not modify this project merely to satisfy another
project's internal needs. Integrations must use explicit contracts and remain
optional for consumers.

## Local development

All active development takes place on the `develop` branch; do not create
or use feature branches for project changes. The working tree may contain
experiments, temporary files, reports, helper scripts, local configuration,
test data, customer-specific working material, and other supporting files.
Their local presence does not make them part of the public product.

Do not create private GitHub repositories or private mirrors for local work.
Keep local-only materials on the developer's computer.

## Development and release branches

`develop` is the sole branch for active development and integration. All
changes, including documentation, tests, and implementation, are made on
`develop`. Do not commit or push directly to `main`.

`main` is the release branch. After work on `develop` is reviewed, validated,
and approved for release, transfer the approved changes from `develop` to
`main` through a reviewed pull request. Do not bypass this review gate.

## Distilled public contents

GitHub must contain only the distilled `tz-rezultat-hz` product: the skill,
its runtime/bootstrap, required scripts and dependencies metadata, relevant
tests, documentation, licenses, and files necessary to install, use, verify,
and maintain the product.

Exclude personal data, customer names and identifiers, customer documents,
business processes, real customer examples, local paths, usernames,
developer-specific configuration, secrets, tokens, passwords, private keys,
temporary files, scratch directories, intermediate outputs, personal reports,
local databases, backups, and unrelated materials from other projects.

Use synthetic examples. Replacing a customer name with a placeholder is not
enough if the surrounding context still identifies the customer. Do not include
customer deliverables or source-project working files. Do not weaken checks or
remove protective tests to pass publication review.

## Publication gate

Before pushing to `main`:

1. Review the complete diff and all added, changed, deleted, and untracked files.
2. Confirm every file belongs to the public `tz-rezultat-hz` product.
3. Check for personal data, customer material, local paths, secrets, and
   unrelated files.
4. Run applicable tests and project checks, including privacy/leak checks.
5. Push only the reviewed, distilled result to `main`.

Do not mirror the local working directory to GitHub. Publication is a deliberate
selection of reviewed product changes. If a file's public status is uncertain,
keep it local and ask the user.

These rules apply to all agents and contributors.
