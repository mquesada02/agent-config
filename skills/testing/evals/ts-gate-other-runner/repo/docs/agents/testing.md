# Testing rules

```toml
[[languages]]
name = "typescript"
root = "."

[commands.typescript]
test = "npm test"

[runner.typescript]
name = "jest"

[layout.typescript]
test_paths = ["tests"]

[libraries.typescript]
fakes = "jest"
```

## Reasons

