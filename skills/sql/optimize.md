# Optimize module

`/sql optimize` reports the problems of the SQL that the user points at. The path with no database reads the SQL text and the repo files, writes a report, and waits for the user to approve. That path never connects to a database and does not use [db-access.md](db-access.md). The database path (the section Database path below) reads a real plan, and it does use [db-access.md](db-access.md).

## Steps

1. Take the repo rules: run the reader of the router's rules file step. A rule that is disabled with a reason is not checked. Name the other results as the `Note:` lines below.
2. Pick the source module by the file form (the router's source module rule). Run its extractor and read its statements. Name each statement as `<file>:<start_line>-<end_line>`.
3. Apply every enabled rule of [dialects/postgres.md](dialects/postgres.md) (the `PG-*` rules) to each statement. For a postgres.js template, also apply the `PGJS-*` rules of [sources/postgres-js.md](sources/postgres-js.md).
4. A rule that needs a fact fires only when the repo shows the fact. Read the repo files for it (a schema file, a migration, a type). When the repo does not show the fact, the rule does not fire.
5. When the repo allows a database, take the plan of each complete `SELECT` as the section Database path says. A failed call gives a `Note:` line, and the run goes on.
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
4. Pick the statements: each `SELECT` or `WITH ... SELECT` that is complete SQL. A `.sql` statement is complete. A template is complete when it has no `${...}` interpolation and no `$n` placeholder outside a string or a comment. A statement with an interpolation or a placeholder has no values, so it gets no call and stays on the no-database path.
5. Pick the service. When the allowlist names several, use the service that the user named, or ask which one to use. The module does not run `--check-services`: setup does.
6. For each picked statement, run `python3 <skill folder>/scripts/pg_run.py explain --repo <repo root> --service <name> --mode select` and read its JSON, as [db-access.md](db-access.md) says.
7. A call with `ok` false is named in one `Note:` line: `Note: the database call for <file>:<start_line>-<end_line> failed (<error>), so that statement has only static findings.` Write the redacted `message` in the line when it helps. Then go on with the static report.

The plan is not turned into findings here (a later ticket does it, see Plan findings): write no `PLAN-*` row. The `ok` plan changes no finding of the static rules.

Catalog facts (stub): ticket #400 fills this paragraph with the catalog facts of the `facts` action. It holds no behavior yet.

## Plan findings (stub)

Stub. Ticket #395 fills this section with the `PLAN-*` plan findings. It holds no behavior yet.

## Write path (stub)

Stub. Ticket #396 fills this section with the write path. It holds no behavior yet.

## Rewrite proof (stub)

Stub. Ticket #397 fills this section with the proof of a rewrite on a database. It holds no behavior yet.
