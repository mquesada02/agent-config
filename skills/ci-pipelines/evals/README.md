# ci-pipelines evals

Model evals for the skill. You run them by hand. They cost tokens and their results vary, so they are not in the repo test command (the deterministic tests are in `../tests/`).

## Run

Run this from the repo root. Put the results outside the repo (`--output-dir`), so they cannot be committed by accident:

```
claude plugin eval skills/ci-pipelines --no-publish -j 2 --runs 3 --threshold 1.0 --scaffold --ablation with-without --trust-plugin --keep-temp --allow-tools "Bash(python3 *scripts/intake.py*)" "Bash(python3 *scripts/check_pins.py*)" --output-dir <results folder> --json <results folder>/result.json
```

- `--no-publish` keeps the cases and the report private.
- `-j 2` keeps the CPU load low.
- `--runs 3` and `--threshold 1.0` are the plugin eval defaults, written here on purpose.
- `--scaffold` runs the `scaffold.sh` of each case. It copies `repo/` into the empty workspace. Pass it only for suites that you wrote.
- `--ablation with-without` adds the no-skill baseline arm (`W/OUT` and `Δ` columns).
- `--allow-tools` grants the shell calls of the review steps: the intake script and the pin check script (with no GitHub credentials the pin check reports `unverified`; the `sec-01-wrong-sha` case gives a recorded `pins.json` instead). The pattern matches the path of the script in the skill folder that the run uses. In the review cases the workspace is a temporary folder that is not inside a git repo (a parent repo with an `origin` would be read), and it has a temporary home and no GitHub credentials. The intake finds no GitHub remote, so `required_checks` is `unknown` and the review says "unreadable" (the `name-09-...` case expects this).
- `--keep-temp` keeps the trace of each run (`tracePath` in the result). The result JSON holds scores and grader verdicts but not the final message, so `grade_eval_results.py` reads the final message from the trace. Plugin eval prints the kept folders (`/tmp/claude-eval-*`, read-only). Remove them by hand when you are done.
- Add `--case <glob>` to run one case. Later tickets add cases to this same run.
- Plugin eval exits 1 when a case scores below the threshold. A bare skill folder is a valid target (it resolves as the plugin `ci-pipelines`), so no wrapper manifest is needed.

Then score the report contract and the rule ids with the two Python graders:

```
python3 skills/ci-pipelines/scripts/grade_eval_results.py <results folder>/result.json
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

Review cases: `name-01-...` to `name-09-...` (one bad fixture for each naming rule), `graph-01-...` to `graph-07-...` and `maint-01-...` to `maint-03-...` (one bad fixture for each job graph and maintainability rule), `cost-01-...` to `cost-08-...` and `mono-01-...` to `mono-02-...` (one bad fixture for each cost and monorepo rule), `fx-sequential-quality`, `fx-suite-list`, `fx-duplicate-build`, `fx-inline-tests`, `fx-no-limits`, `fx-paths-required` and `clean` (it forbids every critical and required rule id). GRAPH-05 is a measured rule, and the eval sandbox has no run history, so it has two cases. `graph-05-shards-no-history` forbids GRAPH-05: with the sandbox's own unknown history, the review must give no shard finding. `graph-05-shards-with-history` expects GRAPH-05: its prompt gives the review a recorded intake output (`repo/intake.json`, the intake contract with `run_history` detected, a test job median of about 25 minutes, so 4 shards) and tells it not to run the intake script. `maint-03-copied-workflow` names two copies of the workflow in its prompt, because MAINT-03 applies only on request. Trigger case: `trigger-edit-workflow` asks for a workflow edit and does not name the skill.

Security cases: `sec-01-...` to `sec-10-...` (one bad fixture for each SEC rule), `fx-token-in-run` (a token written into the git config by a `run:` step, and a checkout that keeps its credentials), `merge-01-zizmor-unpinned` and `tool-01-zizmor-missing`. `fx-sequential-quality` also expects SEC-01 (tag pins) and SEC-10 (an audit step inside the job). The `clean` fixture has a `.github/dependabot.yml`, an `audit` job behind a `changes` job, and a weekly `security-audit.yml`.

Notes on the security cases:

- The critical parts of SEC-04 and SEC-07 each have a case next to their required part: `sec-04-untrusted-context-in-run` (critical) and `sec-04-matrix-in-run` (required), `sec-07-pr-head-checkout` (critical) and `sec-07-privileged-trigger` (required). The rule-id grader sees only the rule id, so the structure tests on the fixtures and on the rule text prove the severity parts.
- A plugin eval case cannot control PATH. The `env` field accepts only `EVAL_*` keys, the child session inherits the PATH of the operator shell, and the environment of a scaffold script does not reach the child session (verified with a smoke run: a fake tool that the scaffold put on PATH was not found by the run). So the merge case and the missing-tool case give the review a recorded `intake.json` (with `installed_tools`), and the merge case also gives a recorded `zizmor.json` (the shape of `zizmor --format=json-v1`, one `unpinned-uses` finding on the tag-pinned line). Their prompts tell the review to use these files and to run no tool. The merge case expects `SEC-01` and forbids the bare zizmor id `unpinned-uses`; `grade_eval_results.py` runs the report-structure grader on it, which fails when a rule appears twice at one severity. The missing-tool case still expects the SEC ids, and the report-structure grader checks the install hint.
- (review cases) Run the evals on a machine where actionlint and zizmor are not on PATH, or add them to `--allow-tools`: with a tool on PATH the review would try to run it, and the run denies any call other than the intake script.

Notes on the cost and monorepo cases:

- COST-04 has mixed parts, so it has one case for each part. `cost-04-missing-timeout` is the required part, with no history. `cost-04-timeout-too-high-with-history` is the measured part: every job has a timeout, the recorded `repo/intake.json` has `run_history` detected, and each timeout is more than 2× the proposal. Its prompt tells the review not to run the intake script. `cost-04-timeout-too-high-no-history` is the same workflow with the sandbox's unknown history, and it forbids COST-04.
- `cost-06-too-many-workers` uses 4 workers. The sandbox visibility is unreadable, so the default private, 2 vCPU applies.
- `mono-01-no-affected-run` forbids COST-08, because its `fetch-depth: 0` is in a job that MONO-01 covers. `mono-02-filter-full-history` forbids COST-08, because its `fetch-depth: 0` is in jobs that already run the MONO-02 pnpm filter. `cost-08-full-history-checkout` (not a monorepo) expects COST-08.

Every fixture is synthetic. No text comes from a private repo.

## Approval cases

`approve-1-3`, `approve-2-4`, `approve-all` and `approve-none` test the fix flow. Each case gives a recorded review report and a reply (`1,3`, `2-4`, `all`, `none`). The four cases share one synthetic fixture: the `clean` workflow with five defects, one finding each, in the order of the recorded report: 1 SEC-03, 2 SEC-05, 3 COST-04, 4 COST-07, 5 COST-08.

- **Second turn.** A case has a `history.jsonl` (`context.history_file`): a user turn ("Review our CI setup in this repo.") and an assistant turn with the report. The prompt of the case is the next user turn: the reply, and the line that points to the recorded `intake.json`. The docs do not give the transcript format. The shape in these files is the one that a smoke run resumed (one `user` line and one `assistant` line with a `text` block). With a path target the case runs one arm.
- **Recorded intake.** `repo/intake.json` says that actionlint is on PATH (a version), and that zizmor and pinact are not. A case cannot control PATH (see the security cases), so the recorded intake makes the model run actionlint after the edits. The graders check that Bash call and its order after the first `Edit`, and a diff in the final message. This proves the attempt and the order, not a real lint pass. The unit tests prove the detection with a fake actionlint on PATH. An operator who has actionlint on PATH gets the real lint in the same run, with the same graders.
- **Session transcript.** A run of an approval case writes the resumed session transcript into the case folder (a file named like the session id in `history.jsonl`, with the paths of the operator). `evals/.gitignore` ignores it. Do not commit it.
- **Scaffold.** `scaffold.sh` copies `repo/` and makes the workspace a git repo with one commit, so that `git diff` works. (The review cases have no git repo.)
- **Graders.** The final message of an editing case holds the applied list, the diff and a post-fix report (title ends with `(after fixes)`). The `expect-<ID>.md` graders (the findings that the reply did not approve) and the `forbid-<ID>.md` graders (the approved ones) read that report. `approve-none` has the three no-edit graders, `no-actionlint.md` and no report graders. Every case has `gh-api-no-write.md`: a `tool_used` grader (`max: 0`) that matches a `gh api` call on a branch protection or ruleset path with a method other than GET, or with a body flag. A call that mixes a read of such a path with a body flag for another path also matches. Run it by hand:

```
claude plugin eval skills/ci-pipelines --case 'approve-*' --no-publish -j 2 --runs 1 --ablation none --scaffold --trust-plugin --keep-temp --allow-tools Edit "Bash(actionlint*)" "Bash(git diff*)" --output-dir <results folder> --json <results folder>/result.json
```

`Edit` is a gated tool: without `--allow-tools Edit` the run withholds it from the model, and the `actionlint-after-edit.md` grader cannot pass. The allow pattern of the actionlint call is `Bash(actionlint*)`.

Then run `python3 skills/ci-pipelines/scripts/grade_eval_results.py <results folder>/result.json`. It grades the three editing cases from their `expect.json` and skips `approve-none`. The full run of these cases (3 runs each) belongs to the eval ticket, not to the ticket that added them.

## Create cases

`create-npm-app`, `create-pnpm-library`, `create-pnpm-turbo-monorepo`, `create-playwright-app` and `create-no-lockfile` test the create steps. Each case asks "Create CI for this repo." and gives a synthetic fixture with no `ci.yml` and a recorded `repo/intake.json` (all 16 facts, `scripts` included, and `installed_tools` that says actionlint is installed). The prompt tells the model not to run the intake script. The `expect.json` of a writing case has `expect: []`, `forbid` with every critical and required id of the `clean` case, and `asserts`: an object from each path that the final message shows in `## Created` to the assertion list of `scripts/check_workflow.py` for that file.

| Case | Fixture | What it proves |
|---|---|---|
| `create-npm-app` | An npm app with no Node pin. Dependabot and `security-audit.yml` are missing. | The single-package template, `matrix-node=26`, `install=npm ci`, and both support files written. |
| `create-pnpm-library` | A pnpm library with `engines` `>=22`. Both support files are missing. | `matrix-node=22,24,26` and `install=pnpm install --frozen-lockfile`. |
| `create-pnpm-turbo-monorepo` | A pnpm and Turborepo monorepo with two published packages (`engines` `>=22` and `>=24`). Both support files exist. | The monorepo template, `affected-run=turbo`, and both support files left unchanged (`max: 0` `Write` and `Edit` graders, and the final message shows `unchanged`). |
| `create-playwright-app` | An app with `@playwright/test`. Both support files are missing. | The browsers install step, `workers=1`, and no browser cache. |
| `create-no-lockfile` | A package with no lockfile. | The run writes nothing under `.github/` (`no-write-github.md`) and names `COST-05` (`names-COST-05.md`). It has no section graders, no `wrote-ci` grader and no `asserts`, so both Python graders skip it. |

In-run graders of a writing case: `wrote-ci.md` (one `Write` of `.github/workflows/ci.yml`), `actionlint-after-write.md` (a `Bash` call with `actionlint` after the first `Write`), `actionlint-ran.md`, the six `section-*.md`, one `forbid-<ID>.md` for each id of the forbid list, `gh-api-no-write.md`, and a `wrote-<file>.md` grader (`min: 1`) for each support file that the case must write.

Run the create cases by hand. `Write` and `Edit` are gated tools, so `--allow-tools` grants them, with the actionlint call:

```
claude plugin eval skills/ci-pipelines --case 'create-*' --no-publish -j 2 --runs 1 --ablation none --scaffold --trust-plugin --keep-temp --allow-tools Write Edit "Bash(actionlint*)" --output-dir <results folder> --json <results folder>/result.json
```

Then run both Python graders on the result:

```
python3 skills/ci-pipelines/scripts/grade_eval_results.py <results folder>/result.json
python3 skills/ci-pipelines/scripts/grade_create_results.py <results folder>/result.json
```

`grade_eval_results.py` scores the report structure and the rule ids of every case that has the `section-summary` grader, so it scores the four writing cases and skips `create-no-lockfile`. `grade_create_results.py` reads the final message of each with-arm run of each case that has the `wrote-ci` grader. It takes each fenced `yaml` block under a `### <path>` heading of the `## Created` section, runs `check_workflow.py` on it with the assertions of that path in `expect.json`, and fails the run when a path that the case asserts is not shown.

- **Real actionlint.** A case cannot control PATH (see the security cases), so the in-run graders prove the attempt and its order, not a real lint pass. `grade_create_results.py` runs the real `actionlint` on each written workflow block when actionlint is on PATH. Without it, the script prints `NOT RUN actionlint: not on PATH` and does not fail the run. An operator who wants the real lint result installs actionlint first, and then runs the script.
- **Model run.** The model run of these cases belongs to the eval ticket (issue 362), not to the ticket that added them. The unit tests of the cases are in `tests/test_create_cases.py`, and the tests of the two scripts are in `tests/test_check_workflow.py` and `tests/test_grade_create_results.py`.
- **No session transcript.** A create case has no `history.jsonl`, so a run writes no transcript into the case folder.

## Fix-quality rationale

Plugin eval tells an `llm` judge to answer with one word, keeps only the votes, and shows the judge one input (the last message). So a result file holds no reason for a `fix-quality` fail, and the judge cannot see the workflow. `scripts/judge_fix_quality.py` reads the same result and the kept traces (`--keep-temp`), and asks a haiku judge one question for each table row, with the exact text of the fixture workflow files (`repo/.github`) and the flag section for a row marked with ⚑. It prints `PASS` or `FAIL` and a reason for each row, then the row and run pass rates. It costs one judge call for each row, so use `--case <glob>` to limit it:

```
python3 skills/ci-pipelines/scripts/judge_fix_quality.py <results folder>/result.json --case 'name-*'
```

## Graders

- `expect-<ID>.md` and `forbid-<ID>.md`: a `regex` grader that finds the id in the Rule cell of a table row. They are generated from `expect.json`, and a unit test keeps them in step.
- `section-*.md`: `regex` graders for the section markers of the report contract.
- `no-edit.md`, `no-write.md`, `no-shell-write.md`: `tool_used` graders with `min: 0` and `max: 0`. The skill must not edit a workflow before approval.
- `fix-quality.md`: an `llm` judge of the fix text. It judges the finding rows one row at a time, on the last message only. It is `arm: with-only`, so it is reported and not scored. Plugin eval reads graders only from the case folder, so every case holds the same copy, and `tests/test_fix_quality_grader.py` fails when a copy differs. To change the text, write one copy and copy it over all the others. To read why a run failed, see "Fix-quality rationale".
- `skill-fired.md` (trigger case): `tool_used: Skill`. Under `--ablation with-without` it is an indicator of the with-arm, not part of the score.
- `actionlint-ran.md`, `actionlint-after-edit.md`, `no-actionlint.md`, `diff-in-message.md`, `gh-api-no-write.md`, `diff-scope.md` (approval cases): see "Approval cases". `diff-scope.md` is an `llm` judge with `arm: with-only`, so it is reported and not scored.
- `wrote-ci.md`, `actionlint-after-write.md`, `wrote-<file>.md`, `no-write-<file>.md`, `no-edit-<file>.md`, `unchanged-<file>.md`, `no-write-github.md`, `names-COST-05.md` (create cases): see "Create cases".
- `scripts/grade_create_results.py`: runs `check_workflow.py` and the real actionlint on the files that each create run shows in the final message. See "Create cases".
- `scripts/grade_eval_results.py`: runs `grade_report.py` and `grade_rule_ids.py` on the final message of each with-arm run of each review case. This is the scored check of the whole report contract.
