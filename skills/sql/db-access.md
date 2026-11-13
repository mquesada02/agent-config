# Database access module

This module holds the only way that the skill reads a plan from a real database, the catalog facts of the `facts` action, and the `diff` action that compares two `SELECT` statements. It runs `EXPLAIN` for one `SELECT` (select mode) or for one `INSERT`, `UPDATE`, `DELETE` or `MERGE` (write mode), `facts` takes no statement, and `diff` takes two `SELECT` statements. The wrapper `scripts/pg_run.py` is the only path to a database. Both scripts need Python 3.11 or newer (`tomllib`).

## Rules

- Never run `psql` yourself. Never run any other database client. Connect only through `scripts/pg_run.py`.
- Never read `~/.pgpass`, the values of the PG service file, or the allowlist file by hand. Use the reader command of the Allowlist section.
- Never print environment variables. Never ask the user for a password, and never put one in a command.
- Use only a service that the allowlist names. A service that is not on the list is never used, even when the user asks for it. Tell the user how to add it: `/sql setup` (a later ticket) writes the allowlist.
- Never start a database, and never change a database. The only write path is `pg_run explain --mode write`, which always rolls back (see the Write mode section).

## Allowlist

The allowlist is a file of the user, never in the repo: `$XDG_CONFIG_HOME/sql-skill/allowlist.toml` (`~/.config/sql-skill/allowlist.toml` when `XDG_CONFIG_HOME` is unset, empty or relative). It has one table for each repo. The key of the table is the normalized URL of the remote `origin`. With no `origin`, the key is the git common dir path, so all worktrees of one clone share one entry. The entry holds `services` (a list of PG service names) and an optional `timeouts.<service>` table.

Run the reader:

```
python3 <skill folder>/scripts/allowlist.py <repo root>
```

It prints one JSON object. With `access` true it has `key`, `services` and `timeouts`. With `access` false it has a `reason`: `no_repo`, `missing_file`, `unreadable_file`, `malformed_file` (with a `detail`) or `no_entry`. The command exits with 0 for every result. With `access` false, make no connection, and tell the user only when the user asked for a database run.

The option `--check-services` adds `service_check`: it lists the allowlisted services that have no `[name]` header in the PG service file. Only `/sql setup` uses it.

## pg_run

Run one statement:

```
python3 <skill folder>/scripts/pg_run.py explain --repo <repo root> --service <name> --mode select --statement '<sql>'
```

With no `--statement`, the statement comes from stdin. Use stdin for a statement that holds a single quote. `--mode` is `select` or `write`: use `--mode select` for a `SELECT`, and `--mode write` for an `INSERT`, `UPDATE`, `DELETE` or `MERGE` (see the Write mode section). The command prints one JSON object. It exits with 0 when `ok` is true, 1 when `ok` is false and 2 for a usage error.

With `ok` true, the object has `action`, `service`, `mode`, `server_version_num`, `ran` (`analyze` or `explain`: `explain` is a downgrade, see the Read-only path and Write mode sections), `reason`, `timeouts` (the timeouts that were sent), `downgrade` (a list, empty for an `analyze` run), `warnings` and `plan` (the parsed plan list). With `ok` false, it has `error`, and the fields of that kind. The only text field is `message`, and it is redacted: every connection value is replaced with the service name.

In the optimize flow the command is piped into `scripts/plan_findings.py -` (see the optimize module). A plan call that fails then comes back from that script as `error` `pg_run_failed`, with `source_error` (the `error` of the plan call) and `source` (the object below, unchanged). Read `source` for the kinds and reasons below.

What Claude does for each `error`:

- `not_allowed`: the allowlist does not allow the call. The `reason` is a reader reason or `service_not_listed`. Claude makes no connection and keeps to the no-database path.
- `refused`: the guard of the mode (or, for `diff`, the diff guard) refused the statement before any connection. Claude reads the `reason` below, and reviews the statement by reading only. A `diff` refusal also has `statement` (`a` or `b`).
- `connection_failed`: `psql` could not connect (service, password file, host or role problem). Claude does not retry and does not look for the cause in a file. Claude names the failure in one line with the `message`, and goes on with the static report.
- `statement_failed`: the server refused or cancelled the statement (a missing relation, a timeout, a read-only error). Claude reports the `message` and goes on with the static report.
- `psql_failed`: `psql` failed in another way, or it is not installed. Claude names the `message`, and does not try to install anything.
- `bad_output`: the run gave no usable version number, plan or `diff` result. Claude names the `message`, and goes on with the static report.

What Claude does for each guard `reason` of `refused`:

- `empty`: there is no statement. Claude asks for the SQL.
- `unterminated`: a quote, a dollar-quoted string or a comment has no end. Claude fixes the text, or asks the user.
- `multiple_statements`: the text holds more than one statement. Claude splits it, and calls `pg_run` once for each statement.
- `write_statement`: the statement is `INSERT`, `UPDATE`, `DELETE` or `MERGE`, and the mode is select. Claude calls `pg_run` again with `--mode write`.
- `not_select`: the first word is not `SELECT` or `WITH`. Claude reviews the statement by reading only. See the section about statements that `EXPLAIN` cannot take.
- `data_modifying`: the statement holds `INSERT`, `UPDATE`, `DELETE`, `MERGE` or `INTO`, as a data-modifying CTE, `SELECT ... INTO` or `FOR UPDATE`. Claude sends a `WITH ... INSERT|UPDATE|DELETE|MERGE` statement to `--mode write`, and reviews `INTO`, `FOR UPDATE` and a data-modifying CTE with a `SELECT` main statement by reading only.
- `not_write`: write mode only. The statement is not exactly one `INSERT`, `UPDATE`, `DELETE` or `MERGE` (with an optional `WITH` list). When `static_review_only` is false and the first word is `SELECT` or `WITH`, Claude calls `pg_run` again with `--mode select`. Otherwise Claude reviews the statement by reading only.
- `forbidden_function`: select mode names `set_config`, `pg_notify`, `lo_export`, and every function that starts with `pg_advisory`, `pg_try_advisory` or `dblink`; write mode names `set_config` only (the other names give a downgrade); `diff` names the select-mode names and also `query_to_xml*`, `cursor_to_xml*`, `ts_stat`, `ts_rewrite`, `crosstab*`, `connectby` and `setval`. Claude reviews the statement by reading only.
- `unicode_identifier`: the statement holds `U&"`, which can hide a function name. Claude reviews it by reading only.
- `unbalanced_parentheses`: `diff` only. The parentheses of the statement do not balance, so the statement could change the structure of the proof query. Claude fixes the text, or asks the user.

For a failure of the allowlist, the `reason` `service_not_listed` means that the service is not on the list. Claude names the services that the reader printed, and asks which one to use.

## Read-only path

Select mode accepts exactly one `SELECT` or `WITH ... SELECT`, with one optional trailing `;`. It refuses mode changes (`SET`, `RESET`, `BEGIN`, `COMMIT`, `ROLLBACK` and the like), `VACUUM`, `LISTEN`, `UNLISTEN`, `NOTIFY`, `EXPLAIN`, `TABLE`, `VALUES`, a statement that starts with `(`, a data-modifying CTE, `SELECT ... INTO`, `set_config`, `pg_notify`, `lo_export`, advisory lock functions, `dblink` functions and `U&"`. The guard fails closed: when it is in doubt, it refuses.

Select mode does not refuse a statement that calls a string-SQL function (`query_to_xml*`, `cursor_to_xml*`, `ts_stat`, `ts_rewrite`, `crosstab*`, `connectby`). Such a function runs SQL from a string argument. The guard cannot scan that text, and `ANALYZE` would run it.

So the run is a plain `EXPLAIN` (`EXPLAIN (FORMAT JSON)`) in the same `BEGIN READ ONLY` ... `ROLLBACK` session. This is a downgrade. The result has `ran` `explain`, a `reason` such as `the statement calls query_to_xml`, and a `downgrade` list of `{"kind": "function", "name"}`. The plan has no actual values.

A forbidden function that the statement calls directly (`dblink_exec`, `pg_notify`) is still refused with `forbidden_function`. This also holds when the statement calls a string-SQL function. The scan reads the statement only (see the Residual risk section).

Write mode has its own guard and its own transaction (`BEGIN READ WRITE`, always ended by `ROLLBACK`): see the Write mode section.

The wrapper connects with `psql -X -w` and one connection string: `service=<name> options='...'`. The session options are in `options=`, so an `options` line in the service entry cannot drop them. They set `default_transaction_read_only=on` and `standard_conforming_strings=on`, then the timeouts. The explain run is one session: `BEGIN READ ONLY`, the `EXPLAIN` statement, `ROLLBACK`. The password comes only from the password file of libpq. The wrapper removes `PGPASSWORD`, `PGSERVICE`, `PGOPTIONS`, `PGHOST`, `PGHOSTADDR`, `PGPORT`, `PGUSER` and `PGDATABASE` from the environment of `psql`. It also sets `LC_ALL=C` and removes `LANGUAGE`, `LC_MESSAGES` and `LANG`, so that `psql` writes English messages and the redaction can read them.

## Statements that EXPLAIN cannot take

A statement with `static_review_only` true (DDL, `VACUUM`, `CREATE INDEX CONCURRENTLY`, mode changes, `LISTEN`, `UNLISTEN`, `NOTIFY`, `EXPLAIN`) is reviewed by reading only: no `pg_run` call and no connection. Claude applies the static rules to it and writes no plan. Write mode follows the same rule with its own value: a `SELECT` or a `WITH` that holds `INSERT`, `UPDATE`, `DELETE`, `MERGE` or `INTO` and is not a write statement (for example a data-modifying CTE with a `SELECT` main statement, `SELECT ... FOR UPDATE`) is `static_review_only` true. A plain `SELECT` or `WITH ... SELECT`, `TABLE`, `VALUES` and a statement that starts with `(` are `static_review_only` false in write mode, and Claude uses select mode for them (`TABLE`, `VALUES` and `(` are reviewed by reading only, as select mode refuses them too).

## No full result

`pg_run explain` returns a plan only. `pg_run facts` returns catalog metadata only. Neither returns result rows. `pg_run diff` returns at most 20 rows of each difference (see the Diff section). Claude never runs a statement to read its rows.

## Timeouts and versions

The wrapper reads the server version first (`SHOW server_version_num`), then sets the options for that version.

| Setting | Value | When |
|---|---|---|
| `statement_timeout` | `30s` | every connection |
| `lock_timeout` | `2s` | every connection |
| `idle_in_transaction_session_timeout` | `10s` | every connection |
| `transaction_timeout` | `60s` | only when the version is `170000` or more |

- A service can override each value with a `timeouts.<service>` table in the allowlist. An override of `transaction_timeout` is not sent to a server before 17.
- The statement is `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` before `180000`, and `EXPLAIN (ANALYZE, FORMAT JSON)` from `180000` (PostgreSQL 18 adds `BUFFERS` by itself). Write mode uses the same two forms for its `ANALYZE` run, and the same timeouts in each of its runs.
- The wrapper sets `PGCONNECT_TIMEOUT` to 10 seconds, so an unreachable host cannot hang a call.

## Residual risk

The session flag does not stop a role that has write rights: a function can write, and the explain run executes the statement. The guard and the wrapper are the barrier. The only hard guarantee for select mode is a role with `SELECT` privilege only, so the user should allowlist a service with such a role. A service that is used in write mode needs a role with write rights, so a role with `SELECT` privilege only stays the hard guarantee for select mode, not for write mode.

In write mode the guard and the forced `ROLLBACK` are the barrier, and `ROLLBACK` does not undo everything. A rolled-back `ANALYZE` leaves dead tuples and moves the statistics counters (`pg_stat_*`). It also moves a sequence (see the `sequence` warning). These risks stay open:

- a user-defined function or a trigger function with an external effect that the scan cannot see, and a privilege-gated system function such as `pg_terminate_backend`;
- a function that runs SQL from a string argument and is not in the scan names (a volatile call inside the string is not scanned);
- `pg_logical_emit_message` with a non-transactional flag, and a scanned function that is called from a column default, a `CHECK` constraint, a generated expression, a domain constraint, a row-level security policy or the body of a view that the statement reads (the scan reads the statement only), and `pg_cancel_backend` on the caller's own backends;
- the `sequence` warning for a `MERGE` into a table with an identity column, which is given even when the `MERGE` only updates (conservative);
- a trigger or a rule that another session adds between the discovery run, the catalog run and the `ANALYZE` run (they are separate sessions);
- a write on a foreign table (the effect on the remote side depends on the foreign data wrapper, and the check does not read foreign servers);
- a sequence that a user function (also one in a column `DEFAULT`) or a `DEFAULT` change moves with no warning (an `UPDATE` or an `ON CONFLICT DO UPDATE` that sets a column to `DEFAULT` with a `nextval` default);
- the guard reads the case of a word with ASCII rules only in select mode, write mode and `diff`, as the server scanner does: a word with a non-ASCII letter that looks like a keyword (a long s, a dotless i, a Kelvin sign) is a different identifier, and no Unicode letter folds to an ASCII letter. On a server with a single-byte encoding the server folds a high-bit letter with the C library; no such letter maps to an ASCII letter, so the ASCII read stays the safe one.

In select mode the downgrade to a plain `EXPLAIN` reads the statement only. A view body, a column default, a row-level security policy or a user-defined function can call a string-SQL function. The scan does not find that call, so `ANALYZE` still runs it. The select guard lexer has the open risks listed below.

`diff` runs the user's `SELECT` statements, so the select guard is its barrier, and its own refusals close the string-SQL functions. These risks stay open:

- the guard lexer is hand written: it can differ from the server lexer in rare cases (a vertical tab: it is blank only on PostgreSQL 17 and later, and the guard tokenizer skips it on every version, so an older server rejects such text, which is the safe direction; the cut of the sent text strips only the blanks of every supported version), and the select-mode function list is a name list, not a proof (on 2026-11-12 a one-time sweep of the built-in functions of PostgreSQL 13 to 18 and of `dblink` and `tablefunc` found `ts_rewrite` as the only string-SQL function that the list lacked; the sweep read the catalogs of PostgreSQL 13 and 18 and the documentation for 14 to 17, so a function that a later version adds, or a function that the sweep misjudged, still reaches the server in `explain` select mode and in `diff`);
- a user function with an external effect that the guard cannot see;
- the three sessions of `diff` are not one transaction: a schema change between them makes the proof fail or compare the new types;
- the order proof does not read the output order of B (see the Diff section);
- the proof runs A and B: a volatile function can give a false difference, and a large result is cut by the 30 second `statement_timeout`;
- a composite or a multirange column is compared as `text` (a conservative reading of "no equality operator");
- `diff` returns up to 80 rows of the user's data to Claude (20 in each of `only_a`, `only_b` and the two lists of `order_mismatch`).

## Write mode

Run one write statement:

```
python3 <skill folder>/scripts/pg_run.py explain --repo <repo root> --service <name> --mode write --statement '<sql>'
```

Write mode takes exactly one `INSERT`, `UPDATE`, `DELETE` or `MERGE`, with one optional `WITH` list and one optional trailing `;`. The guard has its own messages. It refuses (with `reason` `not_write`) every other statement, and `set_config` (with `forbidden_function`). The guard reads the `WITH` list as a grammar and fails closed. Select mode and write mode refuse DDL and `VACUUM`.

The session sets `standard_conforming_strings=on` and the timeouts, and it sets no `default_transaction_read_only`. Each run opens `BEGIN READ WRITE` and ends in `ROLLBACK`, so the data is unchanged. The runs use `ON_ERROR_STOP`, so a failed statement closes the connection and the server rolls back the open transaction. The steps:

1. The version probe (read-only, as in select mode).
2. The discovery run: `EXPLAIN (VERBOSE, FORMAT JSON)` of the statement with no `ANALYZE`, so nothing runs. It finds the written tables, also behind a view or a rule. An odd plan, or a statement that gives no plan (a `DO INSTEAD NOTHING` rule), is `bad_output`, and no later run follows.
3. The scan: the guard finds the functions whose effect `ROLLBACK` cannot undo (`dblink*`, session advisory locks, `lo_export`, `setval`) and the functions that run SQL from a string argument (`query_to_xml*`, `cursor_to_xml*`, `ts_stat`, `ts_rewrite`, `crosstab*`, `connectby`). A name in a string or a comment is not found. With one name, the catalog check is skipped and the run goes down to a plain `EXPLAIN`.
4. The catalog check: one read-only run that finds, on every reached table, a user trigger (enabled, and not internal; a user constraint trigger, and a trigger that PostgreSQL 13 or 14 clones onto a partition as an internal one, count too) or a rule. The reached tables are the targets, the partitions and inheritance children, the children of a foreign key with a `CASCADE`, `SET NULL` or `SET DEFAULT` action, and the base tables of every view (followed through nested views). A hit gives a plain `EXPLAIN`.
5. The last run: `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` (see the Timeouts and versions section) when nothing was found, else a plain `EXPLAIN (FORMAT JSON)`.

The output has the fields of the pg_run section, with these in write mode:

- `ran`: `analyze` or `explain`. `explain` is a downgrade: the plan has no actual values.
- `reason`: for `analyze`, `no trigger, rule or external call on the reached tables`. For a downgrade, one sentence with the function names or the table names.
- `downgrade`: a list of `{"kind", "name"}`. `kind` is `function`, `trigger` or `rule`. `name` is the function name or the schema-qualified table name. It is empty when `ran` is `analyze`.
- `warnings`: `["sequence"]` when the `ANALYZE` run moved a sequence counter (the statement inserts into a table with an identity column or a `nextval` default, or calls `nextval`). `ROLLBACK` does not undo a sequence. It is `[]` for a plain `EXPLAIN`.

What Claude does:

- A `downgrade` is reported as a plain `EXPLAIN`, with its `reason`. Claude writes no `PLAN-*` row for a plan with no actual values.
- A `sequence` warning is named in the `Note:` line of the optimize module.
- Claude never runs a write statement by hand, and never calls write mode for a statement that is not a write.

## Diff

`diff` compares the result of a `SELECT` A with the result of a rewrite B of it, on an allowlisted service. The optimize module uses it for the proof of a rewrite (the section Rewrite proof). Run it:

```
python3 <skill folder>/scripts/pg_run.py diff --repo <repo root> --service <name> --a=<sql> --b=<sql>
```

`--a` and `--b` are both required. Write each as `--a=<sql>`, one argument with an equals sign: a separate value that starts with `-` and holds no space is read as an option, and gives a usage error (exit code 2). Write a single quote of the SQL as `'\''`. Each statement must be one `SELECT` or `WITH ... SELECT`. Both statements pass the guard of `diff` before any connection. The command exits with 0 when `ok` is true, 1 when `ok` is false and 2 for a usage error.

The guard of `diff` has the select-mode reasons with its own messages: a write statement is `write_statement` (a rewrite of a write statement is unproven, so Claude makes no `diff` call for it). It adds two refusals. `unbalanced_parentheses`: the `(` and `)` of the statement do not balance. `forbidden_function`: the statement calls `query_to_xml*`, `cursor_to_xml*`, `ts_stat`, `ts_rewrite`, `crosstab*`, `connectby` or `setval`, or a function that select mode refuses. Such a function runs SQL from a string that the guard cannot read. A refusal has `statement` (`a` or `b`), `reason`, `message` and `static_review_only`, and no connection is made. Claude reviews the statement by reading only.

The comparison runs in one read-only transaction (`BEGIN READ ONLY`, one `SELECT`, `ROLLBACK`), after two read-only sessions that only describe the statements (the output column names with the version, then the column types). A schema change between the sessions can make the proof fail with `statement_failed`. The proof transaction runs each user statement once. The first session runs each statement with `LIMIT 0`, and the second session only plans them.

With `ok` true, every result has `action` (`diff`), `service`, `server_version_num`, `timeouts` (the timeouts that were sent), `equal` and the fields below.

- A shape result has `reason` `shape` and `column_names` (`{"a": [...], "b": [...]}`), and `equal` is false. A and B differ in column count or in a column name, so nothing was compared.
- A full result has `columns` (`{"a": [{"name", "type"}], "b": [...]}`), `rows` (`{"a": <count>, "b": <count>}`), `only_a` and `only_b` (`{"count": <full count>, "rows": [...]}`: at most 20 rows, as arrays in column order), `type_mismatch` (a list of `{"position", "name"}`), `casts`, `floats` (lists of column names) and `order`.
- `equal` is true when the shape matches, `type_mismatch` is empty, both counts are 0, and the order check (when `order` is `checked`) found no difference.

Types and casts. Rows are compared as a multiset (`EXCEPT ALL`: a duplicate count counts). A column whose type differs between A and B is in `type_mismatch` and is compared as `text`. A column of a type with no equality operator that `EXCEPT` can use (for example `json` or `xml`) is compared as `text` and named in `casts`. A column of type `real` or `double precision` is compared exactly and named in `floats`: a difference there can be a rounding difference, so say so.

Order. `order` is `not_applicable` when A has no top-level `ORDER BY`. When A has one with keys that are output column names or positions, both sides are numbered by those keys and the numbered rows are compared: `order` is `checked`, and `order_mismatch` has `count_a`, `count_b` and the samples `a` and `b` (arrays that start with the rank). `checked` means that both sides have the same rows at the same ranks. It does not read the output order of B. `order` is `partial` with `reason` `ties` (a sort key repeats, so the order is not fixed) or `sort_keys` (a key is an expression, a qualified name, `USING`, `COLLATE`, an input column that is not an output column, or a column with a type mismatch).

`diff` is the only action that returns rows of the user's data, and it returns samples only: at most 20 rows in each of `only_a` and `only_b`, and the same cap in each list of `order_mismatch`. A statement with a volatile function (`random()`, `now()`) can give a false difference.

## Facts

`facts` reads the nullability and the type of columns from the catalog. Run it:

```
python3 <skill folder>/scripts/pg_run.py facts --repo <repo root> --service <name> --names <name> [<name> ...]
```

A name is `table.column` or `schema.table.column`. The parts are matched exactly (case-sensitive, with no quote handling and no case folding), so write them as they are in the catalog. An unqualified table is found through the `search_path` of the session. A name of another shape, or with a character that is not printable ASCII, is `missing` and is never sent to the server. When no name is sent, the command makes no `psql` call at all. The command takes no statement, so it needs no guard and no `--mode`. At least one name is required (a usage error, exit 2, otherwise). A name that starts with `-` is a usage error.

The command checks the allowlist first, as `explain` does. It reads the server version, then runs one fixed catalog query in one read-only transaction, with the session options and the timeouts of the Timeouts and versions section. The names reach the server only as one quoted value, never as SQL text.

With `ok` true, the object has `action` (`facts`), `service` and `facts`. `facts` has one key for each name that you gave, in the same order. The value is one of:

- `{"nullable": <true, false or null>, "type": "<type>"}`: the column exists. `nullable` is `false` for a `NOT NULL` column of a table. It is `null` for a column of a view or a materialized view, because the catalog holds no nullability for it. `type` is the type as the catalog writes it (`integer`, `date`, `numeric(10,2)`, a domain name for a domain).
- `{"missing": true}`: the column or the table does not exist, or the name has an invalid shape.

The output holds catalog metadata only: no row data. The errors are the kinds of the pg_run section (`not_allowed`, `connection_failed`, `statement_failed`, `psql_failed`, `bad_output`), with the same redaction and the same exit codes (0 when `ok` is true, 1 when `ok` is false, 2 for a usage error).

What Claude does:

- Read only the keys that the rules need. A `nullable` of `null` and `missing` are not facts: the rule uses the repo fact instead.
- A very long list of names can exceed the argument length limit of the system. The command then gives `psql_failed`. Send fewer names.
- Never run `psql` by hand to read the catalog.
