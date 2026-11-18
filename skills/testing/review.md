# Review steps

Review existing tests against the rules of [general.md](general.md) and write a report. The skill changes no file until the user approves. The reply of the user starts the fix flow (see "Fix on approval").

## Steps

1. Read the intake JSON that [SKILL.md](SKILL.md) made for the files in scope. Run no other shell command for the rules or the facts.
2. Take each setting from the `rules.settings` object. A section that is missing (see `rules.missing_sections`) or an optional key that is absent falls back to the `detected.facts` of the language. When `rules.error` is set, `rules.settings` is empty and every setting falls back.
3. Take the disabled ids from `rules.settings.rules.disabled`. This list is empty when the rules file is absent or `rules.error` is set, and a value that is not a list gives no id.
   - Skip each distinct disabled id that is in the catalogue and is not in `rules.disabled_without_reason`. Line (a) of the report lists them.
   - Check each id in `rules.disabled_without_reason` that has rule text, as any other id. Line (b) of the report lists them. An id without rule text is not checked and is named nowhere.
   - Ignore each id in `rules.unknown_ids`. Line (c) of the report lists them.
4. Check each file in scope against each id that has rule text in [general.md](general.md) (and in the loaded entries, for their check details). Read the test code and the runner config. Run no test in this step. For each failed rule, note every `file:line` place. A rule is one row, at the severity that the catalogue gives.
5. Write the report as your final message. Use the report contract below.
6. With at least one row, stop. Make no edit to any file before the user approves. When the user replies to the approval line, follow "Fix on approval". With zero rows the review ends with the report.

## Report contract

The report is your final message. It has these parts, in this order.

1. The title `# testing review: <scope>`. The scope is the paths of the files in scope, joined with a comma and a space, or `changed tests` when you took the changed files yourself.
2. The line `**Result: N critical, N required, N suggestions.**`. Each `N` is the number of rows of that severity.
3. The note lines. Write each one only when it applies, at most once, in this order:
   - (a) `Disabled (reason recorded, not checked): <ids>.` The ids are comma separated.
   - (b) `No reason line, checked anyway: <ids>.`
   - (c) `Unknown ids in rules.disabled, ignored: <ids>.`
   - (d) The fallback line. Write it only when the rules file is absent or `rules.missing_sections` is not empty. It is `Detected for this run: <names>. Run /testing setup to record them.` The names are the `rules.missing_sections` entries, comma separated, or `all settings (no rules file)` when the file is absent. When `rules.error` is set, it is `Rules file error: <message> (line <N>). Every setting is detected for this run. Run /testing setup.` Leave out ` (line <N>)` when `rules.error.line` is null.
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
5. **Run the affected tests.** Run the tests of the edited files with the single-run test command: the `commands.<language>.test` setting, else the detected fact. Add the worker-flag fact set to 2 workers, in the syntax of the runner. When no worker flag is known, run without one and say so. Use the command of each language of the edited files. Report `pass`, `fail` or `not run` with the reason. When no test command is known, the result is `not run`. Never report `pass` for tests that did not run.
