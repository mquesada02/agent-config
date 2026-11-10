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

These steps apply to the statements that go to the written style.

1. Apply the written style to each target statement.
2. Keep every `${...}` text exactly as it is.
3. For a `.sql` statement, keep the indentation of its first line. Its clause lines sit at that indentation, and the bodies sit one unit deeper. (The measurer takes base 0 for the `sql` form, so a statement that does not start at column 0 can give an indent vote that is too large. This is accepted.)
4. A statement with an interpolation of `keyword` position uses the written style with the opaque word rule of the template layout.

## Report

1. For each of the five style keys, give its value and its source: `rules file`, `repo majority` or `default`. A key that the measurer gave with `source` `default` has the source `default`.
2. Name each target statement as `<file>:<start>-<end>`, with the method that formatted it: the tool name, or `written style`.
3. Name the formatter, in these lines, from the output of `scripts/detect_formatter.py`:
   - `Formatter: <chosen> (<reason>)`. The `chosen` value is a tool name or `none`. When `override` is not null and its `used` is false, add its `reason`: why the rules file value was ignored.
   - `Other tools found: <the tools of found that are not chosen, or none>`.
   - When `uncovered_tags` is not empty: `The Prettier embeddedSqlTags option does not cover: <tags>`, and say that the templates with these tags got the written style.
   - When a tool run failed a check: `check <name>: <reason>` and say that the written style took over for the statements of that run.
   - When `notes` is not empty, list each note once.
4. With no rules file, the router's rules file step already suggests `/sql setup` once. The final message holds that suggestion.

## Safe tool path

The tool path uses two scripts. The detector picks the tool. The runner runs it, checks the result and writes a copy of the file in which only the target statements changed. Never run a formatter by hand, and never run `prettier-plugin-sql-cst` or `eslint-plugin-sql --fix`: only the runner runs a tool.

1. Find the target statements, as the Target section says. Take the tag list: the `tags` of the `[sources]` section of the rules file, or, when that key is missing, the `tags` of the extractor output.
2. Run the detector once for each source form of the target (`template` for a JS or TS file, `sql` for a `.sql` file):

   ```
   python3 <skill folder>/scripts/detect_formatter.py <repo root> --form <template|sql> [--tags <t1,t2,...>] [--tool <name>]
   ```

   Pass `--tool` with the `[formatter] tool` value of the rules file when the key is there. Pass `--tags` only when there is a tag list (an empty list is an error).
3. Send a target statement to the written style when any of these holds. Send every other target statement to the tool.
   - The detector `chosen` is `none`.
   - The statement has an interpolation of `keyword` position (story 45: no tool guesses at such SQL).
   - The source form is `template` and the `tag` of the statement is in `uncovered_tags` (the Prettier `embeddedSqlTags` option does not cover it).
4. Run the runner once for the tool statements of one file. Give one `--range <start_line>-<end_line>` for each statement and a new `--output` path in the system temp folder:

   ```
   python3 <skill folder>/scripts/run_formatter.py <repo root> <file> --tool <chosen> --range <start>-<end> [--range ...] --output <path> [--tags <t1,t2,...>]
   ```

   - `ok` is true: copy the output file over the target file with `cp`. When the shell cannot write the target file, print the output file with `cat` and write that text to the target file with the Write tool. Do not edit the text.
   - `ok` is false: the written style takes over for every statement of that run. The report names the `check` and the `reason`.
5. After the tool run, run the extractor again for the statements that go to the written style: they keep their order and their count, but their lines may have moved. Then apply the written style to them, as the Write section says.
