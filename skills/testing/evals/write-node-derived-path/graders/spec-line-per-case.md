---
type: llm
arm: with-only
---
Read the output that the run of the write step printed (the Bash tool result of the run that holds `--test-reporter=spec`). PASS if every new test case that the write report lists has a result line (`✔ <name> (<N>ms)`) in that output, so that the `Run result: pass` rests on test cases that ran. FAIL otherwise.
