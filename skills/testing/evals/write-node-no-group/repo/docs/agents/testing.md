# Testing rules

```toml
[[languages]]
name = "typescript"
root = "."

[commands.typescript]
test = "node --test"

[[groups]]
name = "only"
language = "typescript"
size = "small"
command = "node --test --test-only"

[runner.typescript]
name = "node:test"

[layout.typescript]
test_paths = ["src"]

[libraries.typescript]
fakes = "node:test"
```

## Reasons
