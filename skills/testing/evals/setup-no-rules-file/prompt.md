---
max_turns: 40
allowed_tools: [Read, Glob, Grep, Skill, Bash, Edit, Write]
---
Set up the test rules file for the repo in the current folder (the current folder is the repo root). Nobody can answer questions, so use these answers. Groups: one group named `unit`, language `typescript`, size `small`, command `npx vitest run`. Limits: skip. Rule ids to disable: `RUN-05` with the reason `slow CI hardware`, and `FOO-99` with the reason `not needed`. Conventions: one line, `Keep tests small.` Show me the draft, then approve it and write the file. In your final message, give the setup report.
