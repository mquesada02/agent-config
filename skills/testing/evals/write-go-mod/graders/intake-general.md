---
type: llm
arm: with-only
---
PASS if the run executed `scripts/intake.py` on the fixture with the product file `calc.go` (and, when the run did it, with the written file `calc_test.go`) and the printed `detected.entries` value is `general` for each file. If the run did not run intake for `calc_test.go`, run `python3 -I <skill folder>/scripts/intake.py <repo> calc.go calc_test.go` yourself and check that `detected.entries` is `general` for both. FAIL otherwise.
