---
type: llm
---
Grader B of seam 2 (the same check as the command `graders/only_target_changes.py`).

The fixture `reports.sql` has 5 lines. The target is line 3 (the second statement). Look at the file that the final message of Claude shows (the file after the first run). Pass when the first statement (`select id, name from customers where active;`) and the third statement (`select count(*) from orders;`) are unchanged, byte for byte (they stay lower case, on one line), and the blank lines between the statements are kept. Fail when any line outside the target changed.
