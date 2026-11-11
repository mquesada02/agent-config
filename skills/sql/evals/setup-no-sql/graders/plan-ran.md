---
type: tool_used
tool: Bash
input_match: 'setup_files\.py +plan'
min: 1
---
Passes when at least one Bash call runs `setup_files.py plan`. The plan comes before any write (grader D proves the order on a kept run).
