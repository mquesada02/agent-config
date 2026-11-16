---
type: regex
pattern: '^\|\s*\d+\s*\|\s*PGN-02\s*\|(?![^|]*src/queries\.ts:10\b)[^|]*src/queries\.ts:6\b'
flags: m
---
Passes when the Where cell of the PGN-02 row names the line of the call with two statements and values (line 6) and not the line of the correct call (line 10).
