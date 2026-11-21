---
type: llm
arm: with-only
---
PASS if the report has one `## File:` section for a Rust test file whose Command line holds `cargo nextest run`, and one for a TypeScript test file whose Command line holds `vitest run` with `--maxWorkers=2` and `--reporter=verbose`. FAIL otherwise.
