---
type: llm
---
Grader C of seam 2 (the same check as the command `graders/style_matches.py`).

The repo has a safe tool (Prettier with `prettier-plugin-embed` and `prettier-plugin-sql`, `keywordCase` upper), so the tool decides the layout. The style that its output has: `keyword_case` upper, `indent` 2 spaces, `clause_per_line` true, `comma` trailing, `alias_as` false.

Look at the file that the final message of Claude shows (the file after the first run). Pass when all of this holds for the `listStock` template:

1. Every SQL keyword is in upper case (`SELECT`, `FROM`, `JOIN`, `ON`, `WHERE`, `ORDER BY`, `AS`).
2. Each clause word (`SELECT`, `FROM`, `WHERE`, `ORDER BY`) is alone on its line, and its body is on the lines below, 2 spaces deeper.
3. The body of the template is 2 spaces deeper than the line that holds the opening backtick, and the closing backtick is at column 0 (it may be followed by a `;`).
4. Each item of the select list is on its own line, with the comma at the end of the line.
5. The table aliases have no `AS` (`stock s`, `warehouses w`), and the `JOIN` is on its own line.
6. The conditional fragment is on its own line, at the level of the `WHERE` body.
7. The final message names `prettier-plugin-embed` as the chosen tool, and says that the second run changed nothing.
