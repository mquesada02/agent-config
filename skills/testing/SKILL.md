---
name: testing
description: Use when writing or reviewing automated tests in a product repo, or when the user calls `/testing setup`, `/testing write` or `/testing review`. Setup writes the repo test rules file, write writes runnable tests for a change, and review judges existing tests against a rule catalogue.
---

# Testing

This skill helps write and judge runnable tests: fast, isolated, safe to run in parallel, and grouped so that a change can run only its own group. This file is the router. It reads the repo rules file and loads only the modules that the task needs.

## Modes

No mode file exists yet. Each later ticket adds the link to its mode file here.

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

- [scripts/intake.py](scripts/intake.py): the intake script. It reads the rules file, holds the rule catalogue (`CATALOG`: each rule id with its severity) and uses no network.
