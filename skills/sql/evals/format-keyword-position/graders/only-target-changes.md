---
type: llm
---
Grader B of seam 2 (the same check as the command `graders/only_target_changes.py`).

The fixture `rows-store.ts` has 11 lines. The target is lines 9 to 11 (the `listRows` template). Look at the Edit or Write calls of Claude and at `first-run.ts`. Pass when every line outside lines 9 to 11 is unchanged: the `import` line, the `const sql` line and the whole `countRows` template (lines 5 to 7, including its lower case `select count(*) from rows`). Fail when any of them changed.
