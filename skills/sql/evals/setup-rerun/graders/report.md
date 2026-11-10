---
type: llm
---
The setup report of the re-run.

Pass when the final message does all of these:

1. Names the formatter as `none`, and names the other tools that the detector found (none, or the word none).
2. Names the tag `sql` and the service `app-dev`.
3. Says that the rules file was written, and which keys changed (`keyword_case`), and that the current `indent` was kept.
4. Says that the new rule was appended and that the hand-written rule and comment were kept.

Fail when any item is missing.
