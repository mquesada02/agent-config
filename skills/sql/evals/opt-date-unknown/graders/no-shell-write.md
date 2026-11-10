---
type: tool_used
tool: Bash
input_match: '\bsed\s+-i|\b(?:tee|mv|cp|rm|patch)\b|(?<!&)>>?(?!&)\s*(?!/dev/null)\S|&>>?\s*(?!/dev/null)\S'
min: 0
max: 0
---
Passes when no Bash call changes a file. A coarse mirror of the exact no-change grader.
