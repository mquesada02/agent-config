---
type: tool_used
tool: Bash
input_match: 'measure_style\.py[\s\S]*--receivers'
min: 1
---
Passes when at least one Bash call runs the style measurer with the `--receivers` option. The repo has SQL in `pg` statements, so the stored style comes from the measurer, and the confirmed receivers go with it.
