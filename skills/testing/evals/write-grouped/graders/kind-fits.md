---
type: llm
arm: with-only
---
PASS if every `Kind` cell fits its change: `unit` for pure logic, `property` only for an invariant that holds for many inputs, `snapshot` only for a structured output against a stored value, `integration` only for a boundary or local I/O. `slugify` is pure, so a `unit` or `property` kind fits. FAIL otherwise.
