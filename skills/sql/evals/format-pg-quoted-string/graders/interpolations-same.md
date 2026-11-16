---
type: llm
---
Grader A of seam 2 (the same check as the command `graders/interpolations_same.py`).

The file `stock-store.ts` holds two `pg` statements, both quoted strings with no `${...}` interpolation. The second one has the placeholder `$1` and the parameter array `[warehouseId]`.

Look at the file that the final message of Claude shows (the file after the first run). Pass when the first statement, now a template, holds no `${...}` interpolation (an interpolation would send a different string), and the second statement still holds `$1` and `[warehouseId]`. Fail when a `${` appears in the first statement or when the second statement changed.
