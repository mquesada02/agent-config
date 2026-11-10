---
type: llm
---
Grader A of seam 2 (the same check as the command `graders/interpolations_same.py`).

The file `reports.sql` holds three statements and no `${...}` interpolation. Only the second one (line 3 before the run) is the target.

Look at the file that the final message of Claude shows (the file after the first run). Pass when the file still holds no `${...}` text anywhere, and the second statement still reads the same SQL: the same columns (`o.id`, `o.total`, `c.name`), the same tables and aliases (`orders o`, `customers c`), the same `JOIN ... ON c.id = o.customer_id` condition, the same `WHERE o.total > 100` and the same `ORDER BY o.total DESC`. Fail when a word of the SQL is changed, dropped or added (case and white space may change).
