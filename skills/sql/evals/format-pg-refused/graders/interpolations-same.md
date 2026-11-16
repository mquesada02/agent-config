---
type: llm
---
Grader A of seam 2 (the same check as the command `graders/interpolations_same.py`).

The file `audit-store.ts` holds two `pg` statements and no `${...}` interpolation. Nothing in the file should change, so no interpolation may appear.

Look at the file that the final message of Claude shows (the file after the first run). Pass when no `${` appears in the file and both statements still have their quoted strings. Fail when a `${` appears or a statement lost a quoted piece.
