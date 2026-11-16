---
type: regex
pattern: '^\|\s*\d+\s*\|\s*PGN-06\s*\|'
flags: m
match: not_contains
---
Passes when PGN-06 is absent from the Rule column of the report.
