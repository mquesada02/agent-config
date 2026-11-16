# Review steps

Review the GitHub Actions workflows of a repo against the rules and write a report. The skill changes no file until the user approves. The reply of the user starts the fix flow (see "Fix on approval").

## Steps

1. Load every rule file in `rules/` except the monorepo file. Today that is [rules/naming.md](rules/naming.md), [rules/job-graph.md](rules/job-graph.md), [rules/cost.md](rules/cost.md), [rules/security.md](rules/security.md) and [rules/maintainability.md](rules/maintainability.md). Load [rules/monorepo.md](rules/monorepo.md) only when the `monorepo` fact of the intake has `monorepo: true`. A single package never loads it.
2. Read the intake JSON (see [SKILL.md](SKILL.md)). It holds every repo fact: do not read `package.json`, the lockfile or the settings yourself, and run no other shell command than the tools of [tools.md](tools.md) that the intake says are on PATH (step 6) and the pin check of [tools.md](tools.md) ("Check the pins"), which you run only when a workflow has a `uses:` line pinned to a 40-character SHA. The fix flow has its own commands (see "Fix on approval"). Use the Read, Glob and Grep tools for the workflow files. Name every default and every unknown fact in section 2 of the report (see "Intake facts" below).
3. Take the required checks from the `required_checks` fact (see "Required checks" below). Do this before you propose a rename or a split.
4. Take the tool status from the `installed_tools` fact (see "Tool status" below). The install hints are in [tools.md](tools.md).
5. Check each workflow file against each rule. For each failed rule, note every `file:line` place and the severity of the part that failed. A rule that fails in parts of different severity gets one row in each severity table.
6. Run the installed tools: for each of `actionlint` and `zizmor` whose `installed_tools` entry has `installed: true`, run it as [tools.md](tools.md) says and merge its findings into the findings of step 5 (see "Merging the output" in tools.md). A tool that is not on PATH is not run, and the review continues with the skill's own rules.
7. Write the report as your final message. Use the report contract below.
8. Stop. Make no edit to any file, not even a workflow, before the user approves. When the user replies to the approval line, follow "Fix on approval". Never edit branch protection or rulesets.

## Intake facts

Section 2 of the report lists each fact with its value. A fact with the status `default` reads `default` and names the default that the script used (for example `Node version for apps: 26 (default, newest LTS)`). A fact with the status `unknown` reads `unknown` and says what the review does about it:

- no lockfile (`package_manager` with `lockfile: null`): a COST-05 finding;
- no test runner (`test_runners` is `[]`): no test job, and the report says so;
- `required_checks` unreadable: every current job name may be required (NAME-09);
- `run_history` unknown: there are no measured findings, and COST-04 uses the create values.

When `supported_node_majors` has the status `default`, the line says `Node support list from <date>, offline`, with the date of the offline list.

A `runner_labels` entry with the status `unknown` (a self-hosted label, a larger runner label, a runner group, or an expression that may name one): ask the user for the vCPU size of that label before you write the report, and put the answer in the `Intake:` line. This is the only question that the intake asks.

## Job graph facts

The job graph rules read these facts from the intake JSON. Run no other command for them.

- GRAPH-03 uses `package_kind` (published or app for each package), `engines` (the `engines.node` range of each package), `supported_node_majors`, `node_version_app` and `os_claims`. Only a test job has a matrix. Lint, typecheck and build run once.
- GRAPH-05 uses `run_history`. With the status `unknown`, there is no GRAPH-05 row. With the status `detected`, compute `m` and `ceil(m / 8)` as the GRAPH-05 check says. A measured finding is a suggestion.

## Cost and monorepo facts

The cost and monorepo rules read these facts from the intake JSON. Run no other command for them.

- COST-04 uses `run_history`. With the status `unknown`, there is no measured finding and the review uses the create values. With the status `detected`, compute `m` and the proposal as the COST-04 check says. A measured finding is a suggestion, and a missing `timeout-minutes` is required.
- COST-06 uses `visibility` and `runner_labels` (the `vcpus` of each label). An unreadable visibility is `private` with the status `default`, so 2 vCPU.
- MONO-01 and MONO-02 use `monorepo` (its `tool`) and `package_manager`. An npm or yarn workspaces monorepo gets no MONO finding.

## Security and tool facts

The security rules and the tool merge read these sources. Run no other command for them.

- SEC-01 reads the output of the pin check (see "Check the pins" in [tools.md](tools.md)) for the commit part. A recorded pin check output that the user names replaces the run. When a pin is `unverified`, the `Intake:` line says `SEC-01 pins not verified (<reason>)` and the form check still applies.
- SEC-02 reads `.github/dependabot.yml` with the Read and Glob tools.
- A mapped zizmor finding takes the severity of its SEC rule part, and shows as the SEC id (see the mapping table in [tools.md](tools.md)).
- Any other zizmor finding keeps its audit id and is a suggestion. An actionlint finding is a suggestion.
- A tool that runs but prints no JSON is named in the Tools section as failed, and the review continues.

## Required checks

Use the `required_checks` fact. With the status `detected` its value lists the required check names (an empty list is `none`). With the status `unknown`, section 3 reads `Required checks: unreadable (<source text of the fact>). Every current job name may be required.` In that case, when the review proposes a rename or a split, add a NAME-09 row (suggestion) marked with ⚑. Its Fix cell is the fixed sentence of NAME-09, which never says "before merging". Mark each other finding that removes or renames a required check with ⚑.

## Tool status

Use the `installed_tools` fact. Section 4 has one bullet for each of `actionlint` and `zizmor`. A tool with `installed: true` reads `on PATH (<version>)`. A tool with `installed: false` reads `not on PATH` and `Install it with` its hint from the "Install hints" section of [tools.md](tools.md) (`brew install actionlint` for actionlint, and `uvx zizmor` or `brew install zizmor` for zizmor). The `pinact` entry has no bullet. The bullet always follows the `installed_tools` fact, even when a run of the tool fails (for example `command not found`). Say that failure in the `Intake:` line, in `## Created` (create mode) or in the actionlint part of the final message (fix flow), never in the bullet.

## Report contract

The report is your final message. The title line is `# ci-pipelines review: <scope>`, where the scope is a path or `all workflows`. The 8 sections follow in this order.

1. The line `**Result: N critical, N required, N suggestions.**` right after the title line. The `N` are integers. Each count is the number of rows of that severity.
2. A line that starts exactly with `Intake:` (the word and the colon, with no other word between them). It lists the facts and the defaults that you used.
3. A line that starts `Required checks`. When the checks are read, it is ``Required checks (branch protection + rulesets, read-only): `A`, `B`.`` (or `none`). When they are not readable, it is `Required checks: unreadable (<source text of the fact>). Every current job name may be required.`
4. The line `Tools:` and one bullet for each tool:
   - `- actionlint: on PATH (1.7.0)`
   - `- zizmor: not on PATH. Install it with `uvx zizmor` or `brew install zizmor`.`

   A bullet has no other text than one of these two forms.
5. One table for each severity that has a finding, in the order `## Critical`, `## Required`, `## Suggestions`. A severity with no finding has no table. The header is `| # | Rule | Where | Problem | Fix |`. Each row is one rule at one severity. The Rule cell is one rule id, followed by ⚑ when the fix needs a branch protection change, and always on a NAME-09 row. The Where cell holds all `file:line` places of that rule at that severity. Numbers start at 1 and follow the severity order, with no gap.
6. `## ⚑ Branch protection change needed` with the exact admin steps (which checks to remove and which to add). Write it only when at least one row has ⚑.
7. `## Job graph after the fixes` with a fenced ASCII sketch of the jobs after the fixes.
8. `## Approve`, the last section. With at least one finding its text is exactly: `Reply with the findings to fix: `all`, `none`, a list such as `1,3,5`, or a range such as `1-12`.` With zero findings its text is exactly: `There is nothing to approve.` Copy this sentence exactly, and never change its examples (`1,3,5` and `1-12`) to fit the number of findings. Write no text after the approval line. When a tool or the intake script was not available, say it in the `Tools:` line (section 4) and in the `Intake:` line (section 2), never after the approval line.

A finding that the skill, actionlint and zizmor all report appears once.

## Fix on approval

The user replies to the approval line. Follow these steps in order. Edit only the findings that the reply approves. When a file was edited, the final message has the parts of step 9 (`## Applied`, `## Diff`, then the whole post-fix report), and you never end with a prose note instead.

1. **Read the reply.** The numbers refer to the `#` column of the latest report in the conversation (after a fix run, that is the post-fix report). Without a report in the conversation, say so, edit nothing and offer a new review.
2. **Reply grammar.** The reply is `all`, `none`, or a selection. A selection is a comma-separated list. Each item is a finding number or a range `a-b` with `a` less than or equal to `b`. A list and ranges can mix (`1,3-5,9`). Spaces around commas and inside a range (`3 - 5`) and the case of `all` and `none` do not matter. A number that is listed twice, or in two overlapping ranges, counts once. `all` against a report with no rows changes no file and says that there is nothing to fix. A number that is not a row of the report, a descending range, `all` or `none` mixed with numbers, an unknown word or an empty reply is invalid: edit nothing, name the invalid part, restate the grammar and wait.
3. **`none`.** Edit no file. Say that no fix was applied. Run no shell command (reading a recorded intake file is not a shell command). Stop.
4. **Edit.** Apply the Fix of each approved row at each `file:line` place of its Where cell, in the order of the numbers, with the Edit tool. Change nothing else: no line of an unapproved row, no formatting, and no other file than the ones the approved rows name (a row such as SEC-02 names `.github/dependabot.yml`). Use no shell command to write a file. When an approved fix cannot be applied without a change to a place of an unapproved row, skip it, edit nothing for it, and say which row and why.
5. **No edit, or no workflow edited.** When no file was edited (every approved row was skipped), the final message holds only `## Applied` with the skipped rows and the line "No file was edited." Run no tool, show no diff, write no post-fix report, and stop. When files were edited but none is a workflow (for example only `.github/dependabot.yml`), skip actionlint, because there is nothing to lint, and do the diff, the check again and the final message as usual.
6. **actionlint.** Take the status from the `installed_tools` fact. With `installed: true`, run `actionlint` after the last edit, as [tools.md](tools.md) says (in the repo root, JSON output, so it lints every workflow, the edited ones included), and report its result. Run it as its own call, never chained with another command. With `installed: false`, say that actionlint is not on PATH and give the hint from [tools.md](tools.md) (`brew install actionlint`). Never install a tool. A failed run of actionlint (for example `command not found`) does not end the fix flow: say the failure, and go on with steps 7 to 9.
7. **Diff.** Show the diff of the edited files in a fenced `diff` block. Use `git diff -- <files>` when the repo is under git. Otherwise write the unified diff of your own edits by hand. `git diff` is the only shell command of this step, and it is its own call, never chained with another command.
8. **Check again.** Check the edited workflows against the same rules as steps 1 and 5 of the review, with the intake facts of the review and the actionlint result of step 6 when it ran (do not run it twice). Reuse the intake facts that the review of this conversation used, or the recorded intake output that the user names. Run the intake script again only when no intake facts are in the conversation.
9. **Final message.** Write these parts in this order: `## Applied` (a bulleted list, never a table, because a table row would be read as a finding: one bullet for each approved row with its number, its rule id and the change, and one bullet for each skipped row with the reason), `## Diff` (the fenced block), the admin steps when an approved row had the ⚑ mark, and then the post-fix report. The post-fix report is the whole report contract (all 8 sections), never a prose summary. It follows the report contract in full, with the title `# ci-pipelines review: <scope> (after fixes)`. It holds the findings that remain: the unapproved rows and any finding that the edits added. It renumbers from 1. Its last section is `## Approve`, as the contract says: with no finding left it reads `There is nothing to approve.`

**Admin steps.** For each approved row that had ⚑, the final message gives one section with the heading `## Branch protection steps for the admin`, and one bullet for each row. Do not start this heading with `## ⚑`, which is the heading of the ⚑ section of a report. A skipped ⚑ row gets no admin steps, because its check name did not change. Each bullet lists every check name to remove and every check name to add. A rename is one of each, a split of a job is one removed name and several added names, a removed job is a removed name and no added name, and a new check is an added name only. It gives both places, in this form: for branch protection, "Settings, Branches, edit the rule for `<default branch>`, Require status checks to pass: remove `<removed names>`, add `<added names>`"; for a ruleset, "Settings, Rules, Rulesets, edit the ruleset, Require status checks to pass: remove `<removed names>`, add `<added names>`". The intake merges the check names of branch protection and rulesets into one list, so the skill always gives both places and tells the admin to change the one that holds the old name. It says that the admin changes the settings after the merge. The skill does not make the change.

**No write to branch protection or rulesets.** No step of the skill, and no command that the skill runs, makes a `gh api` call with a method other than `GET` or with a body (`-f`, `-F`, `--field`, `--raw-field`, `--input`) on a branch protection path (`.../branches/<branch>/protection...`) or a ruleset path (`.../rulesets...`).
