# Research: runnable tests in TypeScript/Node (ticket 814, map 810)

Date of research: 2026-11-17. Public repo: generic content only.

Labels: FACT (with source number from the Sources list), INFERENCE (reasoned from facts), UNTESTED (not run here).

Docs versions seen: Vitest v5.1.1, Jest 30.5, Node.js v26.x docs (the TypeScript page names v26.13.1). The pages show no per-page date; the footers say 2026. [1][6][9]

## Short answer

1. All three runners run test files in parallel and isolate each file. Vitest: separate child process per file by default (`forks` pool). Jest: worker pool of child processes. `node:test`: one child process per file by default. FACT [1][7][8]
2. Inside a file, tests run one after another by default in Vitest. Concurrency is opt-in and helps only I/O-bound tests. FACT [1]
3. Filtering: all three filter by file path and by test name regular expression (regexp). FACT [2][7][8]
4. Changed-files mode exists in Vitest (`--changed`, `related`) and Jest (`--onlyChanged`, `--changedSince`, `--findRelatedTests`). `node:test` has no changed-files flag in the docs read. FACT / UNTESTED for absence [2][7]
5. Sharding exists in all three: `--shard=i/n` (Vitest, Jest) and `--test-shard=i/n` (Node). FACT [2][7][8]
6. Groups: Vitest `test.projects`, Jest `projects`. `node:test` has no project concept; groups are file globs or directories. FACT / INFERENCE [3][7][8]
7. Fast tests rest on fakes at the edges: fake timers, a request interceptor (Mock Service Worker, MSW) and module mocks. All three document timers and module mocks. FACT [4][5][7][8][9]
8. Module mocking has runtime limits: Vitest `vi.mock` is hoisted and covers only `import`; Jest `jest.mock` does not work for native ESM (use `unstable_mockModule`); Node `mock.module` is early development and needs a flag. FACT [4][5][10][8]
9. A setup rules file should record: the runner, the single-run command, the filter and group commands, and the fake/mock conventions. Detection is by `package.json` and config file names. The `cicd-pipelines` skill already detects runners this way. FACT / INFERENCE [11]

## Findings per topic

### 1. Parallelism and isolation

- Vitest: two levels. Files run in parallel across workers; each file gets its own isolated environment. Default pool `forks` (child process per file). `threads` uses worker threads. `vmForks` and `vmThreads` use VM contexts. FACT [1]
- Vitest: `fileParallelism: false` runs files one at a time; the docs suggest it for a shared resource such as a database. FACT [1]
- Vitest: tests inside a file run sequentially in definition order. `test.concurrent` or `describe.concurrent` opt in; bounded by `maxConcurrency`. Synchronous tests gain nothing. FACT [1][12]
- Vitest: isolation can be turned off (`--no-isolate`) for speed, only if tests share no state. `vmThreads` cannot run without isolation. FACT [13]
- Jest: worker pool; `--maxWorkers` sets the size (default: cores minus one in a single run, half the cores in watch mode). `--runInBand` runs serially in one process, "useful for debugging". The troubleshooting page says `--runInBand` can speed up slow CI or Docker by up to 50 percent. FACT [7][14][15]
- Jest: `jest.mock` affects only the file that calls it; `jest.isolateModules` gives a sandbox module registry. `bail`, `maxWorkers`, `reporters` and `randomize` are ignored inside a project config. FACT [3b][16]
- Node: `--test-isolation=process` (default) runs each file in its own child process. `none` runs all files in the runner process and concurrency becomes one. `--test-concurrency` default is `os.availableParallelism() - 1`. Within a file, tests run on one thread whatever the `concurrency` option says. FACT [8][17]
- Node: `--test-randomize` (added v26.1.0, early development) randomizes file and test order and prints the seed. FACT [17]
- Jest has a `randomize` option (named in the projects note). Its default and docs were not read. UNTESTED [3b]

### 2. Filtering

- Vitest: `vitest <substring>` filters file paths (inclusion only, no regexp or glob). `file.test.ts:10` targets a line (from Vitest 3; no ranges). `-t <regexp>` filters full test names and combines with `--last-failed`. FACT [2]
- Jest: positional pattern; `--testPathPatterns=<regex>`; `-t <regex>` matched against the full name (describe names plus test name); `--listTests` prints what would run and exits. FACT [7]
- Node: `--test-name-pattern` and `--test-skip-pattern` (regexps; both must be satisfied when combined), file globs as arguments, `--test-only` with the `only` option. FACT [8][17]
- Vitest blocks `test.only` in CI unless `allowOnly` is set. FACT [12]

### 3. Projects and workspaces (groups)

- Vitest: `test.projects` array in the root config. Entries are globs, config file paths, or inline configs. Names must be unique. Select with `--project <name>` (repeatable, wildcards, `!` exclusion). `coverage` and `reporters` are root-only. The `workspace` file is deprecated since 3.2 in favor of `projects`. FACT [3]
- Jest: `projects` array of paths, globs or config objects; select with `--selectProjects`, which matches the `displayName`. FACT [3b][7]
- Node: no project feature in the pages read. Groups would be directories or globs passed as arguments. INFERENCE [8]
- Use for the skill: a "group" can map to a Vitest/Jest project plus a `--project`/`--selectProjects` command. INFERENCE

### 4. Watch and changed-files modes

- Vitest: bare `vitest` is watch mode in a TTY and run mode in CI or a non-interactive terminal. `vitest run` is a single run. `--changed [since]` runs tests affected by changed files. `vitest related <files> --run` is for lint-staged hooks. `--since-last-run` (5.1.0+) needs the cache. FACT [2]
- Jest: `--watch` (changed files), `--watchAll`. `--onlyChanged` needs a git or hg repo and "a static dependency graph (ie. no dynamic requires)". `--changedSince=<branch>`. `--findRelatedTests <files>`. FACT [7]
- Node: `--watch` is stable since v22.0.0 and v20.13.0 in the CLI page; the test page marks `node --test --watch` as experimental. The two pages disagree. FACT (conflict) [8][17]
- Node: the docs read show no changed-files flag. UNTESTED (the CLI page was read in two truncated parts; the last part, from about character 185000, was not seen)

### 5. Sharding

- Vitest: `--shard=<index>/<count>`; not allowed with `--watch`; splits test files, not test cases; pair with `--reporter=blob` and `--merge-reports`. FACT [2][13]
- Jest: `--shard=<i>/<n>`, 1-based; the `testSequencer` must implement `shard`. FACT [7]
- Node: `--test-shard=<index>/<total>` since v20.5.0 and v18.19.0; `shard` cannot be used with watch. FACT [17][8]
- Overlap: CI sharding and merge jobs belong to `cicd-pipelines` (GRAPH-05). This skill records only that the flag exists. [11]

### 6. Mocking modules

- Vitest `vi.mock`: hoisted above imports; only `import` is affected, not `require`; mocks only external access (an in-module call still uses the original); factory result cached until `vi.unmock`; variables from outside the factory need `vi.hoisted`; modules imported in a setup file are not mocked. Partial mocks use `importOriginal`. FACT [4][5]
- Vitest `vi.spyOn` works on exports; it does not work in Browser Mode without a workaround. FACT [4]
- Jest `jest.mock`: hoisted when `babel-jest` is used; per-file scope; setup-file imports block mocking; partial mocks use `jest.requireActual`; ES6 default exports need `__esModule: true` in the factory. FACT [16][10b]
- Jest ESM: support is experimental; needs `--experimental-vm-modules`; `jest.mock` is CJS only; `jest.unstable_mockModule` plus dynamic `import()` for ESM; "hoisting doesn't work". FACT [10]
- Jest `jest.spyOn` calls the real method by default. `restoreAllMocks` restores only mocks from `spyOn` and `replaceProperty`. Config flags `clearMocks`, `resetMocks`, `restoreMocks` default to `false`. FACT [3b][16]
- Node `mock.fn`, `mock.method`: restored automatically when made through the test context (`t.mock`). `mock.module` needs `--experimental-test-module-mocks`, is "Stability: 1.0 - Early development", since v22.3.0 and v20.18.0. FACT [8][18]
- Vitest advice: "clear or restore mocks before or after each test". `vi.stubGlobal` and `vi.stubEnv` do not reset on their own; use `unstubGlobals`/`unstubEnvs` config or `vi.unstubAll*`. FACT [4]

### 7. Mocking time

- Vitest: `vi.useFakeTimers()` wraps `setTimeout`, `setInterval`, `setImmediate`, `Date`; `process.nextTick` and `queueMicrotask` are not faked by default (add to `toFake`). `vi.setSystemTime` moves the clock; "will not automatically reset between different tests"; `vi.useRealTimers()` restores and discards scheduled timers. Fake timers move only when advanced. Tick modes `interval` and `nextTimerAsync` exist. FACT [4][5][19]
- Jest: `jest.useFakeTimers()` (backed by `@sinonjs/fake-timers`); `advanceTimersByTime`, `runAllTimers`, `runOnlyPendingTimers`; `setSystemTime` does not fire timers; it is "a global operation" that affects other tests in the same file; `runAllTimers` on recursive timers aborts after 100000 timers. `fakeTimers` config sets defaults. FACT [3b][16][20]
- Node: `mock.timers.enable({ apis: [...] })`, `tick`, `runAll`, `setTime`, `reset`; with `Date` the clock starts at epoch unless `now` is given; destructured imports such as `import { setTimeout } from 'node:timers'` are not supported. Stability mark of timers was not shown in the excerpt. FACT / UNTESTED (stability) [8][18]
- INFERENCE: for all three, restore real timers in `afterEach`, because fake state is global to the file or worker.

### 8. Fakes at seams (network, files, environment)

- Vitest recommends MSW for requests: `setupServer(...handlers)` from `msw/node` in a setup file; `beforeAll` `server.listen({ onUnhandledRequest: 'error' })`; `afterEach` `server.resetHandlers()`; `afterAll` `server.close()`. With `'error'`, an unmocked request throws instead of reaching the network. FACT [21]
- MSW home page: intercepts requests in browser and Node, works with any request client. The `setup-server` and best-practices pages returned 404, so the `onUnhandledRequest` default value is not confirmed from MSW docs. FACT / UNTESTED [22][23]
- Jest mock-functions page shows `jest.mock('axios')` and says this avoids "slow and fragile tests". FACT [10b]
- Vitest has separate guides for mocking the file system; the page was not read. UNTESTED [4]
- INFERENCE: prefer a fake at the program's own boundary (a small interface the code owns) over mocking a third-party module, because module mocks depend on hoisting and module format rules above.

### 9. Test structure and naming

- Vitest: `test`/`it`, `describe`; `test.each` (Jest-compatible), `test.for` (Vitest, passes context); `test.extend` for fixtures; `test.todo`, `test.skip`, `test.fails`; default timeout 5 seconds (`testTimeout`); `retry` option. FACT [12]
- Default file patterns: Vitest `**/*.{test,spec}.?(c|m)[jt]s?(x)`; Jest `__tests__` folders plus `.test`/`.spec` suffix; Node `*.test`, `*-test`, `*_test`, `test-*`, `test.*` and `test/**`, with `.ts` patterns unless `--no-strip-types`. FACT [24][3b][8]
- Jest globals are injected by default (`injectGlobals: true`); `@jest/globals` imports otherwise. FACT [3b][25]
- Node: `describe`/`it` alias `suite`/`test`; subtests are cancelled if not awaited. FACT [8]
- Naming advice (INFERENCE): the full name (describe plus test) is what `-t` and `--test-name-pattern` match, so names should read as a sentence and be unique.

### 10. TypeScript handling

- Vitest runs TypeScript through Vite; no type check (INFERENCE from docs not read here). UNTESTED
- Jest: Babel preset does not type-check; `ts-jest` can. Run `tsc` separately for type errors. FACT [25]
- Node: type stripping is on by default since v23.6.0 and v22.18.0, stable since v25.2.0 and v24.12.0. It ignores `tsconfig.json`, supports erasable syntax only (no `enum`, runtime `namespace`, parameter properties), needs file extensions in imports, and refuses `.ts` files under `node_modules`. `--experimental-transform-types` was removed in v26.0.0. FACT [26]

### 11. Keeping tests fast

- Vitest: read the `Duration` phases first; `vitest doctor` benchmarks configs; `isolate: false` with `threads` is fastest if tests share no state; `happy-dom` is cheaper than `jsdom`; set `test.dir` to narrow the search; `fsModuleCache` (on by default) and `NODE_COMPILE_CACHE` help reruns. FACT [13][2]
- Jest: `--maxWorkers=4` or `--runInBand` on slow CI; `--no-cache` for stale transform output. FACT [15]
- Node: `--test-isolation=none` trades isolation for speed. `--test-timeout` default is `Infinity`, so a hung test needs a timeout set. FACT [17]
- No real network (fake at the seam, `onUnhandledRequest: 'error'`) and no real time (fake timers) follow from the sections above. INFERENCE

### 12. Monorepos

- Vitest: projects are "particularly useful for monorepo setups"; share config with `mergeConfig`; referenced project files do not inherit from the root. Root `coverage`/`reporters` apply globally. FACT [3]
- Jest: `projects: ['<rootDir>', '<rootDir>/examples/*']`; "great for monorepos". FACT [3b]
- Node: run `node --test` in each package or pass globs. INFERENCE
- Overlap: `cicd-pipelines` already handles Turborepo and Nx affected runs and monorepo CI. Do not repeat. [11]

### 13. Detecting the existing setup

All INFERENCE from file conventions in the docs, except where cited:

- Config files: `vitest.config.*` (also `vite.config.*` with a `test` key), `jest.config.*` or a `jest` key in `package.json`, none for Node's runner. The `cicd-pipelines` intake script already looks for `vitest`, `jest` and `@playwright/test` in dependencies and for `vitest.config.`, `jest.config.`, `playwright.config.` files. FACT [11]
- `package.json` `scripts.test` and its siblings; `devDependencies`; `packageManager` and lockfile for the install and run prefix.
- Node runner signal: `node --test` or `node:test` imports in test files, no runner dependency.
- Projects: `test.projects` (Vitest), `projects` (Jest).
- Node version: `.nvmrc`, `.node-version`, `engines.node`. It decides whether Node runs `.ts` directly (type stripping since 22.18 or 23.6). FACT [26]
- Test layout: co-located `*.test.ts` versus `__tests__` or `test/` directories (match against the default patterns above).
- Setup files and global mocks: Vitest `setupFiles`; Jest `setupFilesAfterEnv`. Mocks of modules imported there do not apply. FACT [5][16]

## Draft: what the TypeScript/Node entry could say (candidate content, not a decision)

Detect first. Read `package.json` scripts and dependencies, the runner config and the Node version. Use the runner that is there. Never add a second runner.

Write tests that are runnable:
- One behavior per test; the describe plus test name reads as a sentence and is unique.
- No real network: fake at a seam the code owns, or use MSW with unhandled requests set to error.
- No real time: use fake timers, set the clock explicitly, restore real timers after each test.
- No shared state between tests or files; clean up global stubs (`stubGlobal`, `stubEnv`, spies) after each test.
- Mock modules only when the seam cannot be injected; know the hoisting and ESM limits of the runner.
- Keep setup cheap: build data in the test; avoid heavy environments (DOM) unless needed.
- A test needs no order and no other test's output, so any file can run alone and in parallel.

Group and filter: use projects (Vitest, Jest) or directories (Node) so a change runs its own group; give the filter commands from the rules file.

Review mode checks: `.only` left in, real timers and sleeps, unmocked network, shared mutable module state, mocks not restored, test names that repeat, concurrency flags on tests that share state.

## Facts a setup rules file would record for a TypeScript/Node repo

| Fact | How to detect |
|---|---|
| Runner (Vitest, Jest, Node) | dependencies, config files, `node --test` in scripts |
| Runner version | lockfile or `package.json` |
| Node version | `.nvmrc`, `.node-version`, `engines.node`, `packageManager` |
| Package manager and run prefix | lockfile, `packageManager` |
| Single-run command (not watch) | `scripts.test`; Vitest needs `run` or CI mode; Jest `--ci` |
| Run one file / one test name | runner syntax from the filtering section |
| Groups and the command per group | `test.projects` / `projects` names; directories for Node |
| Changed-files command | Vitest `--changed`; Jest `--onlyChanged` or `--changedSince`; none documented for Node |
| Shard flag | per runner |
| Worker limit flag | Vitest `--maxWorkers`; Jest `--maxWorkers`; Node `--test-concurrency` |
| Test file pattern and layout | config `include`/`testMatch`, or defaults |
| Setup files | `setupFiles`, `setupFilesAfterEnv`, MSW server file |
| Fake conventions in use | MSW present, fake timers config (`fakeTimers`, `unstubGlobals`), `restoreMocks` flags |
| Module format | `"type"` in `package.json`; decides Jest ESM limits and Node type stripping |
| Type check command | `tsc` script (Jest and Node do not type-check) |

The repo test command in the `cicd-pipelines` skill requires script names `lint`, `typecheck`, `test`, `build` (create.md line 36). A rules file should record the real script names. [11]

## Options (UNRANKED; the owner decides)

A. Entry scope: (1) one TypeScript/Node entry with a short section per runner; (2) one entry per runner; (3) one entry that names the runner-neutral rules and links to a per-runner facts table.

B. Node runner depth: (1) full coverage of `node:test`; (2) detect and follow it, with a note that module mocks and watch are early-development or conflicting; (3) leave it out of v1.

C. Module mocking rule: (1) prefer seams and avoid module mocks; (2) allow module mocks with the per-runner limits listed; (3) record the repo's current practice and follow it.

D. Network fake: (1) MSW when present or when the repo asks; (2) any interceptor the repo already uses; (3) fakes at an owned interface only.

E. Concurrency inside a file: (1) never turn on; (2) only for I/O-bound tests with no shared state; (3) follow the repo.

F. Isolation off for speed: (1) never; (2) only in a separate group with a stated reason; (3) follow the repo.

G. Changed-files in the rules file: (1) record the command where the runner has one; (2) record it only as a hint, because the workflow decides when tests run (out of scope per the map).

H. Type checking: (1) the skill states that the runner does not type-check and tells the agent to record the `tsc` command; (2) leave it to CI.

## Gaps

- Vitest default `exclude`, `restoreMocks`/`mockReset` defaults and `test.dir` details were not read.
- The Vitest file-system mocking guide and MSW API/best-practices pages were not read (404 for the two MSW pages).
- The Node `--test-changed` or similar flag: the last part of the CLI page (after character 185000) was not seen; absence is UNTESTED. Node test-runner sections on hooks, `run()` options and global setup were truncated.
- Node watch stability conflicts between the CLI page (stable) and the test page (experimental).
- Jest `randomize` option and Jest sequencing docs were not read.
- No command was run; every claim is from docs. All run-time behavior (for example hoisting with a given transform, parallel safety of a given suite) is UNTESTED.
- No other test libraries (Playwright, Testing Library, supertest, Sinon) were read. Playwright appears only through the `cicd-pipelines` skill.
- Existing skills and guides (the installed TDD skill, public agent skills on testing) were not reviewed here. See `testing-existing-skills.md` (ticket 811).

## Sources

Read (HTTP 200 through WebFetch). Version labels are those the pages showed.

1. https://vitest.dev/guide/parallelism (v5.1.1)
2. https://vitest.dev/guide/cli (v5.1.1)
3. https://vitest.dev/guide/projects (v5.1.1)
3b. https://jestjs.io/docs/configuration (Jest 30.5; last 11595 characters not read)
4. https://vitest.dev/guide/mocking (v5.1.1)
5. https://vitest.dev/api/vi
6. https://nodejs.org/api/typescript.html (see 26)
7. https://jestjs.io/docs/cli (30.5)
8. https://nodejs.org/api/test.html (first 100000 characters, then 40000-140000)
9. https://jestjs.io/docs/getting-started (30.5)
10. https://jestjs.io/docs/ecmascript-modules
10b. https://jestjs.io/docs/mock-functions
11. Local: `skills/cicd-pipelines/` in this repo (`scripts/intake.py` lines 32-33, `create.md`, `rules/job-graph.md`, `rules/cost.md`)
12. https://vitest.dev/api/test
13. https://vitest.dev/guide/improving-performance
14. https://jestjs.io/docs/configuration (`maxWorkers`; same page as 3b)
15. https://jestjs.io/docs/troubleshooting
16. https://jestjs.io/docs/jest-object
17. https://nodejs.org/api/cli.html (read in two parts; last about 85000 characters not read)
18. https://nodejs.org/api/test.html (same page as 8, later part)
19. https://vitest.dev/guide/mocking/timers
20. https://jestjs.io/docs/timer-mocks
21. https://vitest.dev/guide/mocking/requests
22. https://mswjs.io/docs/
23. Failed (404): https://mswjs.io/docs/best-practices/ and https://mswjs.io/docs/api/setup-server/
24. https://vitest.dev/config/include
25. https://jestjs.io/docs/getting-started (same page as 9)
26. https://nodejs.org/api/typescript.html (same page as 6)

No web search was used; pages were fetched by URL. Not fetched: the Node.js `mock.module` release notes outside the test page, the Vitest changelog, and the Vitest/Jest pages on coverage.
