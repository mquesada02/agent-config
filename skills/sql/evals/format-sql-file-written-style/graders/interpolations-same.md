---
type: llm
---
Grader A of seam 2 (the same check as the command `graders/interpolations_same.py`).

The file `reports.sql` holds three statements and none has an interpolation. The original second statement (line 3) is `select o.id, o.total, c.name from orders o join customers c on c.id = o.customer_id where o.total > 100 order by o.total desc;`. Compare it with the file that the final message shows. Pass when the file shows three statements and the second one still holds the same query: `o.id`, `o.total`, `c.name`, `orders`, `customers`, the join condition `c.id = o.customer_id`, the filter `o.total > 100` and the order `o.total desc`, only with a new layout and case. Fail when a column, a table or a condition is changed, dropped or added.
