---
type: tool_used
tool: Bash
input_match: 'detect_formatter\.py.* --form|formatter_install\.py'
min: 0
max: 0
---
Passes when no Bash call runs the formatter detector (a call with a `--form` option) or the formatter install script. The repo has no postgres.js template and no `.sql` file (its SQL is two `pg` statements), so neither has a target. A `--help` call of the detector is not a run.
