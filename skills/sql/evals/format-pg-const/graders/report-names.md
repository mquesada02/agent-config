---
type: llm
---
Grader of the report of the pg write-back.

Look at the final message of Claude. Pass when all of this holds:

1. It names the constant that became a template: the file `report-store.ts` and the line range of its definition (line 5 before the rewrite, `Became a template: report-store.ts:5-5 (literal)` or a text with the same facts). It names the definition once, not once for each call.
2. It names no refused rewrite, because nothing was refused (or it says that nothing was refused).
3. It says that the second run changed nothing.

Fail when the constant that became a template is not named, when it is named for a call, or when a refusal is reported that did not happen.
