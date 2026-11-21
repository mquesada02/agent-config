---
type: regex
pattern: '^The skill edits no file in general mode\.$[\s\S]*^Formatter: '
flags: m
---
Passes when the text after the general last line has a `Formatter:` line, as the PostgreSQL format report does.
