# Rust entry

This file is loaded for a file whose `detected.entries` value is `rust`, after [general.md](../general.md). It holds how-to and check details only. The rule text, the severities and the report contract live in the general file, in [review.md](../review.md) and in [write.md](../write.md). The library facts below come from [docs/research/testing-rust.md](../../../docs/research/testing-rust.md); they are research facts, not decisions of the Rust docs.

## Detection notes

Read these intake facts of the language `rust` first: `detected.facts.rust.runner.name` (`nextest` or `cargo test`), `.commands.test`, `.commands.worker_flag`, `.commands.doc`, `.groups` and `.layout.members`. The rules file value wins over the detected fact (`rules.settings.commands.rust`, `rules.settings.runner.rust` and `rules.settings.groups`).

- A crate is a folder with a `Cargo.toml` that has a `[package]` table. A workspace root with only `[workspace]` is not a crate. The crates of a language root are the members of `layout.members`, or the root crate.
- The effective doc command is the recorded `commands.rust.doc` string, else `detected.facts.rust.commands.doc`. The detected value is `cargo test --doc` when nextest is the runner and a library target has doc tests on, else null.
- Read the manifest of each crate for `[lib]` (`doctest = false` turns doc tests off), `[[test]]` tables, `autotests = false` (a crate with either has no default test layout) and `[package] name` (the value of `-p`).
- Read `.config/nextest.toml` for `retries`, `flaky-result`, profiles and the `[test-groups]` table.
- A neighbour of `src/main.rs` with no `src/lib.rs` is a binary-only crate: an integration test cannot import it.

## Commands

The single-run forms are `cargo nextest run` and `cargo test`. The doc command is `cargo test --doc` (nextest does not run doc tests). Neither runner has a changed-files command, and this entry names none.

- Worker flag for 2 workers: `cargo nextest run -j 2` (or `--test-threads 2`, before any `--`). For `cargo test` the form is `cargo test -- --test-threads=2`. When a `--` list is already in the command, merge `--test-threads=2` into that list (replacing a `--test-threads` that is there). Never add a second `--`.
- List command, for the membership of a nextest group: take the group command, replace the `run` subcommand with `list`, drop the options that only a run uses (the worker flags, `--no-fail-fast`, reporters, `--retries`) and add `--message-format oneline`. Each output line is `<binary id> <test name>`. The binary id is the package name for the library target and `<package>::<target>` for an integration target. A test of the library target belongs to no in-scope file. There is no list command for `cargo test` groups.
- Narrowing a run to one test target: add `-p <package> --test <target>` to the command, before any `--`. Do it only when every in-scope Rust test file is a file of one integration target (`tests/<target>.rs`, `tests/<target>/main.rs` or a file below `tests/<target>/`) of one crate with the default test layout, and the command holds no token of the crate scope, file selector, doc flag or unreadable selector class of the table below. Every other case runs the command as it is and keeps only the in-scope test cases.
- Per-test durations: nextest prints one line per passing test, `PASS [   0.005s] <binary id> <test name>`, at the default status level. `cargo test` prints no per-test duration.

### Group selector table

Read a group command as tokens. Skip leading `NAME=value` assignments. A flag with a value reads the same in the forms `--flag value` and `--flag=value`. Each token has one class.

| Class | Tokens | Review reads it as | Write: can the group select a file |
|---|---|---|---|
| Crate scope | `-p`, `--package` | the group applies to the crate whose `[package]` name equals the value (a Cargo manifest counts as the runner config); no such token means every crate | same |
| File selector | `--test <target>` | the files of that integration target: `tests/<target>.rs`, or `tests/<target>/main.rs` and the files below `tests/<target>/` | only when that target holds the file |
| Name filter | a token that is not a flag and not the value of a flag that takes a value | a name filter; with a file selector the group selects the intersection | no file |
| Doc flag | `--doc` | selects only doc tests, which are not in-scope test cases: no in-scope test case, not unreadable, not listed | no file |
| Unreadable selector | `--lib`, `--bin`, `--bins`, `--tests`, `--example`, `--examples`, `--bench`, `--benches`, `--all-targets`, `-E`, `--filterset`, `--exclude`, `--skip`, `--exact`, `--ignored`, `--include-ignored`, `--run-ignored` | unreadable (see below) | no file |
| Other | worker flag, reporter, profile, features, `--workspace`, `--no-fail-fast`, every other token | selects nothing | selects nothing |

- A group with a token of the unreadable selector class is unreadable. For a nextest group the list command above decides its membership; when that command fails, the group stays unreadable and the `Not checked:` line names it. A `cargo test` group stays unreadable and the `Not checked:` line names it.
- When a group has tokens of several classes, the first class present in this order gives its state: doc flag, unreadable selector; otherwise the file selector and the name filter select the intersection.
- For write, a group selects a file when it applies to the crate of the file, has no token of the name filter, doc flag or unreadable selector class, and either has no file selector (it selects every file of the crate) or has a `--test` target that holds the file. Write runs no list command, because its file may not exist yet.

## Runner facts

Each fact below is confirmed from the docs on 2026-11-20, or is marked as unconfirmed and not used.

- Confirmed: `cargo nextest list` takes most options of `cargo nextest run`, `-E` filtersets and `--message-format oneline`, with one `<binary id> <test name>` line per test; the binary id is `<package>` for the library target and `<package>::<target>` for an integration target (https://nexte.st/docs/listing/)
- Confirmed: Narrowing flags for `cargo test` are `-p <package>` and `--test <target>`, before the `--` separator (https://doc.rust-lang.org/cargo/commands/cargo-test.html)
- Confirmed: Narrowing flags for nextest are `-p, --package` and `--test` (https://nexte.st/docs/running/)
- Confirmed: Test target layout: `tests/<name>.rs` and `tests/<name>/main.rs` are integration test targets, a file below `tests/<name>/` is a module of that target, and `autotests = false` and `[[test]]` tables change this (https://doc.rust-lang.org/cargo/guide/project-layout.html and https://doc.rust-lang.org/cargo/reference/cargo-targets.html)
- Confirmed: Retries: `retries` (profile setting, `--retries`, `NEXTEST_RETRIES`) and `flaky-result = "fail"` (profile or per-test override setting, `--flaky-result fail`, `NEXTEST_FLAKY_RESULT=fail`, needs nextest 0.9.131 or newer) fails a run on a test that passes only on retry (https://nexte.st/docs/features/retries/)
- Confirmed: Profile inheritance: a custom profile inherits from the `default` profile (https://nexte.st/docs/configuration/)
- Confirmed: Nextest durations: the run output has one line per test, `PASS [   0.005s] <binary id> <test name>` (https://nexte.st/docs/running/); the default `--status-level` is `pass`, so a lower level removes these lines (https://nexte.st/docs/reporting/)
- Confirmed: Worker flag: nextest `-j N` is `--test-threads N` (https://nexte.st/docs/running/); `cargo test` takes `-- --test-threads=N` (https://doc.rust-lang.org/cargo/commands/cargo-test.html)
- Confirmed: Execution model: `cargo test` runs tests as threads of one process (https://doc.rust-lang.org/book/ch11-02-running-tests.html); nextest runs one process per test (https://nexte.st/docs/design/why-process-per-test/)
- Confirmed: Doc tests: nextest does not run doc tests, and `cargo test --doc` runs them (https://nexte.st/docs/running/ and https://doc.rust-lang.org/cargo/commands/cargo-test.html)
- Confirmed: Doc test switch and fences: `[lib] doctest = false` turns doc tests off; rustdoc runs a fenced block unless it has the `ignore` attribute or a `text` or other-language tag, and `no_run`, `compile_fail` and `should_panic` blocks are still doc tests (https://doc.rust-lang.org/cargo/reference/cargo-targets.html and https://doc.rust-lang.org/rustdoc/write-documentation/documentation-tests.html)
- Unconfirmed, not used: a per-test duration of `cargo test`, a list command for `cargo test` groups, a list command for doc tests, JUnit output for durations, and a changed-files command. Every runner fact that this entry uses has a `Confirmed:` line above.

## Layout

- Integration tests are in `<crate root>/tests/`. They use the public interface only: each file is its own crate. Put shared helpers in `tests/common/mod.rs`, never in `tests/common.rs` (that file would be a test crate with no tests).
- Inline `#[cfg(test)] mod tests` units stay in the product file. They are out of reach of write, which edits no product file. Write never writes a doc test either.
- The `layout.rust.test_paths` and `file_pattern` settings are read for detection only. They do not decide a test location.
- Path derivation (the path that a loaded entry derives for a product file). The path is `<crate root>/tests/<stem>.rs`. The crate root is the nearest crate folder up the tree from the product file; a nearer binary-only crate is the crate root, so it gives no path. Derive a path only when the product file is under `<crate root>/src/` and the crate has `src/lib.rs` and the default test layout.
  - The stem is the path under `src/` without `.rs`, with `/` replaced by `_` and a trailing `/mod` dropped.
  - Derive no path when `tests/<stem>/` already exists, for `main.rs`, `build.rs`, a file under `src/bin/`, `src/mod.rs`, a stem `common` and a file outside every crate.
  - Product files with the same stem share one test file, which belongs to each of them. When the file exists, write adds its test cases to it.
- Group path. When a recorded group selects the derived path for write, the derived path is the location. When none does, the location is the first existing target file of a group that selects files for write with `--test <target>` flags: the groups in the order of the rules file, then each `--test` flag in order, with `tests/<target>.rs`, else `tests/<target>/main.rs`, when the file exists in the crate of the product file. Write adds its test cases to that file and edits no other file and no existing test case.

## Libraries

These facts come from the research file named above. The detected library facts (`detected.facts.rust.libraries`) decide which of them apply.

- Property: `proptest` (256 cases by default, `PROPTEST_CASES` overrides it; `proptest-regressions/` holds saved failing cases and follows `commit_regressions`) or `quickcheck`. A property test states a property: a round trip, an invariant or a comparison with a simple model.
- Snapshot: `insta` (`assert_snapshot!`, `assert_yaml_snapshot!`, `assert_debug_snapshot!`; a `.snap` file follows `commit_snapshots`). Use redactions for a nondeterministic value. The single-run command never sets `INSTA_UPDATE=always` and never uses `cargo insta test --accept`. With the `CI` variable set, insta writes no new snapshot file.
- Fakes: write a fake by hand behind a trait first. Use `mockall` (the detected value) only when a call count is the behavior.
- Async: `#[tokio::test]` with `start_paused = true` (needs the `test-util` feature and the current-thread runtime) for time. Only Tokio's `Instant` is paused.

## Rules

### ASSERT-01

**How to write**: end each test with `assert!`, `assert_eq!`, `assert_ne!`, a `matches!` check inside `assert!`, or a returned `Result` that the test body checks. A test that returns `Result<(), E>` and uses `?` fails on an error, but it still needs an assertion on the value. Use `#[should_panic(expected = "...")]` for an expected panic (never together with a `Result` return).

**Check details**: a `#[test]` function with no `assert` family macro, no `should_panic` attribute and no `unwrap_err`, `unwrap_or_else(|_| panic!())` or `expect_err` call is a candidate. A test that only calls the code under test or prints with `println!` has no assertion. Read helper functions that assert inside.

### ASSERT-02

**How to write**: compute the expected value by hand from the spec and write it as a literal. Do not pass the input back as the expected value. For a mock, assert on the effect that the code has after it used the double.

**Check details**: look for `assert_eq!(x, x)`, `assert_eq!(f(x), x)` where `f` must change `x`, and an `assert_eq!` whose expected side is the value that a `mockall` `returning(...)` call set.

### ASSERT-03

**How to write**: redact a timestamp, a random id, an absolute path or an unordered map with an insta redaction (`with_settings!` filters or `redactions`), or inject the clock or the id source. Run snapshots in the single-run command without an update mode.

**Check details**: read the single-run command, the runner config and the CI variables for `INSTA_UPDATE=always`, `INSTA_FORCE_PASS`, `cargo insta test --accept` and `--force-update-snapshots`. Read each `.snap` file and each inline snapshot for a value that changes between runs. A `cargo insta review` script that a person runs is not the single-run command.

### RUN-01

**How to write**: keep nextest retries off. When a retry must stay for a known outside cause, set `flaky-result = "fail"` next to `retries` so that a test that passes only on retry still fails the run.

**Check details**: read `.config/nextest.toml` for `retries` in the profile in use and in `[[profile.<name>.overrides]]`, and the command for `--retries` and `NEXTEST_RETRIES`. A custom profile inherits `retries` from the `default` profile. `flaky-result = "fail"` (in the profile, in an override, or `--flaky-result fail`, or `NEXTEST_FLAKY_RESULT=fail`) means the retry hides nothing. Also read test code for a loop that runs a check again until it passes.

### RUN-02

**How to write**: pause time with `#[tokio::test(start_paused = true)]` and advance it, or wait for the event (a channel receive, a join, an awaited future). Do not call `std::thread::sleep` or `tokio::time::sleep` on the real clock.

**Check details**: look for `std::thread::sleep`, `tokio::time::sleep`, `async_std::task::sleep` and `Instant::now()` spin loops in test code. A `tokio::time::sleep` in a test with `start_paused = true` is paused time. A sleep in the code under test that a paused clock controls is not a finding.

### RUN-03

**How to write**: use an in-process fake behind a trait. For a medium test bind `127.0.0.1:0`. Never connect to another host.

**Check details**: look for `TcpStream::connect`, `TcpListener::bind`, `UdpSocket`, `reqwest`, `hyper` clients and `ureq` calls in test code. A bind to port 0 on loopback is loopback network.

### RUN-04

**How to write**: fake the slow I/O or time, shrink the work, or move the test to a group of a larger size.

**Check details**: use the timed run of [review.md](../review.md). With nextest, read the `PASS [<seconds>] <binary id> <test name>` lines of the default output and match each in-scope test case by its name. Do not add `--status-level` or a reporter flag. When the runner is `cargo test`, the output holds no per-test duration, so the `Not checked:` entry is `RUN-04 (no per-test duration in the output (exit code N))`.

### RUN-05

**How to write**: give `#[ignore = "reason"]` a reason string, or fix or delete the test.

**Check details**: look for `#[ignore]` with no `= "..."` string and no comment line above it, and for a skip written as an early `return` under a constant condition.

### PAR-01

**How to write**: bind `127.0.0.1:0` and read the port with `local_addr()`.

**Check details**: look for a literal port in `bind`, `connect`, `TcpListener::bind("127.0.0.1:8080")`, `SocketAddr::from(([127, 0, 0, 1], 8080))` and in a constant or an environment default that a test uses.

### PAR-02

**How to write**: give each test its own state: a `tempfile::tempdir()`, a value that the test owns, no `static mut`, no `std::env::set_var` and no `std::env::set_current_dir`. Under `cargo test` the tests of one binary share one process, so global state leaks between them; nextest runs one process per test, which hides the fault but does not fix it.

**Check details**: look for `static mut`, a `static` with a `Mutex`, `OnceLock` or `lazy_static` that a test writes, `std::env::set_var`, `std::env::set_current_dir`, a fixed path such as `/tmp/x` or `./out.txt`, and a shared database name.

### GRP-01

**How to write**: put the test case where a recorded group selects it. For a small group use no file system, child process, database or sleep. A test in `tests/<target>.rs` is selected by a group with no selector, by `-p <package>` alone, or by `--test <target>`.

**Check details**: read each group command with the group selector table above. A group with a token of the unreadable selector class on a nextest command is decided by `cargo nextest list` (see Commands). Map each listed `<binary id> <test name>` line to a file through the integration target; a test of the library target belongs to no in-scope file. A `cargo test` group with an unreadable selector stays unchecked. Read `std::fs`, `std::process::Command`, `tempfile` and database client calls for the I/O half of the rule.

### DBL-01

**How to write**: write a fake by hand behind a trait and assert on its state. Use `mockall` only when a call count is the behavior.

**Check details**: look for `in_sequence`, `Sequence` and a chain of `expect_<method>().times(..)` calls whose order is asserted.

### RS-01

**How to write**: a doc test is a fenced block in a `///` or `//!` comment of the library target. Write the example so that it compiles and runs; hide setup lines with a leading `#`; end an example that uses `?` with a hidden `Ok::<(), E>(())` line. Use `text` or a hidden line, not `ignore`, for a block that must not run. Run doc tests with the doc command `cargo test --doc`, and record it in `commands.rust.doc`. Add a group whose command runs it when the language has groups. Write adds no doc test.

**Check details**: read the three conditions of the rule in the general file this way. (1) The runner: the `name` key of the rules-file table `[runner.rust]`, else `detected.facts.rust.runner.name`; both absent means not nextest. (2) Doc tests exist: a crate under the root has `src/lib.rs` and no `doctest = false` in `[lib]`, and a `.rs` file under that crate's `src/` has a fenced block (a line that starts with three backticks or three tildes) in a `///` or `//!` comment that rustdoc compiles (no attribute that starts with `ignore`, no `text` or other-language tag; `no_run`, `compile_fail` and `should_panic` blocks count). Do not scan `/** */` comments, `#[doc]` attributes or indented blocks. (3) The doc tests are not run: with at least one Rust group, no group command runs doc tests; with none, the effective doc command is null or an empty string. A group command runs doc tests when it is a `cargo test` command that has `--doc`, or has no token of the unreadable selector class and no `--test`. A `cargo nextest` command never does. A group command that starts with neither `cargo test` nor `cargo nextest` is not decided. The `Where` cell lists the rules-file line of the `doc` key and the line of the first Rust `[[groups]]` table; when neither exists, it lists `<root>/Cargo.toml:1` of each failing root.

## Design how-to

- Kinds: unit for pure logic (in the product file, out of reach of write, or in `tests/` through the public interface); integration for a boundary or local I/O in `tests/`; property with `proptest` for an invariant; snapshot with `insta` for a structured output.
- Sizes: a small test case uses no I/O and no sleep; a medium test case may use a temp directory (`tempfile`) and loopback on port 0.
- Doubles: put I/O, the clock, the network and randomness behind a trait. Pass the implementation as a generic parameter or a `Box<dyn Trait>`. A real collaborator first, then a hand-written fake.
- Parallel safety: each test owns its temp directory and its port. Do not rely on test order. Under `cargo test` the tests of one binary run as threads of one process.
- Flakiness: find the cause (shared state, the real clock, a fixed port, unordered collections, threads). Do not hide it with a retry.
- Test points: the public interface of the crate (what `tests/` can import) and the system boundaries. Keep `main.rs` thin and put the logic in `src/lib.rs`, so that it can be tested through the public interface.
