Research for mquesada02/agent-config#258 (map #257).

# Orca CLI facts for a Run-based cleanup ownership proof

Date: 2026-10-30. Binary: `orca-ide` (the same runtimeId `33045c64` answered every call). Every call below was read-only. Ids are shortened; `W/` stands for `/home/mquesada/orca/workspaces/`.

Legend: **observed** = a live call showed it; **documented** = the help text or the guide (`orca-ide skills get orchestration --full`, the version-matched guide that `/home/mquesada/.claude/skills/orchestration/SKILL.md` points to) states it; **unknown** = neither source shows it.

This session: `$ORCA_TERMINAL_HANDLE` = `term_6c10c05c-8b12-468a-8614-02e88bf76f79`. Its terminal anchor (`terminal show`) is the main checkout `/home/mquesada/.claude`.

## Summary of the traps for a fail-closed rule

1. `run-current` for this terminal returns Run `run_ee659055d3ae`, whose `coordinator_handle` is `term_433a3a60`, not this terminal. No Run in `run-list` has `coordinator_handle == $ORCA_TERMINAL_HANDLE`. So a rule "find the Run whose `coordinator_handle` equals my handle" finds nothing for this session, while `run-current` finds a Run.
2. `worker-list --run <unknown id>` returns `ok: true` with zero rows. `dispatch-show --task <unknown>` returns `ok: true` with `dispatch: null`. An empty success is not proof of anything.
3. A Dispatch keeps `worktreeId` after its worktree is removed (92 of 101 worktrees in the big Run no longer exist), and `worktree show` then fails with `selector_not_found`.
4. `worker-list` has no worktree filter.
5. `resource` can be `null` on a Dispatch (5 of 150); the worktree is then in `projection.workspace.id` (and in `worker-show` `.worker.worktreeId`).

## Q1. How does a session find the Run whose `coordinator_handle` equals its handle? Can one handle coordinate several Runs?

### run-current

Command: `orca-ide orchestration run-current --json` (help, documented: `run-current [--from <handle>] [--json]`, "Show the Run bound to this coordinator").

Observed, from this terminal (`term_6c10c05c`):

```
ok: true
result.run = { id: run_ee659055d3ae, objective: "Splitter gaps (map #125): ...",
  coordinator_handle: term_433a3a60-6bef-420d-bb20-6d04c6ff1bf6, consumer_generation: 3,
  legacy: 0, created_at: 2026-10-26T20:53:45Z, updated_at: 2026-10-28T19:00:49Z }
```

The same Run came back on every call in this session. The returned `coordinator_handle` (`term_433a3a60`) differs from `$ORCA_TERMINAL_HANDLE` (`term_6c10c05c`). So what `run-current` returns is not "the Run whose `coordinator_handle` equals the caller handle". The mechanism behind the binding is **unknown**: the help and the guide say only "the Run bound to this coordinator" and "an attested current binding" (guide line 302). Also observed: `terminal show --terminal term_433a3a60...` returns `terminal_handle_stale` (that mailbox terminal no longer exists).

Does it depend on `$ORCA_TERMINAL_HANDLE`? Observed: the caller is attested by Orca, not read from the env var. `run-current --from <other handle>` fails closed:

```
orca-ide orchestration run-current --from term_433a3a60-6bef-420d-bb20-6d04c6ff1bf6 --json
-> ok: false, error.code: consumer_fenced,
   message: "This terminal is attested as term_6c10c05c-... and cannot act as term_433a3a60-...",
   data.effectsApplied: false
```

Same result with `--from term_bogus` and `--from term_46dbdce6-b000-4` (the coordinator of the big Run). So: the result depends on the attested identity of the calling terminal (Orca resolves the caller inside an Orca terminal; the guide says "Omit `--terminal` inside an Orca terminal, where Orca resolves the caller", line 415) and `--from` cannot name another handle. Whether the binding is keyed by terminal handle, pane, or something else is **unknown** (I could not call from a second terminal; that needs a write or a second session). Outside an Orca terminal there is no sender handle (documented in memory `orca-coordinator-outside-terminal.md`: `no_active_sender_terminal`; not re-tested).

### run-list

Command: `orca-ide orchestration run-list --json --limit 100` (help: `[--limit <n>] [--cursor <cursor>]`).

Observed: `ok: true`, `result.runs` (60 rows), `result.nextCursor: null` (the whole list fit; no `page` object). Row fields: `id, objective, coordinator_handle, consumer_generation, legacy, created_at, updated_at`. With `--limit 2` the result has a `nextCursor` (base64 JSON `{createdAt, id}`), so paging exists. `run-list --json` with no limit also returned 60 rows and `nextCursor: null` (the default limit is therefore at least 60; exact value **unknown**). Newest `created_at` first.

Match on this terminal's handle: 0 of 60 rows have `coordinator_handle == term_6c10c05c-...`. Rows with `coordinator_handle: null`: 4 (`run_d7f6ec860e51`, `run_3f38e96fb65c`, `run_5c1f3e514f01`, `run_legacy_local`; the last has `legacy: 1`). Rows that name the Runs of interest: `run_ee659055d3ae` -> `term_433a3a60-6bef-420d-bb20-6d04c6ff1bf6`; `run_6cec8b916ace` -> `term_46dbdce6-b000-4c30-aa59-539db756512a`.

### Can one handle coordinate more than one Run?

Observed: in the 60 rows, no `coordinator_handle` value repeats (the only repeated value is `null`, 4 times). So no handle coordinates two Runs today. Whether Orca allows it (for example a second `run-use` from the same terminal) is **unknown**; the help says only "Bind this coordinator to an existing Run". I did not run `run-use`. A rule that scans `run-list` must handle zero, one or several matches.

`run-show --id <run>` returns the same Run object as `run-list` (observed for `run_ee659055d3ae` and `run_6cec8b916ace`).

## Q2. How to list every worker Dispatch of a Run with its worktree

Command: `orca-ide orchestration worker-list --run run_6cec8b916ace --json --limit 100`, then the same with `--cursor <page.nextCursor>`.

Help (documented): `worker-list [--run <run_id>] [--terminal-state <active|reclaimable|retained|release_pending|release_unknown|released>] [--include-remote] [--cursor <cursor>] [--limit <1-100>] [--json]`. Notes: "Returns at most 100 local rows, newest first, by default"; "Without --run the list is scoped to the Run bound to the calling terminal, and to every Run when there is no binding; the receipt reports which in scope.source (flag, bound, or all)"; "Context-only Dispatches created by orchestration dispatch are included as unsupervised with terminal state retained".

Observed result shape: `result = { workers[], counts, page, warnings, scope }`.

- Page 1: `workers` has 100 rows; `page = {limit: 100, total: 150, hasMore: true, nextCursor: "eyJ2ZXJzaW9uIjoyLCJ..."}`; `warnings: ["Showing 100 of 150 Dispatches, newest first; more are on later pages. Follow page.nextCursor with --cursor."]`; `scope = {run: run_6cec8b916ace, source: "flag"}`.
- Page 2 (with `--cursor`): 50 rows; `page = {limit: 100, total: 150, hasMore: false, nextCursor: null}`. 100 + 50 = 150 unique `dispatchId`s.
- `counts` (always the whole Run, even under a filter): `{active: 1, retained: 140, released: 9}`.
- Run size: 150 Dispatches, 101 distinct `resource.worktreeId`/worktrees, 16 repo ids (`worktreeId` is `<repoId>::<absolute path>`; first segment is the repo id). Dispatches per worktree: up to 5 (`windsail-db/t228-contact-table`), 29 worktrees have more than one.
- A row has `dispatchId, taskId, runId, workerState, dispatchStatus, agentTerminalHandle, terminalState, resource, projection`. The worktree is in `resource.worktreeId` and `projection.workspace.id` (equal when both exist).
- No `creator`, `retryOf` or `creator_handle` field in the list rows; those need `worker-show` (`retryOfDispatchId`) or `dispatch-show` (`creator_handle`).

Filters: only `--run`, `--terminal-state`, `--include-remote`, `--limit`, `--cursor`. Observed: `--terminal-state released --run run_6cec8b916ace` returns `page.total: 9`, 9 rows (`counts` still whole-Run). **There is no worktree filter**: `worker-list --worktree x` -> `ok: false`, `error.code: invalid_argument`, "Unknown flag --worktree for command: orchestration worker-list", `data.validFlags: [cursor, environment, help, include-remote, json, limit, pairing-code, run, terminal-state]`. A consumer filters the rows itself (`resource.worktreeId == <target id>`), paging until `page.hasMore` is false.

Default scope: `worker-list --json --limit 1` with no `--run` returned `scope = {run: run_ee659055d3ae, source: "bound"}`, `page.total: 19`, i.e. it uses the same binding as `run-current`.

`--include-remote`: documented only (adds connected-server observations); not called.

## Q3. Does a released, completed, stopped or abandoned Dispatch keep its worktree? What does a `--retry-of` handover record?

Method: `worker-list` for the 150 Dispatches of `run_6cec8b916ace`, then `orca-ide orchestration worker-show --dispatch <id> --json` for every one of them (150 calls, all `ok: true`), and `dispatch-show --task <task> --json`.

**Observed: all 150 Dispatches keep their worktree, in every state.** `worker-show` -> `.worker.worktreeId` was non-empty for 150 of 150, equal to `.projection.workspace.id` for 150 of 150. Terminal states in the Run and examples (worktreeId shown without the `<repoId>::/home/mquesada/orca/workspaces/` prefix):

| terminalState | count | workerState / dispatchStatus | example Dispatch | worktreeId |
|---|---|---|---|---|
| active | 1 | ready / dispatched | `ctx_95de0cfb6926` | `windsail-api/ticket-212-integration-tests` (resource.ownershipState `owned`) |
| retained | 140 | succeeded/completed 111, abandoned/failed 28, failed/failed 1 (5 of these have `resource: null`, see the caveat) | `ctx_da52fe9f1741` (abandoned/failed) | `marketlink-ingestion/t274-spooled-reps` (ownershipState `external`, retainedReason `external_terminal`) |
| retained | (same) | succeeded/completed | `ctx_0cdd8dd46c0c` | `windsail-api/ticket-191-group-b` (ownershipState `user_owned`, retainedReason `user_takeover`) |
| released | 9 | succeeded/completed 7, failed/failed 2 | `ctx_de8b599d4857` | `windsail-api/ticket-193-swagger-docs` (ownershipState `released`, releaseState `released`) |
| released | | failed/failed | `ctx_4458e16f24a3` | `windsail-crosswalk-standalone/t101-office-normalizer` |

(Total by `workerState`: succeeded 118, abandoned 28, failed 3, ready 1. No `stopped` Dispatch exists in this Run, so a stopped Dispatch is **unknown** by observation; the guide says `worker-stop` "never deletes the worktree" and `failed or stopped` Dispatches are retried with `--retry-of`, documented.)

**Caveat, observed: `resource` can be `null`.** 5 retained Dispatches have `resource: null` in `worker-list` (and `terminalResource: null` in `worker-show`): `ctx_a5946300e4c5`, `ctx_b2f9e4b41500`, `ctx_800148e43584`, `ctx_11e928e85885` (succeeded) and `ctx_2428bd239002` (failed). Their worktree is still in `projection.workspace.id` and `.worker.worktreeId`. Consumers should read the worktree from `projection.workspace.id` (or `worker-show` `.worker.worktreeId`), not only `resource.worktreeId`.

**Observed: the Dispatch outlives its worktree.** Of the 101 distinct worktree ids, `orca-ide worktree show --worktree id:<worktreeId> --json` found 9 and returned `ok: false`, `error.code: selector_not_found` for 92. Example: the released `windsail-api/ticket-193-swagger-docs` -> `selector_not_found` (the error data lists `validSelectorForms`), while the active `ticket-212-integration-tests` returns the record with `parentWorktreeId` = `.../windsail-api/coord-re...` (a per-repo coordinator worktree), `cliProvenance = {kind: created-by-cli, createdAt, callerTerminalHandle: term_64494c36...}`, `lineage`, `childWorktreeIds`. All 9 found worktrees have `cliProvenance.kind == created-by-cli`; their `parentWorktreeId` values are two coordinator worktrees (`coord-rep-hierarchy-takeover` 5, `rep-hierarchy-selling-agreement...` 4).

### `--retry-of` and handover

Help for the start command is blocked by this session's audit hook (the hook denies any command line that contains that verb; so no `--help` text from the binary). Documented instead in the guide (lines 683-700, 740): "Retry only a positively proven failed or stopped attempt. Name the failed Task with `--task`... Placement is never silently inherited: `worker-start --task <task_id> --retry-of <dispatch_id> --worktree <explicit_placement> --agent <agent>`"; "A `--retry-of` replacement for a `failed` worker releases the terminal that worker still owns"; after three consecutive failures `--retry-of` is refused with `task_not_startable`.

Observed (`worker-show` `.dispatch.retryOfDispatchId`): 30 of 150 Dispatches have it set (the field is `retryOfDispatchId`; `dispatch-show` calls it `retry_of_dispatch_id`). All 30 targets are Dispatches of the same Run, and **all 30 retries are on the same worktree id as the Dispatch they retry** (30 of 30). Example: `ctx_d2dddd857c4a` (completed) `retryOfDispatchId = ctx_da52fe9f1741` (abandoned/failed); both on `marketlink-ingestion/t274-spooled-reps`. Example with release: `ctx_4458e16f24a3` (released, failed) retries `ctx_a285003f41bf` (released, failed), both on `windsail-crosswalk-standalone/t101-office-normalizer`. Chains exist (`ctx_cec50a3f1caf` -> `ctx_5044bdb1ecc7` -> `ctx_4603f8c8bd84`). `creatorDispatchId` was null for all 150.

So a retry creates a new Dispatch on the same worktree (a new `worker.effects` entry with `kind: worktree`, `action: reused` for 149 of 150; the 150th, `ctx_a285003f41bf`, has `action: created_child`, i.e. the Dispatch that created the worktree). The worktree is shared by 2 to 5 Dispatches; only one of them is the "creator" of the worktree. A different link also exists: `terminalResource.originDispatchId != ownerDispatchId` on 4 released Dispatches (for example `ctx_de8b599d4857`: origin `ctx_a5946300e4c5`, owner `ctx_de8b599d4857`; the origin has `resource: null`); that records a terminal-resource adoption, with `retryOfDispatchId` null on both.

### Who created each Dispatch (`creator_handle`)

Command: `orca-ide orchestration dispatch-show --task <task_id> --json` -> `result.dispatch` (snake_case fields) including `creator_handle`, `creator_pane_key`, `assignee_handle`, `run_id`, `retry_of_dispatch_id`, `consumer_generation`.

Observed for the 150 Dispatches of `run_6cec8b916ace`: `creator_handle` takes 20 distinct values (23, 17, 14, 14, 9, 9, ... Dispatches each). Only 1 Dispatch has `creator_handle == term_46dbdce6-...`, which is the Run's current `coordinator_handle`. So `creator_handle` is the terminal of whichever coordinator session started that Dispatch, and it is not equal to the Run's current `coordinator_handle` for 149 of 150. A rule "the Dispatch's `creator_handle` equals my handle" proves ownership only of the Dispatches that this very terminal created.

## Q4. Where does `coordinator_handle` change? Does a worker's preamble change it?

- **Documented:** `run-create` ("Create and bind a lightweight orchestration Run", guide line 105) and `run-use` ("Bind this coordinator to an existing Run"; with `--takeover-legacy` "binds the authenticated invoking terminal; `--from` cannot nominate another coordinator. It fences only the old coordinator", guide lines 359-365). `consumer_generation` is the per-Run counter shown in the Run object (`run_6cec8b916ace` is at 18, `run_ee659055d3ae` at 3); "fenced" callers get `consumer_fenced` (guide lines 806-810).
- **Documented:** a dispatched worker does not call these: "Do not `run-create` or `run-use` for them" (guide lines 815-816); the worker's preamble lists `send`, `ask`, `check`, `worker-start --from`, no `run-use`.
- **Observed:** `dispatch-show --task task_3b696484f146 --preamble --json` returns `result = {dispatch, preamble}`. The preamble text starts "Your coordinator's terminal handle is: term_6c10c05c-..." which is **this session's** handle, although that Dispatch's `creator_handle` is `term_46dbdce6-...` and its Run's `coordinator_handle` is `term_46dbdce6-...`. So the preamble is rendered for the caller, and is not a record of the Run's coordinator. Before and after that call, `run-show --id run_6cec8b916ace` showed `coordinator_handle: term_46dbdce6-b000-4c30-aa59-539db756512a`, `consumer_generation: 18`, `updated_at: 2026-10-30T13:40:59Z` (unchanged), and `run-current` still returned `run_ee659055d3ae`.
- **Unknown:** whether other commands (a coordinator handover to a successor, `check`, an Orca restart, `run-use --retry-request`) change `coordinator_handle`; the help of `run-use` lists `[--from <handle>] [--takeover-legacy] [--retry-request <id>]`. I did not call any write command. Whether `run-use --from X` sets `coordinator_handle` to X while the binding that `run-current` reads stays with the attested terminal is **unknown**, but the observed state (Run `coordinator_handle = term_433a3a60`, `run-current` from `term_6c10c05c` returns that Run) is consistent with it; the repo memory note `orca-coordinator-outside-terminal.md` says a mailbox terminal was used as `--from` for this Run's setup.

## Q5. Error shapes (for the fail-closed rules)

Every call returns the envelope `{id, ok, result|error, _meta: {runtimeId}}`; a failure has `ok: false` and `error = {code, message, data?}` (some also have `data.nextSteps`). Observed:

| Command | Condition | Result |
|---|---|---|
| `run-current --from <not the attested handle>` | the handle differs from the caller | `ok: false`, `consumer_fenced`, `data.effectsApplied: false` |
| `run-show --id run_nonexistent` | unknown Run | `ok: false`, `run_not_found`, "Run run_nonexistent was not found." |
| `run-show` (no `--id`) | missing flag | `ok: false`, `invalid_argument`, "Missing required --id"; `_meta.runtimeId: null`, `id: "local"` (rejected by the CLI before the runtime) |
| `run-list --limit 101` | over the limit | `ok: false`, `invalid_argument`, "Too big: expected number to be <=100" |
| `run-list --cursor garbage` | bad cursor | `ok: false`, `cursor_invalid`, "The Run list cursor is invalid." |
| `worker-list --run run_nope` | unknown Run | **`ok: true`**, `workers: []`, `counts: {}`, `page.total: 0`, `scope = {run: run_nope, source: flag}` |
| `worker-list --limit 101` | over the limit | `ok: false`, `invalid_argument`, "Too big: expected number to be <=100" |
| `worker-list --cursor garbage` | bad cursor | `ok: false`, `invalid_argument`, "Unknown worker-list cursor garbage." (`data.nextSteps`) |
| `worker-list --terminal-state bogus` | bad value | `ok: false`, `invalid_argument`, "invalid --terminal-state 'bogus', expected one of: ..." |
| `worker-list --worktree x` | unknown flag | `ok: false`, `invalid_argument`, "Unknown flag --worktree ..." with `data.validFlags` |
| `worker-show --dispatch ctx_nope` | unknown Dispatch | `ok: false`, `dispatch_not_found`, "Worker Dispatch ctx_nope was not found." |
| `worker-show` (no flag) | missing flag | `ok: false`, `invalid_argument`, "Missing required --dispatch" |
| `dispatch-show --task task_nope` | unknown Task | **`ok: true`**, `result.dispatch: null` |
| `terminal show --terminal term_bogus` / stale `term_433a3a60...` | handle not live | `ok: false`, `terminal_handle_stale`, message `terminal_handle_stale`, `data.nextSteps` (the server-bound handle hint) |
| `worktree show --worktree id:nope` / an id of a removed worktree | no such worktree | `ok: false`, `selector_not_found`, `data.selector`, `data.validSelectorForms` |

Fail-closed implications (observed): treat any `ok != true`, any non-JSON output, a missing `result.run` (for `run-current`), and a missing `page` or `hasMore: true` that was not followed to the end (for `worker-list`) as "no proof". An `ok: true` with zero rows from `worker-list`, or `dispatch: null` from `dispatch-show`, must also count as "no proof", not as "no owner found". Other documented codes (the guide's "Refused starts" table for the start verbs: `task_not_found`, `task_not_startable`, `inject_rejected`, `runtime_error`; `request-show` states `pending`/`absent`) are for write calls and were not exercised. The error code for a caller outside an Orca terminal is documented in the repo memory (`no_active_sender_terminal`) and was not re-tested.

## Sources

- `orca-ide orchestration --help`, `... run-current|run-list|run-show|run-use|worker-list|worker-show|dispatch-show --help`, `orca-ide worktree show --help`, `orca-ide terminal show --help` (the start verb's `--help` is blocked in this session by the audit hook, so it was not read).
- `orca-ide skills get orchestration` and `... --full` (the version-matched guide that `/home/mquesada/.claude/skills/orchestration/SKILL.md` delegates to; no local copy of the Orca source exists under `/home/mquesada/.claude/skills` or `/home/mquesada/.claude/plugins`).
- Live calls with `--json`: `run-current`, `run-list`, `run-show`, `worker-list`, `worker-show`, `dispatch-show` (with and without `--preamble`), `worktree show`, `terminal show`, on Runs `run_6cec8b916ace` and `run_ee659055d3ae`.
- Ownership code: `/home/mquesada/.claude/hooks/worktree-cleanup/cleanup`, `anchor_worktree` (reads `terminal show` -> `result.terminal.worktreeId`) and `check_ownership` (compares the anchor with `record.id`/`record.parentWorktreeId` and `cliProvenance.callerTerminalHandle` with the handle).
