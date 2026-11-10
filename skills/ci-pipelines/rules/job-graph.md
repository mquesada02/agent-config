# Job graph rules (GRAPH-*)

How the jobs of a workflow split, depend on each other, fan out in a matrix and share a build. This file is the single source of truth for these rules. Both branches of the skill load it.

- "Mechanical" means a script or a regex can check the rule. "Judgement" means you decide. "Measured" means the rule reads measured run times of the intake.
- The severity is fixed for each rule. The first word of the Severity bullet is the level (`critical`, `required` or `suggestion`). A measured finding is always a suggestion.
- No job graph rule is critical.
- The gate job (NAME-08) needs every job above, and it stays the only required check.

### GRAPH-01
- **Severity:** required
- **Rule:** Each independent check (lint, typecheck, test, build) is its own job. Independent jobs have no `needs:` between them, so they run in parallel. Cost: about 1 to 3 extra runner-minutes per run. This is accepted.
- **Check:** mechanical: a job that runs more than one of these checks
- **Fix:** Split the job into one job for each check, with no `needs:` between them, and add each new job to the `needs:` of the gate job.

### GRAPH-02
- **Severity:** suggestion
- **Rule:** A `needs:` edge exists only for a real dependency: the job uses an output or an artifact of the other job, or the order is required (for example, deploy after test). An edge with no such use is a finding.
- **Check:** judgement, helped by output/artifact use
- **Fix:** Remove the `needs:` edge that has no output, artifact or required order behind it.

### GRAPH-03
- **Severity:** required
- **Rule:** Matrix breadth follows the repo's own promises. A published package tests each Node major in its `engines` range that upstream still supports. An app tests one Node version, read from `.nvmrc`, `.node-version`, `packageManager` or `engines`. OS legs exist only when the package claims OS support (for example `os` in package.json). Only the `test` job has the matrix; lint, typecheck and build run once. A leg with no promise behind it is a finding.
- **Check:** mechanical with the intake facts: `package_kind` (published or app), `engines` (the `engines.node` range of each package), `supported_node_majors` (the Node majors that upstream supports), `node_version_app` (the one Node version of an app) and `os_claims` (the OS values that a package claims). An `engines` entry with the status `default` (no `engines.node`) counts as the newest LTS only, so a published package with such an entry expects one Node leg. When `node_version_app` is a range (for example `>=20`), the one expected app version is the newest major in `supported_node_majors` that the range allows. Shards (GRAPH-05) and suite matrices (GRAPH-07) are matrices of a test job, and they are not a finding of this rule.
- **Fix:** Remove the matrix from the lint, typecheck and build jobs, and cut the Node and OS legs of the test job to the versions and systems that the intake facts promise.

### GRAPH-04
- **Severity:** required
- **Rule:** A matrix uses `fail-fast: ${{ github.event_name == 'pull_request' }}`. On a PR the other legs stop at the first failure. On main every leg finishes. Shards use the same rule.
- **Check:** mechanical
- **Fix:** Set `fail-fast: ${{ github.event_name == 'pull_request' }}` under `strategy:` of each matrix job.

### GRAPH-05
- **Severity:** suggestion (measured)
- **Rule:** Review mode reads the median duration of the `test` job over the last 10 successful runs (the `run_history` fact of the intake). Above 10 minutes, it proposes `ceil(minutes / 8)` shards, at most 8, with a merge job for the reports (Vitest blob reporter + `--merge-reports`, Playwright blob + `merge-reports`, Jest `--shard`). Create mode starts with no shards. With no run history, there is no sharding finding.
- **Check:** measured: `m` is the largest `median_seconds` of the `run_history` jobs that belong to the `test` job of `ci.yml` (its `name:`, or the names that its matrix expands to, such as `Test (node 22)`), divided by 60. The number of shards is `ceil(m / 8)`, at most 8. With the `run_history` status `unknown`, or when the `test` job is in another workflow file, there is no finding.
- **Fix:** Add a shard matrix to the test job with `ceil(m / 8)` shards (at most 8) and a merge job for the reports.

### GRAPH-06
- **Severity:** required
- **Rule:** The `build` job builds once and uploads its output (`dist/`) with `upload-artifact` and `retention-days: 1`. A job that needs the output declares `needs: build` and downloads it. A second build of the same output in one run is a finding.
- **Check:** mechanical: the build command appears in more than one job
- **Fix:** Upload the build output from the `build` job with `retention-days: 1`, and make the other job declare `needs: build` and download the artifact instead of building again.

### GRAPH-07
- **Severity:** required
- **Rule:** A job with more than 5 steps that run independent suites with the same setup becomes one matrix job over a suite list (`matrix.suite`). Each leg runs one script. Short suites can share a leg, so each leg runs for at least about 2 minutes.
- **Check:** count: mechanical. Independence: judgement
- **Fix:** Replace the suite steps with one matrix job over `matrix.suite`, where each leg runs one script and short suites share a leg of about 2 minutes or more.
