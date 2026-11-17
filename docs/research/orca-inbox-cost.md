# Lower token and PC use without losing findings

Research for ticket 780 of map 752 (request 750). Date of reading: 2026-11-17. Marks: **FACT** = counted by a script over local data, or read in a named source. **INFERENCE** = our reading. **UNTESTED** = needs a run that this research did not do. The owner decides; this file makes no decision.

## Question

Where do tokens and PC resources go in the current workflow, and which cuts keep the same quality (the same real findings, issues and audit results)? Measure or estimate per step (map, spec, plan-review, implement, review loop, audit) and per role. Candidate cuts: smaller prompts and briefs, prompt caching, fewer or merged reviewer subagents, cheaper models for low-risk roles, docs-only paths, shared resource caps. For each cut: the saving, the risk to quality, and how a test could show that quality held.

## Short answer

1. FACT: from 2026-09-11 to 2026-11-17 the local transcripts hold about 40 billion cache-read tokens, 1.6 billion cache-write tokens and 160 million output tokens. Uncached input is under 1 million. At list price this is about 12,000 USD (an index, not a bill; see F1).
2. FACT: by list-price index, cache reads are 46 percent, cache writes 37 percent and output 17 percent. Cache writes cost more than their token count suggests, because a write costs 25 times a read on Sonnet 5.5.
3. FACT: coordinator and worker sessions are 55 percent of the index, plain sessions 8 percent, review-type subagents (plan-review, code-review, verifier, auditor) 20 percent, other subagents 17 percent.
4. FACT: Opus 5.5 turns are 40 percent of the index, and they are in coordinator and plain sessions. The settings file sets Opus 5.5 at effort `xhigh` for the main model. Workers and all subagents run on Sonnet.
5. FACT: every subagent starts with a first request of about 19,000 cache-read tokens and about 33,000 cache-write tokens. A reviewer run has a median of 230,000 to 283,000 tokens in 4 to 8 turns, so the fixed start is a large part of each run. Sibling reviewers started within 20 seconds each write the 33,000 again.
6. FACT: the ledgers show where review rounds pay off. A final-phase code-review round finds a Blocking finding in 8 percent of rounds (64 of 816). A correctness-phase round does so in 32 percent. Plan-review rounds find one in 26 to 80 percent, depending on loop and phase.
7. INFERENCE: cuts with a measured basis are (a) a leaner start for subagents, (b) one merged reviewer in final-phase rounds, (c) cache hygiene in long coordinator sessions, and (d) a model or effort change for coordinator sessions. Each needs a quality test first (section "Options"). None is proved here.
8. FACT: the 8,270 deferred Minor findings and 10,402 plan-review-5.3 Minor findings are the largest output of reviewers. In recorded triage batches the owner accepted every item (memory notes). INFERENCE: a Minor cap saves output tokens but trades away findings by definition; it is not a no-loss cut.
9. FACT: PC load is set by concurrency: a median of 6 and a p90 of 14 top-level sessions were active per 10 minutes in the last 7 days, with a peak of 35 (110 transcripts with subagents). The 2-worker rule is per agent, so total load is not capped. The sandbox research (`orca-inbox-sandbox.md`) gives a kernel-enforced shared cap.
10. Existing tools cover measurement well (`/usage` breakdown, OpenTelemetry, ccusage). They do not cover a quality test; that part must be built.

## Findings

### F1. Method and limits of the numbers

- FACT: a Python script read every top-level transcript and every subagent transcript from 2026-09-11 on (about 20,000 files, 19 GB). It summed the usage fields of each assistant message once per message id. It classified top-level sessions by a content rule and subagents by words in their first prompt. I publish counts only.
- FACT: the "coordinator" group in the script is any session with two or more Orca orchestration Bash calls. The worker rule did not match, so this group holds coordinators and workers together (753 sessions, 119,000 turns). 62,000 of its turns ran on Sonnet 5.5 and 57,000 on Opus 5.5. INFERENCE: the Sonnet turns are workers (section 9 of the rules says workers use Sonnet) and the Opus turns are coordinators.
- FACT: the "other" subagent kind (9,413 runs) is every subagent that did not match the plan-review, code-review, verifier, auditor or research words. It holds built-in search agents and other helpers.
- FACT: the index uses list prices from https://platform.claude.com/docs/en/about-claude/pricing: Sonnet 5.5 at 2 / 10 USD per million input and output tokens, 2.50 for a 5-minute cache write, 0.10 for a cache read; Opus 5.5 at 4 / 20, 5, 0.20. The index ignores the 1-hour write price (2 times input), the other models (Fable, Haiku: under 1 percent of turns), and subscription billing. On a subscription the money is not the limit; the usage window is, and its weights are not public (haiku file, section 3.4). Treat the index as a relative size.
- FACT: a phase table in this file attributes each turn to "the last Skill invoked in that session". A skill invoked early takes the turns of later work too. The `simplify` row is inflated for this reason. Use the phase table as an upper bound for each step, not as a measure.
- FACT: ledger counts come from 761 ledger files in the audit runtime folder (dates not restricted to the transcript window). A "round with a Blocking finding" is a ledger round that has at least one Blocking finding of the same loop, phase and round.

### F2. Where the tokens go, by role

FACT (index in USD, rounded; share of the 11,900 total):

| Role | Runs / sessions | Index | Share |
|---|---|---|---|
| Coordinator and worker sessions, Opus 5.5 turns | 753 sessions (both models) | 4,300 | 36% |
| Coordinator and worker sessions, Sonnet 5.5 turns | same | 2,200 | 19% |
| Plain sessions (Opus and Sonnet) | 419 | 1,000 | 8% |
| Plan-review reviewers | 3,118 | 780 | 6.5% |
| Code-review reviewers | 3,103 | 640 | 5.3% |
| Verifiers | 1,669 | 580 | 4.9% |
| Auditors | 1,142 | 340 | 2.8% |
| Other subagents | 9,413 | 1,990 | 17% |
| Research subagents | 289 | 100 | 0.8% |

FACT: by token kind, cache reads are 5,530 (46%), cache writes 4,440 (37%) and output 1,970 (17%). Cache writes are the largest part in every subagent kind: for plan-review reviewers they are 499 of 778, for code-review reviewers 441 of 635, for auditors 224 of 336.

FACT: medians per run (tokens, all kinds): coordinator and worker session 24.3 million (p90 71 million); plain session 3.0 million; plan-review reviewer 283,000 in 4 turns; code-review reviewer 231,000 in 4 turns; verifier 283,000 in 5 turns; auditor 618,000 in 8 turns. A sample of 4,000 subagent starts gave a median of 6 to 12 turns and 2,800 to 6,300 output tokens per run, by kind.

### F3. Where the tokens go, by step

FACT (cache-read tokens of the coordinator-and-worker group, by the last skill invoked; upper bounds, see F1):

| Step (skill) | Cache reads | Share of group |
|---|---|---|
| `simplify` (also the later turns until the next skill) | 5.29 billion | 19.8% |
| `plan-review` | 4.55 billion | 17.1% |
| before any skill | 2.18 billion | 8.2% |
| audit commands (`audit check`, `audit record`) | 2.16 billion | 8.1% |
| `orchestration` | 2.15 billion | 8.1% |
| `code-review` | 1.82 billion | 6.8% |
| `implement` | 1.78 billion | 6.7% |
| `smart-commits` | 1.68 billion | 6.3% |
| `to-tickets` | 1.27 billion | 4.8% |
| `wayfinder` (map) | 0.77 billion | 2.9% |
| `to-spec` (spec) | 0.53 billion | 2.0% |

INFERENCE by step, adding the subagent index of F2 (review reviewers run in these steps):
- Map and spec (wayfinder, grilling, to-spec): about 5 percent of coordinator and worker reads. No subagents. Small.
- Plan-review: the largest named step. 17 percent of reads in the coordinator and worker group plus 780 USD of reviewers (6.5 percent of the index). Plan-review loops write 17,935 findings (3,955 Blocking, 13,980 Minor): plan-review-5.3 wrote 13,143 (2,741 Blocking, 10,402 Minor) across 421 ledgers, and plan-review-3 and 4.1 wrote 4,792 (1,214 Blocking, 3,578 Minor) across 64 and 62 ledgers.
- Implement: about 7 percent. Needed work.
- Review loop (code-review, verifier, simplify, commit): 640 + 580 USD of subagents plus about 7 percent of reads for `code-review`; the `simplify` row is inflated.
- Audit: 8 percent of reads plus 340 USD of auditors.

### F4. The fixed start of every subagent

- FACT (sample of 4,000 subagent runs): the first request has a median of 18,700 to 18,900 cache-read tokens and 28,800 to 34,500 cache-write tokens, for every kind. At least 93 percent of the first requests write more than 20,000 tokens. Input that is not cached is 2 tokens.
- FACT (siblings): in 14 days of subagents, groups started within 20 seconds of each other (3,578 groups of 2 or more). The first, the second and the third member each wrote a median of 32,800, 33,300 and 32,000 tokens and read 18,900. A single subagent wrote 34,200. So parallel siblings share the 18,900 tokens but not the 33,000.
- FACT (https://code.claude.com/docs/en/prompt-caching, "Subagents and the cache"): a subagent "starts its own conversation with its own system prompt and tool set", and its first request "doesn't read the parent's cache". Subagents get a 5-minute TTL, "even on a subscription until you choose a longer one". A fork inherits the parent's prefix and reads the parent's cache.
- FACT (https://code.claude.com/docs/en/sub-agents): "Other built-in and custom subagents load both [CLAUDE.md and the git status snapshot], unless you set `omitClaudeMd`." A custom subagent can set `model`, `effort`, `tools` (allowlist), `skills`, `autoCompactWindow` and `omitClaudeMd`. `CLAUDE_CODE_SUBAGENT_MODEL` sets one model for all subagents.
- FACT: `CLAUDE.md` of this config is 32,497 bytes (262 lines). INFERENCE: about 8,000 tokens (4 bytes per token). The rest of the 33,000 written tokens is not measured here; candidates are the skill and agent listings, deferred tool names, hook-added context and the git snapshot. UNTESTED: which part is identical between siblings.
- INFERENCE: the written 33,000 tokens cost about 0.08 USD per run at the 5-minute price. Over 18,734 subagent runs in the window (F2 table) that is about 618 million tokens (18,734 x 33,000), about 1,500 USD of index at 0.08 USD per run, about 13 percent of all. Part of it is unavoidable.
- FACT (Anthropic): the cache-write price is 1.25 times input for 5 minutes and 2 times for 1 hour; a read is 0.05 times input for Sonnet 5.5 and Opus 5.5 (https://platform.claude.com/docs/en/build-with-claude/prompt-caching and the pricing page).

### F5. What the review loops find (ledgers)

FACT, counts of ledger events (761 ledgers):
- Rounds: 4,433 round events. Reviewers per round: 3 in 2,642 rounds, 2 in 1,559, 1 in 212, 4 in 20. That is about 11,300 reviewer runs.
- Findings: code-review correctness 588 Blocking and 5,161 Minor; code-review final 92 and 803; plan-review-5.3 correctness 2,379 and 8,084; plan-review-5.3 final 362 and 2,318; plan-review-3 and 4.1 together 1,214 Blocking and 3,578 Minor.
- Status events: 15,895 fixed, 8,270 deferred, 544 rejected. Verdicts: 622 confirmed, 59 rejected (8.7 percent of verified Blocking findings were false).
- Rounds that had at least one Blocking finding: code-review correctness 324 of 1,028 (32%), code-review final 64 of 816 (8%), plan-review-5.3 correctness 849 of 1,240 (68%), plan-review-5.3 final 260 of 677 (38%), plan-review-4.1 correctness 67 of 130 (52%), 4.1 final 24 of 91 (26%), plan-review-3 correctness 242 of 301 (80%), plan-review-3 final 84 of 150 (56%).
- Rounds per ledger: code-review correctness ended in 1 round in 497 of 689 ledgers; plan-review-5.3 correctness had a median of 2 rounds and a maximum of 12; plan-review-3 correctness had a median of 4.5.
- Raised findings (the loop session raised a Minor to Blocking): 243.
- INFERENCE: a final-phase code-review round is the least productive paid step per round (8 percent). It is also the step that guards the fixes of earlier rounds, so a cut there needs the quality test of F8.
- INFERENCE: the data does not link a finding to its reviewer axis, so it cannot say which axis could be merged without loss.

### F6. PC load

- FACT (script over the last 7 days, 8,528 transcripts): count of transcripts with at least one assistant message per 10-minute bucket. Top-level sessions: median 6, p90 14, maximum 35. With subagents: median 15, p90 50, maximum 110.
- FACT (`orca-inbox-sandbox.md` F1, F7): the 2-worker rule is a command-line flag that each agent must pass. The PC has 8 cores. A peak of 35 sessions that each run a 2-worker runner is above the core count. The declared test command is one process (`unittest`), so a runner flag does not apply to it.
- FACT (`orca-inbox-tests.md` F3, F4): the declared command has 4,938 test methods in 12 folders; three foreground runs hit the 600 s limit; issue 729 (a possible false pass of S2 on an auto-backgrounded run) is open.
- FACT (`orca-inbox-sandbox.md`, short answer 1 and 2): a systemd user slice with `CPUQuota` and `MemoryMax` gives one kernel-enforced budget for all agents. The `cpu`, `memory` and `pids` controllers are delegated on this PC. Whether Orca can start terminals in a slice is not known.
- INFERENCE: token cuts lower model load only. They do not lower the CPU load of tests, which comes from concurrent test runs and long runs.

### F7. Native cost controls (Claude Code docs)

Source: https://code.claude.com/docs/en/costs, /prompt-caching, /sub-agents.
- FACT: `/usage` shows the session cost at list price and, on a subscription, an attribution of recent usage to skills, subagents, plugins and MCP servers with recommendations such as "Trim ~/code/api/CLAUDE.md". A `Prompt cache (main)` line shows request count, share of input from cache, misses and whether the cache is warm. It covers the main conversation only, not subagents. Both need recent versions (v2.1.251 and later for the cache line).
- FACT: the main conversation gets a 1-hour TTL only on a subscription within plan usage. With an API key or usage credits it gets 5 minutes. Settings `promptCacheTtl` and `subagentPromptCacheTtl` (and the matching environment variables) set either bucket.
- FACT: a model switch, a plugin MCP change or a tool-definition change invalidates the cache; effort changes keep it on Sonnet 5.5 and Opus 5.5 with an API key or subscription. Compaction rebuilds the conversation layer.
- FACT: "Claude Code delivers a message from another of your sessions as a new turn when this session sits idle, sending your full context each time"; the setting `crossSessionInbound: hold` holds them. UNTESTED: whether Orca notices use this path.
- FACT: Anthropic advises to keep CLAUDE.md under 200 lines and to move specialised instructions into skills, which load on demand. This config's CLAUDE.md has 262 lines.
- FACT: thinking tokens are billed as output tokens, and "You can't turn off thinking on Opus 5.5, Sonnet 5.5, Haiku 5.5". Lower effort cuts them. The settings file sets `effortLevel` `xhigh` and `model` Opus 5.5 for the main session.
- FACT: the Haiku test (`orca-inbox-haiku.md`, section 3.6) measured cost 3 times lower, not 20, because the fixed prefix is mostly cache reads and writes, and Haiku was slower per task. Reviewer noise: three unrequested Minor findings on a clean diff.

## Existing tools and what they cover

The "do not reinvent the wheel" check, per need.

| Need | Existing tool | Covers | Gap |
|---|---|---|---|
| See token and cost use per session | `/usage`, status line `prompt_cache`, OpenTelemetry export (Claude Code docs) | Per session; attribution to skills and subagents on a subscription | Not per workflow step or per ledger round |
| Cost reports from local transcripts | ccusage (`ccusage/ccusage` on GitHub, 19,470 stars, last push 2026-11-17, license not detected by the API; README: "Analyze coding (agent) CLI token usage and costs from local data") | Daily, weekly, monthly and session reports | README-level read only; not tested; it has no notion of loops, rounds or findings |
| Lean subagent start | `omitClaudeMd`, `tools`, `skills`, `effort`, `model`, `autoCompactWindow` in a custom subagent file (sub-agents docs) | Everything that sets the start of a custom subagent | The workflow skills spawn `general-purpose` subagents; a custom definition must be named in them (INFERENCE; not read in the skills) |
| Cache control | `promptCacheTtl`, `subagentPromptCacheTtl`, `/compact`, `idleCompaction` | TTL per bucket | No tool shows subagent cache hits (the cache line is main-only) |
| Cheaper model per role | `model` field; `CLAUDE_CODE_SUBAGENT_MODEL` | Per subagent or global | Quality unproved; see `orca-inbox-haiku.md` |
| Filter verbose test output | PreToolUse hook that trims output (costs docs example) | Output size in context | S2 matches command text; a hook rewrite must keep S2 sound (`orca-inbox-tests.md` F1) |
| Shared PC cap | systemd user slice (`orca-inbox-sandbox.md`) | CPU, memory, tasks for all agents | Orca terminals in a slice: unknown |
| Quality test for cuts | None found | - | Must be built; see F8 |
| Findings-per-cost report | None found (not searched beyond the tools above) | - | A small script over ledgers and transcripts would do (this research used one) |

## Options for the owner

### Test design that all options share (F8)

INFERENCE for the design; UNTESTED.

1. Quality oracle (what "held" means). Three numbers per cut: (a) confirmed Blocking findings found, (b) audit result (S1 to S10, L1 to L6 pass or fail), (c) false and noise findings (rejected Blocking, extra Minor). A cut holds when (a) and (b) are equal to the baseline and (c) does not rise.
2. Seeded-defect set. Plant known defects in diffs, specs and ticket sets (the Haiku test used 2 and 5; use at least 20 per document type, with clean controls). Run baseline and cut with at least 5 runs per cell, because the earlier tests had n = 1 and no variance. Compare recall and noise. Run outside every git worktree, as the Haiku and sandbox tests did.
3. Historical replay. Ledgers hold 3,000 or more confirmed Blocking findings with the quoted line and the location. For code-review, the commit and the diff of each round exist in git history. Re-run the cut reviewer on the same diff and check that each confirmed finding is found again. For plan-review, the issue-body version of that time must come from the edit history (UNTESTED that it is available).
4. Audit equivalence. 852 audit records exist. Replay a cut auditor on stored digests and compare L1 to L6 verdicts to the stored ones.
5. Stop rule. Define before the run: for example, any lost confirmed Blocking finding in the replay set fails the cut.
6. Token saving is read from transcripts with the same script as F1 (usage per message id), run before and after on the same task set.

### The options

Savings are index shares of the 11,900 total and are INFERENCE. Risks are to quality. The options are not exclusive and are not ranked.

**O1. Lean start for review subagents (custom definitions with `omitClaudeMd`, a tool allowlist, no extra skills).**
- Saving: if CLAUDE.md is about 8,000 of the 33,000 written tokens, about 150 million cache-write tokens (18,734 x 8,000), about 375 USD (3 percent). Larger if the skill and tool listings can also be cut (not measured).
- Risk: the Standards axis of code-review uses documented repo standards, and CLAUDE.md is one of them; the plan-review axes read CLAUDE.md where their axis text says. A reviewer without it may miss a rule violation, and may break the "read-only" wording in section 11 if it is moved. Verifier and auditor need the rule text the brief names, so the brief must carry it.
- Test: F8 steps 2 to 4 on the same reviewer set, with and without `omitClaudeMd`. Measure first with a single run what the 33,000 tokens hold (UNTESTED).
- Cost: a new definition file per role, and the skills that spawn `general-purpose` must name it.

**O2. Merge reviewers in the final phase (one reviewer, both or all axes).**
- Saving: final code-review rounds are 816 in the ledgers and cost 2 reviewers each (about 0.2 USD per run); merging saves about one reviewer start and some duplicate reading per round, about 150 to 300 USD (1 to 2.5 percent). Merging plan-review's 3 axes into 1 in final rounds saves more per round: 677 + 91 + 150 final rounds.
- Risk: axis dilution; the final round is where 8 percent (code) to 56 percent (plan-review-3) of rounds still find a Blocking finding.
- Test: replay (F8 step 3) on the 64 + 260 + 24 + 84 final rounds that had a Blocking finding; the cut fails if any is missed.
- Cost: changes the `code-review` and `plan-review` skill text, which are partly third-party (code-review is a plugin skill).

**O3. Cache hygiene for long coordinator sessions.**
- Items: set `promptCacheTtl` to `1h` when the session runs on an API key or credits; avoid model and plugin changes mid-session; compact at natural breaks; check `crossSessionInbound`; read the `Prompt cache (main)` line on a real coordinator session first.
- Saving: unknown. Cache writes are 372 million tokens in the coordinator and worker group (about 1,400 USD of index, 12 percent); how much of it is rebuild after idle gaps is not measured (UNTESTED).
- Risk: a 1-hour write costs 2 times input against 1.25 times; on short bursts it costs more. `crossSessionInbound: hold` delays messages, which may break the section 7 rule that a coordinator must see worker asks.
- Test: one-week before and after readings of the cache line and of F1's script on coordinator sessions.

**O4. Model and effort for coordinator and plain sessions.**
- Saving: Opus 5.5 turns are about 4,800 USD of index (40 percent). At the same tokens, Sonnet 5.5 costs half. Lowering effort from `xhigh` to `high` cuts thinking output (output is 17 percent of the index; the split is not measured).
- Risk: coordinators do grilling, spec writing, audits and loop decisions; no data compares Opus and Sonnet on these. The map note says workflow agents stay on Sonnet; the coordinator is the open case. Token counts may rise on a weaker model.
- Test: F8 steps 2 and 4 on spec writing and audit-digest judging; compare cap-extension and failed-audit rates after a trial period.
- Cost: none in code; a settings change.

**O5. Cheaper model for read-only helpers ("other" subagents, 17 percent of the index).**
- Saving: not 20 times; about 3 times per the Haiku test, and none in speed (`orca-inbox-haiku.md`). Roughly 1,300 USD of index at best.
- Risk: missed hits in search; noisier output. Out of the audited set only if the step is not audited.
- Test: `orca-inbox-haiku.md` option E (larger test).
- Cost: a second model setting to maintain.

**O6. Smaller CLAUDE.md and briefs (move section 7, 8 and 16 detail into skills that load on demand).**
- Saving: each turn of every session and subagent reads the file. With about 257,000 turns (INFERENCE, not from the F2 table) and about 19,900 starts (18,734 subagent runs plus 1,172 sessions) in the window, 8,000 tokens cost about 590 USD (5 percent); halving it saves about 300 USD (2.5 percent). INFERENCE from the 4-bytes-per-token estimate.
- Risk: a rule that is not in context is not followed. Hooks and the audit enforce some rules, not all. Sections 6 and 7 are the core of the audit.
- Test: audit pass rate and loop outcomes on a fixed set of 10 tasks, before and after.
- Cost: a rewrite of config text; the config repo tests read CLAUDE.md (`orca-inbox-tests.md` F5).

**O7. Cap the Minor output of reviewers.**
- Saving: output is 17 percent of the index; reviewer output is 5,000 or fewer tokens per run; saving is small (under 1 percent), INFERENCE.
- Risk: this is the one cut that loses findings by definition. In recorded triage batches the owner accepted every deferred Minor (memory notes), so the loss may be nil in value, but the test of F8 cannot show it held, because the oracle counts Minor findings as noise.
- Cost: reviewer brief text change.

**O8. Skip or shrink the verifier where a reproducing test exists (proposal 744).**
- Saving: verifiers are 580 USD (4.9 percent); at most the share on findings that a test settles.
- Risk: 8.7 percent of verified Blocking findings were rejected; a missing verifier would send false findings into fixes.
- Test: replay on the 59 rejected findings (the cut must reject them through the test alone).

**O9. A smaller auditor input (a digest and the check output only).**
- Saving: auditors are 340 USD (2.8 percent); median 618,000 tokens in 8 turns per run.
- Risk: L1 to L6 judge from evidence; less input may miss a quote.
- Test: F8 step 4 on the 852 stored records.

**O10. Docs-only path and test selection.**
- Saving: no token saving; it lowers PC time. See `orca-inbox-tests.md` options A to E and the shared cap in `orca-inbox-sandbox.md` O2.
- Risk and cost: as in those files.

**O11. A shared cap for all agent work (systemd user slice).**
- Saving: no tokens; a hard ceiling for the PC while 35 sessions can be active. Cost and risks: `orca-inbox-sandbox.md` O2.

**O12. Measure first.** Build or adopt a cost report per ledger round and per step (ccusage plus a small script), and run it for one week before any cut. Cost: one ticket; gain: replaces the crude phase attribution of F3.

## Gaps and open questions

- The phase attribution (F3) uses the last skill invoked; the real split by step needs per-turn markers. The `simplify` row is inflated.
- Workers and coordinators are not separated in F1. A better rule (the first prompt of a worker carries a task and a dispatch id) did not match.
- Subscription weights are not public (`orca-inbox-haiku.md` 3.4). The index is a list-price index and may differ from the real usage window.
- What the 33,000 written tokens of a subagent start hold is not measured. A one-run test with a dump of the first request would show it; this research started no session.
- No count links a cap extension or a failed audit to a cause in the reviewer brief (also a gap of `orca-inbox-load.md`).
- The ledgers cover 761 branches and may not match the transcript window. Findings are not tied to a reviewer axis.
- Idle cache rebuilds in coordinator sessions are not measured; the `Prompt cache (main)` line would show them.
- Not tested: any cut. No reviewer, subagent, session or test runner was started.
- The ccusage README was read in part only; its subagent handling is unknown.

## Sources read and sources that failed

Read:
- Prior research of map 752: `docs/research/orca-inbox-load.md`, `orca-inbox-tests.md`, `orca-inbox-haiku.md` (all in full) and `orca-inbox-sandbox.md` (in full).
- Claude Code docs, through a fetch tool that summarises: https://code.claude.com/docs/en/costs (the first read was in full), /prompt-caching (in full), /sub-agents (first 100,000 characters; the end was not read).
- https://platform.claude.com/docs/en/build-with-claude/prompt-caching (first 100,000 of 167,602 characters) and https://platform.claude.com/docs/en/about-claude/pricing (the model rows and the footnote).
- Local files of this repo: `CLAUDE.md` (size and line count), `settings.json` (the `model` and `effortLevel` lines), `skills/plan-review/SKILL.md` and its axis files (3 reviewers per round in both modes), the `code-review` plugin skill (2 parallel reviewers).
- Local data: all session and subagent transcripts (usage fields, counts only); the ledger files in the audit runtime folder (counts only; no finding text was copied); one sample of 4,000 subagent starts; one 14-day sibling-start sample; one 7-day activity count.
- GitHub API: repository data and README head of ccusage.
- `claude --help` (flags `--effort`, `--model`, `--bare`, `--max-budget-usd` exist).

Failed or not done:
- `orca orchestration worker-start --help` was blocked by a hook, so Orca's own worker options (model, effort) were not read; the section 7 rules say workers use Sonnet.
- The first full-scan script ran too slowly and was restarted with a line prefilter; no data was lost.
- Not fetched: the Claude Code docs pages for settings, workflows cost and the OpenTelemetry metrics list; the ccusage docs; any benchmark of merged versus split reviewers (none was searched for beyond the Superpowers reports in `orca-inbox-haiku.md`).
- No container, test runner, Claude Code session or Orca terminal was started. A research subagent was not used: the work was counting over local data.
