---
type: llm
---
Grader A of seam 2 (the same check as the command `graders/interpolations_same.py`).

The file `inventory-store.ts` holds three postgres.js templates. Only the second one (`listStock`, lines 9 to 15 before the run) is the target. It has two interpolations, in this order:

1. `${warehouseId}` (a value) in the `where` clause.
2. `${onlyLow ? sql`and s.qty < 5` : sql``}` (a conditional fragment), also in the `where` clause, after `${warehouseId}`.

Look at the Edit or Write calls of Claude and at `first-run.ts`. Pass when, after the first run, the template still holds exactly these two interpolations, each once, with the same text, in the same order, and each after the `where` clause word and before the `order by` clause word. Fail when one is changed, dropped, duplicated or moved into another clause.
