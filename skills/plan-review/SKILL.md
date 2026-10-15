---
name: plan-review
description: Use when reviewing a spec or a ticket breakdown - runs one parallel Sonnet reviewer per axis, labels each finding Blocking or Minor, and reports one section per axis. Spec mode is `/plan-review spec`. Tickets mode is `/plan-review tickets`.
---

# Plan Review

Review a spec (`/plan-review spec`) or a ticket breakdown (`/plan-review tickets`) with axes made for that document. Code reviews use `/mattpocock-skills:code-review`, not this skill.

Command form: `/plan-review <mode> [case] <links>`. `spec` takes a case word. `tickets` takes none.

## Modes

- `spec`: axes are in [spec-axes.md](spec-axes.md).
- `tickets`: axes are in [tickets-axes.md](tickets-axes.md).

## Inputs

All inputs are tracker links, never a paraphrase from the caller. The exceptions are the request quote, which is given word for word beside its link, and the findings ledger.

`spec general` (section 7 step 3), required:
- the spec
- the map
- the map's resolved decision tickets, including the decision comments the map links
- the user's request: a link to the issue or comment that records it, plus the request quoted word for word

`spec ticket` (section 7 step 5.3), required:
- the spec
- the ticket
- the map

`tickets` (section 7 step 4.1), required, with no case word:
- the general spec
- the ticket issues, each given as a link

Optional in every mode: the findings ledger, as a file path. The session that runs the plan-review loop keeps it (`CLAUDE.md` section 7).

## Process

1. Check the mode, the case and the inputs. Stop and ask the caller if an input is missing, if the mode is unknown, if the mode is `spec` and the case is missing or unknown, or if the mode is `tickets` and a case word is given. Never review without the full source.
2. Read the axis texts for the mode from its reference file.
3. Spawn exactly one subagent per axis in one message, so they run in parallel. Set a Sonnet model in each Agent call.
4. Give each subagent the link to the reviewed document (in tickets mode, every ticket issue link), the source links for its axis, its axis text and the Severity section below. Give it the ledger, when given, and tell it to report only findings that are new to the ledger. Each subagent returns findings labelled Blocking or Minor. Each Blocking finding quotes the line it rests on and states what breaks. Each Fidelity or Coverage finding quotes the line it rests on.
5. Report one heading per axis, in the order the reference file lists the axes (spec mode: Fidelity, Clarity, Codebase fit; tickets mode: Coverage, Slicing, Edges), without merging or reranking. Each axis ends with its Blocking and Minor counts and its most severe finding: the first Blocking finding in report order, else the first Minor finding in report order, else none. An axis with no findings says "No findings" and shows counts of zero.

## Source for each axis

- Fidelity: the source inputs of the case. Step 3: map, decision tickets, request. Step 5.3: ticket and map.
- Clarity: the spec alone.
- Codebase fit: the spec and the codebase. The reviewer reads the code.
- Coverage: the general spec and the ticket set.
- Slicing: the ticket set, and `~/.claude/CLAUDE.md` section 7 steps 5.1 to 5.5 for what one worker does.
- Edges: the ticket set and the codebase. The reviewer reads the code.

## Severity

- Blocking: a missing case, a contradiction, a mismatch with the source, an untestable decision. Every Blocking finding, including one that your axis text labels, counts as Minor without its quoted line and what breaks.
- Minor: wording, style, judgement calls.
- Where your axis text labels a case, that label wins over this list. The source is what your source links and your axis text name, including the code or `CLAUDE.md` where your axis text says to read them.
- Report findings for your own axis only.
