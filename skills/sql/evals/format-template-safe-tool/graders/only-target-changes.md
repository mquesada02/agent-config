---
type: llm
---
Grader B of seam 2 (the same check as the command `graders/only_target_changes.py`).

The fixture `inventory-store.ts` has 19 lines. The target is lines 9 to 15 (the `listStock` template, from the line that holds the opening backtick to the closing backtick line).

Look at the file that the final message of Claude shows (the file after the first run). Pass when every line outside the target is unchanged and in the same order: the `import` line, the `const sql` line, the whole `listWarehouses` template (lines 5 to 7, still lower case `select id, name from warehouses order by name`) and the whole `countSkus` template (the last three lines, still lower case `select count(*) from stock`). Fail when any of them changed, even in white space or case. The target itself may grow or shrink.
