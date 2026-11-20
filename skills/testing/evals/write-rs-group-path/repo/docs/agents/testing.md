# Testing rules

```toml
[[languages]]
name = "rust"
root = "."

[commands.rust]
test = "cargo nextest run"

[[groups]]
name = "missing"
language = "rust"
size = "small"
command = "cargo nextest run --test missing"

[[groups]]
name = "it"
language = "rust"
size = "small"
command = "cargo nextest run --test it"

[runner.rust]
name = "nextest"

[layout.rust]
test_paths = ["tests"]

[libraries.rust]
fakes = "hand-written"
```

## Reasons

