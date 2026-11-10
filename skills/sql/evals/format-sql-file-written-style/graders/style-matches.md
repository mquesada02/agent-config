---
type: llm
---
Grader C of seam 2 (the same check as the command `graders/style_matches.py`).

The rules file sets the default style: `keyword_case` upper, `indent` 2 spaces, `clause_per_line` true, `comma` trailing, `alias_as` true.

Look at the file that the final message of Claude shows (the file after the first run). Pass when all of this holds for the second statement:

1. Every SQL keyword is in upper case (`SELECT`, `FROM`, `JOIN`, `ON`, `WHERE`, `ORDER BY`, `DESC`, `AS`).
2. Each clause word is alone on its line, and its body is on the lines below, 2 spaces deeper (`ORDER BY` stays on one line).
3. Each select item is on its own line with the comma at the end of the line, and each `JOIN` is on its own line at the body level of `FROM`.
4. Both table aliases are written with `AS` (`orders AS o`, `customers AS c`).
5. The statement starts at column 0 and ends with `;`.
6. The final message says that the second run changed nothing.
