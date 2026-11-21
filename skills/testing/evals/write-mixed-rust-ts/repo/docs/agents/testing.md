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
test = "npx vitest run"

[[groups]]
name = "rust-unit"
language = "rust"
size = "small"
command = "cargo nextest run"

[[groups]]
name = "web-unit"
language = "typescript"
size = "small"
command = "npx vitest run"

[runner.rust]
name = "nextest"

[runner.typescript]
name = "vitest"

[layout.rust]
test_paths = ["tests"]

[layout.typescript]
test_paths = ["src"]

[libraries.rust]
fakes = "hand-written"

[libraries.typescript]
fakes = "vitest"
```

## Reasons

