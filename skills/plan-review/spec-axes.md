# Spec mode axes

Give each subagent its own axis text and the SKILL.md Severity section, not the other axes.

## Fidelity

Compare the spec with its source: the source links you were given. Report:
- requirements in the source that the spec does not have (missing)
- requirements in the spec that nobody asked for (extra)
- requirements that contradict the source

If you were given a quoted request, check it against its link. Quote the source line for each finding.

## Clarity

Read the spec alone. Check that:
- every decision is testable
- every acceptance criterion can be checked on its own (in a spec without an acceptance-criteria section: every user story and testing decision)
- open questions are listed, or the spec says there are none
- out of scope is stated
- the spec does not contradict itself

## Codebase fit

Read the spec and the real code. Check that the seams, modules, names and files that the spec mentions exist in the code, or that the spec says they are new.
