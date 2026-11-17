# Orca features for an inbox and central coordinators

Ticket 753, map 752 (request 750). Date of reading: 2026-11-17. Orca app version read: 1.4.261 (`orca status --json`, field `appVersion`). Marks: **FACT** = read in a source named on the line. **INFERENCE** = our reading, not tested. **UNTESTED** = a command that would change state was not run, by the rules of this task. This file makes no decision for the owner.

Neutral labels are used for the owner's setup: "a work group of about 20 repos", "a second product group of 4 repos", "a personal group of 8 repos".

## 1. Question

What does Orca offer today that an inbox and a central coordinator per project group can use? Covered: Runs and their binding, ask/reply, escalations, `check` and wait commands, automations, broadcasts, terminal read and send, worktree comments, notifications, and cross-Run or cross-repo messaging. Also covered: the Claude Code features that help (`SendMessage`/`ListAgents`, `Monitor`, push notifications, scheduled wakeups). Last: what an inbox needs that neither offers.

## 2. Short answer

1. Orca already has a durable mailbox per Run, and one coordinator session can hold several Runs and be woken by mail from all of them (section 3.1, 3.2).
2. `orchestration inbox` with no filter lists every mailbox on the local Orca, so one read-only view over all Runs exists (3.3).
3. Workers and coordinators can ask, escalate and report. A decision gate blocks a task until the coordinator resolves it (3.4, 3.5).
4. A watcher can use `check --peek --wait` without taking mail. This gives a safe "new mail" signal for Claude Code `Monitor` (3.3, 5). UNTESTED.
5. Orca notifies a person with a bell, a sound, an unread dot and phone push. Phone push is a capability of this install (3.7).
6. A folder workspace can hold several Git repos, so one central session can sit above the repos of one group (3.9).
7. Cross-Run send by `run:<id>` is described in the CLI notes. Whether a worker of one Run can mail the coordinator of another Run was not tested (3.6).
8. Gaps: no owner-facing queue that ranks "needs the owner" across Runs, no priority filter on `check`, no answer path from the phone to a gate, and wake needs a live agent session (section 6).

## 3. Findings

### 3.1 Runs and binding

- FACT: "A Run is a namespace and home inbox. It never schedules or places workers." (`orca agent-context --json`, note of `orchestration run-create`.)
- FACT: `run-create --objective <text>` creates and binds a Run to the calling coordinator. `run-use --id <run_id>` resumes coordinating a Run. `run-current`, `run-list`, `run-show` read Runs. (`orca agent-context --json`, usage lines.)
- FACT: "A later `run-create` keeps your earlier Runs: their mail still wakes you, but commands without `--run` use the newest Run, so pass `--run <id>` for an earlier one. `run-use` keeps only the Run it names." (bundled guide: `orca skills get orchestration --reference references/coordinator-loop.md`.)
- FACT: "A worker cannot bind its own or ancestor Run" (note of `run-use`, `orca agent-context --json`). The runtime lists a capability `orchestration.retained-run-bindings.v1` (`orca status --json`).
- FACT: the public docs call orchestration experimental: "Settings → Experimental" (https://orca.dev/docs/cli/orchestration, read through a fetch subagent).
- INFERENCE: one central session can bind one Run per project group, or one Run per effort, and still receive all mail.

### 3.2 Messages, types, wake and `check`

- FACT: valid `send --type` values: "status, dispatch, worker_done, merge_ready, escalation, handoff, decision_gate, question, heartbeat" (note of `orchestration send`, `orca agent-context --json`).
- FACT: priority values are `normal`, `high`, `urgent` (message schema in the installed server bundle `orcad-server.js`; `send --priority <level>` is in the usage line).
- FACT: `send` options include `--to <run:id|dispatch:id|legacy_handle>`, `--thread-id`, `--payload <json>`, `--task-id`, `--dispatch-id`, `--phase` (usage line).
- FACT: default `check` "return[s] the bound Run's oldest unread FIFO batch and mark[s] it handled". `--peek` returns unread mail without marking it. `--all` returns recent mail and does not mark. `--wait` blocks until a matching message arrives or `--timeout-ms` ends; `--types` is the wake condition for `--wait` (help text and notes of `orchestration check`).
- FACT: "A script that only watches the inbox must use --peek (including --peek --wait) and must never --ack, or it takes mail the agent never sees." (note of `check`.)
- FACT: wake text for an idle agent: "You have new orchestration messages. Read them with the `check` command above, then continue." (string in `orcad-server.js`). In this session a mid-turn notice read "You have 1 orchestration message. Run `orca orchestration check`." (observed).
- FACT: the bundled guide says: "Poll or run watch scripts: a script's plain `check` takes your mail" and "Orca wakes you" (`orca skills get orchestration`, section Never).
- FACT: `--wait` timeout: 1 to 1,800,000 ms, default 600,000 ms (note of `ask`). A federated message cannot exceed 64 KiB (error text in `orcad-server.js`).

### 3.3 Reading mail across Runs

- FACT: `orchestration inbox [--limit] [--terminal] [--run] [--full]`. "Without --terminal or --run it lists every mailbox on this Orca. --run <run_id> keeps all mail in that Run, including mail to its workers; --terminal run:<run_id> keeps only the coordinator mailbox." Rows preview each body in 200 characters. (notes of `inbox`.)
- FACT: `check --all` returns recent messages for the handle and `--format` renders them as local text (notes of `check`).
- FACT: "To find mail after losing context, run orca orchestration inbox --terminal <mailbox> --limit <n> --full and name the mailbox: run:<run_id> ... or dispatch:<dispatch_id>" (note of `check`).
- INFERENCE: `inbox` is the closest thing to a cross-Run inbox that Orca has today. It lists mail; it does not rank it, filter it by priority or tell what the owner must answer. `inbox` was not run (rule of this task: no orchestration command except the preamble commands).
- FACT: the whole database is local SQLite: `orchestration.db` in Orca's config folder (file seen in the config folder listing). Tables seen in the bundle include `messages`, `runs`, `dispatch_contexts`, `tasks`. This is state of one Orca on one machine.

### 3.4 Ask, reply, escalation

- FACT: `ask (--question <text> | --resume <message_id>) [--to <run:id>] [--run] [--options <csv>] [--wait] [--timeout-ms]`. "From a worker, a new question goes to its coordinator and ask returns at once: end your turn, and Orca wakes you with the answer as mail." (usage and note of `ask`.)
- FACT: the answer path is `reply --id <msg_id> --body <text>`. "A reply to mail from an agent on another server goes back to that server by itself" (usage and note of `reply`).
- FACT: an `escalation` message with `stopReason` means a worker stopped without `worker_done`. Coordinator options: steer with `send`, stop and retry, or tell the user. "`exited` or `lost` means it is gone" (bundled guide `orca skills get orchestration`, section When Orca wakes you).
- FACT: capability `orchestration.worker-turn-stop-reports.v1` exists (`orca status --json`).
- FACT: `ask --to <run:id>` takes a Run address, so a question can target a Run's coordinator mailbox (usage line).

### 3.5 Decision gates

- FACT: `gate-create --task <id> --question <text> [--options <json_array>]`, `gate-resolve --id <gate_id> --resolution <text>`, `gate-list [--task] [--status] [--run]` (usage lines).
- FACT: "a coordinator-owned question that blocks a task until it is resolved" (https://orca.dev/docs/cli/orchestration, fetch subagent).
- INFERENCE: a gate is a typed, listable "waiting for a decision" record. `gate-list --status pending` over all Runs could be one source for an owner queue. Not run.

### 3.6 Cross-Run, cross-repo and cross-server messaging

- FACT: "Group addresses (@all, @idle, @codex, ...) reach the live Dispatches of your own Run; a sender in no Run must use run:<id> or dispatch:<id>. @worktree:<id> names one workspace." (note of `send`.)
- FACT: "Run groups exclude their owning coordinator; send to run:<id> to raise something with yours. Nested coordinators receive group mail in their child Run mailbox; @worktree:<id> includes workspace coordinators." (note of `send`.)
- FACT: `worker_done` and `heartbeat` "are exact-Dispatch signals and cannot target groups" (note of `send`).
- FACT: address checks in the server bundle give two refusal codes: `recipient_ambiguous` (one name maps to several mailboxes) and `recipient_run_mismatch` ("belongs to Run X, not explicitly requested Run Y") (`orcad-server.js`).
- FACT: `send --on <server>` mails an agent on a paired Orca server (`--to term_…` or `orca_session_id:…`). Replies arrive in your own `check`. "`--environment <server>` runs one command on that server and delivers no mail" (note of `send`; bundled guide `references/placement-and-remote.md`).
- FACT: capabilities `orchestration.peer-mail.v1` and `orchestration.federation.v1` exist (`orca status --json`).
- UNTESTED: a worker in Run A mailing `run:<B>` was not run. INFERENCE from the note above: a sender may address any `run:<id>`, but the server may refuse by ownership; only a test shows it.
- FACT: no command in `orca --help` is named for messages across repos. Groups reach one Run or one workspace, not one repo group.
- FACT: the public docs name no cross-Run or cross-repo messaging ("no explicit statement", fetch subagent report of https://orca.dev/docs/cli/orchestration).

### 3.7 Notifications, unread marks, phone

- FACT: "When an agent transitions from working to idle, Orca fires a notification — system notification, sound, and a chip on the worktree." "The header bell shows unread notifications across all worktrees." (https://orca.dev/docs/notifications, fetch subagent.)
- FACT: `worktree set --worktree <sel> --unread` puts the unread dot on a workspace "to ask for a person's attention"; `--read` clears it (bundled guide `orca skills get orca-cli`, section Worktree Comments).
- FACT: capabilities `notifications.remote-push.v1`, `notifications.desktop-presence.v1`, `mobile.tasks.v1` exist on this install (`orca status --json`).
- FACT: "Get push notifications when an agent finishes, mirroring desktop notifications." The phone has an Agents tab across connected desktops. Mobile is in beta. Pairing uses a one-time code and an optional relay. (https://orca.dev/docs/mobile, fetch subagent.)
- FACT: notification categories and sounds are set in Settings → Notifications (same notifications page).
- INFERENCE: the push triggers are agent-state changes (working to idle). No page read says that a `question`, `escalation` or gate message alone pushes to the phone. A coordinator that asks the owner is idle at a prompt, so the idle push is the likely path. Not tested.

### 3.8 Worktree comments, card status, terminal read and send

- FACT: a worktree comment is "the short status line on the workspace card": `worktree set --worktree active --comment "<text>"`. Card status: `--workspace-status <id>`, defaults `todo`, `in-progress`, `in-review`, `completed` (bundled guide `orca-cli`).
- FACT: `worktree ps [--agent-wait] --json` lists workspaces with `comment`, `unread`, `status`, `agents[]` (with `state`) and parent and child links (output of `orca worktree ps --json`, fields only; values not copied here).
- FACT: `terminal read [--screen] [--cursor]`, `terminal send --text … --enter [--wait-submit <s>]`, `terminal wait --for tui-idle|exit --timeout-ms`. "`accepted: true` proves input acceptance, not a started turn." (bundled guide `orca-cli`, section Terminals.)
- FACT: "Use `terminal send` only for direct terminal input or one-off prompts where no task state, inbox, or reply tracking is needed." (same guide.)
- FACT: `orca search "<phrase>"` searches indexed agent sessions, but only where a human enabled Agent Session History in settings; "There is no CLI way to turn it on." (same guide, section Agent Session Search.)
- FACT: `orca reference find <url-or-key>` finds workspaces and agents by an issue or review link and returns `terminal` handles or `mailbox` addresses (`dispatch:<id>`, `run:<id>`) (bundled guide `orca-cli`, section Review and issue references).
- INFERENCE: comment + status + unread on the workspace card give a cheap human-visible state for a central session, with no new tool.

### 3.9 Repos, folder workspaces and groups of repos

- FACT: `repo add --path <abs> --kind folder` adds "an ordinary directory or a parent of separate Git repositories; worktrees attached to a folder workspace appear in its Source Control panel, one section each." (bundled guide `orca-cli`.)
- FACT: "A worktree created with `--repo` from a folder workspace ... is attached to that folder workspace" and `worktree create` can name a parent in another project (same host) (same guide, section Worktrees and Lineage rules).
- FACT: `@worktree:<id>` "includes workspace coordinators" (note of `send`), so a folder workspace can be the address of a central session.
- FACT: `new-child` from a multi-repo folder workspace "needs `--repo` naming the Git repo to create the worktree in" (bundled guide `references/placement-and-remote.md`).
- INFERENCE: one folder workspace per project group is a place for one central session. A work group of about 20 repos, a product group of 4 repos and a personal group of 8 repos would be three folder workspaces. Orca has no named "group" object; the folder workspace plays that role. No test was run.
- FACT: `project list`, `project setups` exist for "durable projects" across hosts (`orca --help`). Their group semantics were not read.

### 3.10 Automations

- FACT: `automations create --name --trigger hourly|daily|weekdays|weekly|<cron>|<RRULE> --prompt --provider claude|codex|… (--repo <sel> | --workspace <sel>) [--reuse-session] [--precheck <cmd>] [--precheck-timeout <s>]` (bundled guide `references/automations.md`).
- FACT: the guide's own example is "Inbox digest" with `--trigger hourly --prompt "Summarize unread mail" --provider codex --workspace active --reuse-session` (same file).
- FACT: "Use `--precheck <command>` to run a shell command only before scheduled runs. Exit code 0 continues; any other exit ... skips the run." Skips are recorded as `skipped_precheck`. "Run now ... bypass[es] the precheck." (same file.)
- FACT: `--reuse-session` is only for existing-workspace automations; "if the previous terminal is gone, Orca falls back to a fresh session." (same file.)
- FACT: on this install `automations list` returned no automations (`orca automations list --json`).
- INFERENCE: an automation with a precheck that tests for unread mail (for example a `check --peek` count) could wake a central session on a schedule without paying for an agent run when nothing waits. This was not tested. It runs only while Orca is open (INFERENCE; the app owns the scheduler).

### 3.11 Broadcasts

- FACT: no `broadcast` command exists in `orca --help` (full help read).
- FACT: group send exists inside orchestration: `send --to @all|@idle|@claude|@codex|@worktree:<id>` for the live Dispatches of one Run (note of `send`; groups list in https://orca.dev/docs/cli/orchestration, fetch subagent).
- GAP: a desktop feature that sends one message to many agents may exist in the app UI. No CLI command and no source line for it was found, so it is not claimed.

### 3.12 Workers and nesting

- FACT: workers may start helper workers; default depth 4 (https://orca.dev/docs/cli/orchestration, "Nested worker depth", fetch subagent). "Stopping a worker also stops its helpers." (same.)
- FACT: `worker-start` has `--on <saved-environment>` for a paired server, `--keep-open`, `--run`, `--retry-of`. Finished workers close on their own unless kept open. (usage and notes of `worker-start`.)
- FACT: the old `coordinator-start` and `coordinator-stop` are "Retired: load the current orchestration skill" (`orca --help`).
- FACT: "Not every worker has a terminal. Read output with worker-read --source auto or --source transcript" (note of `worker-start`).

### 3.13 Claude Code features that help

All facts below are the tool descriptions loaded in this session.

- `SendMessage` + `ListAgents`: cross-session messages between agents and local Claude sessions. "messages enqueue and drain at the receiver's next tool round"; `notify_when_idle: true` gives one notice when a local session goes idle; a session in another permission mode "holds cross-session messages for its user's approval". It is session-to-session, with no durable inbox and no Run.
- `Monitor`: a background script whose stdout lines become chat notifications; timeout at most 30 minutes (re-arm on expiry); use `grep --line-buffered`; "silence is not success". It can run `orca orchestration check --peek --wait --types …` as the watch command (INFERENCE, UNTESTED; the `--peek` rule is in 3.2). Poll loops are allowed inside Monitor; the CLAUDE.md "no polling" rule must allow this case, which is the owner's choice.
- `PushNotification`: desktop notification, and a phone push only when Remote Control is connected. It skips when the user is at the terminal. The tool text says to err toward not sending.
- `ScheduleWakeup`: only in `/loop` dynamic mode; delay clamped to 60 to 3600 seconds.
- `CronCreate`: session-only, fires only while the REPL is idle, recurring jobs expire after 7 days.
- `RemoteTrigger`: calls the claude.ai routines API (cloud runs). A cloud routine cannot read local Orca state (INFERENCE).
- `SendToProject`: works only in a turn where the user ran `/send-to-project`; not usable by an agent on its own.
- Hook `asyncRewake` (settings schema in the Orca bundle copy of Claude Code settings): a background hook "wakes the model on exit code 2". INFERENCE: a hook could wake an idle session, but only inside a running turn cycle; not tested.

## 4. How the pieces fit (INFERENCE)

1. One central session per group sits in a folder workspace of that group and binds one Run per effort.
2. Every group coordinator mails the central Run with `send --to run:<id> --type question|escalation|merge_ready`. UNTESTED across Runs.
3. The central session reads `inbox` (all mailboxes) and `gate-list`, then asks the owner with one batch.
4. Orca's bell, unread dot and phone push reach the owner. The central session sets `--unread` on its own workspace when the owner must act.

## 5. Options for the owner

Each option states what it costs. The owner decides in the decision tickets.

- **A. One central coordinator Run per group, children as workers.** Uses Runs, `ask` and gates as designed. Cost: the group coordinators of today are main sessions, not workers; they must become workers or Run owners with `send --to run:<id>`; the mail flow across Runs needs a test first. Cheapest on new code.
- **B. Central session reads `orchestration inbox` plus `gate-list` on wake.** No new tool. Cost: every wake costs a model turn; `inbox` shows 200-character previews and no ranking, so the central session ranks by itself.
- **C. `Monitor` on `check --peek --wait` for the central session.** Wakes the session on new mail without taking it. Cost: a Monitor expires after at most 30 minutes and must be re-armed; the Monitor script is a watch loop, which the bundled guide discourages and CLAUDE.md section 12 forbids as a filler loop (a blocking wait is allowed there, so this form likely fits). UNTESTED.
- **D. Automation with a precheck.** Scheduled, cheap when the inbox is empty, survives a closed session. Cost: only while Orca runs; reuse-session falls back to a fresh session if the terminal is gone; one more state to audit.
- **E. Use `SendMessage` between local sessions for the central link.** No Orca change. Cost: no durable mailbox, no Run, messages wait for the receiver's next tool round, and a session in another permission mode holds them for approval; it does not fit the audit trail of the Orca mailbox.
- **F. Folder workspace per group as the address of the central session.** Gives `@worktree:<id>` addressing and one card per group. Cost: the folder-workspace behavior with 20 repos was not tested (lineage, card, source-control view).
- **G. Cap and merge delegation by `reply`.** The owner already allows delegating merges and cap extensions to coordinators (map note). A coordinator answers a worker `ask` with `reply`. Cost: the audit hook text must accept an answer from a coordinator as the owner's words; that is a CLAUDE.md change, outside this research.

## 6. Gaps and open questions

What an inbox needs that neither Orca nor Claude Code offers today:

1. **Owner queue.** No view lists only "waiting for the owner" across Runs, ranked, with the answer path. `inbox` lists all mail; `gate-list --status` lists gates; nothing joins them.
2. **Priority filter.** Messages carry `normal|high|urgent`, but the `check` flags show only a `--types` filter (usage line). No flag filters by priority.
3. **Answer from the phone.** The phone gets an Agents tab and push. No page read says the owner can answer an `ask` or resolve a gate from the phone. `gate-resolve` is a CLI command for a coordinator.
4. **Live session needed.** Wake works for a live agent. If the central session is closed, mail waits in SQLite and nothing answers. Resume needs `run-use` from a new session. Whether a coordinator can run outside an Orca terminal was not checked here.
5. **Cross-Run send rules.** Not tested: worker to foreign Run, coordinator to coordinator, `@worktree:<id>` into another repo. The refusal codes in 3.6 suggest ownership checks.
6. **Scale.** No source says how many Runs or messages one `inbox` call handles well. A work group of about 20 repos may produce many Runs.
7. **Experimental status.** Orchestration is under "Settings → Experimental" in the public docs; the CLI contract may change (capability `orchestration.contract.v1` exists).
8. **Machine bound.** Mail lives in one local database. Several PCs would need `--on` federation. The owner said a local setup is fine (map note).
9. **Public docs page not read:** /docs/activity ("Agents feed"), /docs/cli/reference and /docs/settings. The "Agents feed" may add an inbox-like view. Not claimed.
10. **No test of notifications on `question` messages.** See 3.7.
11. **Prior research.** `docs/research/agent-workflow-comparison.md` (issue 723) gives no Orca facts; its proposals P1, P2 and P8 (rulings, one batch of questions, workers only for independent tickets) change how many mails reach the owner. This file does not judge them; that is a later ticket.

## 7. Sources read and sources that failed

**Read, local (read-only):**
- `orca --help` (full), `orca agent-context --json` (335 commands; usage, flags and notes of every `orchestration` command), `orca status --json`, `orca worktree ps --json` (fields only), `orca automations list --json`.
- Bundled guides: `orca skills get orchestration` and its references `coordinator-loop`, `messaging-and-gates`, `placement-and-remote`, `recovery-and-cleanup`, `low-level-topology`; `orca skills get orca-cli` and its reference `automations`.
- The installed app bundle: strings and schemas in the server file `orcad-server.js` and the CLI bundle `out/cli/index.js` (searched for message types, group addressing, priority values, wake text, refusal codes, capability names). The main app archive was opened read-only and its `out/` files were searched; the code is minified, so only short strings were used as evidence.

**Read, public (through a fetch subagent on model Sonnet, which returns summaries; quotes can differ slightly from the page):**
- https://github.com/stablyai/orca (MIT license, per the README), https://orca.dev/docs/cli/orchestration, https://orca.dev/docs/cli/automations, https://orca.dev/docs/mobile, https://orca.dev/docs/notifications, and the directory listing https://github.com/stablyai/orca/tree/main/src/main/runtime. The orchestration source is public at `src/main/runtime/orchestration` in that repository; its files were not opened.

**Failed or not read:**
- https://onorca.dev answered a redirect (307) to orca.dev; the docs host is orca.dev.
- Not read: /docs/activity, /docs/cli/reference, /docs/settings, and the files in the public orchestration source folder.
- Not run, by the rules of this task: `orchestration inbox`, `gate-list`, `run-list`, any `send` across Runs, any command that changes state. Section 3.3 to 3.6 claims about their output are therefore INFERENCE or UNTESTED where marked.
- A first search of the minified bundle with a wide regular expression timed out and was moved to the background; later searches used fixed strings.
- One command with the text of a `worker-start` help request was blocked by a local hook, so worker-start usage was read from `agent-context` instead.
