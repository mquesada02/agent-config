---
type: llm
---
Grader A of seam 2 (the same check as the command `graders/interpolations_same.py`).

The target template of `rows-store.ts` (`listRows`, lines 9 to 11) has two interpolations, in this order: `${sel}` before the first clause word (a keyword position), then `${id}` (a value) in the `where` clause. Look at the Edit or Write calls of Claude and at `first-run.ts`. Pass when both are still there, once each, with the same text, in this order, `${sel}` before the `FROM` clause word and `${id}` after the `WHERE` clause word. Fail when `${sel}` is split, moved after a clause word or dropped, or `${id}` is moved.
