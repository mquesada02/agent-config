---
type: tool_used
tool: Bash
input_match: 'setup_files\.py +services|pg_service|pgpass'
min: 0
max: 0
---
Passes when no Bash call checks PG service names or opens a PG service file or password file. The confirmed engine is not PostgreSQL and no `paths` entry names PostgreSQL, so setup skips the allowlist step.
