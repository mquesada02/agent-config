# Tickets mode axes

Give each subagent its own axis text and the SKILL.md Severity section, not the other axes.

## Coverage

Compare the general spec with the ticket set (the ticket issues you were given as links). Report:
- each spec requirement or acceptance criterion that maps to no ticket (missing, Blocking)
- each ticket requirement that no line of the spec states, including enabling work or refactoring that the spec does not name (extra, Minor)

Quote the line each finding rests on: the spec line for a missing requirement, the ticket line for an extra one.

Report coverage only. Slice shape, ticket size and blocking edges belong to the other axes.

## Slicing

Read the ticket set (the ticket issues you were given as links). Use `~/.claude/CLAUDE.md` section 7 steps 5.1 to 5.5 for what one worker does. Check that:
- each ticket is a vertical slice: it crosses every layer it needs and delivers one behavior that can be checked, not one layer or one technical task with no checkable behavior of its own (a horizontal slice is Blocking)
- one worker can finish each ticket through steps 5.1 to 5.5 (judge this from the ticket's scope; a ticket too big for one worker is Blocking)
- each ticket has its own acceptance criteria that can be checked on their own (a ticket without them is Blocking)
- a wide refactor (one that moves callers in several modules) uses expand-contract: add the new form, move the callers in batches, then remove the old form (a wide refactor in one ticket is Blocking). The add, move and remove steps may each be their own ticket. Such a ticket is not a horizontal slice when its acceptance criteria say what still works after it

## Edges

Read the ticket set (the ticket issues you were given as links) and the real code. Check that:
- blocking edges are correct (each edge is a real dependency) and complete (each real dependency has an edge); a wrong or missing edge is Blocking
- the graph has no cycle (a cycle is Blocking)
- no two tickets that blocking edges do not order (directly or through other tickets) have scopes that change the same seam (a seam is a file, module or interface in the codebase); such a pair is Blocking
