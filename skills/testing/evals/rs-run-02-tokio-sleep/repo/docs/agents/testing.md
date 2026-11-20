# Testing rules

```toml
[[languages]]
name = "rust"
root = "."

[commands.rust]
test = "cargo nextest run"

[[groups]]
name = "unit"
language = "rust"
size = "small"
command = "cargo nextest run"

[runner.rust]
name = "nextest"

[layout.rust]
test_paths = ["tests"]

[libraries.rust]
fakes = "hand-written"

[rules]
disabled = ["RUN-04"]
```

## Reasons

- RUN-04: static-only fixture, the crate registry is not reachable
