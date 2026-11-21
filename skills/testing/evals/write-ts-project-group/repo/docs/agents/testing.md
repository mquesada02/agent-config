# Testing rules

```toml
[[languages]]
name = "typescript"
root = "."

[commands.typescript]
test = "npx vitest run"

[[groups]]
name = "unit"
language = "typescript"
size = "small"
command = "npx vitest run --project unit"

[[groups]]
name = "slow"
language = "typescript"
size = "large"
command = "npx vitest run --project slow"

[runner.typescript]
name = "vitest"

[layout.typescript]
test_paths = ["src"]

[libraries.typescript]
fakes = "vitest"
```

## Reasons

