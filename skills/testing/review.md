# Review steps

Review existing tests against the rules of [general.md](general.md) and write a report. The skill changes no file until the user approves. The reply of the user starts the fix flow (see "Fix on approval").

## Scope

The files in scope are the files that step 1 of the review flow in [SKILL.md](SKILL.md) takes.

- A path that the user names must exist and be a test file by the name-only rule of that step, or be a directory. A directory means the test files below it (by the name-only rule) that git does not ignore. When a named path does not exist, is not a test file, or is a directory with no such file, the review stops before step 1 below: name each such path, and ask the user which files to review. This is the same outcome as for no file found.
- A product file holds no test file of its own. Inline Rust test modules (`#[cfg(test)] mod tests`) in a product file are not in scope, because a product file is never a file in scope.

## Steps

1. Read the intake JSON that [SKILL.md](SKILL.md) made for the files in scope. Run no other shell command for the rules or the facts. The only commands that a review runs before the report are the timed run (see "Timed run") and a list command that a loaded language entry confirms.
2. Take each setting from the `rules.settings` object. A section that is missing (see `rules.missing_sections`) or an optional key that is absent falls back to the `detected.facts` of the language. When `rules.error` is set, `rules.settings` is empty and every setting falls back.
3. Take the disabled ids from `rules.settings.rules.disabled`. This list is empty when the rules file is absent or `rules.error` is set, and a value that is not a list gives no id.
   - Skip each distinct disabled id that is in the catalogue and is not in `rules.disabled_without_reason`. Line (a) of the report lists them.
   - Check each id in `rules.disabled_without_reason` that has rule text, as any other id. Line (b) of the report lists them. An id without rule text is not checked and is named nowhere.
   - Ignore each id in `rules.unknown_ids`. Line (c) of the report lists them.
4. Check each file in scope against each id that has rule text in [general.md](general.md) (and in the loaded entries, for their check details). Read the test code, the runner config and the rules file. Run no test in this step. Size and group first: settle the size of each in-scope test case as "Size and group of a test case" in [general.md](general.md) says, from `rules.settings.groups`, else `detected.facts` (the detected group fact is empty today). Then `GRP-01`, `RUN-03` and the other static ids. A disabled id with a reason is not checked and makes no `Not checked:` entry. When `GRP-01` is disabled, still settle the sizes: `RUN-03` and `RUN-04` use them. For each failed rule, note every `file:line` place. A rule is one row, at the severity that the catalogue gives. Note each id that you could not check, with its reason, for note line (e).
5. Timed run, for `RUN-04` only (see "Timed run"). Make it after step 4 and before the report.
6. Write the report as your final message. Use the report contract below.
7. With at least one row, stop. Make no edit to any file before the user approves. When the user replies to the approval line, follow "Fix on approval". With zero rows the review ends with the report.

## Timed run

`RUN-04` needs one timed run. The run is not a fix. Review makes no edit before the user approves, and the run is skipped when it would not be safe or would not give durations.

1. Make a run for each language that has at least one small or medium sized in-scope test case. Make none when there are no sizes, when every sized test case is large, or when `RUN-04` is disabled with a reason.
2. Use the single-run test command of that language: `rules.settings.commands.<language>.test`, else the detected fact. When the command is a plain runner command (no wrapper script), append the narrowing arguments for the in-scope test files: the file paths when the runner takes file paths as operands, or the arguments that a loaded entry names for the runner. Otherwise run the command as it is and keep only the in-scope test cases.
3. Set the worker flag to 2 workers. The flag comes from `commands.<language>.worker_flag`, else from the detected fact. Build the form that sets 2 workers from it. When no flag is known, run without one.
4. Skip the run when the command includes an update mode (a flag or setting that writes new or changed snapshots, as `ASSERT-03` says), or when it is a watch command (it has a watch flag or a watch subcommand, or a form that a loaded entry names as a watch form: for Vitest, the bare form, the `related` form without `--run` and every watch marker of its `TS-01` table; for Jest, `--watch` and `--watchAll`; for `node:test`, `--watch` and `--watch-path`).
5. Run `git status --porcelain` before the run. When that call fails (the folder is not a git repository), make no run. Run it again after the run. Set the environment variable `CI=true` for the run. Stop a run that lasts more than 10 minutes. Add no reporter flag, except the reporter argument that a loaded entry names for per-test durations (Vitest: `--reporter=verbose`, Jest: `--json`, `node:test`: `--test-reporter=spec`): read the per-test durations from the default output of the runner, or from the output of that reporter argument.
6. When the status after the run differs from the status before it, a runner wrote a file. Remove nothing, discard the durations of that run, and make the `RUN-04` entry of note line (e) say `the run wrote files, left in place: <paths>`. A rewrite of a file that was already modified or untracked does not show in the status.
7. Compare the duration of each in-scope sized test case with the limit of its size. A finding needs a duration strictly over the limit. Skip a large or unsized test case and a test case that has no duration. A run that ends with failing tests still gives durations.

`RUN-04` is not checked, and note line (e) says why, when: there are no sizes; no test command is known; the command is a watch command; the command includes an update mode; the run lasts more than 10 minutes; the run wrote files; `git status --porcelain` fails (the folder is not a git repository); or no in-scope sized test case has a duration (this reason covers a command that cannot start; it states the exit code).

## Report contract

The report is your final message. It has these parts, in this order.

1. The title `# testing review: <scope>`. The scope is the paths of the files in scope, joined with a comma and a space, or `changed tests` when you took the changed files yourself.
2. The line `**Result: N critical, N required, N suggestions.**`. Each `N` is the number of rows of that severity.
3. The note lines. Write each one only when it applies, at most once, in this order:
   - (a) `Disabled (reason recorded, not checked): <ids>.` The ids are comma separated.
   - (b) `No reason line, checked anyway: <ids>.`
   - (c) `Unknown ids in rules.disabled, ignored: <ids>.`
   - (d) The fallback line. Write it only when the rules file is absent or `rules.missing_sections` is not empty. It is `Detected for this run: <names>. Run /testing setup to record them.` The names are the `rules.missing_sections` entries, comma separated, or `all settings (no rules file)` when the file is absent. When `rules.error` is set, it is `Rules file error: <message> (line <N>). Every setting is detected for this run. Run /testing setup.` Leave out ` (line <N>)` when `rules.error.line` is null.
   - (e) The not-checked line. Write it only when some id was not checked. It is `Not checked: <entry>[; <entry>...].` Each entry is `<ids> (<reason>)`, with the ids comma separated. Write one entry for each distinct reason. This line states why an id was not checked. The entries:
     - No sizes: `GRP-01, RUN-03, RUN-04 (no groups in the rules file and none detected)`. `RUN-04` has no second entry. For a language with no group in a scope of several languages, write `<language>: ` before the reason.
     - An unreadable group: `GRP-01, RUN-03, RUN-04 (selector of group <name> unreadable)`, or `(list command of group <name> failed)`. One entry for each group. The ids are not checked only for the test cases that the group might select; `RUN-04` still runs for the others.
     - The timed run, for `RUN-04`: the reason of "Timed run", in plain words: `command includes an update mode`, `command is a watch command`, `no test command is known`, `run timed out after 10 minutes`, `git status unavailable`, `the run wrote files, left in place: <paths>` or `no per-test duration in the output (exit code N)`. When the scope holds sized test cases of more than one language, write `<language>: ` before the reason, one entry for each language.
     - A Rust group whose command starts with neither `cargo test` nor `cargo nextest`: `RS-01 (group <name> command is not a cargo command)`. One entry for each such group.
     - A single-run command or group command of the TypeScript runner that is a wrapper: `TS-01 (command of <names> is not a plain Vitest command)`, `TS-01 (command of <names> is not a plain Jest command)` or `TS-01 (command of <names> is not a plain node:test command)`, with the form of the runner. The names are `test` for the test command and the group names, comma separated. One entry in all.
     - A disabled id with a reason is in line (a) and not here. An id that is disabled without a reason is checked anyway (line (b)); when it cannot be checked, it is also here.
4. One table for each severity that has a row, in the order `## Critical`, `## Required`, `## Suggestions`. The header is `| # | Rule | Where | Problem | Fix |`. The Rule cell is one rule id. The Where cell holds all `file:line` places of that rule. Numbers start at 1 and run on across the tables with no gap.
5. With at least one row, the last section is `## Approve`. Its text is exactly:

```
Reply with the findings to fix: `all`, `none`, a list such as `1,3,5`, or a range such as `1-12`.
```

The report has no ⚑ mark, no 🔒 mark and no other section. A report with zero rows has the title, the Result line with zeros and the note lines. It has no table and no `## Approve` section. This differs on purpose from the `cicd-pipelines` report, which keeps `## Approve` with `There is nothing to approve.`: this skill has nothing to approve, so it asks nothing.

## Fix on approval

The user replies to the approval line. Edit only the findings that the reply approves.

1. **Read the reply.** The numbers refer to the `#` column of the latest report in the conversation. A reply with no report in the conversation, or after a report with zero rows, edits nothing: it offers a new review, or says that there is nothing to fix.
2. **Reply grammar.** The reply is `all`, `none` or a selection. A selection is a comma-separated list. Each item is a row number or a range `a-b` with `a` less than or equal to `b` (`3-3` is one number). A list and ranges can mix (`1,3-5,9`). Spaces around commas and inside a range, and the case of `all` and `none`, do not matter. A number that is listed twice, or in two overlapping ranges, counts once. A number that is not a row of the report, a descending range, `all` or `none` mixed with numbers, an unknown word or an empty reply is invalid: edit nothing, name the invalid part, state this grammar and wait.
3. **`none`.** Edit no file and run no command. Say that no fix was applied.
4. **Edit.** Apply the Fix of each approved row at each `file:line` place of its Where cell, in the order of the numbers, with the Edit tool. Change nothing else: no line of an unapproved row, no formatting and no other file.
5. **Run the affected tests.** Run the tests of the edited files with the single-run test command: the `commands.<language>.test` setting, else the detected fact. Add the worker-flag fact set to 2 workers, in the syntax of the runner. When no worker flag is known, run without one and say so. When a loaded entry names command forms for the runner, build the command as steps 2 to 5 of "Timed run" say. Use the command of each language of the edited files. Report `pass`, `fail` or `not run` with the reason. When no test command is known, the result is `not run`. Never report `pass` for tests that did not run.
