# Write module

`/testing write` writes runnable tests for a change, runs them and reports. Run the steps in this order. Never skip a step and never reorder them. Write never asks the user a question and never waits for a plan approval. Every input state maps to one defined path, and every product file that gets no test is named in the report with its reason (see "Report contract").

The flow in [SKILL.md](SKILL.md) has already found the product files and run the intake script. Its output is the input of this module. The general file ([general.md](general.md)) is loaded.

Write edits no product file. It adds test cases, and in an existing test file it adds only test cases, helpers and import lines and changes no existing test case.

## Step 1: Settings

Take each setting from `rules.settings`. A missing section (see `rules.missing_sections`), an absent optional key or a set `rules.error` falls back to `detected.facts` for this run. Write ignores `rules.disabled`: an id that review skips is still followed by write.

## Step 2: Choose

For each product file, in the order of the files:

1. Pick the test points from `## Test points` of [general.md](general.md).
2. Pick the kind from `## Kinds of tests` of [general.md](general.md).
3. Pick the size and the group as "Group and size" says.
4. When a loaded entry exists for the language, use its how-to for each rule.
5. Give each test case a one-line reason.
6. Give each expected value of an assertion a source (see "Criterion for test wrong or product wrong"). A test case with no source for its expected value is not written.

A product file gets no test, and is reported as not written, when no test location is known for it (see "Test location"), when it has no test point, or when no test point has a test case with a source. The reason is the first of these that applies: `no test location is known`, `no test point`, `no test case has a source for its expected value`.

## Step 3: Write

Put each test at its test location (see "Test location"). Add test cases. In an existing test file (the test location can name one) add test cases, helpers and import lines, and change no existing test case. Edit no product file. Write a stored snapshot by hand from the source of the expected value, never from a run output. Never use an update mode.

## Step 4: Self-check

Read each new test case against every rule text of [general.md](general.md): `## Rules`, `## Kinds of tests`, `## Test points`, `## Design topics`, `## Sizes and groups`, `## Doubles and seams`, `## Parallel safety` and `## Flakiness`. Change the test case until none of those rules would flag it. The sections `## Kinds of tests`, `## Test points` and `## Design topics` are followed, not flagged. The exceptions are `GRP-01` in the no-group states of "Group and size", `GRP-01` for a test location that no readable group selects, and `RS-01` (a repository setting, not a test-case rule).

## Step 5: Run

Run the new test files. Step 6 may run again, with the same rules.

- The command is the `commands.<language>.test` setting, else the detected fact.
- Build it as steps 2 to 4 of "Timed run" in [review.md](review.md) say, with the files that write wrote to as the in-scope test files to narrow to: set 2 workers with the worker flag, use no watch command and no update mode.
- Set the environment variable `CI=true` and stop a run that lasts more than 10 minutes, as step 5 of "Timed run" says. Write does not run `git status`, because it writes files on purpose.
- The run is one per language. The result of each file follows "Run result rule", so it is never `pass` for tests that did not run.
- The run result of a file is that of the last run that completed. When a re-run cannot complete, the fix loop ends and the Reason of the test says so.

## Step 6: Fix

Classify each failing new test case once per failure by "Criterion for test wrong or product wrong".

- A failure that names no test case (a compile, parse or collection error) counts as one failure of its test file. It is a "test wrong" case. A file that still fails after 2 tries is kept failing, with `(file)` in the Test column and its path in the File column.
- A failing existing test case is not classified and not fixed. It makes the run result `fail` and is listed in it.
- Test wrong: fix the test case and run again. Make at most 2 fix tries in all for that test case. A test case that still fails after 2 tries stays, and the report lists it as kept failing.
- Product wrong: keep the test case, make no fix try, and report it as a found bug.

## Step 7: Report

Write the report as your final message, as "Report contract" says.

## Run result rule

Every run state maps to one result. The result of a test file is the first of these that applies:

1. `not run (<reason>)`: no command is known, or the command cannot start, is a watch command, has an update mode, or runs more than 10 minutes.
2. `fail (<names>)`: a test case of the file failed. A failure that names no test case is named by the path of the test file that holds it. Also `fail`: the run has a failure or a non-zero exit that no reported file holds. Then every file of the language gets `fail (<name or exit code>)`.
3. `not run (no test collected)`: the run completed with no failure for the file, but a new test case of the file is not shown as executed.
4. `pass`.

A test case is shown as executed when the output names it, or when the output gives an executed count (for its file, else for the whole run) that is at least the number of new test cases. Write adds no reporter flag.

## Group and size

The size of a test case is what "Size and group of a test case" in [general.md](general.md) gives: the smallest size among the readable groups that select its file. Write cannot move the file: the test location is the one that "Test location" gives. An unreadable group never counts. A group that selects only by a name filter selects test cases, not files.

- A readable group selects the test location: the wanted size is the size of that group (the smallest, when several select it). Write writes the test cases to fit it, with the double rule of `## Kinds of tests` in [general.md](general.md), so that review gives no `GRP-01` for them. The Reason cell says `size of group <name>`.
- No readable group selects it: the wanted size comes from `## Kinds of tests` in [general.md](general.md), and the Reason cell says why the Group is `none`. Review can report `GRP-01` there. That is the one defined case where review can report `GRP-01` for a written test. It holds when the language has no group, every group is unreadable, the rules file is missing or malformed, or the test location is outside every group. Review checks no `GRP-01` where [general.md](general.md) says it is not checked.
- The Group and Size cells hold what review's sizing gives for the file as written: the smallest-size readable group that selects it, else Group `none` and the wanted size.
- Write never writes a test case that needs more than medium. A large group size is only the Size cell value that review gives.

## Libraries and conventions

Follow the `libraries` and `layout.setup_files` settings of the language (property, snapshot, fakes, async, setup files). Skip a kind of test when its library is missing, or when its commit rule is `false` (`commit_snapshots` for snapshot, `commit_regressions` for property). Then take the next kind that fits, in the order of `## Kinds of tests`.

- A library fact is missing when its value is null or empty, whatever its status. A list `[]` means none.
- A commit rule that is null does not skip the kind. Only `false` does. So a TypeScript property test is allowed.
- Unit and integration need no library.

## Test location

A test location is the path of a separate test file, relative to the repo root. Every product file has exactly one of these states. The first state that applies decides:

1. The user names a path. The test location is that path, for the product file that it is paired with. It is never replaced; the group is only reported.
   - With one product file in scope, the named path belongs to that file.
   - With several product files, a named test path belongs to the product file whose stem its file name starts with, when exactly one product file matches. Else it belongs to none and is ignored.
2. The loaded entry derives no path for the product file. There is no test location (reason `no test location is known`), whatever the groups say. Language entries derive paths under their `layout` how-to.
3. The path that a loaded entry derives is selected by a recorded group that applies and is readable (read as if the file existed). The test location is the derived path.
4. The derived path is selected by no group, and the loaded entry finds a path that a recorded group selects. The test location is that path, and write adds its test cases to that existing file, edits no other file and changes no existing test case.
5. The derived path is selected by no group, and no group path exists. The test location is the derived path, with Group `none` (see "Group and size").

A derived path belongs to its own product file. When the file of a derived path already exists, write adds its test cases to it and changes no existing test case. An inline test module in the product file is never a location, because write edits no product file.

## Criterion for test wrong or product wrong

Before a fix, name the source of the expected value of the failing assertion: a spec or ticket line, documentation, a doc comment, a type or interface contract, or the words of the user. The source must exist before the run. An observed value of the code under test is never a source. Then:

- The product code is wrong when the test code itself is sound (it compiles or parses, and its imports, fixtures and setup work) and the call under test breaks what the source says. That is a failed assertion, or an error, panic or crash inside the product code. A build failure names no test case, so it is a "test wrong" case.
- The test is wrong in every other case: the failure is in the test code (a compile or parse error, a missing import or fixture, a wrong setup, a flaky or timing result with no failed assertion), the expected value has no source, or the source does not support the expected value.

A run that hits the 10-minute stop is not classified: its result is `not run`.

A fix try changes the test mechanics, or changes an expected value only to a value that its source supports. It never changes an expected value to the observed output without a supporting source. Report a found bug with its source.

## Report contract

The report is your final message. It has these parts, in this order.

1. The title `# testing write: <scope>`. The scope is the product files, joined with a comma and a space. It is `none` for an empty scope and for a failed intake.
2. The line `**Result: N files, N pass, N fail, N not run, N bugs.**` The counts are test files by run result, and found bugs. An empty scope and a failed intake have all zeros.
3. The note lines, each at most once, in this order. The empty-scope report has only the line `No product file in scope. Name the files to test.` The failed-intake report has only the line `Intake failed: <message>.` Neither has a file section or another note. Otherwise:
   - The fallback line, with the same text and conditions as note line (d) in [review.md](review.md). It is the only line that holds `/testing setup`.
   - The line `No group: <languages>. Tests are placed at the named or derived path.` The languages are each entry value (`rust`, `typescript` or `general`) that has a test with Group `none`.
   - One line `Not written: <path> (<reason>).` for each product file that gets no test, in the order of the files. A report whose every product file is not written has no file section and a Result line of zeros.
4. One section per test file, `## File: <path>`, in the order of the files. It holds the table with the header `| Test | Point | Kind | Size | Group | Reason |`, then the line `Command: ...`, then the line `Run result: ...`.
   - One table row for each new test case. `Kind` is `unit`, `integration`, `property` or `snapshot`. `Size` is `small`, `medium` or `large`. `Group` is a group name or `none`.
   - The `Point` cell names the public interface or the system boundary that the test goes through.
   - In the Reason cell, the one-line why comes first, then `; wanted <size>` or the no-group explanation when "Group and size" requires it.
   - The `Command` line is `Command: <command as run, with the worker flag>`. A known command that was not started is `Command: <command>`. A command that started and was then stopped is written as run. `Command: none` means no command is known. `CI=true` is not part of the line.
   - The `Run result` line is `Run result: pass`, `Run result: fail (<names>)` or `Run result: not run (<reason>)`. The files of a language share one command. The result is per file ("Run result rule"). A name of a failing existing test case has the suffix ` (existing)`. Names are separated by a comma and a space. When the command runs as it is (step 2 of "Timed run" in [review.md](review.md)), only in-scope test cases are kept, so no existing test case is listed.
   - A test is matched by its file path and its name, so two files may hold the same name.
5. The section `## Found bugs`, only when a test is a found bug. Its header is `| File | Test | Where | Expected | Source |`. `Where` is the `file:line` of the failing assertion, else the call under test in the test file when the product code failed with an error, panic or crash. `Expected` is the expected value as the assertion writes it. Then the section `## Kept failing`, only when a test is kept failing. Its header is `| File | Test | Reason |`. Both come after the file sections, in this order.
   - Every test in them is a row of a file table and is named in the `fail` run result of that file. The one exception is a Kept failing row whose Test is `(file)`: it has no row in a file table and is named by its File cell in the `fail` run result of that file.
   - A found bug counts in `fail`. A row is matched to its test file by its File cell.

The report has no other section.
