---
type: llm
arm: with-only
---
Read the Jest JSON output that the run of the write step printed (the Bash tool result of the run that holds `--json`). PASS if every new test case that the write report lists has an `assertionResults` entry in that output, so that the `Run result: pass` rests on test cases that ran. FAIL otherwise.
