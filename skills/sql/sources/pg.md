# pg source module

Load this module when the SQL is in a plain JavaScript or TypeScript string that reaches the `query()` call of a `pg` (node-postgres) receiver (the router's source module rule): a string, an untagged template literal, the `text` of a config object, or the first argument of `new Query(...)`, `new Cursor(...)` or `new QueryStream(...)`. It tells you how to find each statement and how to read it, and it holds the `dynamic` rule and the rules `PGN-01` to `PGN-06`. The facts of `pg` are those of `pg@8.23.1` (`docs/research/pg-query-api.md`).

## Find the statements

The router runs the extractor once for the file, with `--tags` and `--receivers` from the rules file. Do not run it a second time when the router has run it. This module repeats the command so that you can read it alone:

```
python3 <skill folder>/scripts/extract.py <file> --tags sql,this.sql,tx --receivers pool,this.pool
```

1. Take the receiver list from `receivers` of the `[sources]` section of the rules file. With no `[sources]` section, or an empty `receivers` list, run with no `--receivers`: the script then matches the receivers that the file shows. The given list adds receivers that the file cannot show (`import { db } from './db'`). It never removes a receiver that the file shows.
2. Take the tag list as [sources/postgres-js.md](postgres-js.md) says. Leave `--tags` out when the list is empty.

The output has these keys for the `pg` form:

- `detected_receivers`: the receivers that the file shows. Tell the user about a detected receiver that is not in the repo list, because the repo list may miss it.
- `receivers`: the receiver list that the run matched (the given list and the detected receivers).
- `not_followed`: each call whose first argument gives no statement (a call expression, a member access, a `let`, a `var`, a parameter, an imported name, or a `const` that holds a config object), with its `line`. Tell the user that the skill did not read the call at that line. No rule runs on it.
- `statements`: the statements of the file. This module reads the items with `source` `pg`. The postgres.js module reads the items with `source` `template`.

## Read a statement

Name a statement to the user as `<file>:<start_line>-<end_line>`. For a statement that is a followed `const`, also name the line of each call that uses it.

An item with `source` `pg` has the keys of a template statement and a `pg` object:

- `start_line` and `end_line`: the source lines of the SQL text (the string, the template, the whole `+` chain, or the value of the `const`). The span never holds the parentheses around a `query()` argument (`query(('SELECT 1'))`) or the `as const` tail of a `const`: the skill reads both forms like the form with no parentheses and no tail.
- `text`: the decoded SQL value that `pg` sends. For a `dynamic` statement it is the template body or the raw source of the chain.
- `interpolations`: empty, except for a dynamic template. Each of them has a `position` key as in the postgres.js module. The `pg` rules do not read it.
- `pg.kind`: `literal`, `template` or `chain`.
- `pg.const_name`: the name of the followed `const`, or null.
- `pg.line_starts`: for each line of `text`, the source line where it starts. Map a place in `text` to a source line with `line_starts`, never by the offset in the decoded `text`, because an escape shifts the offsets.
- `pg.dynamic` and `pg.statement_count`: `dynamic` is true when the SQL has a part that is not a literal. `statement_count` is null for a dynamic statement.
- `pg.calls`: one entry for each `query()` call that sends this SQL, in source order. Each has `line` (the source line of the call), `call` (`direct`, `config` or `submittable`), `values_length`, `values_present`, `name`, `rows` and `query_mode`.
  - `values_length` is the length of the `values` array literal. It is 0 when the values are missing (`values_present` false), and null when the values are not an array literal (a variable).
  - `name`, `rows` and `query_mode` are a literal value, null, or an object `{"expression": ...}` when the value is not a literal. The extractor does not give the items of `values`: a rule that needs an item reads the call in the source file at `calls[].line`.

A rule that fires on one call names the `line` of its `calls` entry. The rules check each `calls` entry on its own, with the `text` and `statement_count` of its statement.

## The dynamic rule

A statement with `pg.dynamic` true is a `dynamic` statement: a value or a part is joined into the SQL text, so the skill cannot read the whole SQL.

- A `dynamic` statement gets only `PGN-01`. The `PG-*` rules and `PGN-02` to `PGN-06` skip it.
- It gets no plan call, no rewrite proof and no catalog facts. The skill never runs it against a database.
- It is never formatted, explained or diffed.
- It still counts as a `pg` statement when the router chooses the modules of a file.

## Errors

If `error` is not null, stop. Show its `message` and its `line` (the line can be null when the file cannot be read), and ask the user to fix the file. The script exits with code 1 in this case, and with code 2 for a usage error (it prints no JSON then).

## Rules

These rules check how a `pg` statement is composed and sent. They work with no database (`PGN-06` can also read a column type from the catalog when the database is allowlisted). A fix of a `PGN-*` finding repairs the call or the statement. It is not a rewrite of the SQL text. The Where cell of a finding: the SQL text lines of the statement; for a statement that is a followed `const`, also the call line of each `calls` entry that fires the finding (`PGN-02` to `PGN-06`), or every call line for a finding on the SQL text alone (`PGN-01` or a `PG-*` rule).

`PGN-04` and `PGN-06` read the bound value only from a `values` array literal, and `PGN-04` reads a name only in the same file. A value that the file does not show is not judged.

### PGN-01

- **Title:** Value in the text
- **Severity:** critical
- **Detects:** A `dynamic` statement: a value, a name or a part is joined into the SQL text (a `${...}` in a template, a non-literal piece of a `+` chain).
- **Why it matters:** `pg` sends the text as it is, and only `$n` placeholders are bound as values. A value from a user that is joined into the text is an SQL injection.
- **Fix:** Use a `$n` placeholder with `values` for a value. Use `escapeIdentifier` or `escapeLiteral` (exported by `pg`) for a name, because PostgreSQL has no parameter for a name.
- **Example:** The bad form, then the good form.

  Bad:

  ```js
  pool.query(`SELECT id FROM users WHERE name = '${name}'`)
  ```

  Good:

  ```js
  pool.query('SELECT id FROM users WHERE name = $1', [name])
  ```

### PGN-02

- **Title:** Several statements with values
- **Severity:** critical
- **Detects:** `statement_count` above 1 and, in one `calls` entry, `values_length` above 0, or a non-null `name`, or a non-null `rows`, or `query_mode` `extended`. `values: []` does not fire, and a `values_length` of null (values that are not an array literal) does not fire. An expression `name` or `rows` counts as non-null. An expression `query_mode` does not count, because the value is not known to be `extended`.
- **Why it matters:** The JS client picks the protocol from the first match of: `queryMode` `extended`, a `name`, `rows`, an empty text, no `values`, `values.length > 0`. A non-empty `values`, a `name`, `rows` or `queryMode: 'extended'` use the extended protocol, and the server rejects more than one statement there with a syntax error. With none of them, `pg` uses the simple protocol, which allows several statements. The native client takes the values branch for `values: []` too; the rule does not track the receiver's client.
- **Fix:** Send one statement per call, or pass no `values` when the text holds no `$n`.
- **Example:** The bad form, then the good form.

  Bad:

  ```js
  client.query('INSERT INTO logs (msg) VALUES ($1); DELETE FROM tmp', [msg])
  ```

  Good:

  ```js
  await client.query('INSERT INTO logs (msg) VALUES ($1)', [msg])
  await client.query('DELETE FROM tmp')
  ```

### PGN-03

- **Title:** `$n` and `values` do not match
- **Severity:** required
- **Detects:** The highest `$n` outside strings and comments differs from `values_length` of a `calls` entry. A call with no values has `values_length` 0 (`values_present` false), so a text with `$1` and no values fires. A `values_length` of null (values that are not an array literal) gives no finding.
- **Why it matters:** `pg` does not count the placeholders. The server checks the count and fails the query when the number of values differs from the number of parameters.
- **Fix:** Pass one value per placeholder.
- **Example:** The bad form, then the good form.

  Bad:

  ```js
  pool.query('SELECT id FROM users WHERE a = $1 AND b = $2', [a])
  ```

  Good:

  ```js
  pool.query('SELECT id FROM users WHERE a = $1 AND b = $2', [a, b])
  ```

### PGN-04

- **Title:** `IN ($n)` with an array
- **Severity:** critical
- **Detects:** `IN ($n)` where the item of a `values` array literal at the `$n` position is an array literal, or a name that the same file shows as an array (a TypeScript array type or an array literal). Read the item from the call source at `calls[].line`. A value that the file does not show is not judged.
- **Why it matters:** `pg` sends an array as one array parameter. `IN ($1)` then compares the column with one array value, so the query fails or matches nothing.
- **Fix:** Write `= ANY($n)`.
- **Example:** The bad form, then the good form.

  Bad:

  ```js
  pool.query('SELECT id FROM users WHERE id IN ($1)', [[1, 2, 3]])
  ```

  Good:

  ```js
  pool.query('SELECT id FROM users WHERE id = ANY($1)', [[1, 2, 3]])
  ```

### PGN-05

- **Title:** One `name` with different text
- **Severity:** required
- **Detects:** Two `calls` entries in one file with the same literal `name` (a string literal; a `name` that is an `{"expression": ...}` object is not compared), where the statements that hold them have a different `text`. The `calls` of one statement share one `text`, so the two entries are in two statements. The `text` of a followed `const` counts.
- **Why it matters:** A `name` makes `pg` prepare the statement once per connection. A second text under the same name fails with `Prepared statements must be unique`.
- **Fix:** Use one `name` for each text.
- **Example:** The bad form, then the good form.

  Bad:

  ```js
  pool.query({ name: 'get-user', text: 'SELECT id FROM users WHERE id = $1', values: [id] })
  pool.query({ name: 'get-user', text: 'SELECT id FROM users WHERE email = $1', values: [email] })
  ```

  Good:

  ```js
  pool.query({ name: 'get-user-by-id', text: 'SELECT id FROM users WHERE id = $1', values: [id] })
  pool.query({ name: 'get-user-by-email', text: 'SELECT id FROM users WHERE email = $1', values: [email] })
  ```

### PGN-06

- **Title:** JS `Date` passed to a `date` parameter
- **Severity:** required
- **Detects:** The facts of `PGJS-02` ([postgres-js.md](postgres-js.md)): a JS `Date` value bound to a parameter that is a `date`. The bound value is the item of a `values` array literal at the `$n` position, read from the call source at `calls[].line`; a name that the file shows with the type `Date` (`day: Date`) counts as a `Date` value, as in `PGJS-02`. The `date` fact comes from the repo (a `::date` cast, or a migration or schema column of type `date`) or, with an allowlisted database, from the catalog (the `facts` action says that the column has the type `date`). Otherwise the rule does not fire.
- **Why it matters:** `pg` converts a `Date` to a string with the local offset of the process (UTC only when `parseInputDatesAsUTC` is set). The server then casts that instant to `date` in the session time zone, so the day can differ from the local calendar day of the caller and shift.
- **Fix:** As `PGJS-02`: pass the day as text (`'2026-11-09'`), or format the `Date` to its day before the call.
- **Example:** The bad form, then the good form.

  Bad:

  ```js
  pool.query('SELECT id FROM invoices WHERE due_on = $1::date', [new Date()])
  ```

  Good:

  ```js
  pool.query('SELECT id FROM invoices WHERE due_on = $1::date', [isoDay])
  ```
