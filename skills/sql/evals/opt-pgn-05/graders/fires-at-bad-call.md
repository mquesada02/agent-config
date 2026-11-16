---
type: regex
pattern: '^\|\s*\d+\s*\|\s*PGN-05\s*\|(?![^|]*src/queries\.ts:14\b)(?=[^|]*src/queries\.ts:6\b)(?=[^|]*src/queries\.ts:10\b)'
flags: m
---
Passes when the Where cell of the PGN-05 row names the lines of both calls that share the name (line 6 and line 10) and not the line of the call with its own name (line 14).
