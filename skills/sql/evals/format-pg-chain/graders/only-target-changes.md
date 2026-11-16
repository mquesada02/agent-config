---
type: llm
---
Grader B of seam 2 (the same check as the command `graders/only_target_changes.py`).

The fixture `order-store.ts` has 13 lines. The target is lines 7 to 9, the `+` chain of three quoted strings inside `listOrders`. Only the chain (from its first string to its last) may change: it becomes one untagged template.

Look at the file that the final message of Claude shows (the file after the first run). Pass when every part of the file outside the chain is unchanged and in the same order: the `import` line, the `const pool` line, the lines `export const listOrders = (customerId: number) =>`, `  pool.query(` and `    [customerId],` and `  )`, and the whole `countOrders` statement (line 13 before the run), including its quote characters. Fail when any of them changed, even in white space or case.
