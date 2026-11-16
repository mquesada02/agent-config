---
type: regex
pattern: '^\|\s*\d+\s*\|\s*PGN-01\s*\|(?![^|]*src/queries\.ts:10\b)[^|]*src/queries\.ts:6\b'
flags: m
---
Passes when the Where cell of the PGN-01 row names the line of the dynamic statement (line 6) and not the line of the correct call (line 10).
