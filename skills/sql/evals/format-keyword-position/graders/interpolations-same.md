---
type: llm
---
Grader A of seam 2 (the same check as the command `graders/interpolations_same.py`).

The target template of `rows-store.ts` (`listRows`, lines 9 to 11) has two interpolations, in this order: `${sel}` before the first clause word (a keyword position), then `${id}` (a value) in the `where` clause. Look at the file that the final message of Claude shows (the file after the first run). The original line of the target is `  ${sel} * from rows where id = ${id}`. Compare it with the file that the final message shows. Pass when both are still there, once each, with the same text, in this order, `${sel}` before the `FROM` clause word and `${id}` after the `WHERE` clause word. Fail when `${sel}` is split, moved after a clause word or dropped, or `${id}` is moved.
