# Format module

This module formats SQL with the repo's safe formatter tool when the tool is safe for the input, and with the written style otherwise.

## Target

Format only what the developer points at.

- A query is one statement, named by its text or by its line range.
- A file is every statement of the file.
- A diff is every statement that holds a changed line of `git diff -U0 HEAD -- <file>`. A pure deletion hunk touches no statement. An untracked file has no diff. For both, ask for a file or query target.
- When no target is named, ask which one.

Find each statement with the extractor of the source module (`scripts/extract.py`). Its output gives each statement a `start_line`, an `end_line`, a `tag` and its interpolations. Never change a line outside the target statements.

## Style

Choose the style as `style.md` says. Use the written style for every target statement that the Safe tool path section sends to it.

## Write

These steps apply to the statements that go to the written style and that are not `pg` statements (the `pg` statements go to the next section).

1. Apply the written style to each target statement.
2. Keep every `${...}` text exactly as it is.
3. For a `.sql` statement, keep the indentation of its first line. Its clause lines sit at that indentation, and the bodies sit one unit deeper. (The measurer takes base 0 for the `sql` form, so a statement that does not start at column 0 can give an indent vote that is too large. This is accepted.)
4. A statement with an interpolation of `keyword` position uses the written style with the opaque word rule of the template layout.

## pg statements

This section applies to each target statement whose extractor `source` is `pg`. The tool path and this section work on different statements and do not depend on each other. A file with postgres.js statements and `pg` statements gets both.

A `pg` statement always uses the written style (the tool path formats only tagged templates). Its rules:

- A `dynamic` statement is not formatted. The report says so.
- The `alias_as` key does not apply to a `pg` statement, because the script keeps the string value and changes only white space and keyword case: never add or remove `AS`.
- A new value for a template, or for a string that gets a line break, follows the template layout of `style.md`: the body is one indent unit deeper than the line that holds the opening backtick, and the closing backtick is alone on its line at that indent. With `clause_per_line` false, the body is one line between the opening line and the closing backtick line. So this value starts with a line feed and ends with a line feed. Write no indent after the last line feed: the Write tool removes trailing spaces, and the script adds the indent of the line that holds the opening backtick.
- A string (`literal` kind) stays quoted only when its new value has no line break. When `clause_per_line` is false, write it as a one-line value with no line feed. When `clause_per_line` is true, write it in the template layout: the string then becomes an untagged template.
- A `+` chain becomes one untagged template, in place.
- A `const` that holds the SQL is rewritten once, at its definition. No call of it changes.

Steps for each `pg` target statement:

1. Run the extractor with `--tags` and `--receivers` of the rules file. Leave out each option whose list is empty. Take the statement index in the `statements` list.
2. Write the new value, exactly as it goes between the quotes, with the Write tool to a new file in the system temp folder. When the Write tool cannot write there (as in the eval sandbox, where it can write only in the run folder), write it to a new file in the working folder that the user or the case prompt names. The `format-pg-*` prompts name `new-value.sql` in the current folder.
3. Run the script. Give a new `--output` path in the system temp folder:

   ```
   python3 <skill folder>/scripts/write_back_pg.py <file> --index <n> --sql-file <path> --output <path> [--tags <t1,t2,...>] [--receivers <r1,r2,...>]
   ```

4. The script prints one JSON object with `ok`, `check`, `reason`, `from_kind`, `to_kind`, `became_template`, `start_line`, `end_line` and `const_name`.
   - `ok` is true: copy the output file over the file with `cp`. When the shell cannot write the file, print the output file with `cat` and write that text to the file with the Write tool. Do not edit the text.
   - `ok` is false: the statement stays as it is. The report names the `check` and the `reason`.
   - The run ends with exit code 2 and a stderr line that starts with `cannot write output file:` (the shell cannot write any file, as in a read-only eval shell): run the script again with `--stdout` in place of `--output`. It writes no file, and the JSON holds the new file text in `text`. On `ok` true, write that `text` over the file with the Write tool. Do not edit the text. Any other exit code 2 is a usage error: fix the command, and do not use `--stdout` for it.
5. After a rewrite, run the extractor again before the next statement: the lines moved, the indexes stay.

## Report

1. For each of the five style keys, give its value and its source: `rules file`, `repo majority` or `default`. A key that the measurer gave with `source` `default` has the source `default`.
2. Name each target statement as `<file>:<start>-<end>`, with the method that formatted it: the tool name, or `written style`.
3. Name the formatter, in these lines, from the output of `scripts/detect_formatter.py`:
   - `Formatter: <chosen> (<reason>)`. The `chosen` value is a tool name or `none`. When `override` is not null and its `used` is false, add its `reason`: why the rules file value was ignored.
   - `Other tools found: <the tools of found that are not chosen, or none>`.
   - When `uncovered_tags` is not empty: `The Prettier embeddedSqlTags option does not cover: <tags>`, and say that the templates with these tags got the written style.
   - When a tool run failed a check: `check <name>: <reason>` and say that the written style took over for the statements of that run.
   - When `notes` is not empty, list each note once.
4. For each `pg` string that became a template, give `Became a template: <file>:<start>-<end> (<from_kind>)`, so that the developer can check the ESLint `quotes` rule. For each refused rewrite, give `Refused: <file>:<start>-<end>: <check>: <reason>` (`<check>` and `<reason>` come from the JSON of the script). For each `dynamic` statement that was left, give `Refused: <file>:<start>-<end>: dynamic: dynamic statement, not formatted`. In every line, `<start>-<end>` are the `start_line` and `end_line` of the statement in the extractor output that was run before the rewrite. A refusal `extract` or `index` names `<file>` only. The method of a `pg` statement is `written style`.
5. With no rules file, the router's rules file step already suggests `/sql setup` once. The final message holds that suggestion.

## Safe tool path

The tool path uses two scripts. The detector picks the tool. The runner runs it, checks the result and writes a copy of the file in which only the target statements changed. Never run a formatter by hand, and never run `prettier-plugin-sql-cst` or `eslint-plugin-sql --fix`: only the runner runs a tool.

1. Find the target statements, as the Target section says. Take the tag list: the `tags` of the `[sources]` section of the rules file, or, when that key is missing, the `tags` of the extractor output. Take the receiver list: the `receivers` of the `[sources]` section of the rules file (when that key is missing or the list is empty, the extractor uses the receivers that the file shows).
2. Run the detector once for each source form of the target (`template` for a JS or TS file, `sql` for a `.sql` file):

   ```
   python3 <skill folder>/scripts/detect_formatter.py <repo root> --form <template|sql> [--tags <t1,t2,...>] [--tool <name>]
   ```

   Pass `--tool` with the `[formatter] tool` value of the rules file when the key is there. Pass `--tags` only when there is a tag list (an empty list is an error).
3. Send a target statement to the written style when any of these holds. Send every other target statement to the tool.
   - The detector `chosen` is `none`.
   - The statement has an interpolation of `keyword` position (story 45: no tool guesses at such SQL).
   - The source form is `template` and the `tag` of the statement is in `uncovered_tags` (the Prettier `embeddedSqlTags` option does not cover it).
   - The statement is a `pg` statement: the `source` of the statement is `pg`.
4. Run the runner once for the tool statements of one file. Give one `--range <start_line>-<end_line>` for each statement and a new `--output` path in the system temp folder:

   ```
   python3 <skill folder>/scripts/run_formatter.py <repo root> <file> --tool <chosen> --range <start>-<end> [--range ...] --output <path> [--tags <t1,t2,...>] [--receivers <r1,r2,...>]
   ```

   Pass `--receivers` only when there is a receiver list (an empty list is an error). The detector gets `--tags` alone.

   - `ok` is true: copy the output file over the target file with `cp`. When the shell cannot write the target file, print the output file with `cat` and write that text to the target file with the Write tool. Do not edit the text.
   - `ok` is false: the written style takes over for every statement of that run. The report names the `check` and the `reason`.
5. After the tool run, run the extractor again for the statements that go to the written style and that are not `pg` statements: they keep their order and their count, but their lines may have moved. Then apply the written style to them, as the Write section says. Apply it to the `pg` statements as the `pg statements` section says.
