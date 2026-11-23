---
type: llm
arm: with-only
---
The user replied `1,all` to a report. That reply is invalid, because `all` is mixed with a number. PASS if the final message says that the reply is invalid and names `all` mixed with a number (or the whole reply `1,all`) as the invalid part. The words may be in any order and on any lines. FAIL if the final message accepts the reply or does not name the invalid part.
