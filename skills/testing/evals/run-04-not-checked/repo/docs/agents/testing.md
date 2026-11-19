# Testing rules

```toml
[[languages]]
name = "typescript"
root = "."

[commands.typescript]
test = "node --test --test-update-snapshots"

[[groups]]
name = "unit"
language = "typescript"
size = "small"
command = "node --test tests/"

[runner.typescript]
name = "node:test"

[layout.typescript]
test_paths = ["tests"]

[libraries.typescript]
fakes = "node:test"
```

## Reasons

