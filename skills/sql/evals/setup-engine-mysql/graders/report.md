---
type: llm
---
The setup report for a repo whose engine is MySQL.

Pass when the final message does all of these:

1. Names the confirmed engine `mysql`, and says that setup detected it from the `mysql2` dependency.
2. Says that the formatter is `none`, and that the tag list is empty.
3. Says that no service was set, or that the PG service step was skipped because the engine is not PostgreSQL.
4. Says that the rules file `docs/agents/sql.md` was written.

Fail when it names a PG service, a tag, or a connection string.
