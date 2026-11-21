# Testing rules

```toml
[[languages]]
name = "typescript"
root = "."

[commands.typescript]
test = "npx jest --ci"

[[groups]]
name = "fast"
language = "typescript"
size = "small"
command = "npx jest --ci --testPathIgnorePatterns tests/slow"

[runner.typescript]
name = "jest"

[layout.typescript]
test_paths = ["tests"]

[libraries.typescript]
fakes = "jest"
```

## Reasons
