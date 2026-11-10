# Format module

This module formats SQL with the written style. It covers the case where no safe formatter tool runs. Ticket #392 (sql skill: format with a safe tool) adds the safe tool path.

## Target

Format only what the developer points at.

- A query is one statement, named by its text or by its line range.
- A file is every statement of the file.
- A diff is every statement that holds a changed line of `git diff -U0 HEAD -- <file>`. A pure deletion hunk touches no statement. An untracked file has no diff. For both, ask for a file or query target.
- When no target is named, ask which one.

Find each statement with the extractor of the source module (`scripts/extract.py`). Never change a line outside the target statements.

## Style

Choose the style as `style.md` says. Use the written style for every target: this module runs no safe tool.

## Write

1. Apply the written style to each target statement.
2. Keep every `${...}` text exactly as it is.
3. For a `.sql` statement, keep the indentation of its first line. Its clause lines sit at that indentation, and the bodies sit one unit deeper. (The measurer takes base 0 for the `sql` form, so a statement that does not start at column 0 can give an indent vote that is too large. This is accepted.)
4. A statement with an interpolation of `keyword` position uses the written style with the opaque word rule of the template layout.

## Report

1. For each of the five style keys, give its value and its source: `rules file`, `repo majority` or `default`. A key that the measurer gave with `source` `default` has the source `default`.
2. Name each target statement as `<file>:<start>-<end>`.
3. Say that no safe tool ran.
4. With no rules file, the router's rules file step already suggests `/sql setup` once. The final message holds that suggestion.

## Safe tool path

Ticket #392 adds the formatter detector and the tool runner. Until then, format always uses the written style.
