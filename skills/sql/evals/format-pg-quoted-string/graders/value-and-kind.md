---
type: llm
---
Grader of the pass criterion of the pg write-back (the value stays the same SQL, and the kind is as the rewrite form says).

The first statement of `stock-store.ts` was the quoted string `'select id, name from warehouses order by name'`.

Look at the file that the final message of Claude shows (the file after the first run). Pass when both hold:

1. The SQL of the first statement is the same as before. Only white space and keyword case may differ: the same words in the same order (`select id, name from warehouses order by name`), with no word, name, comma, table alias or `as` added or removed.
2. The first statement is now an untagged template (backticks, no tag before them), because its new value has a line break. It is not a quoted string any more.

Fail when the SQL changed in any other way, or when the statement is still quoted.
