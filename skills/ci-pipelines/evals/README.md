# ci-pipelines evals

Model evals for the skill. You run them by hand. They cost tokens and their results vary, so they are not in the repo test command (the deterministic tests are in `../tests/`).

## Run

Run this from the repo root. Put the results outside the repo (`--output-dir`), so they cannot be committed by accident:

```
claude plugin eval skills/ci-pipelines --no-publish -j 2 --runs 3 --threshold 1.0 --scaffold --ablation with-without --trust-plugin --keep-temp --allow-tools "Bash(python3 *scripts/intake.py*)" --output-dir <results folder> --json <results folder>/result.json
```

- `--no-publish` keeps the cases and the report private.
- `-j 2` keeps the CPU load low.
- `--runs 3` and `--threshold 1.0` are the plugin eval defaults, written here on purpose.
- `--scaffold` runs the `scaffold.sh` of each case. It copies `repo/` into the empty workspace. Pass it only for suites that you wrote.
- `--ablation with-without` adds the no-skill baseline arm (`W/OUT` and `Δ` columns).
- `--allow-tools` grants the one shell call of the review steps, the intake script. The pattern matches the path of the script in the skill folder that the run uses. The workspace is a temporary folder that is not inside a git repo (a parent repo with an `origin` would be read), and it has a temporary home and no GitHub credentials. The intake finds no GitHub remote, so `required_checks` is `unknown` and the review says "unreadable" (the `name-09-...` case expects this).
- `--keep-temp` keeps the trace of each run (`tracePath` in the result). The result JSON holds scores and grader verdicts but not the final message, so `grade_eval_results.py` reads the final message from the trace. Plugin eval prints the kept folders (`/tmp/claude-eval-*`, read-only). Remove them by hand when you are done.
- Add `--case <glob>` to run one case. Later tickets add cases to this same run.
- Plugin eval exits 1 when a case scores below the threshold. A bare skill folder is a valid target (it resolves as the plugin `ci-pipelines`), so no wrapper manifest is needed.

Then score the report contract and the rule ids with the two Python graders:

```
python3 skills/ci-pipelines/scripts/grade_eval_results.py <results folder>/result.json
```

## Cases

Each folder holds one case:

| File | Purpose |
|---|---|
| `prompt.md` | The prompt and the run limits. It never names the skill or a rule. |
| `case.yaml` | The case name and its `scaffold.sh`. |
| `scaffold.sh`, `repo/` | The synthetic fixture repo, copied into the workspace. |
| `expect.json` | `expect`: rule ids that must appear. `forbid`: rule ids that must not appear. |
| `graders/*.md` | The in-run graders (plugin eval has no custom-code graders). |

Review cases: `name-01-...` to `name-09-...` (one bad fixture for each naming rule), `graph-01-...` to `graph-07-...` and `maint-01-...` to `maint-03-...` (one bad fixture for each job graph and maintainability rule), `fx-sequential-quality`, `fx-suite-list`, `fx-duplicate-build`, `fx-inline-tests` and `clean` (it forbids every critical and required rule id). GRAPH-05 is a measured rule, and the eval sandbox has no run history, so it has two cases. `graph-05-shards-no-history` forbids GRAPH-05: with the sandbox's own unknown history, the review must give no shard finding. `graph-05-shards-with-history` expects GRAPH-05: its prompt gives the review a recorded intake output (`repo/intake.json`, the intake contract with `run_history` detected, a test job median of about 25 minutes, so 4 shards) and tells it not to run the intake script. `maint-03-copied-workflow` names two copies of the workflow in its prompt, because MAINT-03 applies only on request. Trigger case: `trigger-edit-workflow` asks for a workflow edit and does not name the skill.

Every fixture is synthetic. No text comes from a private repo.

## Graders

- `expect-<ID>.md` and `forbid-<ID>.md`: a `regex` grader that finds the id in the Rule cell of a table row. They are generated from `expect.json`, and a unit test keeps them in step.
- `section-*.md`: `regex` graders for the section markers of the report contract.
- `no-edit.md`, `no-write.md`, `no-shell-write.md`: `tool_used` graders with `min: 0` and `max: 0`. The skill must not edit a workflow before approval.
- `fix-quality.md`: an `llm` judge of the fix text. It is `arm: with-only`, so it is reported and not scored.
- `skill-fired.md` (trigger case): `tool_used: Skill`. Under `--ablation with-without` it is an indicator of the with-arm, not part of the score.
- `scripts/grade_eval_results.py`: runs `grade_report.py` and `grade_rule_ids.py` on the final message of each with-arm run of each review case. This is the scored check of the whole report contract.
