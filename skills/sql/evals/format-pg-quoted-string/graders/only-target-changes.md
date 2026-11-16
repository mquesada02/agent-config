---
type: llm
---
Grader B of seam 2 (the same check as the command `graders/only_target_changes.py`).

The fixture `stock-store.ts` has 9 lines. The target is line 6, the quoted string of `listWarehouses`: `'select id, name from warehouses order by name'`. Only the string (with its quotes) may change: it becomes an untagged template that spans several lines.

Look at the file that the final message of Claude shows (the file after the first run). Pass when every part of the file outside that string is unchanged and in the same order: the `import` line, the `const pool` line, the line `export const listWarehouses = () =>`, the text `  pool.query(` before the string and the text `)` after it, and the whole `listStock` statement (lines 8 and 9 before the run), including its quote characters (it is still a single-quoted string on one line, with `[warehouseId]`). Fail when any of them changed, even in white space or case.
