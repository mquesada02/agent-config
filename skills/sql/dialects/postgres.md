# PostgreSQL dialect module

This module holds the `PG-*` rules of the static optimize report, and the `PLAN-*` rules of the plan reading (the section Plan reading below). The `PG-*` rules work with no database: each rule reads the SQL text and, where its entry says so, the repo schema. The `PLAN-*` rules are the exception: they need a plan with actual values, so they fire only with an allowlisted database. A rule that needs a fact fires only when the repo shows the fact, or, with an allowlisted database, when the catalog shows it (the optimize module says how).

A rewrite is a fix of a `PG-*` finding that replaces the SQL text of a statement (it can change the result). A fix that only gives advice, with no replacement SQL, is not a rewrite.

## Rules

### PG-01

- **Title:** Join fan-out under an aggregate
- **Severity:** critical
- **Detects:** A join that fans out rows under an aggregate (`COUNT`, `SUM`, `AVG`) with no `DISTINCT` and no collapse. A collapse is a pre-aggregated subquery, a `GROUP BY` on the key of the aggregated table, or `COUNT(DISTINCT ...)`. A fan-out needs a one-to-many join: the join condition joins the key of the aggregated table to a column of the joined table that the schema does not show as unique (or the SQL text shows it plainly).
- **Why it matters:** Each row of the aggregated table repeats once for each matching row of the joined table, so the sum or the count is too large. The result is wrong, and no error shows it.
- **Fix:** Aggregate the many side in a subquery first and join the result, or group by the key of the aggregated table, or use `COUNT(DISTINCT ...)` for a count.
- **Example:** The bad form, then the good form.

  Bad:

  ```sql
  SELECT SUM(o.total) FROM orders o JOIN order_items i ON i.order_id = o.id
  ```

  Good:

  ```sql
  SELECT SUM(o.total) FROM orders o JOIN (SELECT order_id FROM order_items GROUP BY order_id) i ON i.order_id = o.id
  ```

### PG-02

- **Title:** `NOT IN` over a nullable column
- **Severity:** critical
- **Detects:** `NOT IN (subquery)` where the column that the subquery selects is nullable (a `NULL` in it makes `NOT IN` return no rows). The column on the left of `NOT IN` is not checked. With an allowlisted database, the fact comes from the catalog: the `facts` action says that the column is nullable. Without a database this fires only when the repo shows the fact: a migration or schema column that the schema shows as nullable (a column definition with no `NOT NULL` and no `PRIMARY KEY`; a primary key is not nullable). The same repo fact is used when the catalog gives no answer. Otherwise the rule does not fire.
- **Why it matters:** When one selected value is `NULL`, the comparison is never true, so the query returns no rows at all.
- **Fix:** Use `NOT EXISTS`, or filter the subquery with `WHERE <column> IS NOT NULL`.
- **Example:** The bad form, then the good form.

  Bad:

  ```sql
  SELECT id FROM users WHERE id NOT IN (SELECT manager_id FROM teams)
  ```

  Good:

  ```sql
  SELECT id FROM users u WHERE NOT EXISTS (SELECT 1 FROM teams t WHERE t.manager_id = u.id)
  ```

### PG-03

- **Title:** Type mismatch that casts the column
- **Severity:** required
- **Detects:** A comparison of an `integer` column with a numeric or float value, where no cross-type operator exists, so the column is cast. It fires only when the repo schema, or an explicit cast in the SQL, shows the column type.
- **Why it matters:** The cast on the column stops a plain index on that column from being used, so the query reads the whole table.
- **Fix:** Cast the value, or write the value with the type of the column (`WHERE qty = 5::int`).
- **Example:** The bad form, then the good form.

  Bad:

  ```sql
  SELECT id FROM stock WHERE qty::numeric = 5.0
  ```

  Good:

  ```sql
  SELECT id FROM stock WHERE qty = 5
  ```

### PG-04

- **Title:** `DISTINCT` hides a fan-out
- **Severity:** required
- **Detects:** A `DISTINCT` on a query with a join that fans out rows (the same one-to-many join evidence as PG-01).
- **Why it matters:** `DISTINCT` removes the repeated rows after the join did the work, so the query is slow, and the repeat hides a join that is too wide.
- **Fix:** Remove the fan-out: filter the many side with `EXISTS`, or aggregate it in a subquery. Then drop the `DISTINCT`.
- **Example:** The bad form, then the good form.

  Bad:

  ```sql
  SELECT DISTINCT u.id FROM users u JOIN orders o ON o.user_id = u.id
  ```

  Good:

  ```sql
  SELECT u.id FROM users u WHERE EXISTS (SELECT 1 FROM orders o WHERE o.user_id = u.id)
  ```

### PG-05

- **Title:** Function on a column
- **Severity:** suggestion
- **Detects:** A function call on a column in `WHERE` or `JOIN` (`lower(email) = ...`, `date(created_at) = ...`).
- **Why it matters:** A plain index on the column cannot serve the condition, so the query can read the whole table.
- **Fix:** Compare the bare column with a computed value (a range for a date), or add an expression index.
- **Example:** The bad form, then the good form.

  Bad:

  ```sql
  SELECT id FROM users WHERE lower(email) = 'a@example.com'
  ```

  Good:

  ```sql
  SELECT id FROM users WHERE email = 'a@example.com'
  ```

### PG-06

- **Title:** Leading wildcard in `LIKE`
- **Severity:** suggestion
- **Detects:** `LIKE '%...'` (and `ILIKE`) with a pattern that starts with a wildcard.
- **Why it matters:** A btree index cannot search a pattern with a leading wildcard, so the query reads the whole table.
- **Fix:** Anchor the pattern at the start (`LIKE 'abc%'`), or use a trigram index for a search inside the text.
- **Example:** The bad form, then the good form.

  Bad:

  ```sql
  SELECT id FROM users WHERE name LIKE '%son'
  ```

  Good:

  ```sql
  SELECT id FROM users WHERE name LIKE 'son%'
  ```

### PG-07

- **Title:** `OR` across different columns
- **Severity:** suggestion
- **Detects:** An `OR` in `WHERE` whose sides test different columns.
- **Why it matters:** One index rarely serves both sides, so the plan can fall back to a full read.
- **Fix:** Split the query into two queries joined by `UNION`, so each side uses its own index.
- **Example:** The bad form, then the good form.

  Bad:

  ```sql
  SELECT id FROM users WHERE email = $1 OR phone = $1
  ```

  Good:

  ```sql
  SELECT id FROM users WHERE email = $1 UNION SELECT id FROM users WHERE phone = $1
  ```

### PG-08

- **Title:** `SELECT *` in application code
- **Severity:** suggestion
- **Detects:** `SELECT *` in a postgres.js template (application code only, not a `.sql` file). It excludes `count(*)` and `EXISTS (SELECT * ...)`.
- **Why it matters:** The query returns every column, now and after a later migration. It reads more than the code needs, and a new column can change the result of the code.
- **Fix:** List the columns that the code uses.
- **Example:** The bad form, then the good form.

  Bad:

  ```sql
  SELECT * FROM users WHERE id = 1
  ```

  Good:

  ```sql
  SELECT id, name FROM users WHERE id = 1
  ```

### PG-09

- **Title:** Correlated subquery in the select list
- **Severity:** suggestion
- **Detects:** A subquery in the select list that refers to a column of the outer query, so it runs once for each outer row.
- **Why it matters:** The subquery runs again for every row of the outer query, so the cost grows with the row count.
- **Fix:** Replace it with a join to a grouped subquery, or with a lateral join. For a count, wrap the joined value in `coalesce(..., 0)`, because a row with no match gets `NULL` from the join, and the subquery gave 0. This fix gives replacement SQL, so it is a rewrite.
- **Example:** The bad form, then the good form.

  Bad:

  ```sql
  SELECT u.id, (SELECT count(*) FROM orders o WHERE o.user_id = u.id) FROM users u
  ```

  Good:

  ```sql
  SELECT u.id, coalesce(c.n, 0) AS n FROM users u LEFT JOIN (SELECT user_id, count(*) AS n FROM orders GROUP BY user_id) c ON c.user_id = u.id
  ```

### PG-10

- **Title:** Large literal `OFFSET`
- **Severity:** suggestion
- **Detects:** A literal `OFFSET` above 1000. An `OFFSET` that is a parameter is not flagged.
- **Why it matters:** The database reads and drops every skipped row, so a deep page gets slower with each page.
- **Fix:** Use keyset pagination: filter on the last seen key (`WHERE id > $1 ORDER BY id LIMIT 50`).
- **Example:** The bad form, then the good form.

  Bad:

  ```sql
  SELECT id FROM events ORDER BY id LIMIT 50 OFFSET 5000
  ```

  Good:

  ```sql
  SELECT id FROM events WHERE id > $1 ORDER BY id LIMIT 50
  ```

## Plan reading

The `PLAN-*` findings come from `scripts/plan_findings.py`, never from reading the plan JSON yourself. The plan comes only from the Database path of the optimize module (`pg_run`), and every `PLAN-*` rule needs a plan with actual values (`EXPLAIN (ANALYZE, BUFFERS)`). A plan with no actual values gives no `PLAN-*` finding. With no database, no `PLAN-*` rule fires. The script reads fractional row counts (PostgreSQL 18) and applies the fixed thresholds below to each plan node, unless the rule says that it reads the whole plan. A node that never ran (`Actual Loops` 0) is skipped.

The script gives the measured values and the thresholds of each finding. The severity is the one of the entry. A fix of a `PLAN-*` finding is advice in words: it holds no replacement SQL, so it is never a rewrite.

### PLAN-01

- **Title:** Row estimate far from the actual rows
- **Severity:** required
- **Detects:** A node with 1000 or more actual rows, where the estimate is off by 10 times or more, in either direction (an over- or an underestimate). Actual rows are `Actual Rows` × `Actual Loops`. Estimated rows are `Plan Rows` × `Actual Loops`.
- **Why it matters:** The planner chooses join order, join method and scan type from its row estimates. A wrong estimate can lead to a slow plan.
- **Fix:** Refresh the statistics with `ANALYZE` on the tables. If the estimate stays wrong, add extended statistics on correlated columns, or rewrite the condition so that the planner can estimate it (no function on the column, no expression that hides the column).
- **Example:** The bad form, then the good form.

  Bad:

  ```
  Seq Scan on orders (rows=100) (actual rows=5000 loops=1)
  ```

  Good:

  ```
  Seq Scan on orders (rows=5000) (actual rows=5000 loops=1)
  ```

### PLAN-02

- **Title:** Seq scan that discards most rows
- **Severity:** required
- **Detects:** A `Seq Scan` node that scans 10,000 or more rows, where the filter removes 90% or more of them. Scanned rows are (`Actual Rows` + `Rows Removed by Filter`) × `Actual Loops`. The removed ratio is `Rows Removed by Filter` / (`Actual Rows` + `Rows Removed by Filter`).
- **Why it matters:** The query reads the whole table to keep a small part of it. The cost grows with the table, not with the result.
- **Fix:** Add an index on the filtered column (a partial index when the filter uses a fixed condition), or make the condition usable by an existing index (no function on the column).
- **Example:** The bad form, then the good form.

  Bad:

  ```
  Seq Scan on events (actual rows=300) Rows Removed by Filter: 29700
  ```

  Good:

  ```
  Index Scan using events_kind_idx on events (actual rows=300)
  ```

### PLAN-03

- **Title:** Spill to disk
- **Severity:** required
- **Detects:** A node that writes to disk by any of these signals: a `Sort Method` that starts with `external`; `Hash Batches` above 1; `Temp Written Blocks` above 0 that the node adds itself, that is, above the sum of `Temp Written Blocks` of its direct children (the buffer counts of a node include its children).
- **Why it matters:** The work does not fit in memory (`work_mem`), so the node writes temporary files and reads them back. This is much slower than an in-memory sort or hash.
- **Fix:** Reduce the rows that reach the node (filter earlier, select fewer columns), or raise `work_mem` for this query or role after you check the memory that the server has. Do not raise it for the whole server.
- **Example:** The bad form, then the good form.

  Bad:

  ```
  Sort Method: external merge  Disk: 4000kB
  ```

  Good:

  ```
  Sort Method: quicksort  Memory: 900kB
  ```

### PLAN-04

- **Title:** Nested loop with many inner loops
- **Severity:** suggestion
- **Detects:** A `Nested Loop` node whose inner child has 1000 or more actual loops (the child with `Parent Relationship` `Inner`, or the second child when no child has it).
- **Why it matters:** The inner side runs once for each outer row. With many outer rows this repeats a lookup thousands of times, and a hash or merge join can be faster.
- **Fix:** Check that the inner side uses an index on the join column. If the outer side is large, give the planner a reason to choose a hash join (fresh statistics, a join condition on indexed columns), or reduce the outer rows first.
- **Example:** The bad form, then the good form.

  Bad:

  ```
  Nested Loop
    -> Seq Scan on ids (actual rows=2000)
    -> Index Scan on orders (actual rows=1 loops=2000)
  ```

  Good:

  ```
  Hash Join
    -> Seq Scan on orders (actual rows=2000)
    -> Hash -> Seq Scan on ids (actual rows=2000)
  ```

### PLAN-05

- **Title:** Low cache hit ratio
- **Severity:** suggestion
- **Detects:** The whole plan, from the buffer totals of the top node: `Shared Hit Blocks` / (`Shared Hit Blocks` + `Shared Read Blocks`) is below 90%, with 1000 or more `Shared Read Blocks`. With no buffer counts at the top node, the rule does not fire.
- **Why it matters:** The query reads many blocks from disk (or from the operating system cache) instead of from the shared buffers. A cold cache makes a query look slower than it is in steady state.
- **Fix:** Run the query again to see the warm result before you act. Then read fewer blocks: add an index so that the query touches less of the table, select fewer columns, or filter earlier. Raise `shared_buffers` only after you check the memory of the server.
- **Example:** The bad form, then the good form.

  Bad:

  ```
  Buffers: shared hit=100 read=1500
  ```

  Good:

  ```
  Buffers: shared hit=1600
  ```
