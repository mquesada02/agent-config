---
type: llm
---
The folder has no rules file (`docs/agents/sql.md`). Pass when the final message of Claude suggests `/sql setup` (once) as a way to write the rules file. Fail when the final message does not mention `/sql setup`, or when Claude runs setup or writes a rules file without being asked.
