# Deploy rules (DEPLOY-*)

How a deploy workflow (`deploy.yml`) builds once, promotes one artifact through its stages, gets cloud access, checks the result and limits its jobs. This file is the single source of truth for these rules. Both branches of the skill load it by need (see "Loading by need" in [SKILL.md](SKILL.md)).

- "Mechanical" means a script or a regex can check the rule. "Judgement" means you decide. "Measured" means the rule reads measured run times of the intake.
- The severity is fixed for each rule. The first word of the Severity bullet is the level (`critical`, `required` or `suggestion`). A rule with mixed parts gives each part its own severity, and the report uses the severity of the part that failed. A measured finding is always a suggestion.
- No deploy rule is critical. The SEC rules cover the exploitable security problems in CD files.

### DEPLOY-01
- **Severity:** required
- **Rule:** Build once. The deploy jobs use the artifact of the build job. No install or build step runs in a deploy job.
- **Check:** mechanical: a deploy job has no install step (`npm ci`, `pnpm install`, `yarn install`) and no build step (`pnpm build`, `npm run build`, `tsc`).
- **Fix:** Remove the install and build steps from each deploy job and make the job download the artifact that the build job stored.

### DEPLOY-02
- **Severity:** required
- **Rule:** Each stage has its own `environment:` (dev, staging, prod). The prod job `needs` the earlier stage. When prod runs in a tag run and staging in the push run, the staging-record check replaces `needs`, and this rule accepts it: the check is a step of the prod job whose `run:` calls the repo script `scripts/check-staged.sh` with the commit SHA, and the script fails when the GitHub deployment record shows no successful staging deploy of that SHA.
- **Check:** mechanical: each deploy job sets `environment:` with its own stage name, and the prod job either lists the earlier stage in `needs` or has the staging-record check step. A prod job with the staging-record check and no `needs` is no finding.
- **Fix:** Give each deploy job its own `environment:` (dev, staging or prod) and make the prod job `need` the staging job, or, in a tag run, add a step that runs `scripts/check-staged.sh` with the commit SHA.

### DEPLOY-03
- **Severity:** required
- **Rule:** Prod deploys only the staged artifact. A digest check (SHA-256) proves this: the deploy job downloads the artifact with its `.sha256` file and calls the deploy script that compares the digest before it deploys.
- **Check:** mechanical: the prod deploy job downloads an artifact and its `.sha256` file and runs a digest check (`sha256sum` or a deploy script that calls it) before the deploy step.
- **Fix:** Store a `.sha256` file with the artifact in the build job, download both in the prod deploy job and compare the digest with `sha256sum` before the deploy step.

### DEPLOY-04
- **Severity:** required (a long-lived AWS key), suggestion (a role ARN typed into the YAML)
- **Rule:** AWS access uses OIDC with one role for each environment. The role is assumed only in jobs that run no install and no build: the `package` job (the `artifacts` role, for the upload), the deploy jobs and the rollback jobs. A long-lived AWS key (`aws-access-key-id`, or `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` in a secret) is a required finding. A role ARN typed into the YAML is a suggestion finding: the ARN belongs in a variable (for example `vars.AWS_ROLE_PROD`), so that the account id stays out of the file.
- **Check:** mechanical: a job with `id-token: write` and `role-to-assume:` has no install or build step, a job has no `aws-access-key-id` input and no AWS key secret, and a `role-to-assume:` value is a `vars.` expression, not an `arn:aws:iam::` literal.
- **Fix:** Replace the AWS key with `role-to-assume: ${{ vars.AWS_ROLE_<ENV> }}` and `id-token: write` on a job that runs no install and no build, with one role for each environment.

### DEPLOY-05
- **Severity:** required
- **Rule:** A check after the deploy confirms the deployed version (a header, the body or a version endpoint), not only an HTTP status. If the check fails, the job fails. A check that tests only a status code passes an old version that still answers 200.
- **Check:** mechanical: the deploy job, or a repo script that it calls, has a check after the deploy that compares the live version with the commit SHA and exits non-zero on a mismatch.
- **Fix:** Add a check after the deploy that fetches the version endpoint, compares the result with the commit SHA (with retries) and fails the job when the live version is old.

### DEPLOY-06
- **Severity:** required
- **Rule:** No silent skip. When a deploy cannot run because a setting is missing (an empty variable, a missing secret or an unset role), the job writes a notice and fails. A job that exits with success because a variable is empty is a finding. A docs-only skip is an intended skip (DEPLOY-08), not a finding of this rule.
- **Check:** mechanical: a deploy job has no `if:` or shell test that skips the deploy when a variable or secret is empty and then succeeds.
- **Fix:** Replace the skip on an empty setting with a step that writes an error notice (`::error::`) and exits with a non-zero status.

### DEPLOY-07
- **Severity:** suggestion
- **Rule:** The deploy uses the native step-by-step rollout of its target, with alarms: a Lambda weighted alias or CodeDeploy, ECS blue/green, or a CloudFront staging distribution, so that a bad version reaches few users first.
- **Check:** judgement: the target of the deploy has a native step-by-step rollout and the deploy step switches all traffic at once.
- **Fix:** Use the native step-by-step rollout of the target (for example a Lambda weighted alias with CodeDeploy) with alarms that stop the rollout.

### DEPLOY-08
- **Severity:** required
- **Rule:** A push to main that changes only docs runs CI, so the gate stays green. The deploy jobs skip with a notice, based on the `changes` output of the called `ci.yml`. A deploy that runs on a docs-only push is a finding. The skip is intended, so it is never a DEPLOY-06 finding. The deploy trigger has no docs path filter (COST-03).
- **Check:** mechanical: the deploy jobs have an `if:` on the `code` output of the `changes` job, and a `skip-notice` job (or a notice step) runs when that output is not `true`.
- **Fix:** Add `if: needs.ci.outputs.code == 'true'` to each deploy job and a `skip-notice` job that writes a notice when the push changed only docs.

### DEPLOY-09
- **Severity:** required (a missing `timeout-minutes`), suggestion (measured: a timeout more than 2× the proposed value)
- **Rule:** Timeouts are the CD part of COST-04. Every job of `deploy.yml`, `release.yml` and `rollback.yml` sets `timeout-minutes`. A job that calls a reusable workflow (`uses:` at job level, such as the `ci` job of `deploy.yml`) cannot set it, so it is exempt, and the jobs of the called `ci.yml` keep their own timeouts. Create mode uses 30 minutes for a deploy job, 10 for a separate verification job, 15 for a release job and 30 for a rollback job, 10 for the `package` job and 5 for the `skip-notice` job. A timeout is never above the OIDC role session (60 minutes by default). Review mode reads the median duration of the job over the last 10 successful runs in the `deploy_history` fact and proposes `min(session, max(5, ceil(3 × m)))` minutes, where `m = median_seconds / 60` with no rounding before the `ceil` and `session` is the OIDC role session in minutes. A missing timeout is a finding. A timeout more than 2× the proposal is also a finding.
- **Check:** mechanical + measured: `m` is the largest `median_seconds` of the `deploy_history` entries that belong to the job (its `name:`), divided by 60. A timeout of exactly 2× the proposal is no finding, and a job with no `deploy_history` entry gets no measured finding. With the `deploy_history` status `unknown`, the review uses the create values for the missing-timeout part and gives no measured finding.
- **Fix:** On every job except a job that calls a reusable workflow, set `timeout-minutes` to the create value of its kind or, with a measured history, to `min(session, max(5, ceil(3 × m)))`.

### DEPLOY-10
- **Severity:** suggestion
- **Rule:** When the target has a native preview (`cdk diff`, `terraform plan`, a CloudFormation change set, the Lambda action dry-run), a PR runs the deploy as a dry run, so that the deploy is tested before the merge.
- **Check:** judgement: the target has a native preview and no workflow runs it on a PR.
- **Fix:** Add a PR job that runs the native preview of the target (for example `terraform plan`) with no write permission to the environment.
