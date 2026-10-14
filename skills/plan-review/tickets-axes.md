# Tickets mode axes

Give each subagent its own axis text only. Each finding is labelled Blocking or Minor (see SKILL.md).

## Coverage

Compare the general spec with the ticket set. Report:
- each spec requirement or acceptance criterion that maps to no ticket (missing)
- each ticket requirement that no line of the spec states, including enabling work or refactoring that the spec does not name (extra)

Quote the source line for each finding.

## Slicing

Read the ticket set. Use `CLAUDE.md` section 7 steps 5.1 to 5.5 for what one worker does. Check that:
- each ticket is a vertical slice: it crosses every layer it needs and delivers one behavior that can be checked, not one layer or one technical task with no checkable behavior of its own (a horizontal slice is Blocking)
- one worker can finish each ticket through steps 5.1 to 5.5 (judge this from the ticket's scope)
- each ticket has its own acceptance criteria that can be checked on their own
- a wide refactor uses expand-contract: add the new form, move the callers in batches, then remove the old form (a wide refactor in one ticket is a finding)

## Edges

Read the ticket set and the real code. Check that:
- blocking edges are correct (each edge is a real dependency) and complete (each real dependency has an edge); a wrong or missing edge is Blocking
- the graph has no cycle
- no two tickets without an edge between them change the same seam (a seam is a file, module or interface in the codebase)
