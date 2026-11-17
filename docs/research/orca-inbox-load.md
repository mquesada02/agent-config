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
8. INFERENCE: the owner's cost is many small, mostly predictable decisions in many terminals, not a few hard ones. Read with the other five research files, proposal 740 fits worker asks best and 742, 745 to 747 fit in part; 741, 743 and 744 add little for the owner. No proposal covers merges, cap extensions or an owner queue across Runs (section "Proposals 740 to 747, judged again").

## Findings (with sources)

All counts come from one script that I ran over the local session transcripts and from `gh`. The scripts are not in the repo. I publish counts and types only. Method limits are in "Gaps".

### F1. Scope of the data

- FACT: 1,157 top-level sessions (subagent files excluded). Source: the local session transcripts (command: a Python script over every top-level transcript file).
- FACT: roles, by a rule on the content: 325 plain sessions, 129 coordinators, 703 workers.
- FACT: 3 project groups, by repo path: a work group, a second product group and a personal group.
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

- FACT: coordinators received 1,496 "You have N orchestration message(s)" notices; workers received 410 more (1,906 in all roles). Each notice interrupts the coordinator turn, not the owner directly.
- FACT: workers sent 1,422 `ask` commands and 758 `worker_done`; coordinators sent 813 replies and started 896 workers (counts include retries; one worker can have several terminals).
- INFERENCE: asks sent (1,422) are more than replies (813): some asks were answered through another path (terminal send, or the owner typed in the worker terminal; 194 prompts exist in worker terminals), and some are counted from retries. The data does not say how many asks reached the owner.
- FACT: restart broadcasts ("Orca or the PC restarted…"): 295 in total (plain 62, coordinator 118, worker 115). Each restored session must be told what to do again.

### F7. Context breaks

- FACT: 264 "This session is being continued" records (plain 34, coordinator 130, worker 100). The owner is not asked at these, but the work stops and a successor restarts.

### F8. The weeks

- FACT: sessions per week from the first week with ten or more: 57, 111, 207, 125, 517, then 127 for a partial week (2026-10-12 onward). Prompts: 488, 498, 858, 599, 1,856, 301.
- INFERENCE: owner load grew about 4 times from mid-October to mid-November, with the number of parallel efforts. It tracks sessions, not a fixed workload.

## Proposals 740 to 747, judged again

These are the 8 proposals of `docs/research/agent-workflow-comparison.md`, section 6 (issue 740 = P1 … issue 747 = P8). I read each issue and checked that it matches the section. Each reading below rests on two things: my load data (F1 to F8 above) and facts from the five other research files of map 752.

**Source notes.** A note such as (reliab F3) means the file `docs/research/orca-inbox-reliab.md`, section F3. The five files sit next to this file in `docs/research/`: `orca` (ticket 753), `oss` (754), `tests` (756), `reliab` (757), `haiku` (758). Each fact keeps the mark (FACT, INFERENCE) that its file gave it. "Reading" lines are my INFERENCE.

### 740 (P1): workers log rulings and ask only on four stop conditions

- **My load data.** Workers sent 1,422 `ask` commands; coordinators sent 813 replies (F6). Owner questions: 3,363, of which 88 percent took the recommended option (F3).
- **Other files.**
  - FACT: Orca's own worker preamble and `ask --help` say "end your turn" after an ask, while `CLAUDE.md` section 7 says never to end it (reliab F1). Fewer asks mean fewer chances for this conflict; reliab O1 removes the conflict itself.
  - FACT: four October cases of 1.5 to 7 hours idle after an ask (reliab F3). After the rules were added, turn-end cases still happened on 5 later days, with no work lost (reliab F3, F4).
  - FACT: Gas Town routes an escalation "Deacon -> Mayor -> Overseer based on severity"; "Each tier can resolve OR forward" (oss 3.2). Squadra gives the owner "the options, a recommendation and the exact words to answer" (oss 3.5). Both are README-level sources.
- **Reading.** Strong fit for the worker-ask load. Two limits. (1) P1 keeps an ask for an irreversible action and keeps the stop at a review cap and at a failed audit (prior file, P1 "Change" and "Cost"). My data says merge (195), cap (178) and failed-audit (204) questions are 577 of 3,363. P1 as written does not remove them. (2) P1 lowers the number of asks but does not fix a turn-end with no ask open (reliab F4 and its sources section).

### 741 (P2): one ranked batch with a recommended answer

- **My load data.** 2,038 of 2,624 question calls hold one question (F3). 88 percent of answers took the recommended or first option (F3). Median answer time 51 s; 431 answers took over 5 minutes and 92 over 1 hour (F3).
- **Other files.**
  - FACT: Squadra and Novadeck already offer options with a recommendation or a click answer (oss 3.5).
  - FACT: cmux parks an agent request until the human answers in a sidebar, a TUI or a desktop notification (oss 3.1).
  - FACT: Orca has no owner-facing queue that ranks "needs the owner" across Runs (orca 6, item 1), and no page read says a `question` message alone pushes to the phone (orca 3.7).
- **Reading.** The recommended-answer part is mostly in place already (88 percent). A batch saves a turn, not a decision. The costly part of the data is the tail of slow answers (431 over 5 minutes), and a batch does not shorten a wait. The other files point at the place where the owner sees the question (an inbox or a push) as the lever. Medium to low fit for the owner load.

### 742 (P3): always a map, but size the rest by facts the session can check

- **My load data.** 301 spec or ticket approval questions (92 percent recommended) and 156 size approval questions (90 percent recommended: 140 of 156) (F3).
- **Other files.**
  - FACT: no rule exists for docs-only changes; a docs-only change still runs the full declared test command (audit item S2), the section 6 loop and the audit (tests F2, F5).
  - FACT: only S2 depends on the test run; S3 to S10 depend on the loop and not on file type (tests F5).
  - FACT: Markdown is not inert here: 44 test files read `.md` files, so a docs edit can change a test result (tests F5).
  - FACT: S2 requires that the exact declared command ran after the last edit (tests F1).
- **Reading.** P3 removes tickets, ticket review and the pre-dispatch audit for single tasks, which are approval gates the owner passes almost every time (92 and 90 percent). It does not touch the S2 run. A foreground run is cut at about 600 s (tests F3), and issue 729 is still open (tests F4). So the owner-visible saving of P3 depends on the test-run options of the `tests` file (background run with a wait, an S2 fix for auto-backgrounded calls). Medium to high fit; the sizing facts need a written rule.

### 743 (P4): write the spec once

- **My load data.** No count links an owner question to the per-ticket spec step. This is a gap (see Gaps). The 301 approval questions mix both spec steps.
- **Other files.**
  - FACT: Squadra keeps assignments, decisions and checks in one shared registry per project (oss 3.5); Orchvia stores tasks and messages before anything runs (oss 3.5). Neither says anything about a per-ticket spec.
  - FACT: after a restart the coordinator wrote a resume note from the state of the worktree for the new worker (reliab F6). INFERENCE (mine): a ticket that links the general spec sections gives such a note a fixed source.
- **Reading.** No file gives data that confirms or refutes P4. Fit for the owner load: unknown. Keep the earlier reading: it removes a second spec and a second review loop, at a cost to the audit evidence for `plan-review-5.3`.

### 744 (P5): verifier subagent only where no reproducing test can be written

- **My load data.** The owner is not in this loop. No owner count applies.
- **Other files.**
  - FACT: S2 counts only the exact declared command, not a targeted test run (tests F1). INFERENCE (mine): a reproducing test run for one finding does not conflict with S2, and does not replace the full run.
  - FACT: on one synthetic task, a Haiku verifier rejected a false finding with a correct trace, as Sonnet did (haiku 3.6, task 4). It is one run (n = 1); haiku 4 rates the verifier role "Unclear".
  - FACT: Anthropic says Haiku 5.5 "sometimes reports a code change as done without running a check" at low and medium effort (haiku 3.2).
- **Reading.** Low fit for the owner load, as before. The other files add one point: the no-test path (security, design, spec mismatch) is where a verifier is needed, and the haiku file gives no ground to put a non-Sonnet model there. Every workflow agent stays on Sonnet by the map rule.

### 745 (P6): reviewer brief: correctness only, stop at low-value notes, "not run" status

- **My load data.** 178 cap-extension questions (85 percent recommended) and 204 failed-audit questions (87 percent recommended) (F3, F4). The data does not say which caps came from low-value findings.
- **Other files.**
  - FACT: in a small test a Haiku reviewer found both planted bugs but added three unrequested Minor findings to a correct diff; Sonnet said "no findings" (haiku 3.6, tasks 2 and 3). One run per cell, synthetic input.
  - FACT: the "0 of 10 planted defects" report that the prior file quotes in its section 3.5 was found only in a secondary issue; the wording was not found in the Superpowers pages (haiku 3.5, haiku 6). A report on the other side says 5 of 5 (haiku 3.5). INFERENCE (haiku 3.5): two small, opposite reports.
- **Reading.** The cap load is real (178 questions), but no file shows what drives the rounds. P6's "stop at low-value notes" targets a plausible cause; this is unproved. The evidence for P6 in the prior file rests on a Superpowers run and docs, not on a Haiku number, so the haiku file does not change it. It adds one caution: a noisier reviewer produces more Minor findings, so a cheaper model would raise the deferred-Minor load. Medium fit.

### 746 (P7): make the written evidence serve a job and shrink the rest

- **My load data.** 204 failed-audit questions, 6 percent of all (F3). 786 `! gh pr merge` or `! gh pr create` commands (F5); the audit gate blocks `gh pr create` for the session until a passing record exists (`CLAUDE.md` section 8).
- **Other files.**
  - FACT: in 852 audit records, S2 passed in 608; 129 failed for a missing test declaration (records of other repos), 12 did not run, 7 ran and failed or did not finish, 1 ran only before the last edit (tests F1). INFERENCE (tests F1): S2 rarely fails on the order rule here.
  - FACT: an auto-backgrounded call can pass S2 with empty stdout even if the suite fails later; this is read from code and one live example, not tested (tests F4; issue 729).
  - FACT: other tools record a decision with the owner's own words (Squadra `decision --owner-words`) or stop a result from counting as done until a person or a registered check accepts it (Orchvia) (oss 3.5).
- **Reading.** The tests file gives the first concrete example of the P7 idea: a record that may not prove the rule it names (S2 and issue 729). The per-record review that P7 asks for is supported. The data does not split the 204 failed-audit questions by audit item, so the saving to the owner is unknown. Medium fit.

### 747 (P8): dispatch workers only for independent tickets

- **My load data.** 703 of 1,157 sessions are workers (61 percent); 896 `worker-start` commands; 295 restart broadcasts (F1, F6); 1,422 asks (F6).
- **Other files.**
  - FACT: after a PC restart Orca closed the old dispatch as lost, the Task went back to `ready`, and `--retry-of` was refused (`task_not_startable`); the recovery was a plain `worker-start` on the same worktree plus a resume note, needing the coordinator (reliab F6, F7). The same error is in at least three coordinator logs (reliab F6).
  - FACT: no Orca code was found that restarts a dead worker terminal or expires a pending ask (reliab F8, Gaps).
  - FACT: two logged cases of a worker ending its turn with no ask open and no `worker_done` (reliab F4).
  - FACT: Claude Code agent teams allow one team per session and no nested teams (oss 3.2). Orca allows nested workers to a default depth of 4 (orca 3.12). Gas Town gives each repo its own rig under one Mayor (oss 3.2).
  - FACT: the worker role stays on Sonnet: Haiku 5.5 scores 39.2 percent against 70.6 percent for Sonnet on Terminal-Bench 4.0 (haiku 3.1).
- **Reading.** P8 would remove the worker-specific failures (restart loss, open-ask, turn end with no report) for dependent tickets. It keeps them for independent tickets. The data has no count of how many tickets are dependent (see Gaps). Medium fit; it costs parallel speed.

### What the combined reading shows (INFERENCE)

| Issue | Proposal | Main load it targets | Fit | What the other files add |
|---|---|---|---|---|
| 740 | P1 rulings | 1,422 worker asks | High for worker asks | Orca text conflicts with section 7 on ask (reliab F1); does not fix a turn-end with no ask (reliab F4) |
| 741 | P2 batch, recommended answer | 3,363 questions | Medium to low | Recommendations already used (88 percent); the wait tail needs an inbox or a push (orca 6, oss 3.1) |
| 742 | P3 size by facts | 301 + 156 approvals | Medium to high | Docs-only still pays S2; test-run options decide the real saving (tests F5, F4) |
| 743 | P4 spec once | unknown | Unknown | No file has data |
| 744 | P5 verifier only without a test | none for the owner | Low | Haiku verifier n = 1; no ground for a non-Sonnet verifier (haiku 3.6, 4) |
| 745 | P6 reviewer brief | 178 caps | Medium | Cause of caps unknown; a Haiku reviewer is noisier (haiku 3.6) |
| 746 | P7 evidence per job | 204 failed audits | Medium | S2 and issue 729 show a record that may not prove its rule (tests F4) |
| 747 | P8 independent tickets only | 295 broadcasts, worker failures | Medium | Restart and turn-end failures are worker-specific (reliab F4, F6 to F8) |

None of the 8 proposals targets the two largest owner items directly: the 642 `! gh pr merge` commands and the 3,363 mostly-confirming questions. Cap extensions (178), failed-audit questions (204) and merges (195) total 577 questions, about 17 percent. The other files point at three things that no proposal covers: an owner-facing queue across Runs (orca 6, item 1; oss 3.1 cmux and Novadeck), a delegated escalation chain with severity and timeouts (oss 3.2 Gas Town), and the restart and open-ask recovery (reliab O1 to O5, R1 to R4). The owner said they would delegate merges and cap extensions (map note); that delegation is outside P1 to P8.

## Options for the owner

Each option has its cost. They are not exclusive.

1. **Delegate cap extensions to the coordinator, within a hard limit** (for example one extension per phase, then ask). Removes up to 178 questions of the 3,363 (5 percent) with 85 percent approval already. Cost: a loop can run longer; the limit must be set; the audit rule on `extension` events (which quotes the owner's words) needs a new source of approval.
2. **Delegate merges to the coordinator when CI is green and the audit passed.** Targets about 195 merge questions and about 640 `!` commands. Cost: the audit hook and auto mode both block `gh pr merge` today, so this needs a rule change that the owner approves; a wrong merge cannot be undone by the coordinator.
3. **Ask once per effort, not once per gate.** The owner approves the spec; later steps (tickets, caps, size) proceed unless a stop condition holds. Targets 301 + 156 + 178 approval-type questions. Cost: the owner sees fewer decision points; errors surface later (see 740 cost line).
4. **Make "recommended" the default after a short timeout in a coordinator.** The coordinator acts on its own recommendation after N minutes if the owner has not answered. Targets the 92 waits over 1 hour and the 431 over 5 minutes. Cost: a session acts without the owner; unsafe for destructive or security actions; needs the stop list of 740.
5. **Collect asks in one inbox per group** (the main goal of map 752). The data supports the need: 1,496 notices and 1,422 asks across many terminals, and Orca has no owner-facing queue across Runs (orca section 6, item 1; oss 3.1 lists cmux and Novadeck as designs). Cost: a new central session; the other research files give the design options.

## Gaps and open questions

- The script classifies sessions by path rule and keywords. Question types ("design and other" is the rest class) and `!` types are approximate; a few may be wrong in either direction.
- The transcripts cover only sessions that still exist on disk. Orca's own message log was not read, so asks that never reached a transcript are not counted. Ask counts include retries.
- No timing exists for how long the owner spends reading a question, only the time until the answer. Answer time includes time away from the PC.
- The transcript does not link a worker ask to the owner question it caused. INFERENCE only.
- The data starts at 2026-09-11 and the workflow changed during the period (audit gates, caps, branch hook). Counts of a given type may drop after a rule change; I did not split by rule version.
- Ledger counts come from the commands in transcripts, not from `audit ledger show` of each worktree (most worktrees are gone). Extension counts include repeated commands.
- Haiku or model choice is out of scope here (ticket 758); I only cite its facts in the judgement section.
- No count links an owner question to the per-ticket spec step, to a cause of a cap, or to a dependent ticket. Judgements of 743, 745 and 747 are limited by this.
- The judgement section relies on the five other files as written. I did not re-run their commands or re-read their primary sources. Their own gaps hold (see the Gaps section of each file).

## Sources read and sources that failed

Read:
- `docs/research/agent-workflow-comparison.md` (this repo), sections 1 to 6.
- Issue 752 (map) and issue 755 (ticket), and issues 740 to 747, through `gh api repos/<this repo>/issues/<n>` (the `gh issue view` command fails on a GraphQL deprecation).
- Local session transcripts: every top-level transcript file (about 1,157 sessions with data), read by Python scripts. Command output shown above.
- `gh pr list --state merged` for this repo (count of 211 merged PRs after 2026-10-12).
- The five other research files of map 752 (`docs/research/orca-inbox-orca.md`, `-oss.md`, `-tests.md`, `-reliab.md` and `-haiku.md`), each in full.

Failed or not done:
- The first `gh api` call for issue 755 was blocked once by a hook that changed the command, and succeeded on retry.
- Orca message logs, per-worktree ledgers and the owner's own clock were not read.
- I started no research subagent. The question needed counting over local data, which a script does better and with no private text leaving this machine.
