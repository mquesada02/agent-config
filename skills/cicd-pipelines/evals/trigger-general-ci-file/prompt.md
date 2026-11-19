---
max_turns: 10
allowed_tools: [Read, Glob, Grep, Skill]
---
In .gitlab-ci.yml, add a job `lint` that runs `golangci-lint run`.
The recorded intake output for this repo is in `intake.json`: use it as the repo facts and do not run the intake script.
