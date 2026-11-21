---
type: tool_used
tool: Bash
input_match: 'psql|pg_run|PGSERVICE|service='
min: 0
max: 0
---
Passes when no Bash call opens a database connection. The model-invoked path never connects to a database.
