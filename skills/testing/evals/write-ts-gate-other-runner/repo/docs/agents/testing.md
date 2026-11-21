# Testing rules

```toml
[[languages]]
name = "typescript"
root = "."

[commands.typescript]
test = "npx mocha"

[[groups]]
name = "unit"
language = "typescript"
size = "small"
command = "npx mocha"

[runner.typescript]
name = "mocha"

[layout.typescript]
test_paths = ["src"]

[libraries.typescript]
fakes = "mocha"
```

## Reasons

