# Testing rules

```toml
[[languages]]
name = "typescript"
root = "."

[commands.typescript]
test = "node --test"

[[groups]]
name = "wrapped"
language = "typescript"
size = "small"
command = "npm run unit"

[[groups]]
name = "sharded"
language = "typescript"
size = "small"
command = "node --test --test-shard=1/2"

[runner.typescript]
name = "node:test"

[layout.typescript]
test_paths = ["tests"]

[libraries.typescript]
fakes = "node:test"
```

## Reasons
