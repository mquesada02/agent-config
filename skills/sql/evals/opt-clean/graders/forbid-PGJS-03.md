---
type: regex
pattern: '^\|\s*\d+\s*\|\s*PGJS-03\s*\|'
flags: m
match: not_contains
---
Passes when PGJS-03 is absent from the Rule column of the report.
