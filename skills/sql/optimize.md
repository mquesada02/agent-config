# Optimize module

`/sql optimize` reports the problems of the SQL that the user points at. The path with no database reads the SQL text and the repo files, writes a report, and waits for the user to approve. That path never connects to a database and does not use [db-access.md](db-access.md). The database path (the section Database path below) reads a real plan, and it does use [db-access.md](db-access.md).

## Steps

Run the engine step of the router for each file that the user points at. For SQL pasted in the message, run it once with no file. Steps 2 to 5 below run for each PostgreSQL file (the engine step gives `postgres`, also when no engine signal shows). A fallback file (any other engine) runs none of steps 2 to 5. It follows the section General part. Step 1 and step 6 apply to both kinds of file. When a run has both kinds, the reply is the general part first and then the PostgreSQL report in full, as the section General part says.

1. Take the repo rules: run the reader of the router's rules file step. A rule that is disabled with a reason is not checked. Name the other results as the `Note:` lines below.
2. Pick the source modules by the file form (the router's source module rule: for a JS/TS file, by the `source` of its statements). Run the extractor once and read its statements. Name each statement as `<file>:<start_line>-<end_line>`.
3. Apply every enabled rule of [dialects/postgres.md](dialects/postgres.md) (the `PG-*` rules) to each statement. For a postgres.js template, also apply the `PGJS-*` rules of [sources/postgres-js.md](sources/postgres-js.md). For a `pg` statement, also apply the `PGN-*` rules of [sources/pg.md](sources/pg.md). A `dynamic` statement gets only `PGN-01`: the `PG-*` rules and `PGN-02` to `PGN-06` skip it.
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

The final message is the report and nothing else. In a PostgreSQL report, write no text before the title line and no text after the Approve line. A general part (the section General part) has one line before its title, the fallback sentence, and a reply with both kinds of file has the general part before the PostgreSQL title. Write no summary, no list of the statements that you checked, and no prose between the parts. Put anything else that the user must know in a line that starts with `Note:`, placed after the summary line and before the first table.

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
- For a `pg` statement the places are the SQL text lines. For a statement that is a followed `const`, add the call line of each `calls` entry that fires the finding. A finding on the SQL text alone (a `PG-*` rule or `PGN-01`) lists every call line.
- A cell holds no new line. Write rewritten SQL on one line. Write a literal `|` in a cell as `\|`.
- A table row holds one finding. When the rule does not fire, it has no row, and the report does not mention it (a disabled rule is named only on the `Disabled rules:` line).
- Write each table line with a leading and a trailing `|`.
- One numbering runs through all tables: it starts at 1 in the first table, and the first row of the next table continues from the last number of the previous one, with no gap.

The Approve section holds one line, and it ends the message. With a finding it is exactly:

```
Reply with the findings to fix: `all`, `none`, a list such as `1,3,5`, or a range such as `1-12`.
```

With no finding it is exactly `There is nothing to approve.`

## General part

A fallback file (the engine step gives an engine other than `postgres`) gets the general part. The skill reads the file as text, runs no extractor and loads no source module (the router says so for every file form). It judges the lines that the user points at, else every SQL statement that it finds in the file. It applies every enabled `GEN-*` rule of [dialects/general.md](dialects/general.md) to each statement. A rule that a repo fact needs fires only when the repo shows the fact, as in step 4 of the steps (the repo files only: a fallback file has no catalog). A `GEN-*` rule that the rules file disables with a reason is not checked, and the disabled rules are listed as in the section Rules file results.

The general part has these parts, in this order:

1. Line 1: the fallback sentence of the router, exactly as the router gives it.
2. Line 2: the title `# sql optimize (general): <scope>`. The scope is the path of the file that the user named, or the words `the query`. In a reply with both kinds of file, each title names the files of its own part, separated by `, `.
3. The line `**Result: N critical, N required, N suggestions.**`. Each `N` is the row count of that severity. With no finding it is `**Result: 0 critical, 0 required, 0 suggestions.**`, with no table.
4. The line `Disabled rules: <ids>.`, only when a rule is disabled. It names the disabled `GEN-*` ids only.
5. Zero or more lines that start with `Note:`. A `Note:` line about the rules file as a whole (no rules file, an unknown id, a disabled id with no reason) appears once in the whole reply, in its first part.
6. One table for each severity that has a finding, in this order: `## Critical`, `## Required`, `## Suggestions`, each with the same header as the PostgreSQL report.
7. The last line: `The skill edits no file in general mode.`

The table rules of the section Report hold, with these changes:

- The Rule cell holds the `GEN-*` id and the Source of the rule in parentheses, as the module writes it: the entry name of its `## Sources` list or `skill rule`. For example `GEN-08 (SQLFluff)`, `GEN-11 (OWASP SQL Injection Prevention Cheat Sheet)` or `GEN-01 (skill rule)`. A rule id has at most one row in the whole general part.
- The Where cell holds one or more places separated by `, `. A place is `<path>:<line>` or `<path>:<line>-<line>`. When one rule fires in several files or at several lines, its one row lists every place. For SQL pasted in the message, the path is `query` and the line counts from 1 in the pasted SQL.
- The Fix cell gives advice in words. It never holds the capitalised word `Rewrite`.

The general part has no `## Approve` section, no rewrite, no Database path and no `PLAN-*` finding. The skill makes no database call for a fallback file and edits no file.

When a run has both kinds of file, the reply is the general part first, and then the PostgreSQL report in full. Each part has its own title and its own Result line. The PostgreSQL part starts at its own title line `# sql optimize: <scope>`, right after the last line of the general part. The only text before the PostgreSQL title is the general part.

The rule "no prose between the parts" of the section Report holds inside each part. The `Disabled rules:` line of each part names the disabled ids of its own rule family. `## Approve` is the last section of the reply. It covers the PostgreSQL findings only.

## Rewrites

A rewrite is a fix of a `PG-*` finding that replaces the SQL text of a statement. A fix of a `PGJS-*` or `PGN-*` finding repairs how the template or the call is composed, and is not a rewrite.

With no database, every rewrite is unproven. Write it in the Fix cell. The cell starts with the exact label `Rewrite (unproven: no database):`, then the rewritten SQL, then the words `database diff` (the proof that is missing, so the cell names it). For a proposed rewrite on a run with a database, follow the section Rewrite proof: it gives the other labels. The Fix cell of a finding that is not a rewrite never holds the capitalised word `Rewrite`. This holds for every `PGJS-*` and `PGN-*` finding and for a `PG-*` finding that gives advice with no replacement SQL.

## Approval

The skill edits no file before the user replies. After the reply, it edits only the findings that the reply chooses. A rewrite is applied only when the reply names its number, as a number in a list or inside a range. A reply of `all` does not cover a rewrite: name the unproven rows to the user and ask for their numbers.

## Database path

Load [db-access.md](db-access.md) when the run reaches this section. A plan comes only from `pg_run`, as that module says.

1. Run the allowlist reader: `python3 <skill folder>/scripts/allowlist.py <repo root>`. With `access` false, stay on the no-database path and write no extra line.
2. With `access` true and no service in `services`, stay on the no-database path.
3. With no rules file (the router's rules file reader prints `found` false), stay on the no-database path: make no connection.
4. Pick the statements: each `SELECT` or `WITH ... SELECT`, and each statement whose command is `INSERT`, `UPDATE`, `DELETE` or `MERGE` (also with a `WITH` list), that is complete SQL. A write statement has the same completeness rule, the same gates (the allowlist and the rules file) and the same `Note:` lines of step 7 as a `SELECT`. A `.sql` statement is complete. A template is complete when it has no `${...}` interpolation and no `$n` placeholder outside a string or a comment. A statement with an interpolation or a placeholder has no values, so it gets no plan call and stays on the no-database path (the catalog facts step below still reads its column facts). A `pg` statement follows the same completeness rule: a `$n` placeholder outside a string or a comment means no plan call and no rewrite proof, and the catalog facts step still reads its columns. A `dynamic` `pg` statement gets no plan call, no rewrite proof and no catalog facts: only the `PGN-01` check reads it.
5. Pick the service. When the allowlist names several, use the service that the user named, or ask which one to use. The module does not run `--check-services`: setup does.
6. For each picked statement, run one command: `python3 <skill folder>/scripts/pg_run.py explain --repo <repo root> --service <name> --mode select --statement '<sql>'` (use `--mode write` instead for a write statement), then a pipe (`|`), then `python3 <skill folder>/scripts/plan_findings.py -`. Write each single quote of the SQL as `'\''`. The plan goes from one script to the other: copy no plan, use no heredoc and no file. Read the JSON of `plan_findings.py` (it holds the plan too), as [db-access.md](db-access.md) says for the plan call.
7. A result with `ok` false is named in one `Note:` line. When `error` is `pg_run_failed`, the plan call failed: `Note: the database call for <file>:<start_line>-<end_line> failed (<source_error>), so that statement has only static findings.` Read the `source` object as [db-access.md](db-access.md) says for that `error` (its `reason`, `service` and redacted `message`), and write the `message` in the line when it helps. When `error` is `bad_input` (this also holds when the plan call printed nothing): `Note: the plan call or the plan findings call failed (bad_input), so that statement has only static findings.` When a tool hook denies the command (the SQL holds `<<` or a space followed by `#`), do not retry with a heredoc or a file: write `Note: the database call for <file>:<start_line>-<end_line> was denied by a tool hook (the SQL holds << or #), so that statement has only static findings.` Then go on with the static report.

An `ok` plan changes no finding of the static rules. A statement with a failed call gives no `PLAN-*` row.

Catalog facts: PG-02, PGJS-02 and PGN-06 need a fact that is not in the SQL text. After the gates of steps 1 to 3 and the service of step 5, read these facts from the catalog with the `facts` action.
- Collect the column names that these rules need from every statement of the run except a `dynamic` `pg` statement, also from a statement with an interpolation or a `$n` placeholder (`facts` runs no statement). A name is `table.column` or `schema.table.column`. Copy each part as the SQL writes it, with its quotes (`"Order".id`, `public."Order"."Id"`, `Order.id`); the script folds the case of an unquoted part and removes the quotes of a quoted part, so do not fold, unquote or re-quote a part yourself. Resolve each table alias to its table in the same statement: from the `FROM` or `JOIN` clause, from the `UPDATE <table>` target, or from the `INSERT INTO <table>` target (so `INSERT INTO t (col) VALUES (...)` gives `t.col`, and `UPDATE t SET col = ...` gives `t.col`). An unqualified column gets the table of the statement only when the statement has exactly one table. Do not send a name that you cannot build or resolve.
- When no name is left, make no `facts` call and write no `Note:` line for it. The repo-fact rule applies.
- Otherwise make one `pg_run.py facts` call for the run with all names: `python3 <skill folder>/scripts/pg_run.py facts --repo <repo root> --service <name> --names <name> [<name> ...]`. Read its JSON, as [db-access.md](db-access.md) says.
- PG-02: for a `NOT IN (subquery)`, the name is the column that the subquery selects. `nullable` true makes the rule fire. `nullable` false does not. Any other answer (`missing`, `null`, no name, a failed call) uses the repo-fact rule.
- PGJS-02 and PGN-06: the name is the column that the JS value is compared with or assigned to. A `type` that is exactly `date` makes the date fact true. The `Date` value fact still comes from the repo (a TypeScript type, `new Date(...)` or a `Date` variable). Any other answer (`missing`, another type such as `timestamp`, `date[]` or a domain over `date`, no name, a failed call) uses the repo-fact rule, so a `::date` cast in the SQL still counts there.
- A failed call is one line: `Note: the facts call failed (<error>), so the rules use only the facts that the repo shows.` Then go on with the static report.

## Plan findings

The `PLAN-*` rules are in the section Plan reading of [dialects/postgres.md](dialects/postgres.md). Apply them to each statement that got an `ok` plan from the Database path. The findings come from `plan_findings.py` (step 6 of the Database path), never from your own reading of the plan JSON. Use the `findings` list of its result:

1. A finding of a rule that the repo disables is dropped (the ids of the `Disabled rules:` line). The report holds no row of a disabled rule.
2. A rule id has at most one row in the report. When one plan has the finding at many nodes, or many statements have it, the one row covers all of them. The Where cell lists the place of each statement that has the finding.
3. A finding is a row of the severity that the rule entry gives. The Problem cell is one line. It holds one entry for each finding of that rule, in the order of the script output (statement order, then plan order), separated by `; `. An entry is `<place> <node>: <measured values> against <threshold values>`, taken from `measured` and `threshold`. The cell ends with one sentence that explains the cause. Use the node details of the plan in `plan` for the explanation.
4. The Fix cell proposes the fix in words (an index, an `ANALYZE`, a smaller select list, a filter earlier). It holds no replacement SQL and never the capitalised word `Rewrite`: a `PLAN-*` fix is advice, and a rewrite is proven as the section Rewrite proof says.
5. With `analyze` false, write the line `Note: the plan of <file>:<start_line>-<end_line> has no actual values, so no PLAN-* rule applies.` and no row. This also holds for a statement that ran as a plain `EXPLAIN` (a downgrade): a write statement, or a `SELECT` that calls a function that runs SQL from a string (`query_to_xml*`, `cursor_to_xml*`, `ts_stat`, `ts_rewrite`, `crosstab*`, `connectby`), a `SELECT` with a call that a stored object hides (a view body, a column default or a policy), or a `SELECT` that calls a VOLATILE user function. When the result has `ran` `explain`, write `Note: <file>:<start_line>-<end_line> ran as plain EXPLAIN: <reason>.` with the `reason` of the result, in either mode, in place of the first line, and no `PLAN-*` row.
6. A `PLAN-*` rule never fires without a database. A statement with no plan gets no `PLAN-*` row.

## Write path

A statement whose command is `INSERT`, `UPDATE`, `DELETE` or `MERGE` (also with a `WITH` list) uses `--mode write` in the call of the section Database path, piped into `plan_findings.py -` as for a `SELECT`. The same gates and the same completeness rule apply. The write run always rolls back, so the data is unchanged. Read these keys of the JSON of `plan_findings.py`:

- `ran` is `explain`: a user trigger, a rule, an external call, a call that a stored object hides or a VOLATILE user function made the run a plain `EXPLAIN`, so the plan has no actual values. Write `Note: <file>:<start_line>-<end_line> ran as plain EXPLAIN: <reason>.` with the `reason` of the result. Write no `PLAN-*` row (item 5 of the section Plan findings).
- `warnings` holds `sequence`: write `Note: <file>:<start_line>-<end_line> writes to a table with a sequence, so the analysis moved the sequence counter (a ROLLBACK does not undo it).`
- A statement that the guard refuses (`error` `pg_run_failed` with a `source_error` of `refused`) gets the `Note:` line of step 7 of the section Database path and only its static findings.

A rewrite of a write statement stays unproven: it gets no `diff` call and a label of the section Rewrite proof.

## Rewrite proof

A faster query must also be a correct one. This section proves a rewrite of a `SELECT` with the `diff` action of `pg_run` and the repo tests. Claude proposes the rewrite B of the statement A. This section only proves it.

1. A rewrite is proven only for a complete `SELECT` or `WITH ... SELECT` and an allowlisted service (the same gates as the section Database path: the allowlist, the rules file and the completeness rule). Make one call: `python3 <skill folder>/scripts/pg_run.py diff --repo <repo root> --service <name> --a='<A>' --b='<B>'`. Write each as `--a=<sql>`, one argument with an equals sign. Write each single quote of the SQL as `'\''`.
2. Read the result.
   - A result with `ok` false (`refused`, `not_allowed`, `connection_failed`, `statement_failed`, `psql_failed`, `bad_output`) gives the label `Rewrite (unproven: the database diff failed):` and a `Note:` line, as step 7 of the section Database path says. A call that a tool hook denies (the SQL of A or B holds `<<` or a space followed by `#`, so there is no JSON result) or that prints no JSON gets the same label and the hook `Note:` line of that step. Do not retry with a heredoc or a file.
   - `reason` `shape`, or `equal` false: the rewrite changes the result, so it is not offered. For `shape`, the `Note:` line names `column_names` of both sides. Otherwise it names `type_mismatch`, the counts of `only_a` and `only_b`, and `casts` and `floats`. A difference in a column named in `floats` is possibly a rounding difference: say so.
   - `order` `partial` makes the proof partial: the label names the reason (`ties`, `sort_keys` or `b_order`). `b_order` means that B has no top-level `ORDER BY`, or keys that do not resolve, or keys that differ from those of A: the rewrite may change the order of the rows.
   - `order` `checked` means that A has no ties and B has the same top-level `ORDER BY` keys as A (the proof checks it). It does not read the order that the server returns for B.
3. The repo tests, after an `equal` diff. Find the test command in the repo's own instructions (`CLAUDE.md` or `AGENTS.md`, read with the `Read` tool), else in the `test` script of `package.json`. Run it with at most 2 workers: add the limit that the runner takes (`--test-concurrency=2` for `node --test`, `--maxWorkers=2` for `jest`); when the declared command already sets a lower limit, add nothing. For any other runner, whose limit flag this module does not name, do not run the command (the limit of 2 workers would not hold): the rewrite is proven by the database diff only, item 4 applies, and the `Note:` line says `Note: the repo tests were not run: the limit of 2 workers cannot be set for <command>.` Run the command once, as declared plus the worker limit, with no pipe and no redirect. When the tests fail, the rewrite is not offered, and a `Note:` line names the failed command. When the tests pass, the `Note:` line quotes the passing test line of the runner output verbatim (for example `ok 1 - <test name>`).
4. No test command found: the rewrite is proven by the database diff only, with the warning `Note: no repo tests ran for <place>, so the rewrite is proven by the database diff only.`
5. A rewrite of a write statement (`INSERT`, `UPDATE`, `DELETE` or `MERGE`) is unproven: `diff` takes a `SELECT` only, so make no `diff` call for it.
6. A statement that is not complete SQL (a template or a `pg` statement with an interpolation or a `$n` placeholder; a `dynamic` `pg` statement is never rewritten) has no values to diff: its rewrite is unproven.
7. Labels. The Fix cell of a rewrite starts with exactly one of these labels, then the rewritten SQL on one line, and it holds the words `database diff` (in the label, or after the SQL):
   - `Rewrite (proven: database diff and repo tests):`
   - `Rewrite (proven by the database diff only: no repo tests ran):`
   - `Rewrite (partial proof by the database diff: order not checked, ties):` and `Rewrite (partial proof by the database diff: order not checked, sort keys):` and `Rewrite (partial proof by the database diff: order not checked, B order):` (a `Note:` line names the tests: they passed, or the warning of item 4)
   - `Rewrite (unproven: no database):` (with the words `database diff` after the SQL)
   - `Rewrite (unproven: the database diff failed):` (item 2)
   - `Rewrite (unproven: write statement, no database diff):`
   - `Rewrite (unproven: statement not complete, no database diff):`
8. Approval: a proven, partial or unproven rewrite is applied only when the user names its number, as the section Approval says. A reply of `all` covers no rewrite. The report has no new section: the `Note:` lines go in the place that the section Report gives.
