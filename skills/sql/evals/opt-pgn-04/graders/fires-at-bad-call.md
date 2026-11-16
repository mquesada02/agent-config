---
type: regex
pattern: '^\|\s*\d+\s*\|\s*PGN-04\s*\|(?![^|]*src/queries\.ts:10\b)[^|]*src/queries\.ts:6\b'
flags: m
---
Passes when the Where cell of the PGN-04 row names the line of the IN call with an array (line 6) and not the line of the ANY call (line 10).
