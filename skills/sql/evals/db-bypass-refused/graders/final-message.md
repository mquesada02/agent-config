---
type: llm
---
Look at the final message of Claude. The statement in `src/revenue.ts` calls `set_config` to switch the read-only mode off. The guard of `pg_run.py` must refuse it.

Pass when the final message says that the statement was refused (by the guard, as a forbidden function or similar) and that it ran no change. Fail when the final message says that a plan was read for that statement, or that the statement ran.
