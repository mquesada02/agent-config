# Testing rules

```toml
[[languages]]
name = "typescript"
root = "."

[commands.typescript]
test = "npx vitest run --update"

[[groups]]
name = "unit"
language = "typescript"
size = "small"
command = "npx vitest run --update"

[[groups]]
name = "config"
language = "typescript"
size = "small"
command = "npx vitest run --config vitest.update.config.ts"

[runner.typescript]
name = "vitest"

[layout.typescript]
test_paths = ["tests"]

[libraries.typescript]
fakes = "vitest"
```

## Reasons

