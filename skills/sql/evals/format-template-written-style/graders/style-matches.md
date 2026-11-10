---
type: llm
---
Grader C of seam 2 (the same check as the command `graders/style_matches.py`).

The rules file sets this style: `keyword_case` lower, `indent` 4 spaces, `clause_per_line` true, `comma` trailing, `alias_as` false.

Look at the file that the final message of Claude shows (the file after the first run). Pass when all of this holds for the `listStock` template:

1. Every SQL keyword is in lower case (`select`, `from`, `join`, `on`, `where`, `order by`).
2. Each clause word (`select`, `from`, `where`, `order by`) is alone on its line, and its body is on the lines below, 4 spaces deeper.
3. The body of the template is 4 spaces deeper than the line that holds the opening backtick, and the closing backtick is alone on its line, at the indent of that opening line (column 0).
4. Each item of the select list is on its own line, with the comma at the end of the line.
5. The table aliases have no `as` (`stock s`, `warehouses w`), and the `join` is on its own line.
6. The conditional fragment `${onlyLow ? ...}` is on its own line, at the level of the `where` body.
7. The final message says that the second run changed nothing.
