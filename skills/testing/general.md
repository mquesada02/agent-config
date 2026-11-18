# General rules

This file is always loaded. It holds every rule id of the skill with its severity, and the rule text of each id that review checks. Language entries (`entries/<language>.md`) hold only how-to and check details. They name ids, but they hold no severity and no rule line.

Severities are fixed per rule. Critical: the test can give a false result (it passes when the code is broken, or it fails at random). Required: the test breaks a runnable property (speed, isolation, parallel safety, grouping). Suggestion: style and maintainability.

## Catalogue

The script constant `CATALOG` in [scripts/intake.py](scripts/intake.py) lists the same ids with the same severities. A structure test checks that both match.

| Id | Severity | Rule |
|---|---|---|
| ASSERT-01 | critical | A test has no assertion. |
| ASSERT-02 | critical | A tautological assertion: the expected value is a literal or variable that the same test passes in unchanged, or the configured return of a mock. |
| ASSERT-03 | critical | A snapshot holds a nondeterministic value without a redaction, or a snapshot run writes new snapshots without failing. |
| RUN-01 | critical | A retry or rerun hides a flaky test. |
| RS-01 | critical | Doc tests are not run when nextest is the runner, so the run can pass while they never ran. |
| RUN-02 | required | A real sleep or wall-clock wait. |
| RUN-03 | required | Real network in a small or medium test. |
| RUN-04 | required | A small test is over `small_ms`, or a medium test is over `medium_ms`. |
| PAR-01 | required | A fixed port. |
| PAR-02 | required | Shared state between tests (global or static state, shared files, working directory, environment variables). |
| GRP-01 | required | A test that no group selects, or a test in a small group that uses I/O or a sleep. |
| TS-01 | required | A watch-mode command is used as the single-run command. |
| RUN-05 | suggestion | An ignored or skipped test has no reason. |
| DBL-01 | suggestion | A mock asserts call order where a fake would do. |

## Rules

Review checks an id only when this section holds a subsection for it. A catalogue id without a subsection is not checked yet.

### ASSERT-01

**Finding when**: a test body runs code and then checks nothing: no assert, expect, should, check of a returned error, or a framework call that fails the test. A test that only calls the code under test, or only prints the result, is a finding. A test whose only check is that the code did not throw is a finding, unless the framework treats a throw as the check and the test name says so.

**Not a finding when**: the test fails on a wrong result through a helper that the test calls and that asserts inside (read the helper). A test that expects a failure through the framework (an expected-panic or expected-throw marker, or `rejects` and `throws` checks) has an assertion.

**Fix**: add an assertion on the result or on the visible effect. Compare with a value that the test writes by hand, not with a value that comes from the code under test.

### ASSERT-02

**Finding when**: the assertion compares a value with itself or with the input that the same test passed in unchanged (for example, the test builds `x`, calls `f(x)` and asserts that the result equals `x` when `f` must change it). Also a finding when the expected value is the configured return value of a mock or stub that the test set up, so the assertion proves only the setup.

**Not a finding when**: the function really must return its input unchanged (an identity or a no-op case), and the test name or a comment says so. Also not a finding when the mock return value only feeds the code under test and the assertion checks what the code did with it.

**Fix**: assert a literal that you computed by hand from the spec, or assert on the effect that the code has after it used the double.

### ASSERT-03

**Finding when**: a snapshot (a stored file or an inline snapshot) holds a value that changes between runs (a timestamp, a random id, an absolute path, a process id, an order that is not fixed) and the test has no redaction or matcher for it. Also a finding when the single-run test command or the runner config writes new or changed snapshots without failing (an update flag or an update mode, such as `-u`, `--update`, `INSTA_UPDATE=always` or `UPDATE_SNAPSHOTS`), so a changed snapshot cannot fail the run.

**Not a finding when**: the value is redacted, replaced by a fixed placeholder or checked by a matcher before it is stored. An update flag in a separate command that a person runs on purpose (a script named `update-snapshots`) is not a finding, because it is not the single-run command.

**Fix**: redact or fix the nondeterministic value (inject the clock or the id source, or replace the value with a placeholder) and remove the update mode from the single-run command.

### RUN-01

**Finding when**: a retry hides a flaky test. This is a retry setting in the runner config (for example nextest `retries`, Vitest `retry` or a `retry` option on a test) or a retry or rerun wrapper in test code (a loop that runs the check again until it passes, or a script that reruns failed tests). The check is by reading the config and the code.

**Not a finding when**: the run still fails on a test that passes only after a retry. For example, nextest `retries` together with `flaky-result = "fail"` hides nothing. A retry inside the code under test (a retry policy that the test checks) is not a retry of the test.

**Fix**: remove the retry and find the cause of the flaky test (shared state, a real clock, a fixed port, an ordering assumption). When the retry must stay for a known outside cause, set the runner so that a test that passes only after a retry still fails the run.
