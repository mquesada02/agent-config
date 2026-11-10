---
type: regex
pattern: '^\|\s*\d+\s*\|\s*PGJS-01\s*\|'
flags: m
match: not_contains
---
Passes when PGJS-01 is absent from the Rule column of the report.
