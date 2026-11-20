# Testing rules

```toml
[[languages]]
name = "rust"
root = "."

[commands.rust]
test = "cargo test"

[[groups]]
name = "unit"
language = "rust"
size = "small"
command = "cargo test"

[runner.rust]
name = "cargo test"

[layout.rust]
test_paths = ["tests"]

[libraries.rust]
fakes = "hand-written"
```

## Reasons

