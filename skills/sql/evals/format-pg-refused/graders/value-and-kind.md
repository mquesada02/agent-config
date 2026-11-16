---
type: llm
---
Grader of the pass criterion of the pg write-back (the value stays the same SQL, and the kind is as the rewrite form says).

The first statement of `audit-store.ts` is a `+` chain with a comment between its pieces. The write-back script refuses a chain with a comment, so the chain keeps its kind and its value.

Look at the file that the final message of Claude shows (the file after the first run). Pass when the statement is still the `+` chain of two quoted strings with its comment, and the SQL text of the pieces is the same as before. The statement must not have become a template, and no piece may be lost. Fail when the statement was turned into a template, or when the comment or a piece was removed.
