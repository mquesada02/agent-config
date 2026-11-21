---
type: regex
pattern: '^The skill edits no file in general mode\.$(?![\s\S]*^# sql format)(?![\s\S]*^\*\*Result:)'
flags: m
---
Passes when the text after the general last line has no `# sql format` title line and no `**Result:` line. The PostgreSQL format report has no new title and no Result line.
