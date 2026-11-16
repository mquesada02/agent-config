---
type: llm
---
Grader A of seam 2 (the same check as the command `graders/interpolations_same.py`).

The file `report-store.ts` holds one `pg` statement, the constant `LOW_STOCK`, which two calls use. It has no `${...}` interpolation and no placeholder.

Look at the file that the final message of Claude shows (the file after the first run). Pass when the constant, now a template, holds no `${...}` interpolation, and both calls still pass `LOW_STOCK` to `pool.query` (each once). Fail when a `${` appears, when a call lost its use of `LOW_STOCK`, or when a call was given its own SQL.
