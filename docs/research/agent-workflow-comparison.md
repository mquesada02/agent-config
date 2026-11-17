# Public agent coding workflows compared with the section 7 workflow

Question (issue 723): how do public agent workflows compare with the section 7 workflow of `CLAUDE.md` (map, spec, spec review, tickets, ticket review, pre-dispatch audit, workers, code review, audit)? Which practices make it faster without making it less correct?

Date of reading: 2026-11-16. Marks: **FACT** = quoted from the source. **INFERENCE** = our reading. "Not stated" = the source is silent.

## 1. Summary

1. **No source measures a map, spec, ticket and audit pipeline.** No study compares a heavy path with a light path, and none measures the cost of ledgers, audit records or owner questions. Every proposal below rests on documentation, on maintainers' own small runs, or on indirect studies.
2. **Most sources keep a lightest path.** Spec Kit, Kiro, Agent OS, Superpowers, BMAD, Cursor, OpenAI and Anthropic all let small work skip steps. Task Master advises "Always start with a detailed PRD" (it still allows single tasks in chat); ruflo, MetaGPT and ChatDev state no small path. The owner plan (always create a map) is compatible only if the map scales with the task (proposal 3).
3. **Sources ask the human less.** Spec Kit caps clarify at 5 questions, one at a time, with a recommended answer. Claude Code interviews with multiple-choice questions and "keeps asking until the answers add up to a spec". Superpowers and BMAD ask only what the code cannot settle; Superpowers logs its rulings and reports them at the end (proposals 1 and 2).
4. **Review uses a fresh, read-only reviewer in EGM, Superpowers and the vendor docs, and three sources cap repair rounds at 5 (EGM, Superpowers, BMAD).** Superpowers is the only source with run-by-run review numbers. Its numbers come from the maintainers' own runs, and the changes in them are not separated (section 3.5; proposals 5 and 6).
5. **Written records are small.** Sources keep the spec, the plan and the git history. Superpowers deletes its ledger after the final review. In the pages read, no source keeps an audit record file (proposal 7).
6. **Multi-agent splits are a poor fit for coding.** Anthropic and Cognition say so. INFERENCE: a worker per ticket adds a question relay (proposal 8).
7. Eight proposals follow. Each is filed as its own issue after this PR is open.

## 2. Baseline: section 7 in short

Steps 1 to 5 of section 7: map, general spec, spec review loop (caps 5 and 3), tickets, ticket review loop, pre-dispatch audit, one Orca worker per ticket with its own spec and spec review, a section 6 code review loop with verifier subagents and a ledger, a final audit, then a PR. Workers ask the owner through the coordinator. Section 7 has a small-task path under about 150 changed lines. The owner plans to remove it.

## 3. Source findings

Each entry answers the six questions: steps and gates; small-task path; review; how the human is asked; written record; measured result.

### 3.1 google/elephant-goldfish-model (EGM)

Read from a shallow clone (commit 72d06f52), about 30 files, most of them in full. EGM is a design-document workflow (brainstorm, draft, review, human PR review, implement). It does not review code diffs.

- **Steps.** FACT: "**Elephant** holds your project context and drafts the specification. **Goldfish** reviewers examine the draft and referenced source material without the earlier conversation... **You** make the architectural trade-offs and approve the specification before implementing." (README.md). FACT: "You do not have to follow the full sequence." (README.md).
- **Small path.** FACT: "Do not forcibly use the design-first process if you believe you can one-shot a simple bug fix." (docs/getting_started.md). FACT: "Design and review take time and may not pay off for a small, well-understood change." (docs/faq.md). For its own PRs a size rule exists: "Track 1: Bug Fix / Minor Patch (`<= 100` Non-Test Lines, `< 3` Core Files)" (CONTRIBUTING.md). The human chooses.
- **Review.** FACT: "Goldfish reviews require fresh subagent contexts. If your agent cannot create them, EGM stops the review." Reviewers are read-only: "You have NO tools to modify the workspace" (the reviewer agent files, agents/*.md). Severity has three levels (Blocker, Major, Nit). FACT: "Clean round: A round is clean when no reviewer raises a Blocker or Major finding that is not settled. Nits do not block." FACT: "Converged: Two consecutive clean rounds." FACT: "Cap: 5 rounds." A settled-findings list stops re-opened findings. A synthesizer subagent runs "Deduplicate overlapping findings". FACT: "A reviewer that times out, fails, or returns no report did not review... record it as **not run**... Never count it as a reviewer with zero findings."
- **Fixer.** FACT: "A contest must be checkable. 'This was intentional' is not evidence." and "Do not change a severity." (skills/egm-resolve/SKILL.md). No separate verifier agent exists.
- **Human.** FACT: gates hold "strictly one question (`len(questions) == 1`)" and, in the gates tested, no "(Recommended)" prefix (the bootstrap skill does have a recommended option). FACT: the author must not pick architecture: "Do not rank the options, mark a default, or pick one." The agent decides "mechanical choices with one defensible answer". The human has cheap exits: a "Consolidated report" preset "runs full flow without stopping", and findings triage offers "Auto accept". INFERENCE: about 14 gates on the full interactive path (our count).
- **Record.** The design doc and the review reports. FACT: "excessive documentation can become a bottleneck." (docs/faq.md). No ledger and no audit record exist.
- **Measured.** None. FACT: "Completing the EGM workflow alone does not demonstrate a productivity improvement." (docs/faq.md). FACT: "Runtime and token costs have not been measured." (docs/designs/multi_harness_support.md).

### 3.2 github/spec-kit

README, spec-driven.md, docs/quickstart.md and the command templates read in full.

- **Steps.** constitution, specify, plan, tasks, implement, converge. FACT: "Run these skills in your agent's chat, not your terminal, one at a time, reviewing each result before continuing." Gates are checks the agent runs on its own output: the constitution gate in plan, the analyze pass, the spec checklist ("max 3 iterations").
- **Small path.** FACT: "**Full path** — for production features, adding `/speckit-clarify`, `/speckit-checklist`, and `/speckit-analyze` as quality gates" versus "**Shorter path** — for smaller features" (docs/quickstart.md). Bug fixes: "No SDD feature workflow is required first." The human chooses. No size number.
- **Review.** `analyze` is a one-pass read-only report: "**STRICTLY READ-ONLY**: Do **not** modify any files." and "Limit to 50 findings total". No fresh-context reviewer and no stated round cap beyond the checklist loop.
- **Human.** FACT: "Maximum of 5 total questions across the whole session." "Present EXACTLY ONE question at a time." "Present your **recommended option prominently** at the top with clear reasoning" and the user may "accept the recommendation by saying "yes" or "recommended"". Specify allows "Maximum 3 [NEEDS CLARIFICATION] markers total" and says to "Make informed guesses based on context and industry standards".
- **Record.** FACT: the answers go into the spec: "`- Q: <question> → A: <final answer>`". The analyze report has "(no file writes)". No ledger.
- **Measured.** None. FACT: "In 15 minutes, you have:" against "~12 hours of documentation work" is an illustration with no method. INFERENCE: do not cite it as a result.

### 3.3 Kiro (kiro.dev/docs)

- **Steps.** FACT: "All specs follow a three-phase workflow ... Requirements or Bug Analysis ... Design ... Tasks" (/specs/). Review is per document: "comment on exact passages and send your comments to Kiro at once."
- **Small path.** Four weights: vibe chat, Quick Spec, standard spec, Bugfix Spec. FACT: "Quick Spec is a session mode that auto-generates requirements, design, and tasks in a single pass. Instead of approving each phase before the next begins, you answer clarifying questions up front" (/specs/quick-spec/). FACT (best-practices page): "A quick fix in chat is fine for straightforward issues like typos, simple logic errors, or well-understood one-line changes." The human chooses.
- **Review.** Optional requirements analysis. Kiro says that for small or well-understood specs the analysis can be skipped and the work can go directly to design (paraphrase of the analyze-requirements page). Fresh context and caps: not stated.
- **Human.** Questions up front, then approval per whole document, or no gate in Quick Spec. Question count: not stated.
- **Record.** `requirements.md`, `design.md`, `tasks.md`, version-controlled. No ledger.
- **Measured.** None with numbers. Pages /specs/concepts/ and /specs/plan-mode/ returned 404.

### 3.4 Agent OS (buildermethods/agent-os)

- FACT (CHANGELOG, 3.0): "Spec creation now defers to **Plan Mode**" and "Implementation/orchestration phases retired—frontier models handle this well on their own now". The commands write-spec, create-tasks and implement-tasks exist only up to tag v2.1.1.
- FACT (CHANGELOG, 2.1.0): "2.0.x had introduced a bunch of "bloat" that quickly proved unnecessary and inefficient." It dropped the spec verification step and "Documentation of every task's implementation"; "The final overall verification step for a spec's implementation remains intact."
- Small path: FACT "You can use as much or as little of it as you want!" The user chooses; no size rule.
- Human: FACT "**Always use AskUserQuestion tool**" in shape-spec, which also says "ask 1-2 clarifying questions if the scope is unclear"; "**One question at a time**" is in plan-product. INFERENCE: two plan confirmations and about 8 asks in shape-spec (a soft count: 5 explicit AskUserQuestion points plus 1-2 follow-ups).
- Measured: only "Context efficiency by 60-80%" for token loading in an old version, with no method.

### 3.5 obra/superpowers

README and the skill, reference and design files read; some skills only in part (see section 8).

- **Steps.** brainstorming, worktree, plan, execute (subagent-driven or inline), review, finish. FACT: "Nothing gets built until your human partner approves the design doc: the short one for a small change, the full one for a project."
- **Small path.** FACT: "Everything that matters is in the request ('make the icon cornflower blue'). This is a quick, clear task. Do it, and say what you did." and "If it grows mid-task, stop, say so, and step up a size." The agent sizes the work, says so, and the human can override.
- **Review.** FACT: subagents "should never inherit your session's context or history", and "Your review is read-only on this checkout." (task-reviewer-prompt.md). One reviewer gives two verdicts (spec compliance, code quality); an earlier design used two reviewers. FACT: "Minor findings never enter the loop." "Five rounds maximum per task". The re-review is scoped to the findings. In inline mode: "Do not dispatch a re-review: it would re-read a diff whose covering tests already answer 'addressed'". A fix starts with a test: "write the test that reproduces the finding, watch it fail, make it pass". INFERENCE: no verifier subagent is described; the controller rules.
- **Human.** FACT: "Ask one at a time." and "Ask a question only when the answer would change what gets built and neither the request nor the project answers it. Otherwise, state your call and your reason as a proposal they can correct". During execution: "Rulings, not stalls. A running plan does not wait on a human ... Record every decision in the ledger as `Ruling: <what you decided> — <why> — <what it costs if wrong>`". FACT: "Four things stop you, and only these: an irreversible or destructive operation; a security-sensitive action; a side effect outside this worktree ...; and a plan so broken that every path forward is a guess." The rulings reach the human in the final message.
- **Record.** The design and plan are committed. The ledger is git-ignored and exists because of a measured failure (agents re-dispatching finished tasks after compaction). FACT: it is deleted after the final review: "the git history is the record now." Its own eval showed no tool-call reduction ("the raw tool-call count did not drop (9.6 vs 9.0)") and claims a structural gain instead ("misattribution is now impossible when every ledger names its plan").
- **Measured** (maintainers' own runs, small n). FACT: iteration 2 (a merged reviewer prompt, "one fix dispatch addresses both kinds of findings", and implementers running the focused test while iterating, on top of iteration 1) gave "47.5 min / 15.7M / $13.55 — beat baseline on every axis, blind-judged 9/10 vs baseline 7/10" (one run; the changes are not separated). FACT: the best run of the final frozen configuration gave "go-fractals 44.4 min / 13.4M / $11.67 (-32% time, -37% tokens, -27% dollars vs baseline)", and a same-config re-run varied "44.4→57.1 min". FACT: across all 8 same-design go-fractals runs, which mix configurations, "44.4-57.1 min / 13.4-20.0M / $11.67-14.84 — the worst draw beats baseline on every axis; typical mid-band savings ~20-25%". FACT: "per-task haiku cleanly flagged 0 of 10 planted defects at correct severity". FACT: "Review-loop count (2-4 per run) is the biggest run-to-run cost variance; loops are mostly caused by plan ambiguity".

### 3.6 BMAD-METHOD

Read at main (v7 preview) plus the v6.0.0 tag for Quick Flow.

- **Small path chosen by facts.** FACT: "`bmad-build` routes to the smallest safe path. It reports three facts about the settled design: intent gaps ..., irreversible actions, and footprint. A design clean on all three takes the light path — a minimal plan and implementation in the same session, reviewed afterwards." A typical session (not a rule) is "about 500 lines of code added or changed (not counting tests)". FACT: "For a trivial edit you are willing to review yourself, skip the process".
- **Review.** FACT: "Active layers review the same diff independently and in parallel." Triage "Dismiss[es] noise, refuted claims, and unsubstantiated claims, with a recorded reason". Quick review is one reviewer. FACT: "review repair loop exceeded 5 iterations (non-convergence)". FACT: "Defer is a real problem that was already there before this change; a problem this change caused is never deferred." FACT: "Stop when the findings are mostly low-value notes about exotic corner cases."
- **Human.** FACT: "only what the repository and planning context cannot settle becomes an open question on a finished design, not an interview before work starts." FACT: "Human attention is by far the most expensive resource".
- **Record.** One plan file per change, with a review triage log inside. FACT: "Keep completed plans. Deleting one removes the state and evidence later builds, review, and retrospective read." Not a separate ledger.
- **Measured.** None reported. The docs ask the reader to try the review layers on their own work: "Do not take anyone's word for it."

### 3.7 Task Master, ruflo, MetaGPT, ChatDev

- **Task Master.** FACT: "**Always start with a detailed PRD.**" It has no review stage and no measured workflow result. Small tasks: "you can always create individual tasks by asking ... in chat."
- **ruflo** (formerly claude-flow). SPARC phases have gates ("Each phase has a quality gate that must pass before advancing."). Its own audit says: "Headline performance multipliers ... are largely hardcoded doc strings with no benchmark behind them; several are unsubstantiated and one is fabricated at runtime." INFERENCE: a gate is worth what its check proves; do not copy its claims.
- **MetaGPT** (arXiv 2308.00352). Role ablation: 1 agent 10 revisions, 4 agents 2.5 revisions, on two tasks; seven tasks overall. FACT: "MetaGPT requires more tokens (24,613 or 31,255 compared to 19,292)". Small n.
- **ChatDev** (arXiv 2307.07924). Ablation on its own quality metric: "≤Complete 0.3690", "≤Review 0.3717", "≤Testing 0.3953". INFERENCE: testing added more than review in their data.

### 3.8 Anthropic, OpenAI, GitHub, Cursor, Cognition, Google, Aider

Vendor pages read through a fetch tool that returns model-written summaries; the best-practices page and the OpenAI PDF were read as raw text. Quotes marked as summary-based may differ slightly from the page.

- **Gates.** Vendors use one or two human gates: a plan approval (Jules, Cursor, Gemini CLI, Claude Code plan mode) or the PR (Copilot, Devin). FACT: "Give it a cap on turns or spend, and have a person approve the result at the end." (Claude Code best practices). INFERENCE: no vendor describes a map, spec, ticket and audit gate chain.
- **Small path.** FACT (Cursor): "For quick changes or tasks you've done many times before, jumping straight to the agent is fine." FACT (Anthropic): "we recommend finding the simplest solution possible, and only increasing complexity when needed."
- **Questions.** FACT (Claude Code): "Claude comes back with multiple-choice questions about the parts you haven't pinned down", then one SPEC.md and "a fresh session to build from it". FACT (OpenAI): "Two primary triggers typically warrant human intervention: Exceeding failure thresholds ... High-risk actions".
- **Review.** FACT (Claude Code): "reviews the diff in a fresh subagent that never saw your conversation." and "report gaps that affect correctness and skip style". FACT: "A reviewer that's asked to find problems will always find *something*. If you fix every finding, you end up with extra abstraction layers and tests for cases that can't happen." The managed review runs find, verify ("filters out false positives"), then "deduplicated and ranked". FACT: "A review never approves or blocks the pull request".
- **Multi-agent.** FACT (Anthropic): "multi-agent systems use about 15× more tokens than chats", and domains that share context "are not a good fit for multi-agent systems today. For instance, most coding tasks involve fewer truly parallelizable tasks than research". FACT (Cognition): "The simplest way to follow the principles is to just use a single-threaded linear agent". FACT (OpenAI): "maximize a single agent's capabilities first."
- **Records.** A spec file, a progress file, a plan file, the git log, PR check runs, session logs. INFERENCE, in the pages read: no vendor describes a findings ledger or an audit record file; the closest are Anthropic's progress file and its pass/fail feature list.
- **Measured.** Anthropic: a multi-agent system "outperformed single-agent Claude Opus 4 by 90.2%" on its own research eval, and "multi-agent systems use about 15× more tokens than chats" (research, not coding; the two figures use different baselines). Aider: "SOTA score of 85%" with an architect and editor split (edit accuracy, not delivery time). Copilot says "On average, a review costs an estimated $0.25 USD with Lite, $1.50 USD with Balanced, and $10 USD with Max."

## 4. Measured studies

Read at the paper, the abstract page or the lab report. The DORA, Microsoft, CLARITI and METR quotes, and some abstract-page quotes, were checked against the notes only, not at the primary text.

| Study | Result (quoted) | Limit |
|---|---|---|
| METR RCT 2025 (arXiv 2507.09089) | "increases completion time by 19%"; 16 developers, 246 tasks | Tool use, early 2025 |
| METR update, Feb 2026 | estimated speedup of -18% (a subset of the original developers; interval -38% to +9%) and -4% (new developers; interval -15% to +9%), where negative means faster; METR calls the data "an unreliable signal" | Tool use, early 2026 |
| Peng et al. 2023 (arXiv 2302.06590) | "55.8% faster (95% confidence interval: 21-89%)"; 35 completers | One greenfield task |
| Cui et al. field RCTs | "4,867 developers ... a 26.08% increase (SE: 10.3%) in completed tasks" | Code completion, not agents |
| DORA 2025 (about 5,000 respondents) | "AI adoption now improves software delivery throughput ... However, it still increases delivery instability." Benefits "depend on teams working in small batches" | Survey, correlation |
| MAST (arXiv 2503.13657) | "41% to 86.7% failure rate on 7 ... open-source MAS"; in the latest version (v3, Figure 1, 1642 traces) task verification is 23.5 percent of failures and "Fail to Ask for Clarification" is 6.80 percent; in v1 and v2 the same categories read 31.41 and 2.09 percent | Open-source multi-agent systems |
| "LLMs cannot self-correct" (arXiv 2310.01798) | models "more likely to modify a correct answer to an incorrect one"; gains need oracle labels | Reasoning tasks, not code review |
| Self-Refine (arXiv 2303.17651) | "improving by ~20% absolute on average" | Conflicts with the paper above; per-round data not read |
| Meta MetaMateCR (arXiv 2507.13499) | reviewers "taking over 5% longer" when shown AI patches | Safety trial; the abstract says a later UX change showing patches only to authors removed the regression |
| Microsoft blog | "10 - 20% median PR completion time improvements" | Blog, no method; not a paper |

INFERENCE from the table: verification matters (MAST), a reviewer needs external evidence such as tests (self-correction paper), and question count is a minor failure cause. Clarifying-question papers (ClarifyGPT 70.96 to 80.80 percent, Ambig-SWE, CLARITI "41% fewer questions") mostly use simulated users; ClarifyGPT adds a ten-participant human study.

## 5. The issue 591 A/B run (context)

Issue 591 does not mention an A/B run. Only issue 723 does. No public source labels which artefact belongs to which arm, so everything here is INFERENCE from public timestamps.

- Full arm (INFERENCE): one map, four decision issues, one general spec of about 24,000 characters, four ticket issues, two ticket specs, and about 1 h 59 min from the map to the first code commit (21:14Z to 23:13Z). No PR existed at the time of reading (about 23:40Z); a later PR was not read.
- Short arm (INFERENCE): one commit and one PR about 1 h after the commit, +161 -74 lines in 5 files, nine deferred Minor findings in the PR body, no comments.
- FACT (issue 591 brief): "**Size:** about 100 to 150 changed lines, tests included." FACT (a public issue on the dispatch gate): "That planning costs more than the fixes."
- INFERENCE of cost hot spots: the spec is written twice (general, then per ticket) and reviewed each time. About 51 minutes sit between the spec and the tickets.
- Not stated anywhere public: owner question counts, ledger event counts, review rounds, token cost. The ledger is local.

## 6. Proposals

Each proposal states the change, the evidence, the expected effect on time, on owner questions and on correctness, and the cost. Effects are INFERENCE unless a number is quoted. Evidence strength: A = measured by maintainers, B = documented design, C = indirect.

### P1. Workers log rulings and ask only on four stop conditions
- **Change.** Section 7 workers (steps 5.1 to 5.5, and the main session when it runs a ticket itself) decide what the spec and the repo already settle. They log `Ruling: what, why, cost if wrong` and list the rulings in `worker_done`. They send an `ask` only for an irreversible action, a security-sensitive action, an effect outside the worktree, or a spec so broken that every path is a guess. Any choice that would add a temporary fix or workaround, add hidden coupling or weaken security is also an ask (section 0: "Never add a temporary fix or workaround without the user's approval."). A worker still asks when the spec has several defensible readings that change what gets built (section 1: "present them - don't pick silently"), and still stops at a review cap or a failed audit (section 6 steps 5 and 6).
- **Evidence (B).** Superpowers: "A running plan does not wait on a human" and "A wrong ruling costs rework your human partner can see and undo; a session parked on a question costs their whole day and buys nothing." BMAD: "only what the repository and planning context cannot settle becomes an open question". OpenAI: human intervention on "failure thresholds" and "High-risk actions".
- **Effect.** Time: fewer worker stalls and relays through the coordinator. Questions: large drop. Correctness: neutral if the four conditions hold; a wrong ruling costs rework.
- **Cost.** The owner sees decisions after they are taken. The rule "If you're unsure of anything, ask the user" (section 6 item 7) is narrowed to real doubt about what to build: a worker must tell a routine call from a second reading of the spec. Section 1 ("If uncertain, ask.") and step 5.1 ("grilling the user again if needed") are narrowed in the same way: the worker no longer grills for what the spec and the repo settle. The worker must also recognise a temporary fix, hidden coupling or weaker security as an ask, not a ruling; a missed case would be reported only after the fact.

### P2. Ask the owner in one ranked batch with a recommended answer
- **Change.** Grilling in steps 2 and 5.1 sends one message per phase: at most 5 questions, ranked, each with a recommended answer the owner accepts by saying "yes". Skip any question the code or the request answers. Decide mechanical choices without asking.
- **Evidence (B).** The cap and the recommended answer come from Spec Kit ("Maximum of 5 total questions", "accept the recommendation by saying "yes""), which asks one question at a time. The batch comes from Superpowers ("Bring the 'theirs' pile in one message, most important first"). Claude Code supplies the multiple-choice form ("multiple-choice questions about the parts you haven't pinned down"); the page also says it "keeps asking until the answers add up to a spec", so it does not show a single batch. EGM keeps one question per gate and no recommended answer; this proposal differs from EGM on purpose (section 0 already says to recommend the most correct option).
- **Effect.** Time: fewer round trips. Questions: fewer and cheaper. Correctness: neutral; the recommendation is shown, not forced.
- **Cost.** A batch hides the dependency between questions; a question that depends on an earlier answer needs a second round, so the cap of 5 holds per round, not per phase. The cap and the skip rule narrow section 1 ("If uncertain, ask.") and the grilling of steps 2 and 5.1: a real uncertainty beyond the first 5 questions waits for the next round.

### P3. Always create a map, but size the rest by facts the session can check
- **Change.** Keep the owner plan to always create a map. Scale what follows: a one-page map; no decision tickets when nothing is open; a single task skips tickets, ticket review and the pre-dispatch audit, and goes straight to implementation in the main session; the section 6 review loop stays. The session decides the path from three facts it reports in the map: open intent gaps, irreversible actions, and footprint (files and lines). The owner can override.
- **Evidence (B).** BMAD: "A design clean on all three takes the light path — a minimal plan and implementation in the same session, reviewed afterwards." Spec Kit short path and Kiro Quick Spec keep the artefacts and drop the gates. Superpowers: "If it grows mid-task, stop, say so, and step up a size." EGM keeps a size rule in its own contributing guide.
- **Effect.** Time: removes the 51-minute stretch between the spec and the tickets for small work (INFERENCE from the 591 timestamps; section 5 did not measure what that stretch held). Questions: fewer. Correctness: the review loop and tests stay.
- **Cost.** It is a small-task path in a new form; the owner decides if that fits the plan. It skips section 7 steps 4 (tickets), 4.1 (ticket review) and 5 (workers), so the rule "every ticket runs steps 5.1 to 5.5 in full" has no ticket to apply to. The proposal does not say whether the step 3 spec review stays; the owner decides. The size-approval ledger event and the audit check on it (S5) would change with the approval. The facts need a written rule so that they are checkable. The current exception asks the owner to approve a larger diff (size approval); P3 moves that approval to the owner override. The 591 task was briefed as "about 100 to 150 changed lines", but the short-arm PR changed 235 lines (section 5), above the section 7 limit of about 150, so the current rule would have needed a size approval. The 51-minute figure therefore shows the full path near the small-path limit, not what P3 adds.

### P4. Write the spec once
- **Change.** A ticket carries its acceptance criteria and a link to the general spec sections. Step 5.2 and step 5.3 run only when the ticket changes or adds a decision that the general spec does not hold.
- **Evidence (B/C).** Spec Kit stores answers inside the one spec. Kiro Quick Spec makes three files once. Agent OS removed layers as "bloat" in 2.1.0 and passed spec writing to plan mode in 3.0. INFERENCE (591): spec text appears twice and is reviewed twice.
- **Effect.** Time: one fewer spec and one fewer review loop per ticket. Questions: fewer repeated grilling rounds. Correctness: neutral if the ticket still names its tests.
- **Cost.** Tickets must be written with enough detail; the ticket review must check that. This makes section 7 steps 5.2 and 5.3 conditional, which departs from the section 7 Exception ("every ticket runs steps 5.1 to 5.5 in full") and from "the worker executes each of these steps". A ticket without its own spec has no `plan-review-5.3` loop, so the audit has no evidence for that loop on that ticket. The owner must accept this change to the rule and to the audit. A ticket that the main session runs (P8) follows steps 5.1 to 5.5 in section 7, except the skipped 5.2 and 5.3.

### P5. Verifier subagent only where no reproducing test can be written
- **Change.** In the section 6 loop, a Blocking finding that a failing test can show is confirmed by that test, written before the fix and shown failing. The test must use the failing input and expected result that the reviewer wrote in the finding. A verifier subagent runs only when no test can be written (security, design, spec mismatch).
- **Evidence (C).** Superpowers: "write the test that reproduces the finding, watch it fail, make it pass". Its inline mode also skips a re-review when "a diff whose covering tests already answer 'addressed'" (a re-review skip, not a confirmation of a finding, so only loose support). INFERENCE: Superpowers describes no verifier subagent; the controller rules. Self-correction paper: gains need external feedback, not a second opinion of the same kind.
- **Effect.** Time: removes one subagent run per testable Blocking finding. Questions: none. Correctness: a failing test is stronger evidence than a verdict. The audit must still see the test.
- **Cost.** Section 6 says "The agent that reports a finding never fixes it, so a second agent checks each finding first". With P5 the loop session (also the Fixer) writes the confirming test, so for testable findings no second agent checks; a test that encodes the loop session's misreading would pass. The reviewer-written failing input is the guard. It also changes the audit rule that wants a verifier verdict per Blocking finding; the hook and its tests need an update.

### P6. Reviewer brief: correctness only, stop at low-value notes, and a "not run" status
- **Change.** Tell reviewers to report correctness gaps and skip style, to stop at low-value notes, and to list a failed reviewer as "not run" (never as zero findings). Merge the two code-review axes into one reviewer with two verdicts when the diff is small.
- **Evidence (B/C).** Claude Code: "skip style" and "A reviewer that's asked to find problems will always find *something*." BMAD: "Stop when the findings are mostly low-value notes". EGM: "Never count it as a reviewer with zero findings." Superpowers measured one iteration that bundled the reviewer merge with a single fix dispatch and focused-test runs: faster and cheaper, judged 9/10 vs 7/10 (section 3.5; their own run, n small, changes not separated).
- **Effect.** Time: fewer rounds and fewer deferred Minors (the short arm listed nine). Questions: none. Correctness: the "not run" status closes a gap; fewer Minors lowers noise.
- **Cost.** Stopping at low-value notes can hide a real defect; the Blocking evidence rule stays the guard. It also records fewer Minors, which touches section 6 step 1 ("Record the Minor findings in the ledger") and the deferred-Minor issue filed after the merge (section 8). Skipping style can drop the Standards axis of the section 6 review, and merging the axes touches section 7 step 5.5, which names the code-review axes. One merged reviewer loses the independent second read of two reviewers. The saving rests on one project's runs.

### P7. Make the written evidence serve a job and shrink the rest
- **Change.** For each record (ledger event, done report, audit item) name the failure it prevents. Keep those that resume work after a crash or let the audit check a rule mechanically. Generate the done report from the ledger instead of writing it by hand. Put the deferred Minors and the rulings in the PR body; the post-merge issue for deferred Minors (section 8) stays.
- **Evidence (B).** Superpowers keeps its ledger for one measured failure and deletes it after the final review. BMAD keeps one plan file with the triage log inside. Spec Kit analyze: "(no file writes)". EGM: "excessive documentation can become a bottleneck." In the pages read, no source keeps an audit record file.
- **Effect.** Time: less writing per task. Questions: none. Correctness: unchanged if every kept record maps to a checked rule.
- **Cost.** No source measures the value of an audit record, so removal cannot be shown safe by this research. This proposal does not remove any record; it asks for a per-record review. Generating the done report from the ledger touches the section 6 step 5 draft done report: the auditor then no longer compares an independent report with the ledger.

### P8. Dispatch workers only for independent tickets
- **Change.** Tickets that depend on each other, or touch the same files, run one after the other in one session. An Orca worker is used only for independent tickets.
- **Evidence (C).** Anthropic: "most coding tasks involve fewer truly parallelizable tasks than research" and "about 15× more tokens". Cognition: "The simplest way to follow the principles is to just use a single-threaded linear agent". OpenAI: "maximize a single agent's capabilities first." MAST: inter-agent misalignment is 32.3 percent of failures in v3 (Figure 1) and 31.41 percent in v1 and v2.
- **Effect.** Time: removes worker start-up and the ask relay for dependent tickets; the audit still runs for each ticket PR (see the cost line), so the audit time is not saved. Questions: fewer relays. Correctness: less context loss between tickets.
- **Cost.** A long session holds more context; the context-handoff hook already covers that. Parallel speed is lost for dependent tickets. This departs from section 7 step 5 ("dispatch an Orca worker" for each ticket), from the section 7 Exception ("every ticket runs steps 5.1 to 5.5 in full"), from section 10 (each ticket worker gets its own child worktree) and from section 11 (Orca for other delegation). A dependent ticket in the main session needs its own branch, its own PR and its own audit, so the per-ticket audit stays; only the worker, its child worktree and the ask relay go. The owner must accept this change to those rules.

## 7. What is not measured

- No study of a map, spec and ticket pipeline against a direct path.
- No study of the cost of ledgers, audit records or written evidence.
- No study of review-round caps with fresh-context reviewers on code.
- No study of the time cost of an agent question to a real developer. Question papers mostly use simulated users.
- The only end-to-end speed and cost numbers for a gated coding workflow in the pages read come from the Superpowers maintainers' own runs. MetaGPT and Anthropic report token cost for other designs. ChatDev also reports time and cost figures; they were not checked.
- METR could not give a clean figure in 2026. Do not use any single productivity number here as proof.

## 8. Pages read and pages that failed

**Read in full or in the parts named:** the EGM repository (about 30 files, shallow clone, most in full); Spec Kit README, spec-driven.md, quickstart and command templates; Kiro pages /specs/, feature-specs, best-practices, bugfix-specs, quick-spec, analyze-requirements, /steering/ and /hooks/ (opening parts only); Agent OS README, CHANGELOG, main commands and the v2.1.1 tag files; Superpowers README, brainstorming, writing-plans, executing-plans, subagent-driven-development and its references, review skills, and four design and eval documents (TDD, worktrees, finishing and parallel-agent skills only in part); BMAD build, plan and review docs and the v6.0.0 Quick Flow pages; Task Master README and docs; ruflo README, SPARC README and its own audit; MetaGPT, ChatDev and MAST papers; the Anthropic engineering posts and Claude Code docs named in 3.8; Cognition, OpenAI, GitHub, Cursor, Jules, Gemini CLI and Aider pages named in 3.8; the studies in section 4; issues and one PR of the agent-config repository for section 5.

**Failed or not read:**
- kiro.dev/docs/specs/concepts/ and /specs/plan-mode/ returned 404.
- SSRN 4945566 returned 403; the 2024 DORA PDF exceeded the size limit; one Google Cloud DORA page returned no body.
- Old Anthropic, Cognition and OpenAI URLs redirected (308 or 301); the new URLs were read.
- Not read: the EGM essay on a blogging site, EGM bootstrap and harness files, Superpowers resuming and debugging skills, Task Master hosted docs, ruflo benchmark gist, Anthropic "Writing effective tools", Claude Code hooks and memory docs, Kiro steering and hooks beyond their openings, decision issues of the 591 map.
- Three read-only fetch calls of a subagent were blocked by a local hook; the files were read another way with no loss.
- Vendor and abstract pages came through a summarizing fetch; quotes from them can differ in punctuation from the page. This also holds for the METR, DORA and Microsoft pages of section 4.
- Read only in part: the Anthropic subagents page, the handling-reports page, the Kiro correctness page, issues 721 and 722 of the agent-config repository, and the ticket specs of the 591 effort (not seen).
- Local blocks of `gh issue view --comments` (a GraphQL error) were worked around with REST reads.
