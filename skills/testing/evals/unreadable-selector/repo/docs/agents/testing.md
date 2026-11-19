# Testing rules

```toml
[[languages]]
name = "typescript"
root = "."

[commands.typescript]
test = "node --test"

[[groups]]
name = "slow"
language = "typescript"
size = "small"
command = "sh scripts/run-slow.sh"

[runner.typescript]
name = "node:test"

[layout.typescript]
test_paths = ["tests"]

[libraries.typescript]
fakes = "node:test"
```

## Reasons

