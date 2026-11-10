# Tools

How the skill uses actionlint, zizmor and pinact: detect them, give an install hint, run them, merge their output with the skill's own findings, and look up a SHA. The skill checks every SEC rule itself first, so the core rules work when no tool is installed.

## Detection

A tool is on PATH when the `installed_tools` fact of the intake has `installed: true` for it (see [SKILL.md](SKILL.md)). Run a tool only then. Do not look for a tool by any other command. A tool with `installed: false` is not run, and the report gives its install hint.

## Install hints

Write a hint in the report as `Install it with` and the command.

- actionlint: `brew install actionlint`
- zizmor: `uvx zizmor` or `brew install zizmor`
- pinact: `brew install pinact`

The report has a bullet for actionlint and zizmor. The pinact hint is for the fix and create branches and for the SEC-01 fix.

## Running the tools

- actionlint runs in the repo root as `actionlint -format '{{json .}}'`.
- zizmor runs as `zizmor --format=json-v1 .github/workflows` with no `--persona` flag, so the default persona applies.
- A non-zero exit with JSON on stdout means findings, not a failed run (actionlint exits 1 and zizmor exits 11 to 14 when it has findings; these codes come from the tool docs and no test checks them).
- If the output is not JSON, treat the tool as failed: say so in the Tools section of the report and continue with the skill's own rules.
- Do not set a token or any other option.

## Merging the output

1. Check every SEC rule with the skill's own rules first.
2. For each zizmor finding, the audit is its `ident`, and the place is the file of its first location and `row + 1` (the `json-v1` row is zero-based).
   - When the audit is in the mapping table below, the finding is a finding of that SEC id. Add its place to the row of that id and severity, and never write the audit id.
   - The severity is the one of the SEC rule part that the finding fits. `template-injection` is critical when the expression in the flagged `run:` line holds an untrusted context (SEC-04), and required otherwise. `dangerous-triggers` is the required part of SEC-07 (a PR-head checkout is the skill's own finding, made by the SEC-07 rule, and the mapped finding never makes it critical). The other mapped audits have one severity.
   - When the audit is not in the table, the finding keeps its audit id in the Rule cell and is a suggestion, whatever zizmor says about its own severity.
3. For each actionlint finding, the Rule cell is `actionlint-<kind>` (its `kind` field), the place is its `filepath` and `line`, and the severity is suggestion.
4. One row holds one rule id at one severity, and each place appears once in a row. A finding that the skill and a tool both report shows once.

## zizmor to SEC mapping

The skill checks SEC-* itself. When zizmor is installed, each matching audit maps to its SEC id, so a finding that both report shows once. Each zizmor finding with no SEC match is listed under its own audit id.

| zizmor audit | SEC rule |
|---|---|
| `unpinned-uses` | SEC-01 |
| `excessive-permissions` | SEC-03 |
| `template-injection` | SEC-04 (partial: SEC-04 is stricter) |
| `artipacked` | SEC-05 |
| `dangerous-triggers` | SEC-07 |
| `secrets-inherit` | SEC-08 |
| `cache-poisoning` | SEC-09 |

## Pin a SHA

This is the SEC-01 method.

1. When pinact is on PATH, run `pinact run`.
2. Otherwise run `gh api repos/<owner>/<repo>/git/ref/tags/<tag>`.
3. When the `object.type` of the answer is `tag` (an annotated tag), make one more call, `gh api repos/<owner>/<repo>/git/tags/<sha>`, and use its `object.sha`, which is the commit.
4. Write the pin as `@<sha> # <tag>`.

## Offline Node support list

The intake script reads this block when it has no network. It is the dated list of supported Node majors.

```json
{"date": "2026-11-09", "majors": [22, 24, 26], "newest_lts": 26}
```
