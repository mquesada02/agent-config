# Testing rules

```toml
[[languages]]
name = "typescript"
root = "."

[commands.typescript]
test = "npx vitest run"

[[groups]]
name = "fast"
language = "typescript"
size = "small"
command = "npx vitest run --exclude tests/slow/**"

[runner.typescript]
name = "vitest"

[layout.typescript]
test_paths = ["tests"]

[libraries.typescript]
fakes = "vitest"
```

## Reasons

