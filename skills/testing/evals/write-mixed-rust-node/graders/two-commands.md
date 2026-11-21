---
type: llm
arm: with-only
---
PASS if the report has one `## File:` section for a Rust test file whose Command line holds `cargo nextest run`, and one for a TypeScript test file whose Command line holds `node --test` with `--test-concurrency=2` and `--test-reporter=spec`. FAIL otherwise.
