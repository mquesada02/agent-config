---
type: llm
---
Grader B of seam 2 (the same check as the command `graders/only_target_changes.py`).

The fixture `reports.sql` has 5 lines: `select id, name from customers where active;` (line 1), an empty line, the target statement (line 3), an empty line, and `select count(*) from orders;` (line 5). The target is line 3.

Look at the file that the final message of Claude shows (the file after the first run). Pass when line 1 is still exactly `select id, name from customers where active;` (lower case), the last line is still exactly `select count(*) from orders;` (lower case), and one empty line separates each of them from the target. Fail when either of them changed, even in white space or case. The target itself may grow to many lines.
