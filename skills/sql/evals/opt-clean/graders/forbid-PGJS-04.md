---
type: regex
pattern: '^\|\s*\d+\s*\|\s*PGJS-04\s*\|'
flags: m
match: not_contains
---
Passes when PGJS-04 is absent from the Rule column of the report.
