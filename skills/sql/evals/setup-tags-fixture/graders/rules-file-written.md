---
type: llm
---
Grader D of seam 2, the `toml` check (the same check as the command `graders/grade_setup.py` with `expected.json`).

Look at the rules file that the final message shows (the file as it was written). Pass when all of these hold:

1. It has one `toml` block with these values: `[style]` `keyword_case` `"lower"`, `indent` `"2 spaces"`, `clause_per_line` `true`, `comma` `"trailing"`, `alias_as` `false`; `[formatter]` `tool` `"none"`; `[sources]` `tags` the three names `sql`, `this.sql` and `tx` (in any order); `[rules]` `disabled` an empty list.
2. Its prose holds the rule `Pass a list to IN with a tag call such as sql(ids); never put the call in extra parentheses or pass a bare variable.` and the rule `Name every column that a report query selects.`
3. Its prose holds neither the `LIKE` candidate rule (`Do not start a LIKE pattern with a percent sign when the column has an index.`) nor the `SELECT *` candidate rule (`Do not use SELECT * in a template; name the columns.`).

Fail when any item is not true.
