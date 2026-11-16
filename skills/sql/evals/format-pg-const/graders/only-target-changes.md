---
type: llm
---
Grader B of seam 2 (the same check as the command `graders/only_target_changes.py`).

The fixture `report-store.ts` has 11 lines. The target is line 5, the definition of the constant `LOW_STOCK`. Only its string value (with its quotes) may change: it becomes an untagged template.

Look at the file that the final message of Claude shows (the file after the first run). Pass when every part of the file outside that value is unchanged and in the same order: the `import` line, the `const pool` line, the text `const LOW_STOCK = ` before the value, and the two calls: `export const lowStock = () => pool.query(LOW_STOCK)` and the whole `lowStockCount` function (it still calls `pool.query(LOW_STOCK)`, with no inline SQL). Fail when any of them changed, even in white space or case, or when a call now holds SQL text.
