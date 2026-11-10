---
type: llm
---
Grader D of seam 2, the `toml` and `allowlist` checks (the same checks as the command `graders/grade_setup.py` with `expected.json`).

Look at the rules file that the final message shows (the file as it was written). Pass when it has one `toml` block with these values: `[style]` `keyword_case` `"upper"`, `indent` `"2 spaces"`, `clause_per_line` `true`, `comma` `"trailing"`, `alias_as` `true`; `[formatter]` `tool` `"none"`; `[sources]` `tags` an empty list; `[rules]` `disabled` an empty list. The final message also says that no allowlist was written (no service was named).

Fail when any value differs, or when the message says that an allowlist entry was written.
