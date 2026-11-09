---
name: sql
description: Use when writing or editing SQL (PostgreSQL in .sql files or postgres.js templates), or when the user calls `/sql setup`, `/sql format` or `/sql optimize`. Setup writes the repo SQL rules file, format formats only the SQL the user points at, and optimize reports problems in a query.
---

# SQL

PostgreSQL is the only dialect. The source forms are `.sql` files and postgres.js tagged templates. This file is the router: it reads the mode, loads the repo rules file and loads only the modules that the task needs.

## Modes

- `/sql setup`: load [setup.md](setup.md).
- `/sql format`: load [format.md](format.md) and [style.md](style.md).
- `/sql optimize`: load [optimize.md](optimize.md) and [db-access.md](db-access.md).

## No mode

If the user calls `/sql` with no mode, or with a mode that is not in the list above, ask which mode to run: `setup`, `format` or `optimize`. Do nothing else until the user answers. Never guess the mode, because a mode can change files or connect to a database.

## Model-invoked path

When this skill loads with no `/sql` call (you write or edit SQL yourself), apply only the style and the static rules to the SQL you write. Take the style from [style.md](style.md) and the static rules from the dialect module.

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
2. `found` is false: there is no rules file. Every section falls back as in step 3, and you suggest `/sql setup` once. Format and optimize then run tag detection and formatter detection for that run only.
3. Each missing section falls back for that part only, and you name it once: `style` uses the repo majority, `formatter` uses detection, `sources` (the tags) uses detection for that run, and `rules` means no disabled rules.
4. Each id in `disabled_without_reason` stays enabled, because it has no reason line (`- PG-10: <reason>` in the prose outside the TOML block). Name it once.
5. Each id in `unknown_ids` is ignored. Name it once.
6. A disabled id with a reason is not checked. List the disabled rules once in the report.

## Layers

A mode picks one source module and one dialect module. A later dialect or source form is one new module that this list names.

| Module | Load it when |
|---|---|
| [setup.md](setup.md) | `/sql setup` |
| [format.md](format.md) | `/sql format` |
| [optimize.md](optimize.md) | `/sql optimize` |
| [db-access.md](db-access.md) | `/sql optimize` needs a database |
| [style.md](style.md) | the style applies (format, or the model-invoked path) |
| [dialects/postgres.md](dialects/postgres.md) | the SQL is PostgreSQL (the `PG-*` rules and plan reading) |
| [sources/sql-files.md](sources/sql-files.md) | the SQL is in a `.sql` file |
| [sources/postgres-js.md](sources/postgres-js.md) | the SQL is in a postgres.js template (the `PGJS-*` rules) |
