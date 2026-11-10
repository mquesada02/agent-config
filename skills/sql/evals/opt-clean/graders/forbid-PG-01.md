---
type: regex
pattern: '^\|\s*\d+\s*\|\s*PG-01\s*\|'
flags: m
match: not_contains
---
Passes when PG-01 is absent from the Rule column of the report.
