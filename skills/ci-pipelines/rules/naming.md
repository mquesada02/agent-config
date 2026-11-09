# Naming rules (NAME-*)

Names for workflow files, workflows, jobs, steps and matrix legs. This file is the single source of truth for these rules. Both branches of the skill load it.

- "Mechanical" means a script or a regex can check the rule. "Judgement" means you decide.
- The severity is fixed for each rule. The first word of the Severity bullet is the level (`critical`, `required` or `suggestion`). A rule with mixed parts gives each part its own severity, and the report uses the severity of the part that failed.
- No naming rule is critical.

### NAME-01
- **Severity:** required
- **Rule:** Each workflow has a `name:`.
- **Check:** mechanical
- **Fix:** Add a top-level `name:` with the workflow's purpose in sentence case.

### NAME-02
- **Severity:** required
- **Rule:** The repo has one CI workflow, `.github/workflows/ci.yml`, with `name: CI`. Other workflows use a kebab-case purpose file name, and their `name:` is the same words in sentence case (`nightly-e2e.yml` gets `name: Nightly e2e`). `run-name:` is optional, and only manual or scheduled workflows use it.
- **Check:** mechanical
- **Fix:** Rename the file to `ci.yml` and set `name: CI`, or rename the other workflow file to its kebab-case purpose and set `name:` to the same words in sentence case.

### NAME-03
- **Severity:** required (case of the id); suggestion (one purpose)
- **Rule:** A job id is kebab-case and names one purpose: `lint`, `typecheck`, `test`, `build`, `ci-passed`.
- **Check:** case: mechanical. One purpose: judgement.
- **Fix:** Rename the job id to kebab-case, and to one word or phrase for its single purpose.

### NAME-04
- **Severity:** required
- **Rule:** A job `name:` is the job's purpose in short words. A name that lists several tasks ("Typecheck, lint, unit") is a finding, and the report says to split the job (the job graph rules come in a later version of this skill).
- **Check:** heuristic: a comma, " and ", "&" or "/" between verbs. Then judgement removes false positives.
- **Fix:** Name the job for its one purpose, and split a job that does several tasks into one job for each task.

### NAME-05
- **Severity:** required
- **Rule:** A matrix job's `name:` contains each matrix value that varies: `Test (node ${{ matrix.node }}, shard ${{ matrix.shard }}/4)`.
- **Check:** mechanical
- **Fix:** Add each varying matrix value to the job `name:` with `${{ matrix.<key> }}`.

### NAME-06
- **Severity:** required
- **Rule:** Each `run:` step has a `name:`. A `uses:` step can omit it, because the UI shows the action name.
- **Check:** mechanical
- **Fix:** Add a `name:` with a short imperative phrase to the step.

### NAME-07
- **Severity:** required (length and patterns); suggestion (verb phrase)
- **Rule:** A step name is an imperative verb phrase of 50 characters or less ("Run unit tests"). It has no ticket ids (`#123`, `ABC-123`), no versions (`v1.2.3`) and no reasons in parentheses.
- **Check:** length and patterns: mechanical. Verb phrase: judgement.
- **Fix:** Shorten the step name to an imperative verb phrase of 50 characters or less, and move ids, versions and reasons to the PR or the docs.

### NAME-08
- **Severity:** required (⚑ when a rename is needed)
- **Rule:** Each CI workflow has one gate job, `ci-passed` with `name: CI passed`. It has `needs:` on all the other jobs and `if: always()`, and it fails unless every `needs.*.result` is `success` (or `skipped` where a skip is intended). The gate is the only required status check.
- **Check:** mechanical
- **Fix:** Add a `ci-passed` job with `name: CI passed`, `needs:` on all other jobs and `if: always()`, and make `CI passed` the only required check (a repo admin does this by hand, so the finding gets ⚑).

### NAME-09
- **Severity:** suggestion
- **Rule:** Before a rename or a split, read the required checks from classic branch protection and from repository rulesets (rules of type `required_status_checks`), read-only. When a change touches a required check, mark the finding ⚑ and give the exact new check name, normally `CI passed`. Never edit branch protection. When `gh` cannot read the settings, say so, and treat every current job name as possibly required. A NAME-09 row is raised only when the settings cannot be read and the review proposes a rename or a split.
- **Check:** procedure (the read-only `gh api` GET calls of `review.md`)
- **Fix:** Tell the user in the ⚑ section which required checks to remove and which to add after the merge, and never write them yourself.
