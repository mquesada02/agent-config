---
type: tool_used
tool: Bash
input_match: 'setup_files\.py +services'
min: 1
---
Passes when at least one Bash call checks the service name `app-dev` against the PG service file with the `services` action of `setup_files.py`.
