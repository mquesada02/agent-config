---
type: llm
arm: with-only
---
PASS if the written test file uses `jest.useFakeTimers`, restores `process.env` after a test (a saved copy), uses an in-process request fake (`jest.spyOn(globalThis, 'fetch')` or MSW with `onUnhandledRequest: 'error'`), and opens no real network connection. FAIL otherwise.
