# Style module

This module says how to write SQL: the style to use, the default style, the written style and the template layout. The format module and the model-invoked path of the router use it for their own SQL.

## Choose the style

The style has five keys: `keyword_case`, `indent`, `clause_per_line`, `comma` and `alias_as`. Choose the value of each key on its own.

1. Use the value from the `[style]` section of the rules file (the router loads it) when the key is there and its value is allowed. The allowed values: `keyword_case` is `upper` or `lower`; `indent` is `<n> spaces` or `tab`; `comma` is `trailing` or `leading`; `clause_per_line` and `alias_as` are booleans. Name a key with a value that is not allowed once, then treat the key as missing.
2. For each key that is missing (the whole `[style]` section, or one key of it), take the value from the output of the measurer: `style` in the JSON of `scripts/measure_style.py`.
3. Run the measurer on the SQL of the repo: the `.sql` files and the JS or TS files that hold templates. List them with `git ls-files`, or with Glob when the folder is not a git repository. Run `python3 scripts/measure_style.py [--tags <t1,t2,...>] <file>...`. Set `--tags` to the `tags` of the `[sources]` section of the rules file. Leave `--tags` out when that section or key is missing or the list is empty (the extractor rejects an empty value). A file that the extractor cannot read goes in `errors` of the output; it is not measured.
4. When the repo has no such file, use the default style and do not run the measurer (it needs at least one file).

The measurer gives the default style for a key that has a tie or no vote, and for a repo with fewer than 3 statements. Each key in its output has a `source`: `majority` or `default`.

## Default style

Keywords: SELECT DISTINCT FROM WHERE AND OR NOT IN IS NULL AS ON USING JOIN INNER LEFT RIGHT FULL OUTER CROSS NATURAL GROUP BY ORDER HAVING LIMIT OFFSET UNION ALL INTERSECT EXCEPT INSERT INTO VALUES UPDATE SET DELETE RETURNING WITH CASE WHEN THEN ELSE END LIKE ILIKE BETWEEN EXISTS ASC DESC ANY OVER PARTITION CONFLICT DO NOTHING MERGE

Clause words: SELECT INSERT UPDATE DELETE FROM WHERE GROUP HAVING ORDER LIMIT OFFSET SET VALUES RETURNING

A clause word counts only at parenthesis depth 0. `FROM` after `DISTINCT` or `DELETE` is not a clause word. `UPDATE` after `FOR` or `DO` is not a clause word.

The default style: `keyword_case` is `upper`, `indent` is `2 spaces`, `clause_per_line` is true, `comma` is `trailing`, `alias_as` is true.

The default style and the template layout:

```sql
SELECT
  u.id,
  u.name
FROM
  users AS u
  JOIN orders AS o ON o.user_id = u.id
WHERE
  u.active
  AND o.total > 10
ORDER BY
  u.id
```

```js
const rows = await sql`
  SELECT
    u.id
  FROM
    users AS u
  WHERE
    u.id = ${id}
    ${active ? sql`AND u.active` : sql``}
`;
```

## Written style

One rule for each key and each value.

- `keyword_case`: write every word of the `Keywords:` list in that case. Leave names, functions and types as written.
- `indent`: the unit is the value. `<n> spaces` is `n` space characters (any `n`). `tab` is one tab character.
- `clause_per_line` true: each clause word starts its own line.
  - For `SELECT`, `FROM`, `WHERE`, `GROUP`, `HAVING`, `ORDER`, `LIMIT`, `OFFSET`, `SET`, `VALUES` and `RETURNING`, the word is alone on its line. The body of the clause goes on the lines below, one indent unit deeper. For `GROUP` and `ORDER`, the word `BY` stays on the clause line: `ORDER BY a` gives `ORDER BY`, then `a` one unit deeper.
  - For `INSERT`, `UPDATE` and `DELETE`, the line holds the word and the rest of the target: `INSERT INTO t (a, b)`, `UPDATE t`, `DELETE FROM t`.
  - In the body, each item of a comma list at body level goes on its own line. Each `AND` or `OR` condition goes on its own line at the body level. Each `JOIN` goes on its own line at the body level of `FROM`, with its `ON` condition on the same line.
  - Text inside parentheses (function arguments, column lists, `VALUES` tuples, subqueries) stays on its line as written, except for the `keyword_case` and `alias_as` rules.
- `clause_per_line` false: write the statement on one line, with one space between its parts, however long it is. For a template, the body is that one line, between the opening line and the closing backtick line. Two exceptions keep the SQL meaning:
  - A `--` comment ends its line. The text after it starts a new line.
  - A conditional fragment (an interpolation of `fragment` position) starts a new line. The text after it stays on that same line: `SELECT a ${f} FROM t` becomes the two lines `SELECT a` and `${f} FROM t`.

  With either exception, a later measure can vote `true` for the statement. The `comma` key has no effect when `clause_per_line` is false. A word that is not a clause word (`UNION`, `INTERSECT`, `ON CONFLICT`, `WINDOW`, `FOR UPDATE`, `WITH`) keeps its line break position as written. Only the `keyword_case`, `indent` and `alias_as` rules change it.
- `comma` `trailing`: the comma is at the end of the line. `leading`: write `, ` at the start of the next line.
- `alias_as` true: write `AS` for table and column aliases. `alias_as` false: write no `AS`. The measurer and grader C vote only on table aliases after `FROM` or `JOIN`.

## Template layout

- The body of a template is one indent unit deeper than the line that holds the opening backtick. The closing backtick is on its own line, with the indent of that line.
- Each conditional fragment is on its own line, at the clause level it fills.
- Change no `${...}` text, and move none across a clause boundary: the nearest clause word before it stays the same.
- A `value` interpolation stays where it is.
- A `keyword` interpolation is one opaque word. Never split it. The text before the first clause word stays on the first line.
- The default layout is the JS example in the Default style section.
