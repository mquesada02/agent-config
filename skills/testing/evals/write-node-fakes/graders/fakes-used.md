---
type: llm
arm: with-only
---
PASS if the written test file uses `mock.timers`, restores `process.env` after a test (`afterEach` or `t.after`), uses an in-process request fake (`mock.method(globalThis, 'fetch', ...)`), and opens no real network connection. FAIL otherwise.
