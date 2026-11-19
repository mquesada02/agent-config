# Create steps

Create a CI workflow, the CD workflows (deploy, release and rollback), or both for a repo from templates, with every rule applied and the intake facts filled in. The result passes actionlint where actionlint is installed, and its self-review has no critical and no required finding.

Read only the intake JSON (see [SKILL.md](SKILL.md)) for the repo facts. The one exception is step 5: it reads the Dependabot file and `security-audit.yml` with the Read and Glob tools, as SEC-02 does in the review steps. Step 5 also copies the two repo scripts of [templates/scripts/](templates/scripts/) for a CD request, which is a second exception. Create mode never writes branch protection, rulesets or environments: the write belongs to the fix flow of [review.md](review.md), through `scripts/protect_write.py --apply` after the 2-step approval.

## Questions

Ask before step 1, and ask nothing else. A CI-only request asks no question.

- When the request does not say CI, CD or both, ask "CI, CD or both?" and wait.
- For a CD request, decide the deploy target in this order: the target that the request names; else the one target that the facts show; else ask for the deploy target. The `deploy_targets` kind `lambda` shows AWS Lambda, and the `iac_tools` value `terraform` shows Terraform. The `deploy_targets` kinds `s3`, `cloudfront`, `ecs`, `container-registry`, `github-pages`, `cloudflare`, `vercel` and `netlify` each show a target with no template. The kind `aws` alone shows nothing, and so does every other `iac_tools` kind (`opentofu`, `cdk`, `pulumi`, `serverless`, `sam`, `cloudformation`). When the facts show exactly one target, it is the target. With none, or with two or more, ask. A request that names two targets also gets the question. A target that the request names wins over the facts, and the `## Created` section names both when they differ.

## Steps

1. Run the intake through the router and read its JSON. "A CI file" is `.github/workflows/ci.yml` or `.github/workflows/ci.yaml` in the `existing_workflows` fact (`ci.yml` when both exist). "A CD request" is the answer CD or both. A target has a template only when it is AWS Lambda or Terraform. Apply these rules in order:
   - When the `package_manager` fact has `lockfile: null`, write nothing, say that a lockfile is needed first and name the rule id `COST-05` in that sentence, and offer a review.
   - A CI-only request with a CI file: write nothing, say that a CI workflow exists, and offer a review ([review.md](review.md)).
   - A CD request when no CD file can be written: write no CD file. This holds when the target has no template (S3 with a CDN, a signed S3 bundle and every other target), and when no package has a `build` script in the `scripts` fact (the `build` job and its `dist` upload would be removed, and the `package` job of `deploy.yml` downloads `dist`). Say which cause holds. Say that no template exists for the target, or that a build script is needed first and name the rule id `DEPLOY-01`. For "both", go on as a CI-only request (the previous rule for the CI half, and a `ci.yml` with no CD part when no CI file exists). For CD alone, offer a review of the existing workflows, or say that there is nothing to review.
   - A CD request with a template: for each of `deploy`, `release` and `rollback` that the `existing_workflows` fact lists as `.github/workflows/<name>.yml` or `.github/workflows/<name>.yaml`, write nothing for that file (neither form) and offer a review of it. Write each CD file that does not exist.
   - A CD request with a template and no CI file (whichever CD files exist): also write `ci.yml` with the CD part, and the Dependabot and `security-audit.yml` files of step 5.
   - A CD request with a template and a CI file (even for "both"): say that a CI workflow exists, and write no `ci.yml`, no Dependabot file and no `security-audit.yml`. When the CI file lacks the CD part, the final message holds report rows and no file is edited. One row names the rule COST-01 (CD part) when the file has a `push` trigger, has no `workflow_call` trigger, or has a `workflow_call` trigger with no `code` output. One row names the rule GRAPH-06 when its `build` job has no `dist` upload. Each row has the severity of its rule and the reply grammar of the review report ([review.md](review.md)). The fix-on-approval flow edits the CI file after the owner approves.
2. Pick the template. Use [templates/monorepo.yml](templates/monorepo.yml) when the `monorepo` fact has `monorepo: true`. Otherwise use [templates/single-package.yml](templates/single-package.yml). A CD request with a template also picks [templates/deploy.yml](templates/deploy.yml), [templates/release.yml](templates/release.yml), [templates/rollback.yml](templates/rollback.yml) and [templates/scripts/](templates/scripts/). The CI template holds marked CD part blocks (each starts with a `# cd-part:start` line and ends with a `# cd-part:end` line). Keep each block without its two marker lines, and remove the `push:` trigger (the lines `push:` and `branches: [main]`), only when step 1 gives a CD request with a template and no CI file. In every other run that writes `ci.yml`, remove each block with its marker lines, so the file is the CI-only file.
3. Fill the template from the intake facts with the fill table below. Change only the values that the table names. Keep the job ids, the job names, the `timeout-minutes` values, the pins and the job graph (the Terraform steps are the only change of steps in the CD templates). When the table removes a job, remove it from the `needs:` of `ci-passed` too, and name the removed job and the reason in the `## Created` section. For the CD templates, the package manager row also fills `release.yml` (the `Set up pnpm` step, the install command and the command of `publish:`), and the CD rows of the fill table apply.
4. Load and apply every rule file: [rules/naming.md](rules/naming.md), [rules/job-graph.md](rules/job-graph.md), [rules/cost.md](rules/cost.md), [rules/security.md](rules/security.md) and [rules/maintainability.md](rules/maintainability.md). Load [rules/monorepo.md](rules/monorepo.md) only for a monorepo. For a CD request, also load [rules/deploy.md](rules/deploy.md), [rules/rollback.md](rules/rollback.md) and [rules/release.md](rules/release.md), and load [rules/publish.md](rules/publish.md) only when the `package_kind` fact finds a published package. Create mode starts with no shards (GRAPH-05) and uses the create values of COST-04: 5 for `changes` and `ci-passed`, 10 for `lint`, `typecheck`, `build` and `audit`, and 15 for `test`. It uses the create values of DEPLOY-09: 30 for a deploy job, 10 for `package`, 5 for `skip-notice`, 15 for the release job and 30 for the rollback job. Create mode never uses `pull_request_target` or `workflow_run` (SEC-07).
5. Write the files.
   - Write `.github/workflows/ci.yml` only when no CI file exists. Step 1 decides whether it has the CD part.
   - For a CD request with a template, write each CD file that does not exist. Write each repo script (`scripts/deploy-and-verify.sh` and `scripts/check-staged.sh`, copied from [templates/scripts/](templates/scripts/)) that does not exist, only in a run that writes `deploy.yml` or `rollback.yml`. The Write tool keeps no file mode, so after it writes a script, run `chmod +x` on the scripts that this run wrote, as its own Bash call (the deploy jobs run them as `./scripts/...`). When the harness denies that call, print the exact `chmod` command in the final message for the owner. Never overwrite an existing file or script.
   - In a run that writes `ci.yml`, glob `.github/dependabot.yml` and `.github/dependabot.yaml`. When neither exists, write `.github/dependabot.yml` with the Dependabot block below. When one exists and has no `github-actions` entry, add only that entry under `updates:`, and leave every other entry as it is. When one exists and has the entry, leave it unchanged.
   - In a run that writes `ci.yml`, take the `existing_workflows` fact: when it holds `.github/workflows/security-audit.yml` or `.github/workflows/security-audit.yaml`, leave that file unchanged. Otherwise write `.github/workflows/security-audit.yml` with the security audit block below, filled with the same package manager and Node version.
6. Run actionlint when the `installed_tools` fact has `installed: true` for it. Run it in the repo root as `actionlint -format '{{json .}}'` (see [tools.md](tools.md)), as its own call, never chained with another command. When it reports errors, fix the file and run it again, up to 3 runs in all. Only the findings whose `filepath` is a file that this run wrote count. A finding in another file is named in the `## Created` section and is not a finding of the self-review. The same holds for a finding in a written CD file that comes from the call of an existing CI file that lacks the CD part (a missing `workflow_call` input or output): the CD-part report rows of step 1 already cover it. Errors that remain after the third run become findings `actionlint-<kind>` (suggestions) in the self-review, as the merge rules of [tools.md](tools.md) say. When actionlint is not installed, say so and give the install hint of [tools.md](tools.md). Never install a tool.
7. Self-review the files that you wrote against the same rules, as [review.md](review.md) does. The final message has this order:
   - `## Created`. One line for each file that the run wrote or left unchanged: the path and the word `written` or `unchanged`. A file that the run edited (a Dependabot file with an added entry) is `written`. A line for each removed job, and for a missing test runner. The deploy target when it came from the request and differs from the facts. The actionlint output of step 6 when it has errors.
   - For each written file, a heading `### <path>` and the file text in a fenced `yaml` block (a `bash` block for a shell script). The block holds the whole file, line by line, exactly as written: never a summary, an outline, a list of jobs, comments in place of the steps, or a note that the file is on disk. If actionlint is listed as installed but the call fails (for example `command not found`), say so in `## Created`, and the `Tools:` bullet still follows the `installed_tools` fact.
   - The report of the review report contract in [review.md](review.md), starting with the title line `# cicd-pipelines review: .github/workflows/ci.yml (created)` and the `**Result:` line right after it (for a run that writes no `ci.yml`, the title line names the first written file, in the order `deploy.yml`, `release.yml`, `rollback.yml`). Its section 2 names the defaults that the run used. Its job graph section sketches the created jobs, with one line for each trigger of a CD run: push to main (`Deploy`), the final tag (`Deploy`, prod), the dispatch (`Rollback`) and push to main (`Release`). A CD run applies the CD rules to the files that it wrote and raises no PROTECT row: the ⚑ section lists the prerequisites that create does not make (the AWS roles and variables, the artifact bucket, the environments, the release App and its variables, the Changesets config and the `release` script), and the message offers a review for protection. Write no text after the approval line.

## General mode

Use this section when the mode choice of [SKILL.md](SKILL.md) gives general mode for a create request, that is, for a part of the repo that the skill does not cover. The reply gives advice only. The questions, the steps above and the fill table below do not apply to the general part.

- Write no file. Ask no CI, CD or both question and no deploy target question. Use no template, no fill table, no actionlint run and no self-review of files.
- Read the intake JSON for the repo facts, as the rest of this file does, and load [rules/general.md](rules/general.md) so that each stage names GEN ids that exist. When the repo has no covered part, load no other rule file. In a mixed repo, the covered part loads its own rule files as the steps above say, and the general part uses only the GEN rules.
- When the `stack` fact has the status `unknown` and the request names the language (for example Python), that language fills the empty list: skip the unknown-stack question of [SKILL.md](SKILL.md) and go on. A clash still gets its one question, as the mode choice says.

The general reply has these parts, in this order:

1. Line 1 of the general review ("General mode" in [review.md](review.md)), with its two variants. A repo with two or more uncovered parts gets one line that names every uncovered part. A request that names only a language, with no CI system known, says that there is no CI system yet. Every variant starts with `General guidance:`.
2. A numbered plan of the pipeline stages, one stage for each numbered line, in the order that the stages run. Each stage line has the form `N. <stage name>: <one sentence of advice for the repo stack>. Follows GEN-NN.` The `Follows` part lists one or more GEN ids, separated by commas (for example `Follows GEN-05, GEN-17.`). Each stage names at least one GEN id of [rules/general.md](rules/general.md). Write the stage names and the advice in neutral words and with the tools of the repo language (for example `pytest` for Python), with no GitHub Actions key, no named Action and no Node tool unless the repo language is Node.
3. The last line of the general part: `The skill edits no file in general mode.` In a general-only reply it is the last line of the reply. In a mixed repo the normal create flow follows it, so it is the last line of the general part only.

The plan covers the stages that fit the request. A request for a CI pipeline gets: the triggers and the permissions of the pipeline, a checkout, an install with the cache, a lint, a test and a build. A request that names a release, a publish or a deploy adds a final stage for it, which follows the GEN rules of the topic "Release and deploy safety". Draw the GEN ids from the topics of [rules/general.md](rules/general.md) that apply to the request. The plan has no `## Approve` line, no table and no Required checks line, because there is nothing to approve and no rule check runs.

In a mixed repo, write the general plan first (its line 1, the plan, its last line). Then the normal create flow follows in full for the covered part, with its questions, steps and final message. A request that names one detected part limits the reply to that part: it gets the general plan only when the named part is uncovered, and the normal flow only when the named part is covered.

## Fill table

| Fact | What changes |
|---|---|
| `package_manager` | The setup step, the `cache:` value, the install command, the audit command and the lockfile name in the `changes` filter, as the package manager table says. |
| `node_version_app`, `engines`, `supported_node_majors` | The Node versions, as "Node versions" says. |
| `scripts` | The script of each job. A job whose script does not count is removed. |
| `test_runners` | Without a runner, the `test` job is removed. With `@playwright/test`, the `test` job gets the Playwright steps below. |
| `os_claims` | The OS legs of the `test` job, as "OS legs" says. |
| `monorepo` | The affected-only steps, as "Monorepo tools" says. |
| Deploy target Terraform | In `deploy.yml` and `rollback.yml`, the changes of "Terraform steps" below. |
| CI file `.github/workflows/ci.yaml` (a CD request with a template and a CI file) | The `uses:` line of the `ci` job of `deploy.yml` is `./.github/workflows/ci.yaml`, because a file that does not exist cannot be called. |

The script names are exactly `lint`, `typecheck`, `test` and `build`. A script with another name (such as `test:unit`) does not count. A script counts when the `scripts` entry of the root package, or of any workspace package in a monorepo, lists it.

### Package manager table

| Manager | Setup step before `Set up Node` | `cache:` | Install | Run a script | Audit | Run a tool |
|---|---|---|---|---|---|---|
| npm | none | `npm` | `npm ci` | `npm run <script>` | `npm audit --audit-level=high` | `npx` |
| pnpm | `Set up pnpm` with `pnpm/action-setup` (no `version:` input, it reads `packageManager`) | `pnpm` | `pnpm install --frozen-lockfile` | `pnpm run <script>` | `pnpm audit --audit-level=high` | `pnpm exec` |
| yarn | none | `yarn` | `yarn install --immutable` | `yarn run <script>` | `yarn npm audit --audit-level=high` | `yarn` |

The lockfile names for the `changes` filter are `package-lock.json`, `pnpm-lock.yaml` and `yarn.lock`. Never cache `node_modules` or the Playwright browsers (COST-05). The two templates use npm. For pnpm, put this step before `Set up Node` in every job that sets up Node:

```yaml
      - name: Set up pnpm
        uses: pnpm/action-setup@73e46992e05b19abd31f2f3c20e0e7370d762115 # v6.1.1
```

### Node versions

- An app uses one version, from `node_version_app`. Raw text such as `20.11.0` or `v22` gives its leading integer major (20, 22), even when that major is not in `supported_node_majors` (the repo's own pin). The text `lts/*`, `lts/<name>` or `node` gives the newest LTS of `supported_node_majors`. A range gives the newest major in `supported_node_majors` that the range allows.
- A published package uses each major in `supported_node_majors` that its `engines` range allows. An `engines` entry with the status `default` counts as the newest LTS only.
- A monorepo uses the union of the majors that the `engines` ranges of its published packages allow (their widest range), and the newest LTS when it has no published package.
- The `test` job lists these in `matrix.node`. The other jobs use the newest major of that list in `node-version`. An app has a matrix with one value.

### OS legs

When the `os_claims` fact lists `darwin` or `win32`, the `test` job gets an `os` matrix key with one pinned label for each claimed value, in the order of the fact. `linux` gives `ubuntu-24.04`, `darwin` gives `macos-15` and `win32` gives `windows-2025`. So `["darwin"]` alone gives only `macos-15`, and any other `os` string is ignored. The job then has `runs-on: ${{ matrix.os }}` and the name `Test (${{ matrix.os }}, node ${{ matrix.node }})`. A fact with only `linux`, or with `linux` and strings that map to nothing (such as `aix` or `!win32`), gets no `os` key. Every other job uses `ubuntu-24.04`.

### Monorepo tools

The monorepo template uses Turborepo. For another tool, change only the two steps of each task in `lint`, `typecheck`, `test` and `build`.

| `monorepo` tool | Step on a PR | Step on a push |
|---|---|---|
| `turbo` | `<run a tool> turbo run <task> --affected` | `<run a tool> turbo run <task>` |
| `nx` | `<run a tool> nx affected -t <task>`, with a step `nrwl/nx-set-shas` before it, pinned as [tools.md](tools.md) says | `<run a tool> nx run-many -t <task>` |
| `pnpm` | `pnpm --filter "...[origin/main]" run <task>` | `pnpm -r run <task>` |
| `workspaces` | none: one step runs every package (a deliberate narrowing of MONO-01: there is no `pnpm-workspace.yaml`, so MONO-02 does not apply). npm: `npm run <task> --workspaces --if-present`. yarn: `yarn workspaces foreach --all run <task>`. pnpm: `pnpm -r run <task>`. | the same step |

`<run a tool>` is the "Run a tool" cell of the package manager table: `npx` for npm (the template default), `pnpm exec` for pnpm and `yarn` for yarn. Every job with an affected-only step keeps `fetch-depth: 0` (and `filter: blob:none` for Turborepo) on its checkout. For the tool `workspaces`, replace the two steps of each task by the one step of the table, and remove `fetch-depth: 0` and `filter: blob:none` from the checkouts (COST-08).

### Playwright steps

Put these two steps after the unit test step of the `test` job. Never cache the browsers, and use one worker (COST-06).

```yaml
      - name: Install Playwright browsers
        run: npx playwright install --with-deps chromium
      - name: Run end-to-end tests
        run: npx playwright test --workers=1
```

Replace `npx` with the "Run a tool" cell of the package manager table.

### Terraform steps

For the deploy target Terraform, the Lambda templates change in 4 ways. They apply to every job that runs `deploy-and-verify.sh`: `deploy-dev`, `deploy-staging` and `deploy-prod` of `deploy.yml`, and `roll-back` of `rollback.yml`. The Terraform files are at the repo root.

1. `DEPLOY_TARGET: lambda` becomes `DEPLOY_TARGET: terraform`. The script runs its Terraform branch only for this value.
2. Put these two steps after the `Assume the ... role` step and before the deploy step. An S3 backend needs the credentials at init.
3. In `deploy-dev` and `deploy-staging`, the step `Check out the deploy script` becomes `Check out the repo` with a full checkout: remove its `sparse-checkout: scripts` line, because the Terraform files are missing from a sparse checkout. The checkout of `deploy-prod` and `roll-back` is full already.
4. `vars.DEPLOY_NAME` replaces `vars.LAMBDA_FUNCTION`. It is the third argument of the script, which Terraform ignores.

```yaml
      - name: Set up Terraform
        uses: hashicorp/setup-terraform@dfe3c3f87815947d99a8997f908cb6525fc44e9e # v4.0.1
      - name: Initialize Terraform
        run: terraform init -input=false
```

## Support files

### Dependabot block

```yaml
version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
```

### Security audit block

The cron minute is odd. Fill the setup step, the install command, the audit command and the Node version as for `ci.yml`.

```yaml
name: Security audit
on:
  schedule:
    - cron: '17 6 * * 1'
  workflow_dispatch:
permissions:
  contents: read
jobs:
  audit:
    name: Audit
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    steps:
      - name: Check out the repo
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - name: Set up Node
        uses: actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1 # v7.1.0
        with:
          node-version: 26
          cache: npm
      - name: Install dependencies
        run: npm ci
      - name: Audit dependencies
        run: npm audit --audit-level=high
```
