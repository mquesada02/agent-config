---
type: llm
---
Grader of the pass criterion of the pg write-back (the value stays the same SQL, and the kind is as the rewrite form says).

The constant `LOW_STOCK` of `report-store.ts` was the quoted string `'select sku, qty from stock where qty < 5 order by sku'`, used by two calls.

Look at the file that the final message of Claude shows (the file after the first run). Pass when all of this holds:

1. The SQL of the constant is the same as before. Only white space and keyword case may differ: the same words in the same order, with no word, name, comma, `<`, number or `as` added or removed.
2. The constant is rewritten once, at its definition, and is now an untagged template (backticks, no tag before them), because its new value has a line break.
3. The constant is defined once (not copied into a call).

Fail when the SQL changed in any other way, when the constant is still quoted, or when it is defined twice.
