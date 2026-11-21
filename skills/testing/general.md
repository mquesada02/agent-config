# General rules

This file is always loaded. It holds every rule id of the skill with its severity, and the rule text of each id that review checks. It also holds three sections of rule text that have no id: `## Kinds of tests`, `## Test points` and `## Design topics`. Write follows them. Language entries (`entries/<language>.md`) hold only how-to and check details. They name ids, but they hold no severity and no rule line.

Severities are fixed per rule. Critical: the test can give a false result (it passes when the code is broken, or it fails at random). Required: the test breaks a runnable property (speed, isolation, parallel safety, grouping). Suggestion: style and maintainability.

## Catalogue

The script constant `CATALOG` in [scripts/intake.py](scripts/intake.py) lists the same ids with the same severities. A structure test checks that both match. An id has rule text only when `## Rules` holds a subsection for it.

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

## Sizes and groups

A test case has a size. The size tells what the test case may use and how long it may take.

- Small: no I/O, no network, no sleep. At most `small_ms` (default 100 ms).
- Medium: local I/O and loopback network only. At most `medium_ms` (default 1000 ms).
- Large: no limit. A large test case lives only in its own group.

The limits come from `rules.settings.limits`, else from `detected.facts.<language>.limits`. `RUN-02` applies at every size. A group of the rules file has a `name`, a `language`, a `size` and a `command`. These groups are not the nextest `test_groups` fact, which limits concurrency.

### Test cases and scope

A test case is one test function or one case in a test file. The files in scope are the files that step 1 of the review flow takes. The in-scope test cases are the test cases of those files. Review checks the in-scope test cases. The size is per test case. The language root of a language is the `root` of its `[[languages]]` entry, else the root of its detected language. The language of a file is its `detected.entries` value. The value `general` has no group, so its test cases have no sizes.

### Size and group of a test case

The size of a test case is the `size` of the group whose `command` selects it. Only the groups of the language of the test case's file count. A test case that several readable groups select takes the smallest size.

A group selector is **readable** when the command, apart from the runner and its fixed flags, uses only:

- no selector: it selects every test case of the language root;
- path or glob operands: they select every test case in the files they match, and a directory operand selects every test case in the files below it. Several operands select the union;
- a name filter: a substring or a pattern on the test name, or a module path. Several name filters select the union;
- a project or package flag whose root the runner config names: it selects every test case under that root.

Path operands and a name filter together select the intersection. Fixed flags do not change which tests run: worker count, reporter, color and output options. Any other selector or flag makes the group **unreadable**: a tag or attribute filter, a boolean expression of filters (with and, or or not), an exclude or ignore flag, an environment variable or a wrapper script.

A loaded language entry may name further selector forms as readable. A group with a missing `size`, or a `size` that is not `small`, `medium` or `large`, is unreadable. A runner list command may decide membership only when a loaded language entry names that command as confirmed. When that command cannot start, exits with an error or runs longer than 10 minutes, the group is unreadable.

An unreadable group leaves its tests unchecked:

- A test case that no readable group selects, while an unreadable group of its language exists, is **unsized**. `GRP-01`, `RUN-03` and `RUN-04` skip it.
- A test case that a readable group selects takes the smallest size among the readable groups. An unreadable group might also select it. The `Not checked:` line says so.
- A test case that no group selects, when its language has at least one group and every such group is readable, is a `GRP-01` finding. `RUN-03` and `RUN-04` skip it.

A language with no group (none in `rules.settings.groups`, none in `detected.facts`) has no sizes. `GRP-01`, `RUN-03` and `RUN-04` are not checked for it, and it gets no `GRP-01` finding. A large test case needs no extra rule: when a smaller group also selects it, the smallest size makes it small, and `GRP-01`, `RUN-03` and `RUN-04` apply.

## Doubles and seams

A seam is a point where behavior can be swapped without editing the code under test: a function argument, an injected dependency, a trait or interface, a module boundary, the clock, the file system or the network at the system boundary.

- Tests go through the public interface. Put a double at a system boundary, not between two internal functions.
- Prefer, in this order: a real collaborator, a fake, a stub, a mock.
- Use a mock only to prove an outbound side effect that has no readable state.
- Keep a fake honest: test it, or share a contract test with the real code.

`DBL-01` is the rule for mocks that assert call order.

## Parallel safety

A test is safe to run in parallel when it owns all state that it touches.

- Use a unique temp directory. Do not write into the working directory.
- Use port 0 or a free port. Never a fixed port (`PAR-01`).
- Do not read or write global or static state, a fixed file path or an environment variable that another test uses (`PAR-02`).
- Do not rely on the order of tests or on the output of another test.

## Flakiness

A flaky test gives a different result for the same code. Common causes: sleeps and wall-clock waits (`RUN-02`), shared state (`PAR-02`), test order, the clock, randomness, fixed ports and temp paths (`PAR-01`), network (`RUN-03`), threads and unordered collections. Find the cause. Do not hide it with a retry (`RUN-01`).

## Kinds of tests

A test has one of four kinds.

- Unit: it checks pure logic, with no I/O.
- Integration: it checks a boundary between parts, or local I/O.
- Property: it checks an invariant of the contract for many inputs.
- Snapshot: it checks a structured output against a stored value.

Pick the kind from the change. The first line that fits wins:

1. An invariant of the contract that holds for many inputs: property.
2. A structured output that a stored value shows: snapshot.
3. A boundary between parts, or local I/O: integration.
4. Else, pure logic: unit.

The kind and the size are separate choices. Choose the kind first. The size depends on what the test case uses, as `## Sizes and groups` says.

- Write only small or medium test cases: small uses no I/O, no network and no sleep, and medium uses local I/O or loopback network.
- Replace any other use (a sleep, a non-loopback network, a child process, a database or another service) with a double or a fake clock, as `## Doubles and seams` says.
- Doubling a boundary does not change the kind.
- A `large` group size is only the Size cell value that review gives. The test cases are still small or medium.

## Test points

The test points are the public interface (what a caller can reach) and the system boundaries (the file system, the network, the clock, a process, a database and other services).

- A test goes through a test point. It does not call a function that no caller reaches.
- A boundary is replaced as `## Doubles and seams` says.

## Design topics

### Level to test at

Test at the lowest level at which the behavior is visible through a test point. Use a higher level only for behavior that spans parts.

### Failure paths and edge cases

For each test point, cover the error returns, the invalid input, and the empty and boundary values that the source of the expected value names. Each case has its own test case.

### Naming and structure

- A test name states the behavior and the condition.
- One test case checks one behavior.
- A test case follows the order arrange, act, assert.
- Helpers and fixtures are shared by name, not by order.

## Rules

Review checks an id only when this section holds a subsection for it. A catalogue id without a subsection is not checked yet. The sections `## Kinds of tests`, `## Test points` and `## Design topics` hold rule text without an id. Review does not check them.

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

### RUN-02

**Finding when**: a fixed-duration wait in test code: a sleep, a timer wait, a poll loop that sleeps a fixed step, or a loop that spins until the wall clock passes a time. The sleep call is the finding, even when the loop ends early. This holds at every size. A sleep inside the code under test that no fake clock controls is not test code. It is not a `RUN-02` finding, and the slow test shows in `RUN-04`.

**Not a finding when**: time is fake or paused. Also not a finding: a call that blocks on the event itself (a channel receive, a join, an awaited promise, a wait helper of the test framework that polls inside the framework), and a sleep inside code under test that a fake clock controls.

**Fix**: fake or pause time, or wait for the event.

### RUN-03

**Finding when**: a small test uses the network in any way, loopback included. Or a medium test connects to a host other than `localhost`, `127.0.0.1` or `::1`. A large test is not checked.

**Not a finding when**: the test is large. Also not a finding: a fake server that runs inside the process and opens no socket, and loopback in a medium test.

**Fix**: use an in-process fake, or move the test to a medium group (loopback only) or to a large group.

### RUN-04

**Finding when**: the timed run gives a duration for a sized test case that is strictly over the limit of its size: over `small_ms` for a small test case, over `medium_ms` for a medium test case. See "Timed run" in [review.md](review.md).

**Not a finding when**: the duration is at or under the limit, or the test case is large or unsized.

**Fix**: fake the slow I/O or time, shrink the work, or move the test to a group of a larger size.

### RUN-05

**Finding when**: a test is ignored or skipped (a skip or ignore marker, or a conditional skip whose condition is a constant such as a literal `true`) and the marker or the line above holds no reason text. A platform or environment condition is not constant.

**Not a finding when**: the marker has a reason. Also not a finding: a pending-test placeholder that is not a skip.

**Fix**: give the reason, or fix or delete the test.

### PAR-01

**Finding when**: a test uses a literal port number (also one held in a constant or an environment default) to bind, to listen, to start a server, or to connect as a client to a server that the same test starts.

**Not a finding when**: the port is 0, or a free port taken at run time. Also not a finding: a port in a URL to a non-local host.

**Fix**: use port 0 or a free port.

### PAR-02

**Finding when**: two tests share state: a global or static variable that a test writes, a file at a fixed path, a change to the working directory or a write into it, an environment variable set without a restore, or a shared database name.

**Not a finding when**: each test creates and removes its own state (for example a unique temp directory), or the shared value is a read-only constant.

**Fix**: give each test its own state.

### GRP-01

**Finding when**: a test case that no group selects, when its language has at least one group and every such group is readable (see "Size and group of a test case"). Also a finding: a test case in a small group that uses I/O (file system, child process, database) or a sleep, in the test or in the code under test that it calls. Network use is not a `GRP-01` case; `RUN-03` covers it. Both cases are one `GRP-01` row, and its Where cell lists the places of both.

**Not a finding when**: the file is a helper or fixture file with no test case. Also not a finding: I/O in a test case of a medium or large group, and a sleep that fake or paused time controls.

**Fix**: add the test case to a group (or fix the group command), or fake the I/O or the sleep, or move the test case to a medium group.

### DBL-01

**Finding when**: a test asserts the order of calls on a mock (a sequence or in-order check) where a fake or a state check would show the same behavior.

**Not a finding when**: the order is the behavior, for example an ordered outbound side effect that has no readable state.

**Fix**: use a fake and assert on state, or drop the order check.

### RS-01

**Finding when**: `RS-01` is checked when at least one in-scope file has the `entries` value `rust`. It gives one row in all. For each Rust language root it is a finding when all three hold:

1. The Rust runner is nextest: the `name` key of the rules-file table `[runner.rust]`, else `detected.facts.rust.runner.name`. When both are absent, the runner is not nextest.
2. Some crate under the root has doc tests: a `src/lib.rs` whose `[lib]` has no `doctest = false`, and a fenced code block in a `///` or `//!` comment of a `.rs` file under that crate's `src/` that rustdoc compiles (see the Rust entry for the exact reading).
3. The doc tests are not run. With at least one Rust group in the language, no group command runs doc tests (the doc command does not matter). With no Rust group, the effective doc command is null or an empty string. The effective doc command is the recorded `commands.rust.doc` string, else `detected.facts.rust.commands.doc`; a missing recorded key is not a finding when detection supplies the command. A group counts whatever its crate scope. A group command runs doc tests when it is a `cargo test` command that has `--doc` or has no token of the unreadable selector class and no `--test` flag (see the group selector table of the Rust entry); a `cargo nextest` command never does.

A Rust group command that starts with neither `cargo test` nor `cargo nextest` is not decided. It counts as neither running nor not running doc tests, `RS-01` is not reported for that language, and `Not checked:` gets the entry `RS-01 (group <name> command is not a cargo command)`. Write that entry only when conditions 1 and 2 hold and no decided group command runs doc tests. The `Where` cell lists the places that exist: the rules-file line of the `doc` key and the line of the first Rust `[[groups]]` table. When neither exists, it lists `<root>/Cargo.toml:1` of each failing root.

**Not a finding when**: the runner is not nextest; no crate under the root has doc tests; no group exists and the effective doc command is non-empty; or some group command runs doc tests.

**Fix**: record `commands.rust.doc` as `cargo test --doc` and, when the language has a group, add a group whose command runs it.

### TS-01

**Finding when**: `TS-01` is checked when at least one in-scope file has the `entries` value `typescript`, and only for a runner whose watch forms a loaded entry names. It gives one row in all. It is a finding when the single-run command starts the runner in watch mode, or leaves the choice between watch and run to the terminal. The commands in scope are the recorded single-run test command (else the `test` script of the language root `package.json`) and every group command of the language. A wrapper script that hides the runner command is not decided: it gives no finding, and `Not checked:` gets one entry for it (the entry form is in the loaded entry). The `Where` cell lists the rules-file line of the command and, for a resolved script, the line of the script.

**Not a finding when**: the single-run command runs once (a run subcommand or a run flag); the command is a list or benchmark command; the runner is not covered by a loaded entry (it is not checked and gets no `Not checked:` entry); or no file of the language is in scope.

**Fix**: record a single-run command that runs once and does not watch, and put no watch command in a group.
