---
type: llm
arm: with-only
---
PASS if the final message has exactly one line that starts with `Detected for this run:` and mentions `/testing setup` exactly once in the whole message. FAIL otherwise.