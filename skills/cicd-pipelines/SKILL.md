---
name: ci-pipelines
description: ci-pipelines creates or reviews GitHub Actions CI for Node/TypeScript repos. Use it when asked to create or review CI, and before you write or edit any file in .github/workflows.
---

# ci-pipelines

Rules and steps for GitHub Actions CI workflows of Node/TypeScript repos.

## Intake

Before you pick a branch, run the intake script on the repo as one plain command: `python3 <skill folder>/scripts/intake.py <repo path>`, where `<skill folder>` is the full path of this skill folder. Add no `cd`, no `;`, no `&&` and no pipe to this command, and never put another command in the same call (a permission rule for the script matches only a command that starts with `python3` and the script path). It prints one JSON object. Read only this JSON for the repo facts. On the reply to a review report, you reuse the intake facts of the review in this conversation, and you run the intake script again only when none are in the conversation. Each fact has `value`, `status` (`detected`, `default` or `unknown`) and `source`. Name every fact with the status `default` or `unknown` in the report. With no network, the script reads the dated list of supported Node majors from [tools.md](tools.md), and the `installed_tools` fact says which of actionlint, zizmor and pinact are on PATH (see [tools.md](tools.md)).

## Pick the branch

Read the whole branch file with the Read tool, never only a part of it with a search: the parts that you need are at its end too.

- **Review** (the user asks to review or check CI): follow [review.md](review.md). When the user replies to a review report with a selection (`all`, `none`, a list or a range), follow "Fix on approval" in [review.md](review.md).
- **Create** (the user asks for a new CI workflow): follow [create.md](create.md). It picks a template, fills it from the intake facts and ends with a self-review report.
- **Another edit** of a workflow file: read [rules/naming.md](rules/naming.md), [rules/job-graph.md](rules/job-graph.md), [rules/cost.md](rules/cost.md), [rules/security.md](rules/security.md) and [rules/maintainability.md](rules/maintainability.md), and also [rules/monorepo.md](rules/monorepo.md) when the intake finds a monorepo, and keep your edit consistent with them. Do not review the whole repo.

## Modules

- [scripts/intake.py](scripts/intake.py): the intake script. It reads the repo files and makes read-only `gh api` calls. It reads the dated offline Node list from [tools.md](tools.md) when it has no network.
- [scripts/check_pins.py](scripts/check_pins.py): the SEC-01 pin check. It makes read-only `gh api` calls and tells whether each pinned SHA is the commit of its version comment tag.
- [tools.md](tools.md): detection and install hints for actionlint, zizmor and pinact, the zizmor-to-SEC mapping, the output merge, the SHA lookup and the dated offline list of supported Node majors (the intake script reads this list with no network).
- [review.md](review.md): the review steps, the report contract and the fix-on-approval steps.
- [create.md](create.md): the create steps, the fill table, and the Dependabot and `security-audit.yml` texts.
- [templates/single-package.yml](templates/single-package.yml) and [templates/monorepo.yml](templates/monorepo.yml): the two workflow templates that create mode fills.
- [scripts/check_workflow.py](scripts/check_workflow.py): the structural assertion script. It takes a workflow and assertions and returns pass or fail. The create evals and the unit tests use it.
- [scripts/grade_create_results.py](scripts/grade_create_results.py): the post-run grader of the create eval cases (structural assertions and the real actionlint).
- [rules/naming.md](rules/naming.md): NAME-01 to NAME-09. Each rule has an id, a default severity, the rule, its check and its fix.
- [rules/job-graph.md](rules/job-graph.md): GRAPH-01 to GRAPH-07 (jobs, `needs:`, matrices, shards, the build artifact, suite matrices).
- [rules/cost.md](rules/cost.md): COST-01 to COST-08 (triggers, concurrency, path filters, timeouts, installs, workers, runner labels, checkout depth).
- [rules/security.md](rules/security.md): SEC-01 to SEC-10 (SHA pins, Dependabot, permissions, `${{ }}` in `run:`, checkout credentials, submodule tokens, privileged triggers, `secrets: inherit`, caches, the dependency audit).
- [rules/monorepo.md](rules/monorepo.md): MONO-01 to MONO-02 (affected packages on PRs). Load it only for a monorepo, that is when the intake `monorepo` fact has `monorepo: true`.
- [rules/maintainability.md](rules/maintainability.md): MAINT-01 to MAINT-03 (long `run:` blocks, step comments, copied workflows).
