# Test suite timing

Research for issue 997 (group A: measure only, no fix). One run of the declared test command, with per-test durations.

## Method

- Same 13 test folders as the declared test command, in one process, with `unittest.TextTestRunner(durations=0)` (Python 3.12.3).
- One process only (section 15). The machine was shared with other sessions, so treat each number as approximate.
- Result: 6484 tests, 3097 s, all pass, 1 skipped. The timing table lists the 5052 tests of 0.001 s or more (3054 s); the other 1432 tests took under 0.001 s each. Every share below uses the 3097 s total.
- Spot check, outside the timed run: `python3 -I -c pass` takes about 48 ms. `extract.py` on an empty file takes about 277 ms. Each used 5 to 10 runs.

## Time per folder

| Folder | Tests of 0.001 s or more | Seconds |
|---|---|---|
| `skills/sql/tests` | 1532 | 1161 |
| `hooks/workflow-audit` | 1090 | 948 |
| `hooks/context-handoff` | 301 | 516 |
| `skills/cicd-pipelines/tests` | 552 | 127 |
| `hooks/worktree-cleanup` | 232 | 122 |
| `skills/testing/tests` | 320 | 90 |
| `hooks/redact-secrets` | 887 | 50 |
| other 6 folders | 138 | 39 |

## Time per test size

| Test duration | Tests | Seconds |
|---|---|---|
| 10 s or more | 28 | 1366 (44%) |
| 1 s to 10 s | 302 | 634 |
| 0.1 s to 1 s | 2716 | 970 |
| under 0.1 s | 2006 | 84 |

## Slowest classes

| Class | Tests | Seconds |
|---|---|---|
| `test_sql_pg_run_docker.PgRunWriteDockerTest` | 12 | 366 |
| `test_registration.HookOrderTest` | 9 | 364 |
| `test_launch.TimingTest` | 8 | 289 |
| `test_sql_setup_scan.OutputTest` | 8 | 232 |
| `test_launch.WorkerTimingTest` | 1 | 84 |
| `test_sql_db_driver.DriverTest` | 34 | 41 |
| `test_transcripts.S2Test` | 36 | 35 |
| `test_ledger.LinkRefuseTest` | 19 | 30 |
| `test_sql_pg_run.WriteRunTest` | 18 | 29 |
| `test_sql_pg_run_docker.PgRunDiffDockerTest` | 26 | 28 |

Slowest modules: `test_launch` 489 s, `test_sql_pg_run_docker` 419 s, `test_registration` 364 s, `test_sql_setup_scan` 247 s, `test_sql_pg_run` 134 s.

## 30 slowest tests and their causes

The 30 slowest tests all took 9.7 s or more. The rows below list 34 tests, because four tests of 8.2 s to 9.7 s share a row with slower ones.

| s | Test | Cause (from the code) |
|---|---|---|
| 136, 130, 43, 15, 11 | `PgRunWriteDockerTest` (`skills/sql/tests/test_sql_pg_run_docker.py:721`, `:688`, `:811`, `:759`, `:734`) | Docker Postgres. Per case and per version: one `psql` snapshot (`:660`) and one new script process (`:228`). The case tables are `WRITE_CASES` (`:566`) and `STORED_WRITE_CASES` (`:610`), run for 2 versions (`:18`). |
| 128, 102 | `OutputTest` (`skills/sql/tests/test_sql_setup_scan.py:113`, `:120`) | 1000 files, and one new `extract.py` process per file (`skills/sql/scripts/sql_text.py:343`). About 0.1 s per file. |
| 85, 84, 83, 79 | `TimingTest`, `WorkerTimingTest` (`hooks/context-handoff/test_launch.py:1149`, `:1653`, `:1180`, `:1172`) | Real waiting. The fake Orca calls sleep, and the limits are constants. The test comments say "almost no CPU". |
| 62, 49, 48, 45, 43, 41, 40, 38 | `HookOrderTest` (`hooks/workflow-audit/test_registration.py:146`, `:142`, `:161`, `:170`, `:164`, `:154`, `:151`, `:167`) | 4 hook groups give 24 orders (`:134`). Each order starts every repo hook as a new process (`:101`). About 120 process starts per test, about 0.34 s each. |
| 20, 8, 8 | `LinkRefuseTest`, `LinkLockTest` (`hooks/workflow-audit/test_ledger.py:765`, `:857`, `:866`) | Fake `gh` that sleeps 30 s or 8 s (`:767`, `:859`). Real waiting. |
| 12 | `DbEvalTeardownDockerTest` (`skills/sql/tests/test_sql_db_eval_docker.py:158`) | Docker container and volume teardown. |
| 11 | `test_transcripts.S2Test` (`hooks/workflow-audit/test_transcripts.py:673`) | 36 subtests, and each one calls `self.setUp()` again (`:692`), so each builds a new fixture repo. Not profiled. |
| 11, 10, 10 | `WriteGuardTest`, `GuardTest` (`skills/sql/tests/test_sql_pg_run.py:364`, `:1095`, `:355`) | One new process per refusal form. |
| 10 x5 | `TimingTest` hung-call cases, `WorkerEscalationFailureTest` (`hooks/context-handoff/test_launch.py:1116` to `:1140`, `:1340`) | A fake call sleeps 60 s and the launcher kills it at its 10 s limit. Real waiting. |
| 10, 9 | `PgRunDockerTest` (`test_sql_pg_run_docker.py:307`), `DeniedFormsTest` (`hooks/workflow-audit/test_cleanup_gate.py:24`, `:32`) | A process per case (Docker for the first, git for the others). |

## Where the time goes

| Group | Seconds | Share of 3097 s |
|---|---|---|
| Real waiting (sleep or timeout, almost no CPU): `TimingTest` 289 s and `WorkerTimingTest` 84 s, plus `LinkRefuseTest` 30 s and `LinkLockTest` 17 s | about 420 | 14% |
| Docker Postgres (`test_sql_pg_run_docker.py`, `test_sql_db_eval_docker.py`) | about 430 | 14% |
| Process starts in loops: `HookOrderTest`, `OutputTest` cap tests | 596 | 19% |
| All other tests (mostly 0.1 s to 1 s each) | about 1650 | 53% |

For the last group the data shows the time per test, not the cause. The test count (2716 tests of 0.1 s to 1 s) points to one process per test. I did not profile it.

## Ranked fixes (group B candidates)

Savings are estimates from the table above. They are not measured.

1. **Run 2 processes, each with half of the folders** (section 15 allows 2 workers). The wall time falls toward half if the 2 processes do not slow each other. The machine is shared, so measure it. Estimated saving: up to 1500 s. This also overlaps the real waiting, with no code change. Split by time, not by folder count.
2. **`HookOrderTest`: run each hook once per command, then check the 24 orders in memory.** Check first that no hook keeps state between runs. Estimated saving: about 340 s.
3. **`OutputTest` cap tests: call the extractor in process, or batch the files.** The cap logic does not need a process per file. Estimated saving: about 200 s.
4. **Docker write cases: one snapshot per version, not per case, and fewer script processes.** Estimated saving: 100 s to 200 s. The snapshot protects the "data unchanged" check, so keep a check per group.
5. **Per-class fixtures and in-process calls for the 0.1 s to 1 s tests.** Profile this group first. The saving is unknown until then.

The real-waiting tests cannot be shortened without a test switch. `NoTestSwitchTest` (`hooks/context-handoff/test_launch.py:1197`) forbids one on purpose, so only fix 1 helps them.

## Rust port

Both tools need a Rust toolchain on every machine that runs the hooks.

| | fast-anything | rust-anything |
|---|---|---|
| What it ports | Slow functions inside a running Python process (PyO3) | A whole script or CLI |
| Cuts interpreter start-up per process | No | Yes |
| Helps when | A few functions use most of the CPU in one process | Many short processes dominate |

What the data supports:

- **fast-anything: not supported.** The suite is a set of short processes, not a hot function in one process. The run shows no function that uses the time. The 14% real waiting and the 14% Docker time do not use Python code.
- **rust-anything: supported only in a small part.** The interpreter start (48 ms) is small next to an extractor call (about 277 ms for `extract.py`). Both numbers come from the spot check, not from the timed run. `HookOrderTest` gives about 340 ms per hook start (364 s over about 1080 starts: 9 tests, 24 orders, about 5 hooks; the start count is an estimate). So most of each call is script import and start, which a port would replace. How much of it is computation is not measured. The tests that start these scripts in loops use about 600 s (19%). Fixes 2 and 3 reach about the same saving with no toolchain.

What the data does not support: any port for the 0.1 s to 1 s group (not profiled), and any claim on how much a port saves per call (no port was built).

**Recommendation: neither now.** Do fixes 1 to 3 first, then run this timing again. Consider rust-anything again only for the hook entry points, because a hook runs on every tool call in every session. That gain is outside the test suite. Judge it with a measurement of the real hook call time.
