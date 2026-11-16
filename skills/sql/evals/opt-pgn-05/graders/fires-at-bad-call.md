---
type: regex
pattern: '^\|\s*\d+\s*\|\s*PGN-05\s*\|(?![^|]*src/queries\.ts:14\b)[^|]*src/queries\.ts:(?:6|10)\b'
flags: m
---
Passes when the Where cell of the PGN-05 row names the line of a call that shares the name (line 6 or line 10) and not the line of the call with its own name (line 14).
