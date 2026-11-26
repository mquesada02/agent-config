# cicd-pipelines evals

Model evals for the skill. You run them by hand. They cost tokens and their results vary, so they are not in the repo test command (the deterministic tests are in `../tests/`).

## Run

Run this from the repo root. Put the results outside the repo (`--output-dir`), so they cannot be committed by accident:

```
claude plugin eval skills/cicd-pipelines --no-publish -j 2 --runs 3 --threshold 1.0 --scaffold --ablation with-without --trust-plugin --keep-temp --allow-tools "Bash(python3 *scripts/intake.py*)" "Bash(python3 *scripts/check_pins.py*)" --output-dir <results folder> --json <results folder>/result.json
```

- `--no-publish` keeps the cases and the report private.
- `-j 2` keeps the CPU load low.
- `--runs 3` and `--threshold 1.0` are the plugin eval defaults, written here on purpose.
- `--scaffold` runs the `scaffold.sh` of each case. It copies `repo/` into the empty workspace. Pass it only for suites that you wrote.
- `--ablation with-without` adds the no-skill baseline arm (`W/OUT` and `Δ` columns).
- `--allow-tools` grants the shell calls of the review steps: the intake script and the pin check script (with no GitHub credentials the pin check reports `unverified`; the `sec-01-wrong-sha` case gives a recorded `pins.json` instead). The pattern matches the path of the script in the skill folder that the run uses. In the review cases the workspace is a temporary folder that is not inside a git repo (a parent repo with an `origin` would be read), and it has a temporary home and no GitHub credentials. The intake finds no GitHub remote, so `required_checks` is `unknown` and the review says "unreadable" (the `name-09-...` case expects this).
- `--keep-temp` keeps the trace of each run (`tracePath` in the result). The result JSON holds scores and grader verdicts but not the final message, so `grade_eval_results.py` reads the final message from the trace. Plugin eval prints the kept folders (`/tmp/claude-eval-*`, read-only). Remove them by hand when you are done.
- Add `--case <glob>` to run one case. Later tickets add cases to this same run.
- Plugin eval exits 1 when a case scores below the threshold. A bare skill folder is a valid target (it resolves as the plugin `cicd-pipelines`), so no wrapper manifest is needed.

Then score the report contract and the rule ids with the two Python graders:

```
python3 skills/cicd-pipelines/scripts/grade_eval_results.py <results folder>/result.json
```

## Cases

Each folder holds one case:

| File | Purpose |
|---|---|
| `prompt.md` | The prompt and the run limits. It never names the skill or a rule. |
| `case.yaml` | The case name and its `scaffold.sh`. |
| `scaffold.sh`, `repo/` | The synthetic fixture repo, copied into the workspace. |
| `expect.json` | `expect`: rule ids that must appear. `forbid`: rule ids that must not appear. |
| `graders/*.md` | The in-run graders (plugin eval has no custom-code graders). |

Review cases: `name-01-...` to `name-09-...` (one bad fixture for each naming rule), `graph-01-...` to `graph-07-...` and `maint-01-...` to `maint-03-...` (one bad fixture for each job graph and maintainability rule), `cost-01-...` to `cost-08-...` and `mono-01-...` to `mono-02-...` (one bad fixture for each cost and monorepo rule), `fx-sequential-quality`, `fx-suite-list`, `fx-duplicate-build`, `fx-inline-tests`, `fx-no-limits`, `fx-paths-required` and `clean` (it forbids every critical and required rule id). GRAPH-05 is a measured rule, and the eval sandbox has no run history, so it has two cases. `graph-05-shards-no-history` forbids GRAPH-05: with the sandbox's own unknown history, the review must give no shard finding. `graph-05-shards-with-history` expects GRAPH-05: its prompt gives the review a recorded intake output (`repo/intake.json`, the intake contract with `run_history` detected, a test job median of about 25 minutes, so 4 shards) and tells it not to run the intake script. `maint-03-copied-workflow` names two copies of the workflow in its prompt, because MAINT-03 applies only on request. Trigger case: `trigger-edit-workflow` asks for a workflow edit and does not name the skill. The CD trigger cases are `trigger-cd-*` (see "CD trigger cases").

Security cases: `sec-01-...` to `sec-10-...` (one bad fixture for each SEC rule), `fx-token-in-run` (a token written into the git config by a `run:` step, and a checkout that keeps its credentials), `merge-01-zizmor-unpinned` and `tool-01-zizmor-missing`. `fx-sequential-quality` also expects SEC-01 (tag pins) and SEC-10 (an audit step inside the job). The `clean` fixture has a `.github/dependabot.yml`, an `audit` job behind a `changes` job, and a weekly `security-audit.yml`.

Notes on the security cases:

- The critical parts of SEC-04 and SEC-07 each have a case next to their required part: `sec-04-untrusted-context-in-run` (critical) and `sec-04-matrix-in-run` (required), `sec-07-pr-head-checkout` (critical) and `sec-07-privileged-trigger` (required). The rule-id grader sees only the rule id, so the structure tests on the fixtures and on the rule text prove the severity parts.
- A plugin eval case cannot control PATH. The `env` field accepts only `EVAL_*` keys, the child session inherits the PATH of the operator shell, and the environment of a scaffold script does not reach the child session (verified with a smoke run: a fake tool that the scaffold put on PATH was not found by the run). So the merge case and the missing-tool case give the review a recorded `intake.json` (with `installed_tools`), and the merge case also gives a recorded `zizmor.json` (the shape of `zizmor --format=json-v1`, one `unpinned-uses` finding on the tag-pinned line). Their prompts tell the review to use these files and to run no tool. The merge case expects `SEC-01` and forbids the bare zizmor id `unpinned-uses`; `grade_eval_results.py` runs the report-structure grader on it, which fails when a rule appears twice at one severity. The missing-tool case still expects the SEC ids, and the report-structure grader checks the install hint.
- (review cases) Run the evals on a machine where actionlint and zizmor are not on PATH, or add them to `--allow-tools`: with a tool on PATH the review would try to run it, and the run denies any call other than the intake script.

Notes on the cost and monorepo cases:

- COST-04 has mixed parts, so it has one case for each part. `cost-04-missing-timeout` is the required part, with no history. `cost-04-timeout-too-high-with-history` is the measured part: every job has a timeout, the recorded `repo/intake.json` has `run_history` detected, and each timeout is more than 2× the proposal. Its prompt tells the review not to run the intake script. `cost-04-timeout-too-high-no-history` is the same workflow with the sandbox's unknown history, and it forbids COST-04.
- `cost-06-too-many-workers` uses 4 workers. The sandbox visibility is unreadable, so the default private, 2 vCPU applies.
- `mono-01-no-affected-run` forbids COST-08, because its `fetch-depth: 0` is in a job that MONO-01 covers. `mono-02-filter-full-history` forbids COST-08, because its `fetch-depth: 0` is in jobs that already run the MONO-02 pnpm filter and in the `lint` job that MONO-02 would filter. `cost-08-full-history-checkout` (not a monorepo) expects COST-08.

Every fixture is synthetic. No text comes from a private repo.

## CD intake facts

The intake script prints 29 facts: the 16 CI facts, 12 CD facts and the `stack` fact. Each has `value`, `status` and `source`. A recorded `repo/intake.json` holds the 12 CD facts and the `stack` fact too (28 facts in a file that has no `scripts`, 29 in one that has). The 12 CD keys come after `supported_node_majors`, in this order, and `stack` comes last, after `deploy_history`. The value of each is the real output of the script on the case fixture (a copy outside any git repo, offline), so with no GitHub remote the facts that need `gh` hold their defaults. The default of each fact is the value that the review uses when the fact is unknown:

| Fact | Value | Default |
|---|---|---|
| `environments` | list of `{name, reviewers, wait_timer, branch_policy, admin_bypass}` | `[]` (none), status `default` |
| `plan` | `{visibility, plan, reviewers_available}` | private, plan `null`, reviewers proposed (a private repo may need GitHub Enterprise), status `default` |
| `rulesets` | list of `{name, target, enforcement}` | `null`, status `unknown` |
| `classic_protection` | `{branch, protected, required_pull_request_reviews, enforce_admins}` of the default branch | `null`, status `unknown` |
| `deploy_targets` | kinds found in the workflow steps | `[]`, status `default` |
| `iac_tools` | tools found in the workflow steps | `[]`, status `default` |
| `aws_variables` | `{role, region}`: the names of the `vars.*` on the `role-to-assume:` and `aws-region:` lines, never a value | the placeholders `vars.AWS_ROLE_<ENV>` and `vars.AWS_REGION`, status `default` |
| `release_tool` | list of `changesets`, `release-please`, `semantic-release`, `release-it` | `[]` (create adds Changesets), status `default` |
| `publish_target` | the registries of the published packages (`npmjs` or a registry URL) | `["npmjs"]`, status `default` |
| `release_tag_pattern` | one glob: `v*`, `[0-9]*` or `*@*` | `v*`, status `default` |
| `provenance` | true only for a public package of a public repo | `false`, status `default` when the visibility is not readable |
| `deploy_history` | the last 10 successful runs of `deploy.yml` (any ref), with the median of each job | `null`, status `unknown` |
| `stack` | `{languages, ci_systems}`: a list of `{item, file}` for each | `{"languages": [], "ci_systems": []}`, status `unknown` (status `detected` when at least one item is found) |

The `stack` fact is the last key. Its value is `{languages, ci_systems}`: each entry is `{item, file}`, the detected item and the file that showed it. Languages come from manifest files at the repo root and up to 2 folder levels below it (the folders `node_modules`, `.git`, `vendor` and `target` are skipped). CI systems come from CI files at the repo root only. When no item is found, the review uses `{"languages": [], "ci_systems": []}` and the status is `unknown`. The status is `detected` when at least one item is found. The recorded value of each case is the output of the script on the `repo` folder of the case, with `intake.json` left out.

`deploy_history` reads `deploy.yml` only. `run_history` still reads `ci.yml` on the default branch only, and `required_checks` is unchanged.

## CD review cases

The CD cases are review cases. The DEPLOY and ROLLBACK cases each hold a synthetic `ci.yml` (with the `workflow_call` trigger and a `code` output), a `deploy.yml`, a `rollback.yml` (not in `rollback-01-no-rollback-workflow`) and the repo scripts that it calls (`scripts/deploy-lambda.sh` and `scripts/check-staged.sh`). Every action is pinned to a placeholder full SHA with a version comment, and the version endpoint is a variable, never a URL. A case name starts with the rule family in lower case, so the CD cases are found by prefix (`deploy-`, `rollback-`, `release-`, `publish-`, `protect-`, `fx-cd-`, `create-cd-` and `clean-cd`).

DEPLOY cases: `deploy-01-...` to `deploy-10-...` (one bad fixture for each DEPLOY rule). A fixture differs from the good workflow only where its rule needs it.

- `deploy-02-tag-run-staging-record` is the good workflow: prod runs in a tag run, has no `needs`, and checks the staging record with `scripts/check-staged.sh`. It forbids DEPLOY-02.
- DEPLOY-09 is a measured rule, so it has one case for each part, as COST-04 does. `deploy-09-missing-timeout` is the required part, with no history. `deploy-09-timeout-too-high-with-history` is the measured part: its recorded `repo/intake.json` has `deploy_history` detected (every median at most 270 seconds, so the proposal is at most 14 minutes) and every job but the called workflow has `timeout-minutes: 30`. Its prompt tells the review not to run the intake script. `deploy-09-timeout-too-high-no-history` is the same workflow with the sandbox's unknown history, and it forbids DEPLOY-09.
- The `clean` case and the CI create cases that write files forbid the required DEPLOY ids (01 to 06, 08 and 09), the required ROLLBACK ids (01, 02, 03 and 06), the required RELEASE ids (01 to 06), the required PUBLISH ids (01 to 03) and the required PROTECT ids (01 to 05). The review does not load the RELEASE, PUBLISH and PROTECT files for these cases, so these ids are a safety net.

ROLLBACK cases: `rollback-01-...` to `rollback-06-...` (one bad fixture for each ROLLBACK rule). Each one is a copy of the good DEPLOY workflow fixture (`deploy-02-tag-run-staging-record`) plus a good `rollback.yml`: a `workflow_dispatch` with an environment choice, a job that runs only for a tag, the same deploy script as the deploy jobs and the group `deploy-${{ inputs.environment }}`. A fixture differs from the good files only where its rule needs it, and the cases check only their own expect list, so a fixture may also earn a finding of another rule.

- `rollback-01-no-rollback-workflow` has no `rollback.yml`. ROLLBACK-01 is tested with a missing file only: its trigger, tag-ref and free-text version parts are covered by the rule text.
- `rollback-02-rollback-builds`: the rollback job installs and builds.
- `rollback-03-run-artifact-only`: the `package` job of `deploy.yml` stores the zip only with `actions/upload-artifact`. The deploy and rollback scripts stay as they are.
- `rollback-04-parallel-prod-targets`: a matrix of two functions with `max-parallel: 1` under the shared group `deploy-${{ inputs.environment }}`. The matrix is the finding, not the missing `max-parallel`.
- `rollback-05-native-rollback-disabled`: the rollback step is `aws cloudformation deploy` with `--disable-rollback`.
- `rollback-06-other-concurrency-group`: the rollback group is `rollback-${{ inputs.environment }}`.

RELEASE and PUBLISH cases: `release-01-...` to `release-06-...` and `publish-01-...` to `publish-05-...` (one bad fixture for each rule). Each one is a synthetic pnpm library with Changesets: a `ci.yml` (with the `workflow_call` trigger), a `.changeset/config.json`, a `package.json` of a published package and one good `release.yml`. The good `release.yml` runs on a push to main and a dispatch, makes a release App token in the `release` environment, installs from the frozen lockfile with `package-manager-cache: false`, uses Node 24 with `id-token: write`, and releases with `changesets/action`. A fixture differs from the good files only where its rule needs it, and the cases check only their own expect list. These cases hold no `deploy.yml` and no `rollback.yml`.

- `release-01-two-release-tools`: `package.json` also holds `semantic-release`.
- `release-02-lightweight-tag`: a step makes the tag with `git tag` and no `-a`.
- `release-03-no-tag-ruleset`: the good files, and a recorded `repo/intake.json` (28 facts) whose `rulesets` fact is detected and holds only a branch ruleset. Its prompt tells the review not to run the intake script.
- `release-04-pat-token`: the checkout and `changesets/action` use `secrets.RELEASE_PAT` and no App token.
- `release-05-tag-push-trigger`: the release workflow runs on `push: tags:`.
- `release-06-no-release-notes`: `"changelog": false` in the Changesets config and `createGithubReleases: false` on the `changesets/action` step.
- `publish-01-npm-token`: `NODE_AUTH_TOKEN` from `secrets.NPM_TOKEN` and no `id-token`.
- `publish-02-cached-publish`: `actions/setup-node` has `cache: pnpm`.
- `publish-03-no-dependency-order`: a pnpm monorepo of two published packages that publishes each one in a shell loop.
- `publish-04-no-published-version-check`: a plain `npm publish` step with no `npm view` check.
- `publish-05-publish-workflow-renamed`: the good release job lives in `publish.yml` and the repo has no `release.yml`. The report row of PUBLISH-05 gets the ⚑ mark, and the ⚑ section holds the npm admin step.

PROTECT cases: `protect-01-...` to `protect-08-...` (one case for each PROTECT rule). Each one is a copy of the good DEPLOY workflow fixture (`deploy-02-tag-run-staging-record`: `ci.yml`, `deploy.yml`, the two scripts, `package.json` and the lockfile) plus the good `rollback.yml` of the ROLLBACK cases, and a recorded `repo/intake.json` of the 28 facts. The recorded intake holds the good state of every fact that a PROTECT rule reads (`environments` with `artifacts`, `dev`, `staging` and `prod`, each with `branch_policy: custom` and `admin_bypass: false`, and `reviewers: true` for `prod`; `rulesets` with an active branch ruleset and an active tag ruleset; `classic_protection` not protected; `required_checks` of `CI passed`; a plan that allows reviewers; `release_tag_pattern` `v*`; all `detected`), and a case changes only the fact of its own rule. The prompt tells the review not to run the intake script. The cases hold no `release.yml`, so the job graph sketch has three trigger lines. A case checks only its own expect list, so a report may also hold the row of another rule.

- `protect-01-no-main-ruleset`: `rulesets` has only a tag ruleset, and the classic rule is protected (so the Fix holds the classic deletion, a ⚑ step).
- `protect-02-no-tag-ruleset`: `rulesets` has only a branch ruleset.
- `protect-03-env-accepts-any-branch`: `prod` has `branch_policy: none`.
- `protect-04-prod-no-reviewers`: `prod` has `reviewers: false`.
- `protect-05-admin-bypass-on-prod`: `prod` has `admin_bypass: true`. The Fix is a manual ⚑ step.
- `protect-06-classic-and-ruleset-stack`: `classic_protection` is protected next to the good rulesets and the good required checks.
- `protect-07-claimed-protection-missing`: a comment above the prod job of `deploy.yml` claims required reviewers, and `prod` has `reviewers: false` (so the report also holds a PROTECT-04 row).
- `protect-08-repo-wide-role-arn`: the `package` job names no `environment` and reads `vars.AWS_ROLE_ARN`.

The report parts that the PROTECT cases check: the 🔒 mark in the Rule cell (the `expect-<ID>.md` pattern takes `⚑`, `🔒` or both in that order), the lock note (`section-lock-note.md`, in `protect-01` to `protect-04`, whose reports hold a 🔒 row), and the three trigger lines of the job graph sketch (`section-graph-triggers.md`, in all 8 PROTECT cases and in no other case). The `Defaults:` part of the `Intake:` line is checked by `grade_report.py`.

## CD candidate cases

The 10 `fx-cd-*` cases are the multi-rule candidates of the sample catalog. Nine are bad fixtures and one is a good reference. Each one is a review case with the prompt "Review our CI and CD setup in this repo." Except for `fx-cd-publish-no-guard` (which starts from the release files of `release-05-tag-push-trigger`) and `fx-cd-good-reference` (which starts from `clean-cd`), each one is the good deploy fixture (`deploy-02-tag-run-staging-record`) plus the good `rollback.yml` of the ROLLBACK cases, changed only where its defect needs. A case checks only its own lists, so a report may hold other rows.

| Case | Defect | Expects |
|---|---|---|
| `fx-cd-no-timeout` | `deploy.yml` and `rollback.yml` have no `timeout-minutes`, and the deploy jobs hold `id-token: write`. | DEPLOY-09 |
| `fx-cd-no-concurrency` | The deploy jobs have no `concurrency` group. | COST-02 |
| `fx-cd-rebuild-per-env` | The three stage jobs each install and build. | DEPLOY-01 |
| `fx-cd-prod-from-push` | Prod deploys on push to main, with no gate on the staging record. A recorded `repo/intake.json` (the 28 facts of the PROTECT cases) shows `prod` with no reviewers, and the prompt tells the review not to run the intake script. | DEPLOY-02, PROTECT-04 |
| `fx-cd-role-in-yaml` | The three stage jobs type a role ARN with an account id. | DEPLOY-04 |
| `fx-cd-tag-unpinned` | The called CI workflow is a reusable workflow pinned by the tag `@v2`. It is the one `uses:` line in the CD cases that is not a full-SHA pin: `CdFixtures` skips exactly this line of this case. | SEC-01 |
| `fx-cd-rollback-by-input` | The rollback takes a free-text `version` input, checks out that ref, installs and builds. | ROLLBACK-01, ROLLBACK-02 |
| `fx-cd-silent-skip` | `deploy-dev` skips on an empty variable, and the deploy script exits with success on an empty function name. | DEPLOY-06 |
| `fx-cd-publish-no-guard` | A release workflow on a tag push makes a tag with no main-branch check and runs a plain `npm publish`. | RELEASE-02, RELEASE-05, PUBLISH-04 |
| `fx-cd-good-reference` | The `clean-cd` flow plus a `record` job that runs with `!cancelled()`, fails unless prod succeeded and uploads a release record. | Nothing. It forbids the ids that `clean-cd` forbids. |

## CD trigger cases

`trigger-cd-protection` ("Set up branch protection for this repo."), `trigger-cd-deploy` ("Add a deploy workflow for this repo.") and `trigger-cd-release` ("Release this package.") measure the CD words of the skill description. Each case is a copy of `trigger-edit-workflow`: a minimal repo (`package.json` with a `build` script, a lockfile and one workflow file, `ci.yml`), no skill named, and the one grader `skill-fired.md` (`tool_used: Skill`).

## General trigger cases

`trigger-general-ci-file` and `trigger-general-unrelated` measure the general words of the skill description. Both name no skill and allow only `Read`, `Glob`, `Grep` and `Skill`, as the other trigger cases do. A trigger case measures a model choice, so one run can fail and the next can pass.

- `trigger-general-ci-file` asks for an edit of a `.gitlab-ci.yml` file ("In .gitlab-ci.yml, add a job `lint` that runs `golangci-lint run`."). Its repo is a copy of the repo of `general-review-go-gitlab` (a Go repo on GitLab CI, with a recorded `intake.json`, so it has no covered part). The trigger cases cannot run the intake script, so the second line of the prompt tells the run to use `intake.json`. The skill must fire and give the "Another edit" reply of the general mode: `skill-fired.md`, `general-line-1.md` (`^General guidance:`), `general-bullet.md` (a bullet with a GEN id) and `general-last-line.md` (the last line `The skill edits no file in general mode.`).
- `trigger-general-unrelated` asks to fix a SQL query ("Fix the query in queries/orders.sql: it counts each order twice."). Its repo is one SQL file. The skill must stay silent: `no-cicd-reply.md` (a `regex` grader with `match: not_contains` on a `# cicd-pipelines` title and a `General guidance:` line) and `no-skill-call.md` (a `tool_used` grader on the `Skill` tool, with `max: 0`).

Neither case has a marker grader, so `grade_eval_results.py` does not score them.

## Run the CD groups

Run each group by hand, from the repo root. Put the results outside the repo, and never commit them. Use the review run of "Run" for the review groups, and change only `--case`:

```
claude plugin eval skills/cicd-pipelines --case '<glob>' --no-publish -j 2 --runs 3 --threshold 1.0 --scaffold --ablation with-without --trust-plugin --keep-temp --allow-tools "Bash(python3 *scripts/intake.py*)" "Bash(python3 *scripts/check_pins.py*)" --output-dir <results folder> --json <results folder>/result.json
```

| Group | `--case` glob | Run commands that differ |
|---|---|---|
| DEPLOY | `deploy-*` | The review run above. |
| ROLLBACK | `rollback-*` | The review run above. |
| RELEASE and PUBLISH | `release-*` and `publish-*` | The review run above, once for each glob. |
| PROTECT | `protect-0*` | The review run above. The glob leaves out `protect-approve-*`. |
| Candidates | `fx-cd-*` | The review run above. |
| Clean CD | `clean-cd` | The review run above. |
| Triggers | `trigger-cd-*` | The review run above, with no `--allow-tools`: the cases allow `Read`, `Glob`, `Grep` and `Skill`. |
| General triggers | `trigger-general-*` | The review run above, with no `--allow-tools`: the cases allow `Read`, `Glob`, `Grep` and `Skill`. |
| Protection approval | `protect-approve-*` | The command of "Protection approval cases". |
| Create | `create-cd-*` | The command of "Create cases", with this `--case` glob. |

After each review run, grade it: `python3 skills/cicd-pipelines/scripts/grade_eval_results.py <results folder>/result.json`. After the create run, also run `scripts/grade_create_results.py`. Both read the result file and the kept traces.

## Approval cases

`approve-1-3`, `approve-2-4`, `approve-all` and `approve-none` test the fix flow. Each case gives a recorded review report and a reply (`1,3`, `2-4`, `all`, `none`). The four cases share one synthetic fixture: the `clean` workflow with five defects, one finding each, in the order of the recorded report: 1 SEC-03, 2 SEC-05, 3 COST-04, 4 COST-07, 5 COST-08.

- **Second turn.** A case has a `history.jsonl` (`context.history_file`): a user turn ("Review our CI setup in this repo.") and an assistant turn with the report. The prompt of the case is the next user turn: the reply, and the line that points to the recorded `intake.json`. The docs do not give the transcript format. The shape in these files is the one that a smoke run resumed (one `user` line and one `assistant` line with a `text` block). With a path target the case runs one arm.
- **Recorded intake.** `repo/intake.json` says that actionlint is on PATH (a version), and that zizmor and pinact are not. A case cannot control PATH (see the security cases), so the recorded intake makes the model run actionlint after the edits. The graders check that Bash call and its order after the first `Edit`, and a diff in the final message. This proves the attempt and the order, not a real lint pass. The unit tests prove the detection with a fake actionlint on PATH. An operator who has actionlint on PATH gets the real lint in the same run, with the same graders.
- **Session transcript.** A run of an approval case writes the resumed session transcript into the case folder (a file named like the session id in `history.jsonl`, with the paths of the operator). `evals/.gitignore` ignores it. Do not commit it.
- **Scaffold.** `scaffold.sh` copies `repo/` and makes the workspace a git repo with one commit, so that `git diff` works. (The review cases have no git repo.)
- **Graders.** The final message of an editing case holds the applied list, the diff and a post-fix report (title ends with `(after fixes)`). The `expect-<ID>.md` graders (the findings that the reply did not approve) and the `forbid-<ID>.md` graders (the approved ones) read that report. `approve-none` has the three no-edit graders, `no-actionlint.md` and no report graders. Every case has `gh-api-no-write.md`: a `tool_used` grader (`max: 0`) that matches a `gh api` call on a branch protection, ruleset or environment path with a method other than GET, or with a body flag. A call that mixes a read of such a path with a body flag for another path also matches. Run it by hand:

```
claude plugin eval skills/cicd-pipelines --case 'approve-*' --no-publish -j 2 --runs 1 --ablation none --scaffold --trust-plugin --keep-temp --allow-tools Edit "Bash(actionlint*)" "Bash(git diff*)" --output-dir <results folder> --json <results folder>/result.json
```

`Edit` is a gated tool: without `--allow-tools Edit` the run withholds it from the model, and the `actionlint-after-edit.md` grader cannot pass. The allow pattern of the actionlint call is `Bash(actionlint*)`.

Then run `python3 skills/cicd-pipelines/scripts/grade_eval_results.py <results folder>/result.json`. It grades the three editing cases from their `expect.json` and skips `approve-none`. The full run of these cases (3 runs each) belongs to the eval ticket, not to the ticket that added them.

## Protection approval cases

`protect-approve-yes` and `protect-approve-no` test the protection write step of the fix flow. They are not review cases. The recorded history ends at the `--show` output of two protection rows and the step 2 question. The prompt is the reply (`yes` or `no`).

- **Rows.** The row files are in `repo/rows/`: `row1.json` (a `POST` of a ruleset) and `row2.json` (a `PUT` of the prod environment). The sandbox has no GitHub credentials. So `--apply` of row 1 fails at its first read and stops all later writes.
- **Graders.** Each case has `gh-api-no-write.md` and its own graders for the apply call count and for the report of the stopped and not written rows.
- **Run.** Run them by hand:

```
claude plugin eval skills/cicd-pipelines --case 'protect-approve-*' --no-publish -j 2 --runs 1 --ablation none --scaffold --trust-plugin --keep-temp --allow-tools "Bash(python3 *scripts/protect_write.py*)" --output-dir <results folder> --json <results folder>/result.json
```

## Create cases

`create-npm-app`, `create-pnpm-library`, `create-pnpm-turbo-monorepo`, `create-playwright-app` and `create-no-lockfile` test the create steps for CI. `create-cd-lambda-app`, `create-cd-changesets-library`, `create-cd-monorepo-publish` and `create-cd-terraform` test the create steps for CI and CD. Each CI case asks "Create CI for this repo.", and each CD case asks "Create CI and CD for this repo." and names the deploy target. Each case gives a synthetic fixture with no `ci.yml` and a recorded `repo/intake.json` (all 29 facts, `scripts` included, and `installed_tools` that says actionlint is installed). The prompt tells the model not to run the intake script. The `expect.json` of a writing case has `expect: []`, `forbid` with every critical and required id of the `clean` case, and `asserts`: an object from each path that the final message shows in `## Created` to the assertion list of `scripts/check_workflow.py` for that file.

| Case | Fixture | What it proves |
|---|---|---|
| `create-npm-app` | An npm app with no Node pin. Dependabot and `security-audit.yml` are missing. | The single-package template, `matrix-node=26`, `install=npm ci`, and both support files written. |
| `create-pnpm-library` | A pnpm library with `engines` `>=22`. Both support files are missing. | `matrix-node=22,24,26` and `install=pnpm install --frozen-lockfile`. |
| `create-pnpm-turbo-monorepo` | A pnpm and Turborepo monorepo with two published packages (`engines` `>=22` and `>=24`). Both support files exist. | The monorepo template, `affected-run=turbo`, and both support files left unchanged (`max: 0` `Write` and `Edit` graders, and the final message shows `unchanged`). |
| `create-playwright-app` | An app with `@playwright/test`. Both support files are missing. | The browsers install step, `workers=1`, and no browser cache. |
| `create-cd-lambda-app` | An npm app with a `build` script. The deploy target is AWS Lambda. | `ci.yml` with `triggers-cd`, `deploy.yml`, `release.yml` (npm), `rollback.yml`, and `chmod +x` of the repo scripts. |
| `create-cd-changesets-library` | A pnpm library with a `build` script. The deploy target is AWS Lambda. | The same six files, with pnpm in `ci.yml` and `release.yml`. |
| `create-cd-monorepo-publish` | A pnpm and Turborepo monorepo with two published packages. The deploy target is AWS Lambda. | The monorepo `ci.yml` with `triggers-cd`, and the CD files. |
| `create-cd-terraform` | An npm app with a `build` script. The deploy target is Terraform. | The Terraform setup steps in `deploy.yml` and `rollback.yml` (`text=terraform init -input=false`, `no-text=LAMBDA_FUNCTION`). |
| `create-no-lockfile` | A package with no lockfile. | The run writes nothing under `.github/` (`no-write-github.md`) and names `COST-05` (`names-COST-05.md`). It has no section graders, no `wrote-ci` grader and no `asserts`, so both Python graders skip it. |

In-run graders of a writing case: `wrote-ci.md` (one `Write` of `.github/workflows/ci.yml`), `actionlint-after-write.md` (a `Bash` call with `actionlint` after the first `Write`), `actionlint-ran.md`, the six `section-*.md`, one `forbid-<ID>.md` for each id of the forbid list, `gh-api-no-write.md`, and a `wrote-<file>.md` grader (`min: 1`) for each support file that the case must write. A CD case adds `wrote-deploy.md`, `wrote-release.md`, `wrote-rollback.md` and `chmod-scripts.md`. The recorded `intake.json` of a CD case holds the 12 CD intake facts (`environments` to `deploy_history`), with no deploy target found, so the prompt supplies the target.

Run the create cases by hand. `Write` and `Edit` are gated tools, so `--allow-tools` grants them, with the actionlint call:

```
claude plugin eval skills/cicd-pipelines --case 'create-*' --no-publish -j 2 --runs 1 --ablation none --scaffold --trust-plugin --keep-temp --allow-tools Write Edit "Bash(actionlint*)" "Bash(chmod*)" --output-dir <results folder> --json <results folder>/result.json
```

Then run both Python graders on the result:

```
python3 skills/cicd-pipelines/scripts/grade_eval_results.py <results folder>/result.json
python3 skills/cicd-pipelines/scripts/grade_create_results.py <results folder>/result.json
```

`grade_eval_results.py` scores the report structure and the rule ids of every case that has the `section-summary` grader, so it scores the four writing cases and skips `create-no-lockfile`. `grade_create_results.py` reads the final message of each with-arm run of each case that has the `wrote-ci` grader. It takes each fenced `yaml` block under a `### <path>` heading of the `## Created` section, runs `check_workflow.py` on it with the assertions of that path in `expect.json`, and fails the run when a path that the case asserts is not shown.

- **Real actionlint.** A case cannot control PATH (see the security cases), so the in-run graders prove the attempt and its order, not a real lint pass. `grade_create_results.py` runs the real `actionlint` on each written workflow block when actionlint is on PATH. Without it, the script prints `NOT RUN actionlint: not on PATH` and does not fail the run. An operator who wants the real lint result installs actionlint first, and then runs the script.
- **Model run.** The model run of these cases belongs to the eval ticket (issue 362), not to the ticket that added them. The unit tests of the cases are in `tests/test_create_cases.py`, and the tests of the two scripts are in `tests/test_check_workflow.py` and `tests/test_grade_create_results.py`.
- **No session transcript.** A create case has no `history.jsonl`, so a run writes no transcript into the case folder.

## General cases

The general-mode cases check the fallback for a repo with an uncovered part (see "General mode" in `review.md` and in `create.md`). `GEN` is the id prefix of the general rules in `rules/general.md`. Each holds a recorded `repo/intake.json` with 29 facts and the `stack` fact set. The `stack` fact lists the detected languages and CI systems. For the empty repo of the create case, it holds empty lists and the status `unknown`. The prompt of each case tells the run to use that file and not to run the intake script. Every fixture is synthetic. The create case has 40 turns and allows the `Write` and `Edit` tools, as the `create-` cases do, so that a write by the skill shows and fails a no-write grader.

| Case | Repo | What it checks |
|---|---|---|
| `general-review-rust-github` | Rust on GitHub Actions | The general review: `General guidance:` on line 1, GEN rows with no `#` column, no `## Approve`. Expects 4 GEN ids. |
| `general-review-go-gitlab` | Go on GitLab CI | The same form for a CI system that the skill does not cover. Expects 4 GEN ids. |
| `general-review-mixed-node-rust` | Node/TypeScript and Rust on GitHub Actions | The general part first, then the normal report in full. Expects a GEN id and a normal rule id, and holds the section graders of a normal review. |
| `general-clash-rust-node` | Rust repo, and the request asks for a Node pipeline | A clash: the reply is one question, with no `General guidance:` line. |
| `general-create-python-empty` | Empty repo (only `intake.json`), and the request asks for a Python pipeline | The general create plan: `General guidance:` on line 1, a numbered stage plan where each stage names a GEN id, and the last line `The skill edits no file in general mode.` No file is written. |

- `general-report.md` (a `regex` grader on `^General guidance:`) marks a general review. `grade_eval_results.py` scores each case that has it, as it scores each case that has `section-summary`. The clash case and the create case have no marker, so the script does not score them: their replies are not reports.
- The create case has 3 `regex` graders: `general-line-1.md` (`^General guidance:`), `general-stage.md` (every numbered line holds `Follows GEN-NN`; `grade_rule_ids.py REPLY --plan rules/general.md` also checks that each id is an entry of `rules/general.md`) and `general-last-line.md` (the last line of the reply). A model run judges the rest of the plan.
- An `expect-GEN-NN.md` grader finds the id in the first cell of a row (`^\|\s*GEN-NN\s*\|`), because the general table has no `#` column.
- The `no-edit.md`, `no-write.md` and `no-shell-write.md` graders of a general case match any path, not only `.github/workflows`, because general mode writes no file.
- `no-fallback.md` (a `regex` grader with `match: not_contains` on `General guidance:`) is in the clash case and in `clean`: a covered repo must not use the fallback.
- `one-question.md` is an `llm` judge of the clash case.
- The tests of these cases are in `tests/test_general_cases.py`.

## Fix-quality rationale

Plugin eval tells an `llm` judge to answer with one word, keeps only the votes, and shows the judge one input (the last message). So a result file holds no reason for a `fix-quality` fail, and the judge cannot see the workflow. `scripts/judge_fix_quality.py` reads the same result and the kept traces (`--keep-temp`), and asks a haiku judge one question for each table row, with the exact text of the fixture workflow files (`repo/.github`) and the flag section for a row marked with ⚑. It reads the NAME-09 rules and the ⚑ row rule from the case's `graders/fix-quality.md`, so the script and the grader cannot drift. It prints `PASS` or `FAIL` and a reason for each row, then the row and run pass rates. It costs one judge call for each row, so use `--case <glob>` to limit it:

```
python3 skills/cicd-pipelines/scripts/judge_fix_quality.py <results folder>/result.json --case 'name-*'
```

## Graders

- `expect-<ID>.md` and `forbid-<ID>.md`: a `regex` grader that finds the id in the Rule cell of a table row. They are generated from `expect.json`, and a unit test keeps them in step.
- `section-*.md`: `regex` graders for the section markers of the report contract. `section-lock-note.md` and `section-graph-triggers.md` are extra, and only the PROTECT cases hold them (see "CD review cases").
- `no-edit.md`, `no-write.md`, `no-shell-write.md`: `tool_used` graders with `min: 0` and `max: 0`. The skill must not edit a workflow before approval.
- `fix-quality.md`: an `llm` judge of the fix text. It judges the finding rows one row at a time, on the last message only. It is `arm: with-only`, so it is reported and not scored. Plugin eval reads graders only from the case folder, so every case holds the same copy, and `tests/test_fix_quality_grader.py` fails when a copy differs. To change the text, write one copy and copy it over all the others. To read why a run failed, see "Fix-quality rationale".
- `skill-fired.md` (trigger case): `tool_used: Skill`. Under `--ablation with-without` it is an indicator of the with-arm, not part of the score.
- `general-line-1.md`, `general-bullet.md`, `general-last-line.md` (`trigger-general-ci-file`) and `no-cicd-reply.md`, `no-skill-call.md` (`trigger-general-unrelated`): see "General trigger cases". `no-skill-call.md` is a `tool_used` grader with `max: 0` and `arm: with-only`. Under `--ablation with-without` it is an indicator of the with-arm, as `skill-fired.md` is.
- `actionlint-ran.md`, `actionlint-after-edit.md`, `no-actionlint.md`, `diff-in-message.md`, `gh-api-no-write.md`, `diff-scope.md` (approval cases): see "Approval cases". `diff-scope.md` is an `llm` judge with `arm: with-only`, so it is reported and not scored.
- `wrote-ci.md`, `actionlint-after-write.md`, `wrote-<file>.md`, `no-write-<file>.md`, `no-edit-<file>.md`, `unchanged-<file>.md`, `no-write-github.md`, `names-COST-05.md` (create cases): see "Create cases".
- `scripts/grade_create_results.py`: runs `check_workflow.py` and the real actionlint on the files that each create run shows in the final message. See "Create cases".
- `scripts/grade_eval_results.py`: runs `grade_report.py` and `grade_rule_ids.py` on the final message of each with-arm run of each review case. This is the scored check of the whole report contract.
