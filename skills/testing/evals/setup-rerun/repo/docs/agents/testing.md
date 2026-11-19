# Test rules

This file records the test rules of the repo.

```toml
groups = []

[[languages]]
name = "typescript"
root = "."

[commands.typescript]
test = "npx vitest run"
worker_flag = "--maxWorkers"
changed = "--changed"

[runner.typescript]
name = "vitest"
package_manager = "npm"
module_format = "esm"

[layout.typescript]
test_paths = ["tests"]
file_pattern = ["**/*.{test,spec}.?(c|m)[jt]s?(x)"]

[libraries.typescript]
fakes = []

[limits]
small_ms = 200

[rules]
disabled = ["RUN-05"]
```

## Disabled rules

- RUN-05: slow CI hardware

## Conventions

- Keep tests small.
