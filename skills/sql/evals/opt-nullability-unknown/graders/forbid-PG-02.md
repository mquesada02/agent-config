---
type: regex
pattern: '^\|\s*\d+\s*\|\s*PG-02\s*\|'
flags: m
match: not_contains
---
Passes when PG-02 is absent from the Rule column of the report.
