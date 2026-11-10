# Database access module

This module holds the only way that the skill reads a plan from a real database. It covers `SELECT` statements only. The wrapper `scripts/pg_run.py` is the only path to a database. Both scripts need Python 3.11 or newer (`tomllib`).

## Rules

- Never run `psql` yourself. Never run any other database client. Connect only through `scripts/pg_run.py`.
- Never read `~/.pgpass`, the values of the PG service file, or the allowlist file by hand. Use the reader command of the Allowlist section.
- Never print environment variables. Never ask the user for a password, and never put one in a command.
- Use only a service that the allowlist names. A service that is not on the list is never used, even when the user asks for it. Tell the user how to add it: `/sql setup` (a later ticket) writes the allowlist.
- Never start a database, and never change a database. This module has no write path.

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

With no `--statement`, the statement comes from stdin. Use stdin for a statement that holds a single quote. Only `--mode select` exists. The command prints one JSON object. It exits with 0 when `ok` is true, 1 when `ok` is false and 2 for a usage error.

With `ok` true, the object has `action`, `service`, `mode`, `server_version_num`, `ran` (`analyze`), `reason`, `timeouts` (the timeouts that were sent), `warnings` and `plan` (the parsed plan list). With `ok` false, it has `error`, and the fields of that kind. The only text field is `message`, and it is redacted: every connection value is replaced with the service name.

What Claude does for each `error`:

- `not_allowed`: the allowlist does not allow the call. The `reason` is a reader reason or `service_not_listed`. Claude makes no connection and keeps to the no-database path.
- `refused`: the select guard refused the statement before any connection. Claude reads the `reason` below, and reviews the statement by reading only.
- `connection_failed`: `psql` could not connect (service, password file, host or role problem). Claude does not retry and does not look for the cause in a file. Claude names the failure in one line with the `message`, and goes on with the static report.
- `statement_failed`: the server refused or cancelled the statement (a missing relation, a timeout, a read-only error). Claude reports the `message` and goes on with the static report.
- `psql_failed`: `psql` failed in another way, or it is not installed. Claude names the `message`, and does not try to install anything.
- `bad_output`: the run gave no usable version number or plan. Claude names the `message`, and goes on with the static report.

What Claude does for each guard `reason` of `refused`:

- `empty`: there is no statement. Claude asks for the SQL.
- `unterminated`: a quote, a dollar-quoted string or a comment has no end. Claude fixes the text, or asks the user.
- `multiple_statements`: the text holds more than one statement. Claude splits it, and calls `pg_run` once for each statement.
- `write_statement`: the statement is `INSERT`, `UPDATE`, `DELETE` or `MERGE`. Claude reviews it by reading only, because the write path is not available yet.
- `not_select`: the first word is not `SELECT` or `WITH`. Claude reviews the statement by reading only. See the section about statements that `EXPLAIN` cannot take.
- `data_modifying`: the statement holds `INSERT`, `UPDATE`, `DELETE`, `MERGE` or `INTO`, as a data-modifying CTE, `SELECT ... INTO` or `FOR UPDATE`. Claude reviews it by reading only.
- `forbidden_function`: the statement names `set_config`, `pg_notify`, `lo_export`, or a function that starts with `pg_advisory`, `pg_try_advisory` or `dblink`. Claude reviews it by reading only.
- `unicode_identifier`: the statement holds `U&"`, which can hide a function name. Claude reviews it by reading only.

For a failure of the allowlist, the `reason` `service_not_listed` means that the service is not on the list. Claude names the services that the reader printed, and asks which one to use.

## Read-only path

Select mode accepts exactly one `SELECT` or `WITH ... SELECT`, with one optional trailing `;`. It refuses mode changes (`SET`, `RESET`, `BEGIN`, `COMMIT`, `ROLLBACK` and the like), `VACUUM`, `LISTEN`, `UNLISTEN`, `NOTIFY`, `EXPLAIN`, `TABLE`, `VALUES`, a statement that starts with `(`, a data-modifying CTE, `SELECT ... INTO`, `set_config`, `pg_notify`, `lo_export`, advisory lock functions, `dblink` functions and `U&"`. The guard fails closed: when it is in doubt, it refuses.

The wrapper connects with `psql -X -w` and one connection string: `service=<name> options='...'`. The session options are in `options=`, so an `options` line in the service entry cannot drop them. They set `default_transaction_read_only=on` and `standard_conforming_strings=on`, then the timeouts. The explain run is one session: `BEGIN READ ONLY`, the `EXPLAIN` statement, `ROLLBACK`. The password comes only from the password file of libpq. The wrapper removes `PGPASSWORD`, `PGSERVICE`, `PGOPTIONS`, `PGHOST`, `PGHOSTADDR`, `PGPORT`, `PGUSER` and `PGDATABASE` from the environment of `psql`. It also sets `LC_ALL=C` and removes `LANGUAGE`, `LC_MESSAGES` and `LANG`, so that `psql` writes English messages and the redaction can read them.

## Statements that EXPLAIN cannot take

A statement with `static_review_only` true (DDL, `VACUUM`, `CREATE INDEX CONCURRENTLY`, mode changes, `LISTEN`, `UNLISTEN`, `NOTIFY`, `EXPLAIN`) is reviewed by reading only: no `pg_run` call and no connection. Claude applies the static rules to it and writes no plan.

## No full result

`pg_run explain` returns a plan only. It never returns result rows. Claude never runs a statement to read its rows.

## Timeouts and versions

The wrapper reads the server version first (`SHOW server_version_num`), then sets the options for that version.

| Setting | Value | When |
|---|---|---|
| `statement_timeout` | `30s` | every connection |
| `lock_timeout` | `2s` | every connection |
| `idle_in_transaction_session_timeout` | `10s` | every connection |
| `transaction_timeout` | `60s` | only when the version is `170000` or more |

- A service can override each value with a `timeouts.<service>` table in the allowlist. An override of `transaction_timeout` is not sent to a server before 17.
- The statement is `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` before `180000`, and `EXPLAIN (ANALYZE, FORMAT JSON)` from `180000` (PostgreSQL 18 adds `BUFFERS` by itself).
- The wrapper sets `PGCONNECT_TIMEOUT` to 10 seconds, so an unreachable host cannot hang a call.

## Residual risk

The session flag does not stop a role that has write rights: a function can write, and the explain run executes the statement. The guard and the wrapper are the barrier. The only hard guarantee is a role with `SELECT` privilege only, so the user should allowlist a service with such a role.

## Write mode (stub)

Stub. Ticket #396 fills this section with the write path. It holds no behavior yet.

## Diff (stub)

Stub. Ticket #397 fills this section with the `diff` action. It holds no behavior yet.

## Facts (stub)

Stub. Ticket #400 fills this section with the `facts` action. It holds no behavior yet.
