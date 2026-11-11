# Handoff audit: what past handoffs lost (ticket 483)

Generated on 2026-11-11 for map 482 (the context-stop effort). This is a read-only audit of the 30 handoff files in a dated backup folder of the handoff files and of the session transcripts under `~/.claude/projects/`. It records facts only. It proposes no threshold value and no fix: tickets 485 and 486 decide those with the owner.

## Method

- Pairing: each handoff file name is the predecessor session id. All 30 predecessor transcripts exist. The successor transcript is the one whose first prompt names the handoff path ("Read ... and follow it", or the worker wait prompt). All 30 handoffs have exactly one successor transcript.
- Context at the block: the sum of `input_tokens`, `cache_read_input_tokens` and `cache_creation_input_tokens` of the last main-thread assistant line before the first "The context is at" block. This is the same measure that `hooks/context-handoff/hook.py` uses. The window is 1,000,000 tokens for every model in the sample (the hook table `MODEL_WINDOWS`).
- Role: the "session type" field of the handoff State section.
- Gap window: the first 40 tool calls of the successor after it reads the handoff (a worker successor: after the dispatch arrives). A script flagged every call in the window that (a) read a file, a scratchpad file or a tracker issue/PR whose file name or number the handoff text does not contain, (b) ran a command that the predecessor also ran, or (c) asked the user or the coordinator (AskUserQuestion, `orchestration ask`, SendMessage). I then read every flagged item and its handoff, and dropped the items that were new work and not recovery (for example a merge command, a post-merge check, or a decision that arose after the takeover).
- Limits: a "re-read" is an upper bound. The successor may need a file for new work, and the handoff text cannot prove the fact was missing. The handoff text check is by file name or issue number, so a fact that the handoff holds under another name is counted as a gap. Only 40 calls per successor are checked.
- Privacy: this repository is public. Repos other than `.claude` appear as repo A, repo B and so on (one label per repo, the same in every place). Sessions appear as H01 to H30 (handoffs, in the order of the per-handoff section), F1 to F4 (failed launches) and X1, X2. Quotes are shortened and hold no secret, address, file name, ticket number or org name.

## Results in short

| Gap kind | Count | Handoffs with it |
|---|---|---|
| asked (a question the handoff should have answered) | 0 | 0 of 30 |
| redid (work the predecessor already did) | 0 | 0 of 30 |
| re-read (a file or tracker item the handoff did not name) | 14 | 9 of 30 |
| re-read, skill text only (skill reload or `orca skills get`; the handoff cannot hold skill text) | 25 skills | 20 of 30 |
| other: takeover friction (old terminal close denied) | 2 | 2 of 30 |
| other: re-block before the launcher ran | 2 | 2 of 30 |

- The successor windows hold 31 ask calls in 17 handoffs (some are the same ask sent twice). I read the first 130 to 650 characters of each. All of them were decisions that arose after the takeover (round caps, audit failures, ticket proposals, owner approvals, worker relays). In the six handoffs where a cap or an extension was involved (`H12`, `H26`, `H19`, `H06`, `H28`, `H18`) the handoff already held the round count and the extensions, and the successor did not ask for them again.
- One redo candidate (`H25`, `gh issue edit <N> --body-file ...`) is not a redo: step 3 of the handoff "Remaining" list orders that publish.
- Failed handoffs: none inside the 30-file sample. Four handoffs outside the sample failed at the launcher (see the failed list below).

## Per handoff

Each entry: repo, role, model and window, context tokens at the block, handoff file size, block events, then the gaps.

### `H01`
- repo: `.claude`; role: worker; model: claude-sonnet-5-5; window: 1,000,000
- context at the block: 400937 tokens (40.1%); handoff file: 16932 bytes; block events: 1
- gaps (asked / redid / re-read): none
- skill text re-loaded (not a fact gap): mattpocock-skills:code-review, smart-commits

### `H02`
- repo: repo A; role: coordinator; model: claude-opus-5-5; window: 1,000,000
- context at the block: 401492 tokens (40.1%); handoff file: 11783 bytes; block events: 1
- gap `re-read`: "gh issue view <N> ... --json comments" (a tracker issue number that the handoff does not hold)
- skill text re-loaded (not a fact gap): plan-review

### `H03`
- repo: repo B; role: plain; model: claude-opus-5-5; window: 1,000,000
- context at the block: 406223 tokens (40.6%); handoff file: 11473 bytes; block events: 1
- gaps (asked / redid / re-read): none
- skill text re-loaded (not a fact gap): plan-review

### `H04`
- repo: repo C; role: plain; model: claude-sonnet-5-5; window: 1,000,000
- context at the block: 406581 tokens (40.7%); handoff file: 15453 bytes; block events: 1
- gaps (asked / redid / re-read): none
- skill text re-loaded (not a fact gap): mattpocock-skills:to-tickets, plan-review
- other: takeover friction: "the auto-mode classifier denied `orca terminal close`"; the successor stopped and the owner typed "ok. no need to stop. you can just follow the workflow"

### `H05`
- repo: repo D; role: coordinator; model: claude-sonnet-5-5; window: 1,000,000
- context at the block: 400691 tokens (40.1%); handoff file: 12097 bytes; block events: 1
- gaps (asked / redid / re-read): none

### `H06`
- repo: repo A; role: worker; model: claude-sonnet-5-5; window: 1,000,000
- context at the block: 400470 tokens (40.0%); handoff file: 18614 bytes; block events: 1
- gap `re-read`: "gh issue view <N> ... --json body" (issue number not in the handoff)
- gap `re-read`: "gh issue view <M> ... --json body" (issue number not in the handoff)
- skill text re-loaded (not a fact gap): plan-review

### `H07`
- repo: `.claude`; role: worker; model: claude-sonnet-5-5; window: 1,000,000
- context at the block: 400730 tokens (40.1%); handoff file: 15126 bytes; block events: 1
- gaps (asked / redid / re-read): none

### `H08`
- repo: repo A; role: coordinator; model: claude-opus-5-5; window: 1,000,000
- context at the block: 400298 tokens (40.0%); handoff file: 7553 bytes; block events: 1
- gap `re-read`: "a predecessor scratchpad report file (read with cat)"
- gap `re-read`: "a second predecessor scratchpad report file (read with cat)"
- skill text re-loaded (not a fact gap): orchestration

### `H09`
- repo: `.claude`; role: worker; model: claude-sonnet-5-5; window: 1,000,000
- context at the block: 403557 tokens (40.4%); handoff file: 22594 bytes; block events: 1
- gaps (asked / redid / re-read): none
- skill text re-loaded (not a fact gap): smart-commits

### `H10`
- repo: repo E; role: plain; model: claude-opus-5-5; window: 1,000,000
- context at the block: 400766 tokens (40.1%); handoff file: 8012 bytes; block events: 1
- gaps (asked / redid / re-read): none
- other: takeover friction: "The auto-mode permission check blocked my `orca terminal close` call"; the owner closed the old terminal and typed "closed"

### `H11`
- repo: `.claude`; role: worker; model: claude-sonnet-5-5; window: 1,000,000
- context at the block: 402840 tokens (40.3%); handoff file: 14044 bytes; block events: 1
- gap `re-read`: "a predecessor scratchpad evidence file (read with cat)"

### `H12`
- repo: `.claude`; role: worker; model: claude-sonnet-5-5; window: 1,000,000
- context at the block: 400118 tokens (40.0%); handoff file: 18219 bytes; block events: 1
- gap `re-read`: "a predecessor scratchpad ledger script"
- gap `re-read`: "a second predecessor scratchpad ledger script"
- skill text re-loaded (not a fact gap): mattpocock-skills:code-review

### `H13`
- repo: `.claude`; role: worker; model: claude-sonnet-5-5; window: 1,000,000
- context at the block: 417343 tokens (41.7%); handoff file: 15419 bytes; block events: 2
- gaps (asked / redid / re-read): none
- skill text re-loaded (not a fact gap): mattpocock-skills:implement
- other: the predecessor got 2 block events (one re-block) before the launcher ran

### `H14`
- repo: repo F; role: coordinator; model: claude-opus-5-5; window: 1,000,000
- context at the block: 401930 tokens (40.2%); handoff file: 10084 bytes; block events: 1
- gaps (asked / redid / re-read): none

### `H15`
- repo: `.claude`; role: worker; model: claude-sonnet-5-5; window: 1,000,000
- context at the block: 400248 tokens (40.0%); handoff file: 20431 bytes; block events: 1
- gaps (asked / redid / re-read): none
- skill text re-loaded (not a fact gap): mattpocock-skills:code-review

### `H16`
- repo: repo G; role: coordinator; model: claude-opus-5-5; window: 1,000,000
- context at the block: 402124 tokens (40.2%); handoff file: 8360 bytes; block events: 1
- gap `re-read`: "a predecessor scratchpad task file"
- skill text re-loaded (not a fact gap): orchestration, plan-review

### `H17`
- repo: repo A; role: worker; model: claude-sonnet-5-5; window: 1,000,000
- context at the block: 414433 tokens (41.4%); handoff file: 8541 bytes; block events: 1
- gaps (asked / redid / re-read): none

### `H18`
- repo: repo G; role: worker; model: claude-sonnet-5-5; window: 1,000,000
- context at the block: 405532 tokens (40.6%); handoff file: 19001 bytes; block events: 1
- gaps (asked / redid / re-read): none
- skill text re-loaded (not a fact gap): mattpocock-skills:code-review

### `H19`
- repo: `.claude`; role: coordinator; model: claude-opus-5-5; window: 1,000,000
- context at the block: 402468 tokens (40.2%); handoff file: 9378 bytes; block events: 1
- gaps (asked / redid / re-read): none
- skill text re-loaded (not a fact gap): orchestration

### `H20`
- repo: repo F; role: plain; model: claude-opus-5-5; window: 1,000,000
- context at the block: 401936 tokens (40.2%); handoff file: 9785 bytes; block events: 1
- gaps (asked / redid / re-read): none
- skill text re-loaded (not a fact gap): orchestration, plan-review

### `H21`
- repo: repo G; role: worker; model: claude-sonnet-5-5; window: 1,000,000
- context at the block: 417369 tokens (41.7%); handoff file: 12330 bytes; block events: 1
- gaps (asked / redid / re-read): none
- other: the successor stopped work at once on an owner message ("The user is shutting down the PC now"); not a handoff gap

### `H22`
- repo: repo B; role: coordinator; model: claude-opus-5-5; window: 1,000,000
- context at the block: 400397 tokens (40.0%); handoff file: 11098 bytes; block events: 1
- gap `re-read`: "gh api .../issues/<N> --jq .body (two issues that the handoff does not name)"
- gap `re-read`: "a predecessor scratchpad done-report file"

### `H23`
- repo: repo E; role: coordinator; model: claude-opus-5-5; window: 1,000,000
- context at the block: 400688 tokens (40.1%); handoff file: 10228 bytes; block events: 1
- gaps (asked / redid / re-read): none
- skill text re-loaded (not a fact gap): orchestration

### `H24`
- repo: repo H; role: plain; model: claude-opus-5-5; window: 1,000,000
- context at the block: 402565 tokens (40.3%); handoff file: 7578 bytes; block events: 1
- gap `re-read`: "Read of a predecessor screenshot file (expected state)"
- gap `re-read`: "Read of a predecessor screenshot file (actual state)"
- skill text re-loaded (not a fact gap): mattpocock-skills:diagnosing-bugs, smart-commits

### `H25`
- repo: `.claude`; role: worker; model: claude-sonnet-5-5; window: 1,000,000
- context at the block: 404385 tokens (40.4%); handoff file: 15671 bytes; block events: 1
- gaps (asked / redid / re-read): none
- skill text re-loaded (not a fact gap): plan-review

### `H26`
- repo: `.claude`; role: worker; model: claude-sonnet-5-5; window: 1,000,000
- context at the block: 405813 tokens (40.6%); handoff file: 13831 bytes; block events: 1
- gaps (asked / redid / re-read): none
- skill text re-loaded (not a fact gap): plan-review

### `H27`
- repo: repo B; role: coordinator; model: claude-opus-5-5; window: 1,000,000
- context at the block: 403174 tokens (40.3%); handoff file: 9674 bytes; block events: 1
- gap `re-read`: "a predecessor scratchpad done-report file"
- skill text re-loaded (not a fact gap): plan-review

### `H28`
- repo: `.claude`; role: worker; model: claude-sonnet-5-5; window: 1,000,000
- context at the block: 402079 tokens (40.2%); handoff file: 17347 bytes; block events: 1
- gaps (asked / redid / re-read): none
- skill text re-loaded (not a fact gap): simplify

### `H29`
- repo: repo I; role: coordinator; model: claude-opus-5-5; window: 1,000,000
- context at the block: 405281 tokens (40.5%); handoff file: 10911 bytes; block events: 1
- gaps (asked / redid / re-read): none

### `H30`
- repo: repo I; role: worker; model: claude-sonnet-5-5; window: 1,000,000
- context at the block: 401210 tokens (40.1%); handoff file: 14545 bytes; block events: 2
- gaps (asked / redid / re-read): none
- other: the predecessor got 2 block events (one re-block) before the launcher ran

## Failed handoffs

No handoff of the 30-file sample failed, and no successor halted with "handoff loop: context already at ...%". Four more sessions had a failed launcher result. Their handoff files are not in the backup, so no file size is known. The transcript shows the reason:

| Session | Role | Context at the block | Launcher result |
|---|---|---|---|
| `F1` (a `.claude` worktree) | worker | 400,124 | "successor failed: the Dispatch does not match the worker handle and Task"; a rerun said a launch already ran; a later run gave "ok" |
| `F2` (a worktree of repo F) | worker | 401,882 | "successor failed: the Dispatch does not match the worker handle and Task" |
| `F3` (a worktree of repo J) | worker | 400,612 | "successor failed: worker handle is not this terminal" (twice) |
| `F4` (a worktree of repo F) | worker | 404,534 | "successor failed: the Dispatch does not match the worker handle and Task" |

Two more transcripts contain the block text but are not handoffs: `X1` and `X2` quote the text while the hook texts and tests were edited.

## Summary table: gap kinds

| Gap kind | Count |
|---|---|
| asked | 0 |
| redid | 0 |
| re-read, file or tracker item not named in the handoff | 14 |
| re-read, skill text | 25 skill loads in 20 handoffs |

## Table: context size at the handoff against the number of gaps

The hook fires at the first check above 40% of the window, so every context size in the sample lies between 400,118 and 417,369 tokens. The sample holds no handoff at another size.

| Handoff | Context tokens | Share of window | File-or-tracker gaps | Skill loads |
|---|---|---|---|---|
| `H12` | 400118 | 40.0% | 2 | 1 |
| `H15` | 400248 | 40.0% | 0 | 1 |
| `H08` | 400298 | 40.0% | 2 | 1 |
| `H22` | 400397 | 40.0% | 2 | 0 |
| `H06` | 400470 | 40.0% | 2 | 1 |
| `H23` | 400688 | 40.1% | 0 | 1 |
| `H05` | 400691 | 40.1% | 0 | 0 |
| `H07` | 400730 | 40.1% | 0 | 0 |
| `H10` | 400766 | 40.1% | 0 | 0 |
| `H01` | 400937 | 40.1% | 0 | 2 |
| `H30` | 401210 | 40.1% | 0 | 0 |
| `H02` | 401492 | 40.1% | 1 | 1 |
| `H14` | 401930 | 40.2% | 0 | 0 |
| `H20` | 401936 | 40.2% | 0 | 2 |
| `H28` | 402079 | 40.2% | 0 | 1 |
| `H16` | 402124 | 40.2% | 1 | 2 |
| `H19` | 402468 | 40.2% | 0 | 1 |
| `H24` | 402565 | 40.3% | 2 | 2 |
| `H11` | 402840 | 40.3% | 1 | 0 |
| `H27` | 403174 | 40.3% | 1 | 1 |
| `H09` | 403557 | 40.4% | 0 | 1 |
| `H25` | 404385 | 40.4% | 0 | 1 |
| `H29` | 405281 | 40.5% | 0 | 0 |
| `H18` | 405532 | 40.6% | 0 | 1 |
| `H26` | 405813 | 40.6% | 0 | 1 |
| `H03` | 406223 | 40.6% | 0 | 1 |
| `H04` | 406581 | 40.7% | 0 | 2 |
| `H17` | 414433 | 41.4% | 0 | 0 |
| `H13` | 417343 | 41.7% | 0 | 1 |
| `H21` | 417369 | 41.7% | 0 | 0 |

| Band | Handoffs | File-or-tracker gaps | Mean gaps per handoff |
|---|---|---|---|
| 400000 to 402000 | 14 | 9 | 0.64 |
| 402000 to 405000 | 8 | 5 | 0.62 |
| 405000 to 410000 | 5 | 0 | 0.00 |
| 410000 to 420000 | 3 | 0 | 0.00 |
