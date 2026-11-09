# Review steps

Review the GitHub Actions workflows of a repo against the rules and write a report. In this version the skill edits nothing. The fix flow is not built yet.

## Steps

1. Load every rule file in `rules/`. Today that is [rules/naming.md](rules/naming.md). Load the monorepo rule file only when the repo is a monorepo (the file does not exist yet).
2. Read the repo facts yourself (the intake script is not built yet): package manager and lockfile, the shape of the repo, and the workflows in `.github/workflows/`. Use the Read, Glob and Grep tools for files. Use Bash only for the calls that this file names (one call each, never combined with `&&`, `;` or a pipe). Name every default that you assume. Section 2 of the report lists them.
3. Read the required checks (see "Required checks" below). Do this before you propose a rename or a split.
4. Check the tool status (see "Tool status" below).
5. Check each workflow file against each rule. For each failed rule, note every `file:line` place and the severity of the part that failed. A rule that fails in parts of different severity gets one row in each severity table.
6. Write the report as your final message. Use the report contract below.
7. Stop. Make no edit to any file, not even a workflow, before the user approves, and this version has no fix flow. If the user replies to the approval line, say that fixes are not built yet and make no edit. Never edit branch protection or rulesets.

## Required checks

Interim procedure (the intake script replaces it later). Run these read-only `gh api` GET calls, with the repo owner `{o}`, the repo name `{r}` and the default branch `{b}`:

- `gh api repos/{o}/{r}/branches/{b}/protection/required_status_checks`
- `gh api repos/{o}/{r}/rules/branches/{b}` (use the rules of type `required_status_checks`)

Use no method flag and send no body. When a call fails, section 3 of the report reads `Required checks: unreadable (<reason>). Every current job name may be required.` When the review proposes a rename or a split in that case, add a NAME-09 row (suggestion). Mark each finding that removes or renames a required check with ⚑.

## Tool status

Interim procedure. Run `command -v actionlint` and then `command -v zizmor`, as two separate Bash calls. A call that prints a path means the tool is on PATH. A call that prints nothing (exit code 1) means it is not on PATH. For a tool that is on PATH, run `actionlint -version` or `zizmor --version` (one Bash call) and take the version from the first line of its output. Section 4 has one bullet for each tool. A tool on PATH reads `on PATH (<version>)`. A tool that is not on PATH reads `not on PATH` and has its install hint.

## Report contract

The report is your final message. The title line is `# ci-pipelines review: <scope>`, where the scope is a path or `all workflows`. The 8 sections follow in this order.

1. The line `**Result: N critical, N required, N suggestions.**` right after the title line. The `N` are integers. Each count is the number of rows of that severity.
2. A line that starts `Intake:`. It lists the facts and the defaults that you used.
3. A line that starts `Required checks`. When the checks are read, it is ``Required checks (branch protection + rulesets, read-only): `A`, `B`.`` (or `none`). Otherwise use the unreadable text above.
4. The line `Tools:` and one bullet for each tool:
   - `- actionlint: on PATH (1.7.0)`
   - `- zizmor: not on PATH. Install it with `uvx zizmor` or `brew install zizmor`.`
5. One table for each severity that has a finding, in the order `## Critical`, `## Required`, `## Suggestions`. A severity with no finding has no table. The header is `| # | Rule | Where | Problem | Fix |`. Each row is one rule at one severity. The Rule cell is one rule id, followed by ⚑ when the fix needs a branch protection change. The Where cell holds all `file:line` places of that rule at that severity. Numbers start at 1 and follow the severity order, with no gap.
6. `## ⚑ Branch protection change needed` with the exact admin steps (which checks to remove and which to add). Write it only when at least one row has ⚑.
7. `## Job graph after the fixes` with a fenced ASCII sketch of the jobs after the fixes.
8. `## Approve`, the last section. With at least one finding its text is exactly: `Reply with the findings to fix: `all`, `none`, a list such as `1,3,5`, or a range such as `1-12`.` With zero findings its text is exactly: `There is nothing to approve.`

A finding that the skill, actionlint and zizmor all report appears once.
