---
type: llm
---
Grader C of seam 2 (the same check as the command `graders/style_matches.py`).

The rules file sets the default style: `keyword_case` upper, `indent` 2 spaces, `clause_per_line` true, `comma` trailing, `alias_as` true. No safe tool runs, so the written style applies, and `${sel}` is one opaque word.

Look at `first-run.ts`. Pass when all of this holds for the `listRows` template:

1. `${sel} *` stays together on the first line of the body (the text before the first clause word stays on the first line), and `${sel}` is not split.
2. `FROM` and `WHERE` are in upper case, each alone on its line, with its body on the lines below, 2 spaces deeper.
3. The body of the template is 2 spaces deeper than the line that holds the opening backtick, and the closing backtick is alone on its line at column 0.
4. The file at the end of the run is identical to `first-run.ts`.
