---
type: llm
---
Grader of the report of the pg write-back.

Look at the final message of Claude. Pass when all of this holds:

1. It names the refused rewrite: the file `audit-store.ts`, the line range of the chain (lines 7 to 9, `Refused: audit-store.ts:7-9: chain_comment: <reason>` or a text with the same facts) and the reason (a comment between the pieces of the chain).
2. It names no string that became a template, because none did (or it says that none did).
3. It says that the second run changed nothing (it refuses again).

Fail when the refusal or its reason is not named, or when a string is reported as a template that did not become one.
