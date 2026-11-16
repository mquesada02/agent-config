# Security rules (SEC-*)

How a workflow handles actions, tokens, permissions, untrusted input, privileged triggers, caches and the dependency audit. This file is the single source of truth for these rules. Both branches of the skill load it.

- "Mechanical" means a script or a regex can check the rule. "Judgement" means you decide.
- The severity is fixed for each rule. The first word of the Severity bullet is the level (`critical`, `required` or `suggestion`). A rule with mixed parts gives each part its own severity, and the report uses the severity of the part that failed.
- SEC-04, SEC-06 and SEC-07 have critical parts. Every other part of every SEC rule is required.
- A zizmor finding that maps to a SEC id (see [tools.md](../tools.md)) takes the severity of the SEC rule part that it fits.

### SEC-01
- **Severity:** required
- **Rule:** Every `uses:` pins a full 40-character commit SHA with a bare version comment: `@<sha> # v5.0.0`. This applies to `actions/*` and to reusable workflows from other repos too. Local `./` actions are exempt. The check has two parts. The form: a 40-character hexadecimal SHA and a version comment. The commit: the SHA is the commit that the tag of the version comment points to. The commit part is the `check_pins.py` script (see "Check the pins" in tools.md). A pin with the result `tag-mismatch`, `unknown-tag` or `unknown-commit` is a finding. A pin with the result `unverified` is never a finding. To get the SHA for a tag, the skill uses `pinact run` when pinact is installed. Otherwise it uses `gh api repos/<owner>/<repo>/git/ref/tags/<tag>`, and it dereferences annotated tags to their commit.
- **Check:** mechanical
- **Fix:** Replace each tag in `uses:` with the full commit SHA and a bare version comment, and replace each SHA that is not the commit of its version comment tag, getting the SHA as the "Pin a SHA" section of tools.md says.

### SEC-02
- **Severity:** required
- **Rule:** The repo has `.github/dependabot.yml` with a `github-actions` entry (`directory: /`, weekly schedule), so the pins get update PRs. Create mode adds the file. In review mode, a missing entry is a finding.
- **Check:** mechanical
- **Fix:** Add `.github/dependabot.yml` with a `github-actions` entry that has `directory: /` and a weekly schedule.

### SEC-03
- **Severity:** required
- **Rule:** At the top level, the workflow has `permissions: contents: read`. A job that needs more scopes lists its own `permissions` block. Each write scope is at job level only and has a one-line reason comment. A missing top-level block is a finding. A write scope at the top level is also a finding. This matches the OpenSSF Scorecard Token-Permissions check.
- **Check:** mechanical
- **Fix:** Add a top-level `permissions: contents: read` block and move each write scope into the `permissions` block of the job that needs it, with a one-line reason comment.

### SEC-04
- **Severity:** critical (an untrusted context in `run:`), required (any other `${{ }}` in `run:`, such as `matrix.*`)
- **Rule:** A `run:` block never contains `${{ ... }}`. Every value goes through `env:` and is used as `"$VAR"`. This includes secrets, `github.event.*`, `github.head_ref`, inputs and matrix values. The rule has no allowlist.
- **Check:** mechanical. The untrusted contexts are the `github.event.*` fields that hold free text (titles, bodies, messages, branch names, labels), `github.head_ref`, `inputs.*` and `secrets.*`. Every other `${{ }}` in a `run:` block, such as `matrix.*`, `github.sha` or `github.run_id`, is the required part. A workflow that has both gets one row in each severity table.
- **Fix:** Move each `${{ }}` value out of the `run:` block into an `env:` entry of the step and use it there as `"$VAR"`.

### SEC-05
- **Severity:** required
- **Rule:** Every `actions/checkout` sets `persist-credentials: false`. The exception is a job where a later step pushes with git. That checkout has a one-line reason comment.
- **Check:** mechanical
- **Fix:** Set `persist-credentials: false` under `with:` of each `actions/checkout` step, or add a one-line reason comment where a later step pushes with git.

### SEC-06
- **Severity:** critical
- **Rule:** Private submodules use `actions/checkout` with `submodules: recursive` and a `token:`. The preferred token comes from `actions/create-github-app-token`. A token in a git URL, or written into the git config by a `run:` step, is a finding.
- **Check:** mechanical
- **Fix:** Remove the token from the git URL or the git config and give `actions/checkout` `submodules: recursive` and a `token:` from `actions/create-github-app-token`.

### SEC-07
- **Severity:** critical (a checkout of the PR head ref or SHA under `pull_request_target` or `workflow_run`), required (the plain use of one of these triggers)
- **Rule:** Create mode never uses `pull_request_target` or `workflow_run`. In review mode, each use is a finding. A checkout of the PR head ref or SHA under these triggers is a **critical** finding (the "pwn request"). The report prototype ticket defines the severity scale.
- **Check:** mechanical. The PR head is `github.event.pull_request.head.sha`, `github.event.pull_request.head.ref`, `github.head_ref`, `github.event.workflow_run.head_sha` or `github.event.workflow_run.head_branch` as the `ref:` of a checkout. A workflow that has both parts gets a row in each severity table.
- **Fix:** Remove the `pull_request_target` or `workflow_run` trigger and run the job on `pull_request`, and never check out the PR head under a privileged trigger.

### SEC-08
- **Severity:** required
- **Rule:** A CI job gets only the secrets that it names. `secrets: inherit` to a reusable workflow is a finding.
- **Check:** mechanical
- **Fix:** Replace `secrets: inherit` with a `secrets:` map that names only the secrets the reusable workflow needs.

### SEC-09
- **Severity:** required
- **Rule:** A workflow with a privileged trigger (SEC-07) saves no cache. This blocks cache poisoning.
- **Check:** mechanical
- **Fix:** Remove the cache from each workflow that has a privileged trigger, such as `cache:` on `actions/setup-node` or an `actions/cache` step.

### SEC-10
- **Severity:** required
- **Rule:** The dependency audit (`npm audit`, `pnpm audit` or `yarn npm audit`) runs in its own `audit` job, with `--audit-level=high`. On PRs it runs only when the lockfile changes (a `changes` job output, see COST-03), and it is part of the gate. A weekly scheduled workflow, `security-audit.yml`, also runs the audit on main. Its cron uses an odd minute. An audit step inside another job is a finding. A gate check that fails when `audit` is `skipped` is also a finding. A gate check that already accepts a skipped `audit` is no finding, even when it also accepts `skipped` for other jobs.
- **Check:** mechanical
- **Fix:** Move the audit step into its own `audit` job with `--audit-level=high` that runs on PRs only when the lockfile changes, remove the old audit step from the other job, add a first `changes` job whose filter step has the exact line `uses: dorny/paths-filter@ceb8a2b8f2d89434be7ff52d3de7ec3738c5cc9d # v4.0.3` of the create templates (never a SHA that you wrote yourself) and a `lockfile` output when the workflow has none, put `audit` in the `needs` of the gate, and, when the gate check fails a skipped `audit`, change it to `echo "$RESULTS" | jq -e 'all(to_entries[]; .value.result == "success" or (.key == "audit" and .value.result == "skipped"))'` (in a report table, write each pipe as `\|`) so that only `audit` may be `skipped` and every other job must be `success` (a job with a COST-03 `if:` skip gets its own `.key == "<job id>"` clause the same way, never a general skip), and add a weekly `security-audit.yml` with `cron: '17 6 * * 1'` (an odd minute, so the run does not start on the hour).
