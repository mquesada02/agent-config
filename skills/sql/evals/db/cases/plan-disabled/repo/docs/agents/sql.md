# SQL rules

```toml
[sources]
tags = ["sql"]

[rules]
disabled = ["PLAN-02"]
```

- PLAN-02: we keep this sequential scan on purpose (the table is small in production).
