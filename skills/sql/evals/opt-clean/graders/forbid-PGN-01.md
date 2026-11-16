---
type: regex
pattern: '^\|\s*\d+\s*\|\s*PGN-01\s*\|'
flags: m
match: not_contains
---
Passes when PGN-01 is absent from the Rule column of the report.
