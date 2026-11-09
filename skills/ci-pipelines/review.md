# Review steps

Review the GitHub Actions workflows of a repo against the rules and write a report. In this version the skill edits nothing. The fix flow is not built yet.

## Steps

1. Load every rule file in `rules/`. Today that is [rules/naming.md](rules/naming.md), [rules/job-graph.md](rules/job-graph.md) and [rules/maintainability.md](rules/maintainability.md). Load the monorepo rule file only when the repo is a monorepo (the file does not exist yet).
2. Read the intake JSON (see [SKILL.md](SKILL.md)). It holds every repo fact: do not read `package.json`, the lockfile or the settings yourself, and run no other shell command. Use the Read, Glob and Grep tools for the workflow files. Name every default and every unknown fact in section 2 of the report (see "Intake facts" below).
3. Take the required checks from the `required_checks` fact (see "Required checks" below). Do this before you propose a rename or a split.
4. Take the tool status from the `installed_tools` fact (see "Tool status" below).
5. Check each workflow file against each rule. For each failed rule, note every `file:line` place and the severity of the part that failed. A rule that fails in parts of different severity gets one row in each severity table.
6. Write the report as your final message. Use the report contract below.
7. Stop. Make no edit to any file, not even a workflow, before the user approves, and this version has no fix flow. If the user replies to the approval line, say that fixes are not built yet and make no edit. Never edit branch protection or rulesets.

## Intake facts

Section 2 of the report lists each fact with its value. A fact with the status `default` reads `default` and names the default that the script used (for example `Node version for apps: 26 (default, newest LTS)`). A fact with the status `unknown` reads `unknown` and says what the review does about it:

- no lockfile (`package_manager` with `lockfile: null`): a COST-05 finding when the cost rules exist;
- no test runner (`test_runners` is `[]`): no test job, and the report says so;
- `required_checks` unreadable: every current job name may be required (NAME-09);
- `run_history` unknown: there are no measured findings.

When `supported_node_majors` has the status `default`, the line says `Node support list from <date>, offline`, with the date of the offline list.

A `runner_labels` entry with the status `unknown` (a self-hosted label, a larger runner label, a runner group, or an expression that may name one): ask the user for the vCPU size of that label before you write the report, and put the answer in the `Intake:` line. This is the only question that the intake asks.

## Job graph facts

The job graph rules read these facts from the intake JSON. Run no other command for them.

- GRAPH-03 uses `package_kind` (published or app for each package), `engines` (the `engines.node` range of each package), `supported_node_majors`, `node_version_app` and `os_claims`. Only a test job has a matrix. Lint, typecheck and build run once.
- GRAPH-05 uses `run_history`. With the status `unknown`, there is no GRAPH-05 row. With the status `detected`, compute `m` and `ceil(m / 8)` as the GRAPH-05 check says. A measured finding is a suggestion.

## Required checks

Use the `required_checks` fact. With the status `detected` its value lists the required check names (an empty list is `none`). With the status `unknown`, section 3 reads `Required checks: unreadable (<source text of the fact>). Every current job name may be required.` In that case, when the review proposes a rename or a split, add a NAME-09 row (suggestion). Mark each finding that removes or renames a required check with ⚑.

## Tool status

Use the `installed_tools` fact. Section 4 has one bullet for each of `actionlint` and `zizmor`. A tool with `installed: true` reads `on PATH (<version>)`. A tool with `installed: false` reads `not on PATH` and `Install it with` its hint: `brew install actionlint` for actionlint, and `uvx zizmor` or `brew install zizmor` for zizmor. The `pinact` entry has no bullet yet.

## Report contract

The report is your final message. The title line is `# ci-pipelines review: <scope>`, where the scope is a path or `all workflows`. The 8 sections follow in this order.

1. The line `**Result: N critical, N required, N suggestions.**` right after the title line. The `N` are integers. Each count is the number of rows of that severity.
2. A line that starts `Intake:`. It lists the facts and the defaults that you used.
3. A line that starts `Required checks`. When the checks are read, it is ``Required checks (branch protection + rulesets, read-only): `A`, `B`.`` (or `none`). When they are not readable, it is `Required checks: unreadable (<source text of the fact>). Every current job name may be required.`
4. The line `Tools:` and one bullet for each tool:
   - `- actionlint: on PATH (1.7.0)`
   - `- zizmor: not on PATH. Install it with `uvx zizmor` or `brew install zizmor`.`
5. One table for each severity that has a finding, in the order `## Critical`, `## Required`, `## Suggestions`. A severity with no finding has no table. The header is `| # | Rule | Where | Problem | Fix |`. Each row is one rule at one severity. The Rule cell is one rule id, followed by ⚑ when the fix needs a branch protection change. The Where cell holds all `file:line` places of that rule at that severity. Numbers start at 1 and follow the severity order, with no gap.
6. `## ⚑ Branch protection change needed` with the exact admin steps (which checks to remove and which to add). Write it only when at least one row has ⚑.
7. `## Job graph after the fixes` with a fenced ASCII sketch of the jobs after the fixes.
8. `## Approve`, the last section. With at least one finding its text is exactly: `Reply with the findings to fix: `all`, `none`, a list such as `1,3,5`, or a range such as `1-12`.` With zero findings its text is exactly: `There is nothing to approve.`

A finding that the skill, actionlint and zizmor all report appears once.
