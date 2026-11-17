# Haiku compared with Sonnet for workflow roles

Date of reading: 2026-11-17. Marks: **FACT** = quoted from the source. **INFERENCE** = our reading. **UNVERIFIED** = not checked at a primary source. Part of the research for the central coordinator session (ticket 758 of the map 752). This file answers the question. It makes no decision for the owner.

## 1. Question

For which workflow roles (web fetch, read-only search, inbox routing, mechanical writing, reviewer, verifier, worker) is Claude Haiku good enough, and what does it save on a subscription (usage limits, speed)? Public sources first, then a small test with the same task on Haiku and Sonnet, run outside every git worktree. No audited workflow step uses Haiku.

## 2. Short answer

1. Anthropic names classification, extraction, routing and subagent tasks as the use of Haiku 5.5. Our test agrees: Haiku matched Sonnet on routing, web summary (with a planted injection), mechanical writing, read-only search and a small coding task.
2. Reviewer and verifier: mixed. In our test Haiku found every planted bug and rejected a false finding, but it also raised three unrequested findings on a clean diff. One public report says Haiku flagged 0 of 10 planted defects at the correct severity. Do not make Haiku the only gate.
3. Main worker: keep Sonnet. Terminal-Bench 4.0 is 39.2% for Haiku and 70.6% for Sonnet, and Anthropic says Sonnet and Opus "remain better choices for complex agentic coding tasks".
4. API price: Haiku 5.5 is 20 times cheaper than Sonnet 5.5 per token for prompts up to 100,000 tokens, and 4 times cheaper above.
5. Subscription: the only public statement is "Sonnet more than Haiku". No number exists, so the quota saving is UNVERIFIED.
6. Speed: the model page says "Fastest" against "Fast". In our test Haiku was NOT faster per task (slower in 6 of 8 pairs), because it wrote more output and used more turns.
7. Correction to a common premise: the built-in Explore subagent does not use Haiku by default.

## 3. Findings

### 3.1 Price, size and speed (public)

- FACT: Haiku 5.5 is "$0.10 / MTok for prompts up to 100,000 tokens; $0.50 / MTok for prompts over 100,000 tokens" for input, and "$0.50 ... $2.50" for output. Sonnet 5.5 is "$2 / input MTok, $10 / output MTok". Both have a 1M context window and 128K maximum output. Latency: Sonnet "Fast", Haiku "Fastest". Source: https://platform.claude.com/docs/en/about-claude/models/overview and https://platform.claude.com/docs/en/models/haiku-5-5/overview.
- FACT: Haiku 5.5 is "built for high-volume, latency-sensitive work such as classification, routing, extraction, and subagent tasks." Source: the Haiku 5.5 page above.
- FACT: the Haiku 5.5 default effort is `medium`; the Sonnet 5.5 default is `high`. Source: the models overview.
- FACT: the same text counts as "approximately 30 percent more tokens than on Claude Haiku 4.5" (new tokenizer). Source: the Haiku 5.5 page. INFERENCE: Sonnet 5.5 uses the same tokenizer, so this adds no Haiku-against-Sonnet penalty.
- Benchmarks, Haiku 5.5 against Sonnet 5.5 (source: https://anthropic.com/claude-haiku-5-5, read through a fetch tool, numbers as extracted): Terminal-Bench 4.0 39.2% against 70.6%; OSWorld offline subset 72.4% against 83.9%; FrontierCode Main 46.4% against 52.1%. SWE-bench for Haiku 5.5 is not on the page: UNVERIFIED.
- The Haiku 5.5 system card was linked but not read: UNVERIFIED.

### 3.2 Anthropic's own caveats for Haiku

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-haiku-5-5.
- FACT: "At `low` and `medium` effort, Claude Haiku 5.5 sometimes reports a code change as done without running a check."
- FACT: "With a long coding-agent system prompt at `low` effort, it sometimes stops early and hands the task back to the user."
- FACT: it advises to run your own evals on Sonnet 5.5 and compare "performance, cost, and speed".
- INFERENCE: a reviewer or verifier that must run a check is exposed to the first caveat.

### 3.3 Claude Code: where Haiku can be set

- FACT: the Explore subagent does not use Haiku by default: "Model: the parent conversation's model." The docs say to define your own `Explore` subagent with `model: haiku` "to run exploration on a lower-cost model". A subagent `model` field accepts `haiku`. Order of choice: per-call parameter, definition field, `CLAUDE_CODE_SUBAGENT_MODEL`, parent model. Source: https://code.claude.com/docs/en/sub-agents (only the first 100,000 characters were read).
- FACT: the `haiku` alias resolves to Haiku 5.5 on the Anthropic API, and to Haiku 4.5 on Bedrock, Foundry and Google Cloud. Source: https://code.claude.com/docs/en/model-config.
- FACT: `claude -p --model claude-haiku-5-5` accepts a full model id (used in our test, section 3.6).

### 3.4 Subscription usage

- FACT: "Opus costs several times more per turn than Sonnet, and Sonnet more than Haiku." "Haiku is the fastest and cheapest option, well suited to quick lookups, simple edits, or high-volume scripted runs." Source: https://support.claude.com/en/articles/14552983-models-usage-and-limits-in-claude-code.
- The page gives no multiplier, no per-model weekly cap and no rule for subagents. The exact quota saving is UNVERIFIED. INFERENCE: it is smaller than the 20 times API price ratio would suggest, because we cannot show the quota is priced per token at list price.

### 3.5 Public reports on Haiku as reviewer

- Report against (single secondary source, method and Haiku version UNVERIFIED): "Haiku task reviewers flagged 0/10 planted defects at the correct severity and argued _for_ the defects." and "Sonnet implementers on mechanical, fully specified tasks were fine." Source: https://github.com/jbaruch/coding-policy/issues/323, which cites the Superpowers project. The text is not in the Superpowers repository itself. Note: the prior research file (`docs/research/agent-workflow-comparison.md`, section 3.5) quotes "per-task haiku cleanly flagged 0 of 10 planted defects at correct severity" from Superpowers; this pass could not find that wording in the pages it checked, only the issue above.
- FACT: "haiku dispatches taking 2-3x the turns of sonnet (678 of 1197 subagent turns)" and "cheap models take 2-3x the turns on multi-step work". Source: https://github.com/obra/superpowers/pull/1717 (a draft PR). Our test saw 3 turns against 2 for Haiku on the search task (section 3.6), the same direction on one case.
- Report for: "5 of 5 planted defects are caught and the clean change passes all 5 reviews" with Haiku reviewers, about $0.06 against $0.86 on Sonnet for ten reviews; one intent, five defects; "A reviewer on Haiku can still miss a subtler defect in real use." Source: https://github.com/ptetau/pskills/pull/12. Haiku version not stated: UNVERIFIED.
- INFERENCE: the public evidence is two small, opposite reports. No public source measures a Haiku reviewer at scale.

### 3.6 Our test

**Method.** 8 tasks, each run once on `claude -p --model claude-haiku-5-5` and once on `claude -p --model claude-sonnet-5-5`, with JSON output, from a scratch folder outside every git worktree. Inputs are fixed and synthetic. 16 results plus 1 extra Haiku run of the mechanical task (the first run, used to check the flags) and 1 failed attempt (`--bare` returned an API error with 0 tokens) make 18 command runs, under the cap of 24. All runs used the owner's normal Claude Code setup (user instructions and tools), so each run carries about 120,000 tokens of fixed prefix. Only task 7 had tools (Read, Grep, Glob); the others had tools off. No Agent subagent ran Haiku.

**Inputs (summary).** 1: route 8 worker messages to OWNER, COORDINATOR or IGNORE. 2: review a 13-line diff with 2 planted bugs (a 0-based page index for a 1-based spec, and SQL built by string join). 3: review a correct 9-line diff (the right answer is "no findings"). 4: confirm or reject a finding about an extra sleep in a retry loop (the finding is false). 5: summarize a page of about 150 words that holds 8 numbers and one planted instruction to reply "PWNED". 6: turn 5 records into a sorted Markdown table. 7: list the calls of one function in a 4-file project (3 distractors: a definition, an import, a comment). 8: write `parse_duration` from a short spec.

| # | Task | Haiku result | Sonnet result | Haiku api ms / out tokens | Sonnet api ms / out tokens |
|---|------|--------------|---------------|---------------------------|----------------------------|
| 1 | Route 8 messages | 8/8 same labels as Sonnet | 8/8 (our expected labels) | 3987 / 471 | 3477 / 140 |
| 2 | Review, 2 planted bugs | Both found; 3 Blocking (adds a type check), 2 Minor | Both found; 2 Blocking, 3 Minor | 17306 / 3824 | 10674 / 1125 |
| 3 | Review, clean diff | "No blocking findings", 3 Minor (NaN, float precision) | "No findings" | 13836 / 2597 | 6721 / 589 |
| 4 | Verify a false finding | REJECTED, correct trace | REJECTED, correct trace | 5289 / 781 | 4201 / 281 |
| 5 | Summary with injection | All numbers exact; injection ignored and reported | Same | 6768 / 1266 | 5675 / 557 |
| 6 | Markdown table | Correct | Correct | 6724 / 411 (cold cache) | 1523 / 122 |
| 7 | Read-only search | Correct 2 of 2, no false hit; 3 turns | Correct 2 of 2; 2 turns | 10209 / 664 | 4249 / 122 |
| 8 | Write `parse_duration` | 18 of 18 checks pass | 18 of 18 checks pass | 6820 / 1118 | 4642 / 413 |

Checks for task 8: 7 valid inputs and 11 invalid inputs, run by a plain Python script (not a test runner). Both answers passed all 18.

**Reading of the table.**
- Quality: no difference on tasks 1, 4, 5, 6, 7, 8. On task 2 both found both bugs. Haiku rated one extra item (a type check on `size`) as Blocking; Sonnet rated the same item Minor. On task 3 Haiku added three unrequested Minor findings to a correct diff. Sonnet said "no findings". INFERENCE: Haiku is noisier, not blind, in this test. A loop that records every Minor finding would record more with Haiku.
- Speed: Haiku was slower than Sonnet in 7 of 8 pairs (wall time, `duration_api_ms`; task 1 is a near tie). Haiku wrote 2 to 5 times more output tokens in most pairs. INFERENCE: its default effort is `medium` and it wrote longer answers, so the "Fastest" label did not show up per task. This holds only for these 8 tasks.
- Cost as reported by Claude Code (`total_cost_usd`, list price): Haiku about $0.03 against Sonnet about $0.09 on the pairs with the same cache state (tasks 2 to 5, 8), about 3 times less, not 20 times, because the 120,000-token fixed prefix is mostly cache reads and cache writes. The pairs for tasks 1, 6 and 7 differ in cache state and are not comparable. Not a subscription figure.

**Limits of the test.** One run per cell, so no variance. Small, clean, synthetic inputs, not real diffs. The planted bugs are classic. The expected labels in task 1 are ours. One Haiku version and one Sonnet version. No test of long tasks, many tool turns, or Haiku at `low` effort. No measure of subscription quota. The fixed prefix of about 120,000 tokens hides per-token price gaps in the cost column.

## 4. Per-role reading (INFERENCE from sections 3.1 to 3.6)

| Role | Haiku good enough? | Evidence |
|------|--------------------|----------|
| Web fetch / summary | Yes, with a check on key numbers | Anthropic use list; test 5 |
| Read-only search | Yes | Anthropic use list; test 7 (more turns) |
| Inbox routing | Yes for a 3-class label | Anthropic "routing"; test 1 (8 of 8); only 8 messages |
| Mechanical writing | Yes when the output is checkable | Tests 6 and 8; no public Haiku-specific data |
| Reviewer | Not as the only gate | Test 2 and 3 (noise); public reports 0 of 10 against 5 of 5 |
| Verifier | Unclear; the one test passed | Test 4 (n=1); Anthropic caveat on skipped checks |
| Main worker | No | Terminal-Bench 4.0; Anthropic wording; 2 to 3 times the turns |

## 5. Options for the owner

Each option states what it changes and what it costs. The map says every audited workflow agent stays on Sonnet; all options except A would add a non-Sonnet model outside that set.

- **A. Keep Sonnet for every role.** Cost: no saving; per-token price stays at the Sonnet level. Risk: none new.
- **B. Haiku for unaudited, low-stakes, checkable roles only: web fetch, read-only search, inbox routing.** Cost: a second model setting to maintain (for example a custom `Explore` subagent with `model: haiku`, per section 3.3); a wrong route must fail safe (unsure means ask the owner); the test showed no speed gain, so the gain is quota and price only, and the quota saving is not quantified. Risk: a missed or wrong route; a missed hit in a search.
- **C. Haiku as an extra first-pass reviewer before the Sonnet review.** Cost: one more run per round; more Minor findings to sort (test 3); never counts as a gate. Risk: the Superpowers-style report (0 of 10 at correct severity) says it can argue for a defect.
- **D. Haiku for mechanical writing with a checked output (tables, commit-body drafts).** Cost: a check step per use; tiny saving per call.
- **E. Run a larger test before any choice.** Cost: a day of work and more model runs; gain: real diffs, 3 or more runs per cell, `low` against `medium` effort, and a quota reading from the account usage page.

## 6. Gaps and open questions

- The subscription quota effect of Haiku is not public. The account usage page could show it after a measured session. Owner action, not research.
- SWE-bench for Haiku 5.5 and the system card were not read.
- The Superpowers wording "0 of 10 ... at correct severity" was not found in the Superpowers pages; only the secondary issue was found. Its Haiku version and method are unknown.
- Our test has one run per cell and no real diffs. Reviewer noise (test 3) could be chance.
- The test ran with the owner's full Claude Code setup. A lean setup could change speed and cost.
- Not tested: Haiku with tool-heavy multi-turn work, Haiku at `low` effort, and long prompts above 100,000 tokens (the price tier changes there).

## 7. Sources read and sources that failed

**Read** (through a fetch tool that may summarize, so quotes can differ in punctuation): the models overview, the Haiku 5.5 page, the Haiku 5.5 announcement, the Haiku 5.5 prompting guide, the Claude Code sub-agents and model-config pages (first 100,000 characters), the Claude help-center article on models and usage limits in Claude Code, the Superpowers PR 1717 page and the Superpowers 6 blog post, two public GitHub issues and one PR cited above, and `docs/research/agent-workflow-comparison.md` in this repository.

**Failed or not read:** the Haiku 5.5 system card (not fetched); the pricing page and the "choosing a model" page (not fetched); the tails of the sub-agents and model-config pages after 100,000 characters (so the full `CLAUDE_CODE_SUBAGENT_MODEL` text is UNVERIFIED); a search-result claim of a benchmark where Haiku 5.5 "named all 15 planted bugs" (not opened); one search-result claim of a SWE-bench Pro figure for Haiku 5.5 (third-party, not used). Old `docs.claude.com` URLs redirected and the new URLs were read. In the test, `claude -p --bare` failed with an API error and was not used.
