# Maintainability rules (MAINT-*)

How long the workflow file grows. This file is the single source of truth for these rules. Both branches of the skill load it.

- "Mechanical" means a script or a regex can check the rule. "Judgement" means you decide.
- The severity is fixed for each rule. The first word of the Severity bullet is the level (`critical`, `required` or `suggestion`).
- No maintainability rule is critical.

### MAINT-01
- **Severity:** required
- **Rule:** A `run:` block of more than 10 lines moves to a repo script (for example `scripts/ci/<name>.sh`) that a developer can also run locally. The step calls the script.
- **Check:** mechanical
- **Fix:** Move the `run:` block to a repo script such as `scripts/ci/<name>.sh`, and make the step call that script.

### MAINT-02
- **Severity:** required
- **Rule:** A comment on a step is 3 lines or less. Longer reasons go in the docs or the PR.
- **Check:** mechanical
- **Fix:** Cut the step comment to 3 lines or less, and move the longer reason to the docs or the PR.

### MAINT-03
- **Severity:** suggestion
- **Rule:** When the user names other repos, and the same workflow is copied across them, the report proposes a reusable workflow or a composite action. This is a suggestion only, because it touches other repos. The skill cannot see other repos unless the user names them.
- **Check:** judgement, only on request
- **Fix:** Propose a reusable workflow or a composite action for the copied workflow, and change no other repo.
