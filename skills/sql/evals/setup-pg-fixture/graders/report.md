---
type: llm
---
The setup report for a repo whose SQL is two `pg` statements.

Pass when the final message does all of these:

1. Says that the repo has SQL as `pg` statements, and that the formatter is `none`.
2. Says that the tag list is empty.
3. Says that the receivers are `pool` and `client`.
4. Says that no service was set.
5. Says that the rules file `docs/agents/sql.md` was written.

Fail when it names a formatter tool that was detected, a tag, or a service.
