---
type: regex
pattern: '^\|\s*\d+\s*\|\s*PGN-03\s*\|(?![^|]*src/queries\.ts:10\b)[^|]*src/queries\.ts:6\b'
flags: m
---
Passes when the Where cell of the PGN-03 row names the line of the call with one value for two placeholders (line 6) and not the line of the correct call (line 10).
