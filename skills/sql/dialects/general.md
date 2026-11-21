# General dialect module

This module holds the `GEN-*` rules: engine-neutral SQL rules for an engine that the skill does not cover. It is the single source of truth for the GEN rules. A GEN rule is a judgement check: no script checks it against SQL. The fallback gives advice only: it connects to no database and makes no rewrite.

Each rule has the fields of a PostgreSQL rule, plus two more. **Source** is the name of one entry of the `## Sources` list, or `skill rule` for a rule with no neutral published source. **From** lists the rule ids of the PostgreSQL dialect module with the same idea, or `none`. The severity of a rule is the most severe level among its From rules. A rule with From `none` is `required`, except the query-parameters rule, which is `critical`.

Examples use synthetic tables and the portable positional placeholder `?`.

## Rules

### GEN-01

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

- **Source:** skill rule
- **From:** PG-01

### GEN-02

- **Title:** `NOT IN` over a nullable column
- **Severity:** critical
- **Detects:** `NOT IN (subquery)` where the column that the subquery selects is nullable (a `NULL` in it makes `NOT IN` return no rows). The column on the left of `NOT IN` is not checked. The rule fires only when the SQL text or the repo schema shows the selected column as nullable: a column definition with no `NOT NULL` and no `PRIMARY KEY`. Otherwise the rule does not fire.
- **Why it matters:** When one selected value is `NULL`, the comparison is never true, so the query returns no rows at all. This is the three-valued logic of the SQL standard, so it holds in every engine.
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

- **Source:** skill rule
- **From:** PG-02

### GEN-03

- **Title:** Type mismatch that makes the engine cast the column
- **Severity:** required
- **Detects:** A comparison where the type of the column and the type of the value differ, so the engine casts the column and not the value. It fires only when the repo schema, or an explicit cast in the SQL, shows the column type.
- **Why it matters:** The cast on the column stops a plain index on that column from serving the filter, so the query can read the whole table.
- **Fix:** Write the value with the type of the column, or cast the value with the standard form `CAST(<value> AS <type>)`.
- **Example:** The bad form, then the good form.

  Bad:

  ```sql
  SELECT id FROM stock WHERE qty = 5.0
  ```

  Good:

  ```sql
  SELECT id FROM stock WHERE qty = 5
  ```

- **Source:** skill rule
- **From:** PG-03

### GEN-04

- **Title:** `DISTINCT` hides a fan-out
- **Severity:** required
- **Detects:** A `DISTINCT` on a query with a join that fans out rows (the same one-to-many join evidence as GEN-01).
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

- **Source:** skill rule
- **From:** PG-04

### GEN-05

- **Title:** Function on a filtered column
- **Severity:** suggestion
- **Detects:** A function or an expression on a column in a `WHERE` or `JOIN` condition (for example `lower(email) = ?`), when the repo schema shows no index on that same expression.
- **Why it matters:** A plain index on the column cannot serve a condition on the result of a function, so the query can read the whole table.
- **Fix:** Compare the bare column with a value that you change instead (for example store the lower-case form), or add an index on the expression if the engine supports one. Check the manual of the engine for the name of that feature.
- **Example:** The bad form, then the good form.

  Bad:

  ```sql
  SELECT id FROM users WHERE lower(email) = ?
  ```

  Good:

  ```sql
  SELECT id FROM users WHERE email_lower = ?
  ```

- **Source:** Use The Index, Luke
- **From:** PG-05

### GEN-06

- **Title:** Leading wildcard in `LIKE`
- **Severity:** suggestion
- **Detects:** `LIKE '%...'` with a pattern that starts with a wildcard.
- **Why it matters:** An ordinary index cannot search a pattern with a leading wildcard, so the query reads the whole table.
- **Fix:** Anchor the pattern at the start (`LIKE 'abc%'`), or use the full-text or n-gram search feature of the engine for a search inside the text.
- **Example:** The bad form, then the good form.

  Bad:

  ```sql
  SELECT id FROM users WHERE name LIKE '%son'
  ```

  Good:

  ```sql
  SELECT id FROM users WHERE name LIKE 'son%'
  ```

- **Source:** Use The Index, Luke
- **From:** PG-06

### GEN-07

- **Title:** `OR` across different columns
- **Severity:** suggestion
- **Detects:** An `OR` in `WHERE` whose sides test different columns.
- **Why it matters:** One index rarely serves both sides, so the plan can fall back to a full read.
- **Fix:** Split the query into two queries joined by `UNION`, so each side uses its own index.
- **Example:** The bad form, then the good form (`?` is a positional placeholder).

  Bad:

  ```sql
  SELECT id FROM users WHERE email = ? OR phone = ?
  ```

  Good:

  ```sql
  SELECT id FROM users WHERE email = ? UNION SELECT id FROM users WHERE phone = ?
  ```

- **Source:** Use The Index, Luke
- **From:** PG-07

### GEN-08

- **Title:** `SELECT *`
- **Severity:** suggestion
- **Detects:** `SELECT *` in any SQL text (a `.sql` file or SQL in application code). It excludes `count(*)` and `EXISTS (SELECT * ...)`.
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

- **Source:** SQLFluff
- **From:** PG-08

### GEN-09

- **Title:** Correlated subquery in the select list
- **Severity:** suggestion
- **Detects:** A subquery in the select list that refers to a column of the outer query (a correlated subquery).
- **Why it matters:** The engine can run the subquery once for each outer row, so the cost grows with the number of rows.
- **Fix:** Join an aggregated subquery (or a lateral join where the engine has one), and use `COALESCE` for the missing rows.
- **Example:** The bad form, then the good form.

  Bad:

  ```sql
  SELECT u.id, (SELECT COUNT(*) FROM orders o WHERE o.user_id = u.id) AS n FROM users u
  ```

  Good:

  ```sql
  SELECT u.id, COALESCE(c.n, 0) AS n FROM users u LEFT JOIN (SELECT user_id, COUNT(*) AS n FROM orders GROUP BY user_id) c ON c.user_id = u.id
  ```

- **Source:** skill rule
- **From:** PG-09

### GEN-10

- **Title:** Large literal `OFFSET`
- **Severity:** suggestion
- **Detects:** A literal `OFFSET` above 1000 (or the same skip in the paging form of the engine). An `OFFSET` that is a parameter is not flagged.
- **Why it matters:** The database reads and drops every skipped row, so a deep page gets slower with each page.
- **Fix:** Use keyset pagination: filter on the last seen key (`WHERE id > ? ORDER BY id`), and limit the rows with the limit form of the engine.
- **Example:** The bad form, then the good form (`?` is a positional placeholder).

  Bad:

  ```sql
  SELECT id FROM events ORDER BY id LIMIT 50 OFFSET 5000
  ```

  Good:

  ```sql
  SELECT id FROM events WHERE id > ? ORDER BY id LIMIT 50
  ```

- **Source:** Use The Index, Luke
- **From:** PG-10

### GEN-11

- **Title:** Query parameters instead of string building
- **Severity:** critical
- **Detects:** SQL text that the code builds by joining a value into the string (concatenation, a format call or string interpolation), where the value comes from a variable and not from a fixed constant of the code.
- **Why it matters:** A value in the SQL text can change the structure of the statement. This allows SQL injection. Escaping by hand is fragile, because the rules differ by engine and by configuration.
- **Fix:** Pass the value as a bound parameter, so the SQL structure and the data stay apart. A name of a table or a column cannot be bound: map the choice of the user to a fixed value of the code (an allow-list).
- **Example:** The bad form, then the good form (`?` is a positional placeholder).

  Bad:

  ```sql
  SELECT id FROM users WHERE email = '" + email + "'
  ```

  Good:

  ```sql
  SELECT id FROM users WHERE email = ?
  ```

- **Source:** OWASP SQL Injection Prevention Cheat Sheet
- **From:** none

### GEN-12

- **Title:** Indexes on the columns of filters and joins
- **Severity:** required
- **Detects:** A filter or join column of a table that the repo shows as large (a judgement check, with no row threshold) that has no index which the repo schema or the migrations show. The rule does not fire when the repo shows no schema. It reads no plan.
- **Why it matters:** With no index on the column, the engine reads the whole table for each lookup, and the cost grows with the size of the table.
- **Fix:** Add an index on the column (or the columns together, for a filter on several), then measure with the plan tool of the engine. An index also costs time on each write, so index the columns that the queries use.
- **Example:** The bad form, then the good form.

  Bad:

  ```sql
  SELECT id FROM orders WHERE customer_id = ?
  ```

  Good:

  ```sql
  CREATE INDEX orders_customer_id_idx ON orders (customer_id);
  SELECT id FROM orders WHERE customer_id = ?
  ```

- **Source:** Use The Index, Luke
- **From:** PLAN-02

### GEN-13

- **Title:** Safe migrations
- **Severity:** required
- **Detects:** A schema change in a migration that is hard to undo or to run on a large table: a migration with no down step (or no expand and contract steps), a backfill of a large table in one statement, a new `NOT NULL` column with no backfill step before the constraint, or a change that can lock a large table for a long time.
- **Why it matters:** A change that cannot be undone makes a failed release hard to recover from. A backfill in one statement holds locks and fills the log. A constraint added before the data is ready fails the whole change. Lock behavior differs by engine and by version.
- **Fix:** Write a down step, or split the change into expand and contract steps. Fill the data in small batches over a key range that you can resume. Add the `NOT NULL` constraint after the backfill. Read the lock behavior of the change in the manual of your engine and version before you run it on a large table.
- **Example:** The bad form, then the good form. The form of the `NOT NULL` change differs by engine: read the idea, not the exact text.

  Bad:

  ```sql
  ALTER TABLE orders ADD COLUMN status TEXT NOT NULL;
  UPDATE orders SET status = 'new';
  ```

  Good:

  ```sql
  ALTER TABLE orders ADD COLUMN status TEXT;
  UPDATE orders SET status = 'new' WHERE id BETWEEN 1 AND 10000 AND status IS NULL;
  ALTER TABLE orders ALTER COLUMN status SET NOT NULL;
  ```

- **Source:** skill rule
- **From:** none

## Sources

- **SQLFluff:** https://docs.sqlfluff.com/en/stable/reference/rules.html. `ansi` dialect, rule AM04 (`ambiguous.column_count`), MIT license.
- **OWASP SQL Injection Prevention Cheat Sheet:** https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html. CC BY-SA 4.0: quote with attribution.
- **Use The Index, Luke:** https://use-the-index-luke.com/. All rights reserved: link and paraphrase only.
