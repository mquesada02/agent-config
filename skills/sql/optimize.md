# Optimize module

`/sql optimize` reports the problems of the SQL that the user points at. The path with no database reads the SQL text and the repo files, writes a report, and waits for the user to approve. That path never connects to a database and does not use [db-access.md](db-access.md). The database path (the section Database path below) reads a real plan, and it does use [db-access.md](db-access.md).

## Steps

1. Take the repo rules: run the reader of the router's rules file step. A rule that is disabled with a reason is not checked. Name the other results as the `Note:` lines below.
2. Pick the source module by the file form (the router's source module rule). Run its extractor and read its statements. Name each statement as `<file>:<start_line>-<end_line>`.
3. Apply every enabled rule of [dialects/postgres.md](dialects/postgres.md) (the `PG-*` rules) to each statement. For a postgres.js template, also apply the `PGJS-*` rules of [sources/postgres-js.md](sources/postgres-js.md).
4. A rule that needs a fact fires only when the repo shows the fact. Read the repo files for it (a schema file, a migration, a type). When the repo does not show the fact, the rule does not fire. With an allowlisted database, the section Database path reads the fact from the catalog instead (this also holds for a statement with an interpolation). When the catalog gives no answer, the rule uses the repo fact as before.
5. When the repo allows a database, take the catalog facts of the rules and the plan of each complete `SELECT` or write statement (`INSERT`, `UPDATE`, `DELETE` or `MERGE`) as the section Database path says, and turn each plan into `PLAN-*` findings as the section Plan findings says. A write statement follows the section Write path. A failed call gives a `Note:` line, and the run goes on. For a proposed rewrite, follow the section Rewrite proof.
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

With no database, every rewrite is unproven. Write it in the Fix cell. The cell starts with the exact label `Rewrite (unproven: no database):`, then the rewritten SQL, then the words `database diff` (the proof that is missing, so the cell names it). For a proposed rewrite on a run with a database, follow the section Rewrite proof: it gives the other labels. The Fix cell of a finding that is not a rewrite never holds the capitalised word `Rewrite`. This holds for every `PGJS-*` finding and for a `PG-*` finding that gives advice with no replacement SQL.

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
4. The Fix cell proposes the fix in words (an index, an `ANALYZE`, a smaller select list, a filter earlier). It holds no replacement SQL and never the capitalised word `Rewrite`: a `PLAN-*` fix is advice, and a rewrite is proven as the section Rewrite proof says.
5. With `analyze` false, write the line `Note: the plan of <file>:<start_line>-<end_line> has no actual values, so no PLAN-* rule applies.` and no row. This also holds for a write statement that ran as a plain `EXPLAIN` (a downgrade).
6. A `PLAN-*` rule never fires without a database. A statement with no plan gets no `PLAN-*` row.

## Write path

A statement whose command is `INSERT`, `UPDATE`, `DELETE` or `MERGE` (also with a `WITH` list) uses `--mode write` in the call of the section Database path, piped into `plan_findings.py -` as for a `SELECT`. The same gates and the same completeness rule apply. The write run always rolls back, so the data is unchanged. Read these keys of the JSON of `plan_findings.py`:

- `ran` is `explain`: a user trigger, a rule or an external call made the run a plain `EXPLAIN`, so the plan has no actual values. Write `Note: <file>:<start_line>-<end_line> ran as plain EXPLAIN: <reason>.` with the `reason` of the result. Write no `PLAN-*` row (item 5 of the section Plan findings).
- `warnings` holds `sequence`: write `Note: <file>:<start_line>-<end_line> writes to a table with a sequence, so the analysis moved the sequence counter (a ROLLBACK does not undo it).`
- A statement that the guard refuses (`error` `pg_run_failed` with a `source_error` of `refused`) gets the `Note:` line of step 7 of the section Database path and only its static findings.

A rewrite of a write statement stays unproven: it gets no `diff` call and a label of the section Rewrite proof.

## Rewrite proof

A faster query must also be a correct one. This section proves a rewrite of a `SELECT` with the `diff` action of `pg_run` and the repo tests. Claude proposes the rewrite B of the statement A. This section only proves it.

1. A rewrite is proven only for a complete `SELECT` or `WITH ... SELECT` and an allowlisted service (the same gates as the section Database path: the allowlist, the rules file and the completeness rule). Make one call: `python3 <skill folder>/scripts/pg_run.py diff --repo <repo root> --service <name> --a='<A>' --b='<B>'`. Write each as `--a=<sql>`, one argument with an equals sign. Write each single quote of the SQL as `'\''`.
2. Read the result.
   - A result with `ok` false (`refused`, `not_allowed`, `connection_failed`, `statement_failed`, `psql_failed`, `bad_output`) gives the label `Rewrite (unproven: the database diff failed):` and a `Note:` line, as step 7 of the section Database path says. A call that a tool hook denies (the SQL of A or B holds `<<` or a space followed by `#`, so there is no JSON result) or that prints no JSON gets the same label and the hook `Note:` line of that step. Do not retry with a heredoc or a file.
   - `reason` `shape`, or `equal` false: the rewrite changes the result, so it is not offered. For `shape`, the `Note:` line names `column_names` of both sides. Otherwise it names `type_mismatch`, the counts of `only_a` and `only_b`, `order_mismatch` when present, and `casts` and `floats`. A difference in a column named in `floats` is possibly a rounding difference: say so.
   - `order` `partial` makes the proof partial: the label names the reason (`ties` or `sort_keys`).
   - `order` `checked` means that both sides, numbered by the sort keys of A, have the same rows at the same ranks. It does not mean that B returns its rows in that order: when B must keep the order, B needs the same `ORDER BY`.
3. The repo tests, after an `equal` diff. Find the test command in the repo's own instructions (`CLAUDE.md` or `AGENTS.md`, read with the `Read` tool), else in the `test` script of `package.json`. Run it with at most 2 workers: add the limit that the runner takes (`--test-concurrency=2` for `node --test`, `--maxWorkers=2` for `jest`); when the declared command already sets a lower limit, add nothing. For any other runner, whose limit flag this module does not name, do not run the command (the limit of 2 workers would not hold): the rewrite is proven by the database diff only, item 4 applies, and the `Note:` line says `Note: the repo tests were not run: the limit of 2 workers cannot be set for <command>.` Run the command once, as declared plus the worker limit, with no pipe and no redirect. When the tests fail, the rewrite is not offered, and a `Note:` line names the failed command.
4. No test command found: the rewrite is proven by the database diff only, with the warning `Note: no repo tests ran for <place>, so the rewrite is proven by the database diff only.`
5. A rewrite of a write statement (`INSERT`, `UPDATE`, `DELETE` or `MERGE`) is unproven: `diff` takes a `SELECT` only, so make no `diff` call for it.
6. A statement that is not complete SQL (a template with an interpolation or a `$n` placeholder) has no values to diff: its rewrite is unproven.
7. Labels. The Fix cell of a rewrite starts with exactly one of these labels, then the rewritten SQL on one line, and it holds the words `database diff` (in the label, or after the SQL):
   - `Rewrite (proven: database diff and repo tests):`
   - `Rewrite (proven by the database diff only: no repo tests ran):`
   - `Rewrite (partial proof by the database diff: order not checked, ties):` and `Rewrite (partial proof by the database diff: order not checked, sort keys):` (a `Note:` line names the tests: they passed, or the warning of item 4)
   - `Rewrite (unproven: no database):` (with the words `database diff` after the SQL)
   - `Rewrite (unproven: the database diff failed):` (item 2)
   - `Rewrite (unproven: write statement, no database diff):`
   - `Rewrite (unproven: statement not complete, no database diff):`
8. Approval: a proven, partial or unproven rewrite is applied only when the user names its number, as the section Approval says. A reply of `all` covers no rewrite. The report has no new section: the `Note:` lines go in the place that the section Report gives.
