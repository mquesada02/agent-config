---
type: llm
arm: with-only
---
PASS if the written test file uses `vi.useFakeTimers`, uses `vi.stubEnv` with a restore (`vi.unstubAllEnvs`), uses an in-process request fake (MSW with `onUnhandledRequest: 'error'`), and opens no real network connection. FAIL otherwise.
