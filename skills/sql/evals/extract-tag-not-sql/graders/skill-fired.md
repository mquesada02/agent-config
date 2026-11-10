---
type: tool_used
tool: Skill
input_match: '"skill"\s*:\s*"(?:[\w-]+:)?sql"'
---
Passes when Claude invoked the `sql` skill at least once. The prompt does not name the skill, so this proves that a review of the SQL in a file loads it.
