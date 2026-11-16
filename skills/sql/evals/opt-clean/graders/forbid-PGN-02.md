---
type: regex
pattern: '^\|\s*\d+\s*\|\s*PGN-02\s*\|'
flags: m
match: not_contains
---
Passes when PGN-02 is absent from the Rule column of the report.
