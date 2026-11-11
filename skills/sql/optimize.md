# Optimize module

`/sql optimize` reports the problems of the SQL that the user points at. The path with no database reads the SQL text and the repo files, writes a report, and waits for the user to approve. That path never connects to a database and does not use [db-access.md](db-access.md). The database path (the section Database path below) reads a real plan, and it does use [db-access.md](db-access.md).

## Steps

1. Take the repo rules: run the reader of the router's rules file step. A rule that is disabled with a reason is not checked. Name the other results as the `Note:` lines below.
2. Pick the source module by the file form (the router's source module rule). Run its extractor and read its statements. Name each statement as `<file>:<start_line>-<end_line>`.
3. Apply every enabled rule of [dialects/postgres.md](dialects/postgres.md) (the `PG-*` rules) to each statement. For a postgres.js template, also apply the `PGJS-*` rules of [sources/postgres-js.md](sources/postgres-js.md).
4. A rule that needs a fact fires only when the repo shows the fact. Read the repo files for it (a schema file, a migration, a type). When the repo does not show the fact, the rule does not fire. With an allowlisted database, the section Database path reads the fact from the catalog instead (this also holds for a statement with an interpolation). When the catalog gives no answer, the rule uses the repo fact as before.
5. When the repo allows a database, take the catalog facts of the rules and the plan of each complete `SELECT` or write statement (`INSERT`, `UPDATE`, `DELETE` or `MERGE`) as the section Database path says, and turn each plan into `PLAN-*` findings as the section Plan findings says. A write statement follows the section Write path. A failed call gives a `Note:` line, and the run goes on.
6. Write the report as the final message, as described below. Then stop.

One finding is one row. A rule id has at most one row in the whole report. When a rule matches in many places, write all places in the Where cell of its one row, separated by `, `.

## Rules file results

- A disabled rule with a reason is listed once on the line `Disabled rules: <ids>.`, with the ids separated by `, `. The report holds no finding of a disabled rule.
- A disabled id with no reason stays enabled, so its findings can appear in the tables. Name it once: `Note: <ID> is disabled with no reason, so it stays enabled.`
- An unknown id is ignored. Name it once: `Note: <ID> is not a rule id, so it is ignored.`
- With no rules file, make no connection and apply every rule. Add the line `Note: no docs/agents/sql.md found. Run /sql setup to set up the repo rules.`

## Report

The final message is the report and nothing else. Write no text before the title line and no text after the Approve line. Write no summary, no list of the statements that you checked, and no prose between the parts. Put anything else that the user must know in a line that starts with `Note:`, placed after the summary line and before the first table.

The report has these parts, in this order:

1. The title line `# sql optimize: <scope>`. The scope is the path of the file that the user named, or the words `the query`.
2. The line `**Result: N critical, N required, N suggestions.**`. Each `N` is the row count of that severity.
3. The line `Disabled rules: <ids>.`, only when a rule is disabled.
4. Zero or more lines that start with `Note:`.
5. One table for each severity that has a finding, in this order: `## Critical`, `## Required`, `## Suggestions`.
6. `## Approve`, the last section.

Every table starts with its severity heading on its own line, and the table header comes right after it. Each table has this header:

```
| # | Rule | Where | Problem | Fix |
|---|---|---|---|---|
```

- The Rule cell holds one rule id.
- The Where cell holds one or more places separated by `, `. A place is `<path>:<line>` or `<path>:<line>-<line>`. The path has no space.
- A cell holds no new line. Write rewritten SQL on one line. Write a literal `|` in a cell as `\|`.
- A table row holds one finding. When the rule does not fire, it has no row, and the report does not mention it (a disabled rule is named only on the `Disabled rules:` line).
- Write each table line with a leading and a trailing `|`.
- One numbering runs through all tables: it starts at 1 in the first table, and the first row of the next table continues from the last number of the previous one, with no gap.

The Approve section holds one line, and it ends the message. With a finding it is exactly:

```
Reply with the findings to fix: `all`, `none`, a list such as `1,3,5`, or a range such as `1-12`.
```

With no finding it is exactly `There is nothing to approve.`

## Rewrites

A rewrite is a fix of a `PG-*` finding that replaces the SQL text of a statement. A fix of a `PGJS-*` finding repairs how the template is composed, and is not a rewrite.

With no database, every rewrite is unproven. Write it in the Fix cell. The cell starts with the exact label `Rewrite (unproven: no database):`, then the rewritten SQL, then the words `database diff` (the proof that is missing, so the cell names it). The Fix cell of a finding that is not a rewrite never holds the capitalised word `Rewrite`. This holds for every `PGJS-*` finding and for a `PG-*` finding that gives advice with no replacement SQL.

## Approval

The skill edits no file before the user replies. After the reply, it edits only the findings that the reply chooses. A rewrite is applied only when the reply names its number, as a number in a list or inside a range. A reply of `all` does not cover a rewrite: name the unproven rows to the user and ask for their numbers.

## Database path

Load [db-access.md](db-access.md) when the run reaches this section. A plan comes only from `pg_run`, as that module says.

1. Run the allowlist reader: `python3 <skill folder>/scripts/allowlist.py <repo root>`. With `access` false, stay on the no-database path and write no extra line.
2. With `access` true and no service in `services`, stay on the no-database path.
3. With no rules file (the router's rules file reader prints `found` false), stay on the no-database path: make no connection.
4. Pick the statements: each `SELECT` or `WITH ... SELECT`, and each statement whose command is `INSERT`, `UPDATE`, `DELETE` or `MERGE` (also with a `WITH` list), that is complete SQL. A write statement has the same completeness rule, the same gates (the allowlist and the rules file) and the same `Note:` lines of step 7 as a `SELECT`. A `.sql` statement is complete. A template is complete when it has no `${...}` interpolation and no `$n` placeholder outside a string or a comment. A statement with an interpolation or a placeholder has no values, so it gets no plan call and stays on the no-database path (the catalog facts step below still reads its column facts).
5. Pick the service. When the allowlist names several, use the service that the user named, or ask which one to use. The module does not run `--check-services`: setup does.
6. For each picked statement, run one command: `python3 <skill folder>/scripts/pg_run.py explain --repo <repo root> --service <name> --mode select --statement '<sql>'` (use `--mode write` instead for a write statement), then a pipe (`|`), then `python3 <skill folder>/scripts/plan_findings.py -`. Write each single quote of the SQL as `'\''`. The plan goes from one script to the other: copy no plan, use no heredoc and no file. Read the JSON of `plan_findings.py` (it holds the plan too), as [db-access.md](db-access.md) says for the plan call.
7. A result with `ok` false is named in one `Note:` line. When `error` is `pg_run_failed`, the plan call failed: `Note: the database call for <file>:<start_line>-<end_line> failed (<source_error>), so that statement has only static findings.` Read the `source` object as [db-access.md](db-access.md) says for that `error` (its `reason`, `service` and redacted `message`), and write the `message` in the line when it helps. When `error` is `bad_input` (this also holds when the plan call printed nothing): `Note: the plan call or the plan findings call failed (bad_input), so that statement has only static findings.` When a tool hook denies the command (the SQL holds `<<` or a space followed by `#`), do not retry with a heredoc or a file: write `Note: the database call for <file>:<start_line>-<end_line> was denied by a tool hook (the SQL holds << or #), so that statement has only static findings.` Then go on with the static report.

An `ok` plan changes no finding of the static rules. A statement with a failed call gives no `PLAN-*` row.

Catalog facts: PG-02 and PGJS-02 need a fact that is not in the SQL text. After the gates of steps 1 to 3 and the service of step 5, read these facts from the catalog with the `facts` action.
- Collect the column names that the two rules need from every statement of the run, also from a statement with an interpolation (`facts` runs no statement). A name is `table.column` or `schema.table.column`. Resolve each table alias to its table in the same statement: from the `FROM` or `JOIN` clause, from the `UPDATE <table>` target, or from the `INSERT INTO <table>` target (so `INSERT INTO t (col) VALUES (...)` gives `t.col`, and `UPDATE t SET col = ...` gives `t.col`). An unqualified column gets the table of the statement only when the statement has exactly one table. Do not send a name that you cannot build or resolve.
- When no name is left, make no `facts` call and write no `Note:` line for it. The repo-fact rule applies.
- Otherwise make one `pg_run.py facts` call for the run with all names: `python3 <skill folder>/scripts/pg_run.py facts --repo <repo root> --service <name> --names <name> [<name> ...]`. Read its JSON, as [db-access.md](db-access.md) says.
- PG-02: for a `NOT IN (subquery)`, the name is the column that the subquery selects. `nullable` true makes the rule fire. `nullable` false does not. Any other answer (`missing`, `null`, no name, a failed call) uses the repo-fact rule.
- PGJS-02: the name is the column that the JS value is compared with or assigned to. A `type` that is exactly `date` makes the date fact true. The `Date` value fact still comes from the repo (a TypeScript type, `new Date(...)` or a `Date` variable). Any other answer (`missing`, another type such as `timestamp`, `date[]` or a domain over `date`, no name, a failed call) uses the repo-fact rule, so a `::date` cast in the SQL still counts there.
- A failed call is one line: `Note: the facts call failed (<error>), so the rules use only the facts that the repo shows.` Then go on with the static report.

## Plan findings

The `PLAN-*` rules are in the section Plan reading of [dialects/postgres.md](dialects/postgres.md). Apply them to each statement that got an `ok` plan from the Database path. The findings come from `plan_findings.py` (step 6 of the Database path), never from your own reading of the plan JSON. Use the `findings` list of its result:

1. A finding of a rule that the repo disables is dropped (the ids of the `Disabled rules:` line). The report holds no row of a disabled rule.
2. A rule id has at most one row in the report. When one plan has the finding at many nodes, or many statements have it, the one row covers all of them. The Where cell lists the place of each statement that has the finding.
3. A finding is a row of the severity that the rule entry gives. The Problem cell is one line. It holds one entry for each finding of that rule, in the order of the script output (statement order, then plan order), separated by `; `. An entry is `<place> <node>: <measured values> against <threshold values>`, taken from `measured` and `threshold`. The cell ends with one sentence that explains the cause. Use the node details of the plan in `plan` for the explanation.
4. The Fix cell proposes the fix in words (an index, an `ANALYZE`, a smaller select list, a filter earlier). It holds no replacement SQL and never the capitalised word `Rewrite`: a `PLAN-*` fix is advice, and the proof of a rewrite is a later ticket.
5. With `analyze` false, write the line `Note: the plan of <file>:<start_line>-<end_line> has no actual values, so no PLAN-* rule applies.` and no row. This also holds for a write statement that ran as a plain `EXPLAIN` (a downgrade).
6. A `PLAN-*` rule never fires without a database. A statement with no plan gets no `PLAN-*` row.

## Write path

A statement whose command is `INSERT`, `UPDATE`, `DELETE` or `MERGE` (also with a `WITH` list) uses `--mode write` in the call of the section Database path, piped into `plan_findings.py -` as for a `SELECT`. The same gates and the same completeness rule apply. The write run always rolls back, so the data is unchanged. Read these keys of the JSON of `plan_findings.py`:

- `ran` is `explain`: a user trigger, a rule or an external call made the run a plain `EXPLAIN`, so the plan has no actual values. Write `Note: <file>:<start_line>-<end_line> ran as plain EXPLAIN: <reason>.` with the `reason` of the result. Write no `PLAN-*` row (item 5 of the section Plan findings).
- `warnings` holds `sequence`: write `Note: <file>:<start_line>-<end_line> writes to a table with a sequence, so the analysis moved the sequence counter (a ROLLBACK does not undo it).`
- A statement that the guard refuses (`error` `pg_run_failed` with a `source_error` of `refused`) gets the `Note:` line of step 7 of the section Database path and only its static findings.

A rewrite of a write statement stays unproven: the proof is a later ticket (see the section Rewrite proof).

## Rewrite proof (stub)

Stub. Ticket #397 fills this section with the proof of a rewrite on a database. It holds no behavior yet.
