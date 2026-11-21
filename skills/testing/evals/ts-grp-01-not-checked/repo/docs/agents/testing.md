# Testing rules

```toml
[[languages]]
name = "typescript"
root = "."

[commands.typescript]
test = "npx vitest run"

[[groups]]
name = "wrapped"
language = "typescript"
size = "small"
command = "npm run unit"

[[groups]]
name = "related"
language = "typescript"
size = "small"
command = "npx vitest related src/a.ts"

[runner.typescript]
name = "vitest"

[layout.typescript]
test_paths = ["tests"]

[libraries.typescript]
fakes = "vitest"
```

## Reasons

