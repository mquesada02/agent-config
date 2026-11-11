---
type: llm
---
The setup report, and the checks `shown` and `allowlist` of grader D that the final message can show.

In a plugin eval the Write tool may be denied for the new allowlist file (it is outside the run folder). The allowlist proof for this case is then the flow test of the repo test command (grader D with services `app-dev`), and this grader checks the message.

Pass when the final message does all of these:

1. Names the formatter as `none` (the repo has no formatter tool), and names the other tools that the detector found (none, or the word none).
2. Names the three tags `sql`, `this.sql` and `tx`.
3. Names the service `app-dev`.
4. Says that the rules file `docs/agents/sql.md` was written.
5. For the allowlist file, either says that it was written, or (when the write was denied) shows its path and its exact text (`["example.com/acme/shop"]` and `services = ["app-dev"]`) and says that it was not written.
6. Shows or describes the diff that was shown before the files were written.

Fail when any item is missing, or when the message says that a formatter was installed.
