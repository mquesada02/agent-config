---
name: ci-pipelines
description: ci-pipelines creates or reviews GitHub Actions CI for Node/TypeScript repos. Use it when asked to create or review CI, and before you write or edit any file in .github/workflows.
---

# ci-pipelines

Rules and steps for GitHub Actions CI workflows of Node/TypeScript repos.

## Intake

Before you pick a branch, run the intake script on the repo: `python3 scripts/intake.py <repo path>` (the script path is relative to this skill folder). It prints one JSON object. Read only this JSON for the repo facts. Each fact has `value`, `status` (`detected`, `default` or `unknown`) and `source`. Name every fact with the status `default` or `unknown` in the report.

## Pick the branch

- **Review** (the user asks to review or check CI): follow [review.md](review.md).
- **Create** (the user asks for a new CI workflow): not built yet. Say so, and offer a review of the existing workflows.
- **Another edit** of a workflow file: read [rules/naming.md](rules/naming.md), [rules/job-graph.md](rules/job-graph.md) and [rules/maintainability.md](rules/maintainability.md), and keep your edit consistent with them. Do not review the whole repo.

## Modules

- [scripts/intake.py](scripts/intake.py): the intake script. It reads the repo files and makes read-only `gh api` calls.
- [scripts/node-support-offline.json](scripts/node-support-offline.json): the dated offline list of supported Node majors. The intake script uses it with no network.
- [review.md](review.md): the review steps and the report contract.
- [rules/naming.md](rules/naming.md): NAME-01 to NAME-09. Each rule has an id, a default severity, the rule, its check and its fix.
- [rules/job-graph.md](rules/job-graph.md): GRAPH-01 to GRAPH-07 (jobs, `needs:`, matrices, shards, the build artifact, suite matrices).
- [rules/maintainability.md](rules/maintainability.md): MAINT-01 to MAINT-03 (long `run:` blocks, step comments, copied workflows).
