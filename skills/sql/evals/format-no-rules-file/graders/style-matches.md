---
type: llm
---
Grader C of seam 2 (the same check as the command `graders/style_matches.py`).

There is no rules file and no other SQL in the folder, so the default style applies: `keyword_case` upper, `indent` 2 spaces, `clause_per_line` true, `comma` trailing, `alias_as` true.

Look at the file that the final message of Claude shows (the file after the first run). Pass when all of this holds for the `listNotes` template:

1. Every SQL keyword is in upper case.
2. Each clause word (`SELECT`, `FROM`, `WHERE`, `ORDER BY`) is alone on its line, with its body on the lines below, 2 spaces deeper. Each select item is on its own line with the comma at the end of the line.
3. The opening line is now only `export const listNotes = (owner: number) => sql` followed by the opening backtick. The body is 2 spaces deeper than that line, and the closing backtick is alone on its line at column 0.
4. The final message says that the second run changed nothing.
