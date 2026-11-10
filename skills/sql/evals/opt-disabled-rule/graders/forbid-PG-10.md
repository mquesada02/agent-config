---
type: regex
pattern: '^\|\s*\d+\s*\|\s*PG-10\s*\|'
flags: m
match: not_contains
---
Passes when PG-10 is absent from the Rule column of the report.
