# Testing rules

```toml
[[languages]]
name = "typescript"
root = "."

[commands.typescript]
test = "npm test"

[runner.typescript]
name = "vitest"

[layout.typescript]
test_paths = ["tests"]

[libraries.typescript]
fakes = "vitest"
```

## Reasons

