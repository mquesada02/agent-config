---
name: ci-pipelines
description: ci-pipelines creates or reviews GitHub Actions CI for Node/TypeScript repos. Use it when asked to create or review CI, and before you write or edit any file in .github/workflows.
---

# ci-pipelines

Rules and steps for GitHub Actions CI workflows of Node/TypeScript repos.

## Pick the branch

- **Review** (the user asks to review or check CI): follow [review.md](review.md).
- **Create** (the user asks for a new CI workflow): not built yet. Say so, and offer a review of the existing workflows.
- **Another edit** of a workflow file: read [rules/naming.md](rules/naming.md) and keep your edit consistent with it. Do not review the whole repo.

## Intake

The intake script is not built yet. Until it exists, read `package.json`, the lockfile and `.github/workflows/` yourself. Name every default that you assume in the report.

## Modules

- [review.md](review.md): the review steps and the report contract.
- [rules/naming.md](rules/naming.md): NAME-01 to NAME-09. Each rule has an id, a default severity, the rule, its check and its fix.
