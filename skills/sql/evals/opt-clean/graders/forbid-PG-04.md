---
type: regex
pattern: '^\|\s*\d+\s*\|\s*PG-04\s*\|'
flags: m
match: not_contains
---
Passes when PG-04 is absent from the Rule column of the report.
