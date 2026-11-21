# TypeScript/Node entry

This file is loaded for a file whose `detected.entries` value is `typescript`, after [general.md](../general.md). It holds how-to and check details only. The rule text, the severities and the report contract live in the general file, in [review.md](../review.md) and in [write.md](../write.md). The facts below come from [docs/research/testing-typescript.md](../../../docs/research/testing-typescript.md) and from the Vitest, Jest and Node.js docs; they are research facts, not settings of the repo rules file.

Text that belongs to one runner sits under a `### Vitest`, `### Jest` or `### node:test` sub-heading, or in a `Vitest:`, `Jest:` or `node:test:` bullet of a rule subsection. Text outside these holds only facts that are true for every runner of the language.

## Detection notes

Read these intake facts of the language `typescript` first: `detected.facts.typescript.runner.name`, `.commands.test`, `.commands.worker_flag`, `.commands.typecheck`, `.layout.test_paths` and `.groups`. The rules file value wins over the detected fact (`rules.settings.commands.typescript`, `rules.settings.runner.typescript` and `rules.settings.groups`).

- The runner gate: the runner of the language is `rules.settings.runner.typescript.name`, else `detected.facts.typescript.runner.name`. For each of `vitest`, `jest` and `node:test`, the content of this entry that belongs to that runner (its sub-headings, its tables and its `Vitest:`, `Jest:` or `node:test:` bullets) applies only when the runner is that runner. For any other value (null included) no runner content applies: no path derivation, no command form, no group selector reading, no list command, no runner bullet and no `Not checked:` entry of this entry. The general file alone decides every rule for that runner.
- The package manager comes from the recorded settings, else the detected fact, else it is npm. The exec prefix of the package manager is `npx` for npm, `pnpm exec` for pnpm, `yarn` for yarn and `bunx` for bun.
- The module format (ESM or CommonJS) comes from `package.json` (`"type"`) and decides the import style of a new test file: use the import style of the neighbor files.
- The type-check command is `commands.typescript.typecheck`. It can be null.

### Jest

- Read the Jest config (`jest.config.*` or the `jest` key of `package.json`) for `testMatch`, `testRegex`, `roots`, `projects`, `testPathIgnorePatterns` and the `displayName` of each project. Read the Jest root as the language root `R`.

### node:test

- Read the Node version (`detected.facts.typescript.runner.node_version`). A `.ts` test file is derived only for the extensions of Table N3, and a derived `.ts` test file that does not run shows as `not run (no test collected)`.

## Commands

The product command that runs tests is `commands.typescript.test` (recorded, else detected), or the `command` of a group of the language.

### Vitest

The single-run form is `vitest run`. The effective form of a plain Vitest command is `<exec prefix> vitest ...`. Read a command in this order.

1. Strip leading `NAME=value` assignments. The same strip applies again to the text of a resolved script. A `CI=true` assignment is stripped on purpose.
2. Classify the command by its first words. The first row that matches decides.
   - Exec form: the words are `npx vitest`, `pnpm exec vitest`, `yarn vitest`, `bunx vitest`, or `vitest` alone (the last only inside a script text). The command is a candidate for step 3 as written.
   - Script call: the words are exactly `npm test`, `npm run <name>`, `pnpm test`, `pnpm run <name>`, `yarn test`, `yarn run <name>` or `bun run <name>`. Every word after the script name is an argument (a `--` token is kept as an argument). The command is replaced by the text of `scripts.<name>` (`test` for the `test` forms) in the `package.json` of the language root, and the arguments are appended to that text. This is one step: a script text that is itself a script call is a wrapper. A missing script is a wrapper. The `pre` and `post` scripts are not read and not run by the resolved command.
   - Anything else (including `pnpm <name>` and `yarn <name>` forms that are not listed): a wrapper.
3. A candidate with none of `&&`, `||`, `;`, `|`, `$(`, a backtick or a redirect (outside quotes) is a plain Vitest command. Every other command is a wrapper.

The first row that matches decides.

| # | State of the command | Review timed run, fix run and write run |
|---|---|---|
| 1 | A command (plain or wrapper, after steps 1 and 2) that has an update mode: a token `-u`, `--update`, `--update=true`, `--update=all` or `--update=new` anywhere in its text, or an effective Vitest config with `update` set to `true`, `'all'` or `'new'` | Do not run it. Review's timed-run entry says `command includes an update mode`, and write's result is `not run (command includes an update mode)`. The forms `--update=none` and `--update=false` are not an update mode. |
| 2 | Wrapper | Run it as it is. Add no flag and no operand. Keep only the in-scope test cases. Run without a worker flag. |
| 3 | Plain Vitest command that Table 4 reads as a finding (a watch marker or the bare form) | Do not run it. Review's timed-run entry says `command is a watch command`, and write's result is `not run (<reason>)`. |
| 4 | Plain Vitest command with the subcommand `list` or `bench` | Not a test command: do not run it. The result is the same as for a command with no known command. |
| 5 | Plain Vitest command that runs once (Table 4 reads it as no finding) | Remove every `--maxWorkers` and `--reporter` option (the `--flag=value` and the `--flag value` form), then append `--maxWorkers=2` and `--reporter=verbose`. When the command has no path operand and no token of the unreadable class of Table 2, also append the in-scope test file paths (relative to the Vitest root) as operands before the options. Otherwise add no operand and keep only the in-scope test cases. |

Examples:

- Example: `npx vitest run -u` => row 1
- Example: `npm test` with the script `vitest run --update=all` => row 1
- Example: `npm run ci` with the script `vitest run && tsc` => row 2
- Example: `npm run missing` with no such script => row 2
- Example: `npm test` with the script `npm run ci` => row 2
- Example: `make test` => row 2
- Example: `npx vitest` => row 3
- Example: `npx vitest --watch` => row 3
- Example: `npx vitest list --filesOnly` => row 4
- Example: `CI=true npx vitest run --project unit` => row 5
- Example: `pnpm exec vitest run src/price` => row 5

The commands run with `CI=true` set, as the review and write steps say. The reporter argument `--reporter=verbose` is the reporter argument of this entry: it prints every test case as `✓ <file> > <names> <N>ms`. A verbose line is matched to a test case by the file path, then ` > `, then the full test name, then the final duration (a number that ends with `ms` or `s`). Text before the path is ignored.

Group selector classes. Tokens are the words after `vitest` and its subcommand (a subcommand is the first token that is exactly `run`, `watch`, `dev`, `related`, `list` or `bench`). Every token belongs to exactly one class. A named flag with a value reads the same in the forms `--flag value` and `--flag=value`. A project list that holds only `!` exclusions selects every project except the excluded ones.

| Class | Tokens | Review reads it as | Write: can the group select a file |
|---|---|---|---|
| Path operand | a token that is not a flag and not the value of a named flag, and does not end with `:<number>` | a substring filter: it selects every test file whose path (relative to the Vitest root) contains it; several operands select the union | yes, when the derived path contains it |
| Project | `--project <name>`, `-p <name>` (repeatable; `*` wildcard; a leading `!` excludes) | the group applies to the projects whose `name` matches; it selects the files that the `include` patterns of those projects match | yes, when the derived path matches an `include` of a matching project |
| Directory | `--dir <path>` | the test files below the path that the effective `include` matches | yes, when the derived path is below it |
| Name filter | `-t <pattern>`, `--testNamePattern <pattern>` | a filter on the full test name | no file |
| Fixed | `--maxWorkers <n>`, `--reporter <name>`, `--outputFile <path>`, `--retry <n>`, `--run`, `--silent`, `--no-color`, `--passWithNoTests`, `--no-file-parallelism`, `--update`, `-u`, `--coverage` | narrows nothing | narrows nothing |
| Unreadable | every other token: any flag that is not named above (for example `--changed`, `--shard`, `--root`, `--config`, `--exclude`, `--typecheck`), the subcommand `related`, and a path operand that ends with `:<number>` | unreadable (see below) | no file |

Examples:

- Example: `npx vitest run src/price` => class Path operand
- Example: `npx vitest run --project unit` => class Project
- Example: `npx vitest run --dir tests` => class Directory
- Example: `npx vitest run -t slow` => class Name filter
- Example: `npx vitest run --maxWorkers 2` => class Fixed
- Example: `npx vitest run --changed` => class Unreadable
- Example: `npx vitest run src/a.test.ts:12` => class Unreadable

- Selection state for review. The first item that applies gives the state. (1) A token of the unreadable class: the group is unreadable for the general file, and the list command decides its membership. When that command cannot run, the group stays unreadable and the `Not checked:` line names it. (2) Otherwise each class that the group has selects the union of what its tokens select, and the group selects the intersection of what its classes select. (3) A group with Fixed tokens only, or no token, has no selector: it selects every test case of the language root. A wrapper group command is unreadable and has no list command.
- Selection state for write. The first item that applies gives the state. (1) A token of the unreadable or name filter class, or a command that Table 1 does not run (rows 1 to 4): the group selects no file. (2) Otherwise the group selects the derived path when, for each of the classes path operand, project and directory that the group has, at least one token of that class selects it. (3) A group with Fixed tokens only, or no token, selects every file of the language root. A wrapper group selects nothing.
- List command. A group command that Table 1 does not run as a test (rows 1 to 4) has no list command: it stays unreadable and the `Not checked:` line names it. A group with the subcommand `related` has no list command in any form (also with `--run`). For every other plain Vitest group command (Table 1 row 5), take its effective form, remove every token of the Fixed class (with its value) and the subcommand `run`, insert the subcommand `list` right after `vitest` and add `--filesOnly`. The output is one test file path per line, relative to the Vitest root (the language root, where the command runs). Text before the path (such as a project label) is ignored, and a file is selected when the rest of a line is equal to its path. Write runs no list command.
- Size of a selection. A path operand, a project or a directory selects test cases by file; `-t` selects test cases by name (the general rules apply).

### Jest

A Jest command is read in the same three steps as a Vitest command (strip leading `NAME=value` assignments, classify by the first words, a candidate with a wrapper marker is a wrapper), and a script call is resolved in one step by the same rule. The effective form of a plain Jest command is `<exec prefix> jest ...`. Only the exec forms differ: `npx jest`, `pnpm exec jest`, `yarn jest`, `bunx jest`, or `jest` alone (the last only inside a script text). The exec form words are not operands. The single-run form is a Jest command with `--ci`. The command under test is `commands.typescript.test` (recorded, else detected) or a group `command`. The first row of Table J1 that applies decides.

**Table J1 (Jest, review timed run, fix run and write run):**

| # | State of the command | Review timed run, fix run and write run |
|---|---|---|
| 1 | A command (plain or wrapper, after steps 1 and 2) with an update mode: a token `-u`, `--updateSnapshot` or `--updateSnapshot=true` | Do not run it. Review's timed-run entry says `command includes an update mode`, and write's result is `not run (command includes an update mode)`. The form `--updateSnapshot=false` is not an update mode. |
| 2 | Wrapper | Run it as it is. Add no flag and no operand. Keep only the in-scope test cases. Run without a worker flag. |
| 3 | Plain Jest command with a watch marker (Table J4 row 3) | Do not run it. Review's timed-run entry says `command is a watch command`, and write's result is `not run (<reason>)`. |
| 4 | Plain Jest command with a token `--listTests`, `--showConfig`, `--clearCache`, `--version` or `--help` | Not a test command: do not run it. The result is the same as for a command with no known command (write: `not run (command is not a test command)`). |
| 5 | Plain Jest command, any other | Remove every `--maxWorkers`, `-w`, `--runInBand`, `-i`, `--json`, `--outputFile` and `--ci` option (with its value, in both forms). Append `--ci --maxWorkers=2 --json`. When the command has no path operand and no unreadable token (Table J2), also append the in-scope test file paths (relative to the Jest root) as operands and the flag `--runTestsByPath`. Otherwise add no operand and keep only the in-scope test cases. |

Examples:

- Example: `npx jest -u` => row 1
- Example: `npm test` with the script `jest --updateSnapshot` => row 1
- Example: `npm run ci` with the script `jest && tsc` => row 2
- Example: `npm run missing` with no such script => row 2
- Example: `npm test` with the script `npm run ci` => row 2
- Example: `make test` => row 2
- Example: `npx jest --watch` => row 3
- Example: `npx jest --watchAll` => row 3
- Example: `npx jest --watch --listTests` => row 3
- Example: `npx jest --listTests` => row 4
- Example: `npx jest --showConfig` => row 4
- Example: `CI=true npx jest --ci --maxWorkers=2` => row 5
- Example: `pnpm exec jest src/price` => row 5
- Example: `npx jest --watch=false` => row 5
- Example: `npx jest --no-watch --updateSnapshot=false` => row 5

The commands run with `CI=true` set, as the review and write steps say. Jest does not need the `CI` variable: the run uses the `--ci` flag. The reporter argument `--json` is the reporter argument of this entry: Jest prints the result as JSON on stdout (other output goes to stderr), and the result does not depend on the reporter that Jest picks. A per-test duration is read from `testResults[].assertionResults[]`: `testResults[].name` is the absolute path of the test file, `assertionResults[].fullName` is the full test name, and `assertionResults[].duration` is the duration in ms. A missing or null `duration` means no duration. A test case whose file and `fullName` pair is shared by more than one in-scope test case has no duration (the case is skipped).

Group selector classes (Table J2). Tokens are the words after `jest`. Every token belongs to exactly one class. A named flag with a value reads the same in the forms `--flag value` and `--flag=value`. Jest has no directory class: a directory is a path operand.

| Class | Tokens | Review reads it as | Write: can the group select a file |
|---|---|---|---|
| Path operand | a token that is not a flag and not the value of a named flag, or the value of `--testPathPatterns` | a regular expression matched against the test file path relative to the language root, written with `/`; with `--runTestsByPath`, an operand is equal to that path (a leading `./` dropped); `--testPathPatterns <regex>` always reads as a regular expression; several operands select the union; an operand that starts with `^` or `/` is unreadable, because Jest matches the absolute path, which this entry does not rebuild | yes, when the derived path matches (or, with `--runTestsByPath`, equals it) |
| Project | `--selectProjects <name> ...` (the `displayName` values; takes values until the next flag) | the files that the `testMatch` of those projects match | yes, when the derived path matches the `testMatch` of a project with that `displayName` (the agent reads the Jest config; the write grader cannot, so it reads a project group as selecting none) |
| Name filter | `-t <pattern>`, `--testNamePattern <pattern>` | a filter on the full test name | no file |
| Fixed | `--ci`, `--maxWorkers <n>`, `-w <n>`, `--runInBand`, `-i`, `--verbose`, `--json`, `--outputFile <path>`, `--reporters <name>`, `--silent`, `--coverage`, `--passWithNoTests`, `--watchman`, `--no-watchman`, `--cache`, `--no-cache`, `--runTestsByPath`, `-u`, `--updateSnapshot` | narrows nothing | narrows nothing |
| Unreadable | every other token (for example `--onlyChanged`, `-o`, `--changedSince`, `--findRelatedTests`, `--shard`, `--config`, `--roots`, `--projects`, `--testMatch`, `--testPathIgnorePatterns`, `--bail`) | unreadable | no file |

Examples:

- Example: `npx jest src/price` => class Path operand
- Example: `npx jest --testPathPatterns src/price` => class Path operand
- Example: `npx jest --selectProjects unit` => class Project
- Example: `npx jest -t slow` => class Name filter
- Example: `npx jest --ci --maxWorkers 2` => class Fixed
- Example: `npx jest --onlyChanged` => class Unreadable
- Example: `npx jest ^src/price` => class Unreadable

- Selection state for review. The first item that applies gives the state. (1) A token of the unreadable class: the group is unreadable for the general file, and the list command decides its membership. When that command cannot run, the group stays unreadable and the `Not checked:` line names it. (2) Otherwise each class that the group has selects the union of what its tokens select, and the group selects the intersection of what its classes select. (3) A group with Fixed tokens only, or no token, has no selector: it selects every test case of the language root. A wrapper group command is unreadable and has no list command.
- Selection state for write. The first item that applies gives the state. (1) A token of the unreadable or name filter class, or a command that Table J1 does not run as a test (rows 1 to 4: an update mode, a wrapper, a watch marker, or a non-test command): the group selects no file. (2) Otherwise the group selects the derived path when, for each of the classes path operand and project that the group has, at least one token of that class selects it. (3) A group with Fixed tokens only, or no token, selects every file of the language root. A wrapper group selects nothing.
- List command. For a plain group command that Table J1 runs (row 5), take its effective form, remove every Fixed token with its value except `--runTestsByPath`, and add `--listTests`. The output is one absolute test file path per line; a file is selected when a line equals the absolute path of the file (the Jest root joined with its relative path). A group command that Table J1 does not run as a test (rows 1 to 4) and a wrapper group have no list command. Write runs no list command.

### node:test

A `node:test` command is read in the same three steps as a Vitest command, and a script call is resolved in one step by the same rule. Only the exec form differs: a plain command is a command whose first word is `node` and that has a token `--test` (options with values, such as `--import tsx`, may stand between). A `node` command with no `--test` token is a wrapper. The single-run form is `node --test`. The command under test is `commands.typescript.test` (recorded, else detected) or a group `command`. The first row of Table N1 that applies decides.

**Table N1 (`node:test`, review timed run, fix run and write run):**

| # | State of the command | Review timed run, fix run and write run |
|---|---|---|
| 1 | A command (plain or wrapper, after steps 1 and 2) with the token `--test-update-snapshots` | Do not run it. Review's timed-run entry says `command includes an update mode`, and write's result is `not run (command includes an update mode)`. |
| 2 | Wrapper | As row 2 of Table J1. |
| 3 | Plain `node:test` command with a watch marker (Table N4 row 2) | Do not run it. Review's timed-run entry says `command is a watch command`, and write's result is `not run (<reason>)`. |
| 4 | Plain `node:test` command, any other | Remove every `--test-concurrency`, `--test-reporter` and `--test-reporter-destination` option (with its value, in both forms). Append `--test-concurrency=2 --test-reporter=spec`. When the command has no path operand and no unreadable token (Table N2), also append the in-scope test file paths as operands, last. Otherwise add no operand and keep only the in-scope test cases. |

Examples:

- Example: `node --test --test-update-snapshots` => row 1
- Example: `npm test` with the script `node --test --test-update-snapshots` => row 1
- Example: `npm run ci` with the script `node --test && tsc` => row 2
- Example: `npm run missing` with no such script => row 2
- Example: `npm test` with the script `npm run ci` => row 2
- Example: `node tests/a.test.js` => row 2
- Example: `make test` => row 2
- Example: `node --test --watch` => row 3
- Example: `node --test --watch-path src` => row 3
- Example: `node --test` => row 4
- Example: `node --import tsx --test tests/a.test.ts` => row 4
- Example: `CI=true node --test --test-concurrency=2` => row 4

The commands run with `CI=true` set, as the review and write steps say. `node:test` writes no snapshot without `--test-update-snapshots`. The reporter argument `--test-reporter=spec` is the reporter argument of this entry (the default reporter on a non-TTY stdout can be `tap`). A per-test duration is read from the spec reporter: a line that starts with `✔` or `✖`, followed by the test name and a final duration `(<N>ms)` or `(<N>s)`. The full name is the names of the enclosing suites (the `▶` lines at a lesser indent) joined with ` > `, then the test name. The output holds no file path, so a full name that appears on more than one result line of the run (in scope or not) gets no duration for any test case with that name (the case is skipped). A suite line matches no test case and is ignored.

Group selector classes (Table N2). Tokens are the words after `node` and `--test`. Every token belongs to exactly one class. A named flag with a value reads the same in the forms `--flag value` and `--flag=value`. `node:test` has no project class and no directory class: a folder is a path operand.

| Class | Tokens | Review reads it as | Write: can the group select a file |
|---|---|---|---|
| Path operand | a token that is not a flag and not the value of a named flag: a file path, a folder, or a glob, relative to the root | it selects the test files that equal it, that are below it (the folder reading that this skill uses for recorded groups), or that the glob matches (`**` crosses folders, `*` does not cross `/`); a leading `./` is dropped; several operands select the union | yes, when the derived path equals it, is below it, or the glob matches |
| Name filter | `--test-name-pattern <pattern>`, `--test-skip-pattern <pattern>` | a filter on the full test name | no file |
| Fixed | `--test`, `--test-concurrency <n>`, `--test-reporter <name>`, `--test-reporter-destination <path>`, `--test-timeout <ms>`, `--test-isolation <mode>`, `--test-force-exit`, `--test-update-snapshots`, `--import <module>`, `--require <module>`, `-r <module>`, `--env-file <path>`, `--no-warnings`, `--experimental-test-coverage` | narrows nothing | narrows nothing |
| Unreadable | every other token (for example `--test-shard`, `--test-only`, `--test-rerun-failures`) | unreadable | no file |

Examples:

- Example: `node --test tests/unit` => class Path operand
- Example: `node --test --test-name-pattern slow` => class Name filter
- Example: `node --test --test-concurrency 2` => class Fixed
- Example: `node --test --test-shard=1/2` => class Unreadable

- Selection state for review. The same three items as for Jest (Table J2), with Table N2. There is no list command for `node:test`: an unreadable group stays unreadable and the `Not checked:` line names it.
- Selection state for write. The same three items as for Jest, with Table N1 rows 1 to 3 (an update mode, a wrapper and a watch marker) in item (1). A `node:test` operand selects the derived path when it equals the path, the path is below it, or the glob matches. A `node:test` command with a folder operand fails at run time on a runner that rejects it: the run result shows it.
- List command. None. This entry records that no `node:test` list command is confirmed (see Runner facts).

## Runner facts

Each fact below is confirmed from the docs on 2026-11-20 (Vitest v5.1.1; the list and reporter facts were also hand-run), or is marked as unconfirmed and not used.

### Vitest

- Confirmed: `vitest list` prints matching tests (with `--filesOnly`, test files), inherits the options of `vitest`, ignores reporters, and since Vitest 5 parses files statically; `--json` prints JSON (https://vitest.dev/guide/cli)
- Confirmed: Subcommands and watch: `vitest run` is a single run; `vitest watch` and its alias `vitest dev` watch; bare `vitest` watches, and falls back to a single run in CI or with no TTY; `-w, --watch` enables watch mode; `vitest related <files>` watches unless `--run` is passed; `vitest bench` runs benchmarks (https://vitest.dev/guide/cli)
- Confirmed: Options that the group reader names: `--maxWorkers <n>` (https://vitest.dev/config/maxworkers), `--reporter`, `--outputFile`, `--retry`, `--silent`, `--no-color`, `--passWithNoTests`, `--no-file-parallelism`, `-u, --update`, `--coverage`, `--dir`, `-t, --testNamePattern`, `--run` (https://vitest.dev/guide/cli)
- Confirmed: `-p, --project <name>` is repeatable, takes wildcards and `!` exclusion; the entries of `test.projects` have a unique `name` (https://vitest.dev/guide/cli and https://vitest.dev/guide/projects)
- Confirmed: A positional token filters test files by path substring, and `file.test.ts:<line>` targets a line (https://vitest.dev/guide/cli); the default `exclude` is `['**/node_modules/**', '**/.git/**']` (https://vitest.dev/config/exclude)
- Confirmed: Reporters: the default reporter prints per-file lines (a per-test line only for a slow test or in a failing file); the `verbose` reporter prints every test case with its duration; `--reporter=verbose` replaces the reporters of the config; the `minimal` reporter (used when an AI agent is detected) prints failed tests only and no summary (https://vitest.dev/guide/reporters)
- Confirmed: `retry` (config, `--retry` and a test option) takes a number or `{ count, delay, condition }`, default 0 (https://vitest.dev/config/retry and https://vitest.dev/api/test)
- Confirmed: `update` modes are `true` or `'all'`, `'new'` and `'none'`; when `update` is false, a local run acts as `new` and a CI run (`CI` set) acts as `none` (https://vitest.dev/config/update)
- Confirmed: `allowOnly` defaults to `!process.env.CI`, so a test with `only` fails the run in CI (https://vitest.dev/config/allowonly)
- Confirmed: Fake timers (`vi.useFakeTimers`, `vi.advanceTimersByTime`, `vi.advanceTimersByTimeAsync`, `vi.runAllTimers`, `vi.useRealTimers`, `vi.setSystemTime`; `toFake` lists the faked APIs), and `vi.waitFor` and `expect.poll` as polling helpers (https://vitest.dev/guide/mocking/timers and https://vitest.dev/api/vi)
- Confirmed: MSW for requests: `setupServer`, `server.listen({ onUnhandledRequest: 'error' })`, `server.resetHandlers()`, `server.close()` (https://vitest.dev/guide/mocking/requests)
- Confirmed: `restoreMocks`, `unstubEnvs` and `unstubGlobals` default to false (https://vitest.dev/config/restoremocks and https://vitest.dev/config/unstubglobals); `vi.stubEnv`, `vi.unstubAllEnvs`, `vi.stubGlobal` and `vi.unstubAllGlobals` (https://vitest.dev/api/vi)
- Confirmed: Snapshots: `toMatchSnapshot` and `toMatchInlineSnapshot` (the snapshot argument is the last argument, or second to last with property matchers), and property matchers such as `expect.any(String)` (https://vitest.dev/guide/snapshot)
- Confirmed: Call-order assertions: `toHaveBeenCalledBefore`, `toHaveBeenCalledAfter`, `toHaveBeenNthCalledWith` and `mock.invocationCallOrder` (https://vitest.dev/api/expect and https://vitest.dev/api/mock)
- Confirmed: Test options and modifiers: `test.skip` (alias `it.skip`), `test.todo`, `test.only`, `test.skipIf`, `test.fails` and `{ skip: true }` (https://vitest.dev/api/test); `describe.skip` and `describe.skipIf` (https://vitest.dev/api/describe)
- Confirmed: The default `include` pattern is `**/*.{test,spec}.?(c|m)[jt]s?(x)` (https://vitest.dev/config/include); `fileParallelism` is true by default and each file runs in its own isolated environment (https://vitest.dev/guide/parallelism)
- Unconfirmed, not used: a Vitest setting that fails the run for a test that passed only on retry; that Vitest does not type-check test files; the form of a project in a `vitest list` line or a verbose line (this entry matches on the path and the name only); the effect of `--watch=<value>` (every `--watch` form counts as a watch marker); the default `include` of a project that sets none (it is read as the default pattern of the root); and any changed-files command other than the detected `--changed` flag. Every runner fact that this entry uses has a `Confirmed:` line above. The assertion and mock API names that the rules below use (`expect.hasAssertions`, `resolves`, `rejects`, `vi.fn`, `vi.spyOn`, `fast-check`) are API names of the how-to, not runner facts.

### Jest

Confirmed on 2026-11-20 (Jest 30.5.2; facts marked `hand-run` were also run by hand).

- Confirmed: `--listTests` lists the test files that Jest runs for the arguments and exits (hand-run: absolute paths, one per line) (https://jestjs.io/docs/cli)
- Confirmed: `--ci` fails a new snapshot instead of writing it; `-u` and `--updateSnapshot` update snapshots (https://jestjs.io/docs/cli and https://jestjs.io/docs/snapshot-testing)
- Confirmed: `--watch` and `--watchAll` watch; `--no-watch` and `--watch=false` disable watch (https://jestjs.io/docs/cli)
- Confirmed: `--maxWorkers` and `-w` set the worker count (https://jestjs.io/docs/cli)
- Confirmed: `--json` prints the result as JSON and sends other output to stderr (hand-run: `assertionResults` with `fullName` and `duration`); `--verbose` prints every test case (https://jestjs.io/docs/cli)
- Confirmed: `--selectProjects` takes `displayName` values; `-t` and `--testNamePattern` filter by name; `--testPathPatterns` and `--runTestsByPath` select files (https://jestjs.io/docs/cli)
- Confirmed: `jest.retryTimes(n, options?)` retries failed tests; there is no config key or CLI flag for retries and none that fails a run on a retried pass (https://jestjs.io/docs/jest-object)
- Confirmed: `testMatch` (default), `testRegex`, `roots`, `testPathIgnorePatterns` (default) and `projects` decide which files are tests (https://jestjs.io/docs/configuration)
- Confirmed: Fake timers (`jest.useFakeTimers`, `advanceTimersByTime`, `advanceTimersByTimeAsync`, `runAllTimers`, `useRealTimers`, `setSystemTime`) (https://jestjs.io/docs/timer-mocks and https://jestjs.io/docs/jest-object)
- Confirmed: `test.skip` and its aliases, `test.todo` and `test.failing` (https://jestjs.io/docs/api)
- Confirmed: Snapshot matchers and property matchers (https://jestjs.io/docs/snapshot-testing)
- Confirmed: Options that a table names only to classify a token (`--runInBand`, `-i`, `--showConfig`, `--clearCache`, `--version`, `--help`, `--silent`, `--coverage`, `--passWithNoTests`, `--watchman`, `--cache`, `--reporters`, `--outputFile`, `--onlyChanged`, `--changedSince`, `--findRelatedTests`, `--shard`, `--config`, `--roots`, `--projects`, `--testMatch`, `--testPathIgnorePatterns`, `--bail`) are documented options; the entry does not state what they do (https://jestjs.io/docs/cli)
- Unconfirmed, not used: a Jest setting that fails the run for a test that passed only on retry; that Jest does not type-check test files; the effect of `--watchAll=false`; that Jest picks a summary reporter without per-test lines under an AI agent (seen in a hand run; the entry does not use the default reporter); a call-order matcher or a call-order property of a mock for Jest (neither is in the docs read); any changed-files command other than the detected `--onlyChanged`. The assertion and mock API names that the rules below use (`expect.hasAssertions`, `test.failing`, `jest.fn`, `jest.spyOn`, `toHaveBeenNthCalledWith`) are API names of the how-to, not runner facts.

### node:test

Confirmed on 2026-11-20 (Node.js 22.23.3; facts marked `hand-run` were also run by hand).

- Confirmed: `--test` and its default file patterns (TypeScript patterns unless `--no-strip-types`; hand-run: a `.ts` test file ran); glob operands (https://nodejs.org/api/test.html and https://nodejs.org/api/cli.html)
- Confirmed: `--test-concurrency` sets the number of test files that run at once (https://nodejs.org/api/cli.html)
- Confirmed: `--test-reporter` and the built-in reporters (`spec`, `tap`, `dot`, `junit`, `lcov`); the default reporter is `spec` on a non-TTY stdout since v23 (hand-run on 22.23.3: `tap`, so the entry names `--test-reporter=spec`); the spec reporter prints each test with its duration (hand-run) (https://nodejs.org/api/test.html)
- Confirmed: `--watch` with `--test` and `--watch-path` turn watch mode on (https://nodejs.org/api/cli.html)
- Confirmed: `--test-name-pattern`, `--test-skip-pattern`, `--test-only`, `--test-shard` and `--test-rerun-failures` (v24.7) select or rerun tests (https://nodejs.org/api/cli.html)
- Confirmed: `--test-isolation` (default `'process'`: each test file in its own child process) (https://nodejs.org/api/cli.html)
- Confirmed: `--test-update-snapshots` and `t.assert.snapshot` (https://nodejs.org/api/test.html and https://nodejs.org/api/cli.html)
- Confirmed: Options that a table names only to classify a token (`--test-timeout`, `--test-force-exit`, `--env-file`, `--experimental-test-coverage`, `--import`, `-r`, `--require`, `--no-warnings`, `--test-reporter-destination`) are documented on the CLI page (https://nodejs.org/api/cli.html)
- Confirmed: A folder operand is read as the files below it for group membership; a hand run on 22.23.3 rejected a folder operand at run time, so a group command with a folder operand fails when it runs and the run result shows it (hand-run) (https://nodejs.org/api/cli.html)
- Confirmed: `mock.fn`, `mock.method`, `mock.timers` (`enable`, `tick`, `reset`); `skip`, `todo` and `only` options and `t.skip`; `expectFailure`; `t.plan` (https://nodejs.org/api/test.html)
- Unconfirmed, not used: a `node:test` setting that fails the run for a test that passed only on retry; that `node:test` does not type-check test files; a `node:test` list command (no documented list or dry-run command is used); the first Node version that finds TypeScript test files by default (a derived `.ts` test file that does not run shows as `not run (no test collected)`).

## Layout

- The layout facts come from `layout.typescript.test_paths` (recorded, else detected: first path segments under the language root that hold test files), `file_pattern` and `setup_files`. `file_pattern` and `setup_files` are read for detection only.
- All paths below are relative to the language root `R`. The path that write reports is the derived path prefixed with `R` (no prefix when `R` is the repo root).

### Vitest

Test location for write (the path that a loaded entry derives for a product file `P`). A test file is a path that matches the `include` and no `exclude` of the effective Vitest config (the root `test.include`; with `test.projects`, the `include` of any project; the default pattern when none is set; the default `exclude`). The first row that applies decides.

| # | State of `P` | Derived path |
|---|---|---|
| 1 | `P` is outside `R`, is a declaration file (`.d.ts`), is a config file (`*.config.*`, `vitest.*`), is below `node_modules`, `dist`, `build` or `coverage`, or has an extension other than `.ts`, `.tsx`, `.js`, `.mjs`, `.cjs` | none (`no test location is known`) |
| 2 | A test file `<stem>.test.<ext>` or `<stem>.spec.<ext>` of `P` exists beside `P`, or at the mirrored path (row 4) | that file (`.test` first, then `.spec`); write adds test cases to it |
| 3 | The layout is co-located: `test_paths` is empty, holds `.`, or holds the first folder of `P` | `<folder of P>/<stem>.test.<ext of P>` |
| 4 | The layout is mirrored: `test_paths` holds exactly one folder `T` and its name is `test`, `tests` or `__tests__` | `T/<path of P below its first folder, if it has one>/<stem>.test.<ext of P>` |
| 5 | Every other state of `test_paths` | none (`no test location is known`) |

After rows 3 and 4, a derived path that is not a test file (by `include` or `exclude`) is none. A nested test folder (the intake keeps first path segments only) is read as the co-located layout. This entry names no group path: state 4 of "Test location" in [write.md](../write.md) never applies to TypeScript. A group that selects the derived path (state 3 and 5 of "Test location") is read by the write column of the group selector table above. The Group and Size cells follow "Group and size" of [write.md](../write.md).

Examples:

- Example: `P` = `types/api.d.ts` => row 1
- Example: `P` = `vitest.config.ts` => row 1
- Example: `src/price.ts` with `src/price.test.ts` beside it => row 2
- Example: `src/price.ts`, `test_paths` = `["src"]`, no test file yet => row 3
- Example: `src/price.ts`, `test_paths` = `["tests"]` => row 4
- Example: `src/price.ts`, `test_paths` = `["tests", "e2e"]` => row 5

### Jest

Test location for write (Table J3). The rows are the rows of the Vitest Layout table above, with the Jest parts below. A test file is a path that matches the effective `testMatch` (default `**/__tests__/**/*.?([mc])[jt]s?(x)` and `**/?(*.)+(spec|test).?([mc])[jt]s?(x)`) or `testRegex`, is in `roots`, and has no `testPathIgnorePatterns` match (default `/node_modules/`); with `projects`, any project counts. The first row that applies decides.

| # | State of `P` | Derived path |
|---|---|---|
| 1 | `P` is outside `R`, is a declaration file (`.d.ts`), is a config file (`*.config.*`, `jest.*`), is below `node_modules`, `dist`, `build` or `coverage`, or has an extension other than `.ts`, `.tsx`, `.js`, `.mjs`, `.cjs` | none (`no test location is known`) |
| 2 | A test file `<stem>.test.<ext>` or `<stem>.spec.<ext>` beside `P`, `__tests__/<stem>.test.<ext>` or `__tests__/<stem>.<ext>` beside `P`, or at the mirrored path (row 4), exists | that file; write adds test cases to it |
| 3 | The layout is co-located: `test_paths` is empty, holds `.`, or holds the first folder of `P` | `<folder of P>/<stem>.test.<ext of P>` |
| 4 | The layout is mirrored: `test_paths` holds exactly one folder `T` and its name is `test`, `tests` or `__tests__` | `T/<path of P below its first folder, if it has one>/<stem>.test.<ext of P>` |
| 5 | Every other state of `test_paths` | none (`no test location is known`) |

After rows 3 and 4, a derived path that is not a test file is none. A group that selects the derived path is read by the write column of Table J2. The Group and Size cells follow "Group and size" of [write.md](../write.md). This entry names no group path: state 4 of "Test location" in [write.md](../write.md) never applies to TypeScript.

Examples:

- Example: `P` = `types/api.d.ts` => row 1
- Example: `P` = `jest.config.ts` => row 1
- Example: `src/price.ts` with `src/price.spec.ts` beside it => row 2
- Example: `src/price.ts`, `test_paths` = `["src"]`, no test file yet => row 3
- Example: `src/price.ts`, `test_paths` = `["tests"]` => row 4
- Example: `src/price.ts`, `test_paths` = `["tests", "e2e"]` => row 5

### node:test

Test location for write (Table N3). The rows are the rows of the Vitest Layout table above, with the `node:test` parts below. A test file is a path that matches a default name pattern (`<name>.test.<ext>`, `<name>-test.<ext>`, `<name>_test.<ext>`, `test-<name>.<ext>`, `test.<ext>`, or any file below a folder named `test`) or a glob operand of the recorded test command. The first row that applies decides.

| # | State of `P` | Derived path |
|---|---|---|
| 1 | `P` is outside `R`, is a declaration file (`.d.ts`), is a config file (`*.config.*`), is below `node_modules`, `dist`, `build` or `coverage`, or has an extension other than `.ts`, `.js`, `.mjs`, `.cjs` (the default patterns have no TSX files) | none (`no test location is known`) |
| 2 | A test file `<stem>.test.<ext>` beside `P`, or at the mirrored path (row 4), exists | that file; write adds test cases to it |
| 3 | The layout is co-located: `test_paths` is empty, holds `.`, or holds the first folder of `P` | `<folder of P>/<stem>.test.<ext of P>` |
| 4 | The layout is mirrored: `test_paths` holds exactly one folder `T` and its name is `test`, `tests` or `__tests__` | `T/<path of P below its first folder, if it has one>/<stem>.test.<ext of P>` |
| 5 | Every other state of `test_paths` | none (`no test location is known`) |

After rows 3 and 4, a derived path that is not a test file is none. A group that selects the derived path is read by the write column of Table N2. The Group and Size cells follow "Group and size" of [write.md](../write.md). This entry names no group path: state 4 of "Test location" in [write.md](../write.md) never applies to TypeScript.

Examples:

- Example: `P` = `types/api.d.ts` => row 1
- Example: `P` = `src/view.tsx` => row 1
- Example: `src/price.ts` with `src/price.test.ts` beside it => row 2
- Example: `src/price.ts`, `test_paths` = `["src"]`, no test file yet => row 3
- Example: `src/price.ts`, `test_paths` = `["tests"]` => row 4
- Example: `src/price.ts`, `test_paths` = `["tests", "e2e"]` => row 5

## Libraries

- Property: `fast-check`. A property test states a property: a round trip, an invariant or a comparison with a simple model.
- Async: native promises and `async` test functions.

### Vitest

- Snapshot: `toMatchSnapshot` and `toMatchInlineSnapshot`, with property matchers for a nondeterministic value. Write a stored or inline snapshot by hand from the source of the expected value. A run with `CI=true` writes no new snapshot.
- Fakes: `vi.fn`, `vi.spyOn`, fake timers, MSW with `onUnhandledRequest: 'error'` for HTTP, `vi.stubEnv` and `vi.stubGlobal` with restores.

### Jest

- Snapshot: `toMatchSnapshot` and `toMatchInlineSnapshot`, with property matchers (`expect.any(String)`) or an injected clock (`jest.setSystemTime`) for a nondeterministic value. Write a stored or inline snapshot by hand from the source of the expected value. The run uses `--ci`, which fails a new snapshot instead of writing it.
- Fakes: `jest.fn`, `jest.spyOn`, `jest.useFakeTimers`, `jest.setSystemTime`, MSW with `onUnhandledRequest: 'error'` for HTTP, and a saved copy of `process.env` for an environment restore.

### node:test

- Snapshot: `t.assert.snapshot` reads a stored snapshot file; write that file by hand. The run writes no snapshot without `--test-update-snapshots`.
- Fakes: `node:assert/strict`, `mock.fn`, `mock.method`, `mock.timers`, `t.after` for a restore.

## Rules

### ASSERT-01

**How to write**:
- Vitest: end each test with `expect`, `assert`, `expect.assertions`, `expect.hasAssertions`, or a check on a promise with `resolves` or `rejects`. Use `expect.poll` for a value that changes with time. Use `test.fails` for a known failing case, and `test.todo` for a placeholder.
- Jest: end each test with `expect`, `expect.assertions`, `expect.hasAssertions`, or a check on a promise with `.resolves` or `.rejects`. Use `test.failing` for a known failing case, and `test.todo` for a placeholder.
- node:test: end each test with an `assert.*` call (also `t.assert.*`), `t.plan` or `assert.rejects`. Use `test` with `{ expectFailure }` for a known failing case, and `todo` for a placeholder.

**Check details**:
- Vitest: a `test` or `it` body with no `expect`, `assert`, `expect.assertions`, `rejects`, `resolves` or `expect.poll` is a candidate. A test that only calls the code under test has no assertion. A `test.todo` is a placeholder, not a test. Read helper functions that assert.
- Jest: a `test` or `it` body with no `expect`, `expect.assertions`, `expect.hasAssertions`, `.resolves` or `.rejects` is a candidate. `test.todo` is a placeholder, not a test. `test.failing` holds an assertion that must fail. Read helper functions that assert.
- node:test: a `test` or `it` body with no `assert.*`, `t.assert.*`, `t.plan` or `assert.rejects` is a candidate. `todo` is a placeholder, not a test. A test with `{ expectFailure }` still needs an assertion. Read helper functions that assert.

### ASSERT-02

**How to write**:
- Vitest: compute the expected value by hand from the spec and write it as a literal. Do not pass the input back as the expected value. For a mock, assert on the effect that the code has after it used the double.
- Jest: compute the expected value by hand from the spec and write it as a literal. Do not pass the input back as the expected value. For a mock, assert on the effect that the code has after it used the double.
- node:test: compute the expected value by hand from the spec and write it as a literal. Do not pass the input back as the expected value. For a mock, assert on the effect that the code has after it used the double.

**Check details**:
- Vitest: look for `expect(f(x)).toBe(x)` where `f` must change `x`, `vi.fn().mockReturnValue(v)` followed by `expect(result).toBe(v)` on the same value, and `toEqual` with the object that the test passed in.
- Jest: look for `expect(f(x)).toBe(x)` where `f` must change `x`, `jest.fn().mockReturnValue(v)` followed by `expect(result).toBe(v)` on the same value, and `toEqual` with the object that the test passed in.
- node:test: look for `assert.equal(f(x), x)` where `f` must change `x`, `mock.fn(() => v)` followed by `assert.equal(result, v)` on the same value, and `assert.deepEqual` with the object that the test passed in.

### ASSERT-03

**How to write**:
- Vitest: redact a time, a random id or a path with a property matcher (`expect.any(String)`), an injected clock (`vi.setSystemTime`) or a normalised path. Run snapshots in the single-run command without an update mode. Write snapshots by hand.
- Jest: redact a time, a random id or a path with a property matcher (`expect.any(String)`), an injected clock (`jest.setSystemTime`) or a normalised path. Run snapshots in the single-run command with `--ci` and without an update mode. Write snapshots by hand.
- node:test: redact a time, a random id or a path before the `t.assert.snapshot` call, or inject the clock. Run snapshots in the single-run command without `--test-update-snapshots`. Write the snapshot file by hand.

**Check details**:
- Vitest: read the single-run command and the config for `-u`, `--update`, `--update=all`, `--update=new` and `update: true | 'all' | 'new'`. The default `new` mode outside CI is not an update flag, and `CI=true` gives `none`. An inline snapshot with no argument has no stored value. Read each stored and inline snapshot for a time, a random id or a path with no redaction.
- Jest: read the single-run command for `-u` and `--updateSnapshot` (the entry's own run adds `--ci`, which fails a new snapshot). Look for a time, a random id or a path in `toMatchSnapshot` or `toMatchInlineSnapshot` with no property matcher (`expect.any(String)`) and no injected clock (`jest.setSystemTime`). The absence of `--ci` in the repo command is not a finding.
- node:test: read the single-run command for `--test-update-snapshots`. Look for a `t.assert.snapshot` of a nondeterministic value (a time, a random id or a path). The absence of `--test-update-snapshots` is the default and is not a finding.

### RUN-01

**How to write**:
- Vitest: keep `retry` at 0. Do not set `retry` in the config, the command or a test option.
- Jest: do not call `jest.retryTimes`. Keep every test free of a retry.
- node:test: do not use `--test-rerun-failures` in a command. No retry option of `test()` is confirmed.

**Check details**:
- Vitest: read the config for `retry` greater than 0, the command for `--retry`, and test code for `{ retry: n }` or `retry: { count: n }`. Every positive form is a finding, because no setting that fails a run on a retried pass is confirmed. A loop in test code that runs a check again until it passes is also a finding.
- Jest: every `jest.retryTimes(n)` call (in a test file or a setup file) with `n` above 0 is a finding, because no setting that fails a run on a retried pass is confirmed. A loop in test code that runs a check again until it passes is also a finding.
- node:test: `--test-rerun-failures` in a command is a finding (it reruns failed tests from a state file). A loop in test code that runs a check again until it passes is also a finding.

### RUN-02

**How to write**:
- Vitest: use `vi.useFakeTimers` and advance time with `vi.advanceTimersByTime`, or wait for the event (`vi.waitFor`, `expect.poll`, an awaited promise). Do not wait on the real clock.
- Jest: use `jest.useFakeTimers` and advance time with `jest.advanceTimersByTime` (or `advanceTimersByTimeAsync`, `runAllTimers`), or wait for the event with an awaited promise. Do not wait on the real clock. Jest has no documented polling helper that this entry uses.
- node:test: use `mock.timers.enable` and advance time with `mock.timers.tick`, or wait for the event with an awaited promise. Do not wait on the real clock. `node:test` has no documented polling helper that this entry uses.

**Check details**:
- Vitest: look for `setTimeout` promises, `node:timers/promises`, `sleep` helpers and `await new Promise(...)` with a timer in test code. Not a finding: `vi.useFakeTimers` with `advanceTimers*`, `vi.waitFor`, `expect.poll` and awaiting the event. Sleep forms also serve the sleep part of the group rule.
- Jest: look for `setTimeout` promises, `sleep` helpers and `await new Promise(...)` with a timer in test code. Not a finding: `jest.useFakeTimers` with `advanceTimersByTime(Async)` or `runAllTimers`, and awaiting the event. Sleep forms also serve the sleep part of the group rule.
- node:test: look for `setTimeout` promises, `node:timers/promises`, `sleep` helpers and `await new Promise(...)` with a timer in test code. Not a finding: `mock.timers.enable` with `mock.timers.tick`, and awaiting the event. Sleep forms also serve the sleep part of the group rule.

### RUN-03

**How to write**:
- Vitest: use an in-process fake. Use MSW (`setupServer`, `server.listen({ onUnhandledRequest: 'error' })`, `server.resetHandlers()`, `server.close()`) for HTTP. For a medium test listen on port 0. Never connect to another host.
- Jest: use an in-process fake: `jest.spyOn(globalThis, 'fetch')`, or MSW (`setupServer`, `server.listen({ onUnhandledRequest: 'error' })`, `server.resetHandlers()`, `server.close()`) for HTTP. For a medium test listen on port 0. Never connect to another host.
- node:test: use an in-process fake: `mock.method(globalThis, 'fetch', ...)`, or MSW for HTTP. For a medium test listen on port 0. Never connect to another host.

**Check details**:
- Vitest: look for `fetch`, `http` and `https` requests, `net` connect, `axios`, `undici`, `got` and `node-fetch` in test code. An MSW handler runs in the process and is not a socket. Loopback is a finding only in a small test; `listen(0)` on loopback is allowed in a medium test.
- Jest: look for `fetch`, `http` and `https` requests, `net` connect, `axios`, `undici`, `got` and `node-fetch` in test code. A `jest.spyOn(globalThis, 'fetch')` fake and an MSW handler run in the process and are not sockets. Loopback is a finding only in a small test; `listen(0)` on loopback is allowed in a medium test.
- node:test: look for `fetch`, `http` and `https` requests, `net` connect, `axios`, `undici`, `got` and `node-fetch` in test code. A `mock.method(globalThis, 'fetch', ...)` fake and an MSW handler run in the process and are not sockets. Loopback is a finding only in a small test; `listen(0)` on loopback is allowed in a medium test.

### RUN-04

**How to write**:
- Vitest: fake the slow I/O or time, shrink the work, or move the test to a group of a larger size.
- Jest: fake the slow I/O or time, shrink the work, or move the test to a group of a larger size.
- node:test: fake the slow I/O or time, shrink the work, or move the test to a group of a larger size.

**Check details**:
- Vitest: use the timed run of [review.md](../review.md) with `--reporter=verbose`. Match each verbose line to an in-scope test case by file and name, and read the final duration. When the command is a wrapper, the output may hold no per-test duration; then the `Not checked:` entry is `RUN-04 (no per-test duration in the output (exit code N))`. A wrapper that prints durations is read like any other output.
- Jest: use the timed run of [review.md](../review.md) with `--json` (Table J1). Read `assertionResults[].duration` of each in-scope test case by file and `fullName`; a missing or null duration, or a pair that more than one in-scope test case shares, means no duration. When the command is a wrapper, the output may hold no per-test duration; then the `Not checked:` entry is `RUN-04 (no per-test duration in the output (exit code N))`. A wrapper that prints durations is read like any other output.
- node:test: use the timed run of [review.md](../review.md) with `--test-reporter=spec` (Table N1). Match each result line to an in-scope test case by its full name and read the final duration. A full name that more than one result line has gives no duration, and only that case is skipped. When the command is a wrapper, the output may hold no per-test duration; then the `Not checked:` entry is `RUN-04 (no per-test duration in the output (exit code N))`. A wrapper that prints durations is read like any other output.

### RUN-05

**How to write**:
- Vitest: give a skip a reason in a comment on the line above, or in the test name. Fix or delete the test.
- Jest: give a skip a reason in a comment on the line above, or in the test name. Fix or delete the test.
- node:test: give a skip a reason: `skip: '<reason>'`, `t.skip('<reason>')` or a comment on the line above. Fix or delete the test.

**Check details**:
- Vitest: look for `test.skip`, `it.skip`, `describe.skip`, `{ skip: true }`, `test.skipIf(true)` and `describe.skipIf(true)` with no comment line above and no reason in the name. `test.todo` and a skip under a platform condition are not findings.
- Jest: look for `test.skip`, `it.skip`, `describe.skip`, `xit`, `xtest` and `xdescribe` with no comment line above and no reason in the name. `test.todo` is not a finding.
- node:test: look for `skip: true`, `t.skip()` with no message, `it.skip` and `describe.skip` with no comment above. `skip: '<reason>'`, `t.skip('<reason>')`, `todo` and a platform condition are not findings.

### PAR-01

**How to write**:
- Vitest: listen on port 0 and read the port with `server.address()`.
- Jest: listen on port 0 and read the port with `server.address()`.
- node:test: listen on port 0 and read the port with `server.address()`.

**Check details**:
- Vitest: look for a literal port in `listen`, `fetch`, `connect` or a URL constant that a test uses.
- Jest: look for a literal port in `listen`, `fetch`, `connect` or a URL constant that a test uses.
- node:test: look for a literal port in `listen`, `fetch`, `connect` or a URL constant that a test uses.

### PAR-02

**How to write**:
- Vitest: give each test its own state: a temp directory, a value that the test owns, `vi.stubEnv` with `vi.unstubAllEnvs`, `vi.stubGlobal` with `vi.unstubAllGlobals`. Each file runs in its own isolated environment, but the tests of one file share its module state.
- Jest: give each test its own state: a temp directory, a value that the test owns, and a saved copy of `process.env` that `afterEach` restores. The tests of one file share its module state.
- node:test: give each test its own state: a temp directory, a value that the test owns, and a restore in `afterEach` or `t.after`. Each test file runs in its own process by default (`--test-isolation`), but the tests of one file share state.

**Check details**:
- Vitest: look for module-level state that a test writes, `process.env` writes without `vi.stubEnv` and a restore, `process.chdir`, fixed paths, `vi.stubGlobal` without `vi.unstubAllGlobals` (or the `unstubGlobals` config), and shared files.
- Jest: look for module-level state that a test writes, `process.env` writes with no restore in `afterEach`, `process.chdir`, fixed paths, shared files, and a global that the test sets with no restore.
- node:test: look for module-level state that a test writes, `process.env` writes with no restore in `afterEach` or `t.after`, `process.chdir`, fixed paths, shared files, and a global that the test sets with no restore.

### GRP-01

**How to write**:
- Vitest: put the test case where a recorded group selects it. A Vitest project is a group, and its `include` decides which files it holds. For a small group use no file system, child process, database or sleep.
- Jest: put the test case where a recorded group selects it. A Jest project is a group (its `displayName` is the project name, selected by `--selectProjects`). For a small group use no file system, child process, database or sleep.
- node:test: put the test case where a recorded group selects it. `node:test` has no project: a group is a set of files that an operand or a glob selects. For a small group use no file system, child process, database or sleep.

**Check details**:
- Vitest: read each group command with the group selector table above. A group with an unreadable token is decided by `vitest list --filesOnly` (see Commands). A group whose list command cannot run stays unchecked. Read `node:fs`, `node:child_process` and database client calls for the I/O half of the rule, and the `RUN-02` sleep forms for the sleep half.
- Jest: read each group command with Table J2. A group with an unreadable token is decided by `jest --listTests` (see Commands). A group whose list command cannot run stays unchecked. Read `node:fs`, `node:child_process` and database client calls for the I/O half of the rule, and the `RUN-02` sleep forms for the sleep half.
- node:test: read each group command with Table N2. This entry records no list command for `node:test`, so a group with an unreadable token stays unreadable and the `Not checked:` line names it. Read `node:fs`, `node:child_process` and database client calls for the I/O half of the rule, and the `RUN-02` sleep forms for the sleep half.

### DBL-01

**How to write**:
- Vitest: write a fake by hand and assert on its state. Use call-order assertions only when the order is the behavior.
- Jest: write a fake by hand and assert on its state. Use a call-order assertion only when the order is the behavior.
- node:test: write a fake by hand and assert on its state. Use a call-order assertion only when the order is the behavior.

**Check details**:
- Vitest: look for `toHaveBeenCalledBefore`, `toHaveBeenCalledAfter`, `mock.invocationCallOrder` and `toHaveBeenNthCalledWith` sequences where a fake or a state check would do.
- Jest: look for `toHaveBeenNthCalledWith` sequences and `mock.calls` index order where a fake or a state check would do. No call-order matcher is named for Jest, because none is confirmed.
- node:test: look for `mock.fn().mock.calls` order assertions where a fake would do.

### TS-01

**How to write**:
- Vitest: record `commands.typescript.test` as a single-run command (`vitest run`). Do not use `vitest`, `vitest watch`, `vitest dev`, `--watch` or `vitest related` without `--run` as a single-run command.
- Jest: record `commands.typescript.test` as a single-run command: `<exec prefix> jest --ci` (the detected form, for example `npx jest --ci`). Do not use `--watch` or `--watchAll` in a single-run command.
- node:test: record `commands.typescript.test` as a single-run command: `node --test`. Do not use `--watch` or `--watch-path` in a single-run command.

**Check details**:
- Vitest: the commands in scope are `commands.typescript.test` when recorded, else `scripts.test` of the language root `package.json` (when the script exists), and every group command of the language. Each is read by Table 1, and the table below ignores row 1 of Table 1 (an update mode is an `ASSERT-03` matter, not a watch matter), so a command with an update mode still gets its verdict here. The first row of the table below that applies to a command gives its verdict. `TS-01` is a finding when at least one command has the verdict "finding". It gives one row in all. The `Where` cell lists the rules-file line of the command (the `test` key or the group `command`) when it is recorded, and, for a resolved script, the `package.json` line of the script. The check applies when a TypeScript file is in scope.
- Jest: the same commands in scope, read by Table J1 (row 1 ignored) and judged by Table J4 below. "Table 1" in the text above means Table J1 for Jest and Table N1 for `node:test`.
- node:test: the same commands in scope, read by Table N1 (row 1 ignored) and judged by Table N4 below.

Table 4 (Vitest):

| # | Command after Table 1 | Verdict |
|---|---|---|
| 1 | Wrapper | not decided: no finding; one `Not checked:` entry (the form is below), with the names `test` for the test command and the group names, comma separated |
| 2 | Plain Vitest command with the subcommand `list` or `bench` | no finding (not a test run) |
| 3 | A watch marker: the subcommand `watch` or `dev`, or a token `--watch`, `--watch=<value>` or `-w` | finding (a `--watch=false` form is also a finding: the fix is the `run` subcommand) |
| 4 | The subcommand `run`, or a token `--run` | no finding |
| 5 | The subcommand `related` (with no `--run`) | finding |
| 6 | Any other plain Vitest command (no subcommand: the bare form) | finding: bare Vitest watches in a terminal and runs once only in CI or with no TTY |

Examples:

- Example: `npm run ci` with the script `vitest run && tsc` => row 1
- Example: `npx vitest bench` => row 2
- Example: `npx vitest --watch` => row 3
- Example: `npx vitest watch` => row 3
- Example: `npx vitest run` => row 4
- Example: `npx vitest related src/a.ts --run` => row 4
- Example: `npx vitest related src/a.ts` => row 5
- Example: `npx vitest` => row 6

- Not checked entry form: `TS-01 (command of <names> is not a plain Vitest command)`. The entry is written only for the Vitest runner. A runner that no loaded entry covers is not checked for `TS-01` and gets no entry.

Table J4 (Jest):

| # | Jest command after Table J1 | Verdict |
|---|---|---|
| 1 | Wrapper | not decided: no finding; one `Not checked:` entry (the form is below) |
| 2 | Plain, with a token `--listTests`, `--showConfig`, `--clearCache`, `--version` or `--help` | no finding (not a test run) |
| 3 | Plain, with a token `--watch`, `--watchAll`, `--watch=<value>` where the value is not `false`, or `--watchAll=<value>` (any value, because the effect of `--watchAll=false` is unconfirmed); the forms `--watch=false` and `--no-watch` are documented disable forms and are not a marker, but a command with a `--watch` token is a marker | finding |
| 4 | Plain, any other (Jest runs once without a watch flag) | no finding |

Examples:

- Example: `npm run ci` with the script `jest && tsc` => row 1
- Example: `npx jest --listTests` => row 2
- Example: `npx jest --watch --listTests` => row 2
- Example: `npx jest --watch` => row 3
- Example: `npx jest --watchAll` => row 3
- Example: `npx jest --watch --watch=false` => row 3
- Example: `npx jest --ci` => row 4
- Example: `npx jest --watch=false` => row 4
- Example: `npx jest --no-watch -w 2` => row 4
- Example: `npx jest -u` => row 4

Table N4 (`node:test`):

| # | `node:test` command after Table N1 | Verdict |
|---|---|---|
| 1 | Wrapper (this includes a command with no `--test` token) | not decided: no finding; one `Not checked:` entry (the form is below) |
| 2 | Plain, with a token `--watch`, `--watch=<value>` or `--watch-path` (any form; `--watch-path` turns watch on) | finding |
| 3 | Plain, any other | no finding |

Examples:

- Example: `npm run ci` with the script `node --test && tsc` => row 1
- Example: `node tests/a.test.js` => row 1
- Example: `node --test --watch` => row 2
- Example: `node --test --watch=true` => row 2
- Example: `node --test --watch-path src` => row 2
- Example: `node --test` => row 3
- Example: `node --test --test-update-snapshots` => row 3

- Not checked entry forms for Jest and `node:test`: `TS-01 (command of <names> is not a plain Jest command)` and `TS-01 (command of <names> is not a plain node:test command)`. The Vitest form stays. There is one `Not checked:` bullet in all, with the form of the runner. Each entry is written only for its own runner.

## Design how-to

- Kinds: unit for pure logic; integration for a boundary or local I/O; property with `fast-check` for an invariant; snapshot for a structured output.
- Sizes: a small test case uses no I/O and no real sleep; a medium test case may use a temp directory and loopback on port 0.
- Doubles: put I/O, the clock, the network and randomness behind a seam. A real collaborator first, then a hand-written fake.
- Parallel safety: each test owns its temp directory and its port. Do not rely on test order.
- Flakiness: find the cause (shared state, the real clock, a fixed port, unordered collections). Do not hide it with a retry.
- Test points: the public interface of the module and the system boundaries. Import the product file with the import style of its neighbors.
- Write the test so that it passes the recorded `typecheck` command; skip this when that command is null. Write does not run that command.

### Vitest

- Fakes: `vi.fn`, `vi.spyOn`, fake timers, MSW with `onUnhandledRequest: 'error'`, `vi.stubEnv` and `vi.stubGlobal` with restores.
- Async: native promises. Snapshot: property matchers, and inline snapshots written by hand.
- Projects as groups: a Vitest project is a group, and its `include` decides which files it holds.

### Jest

- Fakes: `jest.fn`, `jest.spyOn`, `jest.useFakeTimers`, `jest.setSystemTime`, MSW with `onUnhandledRequest: 'error'`, and a saved copy of `process.env` that a hook restores.
- Async: native promises. Snapshot: property matchers, and inline snapshots written by hand. The run uses `--ci`.
- Projects as groups: a Jest project is a group. Its `displayName` is the project name, and `--selectProjects` selects it.

### node:test

- Fakes: `node:assert/strict`, `mock.fn`, `mock.method`, `mock.timers`, and `t.after` for a restore.
- Async: native promises. Snapshot: a stored snapshot file written by hand (`t.assert.snapshot` reads it; the run writes none without `--test-update-snapshots`).
- No projects: `node:test` has no project concept. A group is a set of files that an operand or a glob selects.
