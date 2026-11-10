---
type: llm
arm: with-only
---
PASS if the diff in the final message changes only the places of the findings that the reply approved, and changes no other line.
FAIL if the diff changes a line that belongs to a finding that the reply did not approve, or changes formatting.
