# SQL rules

```toml
# hand-written: the team still argues about the case of keywords
[style]
keyword_case = "lower"
indent = "4 spaces"
clause_per_line = true
comma = "trailing"
alias_as = true

[formatter]
tool = "none"

[sources]
tags = ["sql"]

[rules]
disabled = []
```

## Repo rules

- Use CTEs for any query that joins more than 3 tables.
