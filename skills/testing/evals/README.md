# testing evals

Model evals for the skill. You run them by hand. They cost tokens and their results vary, so they are not in the repo test command (the deterministic tests are in `../tests/`).

## Run

Run this from the repo root. Put the results outside the repo (`--output-dir`), so they cannot be committed by accident:

```
claude plugin eval skills/testing --no-publish -j 2 --runs 3 --threshold 1.0 --scaffold --ablation with-without --trust-plugin --keep-temp --allow-tools "Bash(python3 *scripts/intake.py*)" "Bash(npx vitest*)" --output-dir <results folder> --json <results folder>/result.json
```

- `--no-publish` keeps the cases and the report private.
- `-j 2` keeps the CPU load low.
- `--scaffold` runs the `scaffold.sh` of each case. It copies `repo/` into the empty workspace.
- `--allow-tools` grants the shell calls of the review: the intake script and the fixture test run (the `approve-1` case runs the fixture tests; the fixtures hold no installed `vitest`, so that run reports `not run` or `fail` with the reason, and the grader accepts any stated result).
- `--keep-temp` keeps the trace of each run. Plugin eval prints the kept folders (`/tmp/claude-eval-*`, read-only). Remove them by hand when you are done.
- Add `--case <glob>` to run one case.

Then grade a saved final message with the report grader:

```
python3 skills/testing/scripts/grade_testing_report.py <report file>
```

## Cases

Each folder holds one case:

| File | Purpose |
|---|---|
| `prompt.md` | The prompt and the run limits. It never names the skill or a rule. |
| `case.yaml` | The case name and its `scaffold.sh`. The `approve-*` cases also name `history.jsonl`, a recorded report that the prompt replies to. |
| `scaffold.sh`, `repo/` | The synthetic fixture repo, copied into the workspace. |
| `expect.json` | `expect`: rule ids that must appear. `forbid`: rule ids that must not appear. |
| `graders/*.md` | The in-run graders (plugin eval has no custom-code graders). |

| Case | What it proves |
|---|---|
| `assert-01-no-assertion`, `assert-02-tautology`, `assert-03-nondeterministic-snapshot`, `run-01-hidden-retry` | Review finds the planted fault of each critical id, at the critical severity. |
| `disabled-no-reason` | A disabled id with no reason line is still checked, and the report says once that it has no reason line. |
| `disabled-with-reason` | A disabled id with a reason line is skipped and listed once; an unknown id is named once. |
| `no-rules-file` | The fallback line is written once and `/testing setup` is suggested once. |
| `malformed-rules-file` | The rules file error is named once with its line. |
| `no-files-in-scope` | Review asks which files to review and reports nothing. |
| `approve-1` | The reply `1` fixes row 1 only and runs the affected tests. |
| `approve-invalid` | The reply `1,all` edits nothing, runs nothing and names the invalid part. |

Not covered by a case in this ticket: the reply `none`, and a reply after a report with zero rows. The grammar text of `review.md` states them.
