---
type: regex
pattern: '^\|\s*\d+\s*\|\s*PGN-05\s*\|'
flags: m
match: not_contains
---
Passes when PGN-05 is absent from the Rule column of the report.
