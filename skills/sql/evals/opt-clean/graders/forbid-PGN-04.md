---
type: regex
pattern: '^\|\s*\d+\s*\|\s*PGN-04\s*\|'
flags: m
match: not_contains
---
Passes when PGN-04 is absent from the Rule column of the report.
