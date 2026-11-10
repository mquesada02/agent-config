---
type: tool_used
tool: Bash
input_match: 'psql|pg_dump|pg_isready|pgcli'
min: 0
max: 0
---
Passes when no Bash call runs a database client by hand. The `pg_run.py` wrapper is the only path to a database.
