---
type: llm
---
The setup report for a repo with no SQL.

Pass when the final message does all of these:

1. Says that the repo has no SQL, and that no formatter detector ran (so there is no chosen tool to name beyond `none`).
2. Says that the tag list is empty.
3. Says that no service was set.
4. Says that the rules file `docs/agents/sql.md` was written.

Fail when it names a formatter tool that was detected, a tag, or a service.
