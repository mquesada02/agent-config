# testing evals

Model evals for the skill. You run them by hand. They cost tokens and their results vary, so they are not in the repo test command (the deterministic tests are in `../tests/`).

## Run

Run this from the repo root. Put the results outside the repo (`--output-dir`), so they cannot be committed by accident:

```
claude plugin eval skills/testing --no-publish -j 2 --runs 3 --threshold 1.0 --scaffold --ablation with-without --trust-plugin --keep-temp --allow-tools "Bash(python3 *scripts/intake.py*)" "Bash(npx vitest*)" "Bash(CI=true npx vitest*)" "Bash(node --test*)" "Bash(CI=true node --test*)" "Bash(git status*)" "Bash(git rev-parse*)" --output-dir <results folder> --json <results folder>/result.json
```

- `--no-publish` keeps the cases and the report private.
- `-j 2` keeps the CPU load low.
- `--scaffold` runs the `scaffold.sh` of each case. It copies `repo/` into the empty workspace.
- `--allow-tools` grants the shell calls of the review: the intake script, the fixture test run and the timed run of `RUN-04` with its `git status --porcelain` calls. The `approve-1` case runs the fixture tests. The older fixtures hold no installed `vitest`. Their runs report `not run`, `fail` or a `Not checked:` entry for `RUN-04` with the reason. No in-run grader of those cases rejects that entry. The new fixtures use the Node built-in runner (`node --test`), which needs no install, and their scaffold runs `git init`.
- `--keep-temp` keeps the trace of each run. Plugin eval prints the kept folders (`/tmp/claude-eval-*`, read-only). Move them to a dated backup folder under `/tmp` when you are done. Never delete them recursively.
- Add `--case <glob>` to run one case.

Grade a setup case on the kept workspace (the folder that the run used as the repo root). For `setup-rerun` add `--before skills/testing/evals/setup-rerun/repo/docs/agents/testing.md`:

```
python3 skills/testing/scripts/grade_testing_setup.py --repo <kept workspace> --expect skills/testing/evals/<case>/expect-setup.json [--before <rules file as it was before the run>]
```

The first acceptance criterion of the setup ticket ("no missing section") means "no missing section except the expected gap": a `commands.<language>` entry for a language whose test command detection cannot find. The setup fixtures all have a detected test command, so no case hits the gap. Pass the gap to the grader with `allow_missing` when you add such a case.

Then grade a saved final message with the report grader:

```
python3 skills/testing/scripts/grade_testing_report.py <report file>
```

## Cases

Each folder holds one case:

| File | Purpose |
|---|---|
| `prompt.md` | The prompt and the run limits. It never names the skill. The review prompts never name a rule. The setup prompts give rule ids (the interview answers), and the `allowed_tools` of their front matter include `Write` and `Edit` (the `--allow-tools` list of the run command holds Bash patterns only). |
| `case.yaml` | The case name and its `scaffold.sh`. The `approve-*` cases also name `history.jsonl`, a recorded report that the prompt replies to. |
| `scaffold.sh`, `repo/` | The synthetic fixture repo, copied into the workspace. |
| `expect.json` | `expect`: rule ids that must appear. `forbid`: rule ids that must not appear. The setup cases hold two empty lists. |
| `expect-setup.json` | Setup cases only. The expectation of `grade_testing_setup.py`, with the keys `set`, `unset`, `allow_missing`, `contains` and `absent`. |
| `graders/*.md` | The in-run graders (plugin eval has no custom-code graders). |

| Case | What it proves |
|---|---|
| `assert-01-no-assertion`, `assert-02-tautology`, `assert-03-nondeterministic-snapshot`, `run-01-hidden-retry` | Review finds the planted fault of each critical id, at the critical severity. |
| `run-02-real-sleep`, `run-03-real-network`, `run-04-slow-small-test`, `run-05-ignored-no-reason`, `par-01-fixed-port`, `par-02-shared-state`, `grp-01-unselected-test`, `grp-01-small-group-io`, `dbl-01-call-order` | Review finds the planted fault of each runnable id. `grp-01-unselected-test` and `grp-01-small-group-io` are the two cases of `GRP-01`. One fault can fire more than one id (a sleep in a small group fires `RUN-02` and `GRP-01`): the case lists in `expect.json` only its planted id. |
| `run-03-medium-loopback` | A medium-group test that connects to loopback gives no `RUN-03` row. |
| `size-smallest-wins` | A slow test case that a small group and a large group both select counts as small, so `RUN-04` finds it. |
| `unreadable-selector` | A group command that is a wrapper script is unreadable: one `Not checked:` entry for the group and no `GRP-01` finding. |
| `run-04-not-checked` | A test command with a snapshot update flag gives `ASSERT-03` and the entry `RUN-04 (command includes an update mode)`, and no timed run. |
| `no-groups` | A rules file with no `[[groups]]` gives exactly one `Not checked: GRP-01, RUN-03, RUN-04 (...)` line and no row for those ids. Note line (d) may also appear. |
| `disabled-no-reason` | A disabled id with no reason line is still checked, and the report says once that it has no reason line. |
| `disabled-with-reason` | A disabled id with a reason line is skipped and listed once; an unknown id is named once. |
| `no-rules-file` | The fallback line is written once and `/testing setup` is suggested once. |
| `malformed-rules-file` | The rules file error is named once with its line. |
| `no-files-in-scope` | Review asks which files to review and reports nothing. |
| `approve-1` | The reply `1` fixes row 1 only and runs the affected tests. |
| `approve-invalid` | The reply `1,all` edits nothing, runs nothing and names the invalid part. |
| `setup-no-rules-file` | A repo with no rules file. Setup writes a file with no missing section, one group, the disabled id with its reason line and one convention. An id that is not in the catalogue is shown as unknown and is not written. The skipped limits question leaves no `limits` key. |
| `setup-skip-all` | The same repo, every question skipped. Setup still writes the six required sections: `groups = []`, no `limits`, no `rules`, no prose section. |
| `setup-no-language` | A repo with no Rust or TypeScript manifest. Setup writes the six sections with `languages = []`, `groups = []` and empty tables, and says that no language was detected. |
| `setup-rerun` | A repo with a rules file that has prose, a reason line and two recorded values that differ from detection. The reply approves one row only: that value and the new group change, and every other value, the prose and the reason line stay. The id that is already recorded and the id with no reason are dropped. |

Not covered by a case in this ticket: the reply `none`, and a reply after a report with zero rows. The grammar text of `review.md` states them.
