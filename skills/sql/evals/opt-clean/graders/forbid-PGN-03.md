---
type: regex
pattern: '^\|\s*\d+\s*\|\s*PGN-03\s*\|'
flags: m
match: not_contains
---
Passes when PGN-03 is absent from the Rule column of the report.
