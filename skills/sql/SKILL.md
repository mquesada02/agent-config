---
name: sql
description: Use when writing or editing SQL (full rules for PostgreSQL in .sql files, postgres.js templates or pg strings; general advice for other engines), or when the user calls `/sql setup`, `/sql format` or `/sql optimize`. Setup writes the repo SQL rules file, format formats only the SQL the user points at, and optimize reports problems in a query.
---

# SQL

PostgreSQL is the only engine with full rules. For every other engine the skill gives general advice (the general fallback). The PostgreSQL source forms are `.sql` files, postgres.js tagged templates and plain strings that a `pg` receiver sends to `query()`. This file is the router: it reads the mode, loads the repo rules file and loads only the modules that the task needs.

## Modes

- `/sql setup`: load [setup.md](setup.md).
- `/sql format`: run the engine step for each target file, then load [format.md](format.md) and [style.md](style.md).
- `/sql optimize`: run the engine step for each file, then load [optimize.md](optimize.md). Load [db-access.md](db-access.md) only when the run reaches the `## Database path` section of `optimize.md`.

## No mode

If the user calls `/sql` with no mode, or with a mode that is not in the list above, ask which mode to run: `setup`, `format` or `optimize`. Do nothing else until the user answers. Never guess the mode, because a mode can change files or connect to a database.

## Model-invoked path

When this skill loads with no `/sql` call (you write or edit SQL yourself), run the engine step (the Engine step section gives the command) for the SQL you write. These call rules apply:

- You write or edit SQL in a file: one call with `--file <path>` for each file.
- The SQL is only in your reply, or in a file that does not exist yet: one call with no `--file`.
- Pass `--request` when the user's request names an engine.
- When `ask` is not null, ask the one question of the Engine step section.

Then apply only the style and the static rules to the SQL you write:

- Engine `postgres`: take the style from [style.md](style.md) and the static rules from [dialects/postgres.md](dialects/postgres.md). This works as today: the reply has no fallback sentence.
- Any other engine: take the style from [style.md](style.md), with the general style that the General part section of [format.md](format.md) gives, and the `GEN-*` rules from [dialects/general.md](dialects/general.md), in place of the PostgreSQL module.
  - Load the rules file with the reader script, as the Rules file section says, so that the `[style]` section and the disabled GEN ids reach you. Do not apply a GEN id that the rules file disables with a reason.
  - Run no extractor and load no source module.
  - The first line of the reply is the fallback sentence of the Engine step section. A reply with several fallback files has the fallback sentence once, with the `<Engine>` display names as that section says.
  - With no rules file, suggest `/sql setup` (step 2 of the Rules file section) in a plain sentence after the fallback sentence.
  - The reply has no title, no table and no `Note:` line: it is your normal reply. Name a GEN rule id only when you change the SQL because of it, or when you keep a construct that the rule warns about and say why.

These rules hold for every engine:

- Do not connect to a database.
- Do not run a formatter.
- Do not edit SQL outside your own change.

The database and rewrite steps need an explicit `/sql optimize`.

## Rules file

The repo rules live in `docs/agents/sql.md`. Load them with the reader script. The script needs Python 3.11 or newer (`tomllib`):

```
python3 <skill folder>/scripts/rules_file.py <repo root>
```

It prints one JSON object with the keys `found`, `settings`, `missing_sections`, `disabled_without_reason`, `unknown_ids` and `error`. Act on it in this order:

1. `error` is set: stop the skill. Show the parse error message and its line, and ask the user to fix the file.
2. `found` is false: there is no rules file. Every section falls back as in step 3, and you suggest `/sql setup` once. Format and optimize then run tag detection and formatter detection for that run only. This holds for PostgreSQL files only: a fallback file runs no tag detection and no formatter detection.
3. Each missing section falls back for that part only, and you name it once: `style` uses the repo majority, `formatter` uses detection, `sources` (the tags and the receivers) uses detection for that run, and `rules` means no disabled rules.
4. Each id in `disabled_without_reason` stays enabled, because it has no reason line (`- PG-10: <reason>` in the prose outside the TOML block). Name it once.
5. Each id in `unknown_ids` is ignored. Name it once.
6. A disabled id with a reason is not checked. List the disabled rules once in the report.

## Engine step

`/sql optimize` and `/sql format` run the engine step once for each file that they judge, before the router picks the modules of that file. The engine step is this command (`--file` is the target file, relative to the repo root or absolute):

```
python3 <skill folder>/scripts/detect_engine.py <repo root> --file <path> [--request <engine name>]
```

Pass `--request` only when the user's request names an engine, with the name as the user wrote it. For SQL that the user pastes in the message (no file), make one call with no `--file`. The script prints one JSON object with the keys `engine`, `signal`, `ask` and `evidence`. Act on it in this order:

1. `ask` is not null (`clash` or `no_signal`): ask one question, in one message, for that file only.
   - Name the evidence of the `evidence` list: driver names, scheme names, file paths and rules-file keys, and "your request" for a `request` entry.
   - Ask which engine the file uses.
   - A run with several such files asks one question for each of them.
   - The answer applies to that file (or to that run, for a call with no `--file`) in this run only. The skill writes it nowhere.
   - The answer `postgres` or `postgresql` (any case) means PostgreSQL. Any other answer is a fallback engine, and its name is lowercase.
2. `ask` is null: use `engine`. With no engine signal at all, `engine` is `postgres` and `signal` is `default`. So a PostgreSQL repo and a repo with no engine signal get the same report as before.

A file whose engine is `postgres` is a PostgreSQL file: load [dialects/postgres.md](dialects/postgres.md) and follow the source module rule below. A file with any other engine is a fallback file: load [dialects/general.md](dialects/general.md) in place of the PostgreSQL module. The first line of a fallback reply is the fallback sentence:

```
General guidance: this repo uses <Engine>, which the skill does not cover. The advice is general, with no database and no rule script.
```

`<Engine>` is the display name: `MySQL` for `mysql`, `SQLite` for `sqlite`, `SQL Server` for `sqlserver`, `Oracle` for `oracle`, and the lowercase engine name for any other name. When one run has several fallback engines, list them in order of first file, separated by `, ` and the last two by ` and `.

## Source module

The source module rule is for PostgreSQL files only. A fallback file skips it. Run no extractor on it (not `scripts/extract.py` for a JS/TS file) and load no source module. Read the file as text. Judge the lines that the user points at, else every SQL statement that you find in the file. This holds for every file form (`.sql`, JS/TS and any other form). So the "not supported" rule below applies to PostgreSQL files only.

When you are pointed at a PostgreSQL file to find its SQL (format, optimize, or a read of the SQL in a file), pick the source module by the file form. The extension is case-insensitive, as it is for `scripts/extract.py`.

- A file that ends in `.sql`: load [sources/sql-files.md](sources/sql-files.md).
- A file that ends in `.js`, `.mjs`, `.cjs`, `.jsx`, `.ts`, `.mts`, `.cts` or `.tsx`: run `scripts/extract.py` once, with `--tags` and `--receivers` from the rules file (leave an option out when its list is empty; the command is the same in both modules below, and the modules do not repeat the run). Read the `source` of each statement, then load the module that it needs: [sources/postgres-js.md](sources/postgres-js.md) when a statement has `source` `template`, [sources/pg.md](sources/pg.md) when a statement has `source` `pg` (a `dynamic` one too), and both when the file has both.
- Any other file form is not supported. Say so, and do not run the extractor on it.

The model-invoked path runs the engine step first (see the Model-invoked path section).

## Layers

A mode picks the source modules that a PostgreSQL file needs (a JS/TS file can load two source modules) and one dialect module for each file: the engine step decides which one. A later dialect or source form is one new module that this list names.

| Module | Load it when |
|---|---|
| [setup.md](setup.md) | `/sql setup` |
| [format.md](format.md) | `/sql format` |
| [optimize.md](optimize.md) | `/sql optimize` |
| [db-access.md](db-access.md) | `/sql optimize` needs a database |
| [style.md](style.md) | the style applies (format, or the model-invoked path) |
| `scripts/detect_engine.py` (the engine step) | `/sql optimize`, `/sql format` and the model-invoked path, once for each file: it decides the engine, and with a fallback engine the first line of the reply is the fallback sentence |
| [dialects/postgres.md](dialects/postgres.md) | the engine step gives `postgres` (the `PG-*` rules and plan reading) |
| [dialects/general.md](dialects/general.md) | the engine step gives any other engine (the `GEN-*` rules of the general fallback; the file is read as text, with no extractor and no source module) |
| [sources/sql-files.md](sources/sql-files.md) | the SQL is in a `.sql` file |
| [sources/postgres-js.md](sources/postgres-js.md) | the SQL is in a postgres.js template (the `PGJS-*` rules) |
| [sources/pg.md](sources/pg.md) | the SQL is in a plain string that a `pg` receiver sends to `query()` (the `dynamic` rule and the `PGN-*` rules) |
