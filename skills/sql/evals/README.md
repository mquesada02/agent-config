# Eval run procedure

The model evals of the `sql` skill run by hand with `claude plugin eval`. They cost tokens, so they run only when you choose. They are not part of the repo test command (the declared command in `.claude/CLAUDE.md` runs the unit tests only).

## Layout

- One folder per case: `evals/<case>/` with `prompt.md` (or `case.yaml` with an inline prompt) and `graders/*.md`.
- Fixture repos live inside the case folder.
- Results go to `evals/results/<timestamp>/`. The folder is ignored by git.
- The target is the bare skill folder: `skills/sql`. No wrapper manifest and no `--eval-dir` are needed (answer to open question 1 on the general spec).

## Run

Run from the repo root. Every run uses `--no-publish`, `-j 2` (the CPU rule), `--runs 3` and `--threshold 1.0`.

A case that needs no database and no temp service files:

```
claude plugin eval skills/sql --no-publish -j 2 --runs 3 --threshold 1.0 --ablation none --allow-tools Bash
```

A case that needs the database or the temp service files adds `--scaffold`, because a case's `scaffold_script` runs only with that flag, and `--allow-tools Bash`, because Bash is a gated tool:

```
claude plugin eval skills/sql --no-publish -j 2 --runs 3 --threshold 1.0 --ablation none --scaffold --allow-tools Bash
```

The `opt-*` cases (the static optimize report) need `--scaffold`, and their score needs the traces. Add `--keep-temp`, `--output-dir` and `--json`, then run the grader commands on the result:

```
claude plugin eval skills/sql --no-publish -j 2 --runs 3 --threshold 1.0 --ablation none --scaffold --keep-temp --allow-tools Bash --output-dir <results folder> --json <results folder>/result.json
python3 skills/sql/graders/grade_eval_results.py <results folder>/result.json
```

A case that makes Claude edit files (every `format-*` case) also needs `Edit` and `Write`, because they are gated tools like `Bash`. Add `--trust-plugin` in a shell with no terminal:

```
claude plugin eval skills/sql --no-publish -j 2 --runs 3 --threshold 1.0 --ablation none --scaffold --allow-tools Bash Write Edit --trust-plugin --case <case>
```

Notes:

- `--ablation none` runs one arm. Under the default two-arm run, every `tool_used: Skill` grader is an indicator and is not part of the score, so the "skill fired" check would not count toward the threshold.
- Use `--case <glob>` to run one case.
- The first run in a directory asks to trust it. In a shell with no terminal, add `--trust-plugin`, only for this repo's own suite.
- A case may set only `EVAL_*` environment variables. A scaffold script cannot set `PGSERVICEFILE`, `PGPASSFILE` or `XDG_CONFIG_HOME` for the agent. It writes the temp service files at the default locations under the run's `HOME` (answer to open question 2 on the general spec). The hand-run driver (`evals/db/run_db_cases.py`, see "Database cases") does set those three variables, for a `claude -p` session that it starts itself.
- A case has one prompt. A reply that the case needs (approval, a setup confirmation) goes in that prompt.

## Cases

| Case | What it proves |
|---|---|
| `trigger-write-query` | A prompt that does not name the skill makes the skill fire, with no database connection and no formatter run (seam 4) |
| `extract-tag-not-sql` | Claude, pointed at a file whose postgres.js templates use the tags `db`, `this.db` and `tx` (not `sql`), runs the extractor and names each template with its line range and tag. Run it with `--scaffold`: its `scaffold_script` copies the fixture into the run's folder |
| `format-template-written-style` | No safe tool. `/sql format` on one template of a `.ts` file, with a rules file whose `[style]` is not the default: a `value` interpolation and a conditional fragment are kept, only the target changes, the style matches, the second run changes nothing (seam 4) |
| `format-sql-file-written-style` | No safe tool. `/sql format` on the middle statement of a `.sql` file, with the default style in the rules file |
| `format-keyword-position` | No safe tool. A template with a `${...}` before the first clause word gets the written style, and the `${...}` is never split |
| `format-no-rules-file` | No safe tool and no rules file. The default style applies, and the final message suggests `/sql setup` |
| `format-template-safe-tool` | A safe tool. `/sql format` on one template of a `.ts` file in a repo with the Prettier chain (`prettier`, `prettier-plugin-embed`, `prettier-plugin-sql`, `language` `postgresql`): the detector picks `prettier-plugin-embed`, the runner formats only the target, and a `value` interpolation and a conditional fragment survive. The scaffold runs `npm ci` in the run folder |
| `format-sql-file-safe-tool` | A safe tool. `/sql format` on the middle statement of a `.sql` file in a repo with `prettier-plugin-sql` in its Prettier config: the detector picks `prettier-plugin-sql` (form `sql`) and the runner formats only the target. The scaffold runs `npm ci` in the run folder |
| `format-tag-outside-embedded-tags` | A tag outside `embeddedSqlTags`. The repo has the Prettier chain, but its `embeddedSqlTags` option covers only `sql` and the templates use `db`. The written style does the work, the report names the gap, and the runner does not run |

## Safe tool cases

The three cases `format-template-safe-tool`, `format-sql-file-safe-tool` and `format-tag-outside-embedded-tags` need a real formatter. Their scaffold copies the fixture and runs `npm ci` in the run's working folder, with the npm cache in that folder (`--cache "$PWD/.npm-cache"`). The packages are pinned in the fixture's `package.json` and `package-lock.json`. Nothing is installed globally or in the real HOME, and the scaffold needs network access to the npm registry. The eval shell of Claude is read-only for Bash in the working folder (a probe of the eval shell showed that writes there fail, and the system temp folder is writable). So `scripts/run_formatter.py` writes its `--output` file in the temp folder, and the case writes the target file with the Write tool (the prompts ask for `first-run.<ext>` the same way). The `llm` graders read only the final message, so each prompt asks Claude to show the whole file and to name the formatter in it.

Each case has the `tool_used` graders `no-connection.md` and `no-raw-formatter.md` (no Bash call starts a formatter by hand), and `runner-ran.md` (the first two cases: at least one call of `run_formatter.py`) or `runner-not-run.md` (the tag case: none).

## Format cases: the grader commands

The `format-*` cases have each an `expected.json` (`file`, `target`, `style`, `tags`) and the fixture. The prompt asks Claude to run the format twice, to copy the file to `first-run.<ext>` after the first run (with the Write tool: the eval sandbox blocks writes from Bash), and to show the whole file after the first run in the final message. The `llm` graders read only that final message. `claude plugin eval` has no grader type that runs a command, so the `llm` graders of each case state the same checks as the three commands in `skills/sql/graders/`. Run the commands by hand on the output of a run kept with `--keep-temp` (the scaffold folder, with the fixture file and `first-run.<ext>`):

```
python3 skills/sql/graders/interpolations_same.py <fixture file> <first-run file> [--tags <tags>]
python3 skills/sql/graders/only_target_changes.py <fixture file> <first-run file> --target <target>
python3 skills/sql/graders/style_matches.py <first-run file> <file after the second run> --style <style json file> --target <start>-<end> [--tags <tags>]
```

- `<fixture file>` is the fixture of the case. `<target>` and the style come from `expected.json`. Write its `style` object to a JSON file for `--style`. `--tags` is the `tags` list joined by commas, left out when the list is empty.
- The range of the third command starts at the start of `target`. Its end is `L1 - (L0 - end)`, where `end` is the end of `target`, `L0` is the line count of the fixture file and `L1` is the line count of `first-run.<ext>`. This holds when only the target changed, which the second command checks.

The `opt-*` cases run `/sql optimize <file>` with no database. Each has `case.yaml`, `scaffold.sh` (it copies `repo/` into the run's folder), `repo/`, `expect.json` (the `expect` and `forbid` rule ids, and an optional `disabled` list) and `graders/`. The `expect-<ID>.md` and `forbid-<ID>.md` regex graders check the Rule column of the report. Four `tool_used` graders (`no-connection.md`, `no-edit.md`, `no-write.md`, `no-shell-write.md`) check that the run makes no connection and changes no file. Their prompts give no reply, so the post-reply approval rule is checked as text of `optimize.md`.

| Case | What it proves |
|---|---|
| `opt-pgjs-01` to `opt-pgjs-04` | One case for each `PGJS-*` rule: the report holds the rule id |
| `opt-pg-01` to `opt-pg-10` | One case for each `PG-*` rule: the report holds the rule id |
| `opt-nullability-unknown` | A `NOT IN` over a column whose nullability the repo does not show: the report has no `PG-02` row |
| `opt-date-unknown` | A `Date` where the repo shows no `date` parameter: the report has no `PGJS-02` row |
| `opt-clean` | A clean query set: the report holds no critical and no required rule id |
| `opt-disabled-rule` | `PG-10` is disabled (TOML entry and reason line): the report lists it once and holds no row of it |
| `opt-rewrite-unproven` | A rewrite with no database: the report calls it unproven and names the missing database diff |
| `opt-no-rules-file` | No rules file: a `Note:` line suggests `/sql setup`, and the run makes no connection |

The graders live in `skills/sql/graders/`. Each one takes a report (or a trace) as a path, or `-` for standard input:

- `grade_rule_ids.py REPORT [--expect ID...] [--forbid ID...]` (E): the rule ids in the Rule column.
- `grade_no_change.py TRACE` (F): no file change in the trace of a run.
- `grade_report.py REPORT [--disabled ID...]` (I): the layout of the report.
- `grade_eval_results.py RESULT.json [--evals DIR]`: applies E, F and I to every run of every case that has an `expect.json`.
- `grade_db_unchanged.py BEFORE AFTER [--sequences-may-differ]` (G), `grade_refusals.py TRACE --expect KIND[:ARG]...` (H) and `grade_leak_scan.py TRACE --canaries FILE`: see "Database cases".
- `grade_db_eval_results.py RESULT.json [--evals DIR] [--canaries FILE]`: applies H and the leak scan to every run of every case that has a `db-expect.json`.

## Database cases

A probe of `claude plugin eval` (2026-11-10) showed that the shell of the model has no network, no DNS and no Unix socket (`socket()` gives `EPERM`), and a private `/tmp`. It cannot reach a database. So the database proof has two layers. Every DB case, in both layers, must pass grader G and the leak scan.

1. **Plugin eval cases** for what needs no database: `db-off-allowlist` (a service that the allowlist does not name gets no connection: `no_connection:other-db`), `db-bypass-refused` (a `set_config` call that switches the read-only mode off is refused by the guard: `refused:forbidden_function`) and `db-connection-fails` (the connection fails in the sandbox: `connection_failed:app-wronghost`). Their `scaffold.sh` runs `evals/db/db_eval.py scaffold`, which writes the service file, the password file and the allowlist at the default paths under the run's `HOME` (canary values, port 5432, no container). Run them inside `db_eval.py around`, which starts the two Docker databases, takes the snapshots, runs the command, takes the snapshots again, runs G and always removes the containers:

```
python3 skills/sql/evals/db/db_eval.py around --state <absolute temp folder> -- claude plugin eval skills/sql --no-publish -j 2 --runs 3 --threshold 1.0 --ablation none --scaffold --allow-tools Bash --keep-temp --case 'db-*' --output-dir <results folder> --json <results folder>/result.json
python3 skills/sql/graders/grade_db_eval_results.py <results folder>/result.json
```

2. **The hand-run driver** for what needs the real database. `python3 skills/sql/evals/db/run_db_cases.py [--case GLOB] [--runs N] [--out FOLDER] [--max-budget-usd USD]` starts the two databases, and for each case under `evals/db/cases/` and each run it copies the case repo, runs `claude -p` (Sonnet) with `PGSERVICEFILE`, `PGPASSFILE` and `XDG_CONFIG_HOME` in a temp state folder, saves the transcript, then runs H, the leak scan and G. The session gets `--setting-sources ""`, no CLAUDE.md, no MCP server, and the tools `Skill`, `Read` and `Bash` for `python3` on five scripts of the skill only (`rules_file.py`, `extract.py`, `allowlist.py`, `pg_run.py`, `plan_findings.py`; #377 amendment 3), and, for a case with a `bash` key, the exact full commands of that key (see `db-expect.json` below). The `claude` login comes from the real `HOME`; the driver writes nothing there. It needs `docker` and `psql` on `PATH` (the wrapper runs `psql` on the host).

| Case | What it proves |
|---|---|
| `db-off-allowlist` | A service off the allowlist gets no connection and the final message names the allowlisted services |
| `db-bypass-refused` | A read-only bypass statement is refused by the guard and runs no change |
| `db-connection-fails` | A failed connection is reported with no host, user or database name |
| `plan-select` (driver) | `/sql optimize` on a `SELECT` gets a plan from `pg_run explain` on PostgreSQL 13 and 18 |
| `facts-pg-02` (driver) | `/sql optimize` reads the nullability of a column that the repo does not define from `pg_run facts` on PostgreSQL 13 and 18, and the report has a `PG-02` row (grader E, grader H kind `facts`, grader G and the leak scan) |
| `write-analyze` (driver) | `/sql optimize` on an `UPDATE` of `shop.orders` pipes `pg_run explain --mode write` into `plan_findings.py` on PostgreSQL 13 and 18: grader H kind `analyzed` (an `ANALYZE` run with a plan), grader G (the tables are unchanged) and the leak scan |
| `write-sequence` (driver) | The same for an `INSERT` into `shop.notes` (a serial id): grader H kinds `analyzed` and `sequence_warning`. `sequences_may_differ` is true: this is the only case where grader G lets the sequence values differ, and the table checksums must still match |
| `write-dblink-trigger` (driver) | The same for an `UPDATE` of `shop.hooked`, whose row trigger calls a `dblink` function: grader H kind `downgraded` (a plain `EXPLAIN` with a reason, so the function never runs), grader G and the leak scan |
| `rewrite-proven` (driver) | `/sql optimize` proves a rewrite of a `SELECT` (PG-09) with one `pg_run diff` call on each service and then runs the repo tests: the fixture has an `AGENTS.md` with `node --test`, a `test/query.test.js` whose test title is `rewrite-proof-ok`, and the case allows exactly `node --test --test-concurrency=2`. Grader H kind `diff`, the `final` key (the label `Rewrite (proven: database diff and repo tests):` and `rewrite-proof-ok` are in the final message, and `Rewrite (unproven` is not), grader G and the leak scan |
| `rewrite-write-unproven` (driver) | A rewrite of an `UPDATE` (PG-05) is unproven (story 61): no `diff` call, and the final message has the label `Rewrite (unproven: write statement, no database diff):`. Grader H kind `analyzed` (the write path runs), the `final` key, grader G (the data is unchanged) and the leak scan. The rewrite with no database is covered by the plugin eval case `opt-rewrite-unproven` |
| `rewrite-no-tests` (driver) | A repo with no test command gives a diff-only proof: grader H kind `diff` and the label `Rewrite (proven by the database diff only: no repo tests ran):` with the words `no repo tests ran` (the `final` key), grader G and the leak scan |
| `plan-01-estimate`, `plan-02-seq-scan`, `plan-03-spill`, `plan-04-nested-loop`, `plan-05-cache` (driver) | `/sql optimize` pipes the plan call into `plan_findings.py` on PostgreSQL 13 and 18, and the report has the `PLAN-01` to `PLAN-05` row of the case (the queries read `shop.events`, a 30000-row table larger than the `shared_buffers=2MB` of the test servers). Grader E, grader I (report layout), grader H kind `plan`, grader G and the leak scan grade them. The LLM judge scores the explanation and the fix text against `db/rubric-plan.md`; its `JUDGE` line is reported, not scored |
| `plan-clean` (driver) | A point lookup of one customer gives no `PLAN-*` row: the case forbids the five ids (grader E) and checks the report layout (grader I). It has no `judge` key, because it has no explanation to score |
| `plan-disabled` (driver) | `PLAN-02` is disabled with a reason line in the rules file: no `PLAN-02` row, and the `Disabled rules:` line is exactly `PLAN-02` (grader I with `--disabled`) |
| `bad-password` (driver) | A real bad password gives `connection_failed` and no canary in the transcript |
| `wrong-host` (driver) | A real address with no listener gives `connection_failed` and no canary in the transcript |

Graders:

- G, `grade_db_unchanged.py`: compares the table checksums (and the sequence values, unless `--sequences-may-differ`) of two snapshots.
- H, `grade_refusals.py`: reads the `pg_run` results of a trace. Kinds: `not_allowed[:SERVICE]`, `refused[:REASON]`, `connection_failed[:SERVICE]`, `plan[:SERVICE]`, `facts[:SERVICE]` (an `ok` result with a non-empty `facts` object), `analyzed[:SERVICE]` (`ok`, a non-empty `plan` and `ran` `analyze`), `sequence_warning[:SERVICE]` (`ok` and `warnings` holds `sequence`), `downgraded[:SERVICE]` (`ok`, `ran` `explain`, a non-empty `reason` and a non-empty `plan`), `diff[:SERVICE]` (`ok` and `equal` is a boolean: the output of `pg_run diff`, read directly), `no_connection:SERVICE`. The three write kinds read the first `{"ok":` object of the tool result, which on the piped call is the output of `plan_findings.py` with the passed-through keys `ran`, `reason`, `downgrade` and `warnings`. It also fails a run in which a Bash call starts `psql`, `pg_dump`, `pg_isready`, `pgcli`, `createdb`, `dropdb` or `docker`.
- The leak scan, `grade_leak_scan.py`: fails when a canary value is anywhere in the trace, and names only the canary key.

`db-expect.json` holds the `expect` list of H kinds and the optional keys `sequences_may_differ` and `rules` (an object with the lists `expect` and `forbid` of rule ids: the driver grades the final message of the run with grader E, `grade_rule_ids.py`; the plugin eval scorer `grade_db_eval_results.py` ignores `rules`). The key `bash` (a list of exact full commands that the case may run in addition to the global tools: the driver adds each as an exact rule `Bash(<command>)`, so the same command with an added argument is refused) and the key `final` (an object with the lists `contains` and `absent` of literal strings that must or must not be in the final message; a failure is `FAIL <case>#<n> final: missing "<string>"` or `... unexpected "<string>"`) are read by the driver only; a malformed `bash` or `final` is a message on stderr and exit code 2 before anything starts. The keys `report` (true: grader I, `grade_report.py`, on the final message), `disabled` (rule ids, passed to grader I as `--disabled`) and `judge` (the file name of a rubric in `db/`, for example `rubric-plan.md`: one `claude -p` call with no tools scores the explanation and the fix text, and the driver prints `JUDGE <case>#<n>: <score>/5 <reason>`, or `not scored (<reason>)`; a `JUDGE` line never changes a PASS or FAIL line or the exit code) are read by the driver only. The graders take their expectations from the command line, so a later ticket adds a case with no grader change, unless it needs a new H kind (a new `pg_run` result kind needs one: #396 added `analyzed`, `sequence_warning` and `downgraded`, and #397 added `diff`). `db/canaries.json` holds fixed synthetic values (password, wrong password, user, database, three host names). They appear only in generated files, never in a committed fixture, prompt or module text. The driver cases have no `case.yaml`, `prompt.md` or `graders/` folder, so `claude plugin eval` does not find them. Docker rules: `docker run --rm`, a unique container name, `docker rm -fv` in a `finally` block, no named volume, no `docker ... prune`. Check with `docker ps -a` and `docker volume ls -f dangling=true` after a run.

## Setup cases

The `setup-*` cases run `/sql setup`. Each has `case.yaml`, `scaffold.sh`, `repo/`, `expected.json` (the `--expect` file of grader D) and `graders/`. Each prompt holds the replies, because a case has one user turn. Run them with `--keep-temp`, `--output-dir` and `--json` so that each run has a `tracePath`:

```
claude plugin eval skills/sql --no-publish -j 2 --runs 3 --threshold 1.0 --ablation none --scaffold --keep-temp --allow-tools Bash Write Edit --trust-plugin --case 'setup-*' --output-dir <results folder> --json <results folder>/result.json
```

Grader D (`graders/grade_setup.py TRACE --repo <folder> --expect <expected.json> [--allowlist <file> --key <repo key>]`) runs by hand on each kept run: the trace is `tracePath`; the kept run folder is `<kept folder>/home/cwd` (the repo) and the run HOME is `<kept folder>/home` (open it with the `chmod` that the eval prints). The allowlist is `<run HOME>/.config/sql-skill/allowlist.toml` and the key is `example.com/acme/shop`. In a plugin eval the Bash tool is read-only, so `setup_files.py write` gives `write_failed` and the Write fallback of `setup.md` writes the files. The Write tool is denied for a new allowlist file outside the run folder (amendment 4 on #377), so `setup-tags-fixture` has no `services` key; a flow test in `tests/test_sql_setup_evals.py` passes D with `services` for it.

| Case | What it proves |
|---|---|
| `setup-tags-fixture` | Tags `sql`, `this.sql` and `tx` are detected and stored; three pitfall candidates, one kept; the diff is shown before the write |
| `setup-no-sql` | A repo with no SQL: default style, empty tags, no allowlist, no detector run |
| `setup-rerun` | A re-run asks per changed key, keeps the hand-written comment and rule, appends the new rule |

## Fixture rules

- Every fixture is synthetic. No fixture copies code from the private inspiration repo, and no file names it.
- No fixture under the skill folder has a file named `test_*.py`. Fixture repos are JavaScript or TypeScript projects, and their own tests use `*.test.js` or `*.test.ts`. A `test_*.py` file under the skill folder would add a folder to the repo coverage test.
- Each fixture repo has its own `docs/agents/sql.md` when its case needs one.
- No case relies on this repo's own `docs/agents/` files.
