---
type: llm
---
Grader A of seam 2 (the same check as the command `graders/interpolations_same.py`).

The file `reports.sql` holds three statements and none has an interpolation. Pass when the statement count is still three and the second statement still holds the same query: `o.id`, `o.total`, `c.name`, `orders`, `customers`, the join condition `c.id = o.customer_id`, the filter `o.total > 100` and the order `o.total desc`, only with a new layout and case. Fail when a column, a table or a condition is changed, dropped or added.
