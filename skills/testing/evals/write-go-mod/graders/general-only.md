---
type: llm
arm: with-only
---
PASS if the run read no file under `skills/testing/entries/` and used `general.md` only for the rules, and the written file `calc_test.go` follows the rules of `general.md` (an assertion in every test case, one behavior per test case, a name that states the behavior). FAIL otherwise.
