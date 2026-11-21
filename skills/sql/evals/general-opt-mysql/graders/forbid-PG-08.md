---
type: regex
pattern: '^\|\s*\d+\s*\|\s*PG-08\s*\|'
flags: m
match: not_contains
---
Passes when PG-08 is absent from the Rule column of the report. A MySQL file gets GEN rules only.
