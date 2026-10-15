# Transcript audit facts

Ticket: mquesada02/agent-config#84, "Can a script read the audit facts from transcripts?"
Observed on Claude Code 2.1.300 (Linux), Orca 1.4.223, 843 local transcripts under `~/.claude/projects/` (versions 2.1.260 to 2.1.300). Dates: 2026-10-15. IDs are shortened; prompts and tool output are not quoted.

The Claude Code docs say the entry format is not a stable interface (sessions.md, "Where transcripts are stored"):
> "The entry format is internal to Claude Code and changes between versions, so scripts that parse these files directly can break on any release."

So every parser must check `version` and fail loud on unknown shapes (see section 5).

Doc URLs fetched raw as `https://code.claude.com/docs/en/<page>.md`: `sessions`, `hooks`, `env-vars`, `sub-agents`, `claude-directory`, `settings-reference`.

---

## 1. A session finds its own transcript

### Env vars seen by a Bash tool command (`env | grep -i -E 'claude|orca'`, secrets omitted)

| Variable | Observed value (shape) | Use |
|---|---|---|
| `CLAUDE_CODE_SESSION_ID` | `2e56c352-...` (equals the transcript file name) | Session id. Documented. |
| `CLAUDE_CODE_ENTRYPOINT` | `cli` | |
| `CLAUDE_PID`, `CLAUDECODE=1`, `CLAUDE_CODE_EXECPATH`, `CLAUDE_EFFORT` | pid, `1`, binary path, `medium` | |
| `CLAUDE_CODE_CHILD_SESSION=1`, `CONTEXT_HANDOFF_SUCCESSOR` | set here because this session was started by the context-handoff launcher | local hook machinery, not a Claude Code contract |
| `ORCA_TERMINAL_HANDLE` | `term_f0d6...` | Orca terminal handle of this session |
| `ORCA_AGENT_PANE`, `ORCA_PANE_KEY` | `<tabId>:<leafId>` | key into Orca's hook status file (section 4) |
| `ORCA_WORKTREE_ID`, `ORCA_WORKSPACE_ID` | `<repoId>::<worktree path>` | |

Not present: `CLAUDE_SESSION_ID`, any `*TRANSCRIPT*` variable, any `CLAUDE_CONFIG_DIR`, any variable naming the current agent/subagent id.

Doc (env-vars.md):
> "`CLAUDE_CODE_SESSION_ID` | Set automatically to the current session ID in Bash and PowerShell tool subprocesses, hook command subprocesses, and stdio MCP server subprocesses. For Bash, PowerShell, and hooks this matches the `session_id` field in the hook JSON input and is updated on `/clear`."

Observed: this session ran `/clear` at 15:02Z (a `system`/`local_command` record with `commandRun.command = "clear"`). The env var is the post-clear id (`2e56...`) and equals the new file name. It is correct.

A Bash command run inside a subagent sees the parent's `CLAUDE_CODE_SESSION_ID` (this research ran in a subagent and read `2e56...`, the parent). The env gives no way to tell main agent from subagent. Hooks get `agent_id` / `agent_type` in stdin (hooks.md, "Common input fields").

### Hook stdin

Fields (hooks.md, "Common input fields"): `session_id`, `prompt_id`, `transcript_path`, `cwd`, `scratchpad_dir`, `permission_mode`, `effort`, `hook_event_name`. Doc:
> "`transcript_path` | Path to conversation JSON. The transcript file is written asynchronously and may lag the in-memory conversation, so it may not yet include the current turn's most recent messages when a hook fires."

`SubagentStop` adds `agent_id`, `agent_type`, `agent_transcript_path`, `last_assistant_message` (hooks.md): "The `transcript_path` is the main session's transcript, while `agent_transcript_path` is the subagent's own transcript stored in a nested `subagents/` folder."

A hook is the most exact route: it gets the full path. Observed in this repo: `hooks/context-handoff/hook.py` reads `data.get("transcript_path")`.

### Path from a Bash command

```
~/.claude/projects/<project>/<CLAUDE_CODE_SESSION_ID>.jsonl
```

`<project>` is the cwd with every non-alphanumeric character replaced by `-` (sessions.md: "your working directory path with non-alphanumeric characters replaced by `-`. For a working directory whose converted name exceeds 200 characters, Claude Code truncates the name to 200 characters and appends a hash of the full path").

Verified on all 842 local transcripts that have a `cwd`: `re.sub(r'[^A-Za-z0-9]','-',cwd)` equals the directory name in 841. Examples:

| cwd | project dir |
|---|---|
| `~/.claude` | `-home-<user>--claude` (`/.` becomes `--`) |
| `~/orca/workspaces/.claude/handoff-6-worker` | `-home-<user>-orca-workspaces--claude-handoff-6-worker` |
| `~/orca/workspaces/<other-repo>/<branch>` | `-home-<user>-orca-workspaces-<other-repo>-<branch>` |

The encoding is one-way (`-` could be `/`, `.` or a literal `-`). A script must encode a known cwd. It must not decode a directory name.

Which cwd? The directory comes from the cwd at session start, not the current cwd. Per-row `cwd` changes when the Bash tool `cd`s: 312 of 843 transcripts have more than one `cwd` value (for example `.../quality-ts` then `.../quality-ts/docs/research`). The one mismatch among the 842 is a session whose first row `cwd` was another repo while the file sits in `orca-broadcast`; the dir is the start cwd. The `cwd` of a Bash tool call is not a safe input. A robust script avoids guessing and uses, in order:
1. `transcript_path` from hook stdin.
2. Glob `~/.claude/projects/*/$CLAUDE_CODE_SESSION_ID.jsonl` (the id is a UUID, unique across project dirs).

Overrides that break the encoding (env-vars.md): `CLAUDE_CONFIG_DIR` moves `~/.claude`; `CLAUDE_CODE_PROJECT_DIR_NAME` "choose[s] the `projects/` directory name ... in place of one derived from the working directory path". Neither is set here. Globbing works with both only if the script also reads `CLAUDE_CONFIG_DIR`.

Worktree vs main checkout: a session started in a worktree gets the project dir of the worktree path. A session started in the main checkout that later uses `EnterWorktree` keeps the old dir and records `{"type":"worktree-state","worktreeSession":{...,"worktreePath":...}}` and `{"type":"relocated","relocatedCwd":...}` rows (seen in `-home-<user>-Documents-Projects-<other-project>/777c...`). Orca worker sessions start in the worktree, so dir and worktree match (for example `.../orca/workspaces/.claude/<name>` gives `-home-<user>-orca-workspaces--claude-<name>`).

Session id inside the file:
- `sessionId` (camelCase) equals the file name in all 843 files. Use it.
- `session_id` (snake_case) appears on about half the rows and is stale after `/clear`: in this file 581 rows carry `4e77a7b4...` (the startup id) while `sessionId` is `2e56c352...`. 11 local files have a `session_id` that differs from the file name. Do not use `session_id`.
- The background-task output dir also uses the startup id: `/tmp/claude-1000/-home-<user>--claude/4e77a7b4-.../tasks/<taskId>.output`.

---

## 2. Subagents

### Where they live

Doc (sub-agents.md): "find IDs in the transcript files at `~/.claude/projects/{project}/{sessionId}/subagents/`. Each transcript is stored as `agent-{agentId}.jsonl`." claude-directory.md: "`projects/<project>/<session>/subagents/` | Subagent conversation transcripts, removed with the parent session transcript when it ages out".

Observed:
```
~/.claude/projects/-home-<user>--claude/2e56c352-.../subagents/agent-a770e6abe3646e284.jsonl
~/.claude/projects/-home-<user>--claude/2e56c352-.../subagents/agent-a770e6abe3646e284.meta.json
```
The subagent rows are not inline in the parent file. All rows in the subagent file have `isSidechain: true`, `agentId`, and the parent's `sessionId`. Nested subagents sit in the same flat `subagents/` dir; their `.meta.json` has `parentAgentId`. 24000+ local subagent files all have a `.meta.json`.

### `.meta.json` (real, redacted)

```json
{"agentType":"general-purpose","description":"Standards review of handoff diff","toolUseId":"toolu_01BGhh...","spawnDepth":1,"requestShape":"background","requestNonInteractive":true,"model":"sonnet"}
```
Keys seen: `agentType`, `description`, `toolUseId`, `spawnDepth`, `model`, optional `requestShape`, `requestNonInteractive`, `parentAgentId`, `spawnedWithWorktree`, `inheritedWorktreePath`. Counts of (`agentType`, `model`): (general-purpose, sonnet) 23898; (Explore, sonnet) 36; (fork, inherit) 27; (claude, sonnet) 20; (general-purpose, haiku) 3; (general-purpose, null) 2.

`meta.model` is the requested alias (`sonnet`, `inherit`, `null`). It is not the model used.

### Mapping parent `Agent` tool_use to the subagent file

Parent, assistant row, content block (one block per row):
```json
{"type":"tool_use","id":"toolu_01BGhhTB...","name":"Agent","input":{"description":"Standards review of handoff diff","subagent_type":"general-purpose","model":"sonnet","prompt":"..."}}
```
Parent, matching user row (`tool_result.tool_use_id` equals the tool_use `id`), with `toolUseResult`:
```json
{"isAsync":true,"status":"async_launched","agentId":"a770e6abe3646e284","description":"Standards review of handoff diff","resolvedModel":"claude-sonnet-5-5","prompt":"...","outputFile":"/tmp/claude-1000/...","canReadOutputFile":true,"canContinueAgent":true}
```
Join chain: `tool_use.id` = `meta.toolUseId` = `tool_result.tool_use_id`; `toolUseResult.agentId` = file name `agent-<agentId>.jsonl`. In 706 of 706 joined local agent launches in the `-home-<user>--claude` project, all three agree: input `model: sonnet`, `resolvedModel: claude-sonnet-5-5`, and every assistant row in the subagent file has `message.model: claude-sonnet-5-5`. Every `toolUseResult` for `Agent` in the local data is `async_launched` (1101 of 1101); the foreground shape was not seen.

### Model actually used

Read `message.model` of each `assistant` row in the subagent file (here `claude-sonnet-5-5`; 0 rows with `<synthetic>` in 3000 files checked). `toolUseResult.resolvedModel` (parent) is the second source. The `model` field of the `Agent` input is only a request and can be absent (inherit). The row also has `requestedModel` and `advisorModel`.

### Final report

Two shapes:
1. Subagent file: the last `assistant` row has a tool_use `SubagentHandback` with `input.message` (the full report). Seen in 8 of 9 subagent files here. Older/other agents end with a plain text block.
2. Parent file: a `queue-operation` (`operation: "enqueue"`) and a `user` row with
   `origin: {"kind":"peer","from":"<agentId>","senderTaskId":"<agentId>","name":"general-purpose","handback":true,"handbackReportText":"<report>","body":"..."}`. `handbackReportText` is the clean report.
   The task-notification row says: "This agent's report was delivered to you as a message from ... (its SubagentHandback call). Read it there; it is not repeated here." The notification carries `<status>completed|failed|killed</status>` and `<usage><subagent_tokens>..</subagent_tokens><tool_uses>..</tool_uses><duration_ms>..</duration_ms></usage>`.
3. Hook route: `SubagentStop` stdin has `last_assistant_message` and `agent_transcript_path`.

Other facts:
- Statuses in the notification summary (all local transcripts): `Agent "X" finished` (completed), `was stopped by Claude` (killed, 32), `failed: Agent terminated early due to an API error ...` (failed; session limit or login expired). A reviewer that died has no report; the audit must treat a missing report as a failure.
- Skill attribution: rows made while a skill is active carry `attributionSkill` (for example `mattpocock-skills:code-review`, 7 rows here). Skill calls are `tool_use` `name: "Skill"`, `input: {"skill":"orca-cli"}`.
- A subagent's own first user row is the `prompt` string; the SubagentStart hook adds `attachment` rows (`hook_additional_context`).
- One reviewer or verifier per round must be counted from `Agent` tool_use rows (`description`, `subagent_type`, `model`). `description` is free text written by the model; no structured "round" field exists.

---

## 3. Bash commands, results, ordering, background

### Records

Assistant row (one content block per row; a message with several parallel tool calls becomes several rows sharing `message.id`; 49 shared ids in this file):
```json
{"type":"assistant","timestamp":"2026-10-15T15:03:48.932Z","uuid":"0d9ae0e5-...","parentUuid":"...","message":{"model":"claude-opus-5-5","id":"msg_...","content":[{"type":"tool_use","id":"toolu_01J1A7...","name":"Bash","input":{"command":"...","description":"...","run_in_background":true}}]},"cwd":"~/.claude","sessionId":"2e56c352-...","version":"2.1.300"}
```
Result row (`type: "user"`, `message.content[0]` is the tool_result; `timestamp` is the result time):
```json
{"type":"user","timestamp":"2026-10-15T15:03:49.405Z","sourceToolAssistantUUID":"...","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_01J1A7...","content":"<stdout text>"}]},
 "toolUseResult":{"stdout":"...","stderr":"","interrupted":false,"isImage":false,"noOutputExpected":false},
 "permissionDecision":{"decision":"accept","source":"config","reasonType":"classifier"}}
```

| Fact | Where | Notes |
|---|---|---|
| Command text | assistant row `message.content[].input.command` | Raw as the model wrote it. A `wireToolInputs.<toolUseId>.command` on the row can hold the form actually run (prefixed `cd <cwd> &&`). |
| stdout / stderr | user row `toolUseResult.stdout`, `.stderr` | Split. `message.content[0].content` is the merged text. |
| Failure | `tool_result.is_error: true` and `content` starts `Exit code N\n...`; `toolUseResult` is then the string `"Error: Exit code N\n..."` | Example: `Exit code 2` for `ls` of missing files. |
| Success | no `is_error`; **no exit code field at all** | Exit 0 is only implied by absence of `is_error`. |
| Pipes mask | `cmd 2>&1 \| tail -4` returns tail's code | The audit cannot see the test runner's code through a pipe. |
| Large output | `content` becomes `<persisted-output>\nOutput too large (33.6KB). Full output saved to: .../<session>/tool-results/<id>.txt\n\nPreview (first 2KB): ...`; `toolUseResult.persistedOutputPath`, `.persistedOutputSize` | Seen in this run. Read the spill file for the full text. |
| Interrupt | `toolUseResult.interrupted` | |
| Denied | `tool_result.is_error`, `toolUseResult` string `Error: Permission for this action was denied by the Claude Code auto mode classifier...`, row field `toolDenialKind: "automode-blocked"`, `permissionDecision.decision: "reject"` | A denied call did not run. Count `permissionDecision.decision == "accept"` or no denial before treating a command as run. |
| Timestamps | assistant row `timestamp` (all 161 have one); user row `timestamp`; `system`/`turn_duration` rows have `durationMs`, `messageCount` | Tool duration = result timestamp minus call timestamp (here about 0.5 s). |
| Order vs Edit/Write | file order, backed by `parentUuid` chain and `timestamp` | Rows are append-only. `Edit` input: `file_path`, `old_string`, `new_string`, `replace_all`; result `toolUseResult` has `filePath`, `structuredPatch`. `Write` input: `file_path`, `content`. |
| Subagent Bash | same shapes in `subagents/agent-*.jsonl` | Sorting main + subagent rows needs `timestamp`, not file order. |

"Tests ran after the last edit" is computable: find the last `Edit`/`Write` tool_use whose result was not denied, then a later `Bash` tool_use matching a test command whose result has no `is_error`. Caveats: pipes (above), commands run by subagents (other file), edits made through Bash (`sed -i`, heredocs; auto-mode allows them), and `edited_text_file` attachments (the harness records edits the user made outside the session).

### Background commands

Start (`input.run_in_background: true`). Immediate result:
```json
"content":"Command running in background with ID: bntlfncq8. Output is being written to: /tmp/claude-1000/-home-<user>--claude/4e77a7b4-.../tasks/bntlfncq8.output. You will be notified when it completes ..."
"toolUseResult":{"stdout":"","stderr":"","interrupted":false,"backgroundTaskId":"bntlfncq8","backgroundCwdHint":"Session cwd remains ..."}
```
Completion appears twice in the parent file:
1. `{"type":"queue-operation","operation":"enqueue","content":"<task-notification>..."}`
2. a `user` row, `origin: {"kind":"task-notification","producer":"session-task","runId":"..."}`, `turnOrigin: "task_notification"`, `promptSource: "system"`, with the same text. Also seen as an `attachment` of type `queued_command` (`prompt` field).

```
<task-notification>
<task-id>bntlfncq8</task-id>
<tool-use-id>toolu_01CyY6u3...</tool-use-id>
<output-file>/tmp/claude-1000/.../tasks/bntlfncq8.output</output-file>
<status>completed</status>
<summary>Background command "Run the hook test file after the fix" completed (exit code 0)</summary>
</task-notification>
```
Join: `<tool-use-id>` = the Bash `tool_use.id`; `<task-id>` = `backgroundTaskId`.

Exit code lives only in the `<summary>` text. Over 8500 local notifications: `completed` 7710 (`completed (exit code 0)`), `failed` 751 (`failed with exit code 1`: 583, `exit code 144`: 46), `killed` 50 (`was stopped`, `was stopped because the system is running low on memory`). Parse with `status` plus `exit code (\d+)`; the summary embeds the model's own description in quotes, which can contain anything (one local summary contains extra quoted words), so anchor the regex on the end of the summary.

The stdout of a background command is only in `/tmp/claude-1000/<project>/<startup session id>/tasks/<task-id>.output`. That file is outside `~/.claude`, uses the stale startup id after `/clear`, and is cleared by the system. The transcript has no copy. A background test run therefore proves "ran, exit code N" but not its output.

A background command that is still running when the session ends has no notification row. That is "unknown", not "passed".

---

## 4. Worker transcripts from the coordinator

### Commands (read-only; run with `--json`; the CLI is `orca`, shim `orca-ide` also works)

| Command | Gives | Session id / transcript path? |
|---|---|---|
| `orca terminal show --terminal <handle> --json` | `terminal.handle`, `ptyId`, `worktreeId`, `worktreePath`, `branch`, `tabId`, `leafId`, `title`, `connected`, `agentIdentity`, `preview` | No. `tabId` + `leafId` build the pane key. |
| `orca terminal list --json` | same fields for 35 live terminals | No |
| `orca orchestration worker-show --dispatch <ctx_id> --json` | `dispatch` (`id`, `runId`, `taskId`, `assigneeHandle`, `status`, `dispatchedAt`, `completedAt`), `worker` (`state`, `agentTerminalHandle`, `startOptions.launch.requested.model`, `.effective.model`), `terminal` (as above), `projection`, `observation`, `terminalResource` | No |
| `orca orchestration worker-list [--run <id>] --json` | per worker: `dispatchId`, `taskId`, `runId`, `agentTerminalHandle`, `terminalState` | No |
| `orca orchestration worker-read --dispatch <id> --source transcript --limit N --json` | `result.transcript.messages[]` (`id`, `role`, `blocks[]`, `timestamp`, `parentId`), `sourceIdentity` (opaque), `cursor` | Content only. It is a normalised render, not the raw JSONL. No path. |
| `orca orchestration run-list`/`run-show`, `dispatch-show --task <id>` | run objective, coordinator handle, task | No |
| `orca worktree current/list/show` | worktree metadata | Not checked for session fields |

`worker-read` help: "The default auto source uses an exact hook-reported transcript when available and otherwise returns labeled terminal output." Orca therefore knows the transcript, but exposes only content. Its pages are bounded, with opaque cursors, and `source_changed` can invalidate them.

Observed `worker-show` for a live dispatch (redacted):
`dispatch.status: dispatched`, `dispatch.dispatchedAt: 2026-10-15 15:38:01` (UTC), `worker.startOptions.launch.effective.model: claude-sonnet-5-5`, `worker.startOptions.worktree: path:~/orca/workspaces/<other-repo>/<branch>`, `terminal.worktreePath` the same, `observation.exactWorker: true`.

### Route A: Orca hook status file (exact, undocumented)

`~/.config/orca/agent-hooks/last-status.json` (`version: 2`, keys `version`, `entries`, `authorityCommitments`). Each `entries["<tabId>:<leafId>"]` is the last hook event of that pane:
```json
{"paneKey":"a6aca96c-...:75f5a248-...","source":"claude","worktreeId":"<repoId>::~/orca/workspaces/<other-repo>/<branch>","hookEventName":"PostToolUse",
 "providerSession":{"key":"session_id","id":"4c1deee3-...","transcriptPath":"~/.claude/projects/-home-<user>-orca-workspaces-<other-repo>-<branch>/4c1deee3-....jsonl"},
 "agentPresence":{"agent":"claude","process":{"pid":2595925,...}},"toolAgentId":"a0185cc194d1ce2a6","receivedAt":1792078823198,...}
```
Chain: dispatch id -> `worker-show` -> `terminal.tabId` + `terminal.leafId` -> pane key -> `providerSession.id` and `.transcriptPath`. For this session, `ORCA_AGENT_PANE` (`89aef18e-...:08668045-...`) is the key, and its entry names `2e56c352-...` (the post-`/clear` id), so the file follows `/clear`. All 19 entries had an existing transcript file. Limits: it holds only live panes (19 entries against 35 listed terminals), so it can lose a worker after its terminal is released or Orca restarts; the format is Orca-internal and versioned (`version: 2`); entries are overwritten by each new hook event (a restarted claude in the same pane replaces the session).

### Route B: derive from the worktree path (no Orca internals)

1. `worktreePath` from `worker-show` or `terminal show` (or `worker.startOptions.worktree` with the `path:` prefix removed).
2. Project dir = encode(`worktreePath`) as in section 1, for example `-home-<user>-orca-workspaces-<other-repo>-<branch>`.
3. List `*.jsonl` there. A worktree can have several sessions (restarts, `/clear`, handoff successors, the Orca mailbox terminal). Select by time: first row `timestamp` >= `dispatch.dispatchedAt` (UTC). For the example, the dispatch was at 15:38:01 and the session's first user row at 15:38:09.
4. Confirm with content: the worker's first user row contains the Orca brief, which includes `--task-id task_... --dispatch-id ctx_...` (observed in `4c1deee3`'s first prompt). Match `--dispatch-id <ctx_id>` as a regex over rows with `type: "user"` and no `isMeta`.

Step 4 depends on Orca's brief wording. If the worker was started by a hook-launched successor, the first row is the successor prompt (see section 5).

The coordinator can also use the Orca terminal handle only via `terminal show` (above), since no transcript field exists on the handle.

Worker model: `worker-show` `worker.startOptions.launch.effective.model` (requested vs effective) is the launch config; the transcript's assistant `message.model` is the actual model. Compare both.

---

## 5. Missing, ambiguous, unstable data

1. Format versions. 33 Claude Code versions in the local data (2.1.260 to 2.1.300). New row types appear (`atis-latch`, `api-request`, `cost-state`, `frame-link`, `bridge-session`, ...). Field names differ by row (`session_id` stale vs `sessionId`). Parsers must ignore unknown types and key off `version`.
2. `/clear`. A new session id and a new file in the same process. The new file has no pointer to the old one: only the stale `session_id` field (startup id) on later rows, and the old file ends without a link record (`continued-in` appears once in 20k+ rows, in a different flow). The `/tmp/.../<startup id>/tasks/` dir keeps the startup id. The old and new sessions are joined only by that stale field, by `ORCA_PANE_KEY` history, or by time.
3. Compaction. 123 `system` rows with `subtype: "compact_boundary"` (`compactMetadata.trigger`, `preTokens`, `postTokens`, `preservedSegment`, `logicalParentUuid`); the summary row has `isCompactSummary: true`. A message "Compacted while idle, before the prompt cache expired" is a separate `informational` row. The file keeps appending; rows before the boundary stay in the file but are no longer in the model's context. The model's recall of earlier steps is gone, but the audit sees all rows. Linear `parentUuid` walks break at a boundary (`parentUuid: null`, `logicalParentUuid` set): use file order, not parent links.
4. Resume. `sessionId` always equals the file name (843 of 843), so a resume of the same session appends to the same file. Docs: "If you resume the same session in two terminals without forking, messages from both interleave into one transcript" (sessions.md). `/branch` and `--fork-session` create a new id. claude-directory.md lists `<session>.orphaned-<timestamp>-<suffix>.jsonl` and `<session>.jsonl.superseded-<timestamp>` as sets-aside copies: none exist locally, so this was not observed.
5. Context handoff successors. A new process, a new session id, a new file. The link is prose in the successor's first user message: `- predecessor session_id: <uuid>` and `- predecessor transcript_path: <path>` (seen in `2c32484e...`, predecessor `fbf7534b...`). These lines are written by the predecessor model into a handoff file. The hook text allows `unknown`. Treat as ambiguous. A task audit across a handoff must follow the chain of these lines and concatenate files; nothing in JSON links them.
6. Lazy writes. Hook docs: the transcript "may lag the in-memory conversation" and "the transcript file isn't guaranteed to include the final message at Stop time on all versions". Observed: the subagent file was within about 1 s of the running agent (mtime 12:42:57 vs last row 15:42:57Z), and the parent file within about 70 s at the time of the check. A post-task audit should run after the session stops (`SessionEnd`) or use `last_assistant_message`.
7. Retention. `cleanupPeriodDays` default 30 (settings-reference.md: "Default: `30`"). The sweep deletes the transcript and its `subagents/` and `tool-results/` dirs. `/tmp/claude-1000/...` background output and scratchpad are cleared by the OS. An old task cannot be audited after 30 days.
8. Spilled outputs. Big tool output is stored in `<session>/tool-results/<id>.txt`; the transcript has only a 2KB preview. Test result text beyond the preview needs the spill file.
9. No exit code on success (section 3). Piped commands hide the real code.
10. Task identity. There is no structured "task", "round" or "phase" field. Rounds must be inferred from `Agent` calls (`description` text, order) and ledger files. `description` is model-written free text.
11. Model fallback. `system`/`model_fallback` rows (`originalModel`, `fallbackModel`, 4 local rows) mean the model changed mid-session. Read `message.model` per row, not the first one.
12. `meta.model` vs actual (section 2): `inherit` and `null` exist; use `message.model` in the subagent file.
13. Cost and model totals. `cost-state` rows (`modelUsage` keyed by model id, `totalCostUSD`, 1745 local rows) give a per-model usage summary for a session. Whether subagent usage is included was not checked.
14. Orca routes are undocumented. `last-status.json` (route A) and the dispatch-id text in the brief (route B step 4) can change without notice.
15. Permission mode. Rows carry `permissionMode` (`auto`) and tool results carry `permissionDecision`. Auto-mode denials need `toolDenialKind`. A denied call must not count as a run.
16. Secrets. Docs: "that value is written to `projects/<project>/<session>.jsonl`" (claude-directory.md, "Transcripts and history are not encrypted at rest"). The audit script must not print raw rows.

---

## Summary table

| Fact | Source path / field | Reliability |
|---|---|---|
| Own session id (Bash) | env `CLAUDE_CODE_SESSION_ID` (documented, follows `/clear`) | reliable |
| Own session id (subagent's Bash) | same env; gives the parent's id, no agent id | ambiguous |
| Own transcript path (hook) | stdin `transcript_path`, `session_id` | reliable (file may lag) |
| Own transcript path (Bash) | `~/.claude/projects/*/$CLAUDE_CODE_SESSION_ID.jsonl` (glob) | reliable |
| Project dir name | cwd with `[^A-Za-z0-9]` to `-` (841/842 match) | reliable forward; cannot decode; start cwd, not current cwd |
| Session id inside the file | row `sessionId` (= file name, 843/843) | reliable |
| Stale session id after `/clear` | row `session_id`, `/tmp/.../<id>/tasks/` | ambiguous (do not use) |
| Subagent transcript | `<session>/subagents/agent-<agentId>.jsonl` | reliable |
| Subagent description, type | `agent-<id>.meta.json` `description`, `agentType`; parent `Agent` input `description`, `subagent_type` | reliable |
| Subagent model requested | `.meta.json` `model` (`sonnet`, `inherit`, null), `Agent` input `model` | ambiguous (request only) |
| Subagent model actually used | subagent file `assistant` rows `message.model`; parent `toolUseResult.resolvedModel` | reliable |
| Link Agent call to file | `tool_use.id` = `meta.toolUseId`; `toolUseResult.agentId` = file name | reliable |
| Subagent final report | last row `SubagentHandback.input.message`; parent `origin.handbackReportText`; hook `last_assistant_message` | reliable; absent if the agent died |
| Subagent status | task-notification `<status>`, `<usage>` | reliable |
| Review round number | none; infer from `Agent` descriptions and order | missing |
| Bash command | assistant `tool_use.input.command` | reliable |
| Bash success / failure | `tool_result.is_error` and `Exit code N` prefix in `content` | reliable for non-zero; exit 0 only implied |
| Bash exit code on success | not recorded | missing |
| Bash output | `toolUseResult.stdout/stderr`; spill file for large output | reliable; large output needs `tool-results/` file |
| Real test exit code through a pipe | not recorded (`\| tail` masks) | ambiguous |
| Denied call | `toolDenialKind`, `permissionDecision.decision` | reliable |
| Time of call and result | assistant and user row `timestamp` (ISO UTC) | reliable |
| Order of Edit / Write vs Bash | file order, `parentUuid`; timestamps across files | reliable in one file; use timestamps across subagent files |
| Edits made through Bash | only visible in command text | ambiguous |
| Background start | `toolUseResult.backgroundTaskId`, `run_in_background` | reliable |
| Background exit code | task-notification `<summary>... (exit code N)` / `failed with exit code N`, `<status>` | reliable if the notification exists |
| Background output | `/tmp/claude-1000/.../tasks/<id>.output` | ambiguous (outside `~/.claude`, temporary) |
| Background command unfinished at session end | no notification row | missing |
| Skill used | `tool_use` `Skill` `input.skill`; `attributionSkill` | reliable |
| Worker terminal to worktree | `orca terminal show` `worktreePath`, `tabId`, `leafId` | reliable |
| Worker session id / transcript path (Orca) | `~/.config/orca/agent-hooks/last-status.json` `entries["tabId:leafId"].providerSession` | ambiguous (internal; live panes only) |
| Worker transcript path (derived) | encode(`worktreePath`) dir + pick by `dispatchedAt` + dispatch-id text in first prompt | ambiguous |
| Worker transcript content via Orca | `orca orchestration worker-read --source transcript` | reliable for content, no path, normalised |
| Worker launch model | `worker-show` `worker.startOptions.launch.effective.model` | reliable (launch config) |
| Handoff predecessor | prose `predecessor session_id/transcript_path` in first user row | ambiguous |
| `/clear` predecessor | none in JSON | missing |
| Compaction | `system` `compact_boundary`, `compactMetadata` | reliable |
| Model change mid-session | `system` `model_fallback`, per-row `message.model` | reliable |
| Commits | not in transcripts as structured data (only Bash text); use `git log` | missing |
| Transcript completeness at hook time | hooks.md: may lag | ambiguous |
| Retention | `cleanupPeriodDays` default 30 | reliable limit |
| Format stability | docs: internal, changes between versions | ambiguous |

## Open gaps

- Foreground (synchronous) `Agent` results were not seen; all 1101 local launches are `async_launched`. The final-report shape for them is unknown.
- Whether `last-status.json` keeps an entry after a worker terminal is released (`worker-release`) or after Orca restarts was not tested (it needs a destructive action).
- `orca worktree current/show` JSON was not inspected for session fields.
- Whether `cost-state.modelUsage` includes subagent usage was not checked.
- Frequency of Bash edits (`sed -i`, heredoc) that bypass `Edit`/`Write` was not measured.
- Fork (`/branch`, `--fork-session`) and `.orphaned` / `.superseded` files were not observed locally; their link fields are unknown.
- The `Exit code` prefix was checked for plain failures only; it was not checked for timeouts, kills and sandbox denials.
- `SubagentStop` / `Stop` stdin was taken from the docs; no live hook payload dump was made (writing a hook was out of scope).
- Truncation of project dir names over 200 characters was not tested.
