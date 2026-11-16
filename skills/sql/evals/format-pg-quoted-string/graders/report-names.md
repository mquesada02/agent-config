---
type: llm
---
Grader of the report of the pg write-back.

Look at the final message of Claude. Pass when all of this holds:

1. It names the string that became a template: the file `stock-store.ts` and the line range of that string (line 6 before the rewrite, `Became a template: stock-store.ts:6-6 (literal)` or a text with the same facts).
2. It names no refused rewrite, because nothing was refused (or it says that nothing was refused).
3. It says that the second run changed nothing.

Fail when the string that became a template is not named, or when a refusal is reported that did not happen.
