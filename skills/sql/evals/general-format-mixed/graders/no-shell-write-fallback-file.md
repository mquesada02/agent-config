---
type: tool_used
tool: Bash
input_match: '(?:\bsed\s+-i|\b(?:tee|mv|cp|rm|patch)\b|>>?)[^|;&\n]*reports\.ts'
min: 0
max: 0
---
Passes when no Bash call writes `src/reports.ts`, the fallback file. A coarse mirror of the hand check that the file equals the fixture.
