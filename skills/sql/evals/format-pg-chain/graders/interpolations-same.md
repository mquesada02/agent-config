---
type: llm
---
Grader A of seam 2 (the same check as the command `graders/interpolations_same.py`).

The file `order-store.ts` holds two `pg` statements and no `${...}` interpolation. The first one (the chain) has the placeholder `$1` in its `where` clause and the parameter array `[customerId]`.

Look at the file that the final message of Claude shows (the file after the first run). Pass when the first statement, now one template, holds no `${...}` interpolation, still holds `$1` once, in the `where` clause, and still has the parameter array `[customerId]` after it. Fail when a `${` appears, when `$1` is changed, dropped or moved, or when the parameter array changed.
