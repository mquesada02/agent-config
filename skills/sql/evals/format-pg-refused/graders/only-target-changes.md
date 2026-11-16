---
type: llm
---
Grader B of seam 2 (the same check as the command `graders/only_target_changes.py`).

The fixture `audit-store.ts` has 12 lines. The target is lines 7 to 9, a `+` chain of two quoted strings with a comment (`// active users only`) between them. The rewrite is refused, so the target stays as it is too.

Look at the file that the final message of Claude shows (the file after the first run). Pass when every line outside lines 7 to 9 is unchanged and in the same order: the `import` line, the `const pool` line, the lines `export const listUsers = () =>`, `  pool.query(` and `  )`, and the whole `countUsers` statement (line 12 before the run). Fail when any of them changed, even in white space or case.
