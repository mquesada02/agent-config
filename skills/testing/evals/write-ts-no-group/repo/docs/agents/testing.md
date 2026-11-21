# Testing rules

```toml
[[languages]]
name = "typescript"
root = "."

[commands.typescript]
test = "npx vitest run"

[[groups]]
name = "changed"
language = "typescript"
size = "small"
command = "npx vitest run --changed"

[runner.typescript]
name = "vitest"

[layout.typescript]
test_paths = ["src"]

[libraries.typescript]
fakes = "vitest"
```

## Reasons

