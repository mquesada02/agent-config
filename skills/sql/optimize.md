# Optimize module

`/sql optimize` reports the problems of the SQL that the user points at. This module holds the path with no database: it reads the SQL text and the repo files, writes a report, and waits for the user to approve. It never connects to a database, and the module [db-access.md](db-access.md) is not used on this path.

## Steps

1. Take the repo rules: run the reader of the router's rules file step. A rule that is disabled with a reason is not checked. Name the other results as the `Note:` lines below.
2. Pick the source module by the file form (the router's source module rule). Run its extractor and read its statements. Name each statement as `<file>:<start_line>-<end_line>`.
3. Apply every enabled rule of [dialects/postgres.md](dialects/postgres.md) (the `PG-*` rules) to each statement. For a postgres.js template, also apply the `PGJS-*` rules of [sources/postgres-js.md](sources/postgres-js.md).
4. A rule that needs a fact fires only when the repo shows the fact. Read the repo files for it (a schema file, a migration, a type). When the repo does not show the fact, the rule does not fire.
5. Write the report as the final message, as described below. Then stop.

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

## Database path (stub)

Stub. Tickets #394 (the database allowlist and the connection) and #400 (the catalog facts) fill this section. It holds no behavior yet.

## Plan findings (stub)

Stub. Ticket #395 fills this section with the `PLAN-*` plan findings. It holds no behavior yet.

## Write path (stub)

Stub. Ticket #396 fills this section with the write path. It holds no behavior yet.

## Rewrite proof (stub)

Stub. Ticket #397 fills this section with the proof of a rewrite on a database. It holds no behavior yet.
