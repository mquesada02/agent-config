---
name: cicd-pipelines
description: cicd-pipelines creates or reviews GitHub Actions CI and CD for Node/TypeScript repos: deploy, release, rollback, npm publish, and branch protection, rulesets and environments. Use it when asked to create or review any of these, and before you write or edit any file in .github/workflows.
---

# cicd-pipelines

Rules and steps for GitHub Actions CI workflows of Node/TypeScript repos.

## Intake

Before you pick a branch, run the intake script on the repo as one plain command: `python3 <skill folder>/scripts/intake.py <repo path>`, where `<skill folder>` is the full path of this skill folder. Add no `cd`, no `;`, no `&&` and no pipe to this command, and never put another command in the same call (a permission rule for the script matches only a command that starts with `python3` and the script path). It prints one JSON object. Read only this JSON for the repo facts. On the reply to a review report, you reuse the intake facts of the review in this conversation, and you run the intake script again only when none are in the conversation. Each fact has `value`, `status` (`detected`, `default` or `unknown`) and `source`. Name every fact with the status `default` or `unknown` in the report. With no network, the script reads the dated list of supported Node majors from [tools.md](tools.md), and the `installed_tools` fact says which of actionlint, zizmor and pinact are on PATH (see [tools.md](tools.md)).

## Pick the branch

Read the whole branch file with the Read tool, never only a part of it with a search: the parts that you need are at its end too.

- **Review** (the user asks to review or check CI): follow [review.md](review.md). When the user replies to a review report with a selection (`all`, `none`, a list or a range), follow "Fix on approval" in [review.md](review.md).
- **Create** (the user asks for a new CI workflow, CD workflows or both): follow [create.md](create.md). It asks the CD questions when they are open, picks the templates, fills them from the intake facts and ends with a self-review report.
- **Another edit** of a workflow file: read [rules/naming.md](rules/naming.md), [rules/job-graph.md](rules/job-graph.md), [rules/cost.md](rules/cost.md), [rules/security.md](rules/security.md) and [rules/maintainability.md](rules/maintainability.md), and also [rules/monorepo.md](rules/monorepo.md) when the intake finds a monorepo, and [rules/deploy.md](rules/deploy.md) and [rules/rollback.md](rules/rollback.md) when the repo has a deploy workflow, and [rules/release.md](rules/release.md), [rules/publish.md](rules/publish.md) and [rules/protect.md](rules/protect.md) under their own load rules (see "Loading by need"), and keep your edit consistent with them. Do not review the whole repo.

## Loading by need

The CI rule files (naming, job graph, cost, security and maintainability) load always. They apply to the CD workflow files too. The monorepo file loads only for a monorepo. Each CD rule file loads only when its rule below holds, and only when the file exists in `rules/`:

- `DEPLOY` and `ROLLBACK` ([rules/deploy.md](rules/deploy.md) and [rules/rollback.md](rules/rollback.md)): when the request names a deploy or a rollback, or the repo has a deploy workflow (the `existing_workflows` fact lists `deploy.yml`, or the `deploy_targets` fact has a value).
- `RELEASE` ([rules/release.md](rules/release.md)): when the request names a release, or the repo has a release tool or tag-driven releases: the `release_tool` fact has a value, the `existing_workflows` fact lists `release.yml`, or the `release_tag_pattern` fact has the status `detected` (a tag of a version shape exists).
- `PUBLISH` ([rules/publish.md](rules/publish.md)): when the intake finds a published package (the `package_kind` fact).
- `PROTECT` ([rules/protect.md](rules/protect.md)): with any CD rule file, or when the request is about branch protection, rulesets or environments.

## Modules

- [scripts/intake.py](scripts/intake.py): the intake script. It reads the repo files and makes read-only `gh api` calls. It reads the dated offline Node list from [tools.md](tools.md) when it has no network.
- [scripts/check_pins.py](scripts/check_pins.py): the SEC-01 pin check. It makes read-only `gh api` calls and tells whether each pinned SHA is the commit of its version comment tag.
- [scripts/protect_write.py](scripts/protect_write.py): the protection write script. `--read`, `--show` and `--apply` make every protection read and write of the protection step in "Fix on approval" in [review.md](review.md), with the `gh` CLI. Run it as one plain command (no `cd`, `;`, `&&` or pipe), as the intake script, so that a permission rule can match it. The main session runs it, never a subagent. It is the only way that the skill writes branch protection, rulesets or environments.
- [tools.md](tools.md): detection and install hints for actionlint, zizmor and pinact, the zizmor-to-SEC mapping, the output merge, the SHA lookup and the dated offline list of supported Node majors (the intake script reads this list with no network).
- [review.md](review.md): the review steps, the report contract and the fix-on-approval steps.
- [create.md](create.md): the create steps for CI and CD, the questions, the fill table (with the Terraform steps), and the Dependabot and `security-audit.yml` texts.
- [templates/single-package.yml](templates/single-package.yml) and [templates/monorepo.yml](templates/monorepo.yml): the two workflow templates that create mode fills.
- [templates/deploy.yml](templates/deploy.yml), [templates/release.yml](templates/release.yml) and [templates/rollback.yml](templates/rollback.yml): the three CD workflow templates (`Deploy`, `Release` and `Rollback`) for an AWS Lambda app. They call the repo scripts of `templates/scripts/`.
- `templates/scripts/`: the repo scripts that the CD templates call. `deploy-and-verify.sh` downloads the stored zip, checks its SHA-256 digest, deploys it (`DEPLOY_TARGET` is `lambda` or `terraform`) and checks the live version. Deploy and rollback share it. `check-staged.sh` fails unless the GitHub deployment record shows a successful staging deploy of the commit. The dry-run tests of the skill run both with fake `aws`, `gh`, `curl` and `terraform`.
- [scripts/check_workflow.py](scripts/check_workflow.py): the structural assertion script. It takes a workflow and assertions and returns pass or fail. The create evals and the unit tests use it.
- [scripts/grade_create_results.py](scripts/grade_create_results.py): the post-run grader of the create eval cases (structural assertions and the real actionlint).
- [rules/naming.md](rules/naming.md): NAME-01 to NAME-09. Each rule has an id, a default severity, the rule, its check and its fix.
- [rules/job-graph.md](rules/job-graph.md): GRAPH-01 to GRAPH-07 (jobs, `needs:`, matrices, shards, the build artifact, suite matrices).
- [rules/cost.md](rules/cost.md): COST-01 to COST-08 (triggers, concurrency, path filters, timeouts, installs, workers, runner labels, checkout depth).
- [rules/security.md](rules/security.md): SEC-01 to SEC-10 (SHA pins, Dependabot, permissions, `${{ }}` in `run:`, checkout credentials, submodule tokens, privileged triggers, `secrets: inherit`, caches, the dependency audit).
- [rules/monorepo.md](rules/monorepo.md): MONO-01 to MONO-02 (affected packages on PRs). Load it only for a monorepo, that is when the intake `monorepo` fact has `monorepo: true`.
- [rules/maintainability.md](rules/maintainability.md): MAINT-01 to MAINT-03 (long `run:` blocks, step comments, copied workflows).
- [rules/deploy.md](rules/deploy.md): DEPLOY-01 to DEPLOY-10 (build once, stages and environments, the digest check, OIDC roles, the version check, silent skips, the step-by-step rollout, docs-only pushes, CD timeouts, PR dry runs). Load it by the DEPLOY rule of "Loading by need".
- [rules/rollback.md](rules/rollback.md): ROLLBACK-01 to ROLLBACK-06 (the rollback workflow, no rebuild, durable artifacts, one target at a time, the native automatic rollback, the shared concurrency group). Load it by the ROLLBACK rule of "Loading by need".
- [rules/release.md](rules/release.md): RELEASE-01 to RELEASE-06 (one release tool, annotated tags on main, the tag ruleset, the release token and actor, the triggers, release notes). Load it by the RELEASE rule of "Loading by need".
- [rules/publish.md](rules/publish.md): PUBLISH-01 to PUBLISH-05 (npm trusted publishing, the frozen install with no cache, dependency order, a safe re-run, the `release.yml` name). Load it by the PUBLISH rule of "Loading by need".
- [rules/protect.md](rules/protect.md): PROTECT-01 to PROTECT-08 (the main ruleset, the tag ruleset, environment policies, prod reviewers, no admin bypass, classic protection that stacks with a ruleset, claimed protections, role ARNs and App keys per environment). Load it by the PROTECT rule of "Loading by need".
