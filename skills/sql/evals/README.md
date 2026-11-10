# Eval run procedure

The model evals of the `sql` skill run by hand with `claude plugin eval`. They cost tokens, so they run only when you choose. They are not part of the repo test command (the declared command in `.claude/CLAUDE.md` runs the unit tests only).

## Layout

- One folder per case: `evals/<case>/` with `prompt.md` (or `case.yaml`) and `graders/*.md`.
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

A case that makes Claude edit files (the four `format-*` cases) also needs `Edit` and `Write`, because they are gated tools like `Bash`. Add `--trust-plugin` in a shell with no terminal:

```
claude plugin eval skills/sql --no-publish -j 2 --runs 3 --threshold 1.0 --ablation none --scaffold --allow-tools Bash Write Edit --trust-plugin --case <case>
```

Notes:

- `--ablation none` runs one arm. Under the default two-arm run, every `tool_used: Skill` grader is an indicator and is not part of the score, so the "skill fired" check would not count toward the threshold.
- Use `--case <glob>` to run one case.
- The first run in a directory asks to trust it. In a shell with no terminal, add `--trust-plugin`, only for this repo's own suite.
- A case may set only `EVAL_*` environment variables. A scaffold script cannot set `PGSERVICEFILE`, `PGPASSFILE` or `XDG_CONFIG_HOME` for the agent. It writes the temp service files at the default locations under the run's `HOME` (answer to open question 2 on the general spec).
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

## Format cases: the grader commands

The four `format-*` cases have each an `expected.json` (`file`, `target`, `style`, `tags`) and the fixture. The prompt asks Claude to run the format twice, to copy the file to `first-run.<ext>` after the first run (with the Write tool: the eval sandbox blocks writes from Bash), and to show the whole file after the first run in the final message. The `llm` graders read only that final message. `claude plugin eval` has no grader type that runs a command, so the `llm` graders of each case state the same checks as the three commands in `skills/sql/graders/`. Run the commands by hand on the output of a run kept with `--keep-temp` (the scaffold folder, with the fixture file and `first-run.<ext>`):

```
python3 skills/sql/graders/interpolations_same.py <fixture file> <first-run file> [--tags <tags>]
python3 skills/sql/graders/only_target_changes.py <fixture file> <first-run file> --target <target>
python3 skills/sql/graders/style_matches.py <first-run file> <file after the second run> --style <style json file> --target <start>-<end> [--tags <tags>]
```

- `<fixture file>` is the fixture of the case. `<target>` and the style come from `expected.json`. Write its `style` object to a JSON file for `--style`. `--tags` is the `tags` list joined by commas, left out when the list is empty.
- The range of the third command starts at the start of `target`. Its end is `L1 - (L0 - end)`, where `end` is the end of `target`, `L0` is the line count of the fixture file and `L1` is the line count of `first-run.<ext>`. This holds when only the target changed, which the second command checks.

## Fixture rules

- Every fixture is synthetic. No fixture copies code from the private inspiration repo, and no file names it.
- No fixture under the skill folder has a file named `test_*.py`. Fixture repos are JavaScript or TypeScript projects, and their own tests use `*.test.js` or `*.test.ts`. A `test_*.py` file under the skill folder would add a folder to the repo coverage test.
- Each fixture repo has its own `docs/agents/sql.md` when its case needs one.
- No case relies on this repo's own `docs/agents/` files.
