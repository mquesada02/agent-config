---
type: llm
arm: with-only
---
PASS if the draft (the whole new file, or the answers and the table) was shown in a message and the user approval was asked before the first Write or Edit of `docs/agents/testing.md` in the repo. A Write of a file in a temporary folder outside the repo is not a write of the rules file. FAIL otherwise.