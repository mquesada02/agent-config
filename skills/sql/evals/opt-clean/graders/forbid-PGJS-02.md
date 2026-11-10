---
type: regex
pattern: '^\|\s*\d+\s*\|\s*PGJS-02\s*\|'
flags: m
match: not_contains
---
Passes when PGJS-02 is absent from the Rule column of the report.
