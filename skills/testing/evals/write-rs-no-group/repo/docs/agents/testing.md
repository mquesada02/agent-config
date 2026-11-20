# Testing rules

```toml
[[languages]]
name = "rust"
root = "."

[commands.rust]
test = "cargo test"

[[groups]]
name = "fast"
language = "rust"
size = "small"
command = "cargo test -- --skip slow_"

[runner.rust]
name = "cargo test"

[layout.rust]
test_paths = ["tests"]

[libraries.rust]
fakes = "hand-written"
```

## Reasons

