# testing evals

Model evals for the skill. You run them by hand. They cost tokens and their results vary, so they are not in the repo test command (the deterministic tests are in `../tests/`).

## Run

Run this from the repo root. Put the results outside the repo (`--output-dir`), so they cannot be committed by accident:

```
claude plugin eval skills/testing --no-publish -j 2 --runs 3 --threshold 1.0 --scaffold --ablation with-without --trust-plugin --keep-temp --allow-tools "Bash(python3 *scripts/intake.py*)" "Bash(npx vitest*)" "Bash(CI=true npx vitest*)" "Bash(npx jest*)" "Bash(CI=true npx jest*)" "Bash(node --test*)" "Bash(CI=true node --test*)" "Bash(cargo nextest*)" "Bash(CI=true cargo nextest*)" "Bash(cargo test*)" "Bash(CI=true cargo test*)" "Bash(npm test*)" "Bash(npm run ci*)" "Bash(npm run unit*)" "Bash(CI=true npm test*)" "Bash(CI=true npm run ci*)" "Bash(CI=true npm run unit*)" "Bash(git status*)" "Bash(git rev-parse*)" --output-dir <results folder> --json <results folder>/result.json
```

- `--no-publish` keeps the cases and the report private.
- `-j 2` keeps the CPU load low.
- `--scaffold` runs the `scaffold.sh` of each case. It copies `repo/` into the empty workspace.
- `--allow-tools` grants the shell calls of the review: the intake script, the fixture test run and the timed run of `RUN-04` with its `git status --porcelain` calls. The `approve-1` case runs the fixture tests. The older fixtures hold no installed `vitest` or `jest`. Their runs report `not run`, `fail` or a `Not checked:` entry for `RUN-04` with the reason. No in-run grader of those cases rejects that entry. The new fixtures use the Node built-in runner (`node --test`), which needs no install, and their scaffold runs `git init` and commits the fixture.
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
| `unreadable-selector` | A group command that is a wrapper script is unreadable: one `Not checked:` entry for the group and no `GRP-01` finding. For a `node:test` repo with a recorded test command, the `TS-01` wrapper entry is also written, on the same single `Not checked:` line (entries are separated by `;`). |
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
| `ts-assert-forms` | A test with only a call (`ASSERT-01`) and a `mockReturnValue` value that the assertion compares (`ASSERT-02`); a test with `expect.assertions` is clean. |
| `ts-net-and-port` | A real `fetch` to a remote host in a small group (`RUN-03`) and a literal `listen` port (`PAR-01`); an MSW-handled request is not a finding. Static-only. |
| `ts-skip-and-order` | A `test.skip` with no reason (`RUN-05`) and a `toHaveBeenCalledBefore` assertion (`DBL-01`); a `test.skipIf` on a platform and a `test.todo` are not findings. |
| `ts-01-watch-script` | The recorded test command is `npm test` and the `test` script is `vitest`: one `TS-01` row whose Where cell lists both lines. |
| `ts-01-run-mode` | The single-run command is `vitest run`: no `TS-01` row. |
| `ts-assert-03-update` | `--update` in the single-run command, `update: true` in the config of a second group and a time value in a snapshot: `ASSERT-03`. |
| `ts-run-01-retry` | `retry` in the config and a `{ retry: 3 }` test option: `RUN-01`. |
| `ts-run-02-fake-timers` | One real sleep gives `RUN-02`; a fake-timer test beside it is not a finding. |
| `ts-run-04-verbose-durations` | A test with a fixed real 2 second sleep in a small group: the timed run uses `--reporter=verbose`, reads the verbose line and gives `RUN-04`. |
| `ts-run-04-wrapper-not-checked` | The test command and the group are a wrapper script: no `RUN-04` row, and the `Not checked:` line names `RUN-04`. |
| `ts-grp-01-list-decides` | A group with `--exclude` is unreadable for the general file: `vitest list --filesOnly` decides its membership, no `Not checked:` entry names the group, and the unselected test case gives `GRP-01`. |
| `ts-grp-01-not-checked` | A wrapper group and a `related` group have no list command: the `Not checked:` line names both for `GRP-01` and no `GRP-01` row is given. |
| `ts-par-02-env-var` | A test writes `process.env` without a restore: `PAR-02`; a `vi.stubEnv` test with a restore is clean. |
| `ts-gate-other-runner` | The recorded runner is `mocha`: the Vitest, Jest and `node:test` content of the entry does not apply, so there is no `TS-01` row, no `TS-01` entry in `Not checked:` and no reporter flag. |
| `write-ts-derived-path` | A co-located layout and a group with no selector. The prompt names no test path. The tests go to `src/<stem>.test.ts`, the Group cell names the group, the command holds `--maxWorkers=2` and `--reporter=verbose`, `CI=true` is set, and the result is `pass`. |
| `write-ts-mirrored-path` | The tests live under `tests/`: the tests go to `tests/<stem>.test.ts`. |
| `write-ts-project-group` | The groups are Vitest projects. The derived path matches the `include` of project `unit`, so the Group cell is `unit` (checked by an in-run grader, because `grade_testing_write.py` cannot read the config). |
| `write-ts-no-group` | The only group is `--changed`, so it never counts. The tests go to the derived path, the report has the `No group:` note and Group `none`. |
| `write-ts-no-path` | A declaration file as the product file: the report has `Not written: types/api.d.ts (no test location is known)` and a Result line of zeros. Its `expect-write.json` holds the `tests` key for the structure test only, so grade it with its in-run graders. |
| `write-ts-existing-test` | The product file already has a test file beside it: the new test cases go into that file and no second test file is written. |
| `write-ts-fakes` | The product file uses a timer, `process.env` and an HTTP call: the new test uses fake timers, `vi.stubEnv` with a restore and an MSW request fake, and the run passes in `CI=true` mode. |
| `write-ts-gate-other-runner` | The recorded runner is `mocha`: no test location is known, so the report has `Not written` and the run holds no flag that the entry adds for Vitest, Jest or `node:test`. Grade it with its in-run graders. |
| `write-mixed-rust-ts` | A Rust root crate and a TypeScript folder `web`: one change touches both languages, both entries are read, and each file's tests run with the command of its own entry. |
| `jest-01-watch-script` | The recorded test command is `npm test` and the `test` script is `jest --watch`: one `TS-01` row whose Where cell lists both lines. |
| `jest-01-run-mode` | The single-run command is `npx jest --ci`: no `TS-01` row. |
| `jest-assert-03-update` | `--updateSnapshot` in the single-run command and a time value in a snapshot: `ASSERT-03`. |
| `jest-run-01-retry` | A `jest.retryTimes(2)` call: `RUN-01`. |
| `jest-run-02-fake-timers` | One real sleep gives `RUN-02`; a `jest.useFakeTimers` test beside it is not a finding. |
| `jest-run-04-json-durations` | A test with a fixed real 2 second sleep in a small group: the timed run uses `--json`, reads the `assertionResults` duration and gives `RUN-04`. |
| `jest-run-04-wrapper-not-checked` | The test command and the group are a wrapper script: no `RUN-04` row, and the `Not checked:` line names `RUN-04`. |
| `jest-grp-01-list-decides` | A group with `--testPathIgnorePatterns` is unreadable for the general file: `jest --listTests` decides its membership, no `Not checked:` entry names the group, and the unselected test case gives `GRP-01`. |
| `jest-grp-01-not-checked` | A wrapper group and a `--watch` group have no list command: the `Not checked:` line names both for `GRP-01` and no `GRP-01` row is given. The `--watch` group also gives a `TS-01` row. |
| `jest-assert-forms` | A test with only a call (`ASSERT-01`) and a `mockReturnValue` value that the assertion compares (`ASSERT-02`); a test with `expect.assertions` is clean. |
| `jest-net-port-skip` | A real `fetch` (`RUN-03`), a literal `listen` port (`PAR-01`), a `test.skip` with no reason (`RUN-05`) and `toHaveBeenNthCalledWith` calls (`DBL-01`); a `jest.spyOn(globalThis, 'fetch')` fake and a `test.todo` are not findings. Static-only. |
| `jest-par-02-env-var` | A test writes `process.env` without a restore: `PAR-02`; a test with a restore in `afterEach` is clean. |
| `node-01-watch-script` | The recorded test command is `npm test` and the `test` script is `node --test --watch`: one `TS-01` row whose Where cell lists both lines. |
| `node-01-run-mode` | The single-run command is `node --test`: no `TS-01` row. |
| `node-assert-03-update` | `--test-update-snapshots` in the single-run command and a time value in `t.assert.snapshot`: `ASSERT-03`. |
| `node-run-01-rerun` | `--test-rerun-failures=<file>` in the single-run command: `RUN-01`. |
| `node-run-02-mock-timers` | One real sleep gives `RUN-02`; a `mock.timers` test beside it is not a finding. |
| `node-run-04-spec-durations` | A test with a fixed real 2 second sleep in a small group: the timed run uses `--test-reporter=spec`, reads the result line with its duration and gives `RUN-04`. |
| `node-run-04-wrapper-not-checked` | The test command and the group are a wrapper script: no `RUN-04` row, and the `Not checked:` line names `RUN-04`. |
| `node-grp-01-not-checked` | A wrapper group and a `--test-shard` group (an unreadable selector) have no list command: the `Not checked:` line names both for `GRP-01` and no `GRP-01` row is given. The case shows that this entry has no `node:test` list command. |
| `node-grp-01-readable` | A group with a glob operand is readable: no `Not checked:` entry names it, and a test file that no group selects gives `GRP-01`. |
| `node-assert-forms` | A test with only a call (`ASSERT-01`) and a `mock.fn` value that the assertion compares (`ASSERT-02`); a test with `t.plan` is clean. |
| `node-net-port-skip` | A real `fetch` (`RUN-03`), a literal `listen` port (`PAR-01`), a `skip: true` test with no reason (`RUN-05`) and `mock.calls` order assertions (`DBL-01`); a `mock.method(globalThis, 'fetch', ...)` fake and a `todo` test are not findings. Static-only. |
| `node-par-02-env-var` | A test writes `process.env` without a restore: `PAR-02`; a test with a restore in `afterEach` is clean. |
| `write-jest-derived-path` | A co-located layout and a group with no selector. The prompt names no test path. The tests go to `src/<stem>.test.js`, the Group cell names the group, the command holds `--ci`, `--maxWorkers=2` and `--json`, `CI=true` is set, and the result is `pass` (an in-run grader checks that each new test case has a result in the JSON output). |
| `write-jest-project-group` | The groups are Jest projects. The derived path matches the `testMatch` of project `unit`, so the Group cell is `unit` (checked by an in-run grader, because `grade_testing_write.py` cannot read the config). |
| `write-jest-no-path` | A declaration file as the product file: the report has `Not written: types/api.d.ts (no test location is known)` and a Result line of zeros. Grade it with its in-run graders. |
| `write-jest-existing-test` | The product file already has a test file beside it: the new test cases go into that file and no second test file is written. |
| `write-jest-fakes` | The product file uses a timer, `process.env` and an HTTP call: the new test uses fake timers, an environment restore and an in-process request fake, and the run passes in `CI=true` mode. |
| `write-jest-no-group` | The only group has `--onlyChanged` (an unreadable token), so it never counts. The tests go to the derived path, the report has the `No group:` note and Group `none`. |
| `write-node-derived-path` | A co-located layout and a group with no selector. The prompt names no test path. The tests go to `src/<stem>.test.js`, the command holds `--test-concurrency=2` and `--test-reporter=spec`, `CI=true` is set, and the result is `pass` (an in-run grader checks that each new test case has a result line). |
| `write-node-mirrored-path` | The tests live under `tests/`: the tests go to `tests/<stem>.test.js`. |
| `write-node-no-group` | The only group has `--test-only` (an unreadable token), so it never counts. The tests go to the derived path, the report has the `No group:` note and Group `none`. |
| `write-node-no-path` | A declaration file as the product file: the report has `Not written: types/api.d.ts (no test location is known)` and a Result line of zeros. Grade it with its in-run graders. |
| `write-node-existing-test` | The product file already has a test file beside it: the new test cases go into that file and no second test file is written. |
| `write-node-fakes` | The product file uses a timer, `process.env` and an HTTP call: the new test uses `mock.timers`, an environment restore and a `mock.method` request fake, and the run passes in `CI=true` mode. |
| `write-mixed-rust-node` | A Rust root crate and a `node:test` folder `web`: one change touches both languages, both entries are read, and each file's tests run with the command of its own entry. |

The `ts-*`, `write-ts-*`, `jest-*` and `write-jest-*` cases that run Vitest or Jest install it in their scaffold (`npm install`), which needs network access. They need `npm` on the machine. The `node-*` and `write-node-*` cases use `node --test` and need no install. The cases `write-mixed-rust-ts` and `write-mixed-rust-node` also need `cargo` and `cargo-nextest`.

Not covered by a case in this ticket: the reply `none`, and a reply after a report with zero rows. The grammar text of `review.md` states them.
