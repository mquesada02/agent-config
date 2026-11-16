---
type: regex
pattern: '^\|\s*\d+\s*\|\s*PGN-06\s*\|(?![^|]*src/queries\.ts:10\b)[^|]*src/queries\.ts:6\b'
flags: m
---
Passes when the Where cell of the PGN-06 row names the line of the call that binds a Date (line 6) and not the line of the call that binds text (line 10).
