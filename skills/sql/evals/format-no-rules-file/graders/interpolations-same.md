---
type: llm
---
Grader A of seam 2 (the same check as the command `graders/interpolations_same.py`).

The target template of `notes-store.ts` (`listNotes`, line 5) has one interpolation, `${owner}` (a value), in the `where` clause. Look at the Edit or Write calls of Claude and at `first-run.ts`. Pass when the template still holds `${owner}` once, with the same text, after the `where` clause word and before the `order by` clause word. Fail when it is changed, dropped or moved.
