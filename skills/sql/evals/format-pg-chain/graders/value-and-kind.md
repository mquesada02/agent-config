---
type: llm
---
Grader of the pass criterion of the pg write-back (the value stays the same SQL, and the kind is as the rewrite form says).

The first statement of `order-store.ts` was a `+` chain of three quoted strings: `select id, total, placed_at from orders `, `where customer_id = $1 ` and `order by placed_at desc`.

Look at the file that the final message of Claude shows (the file after the first run). Pass when both hold:

1. The SQL of the statement is the same as before. Only white space and keyword case may differ: the same words in the same order, with no word, name, comma or `as` added or removed.
2. The chain is now one untagged template (backticks, no tag before them), in the same place. No `+` and no quoted piece remains in it.

Fail when the SQL changed in any other way, or when a `+` or a quoted piece remains.
