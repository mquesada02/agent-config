# Cost rules (COST-*)

How a workflow spends runner minutes: triggers, concurrency, path filters, timeouts, installs, workers, runner labels and checkout depth. This file is the single source of truth for these rules. Both branches of the skill load it.

- "Mechanical" means a script or a regex can check the rule. "Judgement" means you decide. "Measured" means the rule reads measured run times of the intake.
- The severity is fixed for each rule. The first word of the Severity bullet is the level (`critical`, `required` or `suggestion`). A rule with mixed parts gives each part its own severity, and the report uses the severity of the part that failed. A measured finding is always a suggestion.
- No cost rule is critical.

### COST-01
- **Severity:** required
- **Rule:** CI triggers are `push: branches: [main]` and `pull_request`, so a PR branch never runs twice. A `push:` with no `branches:` filter is a finding.
- **Check:** mechanical
- **Fix:** Set the triggers to `push` with `branches: [main]` and to `pull_request`.

### COST-02
- **Severity:** required
- **Rule:** The CI workflow has a `concurrency` block: `group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}` and `cancel-in-progress: ${{ github.event_name == 'pull_request' }}`. A new push to a PR cancels the old run. Main keeps one result per commit.
- **Check:** mechanical
- **Fix:** Add a top-level `concurrency` block with the group and the `cancel-in-progress` expression of this rule.

### COST-03
- **Severity:** required
- **Rule:** A workflow that has the gate job (NAME-08) has no workflow-level `paths` or `paths-ignore`. To skip work, a first `changes` job uses `dorny/paths-filter` (SHA-pinned, `pull-requests: read`, no checkout on PRs) and gives outputs such as `code` and `docs_only`. Each heavy job has `if: needs.changes.outputs.code == 'true'`. The gate accepts `skipped` for jobs that have such an `if:`.
- **Check:** mechanical
- **Fix:** Remove the workflow-level `paths` and `paths-ignore`, add a `changes` job with `dorny/paths-filter`, and put `if: needs.changes.outputs.code == 'true'` on each heavy job.

### COST-04
- **Severity:** required (a missing `timeout-minutes`), suggestion (measured: a timeout more than 2× above the proposed value)
- **Rule:** Every job sets `timeout-minutes`. Create mode uses these values: `changes` and the gate get 5, lint, typecheck and build get 10, and test gets 15 (per shard). Review mode reads the median duration of the job over the last 10 successful runs and proposes `max(5, ceil(3 × median))`. A missing timeout is a finding. A timeout more than 2× above the proposed value is also a finding.
- **Check:** mechanical + measured: `m` is the largest `median_seconds` of the `run_history` entries that belong to the job (its `name:`, or the names that its matrix expands to, such as `Test (node 22)`), divided by 60, and the proposal is `max(5, ceil(3 × m))`. A timeout of exactly 2× the proposal is no finding, and a job with no `run_history` entry gets no measured finding. With the `run_history` status `unknown`, the review uses the create values for the missing-timeout part and gives no measured finding.
- **Fix:** Set `timeout-minutes` on every job to the create value or, with a measured history, to `max(5, ceil(3 × m))`.

### COST-05
- **Severity:** required
- **Rule:** Each job installs from the frozen lockfile: `npm ci`, `pnpm install --frozen-lockfile` or `yarn install --immutable`. Only the package manager store is cached, with the `actions/setup-node` `cache:` input. For pnpm, `pnpm/action-setup` runs first and takes the version from `packageManager`. The skill never caches `node_modules`, and it never caches Playwright browsers, because the Playwright docs advise against it. A repo with no lockfile is a finding. A tool that a job installs on each run (for example `pipx install x`) uses a pinned version and a cache, or it moves to a dev dependency.
- **Check:** mechanical
- **Fix:** Install with the frozen-lockfile command of the package manager, cache only the package manager store through `actions/setup-node`, and remove any cache of `node_modules` or Playwright browsers.

### COST-06
- **Severity:** required
- **Rule:** A test worker setting is never above the runner's vCPU count. The setting is Vitest `--maxWorkers` / `VITEST_MAX_WORKERS`, Jest `--maxWorkers`, or Playwright `workers`. The vCPU count is 2 for a private repo and 4 for a public repo on standard Linux runners. For self-hosted runners and larger runners, the intake gives the size. Playwright uses `workers: 1` in CI, and sharding adds the parallelism. Self-hosted runners are in scope.
- **Check:** mechanical with the intake facts: `visibility` and `runner_labels` (the `vcpus` of each label). When the repository visibility is not readable, the intake gives `visibility` the value `private` with the status `default`, so the vCPU count is 2. A Playwright `workers` value above 1 in CI is a finding.
- **Fix:** Set each test worker setting to the vCPU count of the runner or lower, and set the Playwright `workers` to 1 in CI.

### COST-07
- **Severity:** required
- **Rule:** Runner labels are pinned (`ubuntu-24.04`, not `ubuntu-latest`). A macOS or Windows runner is used only when GRAPH-03 promises that OS.
- **Check:** mechanical
- **Fix:** Replace each floating runner label with a pinned label such as `ubuntu-24.04`, and remove each macOS or Windows runner that GRAPH-03 does not promise.

### COST-08
- **Severity:** required
- **Rule:** `actions/checkout` keeps the default `fetch-depth: 1`. It uses `fetch-depth: 0` only when a step needs the history (MONO-01, MONO-02, or a `changes` script that uses git).
- **Check:** mechanical. A checkout with `fetch-depth: 0` in a job of a PR run is never a COST-08 finding when MONO-01 or MONO-02 applies: the `monorepo` fact has the tool `turbo`, `nx` or `pnpm`, or the workflow runs the pnpm filter. MONO-01 and MONO-02 cover every PR-run job of that repo: each job needs `fetch-depth: 0` for its affected-only command, so the review gives no second fix for the same line. A job that runs only on a push to main is still a COST-08 finding, because a full run needs no history.
- **Fix:** Remove `fetch-depth: 0` from each checkout whose job no MONO-01 or MONO-02 rule covers and runs no script that reads the git history, and keep it in a job that MONO-01 or MONO-02 covers.
