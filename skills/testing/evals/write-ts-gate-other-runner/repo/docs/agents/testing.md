# Testing rules

```toml
[[languages]]
name = "typescript"
root = "."

[commands.typescript]
test = "npx jest"

[[groups]]
name = "unit"
language = "typescript"
size = "small"
command = "npx jest"

[runner.typescript]
name = "jest"

[layout.typescript]
test_paths = ["src"]

[libraries.typescript]
fakes = "jest"
```

## Reasons

