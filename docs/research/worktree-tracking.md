# Research: tracking the worktrees that agent sessions create

Date: 2026-11-14. Research was read-only: no worktree, branch, terminal or Orca state was changed.
Counts of other repos are given as numbers only. Paths `~/.claude/...` are the main checkout of this repo.
Numbering: the brief's question 5 (recommendation and its cost) is answered in the summary and in Q7. Q5 here holds the worked examples and Q6 the constraints.

## Summary and recommendation

- Orca already records who created each worktree. Every worktree created by the CLI carries `cliProvenance.callerTerminalHandle` (the terminal that ran the create command). 57 of 59 linked worktrees have it; the other 2 have `lineage`. No worktree has neither.
- `lineage` (parent worktree) is weaker: only 26 of 59 linked worktrees have it, and it points to the coordinator's worktree, not to a session.
- Orca has no "owner session" field. The creator is a terminal handle, not a session id. A context-handoff successor gets a new terminal handle, so Orca alone does not link successor to predecessor.
- The repo already closes that gap: the launcher writes `lineage.jsonl` (successor handle to predecessor handle) and `~/.claude/hooks/worktree-cleanup/cleanup` already uses it in its Ownership check. So "which worktrees are mine, my workers' or my predecessors'" can be derived with no new registry.
- Recommendation: design (c), a read-only list command that reuses the cleanup ownership logic. It lists the worktrees of the current repo that this session, its predecessor chain or its Run workers created, with their state (clean, pushed, merged, live terminal). It is run at handoff takeover, after each `worker_done`, and before the done report. It also lists "orphans" (creator terminal gone, no proof) for the owner to decide. It never removes anything; `cleanup` stays the only removal path.
- Cost compared with the simplest option (a CLAUDE.md rule "run `orca worktree list` and look"): about 150 lines of script and about 250 lines of tests, plus 3 to 4 changed sentences in CLAUDE.md and the handoff successor steps. The simplest option needs no code but depends on the model remembering and on reading 90+ rows.
- No hook can make the model act at real session end (Q3). So "session end" must be a step the model runs, backed by the existing audit gate.
- The owner must decide the points in Q7.

## Q1. What Orca already tracks

Commands run: `orca --help`, `orca worktree --help`, `orca worktree list --json` (92 worktrees, 32 repos, 59 linked; the brief counted 104 on 2026-11-13 and the total moves as sessions add and remove worktrees: 91 to 92 during this run), `orca terminal list --json` (35 live terminals, 0 orphaned), `orca worktree show --json`, `orca orchestration run-list --json`.

Fields of a worktree record (from `orca worktree list --json`; the rows hold more keys, such as `identity`, `hostId` and `isPinned`, that this research did not use): `id`, `path`, `head`, `branch`, `isMainWorktree`, `linkedIssue`, `linkedPR`, `workspaceStatus`, `lastActivityAt`, `isArchived`, `parentWorktreeId`, `childWorktreeIds`, `lineage`, `createdAt`, `createdWithAgent`, `baseRef`, `creatorProvenance`, `cliProvenance`.

| Field | What it holds | Usable for tracking? |
|---|---|---|
| `branch`, `head` | `refs/heads/<branch>`, tip sha | Yes, for merged/pushed checks with git. |
| `parentWorktreeId`, `childWorktreeIds` | Set only when created with a parent. The main checkout lists its children (3 for this repo). | Partly: 26 of 59 linked rows have `lineage`. This repo: `handoff-audit-483` and `worktree-tracking` have `lineage: null`, `parentWorktreeId: null`. |
| `lineage` | `{parentWorktreeId, origin: "cli", capture.confidence: explicit or inferred, createdByTerminalHandle, createdAt}`. Seen: 16 explicit, 10 inferred. | Has a creator handle, but only when lineage exists. |
| `cliProvenance` | `{kind: "created-by-cli", createdAt, callerTerminalHandle, startupAgent?}` | Yes: the creator terminal. 57 of 59 linked rows. |
| `creatorProvenance` | `{kind: "host"}` on all 59. | No: carries no creator. |
| `linkedIssue` | Number. 16 of 59 set; set by `worktree set --issue` (help text of `orca worktree set`). | Weak: manual. |
| `linkedPR` | 1 of 59 set. | Not usable: rarely filled. |
| `workspaceStatus` | All 59 linked rows are `in-progress`. | Not usable. |
| `isArchived` | All false. | Not usable. |
| `lastActivityAt` | ms timestamp. `splitter-gaps` 1792763919234 (about 21.6 days before this run), `handoff-audit-483` 1794438330795 (about 2.2 days). | Useful as an age hint only. |

Terminals: `orca terminal list --json` rows have `handle`, `worktreeId`, `worktreePath`, `branch`, `title`, `connected`, `orphaned`, `agentIdentity`, `lastOutputAt`. `--worktree <selector>` filters by worktree. So "live terminal in worktree X" is one call.

Environment of a session: `ORCA_TERMINAL_HANDLE` and `ORCA_WORKTREE_ID` are set in the terminal (checked with `env`). `cleanup` reads `ORCA_TERMINAL_HANDLE` at `~/.claude/hooks/worktree-cleanup/cleanup:479`.

Orca skill guide (`orca skills get orca-cli`, lines 144-154 of the printed guide): "When creating from inside an Orca-managed worktree or folder context, Orca infers the current parent context when it can"; `--parent-worktree active` makes it explicit; `--no-parent` means independent. So lineage depends on a flag or on inference; provenance does not.

Test with real data (this repo, 5 linked worktrees plus main):

| Worktree | `callerTerminalHandle` | Handle live now? | `lineage` |
|---|---|---|---|
| a worker worktree of a running coordinator (A) | term_bffda5dc | yes (coordinator terminal in main checkout) | parent = main checkout |
| a second worker worktree of the same coordinator (B) | term_bffda5dc | yes | parent = main checkout |
| `handoff-audit-483` | term_802d4871 | no | none |
| `splitter-gaps` | term_b025420c | no | parent = main checkout |
| `worktree-tracking` (this one) | term_62e7e519 | yes | none |

Can a session tell from Orca alone? Own worktrees: yes, `callerTerminalHandle == $ORCA_TERMINAL_HANDLE`. Workers' worktrees: yes if the coordinator created them (it does, CLAUDE.md section 10, so the caller is the coordinator). Predecessors' worktrees: no. A successor has a new handle, and the creator handle (for example term_802d4871) is gone from `terminal list`. Orca does not store "term_62e7e519 replaced term_802d4871". Orca's `lineage` does not cover it either: it links worktrees, and the successor works in the same worktree as the predecessor.

The missing link is in `/tmp/claude-context-handoff/lineage.jsonl` (59 lines when read), written by `launch.py:448-456` through `runtime_dir.append_lineage` (`runtime_dir.py:149-158`). Real data: line `successor term_62e7e519 <- predecessor term_802d4871`. So from term_62e7e519 the chain reaches term_802d4871, the creator of `handoff-audit-483`. Limits: the file is in `/tmp` (`runtime_dir.py:11-23`), its birth time is Nov 11 10:47, so handoffs before that are not in it. `splitter-gaps` (created Oct 26) is not provable from it.

## Q2. Designs

### (a) Registry file with the owning session

- Data: a file (for example `/tmp/claude-context-handoff/worktrees.jsonl` or under `~/.claude`), one line per worktree: path, branch, owner session id, owner terminal handle, time.
- Writing: a PostToolUse hook on Bash that parses `orca worktree create ... --json` output (the hook gets `tool_input.command` and `tool_response`; see `hook.py:328-337` and `352-373` for how the context hook reads `tool_input.command` and `tool_response`). Alternatively the model writes it by hand (unreliable).
- Reading: shown in the handoff State section and at session end; `cleanup` removes the line on success.
- Code touched: new PostToolUse hook (about 80 lines), `cleanup` (about 20 lines to remove a line), `hook.py` STATE_CORE (one field) and successor steps, CLAUDE.md sections 7, 10, 11, `settings.json` (hook entry; a settings edit may need the owner's `!` command: known for permission settings, unverified for hook entries).
- Size: about 200 lines code, about 350 lines tests, 3 sections of CLAUDE.md.
- Failure modes: worktrees made outside Bash (Orca UI) or by a failing parse are missed. Two sources of truth: Orca already holds the creator, so the registry can disagree with Orca (hidden coupling). If kept in `/tmp`, a reboot erases it. A crash between create and write loses the line. A stale line for a worktree removed by hand.
- Races: concurrent sessions appending (solved with `runtime_dir.append_line` locking). `cleanup` removing a line while another session reads.
- Test: unit tests with the stub of `orca`/`gh` in `worktree-cleanup/cleanup_support.py` (lines 15-58); hook tests with fake `tool_response` JSON.

### (b) Sweep, no registry, merged or gone branch and no live terminal

- Data: `orca worktree list --json` (scope to the repo), `orca terminal list --json`, git (`merge-base --is-ancestor <tip> origin/main`), `gh pr list --head <branch> --state all`.
- Code: one read-only script (about 100 lines), a call in the handoff successor steps and in the done step of CLAUDE.md.
- Size: about 100 lines code, about 200 lines tests.
- Failure modes:
  - False positive on a fresh worktree: a worktree with no commit has its tip on `origin/main`, so it looks "merged". Real data: this very worktree (`research/worktree-tracking`, tip 47c451d is on origin/main, no PR). Only the "no live terminal" rule saves it; a worktree whose terminal was closed just before a commit would be listed.
  - It lists worktrees of other sessions that are merged but not yet cleaned by their coordinator. Owner noise.
  - It misses work that is not merged (a research branch with no PR, such as `handoff-audit-483`) and that is exactly the kind a session forgets. By design it cannot flag it, since the rule is "merged or gone".
  - `gh` needs network; 5 worktrees means about 5 `gh` calls.
- Races: a worktree listed while its owner is about to push or merge; a listing is a snapshot (during this research, one worktree of another session was in one `worktree list` output and absent from the next, because that session removed it).

### (c) Derive ownership from Orca provenance plus handoff lineage (no registry, no merged rule for ownership)

- Data: `orca worktree list --json` (`cliProvenance.callerTerminalHandle`, `lineage.parentWorktreeId`, `repoId`), `lineage.jsonl` (already written), `orca orchestration worker-list` for the Run (already read by `cleanup:171-197`), `ORCA_TERMINAL_HANDLE`, `ORCA_WORKTREE_ID`.
- Rule: a worktree is mine when its repoId equals mine and one of:
  1. its `callerTerminalHandle` is my handle or in my predecessor chain (the logic of `check_ownership`, `cleanup:159-168`, and `in_predecessor_chain`, `cleanup:142-156`);
  2. its parent worktree is the worktree of my terminal (`cleanup:162`);
  3. its creator is the `agentTerminalHandle` of a worker of my bound Run (workers that made sub-worktrees; `cleanup:218` reads that field).
  Everything else of the same repo with a gone creator and no chain is an "orphan": listed separately, never claimed.
- Output per row: path, branch, why it is mine, clean or not, branch pushed or not, PR state, live terminal count. State is information; it is not the ownership test, so a new empty worktree is not mis-flagged.
- Code touched: a new script `hooks/worktree-cleanup/mine` (about 150 lines) that imports the checks of `cleanup` (it has no `.py` suffix, so either load it with `importlib` or move the shared functions to a module; moving them touches `cleanup` and up to its 8 test files), one successor step in `hook.py` (the SUCCESSOR_* constants, lines 85-108), CLAUDE.md section 7 (after `worker_done`) and section 6 step 5 / section 8 (before done).
- Size: about 150 lines of script, about 250 lines of tests (reuse the stub in `cleanup_support.py`), if shared functions are moved add about 30 changed lines in `cleanup`.
- Failure modes: `lineage.jsonl` lost at reboot (predecessor worktrees fall to "orphan", visible, not lost); creator handle reused (not observed; unverified); a worktree made from the Orca UI has no `cliProvenance` (the 2 such rows had `lineage`); `worker-list` unreadable (then rule 3 is skipped and the output says so).
- Races: read-only, so none that can destroy data. A snapshot may be stale by seconds.
- Test: stub `orca`/`gh` as in `cleanup_support.py`; cases: own handle, predecessor chain, chain with a missing line, parent anchor, worker creator, other repo, orphan, no Orca.

### Comparison

| | (a) registry | (b) sweep | (c) derive |
|---|---|---|---|
| New data store | yes | no | no |
| Source of truth | duplicate of Orca | git+gh | Orca (+ existing lineage file) |
| Finds unmerged forgotten work | yes if registered | no | yes |
| False positive on fresh worktree | no | yes | no |
| Missed worktree causes | creation outside Bash, parse failure | none if merged | no `cliProvenance` (2 of 59 now; both have `lineage`) |
| Code, approx. | 200 + 350 tests | 100 + 200 | 150 + 250 |
| Settings edit needed | yes (hook) | no | no |

## Q3. Where a check can run

| Place | Input it gets | What it can do | Fit |
|---|---|---|---|
| Context-handoff hook `~/.claude/hooks/context-handoff/hook.py` (events Stop and PostToolUse, `run`, lines 423-446) | Hook JSON: `session_id`, `transcript_path`, `cwd`, `permission_mode`, `effort`, tool fields. Skips subagents (`agent_id`) and `CLAUDE_CODE_SESSION_ATTENDED=0` (line 427). | At 40% context it returns `decision: block` with a text (`block()`, lines 248-259). The text lists the State fields (lines 51-62) and the successor steps (lines 85-108). It cannot run commands itself. | Good for handoff: add a State field "worktrees I own" (but the text says "Run no command to find it", line 62, so the list must come from the launcher or a successor step) and a successor step "run the list command". The launcher (`launch.py`) runs as a command and already calls `orca worktree list` (line 315): it could print the list. |
| Coordinator steps after `worker_done` (CLAUDE.md lines 147-151, section 7) | Report with branch and worktree path (5.6). | Audit, open PR. | Good: one more step, "list my worktrees, list those that are merged or settled". Instruction only; no enforcement. |
| Stop hook | `~/.claude/settings.json` has `Stop` hooks: the context hook and an Orca hook. Docs: Stop "Runs when the main Claude Code agent has finished responding" and not on a user interrupt; input `stop_hook_active`, `last_assistant_message`, `background_tasks`, `session_crons`; `decision: block` continues the conversation; 8 consecutive continuations cap. (https://code.claude.com/docs/en/hooks, section Stop) | Block or add context at the end of each turn. | Not real session end: it fires every turn. A check here would run at every turn or need a state file; noisy. |
| SessionEnd hook | Input `reason`: clear, resume, logout, prompt_input_exit, other. "no decision control", "can't block session termination"; default budget 1.5 s, raisable to 60 s with `timeout`. (same page, section SessionEnd) | Side effects only (log, write a file). Cannot talk to the model. | Cannot make the session clean up. It could write a "worktrees still owned" note file. Whether it runs when the terminal is closed or the process is killed: unverified (docs read do not say). Currently only an Orca hook uses it in `settings.json`. |
| Cleanup command `~/.claude/hooks/worktree-cleanup/cleanup` | argv: optional `--skip-ownership`, `--base`, one path. Env `ORCA_TERMINAL_HANDLE`. Reads Orca record, lineage file, bound Run. | Checks 1-8 then removes (`main`, lines 467-504). It acts on one path at a time. | It knows ownership but is only run per worktree, after merge (CLAUDE.md line 180). A `--list` mode would fit here but would mix a read-only report into the only removal path; a separate script that reuses the checks is cleaner. |
| Audit gate (CLAUDE.md section 6 step 5, line 115; `hooks/workflow-audit`) | Worktree path, draft done report. | Blocks `gh pr create` until a pass. | The only enforced "before done" point. A check "no owned worktree left except the current one, or each is listed in the report" could be an extra auditor item. Not read in detail: the auditor brief lists L1-L6 (`auditor-brief.md` lines 30-40) and `audit check` S-items. Adding an item is a larger change. |

## Q4. Owner gone, and other repos

Owner gone (crash, reboot, closed terminal):
- (a) The registry holds the owner's session id and handle, but nobody reads it unless a new session looks. After a reboot a `/tmp` registry is gone. The successor chain is not written for a crash (no launcher ran), so the dead session's entries have no heir. The new session must show "entries whose owner terminal is not live", which is the orphan list of (c) with an extra file.
- (b) Independent of the owner: any session can run the sweep. It finds the merged ones only; unmerged work of a dead owner stays hidden.
- (c) If the creator handle is not live and not in `lineage.jsonl`, the worktree is an orphan. It is listed with creator handle, age (`lastActivityAt`), PR and push state. A crash has no handoff line, so the new session cannot prove ownership; the owner decides, and removal for an unproven worktree needs `! cleanup --skip-ownership <path>` (the command printed at `cleanup:20, 490`).
- Terminal handles after a reboot: unverified (not tested; not stated in the Orca CLI help read). `launch.py:346` mentions error code `terminal_handle_stale`, which shows Orca can return a stale handle.

Other repos: `orca worktree list --json` returns all 92 worktrees of 32 repos; each row has `repoId`. A session's own repo id is the part before `::` in `ORCA_WORKTREE_ID`. Counts for this run: 6 rows for this repo now (main plus 5 linked; 7 earlier in the run, before another session removed one). A list command filters `repoId` first, then applies the ownership rule. Other repos are never inspected. `launch.py:134-157` (`managed_worktree`) already maps a cwd to a listed worktree.
Several sessions of the same repo at the same time: ownership by creator handle separates them. (b) cannot separate them.

## Q5. Worked examples

Data (commands in Sources). Today is 2026-11-14.

### `splitter-gaps` (branch `mquesada02/splitter-gaps`)

- Orca: `workspaceStatus` in-progress, `isArchived` false, `linkedIssue` none, `linkedPR` none, `lastActivityAt` about 21.6 days ago, `callerTerminalHandle` term_b025420c (not in `terminal list`), `lineage.parentWorktreeId` = main checkout, 0 live terminals in the worktree.
- Git: tip `e18c2f3` ("feat(workflow-audit): read the full ledger with audit ledger show (#167)") is an ancestor of `origin/main` (`merge-base --is-ancestor` gave ON-MAIN). Worktree is clean, 0 commits ahead of `origin/main`. Remote branch `refs/heads/mquesada02/splitter-gaps` does not exist.
- gh: `gh pr list --state all --head mquesada02/splitter-gaps` returns `[]`.
- `cleanup` would: Target pass; Ownership refuse for a session that is not in the main checkout and has no chain to term_b025420c (creator not in `lineage.jsonl`, file starts Nov 11); the printed hint is the `--skip-ownership` command. A session running in the main checkout (anchor = parent worktree, `cleanup:162`) passes. Clean pass. Merged: no merged PR, but tip is on `origin/main` (`tip_off_base`, `cleanup:295-306`), pass. Pushed: remote ref absent and `numbers == []`, pass (`cleanup:332-333`). Docker: unverified (not run). So the only blocker is Ownership.
- Design (a): would have recorded it if created by a Bash call in a registered session; the entry would be 21 days old; owner gone, so no heir. Caught only by a later reader of the registry.
- Design (b): caught at the first sweep after the branch tip reached `origin/main` (tip is on main, no live terminal), by any session, in any repo-scoped run. Lists it with no owner claim.
- Design (c): caught as an orphan at the first run by any session of this repo: creator gone, no chain. Same moment as (b) for this case, plus its state (clean, on main).

### `handoff-audit-483` (branch `research/handoff-audit-483`)

- Orca: `linkedIssue` 483, `linkedPR` none, no `lineage`, `callerTerminalHandle` term_802d4871 (gone), `lastActivityAt` about 2.2 days ago. 1 live terminal in the worktree (title names the ticket, agent claude).
- Git: tip `7a40d70` ("docs(research): add handoff audit for ticket 483") is NOT on `origin/main` (NOT-ON-MAIN). Remote branch exists at the same sha. Worktree is clean. The file `docs/research/handoff-audit-483.md` is not on `origin/main` (`git ls-tree` found no match).
- gh: `gh pr list --state all --head research/handoff-audit-483` returns `[]`: no PR was ever opened. (A local branch `mquesada02/handoff-audit-483` is merged into `origin/main` and has no remote and no PR; unrelated stale local branch, not examined further.)
- Section 8 says a research branch reaches the base through a PR. So this is not a leftover to delete: it is open work (research with no PR).
- `cleanup` would: Ownership pass for a session whose handle chain reaches term_802d4871 (real chain: term_62e7e519 <- term_802d4871); refuse for others. Clean pass. Merged: refuse, "no merged PR has the local tip 7a40d70fe... as its head, and it is not on origin/main". So it refuses, rightly, and no work is lost.
- Design (a): registered at creation, would show it as "still owned" at every handoff and end: correct. If its owner died it stays listed until `cleanup` removes it.
- Design (b): not caught (branch not merged, live terminal present). Correct not to flag for removal, but also never reminds anyone that the PR is missing.
- Design (c): listed as owned by the chain of term_62e7e519, with state "pushed, not merged, no PR, 1 live terminal, linked issue 483". That is the useful reminder.

### Fresh worktree (this one)

`research/worktree-tracking`: tip 47c451d is on `origin/main` (no commits yet) and no PR. This is the false-positive case of Q2 (b). (c) lists it as owned by term_62e7e519 (its `callerTerminalHandle`, live) and shows 1 live terminal.

## Q6. Constraints

- Only removal path stays `~/.claude/hooks/worktree-cleanup/cleanup` (CLAUDE.md lines 180, 236-241). (a), (b), (c) as written only read; none calls `orca worktree rm` or `git worktree remove`. The `Bash` pre-hook already denies other forms (seen: a "run worktree rm as a plain command, or use ~/.claude/hooks/worktree-cleanup/cleanup" denial when a command string contained those words).
- No recursive delete (CLAUDE.md section 13): none needed.
- Docker (CLAUDE.md section 14; `~/.claude/docs/agents/docker.md` line "Before you remove any worktree, run `docker compose ls -a` ..."): the list command should show a "compose stack has config in this worktree" flag, using `docker compose ls -a --format json` as `check_docker` does (`cleanup:362-379`). `cleanup` already refuses while a stack has config files in the target (line 500). The list command must not remove stacks.
- Settings edits: (c) needs none; (a) needs one (caveat in Q2 (a)).
- Section 10 (every task in a worktree; every ticket worker gets its own child worktree with the coordinator as parent): (c) relies on that for rule 2.

## Q7. Recommendation and owner decisions

Recommendation: (c), implemented as a read-only script in `~/.claude/hooks/worktree-cleanup/` that reuses the `cleanup` ownership code, plus 3 to 4 sentences in CLAUDE.md and the successor steps. Reasons (section 0, correctness first):
1. One source of truth (Orca provenance plus the lineage file that already exists); no second store to drift.
2. It finds unmerged forgotten work, which (b) cannot, and it has no false positive on a fresh worktree.
3. It is read-only, so it cannot break the "only `cleanup` removes" rule.
4. It needs no settings change.

Cost compared with the simplest option:
- Simplest: a CLAUDE.md rule only, "before the done report run `orca worktree list --json` and check your worktrees". 0 lines of code, about 3 sentences. Weakness: 90+ rows across 32 repos, no ownership filter, relies on the model; it misses predecessors' worktrees.
- (c): about 150 lines + 250 lines tests + about 30 changed lines if shared functions move out of `cleanup`.
- (b) is cheaper than (c) in code, but has the false positive and the blind spot for unmerged work.

Known limit of (c): after a reboot `lineage.jsonl` is gone and predecessors' worktrees show as orphans (visible, not lost). A crash leaves the same. The owner must then decide them.

What the owner must decide:
1. Which design: (c) as recommended, or (b), or the CLAUDE.md-only rule.
2. Where the check runs: handoff successor step, coordinator after `worker_done`, before done (audit item or model step). A hook cannot make the model act at "session end" (Q3).
3. Orphans: list only, or also an owner `!` hint with the exact `cleanup --skip-ownership` command (as `cleanup` already prints).
4. Whether the shared checks move out of `cleanup` into a module (cleaner, touches up to 8 test files) or the new script loads `cleanup` with `importlib` (smaller, more fragile).
5. Whether the audit gets an item for "no unlisted owned worktree" (larger change to `hooks/workflow-audit`).
6. Whether the lineage file should leave `/tmp` so reboots keep it (a change to `runtime_dir.py`; outside this question).

## Sources

Commands run (all read-only), in this worktree on 2026-11-14:
- `orca --help`; `orca worktree --help`; `orca worktree list --json`; `orca worktree show --worktree path:<...> --json`; `orca worktree ps --help`; `orca worktree set --help`; `orca worktree rm --help` (help only); `orca terminal list --json`; `orca terminal list --help`; `orca orchestration --help`; `orca orchestration run-list --json`; `orca orchestration run-current --json`; `orca skills list`; `orca skills get orca-cli`.
- `git worktree list`; `git branch -a --merged origin/main`; `git rev-parse <branch>`; `git ls-remote origin refs/heads/<branch>`; `git merge-base --is-ancestor <branch> origin/main`; `git log -1`, `git status --porcelain` in the two example worktrees; `git ls-tree -r origin/main --name-only`.
- `gh pr list --state all --head <branch> --json number,state,headRefOid,mergedAt,baseRefName` for `mquesada02/splitter-gaps`, `research/handoff-audit-483`, `research/worktree-tracking`, `mquesada02/handoff-audit-483` (all `[]`).
- `env` (ORCA_TERMINAL_HANDLE, ORCA_WORKTREE_ID present).

Files:
- `~/.claude/CLAUDE.md` (lines 115, 119-154, 156-180, 186-198, 200-228, 236-241, 243-245).
- `~/.claude/settings.json` (hook list: Stop, SessionEnd, PostToolUse; read with a script).
- `~/.claude/hooks/context-handoff/hook.py` (lines 51-108, 228-259, 328-337, 423-446), `launch.py` (lines 134-157, 310-346, 424-456), `runtime_dir.py` (lines 11-23, 149-186).
- `~/.claude/hooks/worktree-cleanup/cleanup` (lines 1-26, 101-168, 171-233, 268-343, 362-379, 467-504), `cleanup_support.py` (lines 1-58, test stub).
- `/tmp/claude-context-handoff/lineage.jsonl` (59 lines; read the line for term_62e7e519).
- `~/.claude/docs/agents/docker.md`.
- `~/.claude/skills/orca-cli/SKILL.md` and `orchestration/SKILL.md` (stubs that load `orca skills get ...`); `~/.claude/hooks/workflow-audit/auditor-brief.md` (L1-L6).
- Claude Code hooks docs: https://code.claude.com/docs/en/hooks (sections Stop, SessionEnd), fetched through a summarizing tool; quoted lines were checked in the saved fetch output.

## Unverified / open points

- Whether SessionEnd runs when the terminal is closed, the process is killed or the machine reboots: not stated in the docs sections read. Unverified.
- Whether Orca terminal handles survive an Orca restart or reboot: not tested. Unverified.
- Whether a handle can be reused by a new terminal: not observed. Unverified.
- Docker check on the two example worktrees: not run. Unverified.
- The effect of `cleanup` on the two examples is derived from its source and the read data; `cleanup` was not run (it removes worktrees).
- Why `worktree-tracking` and `handoff-audit-483` have no `lineage` although created from a terminal in this repo (flag `--no-parent`, or no inference): not determined. Unverified.
- Size estimates are rough guesses from similar files in the repo, not measured.
- Orca `worktree create --help` was not read (a hook denies it without `--branch`); the lineage flags come from the Orca skill guide.
- Whether other repos' sessions use the same terminal-handle-based provenance: the counts (57 of 59) come from `worktree list`, but not from inspecting those repos.
