# Research: runnable tests in Rust

Ticket 813, part of map 810. Date of research: 2026-11-17.

Labels: FACT (with source number from the Sources list), INFERENCE (my reasoning, not stated by a source), UNTESTED (not run on a real repo; no Rust was built or run).

## Short answer

1. `cargo test` is the built-in runner. It runs unit tests, integration tests and doc tests in one command. [S1, S4]
2. `cargo-nextest` is a separate runner. It runs each test in its own process, and it does not run doc tests. [S6, S8]
3. Rust tests have three homes: a `#[cfg(test)] mod tests` in the source file (unit tests, can reach private items), files in `tests/` (integration tests, public API only), and `///` examples (doc tests). [S2, S3, S5]
4. Parallelism and isolation differ. `cargo test` runs tests as threads in one process per binary. `nextest` runs one process per test. Shared global state is the main risk with `cargo test`. [S1, S6]
5. Test groups in `nextest` (`.config/nextest.toml`) cap concurrency for a subset of tests. They are the closest match to the map's "groups". Built-in alternatives are `#[ignore]`, name filters, `--test`, `--lib`, and `required-features`. [S7, S1, S3, S4, S9]
6. Property tests (`proptest`, `quickcheck`) and snapshot tests (`insta`) are libraries added as dev-dependencies. Both write or read files that should be committed or reviewed. [S10, S11, S12, S13]
7. Traits are the usual seam for fakes. `mockall` generates mocks for traits. Hand-written fakes need no library. [S14] (the "seam" advice is INFERENCE)
8. Async tests need a runtime. `#[tokio::test]` gives each test its own single-threaded runtime by default. [S15]
9. Detecting the setup is file-based: `Cargo.toml`, `.config/nextest.toml`, `tests/`, dev-dependencies, and `proptest-regressions/` or `snapshots/` directories. [S4, S9, S10, S12]
10. Default fast loop (candidate): `cargo nextest run` for tests plus `cargo test --doc` for doc tests, falling back to `cargo test` when `nextest` is absent. [S8]

## Findings by topic

### 1. `cargo test`

- FACT: Synopsis is `cargo test [options] [testname] [-- test-options]`. Options before `--` go to Cargo, options after go to the libtest harness. [S4]
- FACT: By default it builds lib, bins, examples and integration tests, runs lib and bin unit tests, and runs doc tests for the lib. [S4]
- FACT: Target flags: `--lib`, `--bins`, `--test <name>`, `--tests`, `--doc` (cannot combine with other target options), `--all-targets`. Package flags: `-p`, `--workspace`, `--exclude`. [S4]
- FACT: Cargo stops after the first failing test executable. `--no-fail-fast` keeps going. Inside one executable, all tests run. [S4]
- FACT: `--no-run` compiles without running. [S4]
- FACT: Exit code 101 covers test failures and build errors. [S4]
- FACT: `-j N` sets parallel compile jobs. `-- --test-threads=N` sets parallel tests. Example: `cargo test -j 2 -- --test-threads=2`. [S4]
- FACT: Tests run in parallel threads by default. The Book says tests must not depend on shared state such as files, the working directory or environment variables. `--test-threads=1` serializes them. [S1]
- FACT: Output of passing tests is captured. `-- --show-output` shows it. [S1]
- FACT: Filtering: `cargo test <substring>` runs tests whose path contains the string; only the first name argument is used. Module names are part of the path. [S1]
- FACT: `#[ignore]` skips slow tests. `-- --ignored` runs only them. `-- --include-ignored` runs all. [S1]
- FACT: Tests can return `Result<(), E>` and use `?`. `#[should_panic(expected = "...")]` checks a panic message. Do not combine `should_panic` with a `Result` return. [S16]
- FACT: Feature flags: `-F`, `--all-features`, `--no-default-features`. [S4]
- FACT: The `test` profile is used by default (some optimization, no debug info). `--release` and `--profile <name>` select others. [S4]
- FACT: `[[test]] harness = false` disables libtest, and you provide `main`. `[lib] doctest = false` disables doc tests. `required-features` on a `[[test]]` target skips it when a feature is off. [S4, S9]
- FACT: Cargo book says `cargo test` runs integration test files serially. [S9]

### 2. `cargo-nextest`

- FACT: Default execution model is process-per-test. [S6]
- FACT: Separate processes keep global state, environment variables and main-thread requirements from leaking between tests. A crash in one test does not affect others. [S6]
- FACT: Per-test timeouts can be enforced because a process can be killed: SIGTERM, then SIGKILL after 10 seconds on Unix. [S6, S17]
- FACT: Cost: tests that share in-memory state (semaphores, caches, in-process servers) are harder to write. Process creation is slow on Windows and can be slow on macOS with anti-malware. [S6]
- FACT: The same page says `cargo test` has no per-test timeouts and a crash cancels the other tests in that binary. The page carries two dates, January 7, 2025 and September 6, 2026; it does not say which is which. [S6]
- FACT: `cargo nextest run` accepts the same options as `cargo test`, for example `-p my-package`. [S8]
- FACT: Nextest does not run doc tests. Run `cargo test --doc` separately. [S8]
- FACT: `--no-fail-fast` (alias `--nff`) equals `--max-fail=all`; the docs say it is most useful in CI. [S8]
- FACT: `-j N` or `--test-threads=N` sets concurrency; default is the CPU count; a negative value subtracts from available parallelism. [S8]
- FACT: `-P <profile>` or `NEXTEST_PROFILE` selects a profile. [S8, S18]
- FACT: `--partition hash:1/2`, `count:2/3`, `slice:1/3` split a run. Archives (`--archive-file`) run pre-built tests. [S8]
- FACT: Install: script `curl -LsSf https://get.nexte.st/install.sh | sh -s --`, `cargo binstall cargo-nextest --secure`, or package managers (`brew`, `pacman`, `winget`). Update with `cargo nextest self update`. The docs page does not state a current version or MSRV (Minimum Supported Rust Version). [S19]
- FACT: The newest version named on the running page is 0.9.123. Other pages name 0.9.115 (profile inheritance, `on-timeout`) and 0.9.100 (`global-timeout`). [S8, S17, S18]

#### Filtering and groups

- FACT: Filtersets are passed with `-E` or `--filterset`. Predicates shown: `test(...)` (substring, or `/regex/`), `package(...)`, `deps(...)`, `rdeps(...)`, `default()`. Operators: `and`, `not`, `|` or `+`, parentheses. [S20]
- FACT: Several `-E` arguments are unioned. Substring filters after `--` are intersected with the filterset union. [S20]
- FACT: `group(name)` is a filter that selects a test group. `cargo nextest show-config test-groups` shows groups. [S7]
- FACT: Test groups act like a semaphore with `max-threads` permits (a mutex when `max-threads = 1`). Tests outside a group are unaffected. Use cases: shared network service, global resource, fixed port. [S7]
- FACT: Groups are declared in `[test-groups]` in `.config/nextest.toml` and assigned through `[[profile.default.overrides]]` with `filter = '...'` and `test-group = '...'`. [S7]
- FACT: The filterset page does not list the `kind`, `binary_id` or `platform` predicates; the DSL (domain-specific language) reference was not read. [S20]
- INFERENCE: "Groups so a change can run only its own group" maps to either (a) `-p <crate>` and `-E 'package(...)'` selections, (b) a filter on a test-name module prefix such as `integration::`, or (c) a test-group name with `-E 'group(name)'`. Note that nextest groups were designed to limit concurrency, not only to label tests; a filter on module path works for pure selection.

#### Retries

- FACT: `--retries N` re-runs a failed test up to N more times. A pass on retry is marked flaky and counts as success (exit 0) by default. Also `NEXTEST_RETRIES` and config. [S21]
- FACT: Config forms: `retries = { backoff = "fixed", count = 2, delay = "1s" }` and `{ backoff = "exponential", count = 3, delay = "5s" }`, with `max-delay` and `jitter`. Per-test overrides use `filter`. [S21]
- FACT: `--flaky-result fail` (or `NEXTEST_FLAKY_RESULT=fail`, or `flaky-result = "fail"`) fails the run on flaky tests; retries must be on. [S21]
- FACT: Passing `--retries` on the command line disables per-test override settings. [S21]
- INFERENCE: For an agent-written test suite, retries hide flakiness. Candidate rule: keep retries off by default, or pair retries with `flaky-result = "fail"`.

#### Slow tests

- FACT: `slow-timeout` default is 60 seconds (flag only). `terminate-after` kills the test after N periods. `on-timeout`, `grace-period` and `global-timeout` exist. Per-test overrides use `filter`. [S17]

### 3. Unit tests, `tests/` integration tests, doc tests

- FACT: Unit tests live in the file they test, in a `#[cfg(test)] mod tests` that uses `use super::*;`, so they can call private functions. `#[cfg(test)]` code is not compiled by `cargo build`. [S2]
- FACT: Integration tests live in `tests/` next to `src`. Each file is compiled as a separate crate and uses only the public API. No `#[cfg(test)]` is needed. `cargo test --test <file>` runs one. [S2, S9]
- FACT: Shared helpers go in `tests/common/mod.rs`. A file `tests/common.rs` would be its own test crate with "running 0 tests". [S2]
- FACT: A binary-only crate (`src/main.rs`, no `src/lib.rs`) cannot be imported by `tests/`. The usual pattern is a thin `main.rs` and logic in `src/lib.rs`. [S2]
- FACT: Cargo sets `CARGO_BIN_EXE_<name>` for integration tests when a binary target exists, so tests can run the built executable. [S9]
- FACT: In `cargo test`, if a section (unit, integration) fails, later sections do not run. [S2]
- FACT: Each file in `tests/` is its own crate and binary. [S2][S9] INFERENCE: many files mean more link time; the Cargo reference text I read does not say this.
- INFERENCE: Fewer, larger integration test files (or one `tests/it/main.rs` with modules) cut link time. The Cargo book page read did not cover `tests/<subdir>/main.rs`. UNTESTED.
- FACT: Doc tests: rustdoc extracts fenced blocks from `///` comments; a block passes if it compiles and runs without panic. Lines starting `#` are hidden from rendered docs but compiled. Attributes: `ignore`, `should_panic`, `no_run`, `compile_fail`, `edition2021` etc., `ignore-<target>`. `cargo test --doc` runs them. Use `?` with a hidden `Ok::<(), E>(())` last line. [S5]
- FACT: The rustdoc book advises `text` or `#` hiding rather than `ignore`, because `ignore` is the most generic option. [S5]
- FACT: Doc tests only apply to the library target. [S9]
- INFERENCE: Doc tests document public API usage; they are slow to compile (one compile per block unless merged) and are not a place for behavior coverage. The merge behavior is not stated by the pages read.

### 4. Property-based testing

- FACT: `proptest` is a property testing framework in the QuickCheck family, inspired by Hypothesis. It reduces a failing input to a minimal case. Generation and shrinking are per value, not per type. The docs say the crate is close to feature-complete with mostly passive maintenance. [S10]
- FACT: Default is 256 successful cases. `PROPTEST_CASES` (a `u32`) overrides it when the `std` feature is on. `#![proptest_config(ProptestConfig::with_cases(1000))]` inside `proptest!` sets it in code. [S11]
- FACT: Failing cases are saved under a `proptest-regressions` directory tree, named after the source file. Later runs replay them first. The docs recommend committing these files. The saved item is the random seed, not the value. [S12]
- FACT: `quickcheck` 1.x: add `quickcheck = "1"` (dev-dependency). Use the `quickcheck!` macro or `#[quickcheck]` (needs `quickcheck_macros = "1"`). It targets 100 valid tests and gives up after 10,000 attempts; env vars `QUICKCHECK_TESTS`, `QUICKCHECK_MAX_TESTS`, `QUICKCHECK_MIN_TESTS_PASSED`. MSRV 1.85.0. The README points to `proptest` if shrinking is a problem. [S13]
- INFERENCE: Candidate rule: a property test needs a stated property (round trip, invariant, comparison with a simple model), not "no panic" alone. Cases cost time, so low `PROPTEST_CASES` on the fast path and higher in a scheduled run is an option. UNTESTED.

### 5. Snapshot testing (`insta`)

- FACT: Add with `cargo add --dev insta --features yaml`. `cargo-insta` is recommended but "entirely optional". [S22]
- FACT: Macros: `assert_snapshot!` (string), `assert_yaml_snapshot!` (any `serde::Serialize`; docs recommend YAML, with JSON, TOML, RON, CSV variants), `assert_debug_snapshot!`. Inline snapshots keep the value in the macro call. [S22, S23]
- FACT: A changed snapshot is written as `.snap.new` beside the old file. Accept by `cargo insta review`, or move the file. `cargo insta test --review` combines run and review. [S22]
- FACT: `INSTA_UPDATE`: `auto` (default: `no` in CI, otherwise `new`), `always`, `unseen`, `new`, `no`. Setting the `CI` env var stops insta writing new files. [S22, S23]
- FACT: `INSTA_FORCE_PASS=1` stops snapshot failures failing tests so all snapshots are produced in one run. [S23]
- FACT: `cargo insta test --unreferenced=auto` deletes unused snapshots locally and rejects them in CI. [S23]
- FACT: Redactions keep snapshots stable when output holds timestamps or random IDs. `glob!` runs a closure per input file (needs the `glob` feature). [S23]
- INFERENCE: The main snapshot risk for agents is approving a snapshot without reading it. Candidate rule: `review` should check that every changed `.snap` was read and is deterministic. Snapshot files (`snapshots/` next to the test) should be committed. The pages read do not state the folder name; it is an INFERENCE from `.snap` and `.snap.new` file names.

### 6. Fakes and traits as seams

- FACT: `mockall` (docs.rs "latest" page showed 0.15.0): `#[automock]` generates `Mock<Name>` for most traits and for structs with one `impl` block. `mock!` handles multiple traits, external traits, several `impl` blocks. Expectations: `expect_<method>()` with `with`, `times`, `returning`, `in_sequence`. Unmatched calls panic. Async traits work with conditions. Static-method expectations are global, so tests using them need their own synchronization. [S14]
- INFERENCE: Mockall checks expectations when the mock is dropped (not stated verbatim in what I read). FACT: `checkpoint()` validates and clears expectations. [S14]
- INFERENCE: Design for seams: put I/O, clock, network and randomness behind a trait; pass an implementation in (generic parameter or `Box<dyn Trait>`); in tests pass a hand-written fake or a `mockall` mock. Hand-written fakes avoid a dependency and macro limits; mocks give call-count checks.
- INFERENCE: Prefer fakes with real behavior (in-memory store) over mocks that assert call order, because order assertions break on refactors. This is a general testing view, not a Rust-docs claim.
- UNTESTED: No mock or seam example was compiled.

### 7. Async tests

- FACT: `#[tokio::test]` runs an async test on a Tokio runtime. Each test gets its own current-thread runtime by default. `flavor = "multi_thread"` (needs `rt-multi-thread`) with `worker_threads`. Needs the `macros` and `rt` features. [S15]
- FACT: `start_paused = true` starts with the clock paused; needs the `test-util` feature. Pausing needs the `current_thread` runtime. When paused and idle, time jumps to the next timer, so `sleep` in a test returns at once. Only Tokio's `Instant` is affected, not `std::time::Instant`. [S15, S24]
- INFERENCE: Paused time makes timeout and retry logic fast and deterministic. Real sleeps in tests are a "slow test" smell.
- INFERENCE: Other runtimes (`async-std`, `smol`) have their own test attributes; not researched. See Gaps.

### 8. Keeping tests fast

- FACT: Run only what you need: `-p`, `--lib`, `--test <name>`, name substring, `#[ignore]` for slow ones. [S1, S4]
- FACT: `cargo test --no-run` and `cargo build --tests --keep-going` separate compile errors from test failures. [S4]
- FACT: `cargo test` uses the `test` profile (some optimization). `insta` docs suggest raising optimization for `insta` and `similar` in `[profile.dev.package]`. [S4, S22]
- FACT: Nextest: per-test slow timeout, global timeout, partitioning, archives. [S8, S17]
- INFERENCE: Compile time is often the largest cost in a Rust loop, so fewer integration test binaries and fewer heavy dev-dependencies help. UNTESTED, no timing done.
- INFERENCE: Isolation rules that keep tests parallel-safe: per-test temp dirs, no fixed ports (bind to port 0), no `set_var` on the process environment, no shared files. The Book lists shared files, the working directory and environment variables as the hazards. [S1]

### 9. Detecting the repo's existing setup

All detection is file inspection (read-only):

| Question | Where to look | Source |
|---|---|---|
| Is it a Cargo project? workspace? | `Cargo.toml` with `[package]` or `[workspace]` (`members`, `default-members`) | S4 |
| Library or binary only? | `src/lib.rs` present? Binary-only means `tests/` cannot import | S2 |
| Unit tests | `#[cfg(test)]` in `src/**` | S2 |
| Integration tests | `tests/*.rs`, `tests/*/mod.rs`, `[[test]]` tables, `autotests = false` | S2, S9 |
| Custom harness | `harness = false` in a `[[test]]` | S4, S9 |
| Doc tests on or off | `[lib] doctest = false` | S9 |
| Feature-gated tests | `required-features` in `[[test]]` | S9 |
| Nextest in use | `.config/nextest.toml`; `cargo nextest --version` | S18 |
| Nextest groups and profiles | `[test-groups]`, `[profile.*]`; `cargo nextest show-config test-groups` | S7, S18 |
| Property tests | dev-dependency `proptest` or `quickcheck`; `proptest-regressions/` directory | S12, S13 |
| Snapshot tests | dev-dependency `insta`; `.snap` files | S22 |
| Mocks | dev-dependency `mockall` | S14 |
| Async runtime | dev-dependency or dependency `tokio` with features `macros`, `rt`, `test-util` | S15 |
| CI test command | workflow file (belongs to the `cicd-pipelines` skill) | out of scope |

- INFERENCE: Also check `rust-toolchain.toml` and `rust-version` in `Cargo.toml` for toolchain and MSRV. These are not covered by the pages read. UNTESTED.

## Draft: what the Rust entry could say (candidate content, not a decision; each rule is INFERENCE and picks one option that the owner may reject)

1. Run commands. Prefer `cargo nextest run` when `.config/nextest.toml` exists or `cargo nextest` is installed; else `cargo test`. Always add `cargo test --doc` when doc tests exist, because nextest skips them. [S8]
2. Place tests. Unit tests in `#[cfg(test)] mod tests` beside the code; integration tests in `tests/` against the public API; share helpers in `tests/common/mod.rs`; keep `main.rs` thin so logic is testable from `src/lib.rs`. [S2]
3. Make tests parallel-safe. No shared files, working directory, environment variables or fixed ports. Under `cargo test` these share one process, so global state leaks between tests; under nextest each test has its own process. [S1, S6]
4. Name tests so filters work. Put tests in modules so `cargo test <module>` and nextest `test(module::)` can select them. [S1, S20]
5. Group. Use nextest groups (`max-threads = 1`) only for tests that must not run together; use module/package filters to select a change's tests. [S7, S20]
6. Property tests for pure logic with a real property; commit `proptest-regressions/`. Keep case counts low on the fast path. [S11, S12]
7. Snapshot tests for structured output; redact nondeterministic fields; never run with `INSTA_UPDATE=always` and approve blindly; review every `.snap`. [S22, S23]
8. Seams: put I/O, time and randomness behind traits; prefer hand-written fakes; use `mockall` when call checks matter. [S14]
9. Async: `#[tokio::test]`; use `start_paused = true` for time; use `multi_thread` only when the code needs it. [S15, S24]
10. Review checks: no real sleeps, no network, no reading user files, no `#[ignore]` without a reason, no retries hiding flakiness, every test has an assertion, `compile_fail` doc tests are not relied on as stable. [S1, S5, S21]

## Facts a setup rules file would record for a Rust repo

| Fact | How to detect | Notes |
|---|---|---|
| Runner: `cargo test` or `cargo nextest` | `.config/nextest.toml`, `cargo nextest --version` | Record the exact fast command |
| Doc test command | `cargo test --doc` unless `doctest = false` | Needed beside nextest |
| Workspace members and default members | `Cargo.toml` | Which `-p` values exist |
| Test layout | `tests/`, `#[cfg(test)]`, `[[test]]` | Where new tests go |
| Features needed for tests | `required-features`, `--all-features` use | Record flags |
| Nextest profiles and groups | `[profile.*]`, `[test-groups]` | Group names and what they protect |
| Retry policy | `retries`, `flaky-result` in nextest config | Default is no retry |
| Timeouts | `slow-timeout`, `global-timeout` | |
| Property and snapshot libraries | dev-dependencies | Plus commit rules for regression and snapshot files |
| Async runtime and test attribute | dev-dependencies, `#[tokio::test]` use | |
| Worker cap | `-j`, `--test-threads` flags (the user's CPU rule is out of scope here) | Command-line flags, no config change |
| Toolchain / MSRV | `rust-toolchain.toml`, `rust-version` | INFERENCE |

## Options (unranked; the owner decides)

A. Entry names `cargo nextest run` + `cargo test --doc` as the default, with `cargo test` as fallback when nextest is absent.
B. Entry names only `cargo test`, and mentions nextest as an upgrade when the repo already has `.config/nextest.toml`.
C. Entry follows whatever the setup detection finds and states no default runner.
D. Groups defined as nextest test groups plus filtersets.
E. Groups defined as module-path prefixes and packages (works for both runners), with nextest groups only for concurrency limits.
F. Groups defined as `#[ignore]` for slow tests plus `--include-ignored` for the full run.
G. Property and snapshot testing as optional sections, loaded only when the dev-dependency exists.
H. Property and snapshot testing as general guidance, with `/testing write` proposing the dependency.
I. Seam guidance as trait + hand-written fake first, `mockall` only on request; or `mockall` as the default mock tool.
J. Retry policy: off by default; or on with `flaky-result = "fail"`.

## Gaps

- No Rust code was built or run, so every command here is read from docs, not executed (UNTESTED).
- The nextest DSL reference (`kind`, `binary_id`, `platform` predicates) was not read.
- Nextest current version and MSRV are not stated on the pages read.
- Coverage tools (`cargo-llvm-cov`, `tarpaulin`), `cargo-mutants`, fuzzing (`cargo-fuzz`), `rstest`, `test-case`, `serial_test`, `wiremock`, `tempfile`, and Miri were not researched.
- `tests/<subdir>/main.rs` layout and the merged doc test compile behavior were not confirmed from the Cargo book.
- Other async runtimes (`async-std`, `smol`) were not researched.
- Mockall's MSRV and the drop-time expectation check were not confirmed. The docs.rs "latest" page showed 0.15.0; this may differ from the real latest release.
- The Rust Book edition fetched was the current online version; its date was not shown.
- No existing skills (for example the installed TDD skill) were compared here. See `testing-existing-skills.md` (ticket 811).

## Sources

All read on 2026-11-17 with WebFetch. No fetch failed.

- S1 https://doc.rust-lang.org/book/ch11-02-running-tests.html
- S2 https://doc.rust-lang.org/book/ch11-03-test-organization.html
- S3 https://doc.rust-lang.org/book/ch11-01-writing-tests.html (same as S16)
- S4 https://doc.rust-lang.org/cargo/commands/cargo-test.html
- S5 https://doc.rust-lang.org/rustdoc/write-documentation/documentation-tests.html
- S6 https://nexte.st/docs/design/why-process-per-test/
- S7 https://nexte.st/docs/configuration/test-groups/
- S8 https://nexte.st/docs/running/
- S9 https://doc.rust-lang.org/cargo/reference/cargo-targets.html
- S10 https://proptest-rs.github.io/proptest/intro.html
- S11 https://proptest-rs.github.io/proptest/proptest/tutorial/config.html
- S12 https://proptest-rs.github.io/proptest/proptest/failure-persistence.html
- S13 https://github.com/BurntSushi/quickcheck
- S14 https://docs.rs/mockall/latest/mockall/
- S15 https://docs.rs/tokio/latest/tokio/attr.test.html
- S16 https://doc.rust-lang.org/book/ch11-01-writing-tests.html
- S17 https://nexte.st/docs/features/slow-tests/
- S18 https://nexte.st/docs/configuration/
- S19 https://nexte.st/docs/installation/pre-built-binaries/
- S20 https://nexte.st/docs/filtersets/
- S21 https://nexte.st/docs/features/retries/
- S22 https://insta.rs/docs/quickstart/
- S23 https://insta.rs/docs/advanced/
- S24 https://docs.rs/tokio/latest/tokio/time/fn.pause.html

Note: WebFetch answers come from a small model summarizing each page, so a quoted detail is a summary, not a verbatim copy.
