# Testing rules

```toml
[[languages]]
name = "rust"
root = "."

[commands.rust]
test = "cargo nextest run"

[[groups]]
name = "slow"
language = "rust"
size = "small"
command = "cargo nextest run -E 'test(slow_) & package(demo)'"

[runner.rust]
name = "nextest"

[layout.rust]
test_paths = ["tests"]

[libraries.rust]
fakes = "hand-written"
```

## Reasons

