---
type: llm
arm: with-only
---
PASS if the `Source` cell of the found bug names the README or the doc comment of `src/discount.js` (the documented result `applyDiscount(200, 25)` returns `150`), and not the observed output of the run. FAIL otherwise.
