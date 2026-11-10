---
type: tool_used
tool: Bash
input_match: '(node_modules/\.bin/|npx +|^ *)(prettier|sqlfluff|pg_format|sql-formatter)( |$)'
min: 0
max: 0
---
Passes when no Bash call starts a formatter by hand. Only the runner script may run a tool.
