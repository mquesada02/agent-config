# Monorepo rules (MONO-*)

Which packages a monorepo runs on a PR and on main. This file is the single source of truth for these rules. The review loads it only when the intake `monorepo` fact has `monorepo: true`. A single package never loads it.

- "Mechanical" means a script or a regex can check the rule. "Judgement" means you decide.
- The severity is fixed for each rule. The first word of the Severity bullet is the level (`critical`, `required` or `suggestion`).
- No monorepo rule is critical.

### MONO-01
- **Severity:** required
- **Rule:** On a PR, a monorepo runs only the affected packages, with the tool that the repo already uses. The tools are `turbo run <task> --affected`, `nx affected -t <task>` with `nrwl/nx-set-shas`, or `pnpm --filter "...[origin/<base>]"`. Each needs `fetch-depth: 0`, and Turborepo also takes `filter: blob:none`. A push to main runs every package, so main always has a full result and avoids the base-commit edge cases.
- **Check:** mechanical with the intake facts: the `monorepo` fact (its `tool` is `turbo`, `nx`, `pnpm` or `workspaces`). The rule applies when the tool is `turbo` or `nx`, or when the workflow already runs the pnpm filter. A PR run that does not use the affected-only command of that tool, or that has no `fetch-depth: 0` for it, is a finding. A push to main that runs every package is never a finding.
- **Fix:** Run the affected-only command of the repo's own tool on PRs with `fetch-depth: 0` (and `filter: blob:none` for Turborepo), and keep the full run on main.

### MONO-02
- **Severity:** required
- **Rule:** When the repo has no monorepo tool, the skill proposes the pnpm filter, because pnpm is already in the repo. It does not add Turborepo or Nx.
- **Check:** mechanical with the intake facts: the `monorepo` fact has the tool `pnpm` (pnpm workspaces and no Turborepo or Nx) and the `package_manager` fact is pnpm, and a PR run runs every package with no filter. A monorepo with the tool `workspaces` (npm or yarn workspaces) gets no MONO finding.
- **Fix:** Run `pnpm --filter "...[origin/<base>]"` on PRs with `fetch-depth: 0`, and add no Turborepo or Nx dependency.
