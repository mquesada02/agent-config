---
max_turns: 10
allowed_tools: [Read, Glob, Grep, Skill]
---
In .github/workflows/ci.yml, rename the job `build-and-test` to `test`, and add a job `lint` that runs `pnpm lint`.
