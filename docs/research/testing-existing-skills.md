# Research: existing testing skills, guides and tools to reuse

Ticket 811, part of map 810. Date read: 2026-11-17.

Labels: FACT (with source number from the Sources list), INFERENCE (my reasoning), UNTESTED (a claim I did not run or verify).

## Short answer

1. The installed TDD (Test-Driven Development) skill covers **write** only. It has no setup and no review mode. FACT [1].
2. It gives the `testing` skill a strong base for "what a good test is": behaviour through public interfaces, no implementation coupling, no tautological assertions, agreed seams. FACT [1].
3. It says nothing about runnable tests: speed, isolation, parallel safety or grouping. FACT [1] (the files do not mention them). Those are the map's core terms, so the `testing` skill must build them.
4. No public skill or rule set found covers setup, write and review together. INFERENCE from the search; the search was not exhaustive.
5. The public skills found are mostly TDD process skills or tool skills (Playwright browser driving), not test-quality review skills. FACT [2][3].
6. The best reusable source for "runnable" is the guide material: Google test sizes, Kent Beck's test desiderata, and the tool docs for filtering and isolation. FACT [6][9][10][11][12].
7. For Rust and Node, the runner features that give "groups" and "isolation" already exist: nextest filtersets and test groups, `cargo test` unit/integration layout, `node:test` file isolation and name filters, Vitest filters and tags. FACT [10][11][12][13][14].
8. The pyramid, trophy and honeycomb disagree on proportions but agree on three points: speed matters, test through stable interfaces, avoid fragile cross-system tests. INFERENCE from [4][5][7][8][9].
9. Licences differ. MIT and CC0 sources can be adapted. Articles with "all rights reserved" or CC BY-NC-ND (Creative Commons, non-commercial, no-derivatives) can only be cited and paraphrased, not copied. FACT per row in the table.
10. Review of test quality has little public skill support. The only concrete reusable review aids found are the "mentally mutate" check and mutation tools (cargo-mutants, StrykerJS). FACT [3b][15][16]. How well they fit an agent skill is UNTESTED.

## Findings

### 1. The installed TDD skill (version 1.2.0)

- FACT [1]: `SKILL.md` plus `tests.md` and `mocking.md`. Licence of the plugin repo: MIT [17].
- FACT [1]: it defines a good test as behaviour through public interfaces that survives refactors.
- FACT [1]: **seams**. Tests go only at pre-agreed seams, confirmed with the user before any test is written.
- FACT [1]: three anti-patterns: implementation-coupled, tautological, horizontal slicing (all tests first, then all code).
- FACT [1]: rules of the loop: red before green, one slice at a time, refactoring is not part of the loop.
- FACT [1]: `mocking.md` says mock only at system boundaries (external APIs, sometimes databases, time and randomness, sometimes the file system). Use dependency injection. Prefer SDK-style interfaces.
- FACT [1]: `tests.md` gives TypeScript examples only.

Where it stops (all INFERENCE from what the files do not contain, checked by reading all three files):

- No setup: no framework choice, no commands, no repo rules file.
- No review mode: it points to the `code-review` skill for refactoring, not for judging a test suite.
- No runnable-test rules: nothing on speed, isolation, order independence, parallel safety, flakiness or grouping by change.
- No language entries: examples are TypeScript only. Nothing for Rust.
- No test kinds beyond "integration-style" against unit: no property tests, contract tests, snapshots or end-to-end guidance.
- The agent's workflow rules (run rules, audit) are out of scope for the map, so that gap is not a gap of this skill.

### 2. Public skills and rule sets

- Superpowers `test-driven-development` skill [2]. FACT: write-workflow guide with "no production code without a failing test first". Verification checklist at the end (review support is only that). Linked file `writing-good-tests.md` [2b] has concrete rules: each test names a bug it would catch, expected values by hand, no mock-presence assertions, no change detectors, and a "mentally mutate the code" check before finishing. Licence of the repo: MIT [18]. INFERENCE: closest match to a review checklist; its stance on deleting code written before the test is stricter than the installed TDD skill.
- Anthropic `webapp-testing` skill [3]. FACT: drives a local web app with Playwright, plus a helper script that starts servers. It is about browser automation, not about test quality. The repo README says many skills are Apache 2.0, and this skill's own licence text is in a `LICENSE.txt` that I did not read, so the licence is UNTESTED.
- awesome-cursorrules [19]. FACT: CC0-1.0 licence. `.mdc` rule files with `description`, `globs` and `alwaysApply` front matter. Testing sets exist for Jest, Vitest, Cypress and Playwright. The Rust set is a general Rust rule, not a testing rule. I did not read the individual rule texts, so their quality is UNTESTED.
- Community mutation-testing skills (third-party write-ups only). FACT: a skill routes Rust to cargo-mutants and TypeScript to Stryker, with a kill-rate gate [20]. These are third-party pages, not the skill source, so treat as UNTESTED.
- Evals for skills (mgechev skillgrade, MLflow write-up) [21][22]. FACT: public tools exist that run a skill against a task and grade the artifact with a deterministic script. INFERENCE: relevant to the map's "not yet specified" eval item, not to the skill content. UNTESTED for fit.

### 3. Guides

- Test pyramid (Ham Vocke, on a well-known software engineering site) [4]. FACT: many fast unit tests, fewer coarse tests, very few end-to-end tests. Test one condition per test, arrange/act/assert. Test observable behaviour, not internals. Push each check to the lowest level that can catch it. A "unit" is up to the team. FACT: both sociable (real collaborators) and solitary (stubbed) styles are accepted.
- "Unit test" definition [5]. FACT: loosely defined; low-level, written by programmers, faster than other tests. Solitary versus sociable. Speed matters because tests are run often; a commit suite should fit about ten minutes (a rule attributed to Kent Beck).
- Testing trophy (Kent C. Dodds) [7]. FACT: layers static, unit, integration, end-to-end; most effort on integration; the trophy is about return on investment; the author applied it only to monoliths. Page is "all rights reserved".
- Testing honeycomb (Spotify) [8]. FACT: for microservices, mostly integration tests of one service in isolation, few implementation-detail tests, ideally no "integrated" tests that depend on another system's correctness.
- Google "Just Say No to More End-to-End Tests" [6]. FACT (partly from reader comments; article body not read): keep the pyramid shape, exact mix differs per team.
- Software Engineering at Google, chapter 11 [9]. FACT: **test sizes** by resource use, not line count. Small: one process, no sleep, no I/O, no network. Medium: may use several processes and localhost. Large: may span machines. Also the "Beyoncé rule" (test what you do not want to break) and a warning that over-specified, mock-heavy tests are brittle. Licence CC BY-NC-ND 4.0.
- Test Desiderata (Kent Beck) [10]. FACT: 12 properties: isolated, composable, deterministic, fast, writable, readable, behavioral, structure-insensitive, automated, specific, predictive, inspiring. INFERENCE: this list maps cleanly to review criteria and to "runnable" (isolated, deterministic, fast, automated). The page states no licence.
- INFERENCE: the sources disagree on proportions (pyramid versus trophy versus honeycomb). They agree on: fast feedback, test through stable interfaces, avoid fragile tests that depend on other systems. A language-neutral skill can state the shared points and leave proportions to a per-repo setting.

### 4. Tools for Rust and Node/TypeScript

- Rust `cargo test` layout [11]. FACT: unit tests in `#[cfg(test)]` modules inside `src`; integration tests in `tests/`, one crate per file; shared helpers in `tests/common/mod.rs`; doc tests are a third section; binary-only crates cannot be integration-tested, so keep logic in `src/lib.rs`; name filter, `--test <file>`, and `#[ignore]` with `-- --ignored`. (The `#[ignore]` point came from the fetch tool's own note, not the page: UNTESTED here.)
- cargo-nextest [12]. FACT: process-per-test isolation, filtersets (select by name, binary, platform), test groups (serial or limited concurrency), retries, partitioning for CI workers. Licence Apache 2.0, docs CC BY 4.0. Doc tests are not supported yet (run with `cargo test --doc`).
- `node:test` [13]. FACT: stable runner; each file runs in its own process by default; `--test-name-pattern` and `--test-skip-pattern`; `--test-concurrency`; tests inside one file run in one thread. Tags exist but are marked early development in the page I read. Coverage and watch mode are experimental.
- Vitest filtering [14]. FACT: filter by file path, name regex, line number and tags; `.only` fails CI by default. A "run only affected tests" recipe exists but I did not read it (UNTESTED).
- cargo-mutants [15]. FACT: MIT; injects bugs and reports which ones no test catches; needs non-flaky tests; works with `cargo test` or nextest. Its diff-scoped mode (`--in-diff`) is UNTESTED (the page I read did not describe it).
- StrykerJS [16]. FACT: Apache 2.0; mutation testing for JavaScript and TypeScript; Jest and Vitest runners listed; `node:test` support not confirmed on the page.
- INFERENCE: setup mode can detect the runner and write the commands and groups into a repo rules file, as `/sql setup` does, using only existing runner features. No custom runner is needed.

### 5. Format of the two existing repo skills

- FACT [23][24]: `SKILL.md` is a router. `sql` lists modes and loads `setup.md`, `format.md`, `style.md` and `optimize.md` by need. It reads a repo rules file (`docs/agents/sql.md`) with a script that prints JSON. `cicd-pipelines` loads `review.md`, `create.md` and `rules/*.md` by need and runs an intake script for repo facts. Both keep scripts, `evals/` and `tests/` folders.
- INFERENCE: the `testing` skill can follow the same shape: router, one file per mode, a rules file for the repo, an intake script that detects the runner, and a language router with `rust.md` and `typescript.md` entries.

## Candidates

| Candidate | Setup | Write | Review | Licence | Verdict |
|---|---|---|---|---|---|
| Installed TDD skill (tests.md, mocking.md) | no | yes | partial (anti-patterns) | MIT (repo) | adapt: reuse good-test definition, seams, anti-patterns; build the rest |
| Superpowers TDD + writing-good-tests | no | yes | partial (checklist, mutate check) | MIT | adapt: the review checklist items |
| Anthropic webapp-testing | no | no (browser driving) | no | Apache 2.0 claimed by README; skill file not checked | not needed for first version |
| awesome-cursorrules testing sets | no | rule text per tool | no | CC0-1.0 | adapt only after reading each rule (UNTESTED) |
| Google test sizes (SWE at Google ch. 11) | no | guidance | guidance | CC BY-NC-ND 4.0 | cite and paraphrase; do not copy |
| Test Desiderata (Beck) | no | guidance | yes (criteria) | not stated | cite and paraphrase; build own wording |
| Test pyramid / honeycomb / trophy articles | no | guidance | guidance | copyright, no reuse licence | cite and paraphrase |
| Rust Book test organisation | yes (layout) | yes | no | not read | cite; Rust entry is built on it |
| cargo-nextest | yes (groups, filters) | no | no | Apache 2.0 / CC BY 4.0 | reuse as a tool the setup mode detects |
| `node:test` / Vitest runners | yes (filters) | no | no | not read (Node and Vitest pages show no licence in what I read) | reuse as tools; TypeScript entry built on them |
| cargo-mutants / StrykerJS | no | no | yes (strength check) | MIT / Apache 2.0 | reuse as optional review tools |
| Skill eval tools (skillgrade etc.) | n/a | n/a | n/a | not read | candidate for the eval ticket; UNTESTED |
| Complete setup + write + review skill | none found | | | | build |

## Options (unranked, the owner decides)

- **A. Adapt the installed TDD skill as the "write" core.** Keep its seams, anti-patterns and mocking rules, extend them with runnable-test rules and language entries. Cost: depends on a plugin that can change in an update, so copy the text into this repo or reference it by name. Gain: least new text.
- **B. Write own rules, citing the guides.** Rules for kinds of tests, test sizes and desiderata-based review criteria in own words, with the TDD skill left as a separate skill. Cost: more writing; risk of overlap with TDD. Gain: one consistent voice and no plugin coupling.
- **C. Define "runnable" by Google-style test sizes plus Beck's properties.** Small (no I/O, no network), medium (local only), large. Groups map to sizes. Cost: sizes need a per-language rule for what counts as I/O. Gain: groups are objective, and a review can check them.
- **D. Define "runnable" by each runner's own filters.** Rust: unit/integration layout, nextest filtersets and groups. Node: name patterns, file paths, tags. Cost: groups differ per language, and `node:test` tags are early development in the page read. Gain: no new concepts.
- **E. Add mutation tools as an optional review step.** cargo-mutants and StrykerJS find tests that never fail. Cost: slow, needs non-flaky tests, fit for agent runs UNTESTED. Gain: an objective check of test strength. Alternative: only the "mentally mutate" prompt from the Superpowers file, which costs nothing.
- **F. Keep the router shape of `sql` and `cicd-pipelines`.** Router, mode files, repo rules file, intake script, language entries. Alternative: a smaller skill with only the three mode files and no scripts.

## Gaps

- No public skill found that covers setup, write and review together (search not exhaustive; the search tool returned mostly aggregator sites).
- No public language-neutral rule set for "runnable" tests (speed, isolation, parallel safety) found other than the Google chapter and Beck's list.
- No source read on flaky test handling, test data and fixtures, property-based testing or snapshot testing.
- Rust guidance read covers layout only; no source read on async tests, test doubles in Rust or `proptest`.
- The Google article body and the Vitest "affected tests" recipe were not read in full.
- Eval fit (skill graders) and mutation-tool fit for agent runs are UNTESTED.
- Licence of the Node.js docs, the Rust Book, Vitest, Beck's desiderata page and the Anthropic `webapp-testing` skill file were not confirmed.

## Sources

Read (success):
1. Installed TDD skill files, local: plugin cache `mattpocock-skills/1.2.0/skills/engineering/tdd/` (`SKILL.md`, `tests.md`, `mocking.md`).
2. https://github.com/obra/superpowers/blob/main/skills/test-driven-development/SKILL.md ; 2b. https://github.com/obra/superpowers/blob/main/skills/test-driven-development/writing-good-tests.md
3. https://github.com/anthropics/skills ; https://raw.githubusercontent.com/anthropics/skills/main/skills/webapp-testing/SKILL.md
4. https://martinfowler.com/articles/practical-test-pyramid.html
5. https://martinfowler.com/bliki/UnitTest.html
6. https://testing.googleblog.com/2015/04/just-say-no-to-more-end-to-end-tests.html (partial: first 100000 characters, mostly comments)
7. https://kentcdodds.com/blog/the-testing-trophy-and-testing-classifications
8. https://engineering.atspotify.com/2018/01/testing-of-microservices
9. https://abseil.io/resources/swe-book/html/ch11.html
10. https://testdesiderata.com/
11. https://doc.rust-lang.org/book/ch11-03-test-organization.html
12. https://nexte.st/
13. https://nodejs.org/api/test.html (partial: first 100000 characters)
14. https://vitest.dev/guide/filtering.html
15. https://github.com/sourcefrog/cargo-mutants
16. https://stryker-mutator.io/docs/stryker-js/introduction/
17. https://github.com/mattpocock/skills (licence shown as MIT)
18. https://raw.githubusercontent.com/obra/superpowers/main/LICENSE (MIT)
19. https://github.com/PatrickJS/awesome-cursorrules (CC0-1.0)
20. Search result pages (third-party, not fetched): https://agentskills.so/skills/jwilger-agent-skills-mutation-testing ; https://tomevault.io/tome/jwilger/agent-skills/mutation-testing
21. Search result (not fetched): https://blog.mgechev.com/2026/02/26/skill-eval/
22. Search result (not fetched): https://www.mlflow.org/blog/evaluating-skills-mlflow
23. This repo: `skills/sql/SKILL.md`
24. This repo: `skills/cicd-pipelines/SKILL.md`

Failed:
- https://medium.com/@kentbeck_7670/test-desiderata-94150638a4b3 (HTTP 403; used testdesiderata.com instead)
- https://raw.githubusercontent.com/obra/superpowers/main/skills/test-driven-development/testing-anti-patterns.md (HTTP 404; the file does not exist at that path)
- `gh issue view` for the ticket and map failed on a GraphQL deprecation error; I read both through `gh api` (read-only) instead.
