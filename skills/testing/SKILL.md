---
name: testing
description: Use when writing or reviewing automated tests in a product repo, or when the user calls `/testing setup`, `/testing write` or `/testing review`. Setup writes the repo test rules file, write writes runnable tests for a change, and review judges existing tests against a rule catalogue.
---

# Testing

This skill helps write and judge runnable tests: fast, isolated, safe to run in parallel, and grouped so that a change can run only its own group. This file is the router. It reads the repo rules file and loads only the modules that the task needs.

## Modes

- `/testing setup`: detect the repo test facts, ask a short interview and write the repo rules file. See [setup.md](setup.md) and the setup flow below.
- `/testing review`: judge existing tests against the rule catalogue, report by severity, then fix only the approved findings. See [review.md](review.md) and the review flow below.

- `/testing write`: write runnable tests for a change, run them and report. See [write.md](write.md) and the write flow below.

## Setup flow

For `/testing setup`, follow these steps in order:

1. Load [general.md](general.md). It is always loaded. Its catalogue table lists the rule ids that the interview offers.
2. Load [setup.md](setup.md) and follow it. It runs the intake script itself (see "Rules file"), so this flow step runs no intake. It loads no language entry.

## Review flow

For `/testing review`, follow these steps in order:

1. Scope. Take the files in scope: the paths the user names, else the changed files (`git diff --name-only` against the default branch, plus the working-tree changes) that are test files by name alone (a path part is `test`, `tests` or `__tests__`, or the file name matches `*.test.<ext>`, `*.spec.<ext>`, `test_*` or `*_test.<ext>`). This step reads no intake output. When no file is found, stop and ask the user which files to review.
2. Intake. Run the intake script (see "Rules file") with the repo root and the files. Exit code 0 and exit code 1 both print the JSON, and you continue (exit code 1 with the JSON on stdout means that `rules.error` is set: this is a fallback, not a failed command). Exit code 1 with no JSON is a failed command: report the output and stop. Exit code 2 is a usage error: report the message, run no check and stop.
3. General. Load [general.md](general.md). It is always loaded.
4. Entries. For each distinct `entries` value other than `general`, load `entries/<value>.md` when that file exists. When it does not exist, or when every file is `general`, use the general guidance only.
5. Review. Load [review.md](review.md) and follow it.

## Write flow

For `/testing write`, follow these steps in order:

1. Scope. Take the product files of the change. A product file is a file that is not a test file (by the name-only rule of step 1 of the review flow) and has the extension `.rs`, `.ts`, `.tsx`, `.js`, `.mjs` or `.cjs`. The candidates are the paths the user names (a directory means the files below it that git does not ignore), else the changed files (as step 1 of the review flow). A file that the user names is never filtered by extension. A named test file, and a path that does not exist, are not product files. When no product file is found, ask nothing: write the empty-scope report (see "Report contract" in [write.md](write.md)) and stop.
2. Intake. As step 2 of the review flow, with the product files as the file arguments. When intake fails (exit code 2, or exit code 1 with no JSON), ask nothing: write the failed-intake report (see "Report contract" in [write.md](write.md)) and stop.
3. General. Load [general.md](general.md). It is always loaded.
4. Entries. As step 4 of the review flow.
5. Write. Load [write.md](write.md) and follow it.

## Rules file

The repo rules live in `docs/agents/testing.md` of the product repo. The intake script checks them. It needs Python 3.11 or newer (`tomllib`):

```
python3 <skill folder>/scripts/intake.py <repo root> [file ...]
```

It prints one JSON object with the keys `rules` and `detected`. The `rules` object has the keys `found`, `settings`, `missing_sections`, `disabled_without_reason`, `unknown_ids` and `error`. The `detected` object has three keys:

- `languages`: a list of `{name, root, manifest}` for `rust` and `typescript`. The `manifest` is `null` when the root holds none.
- `entries`: for each `[file ...]` argument, the language entry to load: `rust`, `typescript` or `general`. A path outside the repo root is a usage error (exit code 2).
- `facts`: for each listed language, the detected test facts. Each fact is `{value, status, source}`. The `status` is `detected`, `default` or `unknown`. The script always prints them. Use them when the rules file is missing or malformed.

## Modules

- [general.md](general.md): the always-loaded general file. It holds the rule catalogue, the rule text of each checked rule id, and three sections of rule text without an id (kinds of tests, test points, design topics).
- [setup.md](setup.md): the setup mode steps, the interview and the layout of the rules file.
- [review.md](review.md): the review mode steps, the report contract and the fix flow.
- [write.md](write.md): the write mode steps, the report contract and the rules for run results, sizes, libraries, test location and test wrong or product wrong.
- [scripts/grade_testing_report.py](scripts/grade_testing_report.py): the report grader. It checks a review report against the report contract, the rule ids and the severities.
- [scripts/grade_testing_setup.py](scripts/grade_testing_setup.py): the setup grader. It checks a written rules file through the intake script (intake clean, approved values changed, other values and prose kept, skipped keys unset).
- [scripts/grade_testing_write.py](scripts/grade_testing_write.py): the write grader. It checks a write report against the report contract, and a written test file against an expectation file.
- [scripts/intake.py](scripts/intake.py): the intake script. It reads the rules file, holds the rule catalogue (`CATALOG`: each rule id with its severity) and uses no network.
