# Testing rules

```toml
[[languages]]
name = "typescript"
root = "."

[commands.typescript
test = "node --test"

[[groups]]
name = "unit"
language = "typescript"
size = "small"
command = "node --test tests/unit/"

[runner.typescript]
name = "node:test"

[layout.typescript]
test_paths = ["tests"]

[libraries.typescript]
fakes = "node:test"
```

## Reasons
