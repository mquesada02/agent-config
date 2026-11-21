# Testing rules

```toml
[[languages]]
name = "rust"
root = "."

[[languages]]
name = "typescript"
root = "web"

[commands.rust]
test = "cargo nextest run"

[commands.typescript]
test = "node --test"

[[groups]]
name = "rust-unit"
language = "rust"
size = "small"
command = "cargo nextest run"

[[groups]]
name = "web-unit"
language = "typescript"
size = "small"
command = "node --test"

[runner.rust]
name = "nextest"

[runner.typescript]
name = "node:test"

[layout.rust]
test_paths = ["tests"]

[layout.typescript]
test_paths = ["src"]

[libraries.rust]
fakes = "hand-written"

[libraries.typescript]
fakes = "node:test"
```

## Reasons
