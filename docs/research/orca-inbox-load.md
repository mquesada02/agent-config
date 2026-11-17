# Where the owner's time goes in the current workflow

Ticket 755 of map 752 (request 750). Date of reading: 2026-11-17. Marks: **FACT** = counted or quoted from a source. **INFERENCE** = our reading. This file answers a question; it decides nothing for the owner.

## Question

What does the owner do by hand today, and how often? Count, by type, the owner questions (asks, cap extensions, `AskUserQuestion`), approvals, `!` commands, merge commands and broadcast handling, from local transcripts, ledgers and Orca messages of recent efforts. Then judge proposals 740 to 747 again against this data.

## Short answer

1. FACT: in 38 active days (2026-09-11 to 2026-11-17) the owner typed about 5,000 prompts, answered about 3,360 multiple-choice questions and ran about 1,700 `!` commands across 1,157 sessions.
2. FACT: 88 percent of the answered questions (2,958 of 3,363) took the recommended or first option. Only 49 got free text. The owner mostly confirms.
3. FACT: 2,046 of 4,204 counted text prompts (49 percent) are 20 characters or fewer ("1", "yes", "go", "a", "ok", "done", "merge"). Half of the owner turns are one-word go-aheads.
4. FACT: merges and PR creation need the owner: 786 `! gh pr merge` or `! gh pr create` commands, plus 195 merge questions and 204 failed-audit questions.
5. FACT: 178 questions ask for a review-cap extension; the owner took the recommended answer 151 times and never wrote free text.
6. FACT: coordinators got 1,496 "you have N orchestration messages" notices and 1,422 worker asks were sent; coordinators sent 813 replies. INFERENCE: most worker asks are answered by the coordinator, and the owner sees only a part.
7. FACT: 295 restart broadcasts reached sessions (62 plain, 118 coordinator, 115 worker).
8. INFERENCE: the owner's cost is many small, mostly predictable decisions in many terminals, not a few hard ones. Proposals 740, 741, 744 and the cap and merge delegation fit this data best.

## Findings (with sources)

All counts come from one script that I ran over the local session transcripts and from `gh`. The scripts are in my scratchpad, not in the repo. I publish counts and types only. Method limits are in "Gaps".

### F1. Scope of the data

- FACT: 1,157 top-level sessions (subagent files excluded). Source: transcripts under `~/.claude/projects` (command: a Python script over every `*.jsonl`).
- FACT: roles, by a rule on the content: 325 plain sessions, 129 coordinators, 703 workers.
- FACT: 3 groups, by repo path: a work group of about 20 repos (253 sessions), a second product group of 4 repos (170), a personal group of 8 repos (734).
- FACT: the data spans 2026-09-11 to 2026-11-17 with 38 active days. The week of 2026-11-09 holds 517 sessions and 1,856 prompts, the peak.

### F2. Prompts, by size

- FACT: owner prompts counted (not tool results, not Orca notices, not worker briefs, not hook text): plain 1,503, coordinator 3,347, worker terminals 194.
- FACT: by length: at most 20 characters 2,046; 21 to 100 characters 1,312; 101 to 500 characters 757; over 500 characters 89 (this length count covers a smaller set of prompts than the totals above; same script, human-origin string prompts only).
- FACT: the most frequent short prompts: "1" 189, "yes" 136, "go" 89, "a" 88, "ok" 86, "done" 68, "post" 49, "merge" 36, "what's the state" 29, "merge it" 29.
- INFERENCE: about half of the prompts need little thought: they answer a numbered list, confirm, or tell the session to continue.

### F3. `AskUserQuestion`

- FACT: 2,624 calls (656 plain, 1,968 coordinator) with 3,696 questions. Questions per call: 1 → 2,038; 2 → 289; 3 → 117; 4 → 180; 5 or 6 → 2.
- FACT: types of 3,363 answered questions (keyword class of the question text, so approximate):

| Type | Asked | Took recommended/first | Free text |
|---|---|---|---|
| Design and other | 2,329 | 2,035 | 42 |
| Approve spec or tickets | 301 | 277 | 4 |
| Failed audit (override or fix?) | 204 | 178 | 0 |
| Merge | 195 | 177 | 1 |
| Cap extension | 178 | 151 | 0 |
| Size approval | 156 | 140 | 2 |
| All | 3,363 | 2,958 (88%) | 49 (1.5%) |

- FACT: 356 questions (3,363 − 2,958 − 49) took another listed option or could not be matched to an answer.
- FACT: owner answer time per question call (time from the call to its tool result): median 51 s; 1,433 of 2,623 within 60 s; 431 over 5 minutes; 92 over 1 hour. Total: about 209 hours if each wait is capped at 1 hour; 901 hours uncapped. INFERENCE: the uncapped number counts nights and breaks; the real owner effort is the 1,433 quick answers plus the long tails that block a session.

### F4. Cap extensions and failed audits

- FACT: 178 cap questions; ledger extension commands run: 225 (plain 39, coordinator 186, worker 5; this count includes retries and several loops of one task).
- FACT: one long task in the transcripts needed five 1-round extensions on top of the cap of 3 for a single code-review phase (read from an audit report in a coordinator transcript; no name given).
- INFERENCE: caps are a gate the owner passes almost every time (151 of 178 on the recommended answer). They cost a question and a turn each, not a decision.
- FACT: 204 questions about a failed audit; 178 took the recommended answer.

### F5. `!` commands

- FACT: 1,703 `!` commands (bash-input records): plain 234, coordinator 1,469.
- FACT: by type, plain + coordinator: `gh pr merge` 642; `gh pr create` 144; worktree cleanup 193; settings or git changes 45; other 679 (for example fixes to hook state, `git` operations, one-off checks; not classified further).
- FACT: sessions told the owner to run `! gh pr merge` 912 times and `! gh pr create` 392 times (text of agent messages; one message can repeat across turns, so this overcounts).
- FACT: agent-config merged 211 PRs from 2026-10-12 to 2026-11-17. Source: `gh pr list --repo <this repo> --state merged --json number,mergedAt`, counted after 2026-10-12. This is only one repo; the 642 merge commands cover all 3 groups.
- INFERENCE: every PR costs the owner at least one merge command and often a create command (the audit gate blocks the session; the owner overrides by hand). Memory records that auto mode blocks `gh pr merge`.

### F6. Orca messages and broadcasts

- FACT: coordinators received 1,496 "You have N orchestration message(s)" notices (all roles together, by group: personal 1,003, second 170, work 733; the sum is higher because workers also get notices, 410). Each notice interrupts the coordinator turn, not the owner directly.
- FACT: workers sent 1,422 `ask` commands and 758 `worker_done`; coordinators sent 813 replies and started 896 workers (counts include retries; one worker can have several terminals).
- INFERENCE: asks sent (1,422) are more than replies (813): some asks were answered through another path (terminal send, or the owner typed in the worker terminal; 194 prompts exist in worker terminals), and some are counted from retries. The data does not say how many asks reached the owner.
- FACT: restart broadcasts ("Orca or the PC restarted…"): 295 in total (plain 62, coordinator 118, worker 115). Each restored session must be told what to do again.

### F7. Context breaks

- FACT: 264 "This session is being continued" records (plain 34, coordinator 130, worker 100). The owner is not asked at these, but the work stops and a successor restarts.

### F8. The weeks

- FACT: sessions per week from the first week with ten or more: 57, 111, 207, 125, 517, then 127 for a partial week (2026-10-12 onward). Prompts: 488, 498, 858, 599, 1,856, 301.
- INFERENCE: owner load grew about 4 times from mid-October to mid-November, with the number of parallel efforts. It tracks sessions, not a fixed workload.

## Proposals 740 to 747, judged again

These are the 8 proposals of `docs/research/agent-workflow-comparison.md`, section 6 (issue 740 = P1 … issue 747 = P8). I read each issue and checked that it matches the section. The judgement below uses only the load data above. "Fit" = how much of the measured load the proposal can remove. I decide nothing.

| Issue | Proposal | Load it targets | Fit | Note |
|---|---|---|---|---|
| 740 | P1 rulings, 4 stop conditions | worker asks (1,422) and coordinator relays (813) | High | The owner sees few asks directly; the gain is less coordinator relay and fewer worker stalls. Cost: wrong rulings found late. |
| 741 | P2 one ranked batch, recommended answer | 3,363 questions, 88% already take the recommended answer | Medium | Most calls already hold one question (2,038 of 2,624). The owner already answers fast (median 51 s). A batch saves turns, not decisions. |
| 742 | P3 always a map, size the rest by facts | spec, tickets, 301 approval questions, 156 size questions | Medium to high | 92% of spec and ticket approvals use the recommended answer: those gates rarely change anything. Cost: this is the small-task path in new form. |
| 743 | P4 write the spec once | repeated grilling and approval | Medium | The data has no count of how many questions come from the per-ticket spec. INFERENCE only. |
| 744 | P5 verifier only if no test | agent time, not owner time | Low for the owner | The owner is not in this loop. It helps wall-clock time, not the owner's load. |
| 745 | P6 reviewer brief | fewer rounds, fewer caps | Medium | 178 cap questions come from rounds that did not converge. Fewer low-value findings could reduce them. No data on the cause per cap. |
| 746 | P7 evidence serves a job | 204 failed-audit questions | Medium | Failed audits are 6% of questions. Some failures are record keeping, not defects (INFERENCE from the transcripts' audit reports). |
| 747 | P8 workers only for independent tickets | worker asks, restarts (295 broadcasts) | Medium | Fewer workers means fewer terminals and fewer restart recoveries. It costs parallel speed. |

INFERENCE on the whole set: none of the 8 proposals targets the two largest owner items directly: the 642 merge commands and the 3,363 mostly-confirming questions. Cap extensions (178), failed-audit questions (204) and merges (195) total 577 questions, about 17 percent. They are routine and fit a delegated decision (the owner said they would delegate merges and cap extensions).

## Options for the owner

Each option has its cost. They are not exclusive.

1. **Delegate cap extensions to the coordinator, within a hard limit** (for example one extension per phase, then ask). Removes up to 178 questions of the 3,363 (5 percent) with 85 percent approval already. Cost: a loop can run longer; the limit must be set; the audit rule on `extension` events (which quotes the owner's words) needs a new source of approval.
2. **Delegate merges to the coordinator when CI is green and the audit passed.** Targets about 195 merge questions and about 640 `!` commands. Cost: the audit hook and auto mode both block `gh pr merge` today, so this needs a rule change that the owner approves; a wrong merge cannot be undone by the coordinator.
3. **Ask once per effort, not once per gate.** The owner approves the spec; later steps (tickets, caps, size) proceed unless a stop condition holds. Targets 301 + 156 + 178 approval-type questions. Cost: the owner sees fewer decision points; errors surface later (see 740 cost line).
4. **Make "recommended" the default after a short timeout in a coordinator.** The coordinator acts on its own recommendation after N minutes if the owner has not answered. Targets the 92 waits over 1 hour and the 431 over 5 minutes. Cost: a session acts without the owner; unsafe for destructive or security actions; needs the stop list of 740.
5. **Collect asks in one inbox per group** (the main goal of map 752). The data supports the need: 1,496 notices and 1,422 asks across many terminals. Cost: a new central session; the other research tickets decide its design.

## Gaps and open questions

- The script classifies sessions by path rule and keywords. Question types ("design and other" is the rest class) and `!` types are approximate; a few may be wrong in either direction.
- The transcripts cover only sessions that still exist on disk. Orca's own message log was not read, so asks that never reached a transcript are not counted. Ask counts include retries.
- No timing exists for how long the owner spends reading a question, only the time until the answer. Answer time includes time away from the PC.
- The transcript does not link a worker ask to the owner question it caused. INFERENCE only.
- The data starts at 2026-09-11 and the workflow changed during the period (audit gates, caps, branch hook). Counts of a given type may drop after a rule change; I did not split by rule version.
- Ledger counts come from the commands in transcripts, not from `audit ledger show` of each worktree (most worktrees are gone). Extension counts include repeated commands.
- Haiku or model choice is out of scope here (ticket 758).

## Sources read and sources that failed

Read:
- `docs/research/agent-workflow-comparison.md` (this repo), sections 1 to 6.
- Issue 752 (map) and issue 755 (ticket), and issues 740 to 747, through `gh api repos/<this repo>/issues/<n>` (the `gh issue view` command fails on a GraphQL deprecation).
- Local transcripts: every top-level `*.jsonl` under `~/.claude/projects` (about 1,157 sessions with data), read by Python scripts. Command output shown above.
- `gh pr list --state merged` for this repo (count of 211 merged PRs after 2026-10-12).

Failed or not done:
- The first `gh api` call for issue 755 was blocked once by a hook that changed the command, and succeeded on retry.
- Orca message logs, per-worktree ledgers and the owner's own clock were not read.
- I started no research subagent. The question needed counting over local data, which a script does better and with no private text leaving this machine.
