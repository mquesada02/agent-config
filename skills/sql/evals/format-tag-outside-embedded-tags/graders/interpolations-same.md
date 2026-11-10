---
type: llm
---
Grader A of seam 2 (the same check as the command `graders/interpolations_same.py`).

The file `inventory-store.ts` holds three postgres.js templates with the tag `db`. Only the second one (`listStock`, lines 9 to 15 before the run) is the target. It has two interpolations, in this order:

1. `${warehouseId}` (a value) in the `where` clause.
2. `${onlyLow ? db`and s.qty < 5` : db``}` (a conditional fragment), also in the `where` clause, after `${warehouseId}`.

Look at the file that the final message of Claude shows (the file after the first run). Pass when, after the first run, the template still holds exactly these two interpolations, each once, with the same text, in the same order, and each after the `where` clause word and before the `order by` clause word. Fail when one is changed, dropped, duplicated or moved into another clause.
