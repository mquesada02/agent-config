# Testing rules

```toml
[[languages]]
name = "typescript"
root = "."

[commands.typescript]
test = "npx jest --updateSnapshot"

[[groups]]
name = "unit"
language = "typescript"
size = "small"
command = "npx jest --updateSnapshot"

[runner.typescript]
name = "jest"

[layout.typescript]
test_paths = ["tests"]

[libraries.typescript]
fakes = "jest"
```

## Reasons
