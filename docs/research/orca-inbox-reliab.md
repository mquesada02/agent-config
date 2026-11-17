# Worker reliability: open asks at turn end and restart recovery

Ticket 757, part of map 752 (request 750). Date of reading: 2026-11-17. Marks: **FACT** = quoted from the source. **INFERENCE** = our reading. The owner decides later; this file makes no decision.

## Question

Why do workers end a turn while an `ask` is open? Why did a PC restart lose a worker whose `--retry-of` was then refused? What would make both cases recover without the owner (hooks, Orca settings, brief text, a watcher in the central session)?

## Short answer

1. The open-ask cases have a built-in cause: Orca's own worker preamble and CLI help tell a worker to end its turn after `ask`, while `CLAUDE.md` section 7 says never to end it. The two instructions conflict.
2. Orca stores an ask as mail and wakes the worker with the reply. Recent logs show the wake working. The old "nobody wakes the worker" failures (October) were found before the coordinator rule "read the terminal after each reply" existed.
3. Other turn-ends are a separate failure: a worker ends its turn with no ask open and no `worker_done` (two cases seen in local logs).
4. The restart case: after the PC restart Orca closed the old dispatch as lost, and the Task went back to `ready`. `--retry-of` accepts only a failed or blocked Task, so it was refused (`task_not_startable`).
5. The recovery that worked in the one real restart case: a plain `worker-start --task` (no `--retry-of`) on the same worktree, plus a resume note. It needed the coordinator, not the owner.
6. Not found: any Orca code that restarts a dead worker terminal, or that expires a pending ask. A Stop hook can block a turn end today (the context hook does it), but nothing exposes the "open ask" state to a hook (INFERENCE).
7. Options with costs are in the section "Options for the owner".

## Findings

### F1. What the instructions say about turn end and ask

- FACT, `CLAUDE.md` section 7: "A worker never ends its turn while an `ask`, a background test run or a CI watch is open. It waits on them in the foreground (a blocking wait with no short timeout), or it keeps working on parts that they do not touch." Same rule in section 11.
- FACT, Orca's bundled orchestration guide (printed by `orca skills get orchestration --full`): "To ask your coordinator, run `ask`, then end your turn; Orca wakes you with the answer."
- FACT, the worker preamble that Orca injects: "Ask the coordinator, then end your turn; Orca wakes you with the answer."
- FACT, `orca orchestration ask --help` (read by a subagent): "From a worker, a new question goes to its coordinator and ask returns at once: end your turn, and Orca wakes you with the answer as mail. ... --wait and --resume block until the answer instead; --timeout-ms accepts 1 to 1800000 ms per wait (default 600000 = 10 minutes, max 30 minutes), and a timeout leaves the question pending."
- INFERENCE: a worker that follows the preamble (the text nearest to the command) breaks the section 7 rule. The rule can be kept only with `--wait` or `--resume`, and each wait lasts at most 30 minutes, so a long answer needs a loop of waits.

### F2. How Orca stores and wakes an ask

- FACT (Orca CLI help and bundled server code, read by a subagent): an ask is a stored mail message of type `question`. The dispatch stays `dispatched` during an ask. No "asking" state exists. Dispatch states: pending, dispatched, completed, failed, circuit_broken. Task states: pending, ready, dispatched, completed, failed, blocked. Worker states: starting, start_unknown, ready, stopping, stop_unknown, succeeded, failed, stopped, abandoned.
- FACT (bundled guide): `send` to a working worker "gets it when its current turn ends; a finished or closed one gets it as a follow-up Task and reports with `worker_done`".
- INFERENCE: nothing found that expires a pending question. If the worker's terminal is gone, no code was found that starts it again; the reply stays in the inbox.
- OBSERVATION from local logs (not tracked, paraphrased): in one case a worker ended its turn with a question open, and Orca woke it when the reply came, so no work was lost. In several other cases the coordinator confirmed a new worker turn after a reply; once the terminal first looked idle and a wake prompt was sent.

### F3. History of the open-ask failure

- FACT (issue 111, closed): four cases in October 2026 where a worker sent `ask`, ended its turn and sat idle for 1.5 to 7 hours. In one case "the answer landed in the worker's ask output file one minute after the worker ended its turn". The issue lists three proposals: a worker rule, a coordinator rule, and "Optional: a Stop hook in worker sessions that blocks ending the turn while the session has an open `ask`". The owner chose the first two and no hook (comment of 2026-11-03: "(c), not chosen").
- FACT: both rules are now in `CLAUDE.md` (section 7, the worker paragraph and the coordinator paragraph "after every `reply` to a worker, the coordinator reads the worker's terminal and confirms that a new turn started").
- OBSERVATION from local logs (paraphrased): after the two rules existed, turn ends happened again in at least 4 cases: three workers ended their turn while a background job ran, and one ended its turn with a question open. In the background-job cases the work continued, because Claude Code starts a new turn when a background shell exits. No work was lost in any case.
- INFERENCE: the rule does not hold by itself; the coordinator's read-the-terminal step is what catches it.

### F4. A second turn-end failure: no ask open, no `worker_done`

- OBSERVATION from local logs (paraphrased): in 2 cases a worker ended its turn with no question open and no `worker_done`. One had written a "next step" line as if it waited for a go-ahead. The coordinator sent a message and a wake prompt, and the worker resumed.
- INFERENCE: a Stop hook that blocks a turn end with neither an open ask nor a `worker_done` would cover this case and the open-ask case with one check.

### F5. Hooks that exist today

- FACT (`settings.json`): a `Stop` hook list runs `hooks/context-handoff/hook.py`. FACT (`hooks/context-handoff/hook.py`): it returns `{"decision": "block", "reason": ...}` to stop a turn from ending, re-blocks an ignored instruction and halts after 3 re-blocks (`MAX_REBLOCKS`).
- FACT (same file): the hook already knows the worker role from the injected preamble and tells a worker to read finished background `ask` outputs.
- INFERENCE: a worker Stop hook is feasible with this pattern. Open points: (a) how the hook learns that an ask is open (it would have to read Orca state or the worker's own log; no hook in this repo does either today), (b) a loop guard so a legitimately finished worker is not trapped (the 3-re-block halt is a model), (c) a worker that is told to "end your turn" by Orca would be blocked from doing the Orca-documented flow.

### F6. What happened in the restart case

- OBSERVATION from local logs (paraphrased): after the PC restart the coordinator first had to bind itself to the Run again (a `worker-start` before that failed with the Orca error code `consumer_fenced`). Then it ran `worker-start` with `--retry-of` for the old dispatch, and Orca refused it with the error code `task_not_startable`. The error data showed the Task status `ready`.
- FACT (Orca behaviour, F7): the refusal text names the rule: `--retry-of` must name the latest settled Dispatch of a failed or blocked Task.
- OBSERVATION from local logs (paraphrased): the coordinator then ran the same command without `--retry-of`. It started a new dispatch on the same worktree. The coordinator sent the new worker a resume note (state of the worktree, where the old worker stopped). Orca had marked the old dispatch as lost.
- OBSERVATION from local logs: the same `task_not_startable` error appears in at least 3 coordinator logs. INFERENCE: it is a repeating pattern, not a one-off.
- OBSERVATION from local logs: the coordinator also had to move files back from a backup folder, because `/tmp` content is lost at reboot. That is a separate restart cost (see Gaps).

### F7. Why `--retry-of` is refused

- FACT (Orca bundled server code, read by a subagent): the retry is accepted only if all hold: the dispatch exists and belongs to the Task; it is the Task's latest dispatch; the Task has no active remote placement; the worker state is `failed`, `stopped` or `abandoned` (or, with no worker row, the dispatch status is `failed`); and the Task status is `failed` or `blocked`. A running worker (starting, ready, stopping, start_unknown, stop_unknown) is not retryable.
- FACT (same source): without `--retry-of`, "only a ready Task can start".
- INFERENCE: after the restart the Task was `ready` (observed in the error data in local logs), so the plain start was allowed and `--retry-of` was refused by the Task-status check.
- FACT (bundled guide, recovery reference): "After three failed starts in one `--retry-of` chain, the Dispatch circuit-breaks and the Task fails." Reopening a circuit-broken Task is allowed only when the user explicitly asks. "Silence, a startup timeout, or `unverifiable` liveness alone never proves exit or authorizes autonomous stop, abandon, retry, or release." An `escalation` with `stopReason` `exited` or `lost` "means it is gone: retry it or tell the user."
- FACT (bundled guide): `worker-abandon` "fence[s] a worker without claiming its process stopped"; `worker-stop` can end with `stop_unknown`.

### F8. What Orca does at an app or PC restart

- FACT (bundled server code): coordination state lives in a local SQLite database (tables for dispatch contexts, worker dispatches, terminal resources, messages). Each worker row stores a runtime epoch.
- FACT (same source): reconcile is lazy, on read. A worker in `starting` with an old epoch becomes `start_unknown`; `stopping` becomes `stop_unknown`. A worker in `ready` has no conversion that was found.
- FACT (bundled guide): terminal handles are runtime-scoped; "after an Orca restart or a `terminal_handle_stale` error, re-list and continue with the replacement only".
- INFERENCE: a worker that was `ready` and working at restart can stay `ready` in the database with a dead terminal. Local logs show the final result was a lost dispatch and a `ready` Task; the code path that did this was not found.
- Not found: any heartbeat timeout that fails a worker, and any code that restarts a dead worker terminal.

### F9. Gate interaction (INFERENCE)

- FACT (`CLAUDE.md` section 7): "A hook blocks `orchestration worker-start` until this audit passes; a plain `worker-start --retry-of` for a worker handover is exempt".
- INFERENCE: the recovery that worked (plain `worker-start --task`, no `--retry-of`) is not in that exemption. It worked in the observed case, probably because the pre-dispatch audit of that Run had already passed; whether the gate would refuse it for a Run with no audit record was not tested.

## Options for the owner

Each option states its cost. They can be combined. Open asks first (O1 to O5), restart recovery after (R1 to R4).

- **O1. Fix the contradiction in the text.** Choose one flow and make `CLAUDE.md`, the worker brief template and the Orca preamble agree. Either (a) keep the section 7 rule and tell workers to use `ask --wait`/`--resume` in a loop (the preamble line cannot be edited; the brief would override it), or (b) allow "end the turn after a bare `ask`" and rely on Orca's wake plus the coordinator's terminal check. Cost: (a) a worker blocks a terminal for hours, with a 30-minute maximum per wait, and a worker that ends its turn anyway is not stopped; (b) the October failures (no wake) return if the wake ever fails, and the coordinator check becomes the only guard.
- **O2. A Stop hook for workers that blocks the turn end while an ask is open (or while there is no `worker_done`).** Same pattern as the context hook. Also covers F4. Cost: a new hook with tests; the hook needs a source for "ask open" that was not found (INFERENCE); a loop guard is needed; it conflicts with Orca's documented "end your turn" flow unless O1(a) is chosen. The owner rejected this hook in 2026-11 (issue 111); the owner may reconsider with F3 and F4.
- **O3. A watcher in the central session.** The central session lists its coordinators' workers on a schedule and wakes a worker whose terminal is idle with an open ask or a settled dispatch missing. Cost: it needs Orca read commands and a send command from a long-lived session; the guide says "Never poll or run watch scripts" for coordinators because a script's `check` takes the coordinator's mail (a watcher must use read-only commands such as `worker-list`, not `check`); more load on the owner's PC.
- **O4. Keep rule (b) and make it mechanical.** Add the "read the terminal after each reply" step to a coordinator checklist or script, with a time limit. Cost: low; it relies on the coordinator following the step, the same reliance as today.
- **O5. Brief text only.** Add one sentence to every worker brief: "Orca says to end your turn after ask; here you must wait with `ask --wait` in the foreground." Cost: cheapest; the logs show the rule failing several times even with the sentence in `CLAUDE.md`, so it is the weakest guard (INFERENCE from F3). It only overrides the conflicting Orca preamble line per brief; O1 removes the conflict itself.
- **R1. Write the restart runbook.** After a restart the coordinator runs `run-use`, `worker-list`, `worker-show` for each dispatch; for a Task that is `ready` with a lost dispatch it starts the Task again without `--retry-of`, on the same worktree, with a resume note. Cost: text only; the coordinator must prove the old worker is gone before it acts (bundled guide: silence alone is no proof), which is a manual step.
- **R2. A resume-note template or script.** It builds the note from the worktree (git status, last commit, the ledger) so a lost worker's state passes to the new one. Cost: a small script and tests; the note must not claim what was not seen (the `CLAUDE.md` handoff rules).
- **R3. Make the gate accept recovery starts.** Extend the pre-dispatch gate exemption to a plain `worker-start --task` for a Task that had a dispatch in this Run. Cost: a change to the audit hook and its tests; it weakens a gate, so section 0 applies and the owner must approve it.
- **R4. Sessions start themselves after a PC restart, so the central session does the runbook.** Cost: needs an auto-start of the central session (a local setup, per the map notes) and R1; the central session holds more state.

## Gaps and open questions

- No code was found that restarts a dead worker terminal, expires a pending ask, or fails a worker on a missing heartbeat. Absence in the code read is not proof; the bundled server code is one minified file.
- The exact flags of `worker-start --help` and `orchestration dispatch --help` were not read: a local hook blocked those two help calls. The flags come from Orca's own CLI spec file.
- The code path that turned the old dispatch into a lost dispatch and the Task into `ready` was not found. Only local logs show the result.
- Not tested live (the task forbids orchestration commands): whether a plain `worker-start --task` passes the pre-dispatch gate in a Run with no audit record; whether `ask --wait` survives a restart.
- How a hook could learn that an ask is open is unknown. Candidates: the worker's own ask output file, a worker-side marker, or an Orca read command; none was tested.
- Counts are small: four cases in issue 111, about six later turn-end cases in local logs, three logs with `task_not_startable`. No rate per worker-hour exists. The restart case is one real recovery.
- A restart also loses `/tmp` content (scratchpad briefs, the audit folder). The coordinator moved files to a backup folder by hand before the restart and restored them after. This is outside ticket 757 and is listed for the owner.
- The background-job cases may be a different failure: a worker waits on a background job, not on an ask. The rule in section 7 names it, and Claude Code's own background-job wake saved it.

## Sources read and sources that failed

**Read (this repo):**
- `CLAUDE.md` sections 7, 8, 11 and 13 (worker and coordinator paragraphs, no-polling and context rules).
- `docs/research/agent-workflow-comparison.md` (prior research 723; it proposes workers that log rulings and ask on four stop conditions, which would lower the number of asks but not fix a turn end).
- `skills/orchestration/SKILL.md` (stub that loads Orca's guide).
- `settings.json` hook list; `hooks/context-handoff/hook.py` (block pattern, role slots, re-block cap).
- Issue 111 (body and the triage comment), issue 752 (map), issue 757 (ticket), through the REST API (`gh api repos/<owner>/<repo>/issues/<n>`).

**Read (outside this repo, local, read-only):**
- Orca's version-matched guide: `orca skills get orchestration --full` (ask, wake, recovery, retry, circuit breaker, abandon, stop).
- Orca CLI help text and its bundled CLI spec and server files (read by a Sonnet subagent): ask, worker-start, worker-stop, worker-abandon, worker-release, worker-show, reset, request-show; the retry check; the state tables; the runtime-epoch reconcile.
- Coordinator session logs (local, private, not tracked; paraphrased as observations, never quoted): one restart recovery, three logs with `task_not_startable`, and about six turn-end cases.

**Failed or not read:**
- `worker-start --help` and `orchestration dispatch --help`: blocked by a local hook; replaced by the CLI spec file.
- The live Orca database: not queried.
- No web source was used; no URL was fetched.
- One subagent (Sonnet, read-only) read the Orca files. Its report is the source of the Orca code facts above; they were not re-read by this worker, except the bundled guide, which this worker read itself.
