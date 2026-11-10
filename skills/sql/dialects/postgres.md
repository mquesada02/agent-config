# PostgreSQL dialect module

This module holds the `PG-*` rules of the static optimize report. They need no database: each rule reads the SQL text and, where its entry says so, the repo schema. A rule that needs a fact fires only when the repo shows the fact.

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
- **Detects:** `NOT IN (subquery)` where the column that the subquery selects is nullable (a `NULL` in it makes `NOT IN` return no rows). The column on the left of `NOT IN` is not checked. Without a database this fires only when the repo shows the fact: a migration or schema column that the schema shows as nullable (a column definition with no `NOT NULL` and no `PRIMARY KEY`; a primary key is not nullable). Otherwise the rule does not fire.
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

Stub. Ticket #395 (sql skill: plan findings) fills this section: the `PLAN-*` rules and the reading of a query plan. It needs a database, so it holds no behavior in this module yet.
