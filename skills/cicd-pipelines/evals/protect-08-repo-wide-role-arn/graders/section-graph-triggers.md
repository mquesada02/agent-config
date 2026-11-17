---
type: regex
pattern: '^push main: Deploy\b[^\n]*\n(?:(?!(?:push main|tag \S+|dispatch): )[^\n]*\n)*tag v\*: Deploy\b[^\n]*\n(?:(?!(?:push main|tag \S+|dispatch): )[^\n]*\n)*dispatch: Rollback\b[^\n]*\n(?:(?!(?:push main|tag \S+|dispatch): |```)[^\n]*\n)*```'
flags: m
---
