# Testing rules

```toml
[[languages]]
name = "typescript"
root = "."

[commands.typescript]
test = "node --test"

[[groups]]
name = "loopback"
language = "typescript"
size = "medium"
command = "node --test tests/"

[runner.typescript]
name = "node:test"

[layout.typescript]
test_paths = ["tests"]

[libraries.typescript]
fakes = "node:test"
```

## Reasons

