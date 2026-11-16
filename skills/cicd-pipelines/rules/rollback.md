# Rollback rules (ROLLBACK-*)

How a rollback workflow (`rollback.yml`) goes back to an older release: a dispatch on an older final tag that never builds, keeps the deploy checks, uses durable artifacts and shares the concurrency group of the deploy. This file is the single source of truth for these rules. Both branches of the skill load it by need (see "Loading by need" in [SKILL.md](SKILL.md)).

- "Mechanical" means a script or a regex can check the rule. "Judgement" means you decide. "Measured" means the rule reads measured run times of the intake.
- The severity is fixed for each rule. The first word of the Severity bullet is the level (`critical`, `required` or `suggestion`).
- No rollback rule is critical. The SEC rules cover the exploitable security problems in CD files.

### ROLLBACK-01
- **Severity:** required
- **Rule:** When `deploy.yml` exists, `rollback.yml` exists too. Its only trigger is `workflow_dispatch`, and a rollback job runs only for a tag ref (`github.ref_type == 'tag'`), so that the version comes from the ref and never from a free-text input. A final tag has no pre-release suffix. The check does not read which tag is older, because the person who dispatches chooses it. A dispatch input that holds a version is a finding: an input of `type: string`, or any input whose name has `version`, `tag` or `ref`. An environment choice input (`type: choice`) is allowed.
- **Check:** mechanical: `rollback.yml` exists when `deploy.yml` exists, its only trigger is `workflow_dispatch`, each rollback job has `if: github.ref_type == 'tag'`, and no dispatch input holds a version. A missing file is reported with the file name `rollback.yml` as its location.
- **Fix:** Add `rollback.yml` with a `workflow_dispatch` trigger, an environment choice input and a job that runs only for a tag ref and takes the version from the ref.

### ROLLBACK-02
- **Severity:** required
- **Rule:** A rollback never builds. It reuses the stored artifact of the tag, or the previous version on the target, and it keeps every deploy check: the digest check of DEPLOY-03 and the version check of DEPLOY-05. A rollback job passes when it runs the same deploy script as the deploy jobs (that script holds both checks), or when it runs both checks itself. A rollback job whose deploy step has neither is a finding. DEPLOY-01 covers `deploy.yml` only, so a rollback job that builds is a ROLLBACK-02 finding and no DEPLOY-01 finding.
- **Check:** mechanical: a rollback job has no install step (`npm ci`, `pnpm install`, `yarn install`) and no build step (`pnpm build`, `npm run build`, `tsc`), and its deploy step calls the same deploy script as the deploy jobs or runs a digest check and a version check itself.
- **Fix:** Remove the install and build steps from the rollback job and make it download the stored artifact of the tag and run the deploy script with its digest and version checks.

### ROLLBACK-03
- **Severity:** required
- **Rule:** The rollback artifacts outlive the retention of run artifacts (1 to 90 days). They are kept in S3 with versioning, in a registry, or as Lambda versions. The job that stores the deploy artifact writes it to S3 under the commit SHA, to a registry, or as a Lambda version. The S3 key holds the commit SHA, so a new deploy never overwrites it. The review cannot read the versioning setting of the bucket, so it does not check it. A job that stores the artifact only with the run-artifact action (`actions/upload-artifact`) is a finding.
- **Check:** mechanical: the job that stores the deploy artifact writes it to S3 (`aws s3 cp` or `aws s3 sync`, with the commit SHA in the key), pushes it to a registry or publishes a Lambda version, and not only to `actions/upload-artifact`.
- **Fix:** Store the zip and its `.sha256` file in the S3 artifact bucket under the commit SHA (or push the image to a registry, or publish a Lambda version) and make the rollback read from there.

### ROLLBACK-04
- **Severity:** suggestion
- **Rule:** A prod rollback of several targets deploys them one at a time, so that a bad rollback stops early. A target is a prod target when its job has `environment: prod`, or when its job takes the environment from a choice input whose `options` include `prod`. Several targets are a matrix with more than one value, or several rollback jobs. A matrix sets `max-parallel: 1`. Several jobs are chained with `needs`. The fix does not set `fail-fast`, because GRAPH-04 owns that key.
- **Check:** judgement: a rollback has several prod targets and its matrix has no `max-parallel: 1`, or its jobs are not chained with `needs`.
- **Fix:** Add `max-parallel: 1` under `strategy:` of the rollback matrix, or chain the rollback jobs of the targets with `needs`.

### ROLLBACK-05
- **Severity:** suggestion
- **Rule:** The rollback uses the native automatic rollback of its target where one exists. The finding is one of these three forms, and nothing else is a finding: a CloudFormation or CDK step with `--disable-rollback` or `--no-rollback` (the CloudFormation rollback is on by default, so a step with no flag passes); an ECS deploy step whose deployment configuration turns the circuit breaker rollback off; a CodeDeploy `create-deployment` step with no `--auto-rollback-configuration`, or with that configuration disabled. A target with no native automatic rollback (for example a Lambda alias or an S3 bucket) gets no finding.
- **Check:** judgement: a rollback step matches one of the three forms of the rule.
- **Fix:** Remove the flag that turns the native rollback off, or set the automatic rollback of the target (the CloudFormation default, the ECS circuit breaker with rollback on, or the CodeDeploy `--auto-rollback-configuration`).

### ROLLBACK-06
- **Severity:** required
- **Rule:** A rollback uses the same concurrency group as the deploy to that environment, so that a deploy and a rollback never write to one environment at once. Each rollback job has job-level `concurrency.group` equal to the group of the deploy job of the same environment (`deploy-<env>`, and `deploy-${{ inputs.environment }}` for the choice input) and `cancel-in-progress: false`. COST-02 owns the deploy group form. A rollback job with no group is a finding, and so is a rollback job with another group name.
- **Check:** mechanical: each rollback job has a job-level `concurrency.group` that equals the group of the deploy job of its environment, and `cancel-in-progress: false`.
- **Fix:** Set job-level `concurrency: { group: deploy-${{ inputs.environment }}, cancel-in-progress: false }` on each rollback job, with the group name of the deploy job of the same environment.
