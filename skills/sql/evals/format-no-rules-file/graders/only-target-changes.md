---
type: llm
---
Grader B of seam 2 (the same check as the command `graders/only_target_changes.py`).

The fixture `notes-store.ts` has 5 lines. The target is line 5 (the whole `listNotes` template is on that line). Look at the file that the final message of Claude shows (the file after the first run). Pass when the first four lines (the `import` line, a blank line, the `const sql` line and a blank line) are unchanged. Fail when any of them changed.
