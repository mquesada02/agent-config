# testing evals

Model evals for the skill. You run them by hand. They cost tokens and their results vary, so they are not in the repo test command (the deterministic tests are in `../tests/`).

## Run

Run this from the repo root. Put the results outside the repo (`--output-dir`), so they cannot be committed by accident:

```
claude plugin eval skills/testing --no-publish -j 2 --runs 3 --threshold 1.0 --scaffold --ablation with-without --trust-plugin --keep-temp --allow-tools "Bash(python3 *scripts/intake.py*)" "Bash(npx vitest*)" "Bash(CI=true npx vitest*)" "Bash(node --test*)" "Bash(CI=true node --test*)" "Bash(cargo nextest*)" "Bash(CI=true cargo nextest*)" "Bash(cargo test*)" "Bash(CI=true cargo test*)" "Bash(git status*)" "Bash(git rev-parse*)" --output-dir <results folder> --json <results folder>/result.json
```

- `--no-publish` keeps the cases and the report private.
- `-j 2` keeps the CPU load low.
- `--scaffold` runs the `scaffold.sh` of each case. It copies `repo/` into the empty workspace.
- `--allow-tools` grants the shell calls of the review: the intake script, the fixture test run and the timed run of `RUN-04` with its `git status --porcelain` calls. The `approve-1` case runs the fixture tests. The older fixtures hold no installed `vitest`. Their runs report `not run`, `fail` or a `Not checked:` entry for `RUN-04` with the reason. No in-run grader of those cases rejects that entry. The new fixtures use the Node built-in runner (`node --test`), which needs no install, and their scaffold runs `git init`.
- The Rust cases (`rs-*` and `write-rs-*`) need `cargo` and `cargo-nextest` on the machine. The fixtures that run use std-only crates with a hand-written `Cargo.lock`, so they need no crate registry. Their scaffold commits the files, so that the timed run leaves `git status --porcelain` unchanged. The cases `rs-assert-03-insta-update` and `rs-run-02-tokio-sleep` use `insta` or `tokio`: they are static-only (graded by reading, no run, no registry).
- `--keep-temp` keeps the trace of each run. Plugin eval prints the kept folders (`/tmp/claude-eval-*`, read-only). Move them to a dated backup folder under `/tmp` when you are done. Never delete them recursively.
- Add `--case <glob>` to run one case.

Grade a setup case on the kept workspace (the folder that the run used as the repo root). For `setup-rerun` add `--before skills/testing/evals/setup-rerun/repo/docs/agents/testing.md`:

```
python3 skills/testing/scripts/grade_testing_setup.py --repo <kept workspace> --expect skills/testing/evals/<case>/expect-setup.json [--before <rules file as it was before the run>]
```

The first acceptance criterion of the setup ticket ("no missing section") means "no missing section except the expected gap": a `commands.<language>` entry for a language whose test command detection cannot find. The setup fixtures all have a detected test command, so no case hits the gap. Pass the gap to the grader with `allow_missing` when you add such a case.

Grade a write case on its kept workspace and its saved final message. The report is the file that holds the final message. `--before` is the fixture repo as it was before the run:

```
python3 skills/testing/scripts/grade_testing_write.py <report file> --repo <kept workspace> --expect skills/testing/evals/<case>/expect-write.json --before skills/testing/evals/<case>/repo
```

Grade a saved review report with the report grader:

```
python3 skills/testing/scripts/grade_testing_report.py <report file>
```

## Cases

Each folder holds one case:

| File | Purpose |
|---|---|
| `prompt.md` | The prompt and the run limits. It never names the skill. The review prompts never name a rule. The setup prompts give rule ids (the interview answers), and the `allowed_tools` of their front matter include `Write` and `Edit` (the `--allow-tools` list of the run command holds Bash patterns only). The `allowed_tools` of the write prompts include `Write` and `Edit` too: write creates the test file. |
| `case.yaml` | The case name and its `scaffold.sh`. The `approve-*` cases also name `history.jsonl`, a recorded report that the prompt replies to. |
| `scaffold.sh`, `repo/` | The synthetic fixture repo, copied into the workspace. |
| `expect.json` | `expect`: rule ids that must appear. `forbid`: rule ids that must not appear. The setup cases and the write cases hold two empty lists. |
| `expect-write.json` | Write cases only. The expectation of `grade_testing_write.py`, with the keys `tests` (required), `product`, `existing`, `grouped`, `fallback`, `error_line`, `result`, `bugs` and `command_contains`. |
| `expect-setup.json` | Setup cases only. The expectation of `grade_testing_setup.py`, with the keys `set`, `unset`, `allow_missing`, `contains` and `absent`. |
| `graders/*.md` | The in-run graders (plugin eval has no custom-code graders). |

| Case | What it proves |
|---|---|
| `assert-01-no-assertion`, `assert-02-tautology`, `assert-03-nondeterministic-snapshot`, `run-01-hidden-retry` | Review finds the planted fault of each critical id, at the critical severity. |
| `run-02-real-sleep`, `run-03-real-network`, `run-04-slow-small-test`, `run-05-ignored-no-reason`, `par-01-fixed-port`, `par-02-shared-state`, `grp-01-unselected-test`, `grp-01-small-group-io`, `dbl-01-call-order` | Review finds the planted fault of each runnable id. `grp-01-unselected-test` and `grp-01-small-group-io` are the two cases of `GRP-01`. One fault can fire more than one id (a sleep in a small group fires `RUN-02` and `GRP-01`): the case lists in `expect.json` only its planted id. |
| `run-03-medium-loopback` | A medium-group test that connects to loopback gives no `RUN-03` row. |
| `size-smallest-wins` | A slow test case that a small group and a large group both select counts as small, so `RUN-04` finds it. |
| `unreadable-selector` | A group command that is a wrapper script is unreadable: one `Not checked:` entry for the group and no `GRP-01` finding. |
| `run-04-not-checked` | A test command with a snapshot update flag gives `ASSERT-03` and the entry `RUN-04 (command includes an update mode)`, and no timed run. |
| `no-groups` | A rules file with no `[[groups]]` gives exactly one `Not checked: GRP-01, RUN-03, RUN-04 (...)` line and no row for those ids. Note line (d) may also appear. |
| `disabled-no-reason` | A disabled id with no reason line is still checked, and the report says once that it has no reason line. |
| `disabled-with-reason` | A disabled id with a reason line is skipped and listed once; an unknown id is named once. |
| `no-rules-file` | The fallback line is written once and `/testing setup` is suggested once. |
| `malformed-rules-file` | The rules file error is named once with its line. |
| `no-files-in-scope` | Review asks which files to review and reports nothing. |
| `approve-1` | The reply `1` fixes row 1 only and runs the affected tests. |
| `approve-invalid` | The reply `1,all` edits nothing, runs nothing and names the invalid part. |
| `setup-no-rules-file` | A repo with no rules file. Setup writes a file with no missing section, one group, the disabled id with its reason line and one convention. An id that is not in the catalogue is shown as unknown and is not written. The skipped limits question leaves no `limits` key. |
| `setup-skip-all` | The same repo, every question skipped. Setup still writes the six required sections: `groups = []`, no `limits`, no `rules`, no prose section. |
| `setup-no-language` | A repo with no Rust or TypeScript manifest. Setup writes the six sections with `languages = []`, `groups = []` and empty tables, and says that no language was detected. |
| `setup-rerun` | A repo with a rules file that has prose, a reason line and two recorded values that differ from detection. The reply approves one row only: that value and the new group change, and every other value, the prose and the reason line stay. The id that is already recorded and the id with no reason are dropped. |
| `write-grouped` | A rules file with a recorded group that selects the named test path. The tests are written at that path, hold an assertion and run `pass` with the worker flag of the runner, the Group cell names the group, and no question is asked. |
| `write-product-bug` | A planted bug against documented behavior. The test stays with the documented value, the report lists it in `## Found bugs` with the README or the doc comment as the Source, the run result is `fail`, and the product file is unchanged. |
| `write-no-runner` | No test command is known. The run result is `not run` with a reason and the command is `none`. |
| `write-no-rules-file` | The fallback line is written once and `/testing setup` is named once. |
| `write-malformed-rules-file` | The rules file error is named once with its line. |
| `write-go-mod` | A repo with only a `go.mod`. Write uses the general file only (no entry is read), places the tests at the named path, and reports `not run` because no command is known. |
| `rs-01-doc-tests-skipped` | Nextest is the runner, a library has doc tests, a doc command is recorded and no group runs doc tests: review gives one `RS-01` row. |
| `rs-01-doc-group-present` | The same repo with a group whose command is `cargo test --doc`: no `RS-01` row. |
| `rs-assert-03-insta-update` | The single-run command sets `INSTA_UPDATE=always` and the snapshot holds a timestamp: `ASSERT-03`. Static-only. |
| `rs-run-01-retries` | The nextest profile has `retries` and no `flaky-result`: `RUN-01`. |
| `rs-run-01-flaky-fail` | The nextest profile has `retries` with `flaky-result = "fail"`: no `RUN-01` row. |
| `rs-run-02-tokio-sleep` | A `#[tokio::test]` that sleeps on the real clock: `RUN-02`. Static-only. |
| `rs-run-04-nextest-durations` | A slow test case in a small group: the timed run reads the nextest `PASS [` duration line and gives `RUN-04`. |
| `rs-run-04-cargo-test-not-checked` | The runner is `cargo test`: no `RUN-04` row, and the entry `RUN-04 (no per-test duration in the output` is in the `Not checked:` line. |
| `rs-par-02-env-var` | A test sets an environment variable without a restore: `PAR-02`. |
| `rs-grp-01-list-decides` | A nextest group with a filterset is unreadable for the general file: `cargo nextest list` decides its membership, no `Not checked:` entry names the group, and the unselected test case gives `GRP-01`. |
| `write-rs-derived-path` | A workspace member crate with a library and a group with no selector. The prompt names no test path. The tests go to `<member>/tests/<stem>.rs`, the Group cell names the group, the command holds `-j 2` and the result is `pass`. |
| `write-rs-group-path` | The groups are `--test missing` and `--test it`. The derived path is selected by no group, so the tests are added to the existing `tests/it.rs`, and `tests/<stem>.rs` is not written. |
| `write-rs-no-group` | The only group has an exclude flag, so it never counts. The tests go to the derived path, the report has the `No group:` note and Group `none`. |
| `write-rs-binary-only` | A crate with only `src/main.rs`: the report has `Not written: src/main.rs (no test location is known)` and a Result line of zeros. Its `expect-write.json` holds the `tests` key for the structure test only, so grade it with its in-run graders, not with `grade_testing_write.py`. |

Not covered by a case in this ticket: the reply `none`, and a reply after a report with zero rows. The grammar text of `review.md` states them.
