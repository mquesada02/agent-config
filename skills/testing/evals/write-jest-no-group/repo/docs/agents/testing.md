# Testing rules

```toml
[[languages]]
name = "typescript"
root = "."

[commands.typescript]
test = "npx jest --ci"

[[groups]]
name = "changed"
language = "typescript"
size = "small"
command = "npx jest --ci --onlyChanged"

[runner.typescript]
name = "jest"

[layout.typescript]
test_paths = ["src"]

[libraries.typescript]
fakes = "jest"
```

## Reasons
