# Testing rules

```toml
[[languages]]
name = "rust"
root = "."

[commands.rust]
test = "cargo nextest run"
doc = "cargo test --doc"

[[groups]]
name = "unit"
language = "rust"
size = "small"
command = "cargo nextest run"

[[groups]]
name = "docs"
language = "rust"
size = "small"
command = "cargo test --doc"

[runner.rust]
name = "nextest"

[layout.rust]
test_paths = ["tests"]

[libraries.rust]
fakes = "hand-written"
```

## Reasons

