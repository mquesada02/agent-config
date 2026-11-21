# Testing rules

```toml
[[languages]]
name = "typescript"
root = "."

[commands.typescript]
test = "npx jest --ci"

[[groups]]
name = "wrapped"
language = "typescript"
size = "small"
command = "npm run unit"

[[groups]]
name = "watching"
language = "typescript"
size = "small"
command = "npx jest --watch"

[runner.typescript]
name = "jest"

[layout.typescript]
test_paths = ["tests"]

[libraries.typescript]
fakes = "jest"
```

## Reasons
