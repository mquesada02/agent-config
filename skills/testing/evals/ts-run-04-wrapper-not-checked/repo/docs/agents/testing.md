# Testing rules

```toml
[[languages]]
name = "typescript"
root = "."

[commands.typescript]
test = "npm run ci"

[[groups]]
name = "unit"
language = "typescript"
size = "small"
command = "npm run ci"

[runner.typescript]
name = "vitest"

[layout.typescript]
test_paths = ["tests"]

[libraries.typescript]
fakes = "vitest"
```

## Reasons

