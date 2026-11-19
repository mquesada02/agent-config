---
max_turns: 40
allowed_tools: [Read, Glob, Grep, Skill, Bash, Edit, Write]
---
Update the test rules file for the repo in the current folder (the current folder is the repo root). Nobody can answer questions, so use these answers. Groups: add one group named `unit`, language `typescript`, size `small`, command `pnpm exec vitest run`. Limits: skip. Rule ids to disable: `RUN-05` again with the reason `slow CI hardware`, and `RUN-02` with no reason. Conventions: skip. When you show the table of differences, approve only the row of `runner.typescript.package_manager` (with the answers) and decline the other row.
