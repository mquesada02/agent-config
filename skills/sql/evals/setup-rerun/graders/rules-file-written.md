---
type: llm
---
Grader D of seam 2, the `toml`, `unchanged` and `allowlist` checks (the same checks as the command `graders/grade_setup.py` with `expected.json`).

The old rules file had `keyword_case = "lower"` and `indent = "4 spaces"`, a hand-written comment line inside the `toml` block (`# hand-written: the team still argues about the case of keywords`), and the hand-written rule `Use CTEs for any query that joins more than 3 tables.`

Look at the rules file that the final message shows (the file as it was written). Pass when all of these hold:

1. The `toml` block has `keyword_case = "upper"` and `indent = "4 spaces"` (the current `indent` was kept), and the other style keys are as before: `clause_per_line = true`, `comma = "trailing"`, `alias_as = true`; also `[formatter]` `tool = "none"`, `[sources]` `tags = ["sql"]` and `[rules]` `disabled = []`.
2. The hand-written comment line is still inside the `toml` block, and the hand-written rule is still in the prose.
3. The prose also holds the new rule `Never build SQL with string concatenation.`
4. The final message says that the services stay `app-dev`.

Fail when any item is not true.
