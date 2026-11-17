# Inbox interface: forms compared

Ticket 775, map 752 (request 750). Date of reading: 2026-11-17. Orca app version read: 1.4.261 (see `docs/research/orca-inbox-orca.md`). Claude Code build read: the mod types of the installed build (version 2.1.326 per the bundled skill folder).

Marks: **FACT** = read in a source named on the line. **INFERENCE** = our reading. **UNTESTED** = a command or feature that would change state or start a process; none was run, by the rules of this task. This file decides nothing for the owner.

Neutral labels are used for the owner's setup: "a work group of about 20 repos", "a second product group of 4 repos", "a personal group of 8 repos". Prior files are cited as `orca` (`orca-inbox-orca.md`, ticket 753), `oss` (`orca-inbox-oss.md`, 754) and `load` (`orca-inbox-load.md`, 755).

## Question

Which form should the inbox interface take? The inbox lists the project groups, their sessions and the open questions, and lets the owner answer from one place. Four forms are compared: a local web page, a terminal user interface (TUI), a view inside Orca, and a Claude Code mod with a side panel. For each form: how it reads state, how the owner answers, notifications, resource cost, build and upkeep effort, and open-source projects that do most of it.

## Short answer

1. FACT: all four forms read the same data, and none needs new storage. Orca keeps all mail in one local database and exposes it through `orca orchestration inbox`, `gate-list` and `worktree ps` (`orca` 3.3, 3.5, 3.8).
2. FACT: Orca has its own plugin system with sidebar panels written in TSX or HTML. This is the "view inside Orca" form, and it is native (F1).
3. FACT: an Orca plugin panel is sandboxed and has no network. Its host API has no orchestration method (no inbox, no reply, no gate). A plugin can read workspace status, agent state and unread marks, notify, and type into terminals (F2).
4. INFERENCE, UNTESTED: a plugin worker is an out-of-process Node module, so it may run the `orca` CLI and so reach the mailbox and `reply`. This is the one unknown that decides whether the Orca view can answer questions itself (F3).
5. FACT: a Claude Code mod can run commands with `$.process.run` (CLI only) and draw a pane. A pane shows only inside one session, and only from 144 terminal columns unless asked (F5).
6. FACT: Textual (Python) can serve one TUI app in a terminal or in a browser with `textual serve`. This makes the TUI and web forms one code base (F6).
7. FACT: no open-source project found covers the owner's case as a ready tool. Novadeck, Hermes IDE and cmux Feed are design references; their licences limit code reuse (`oss` 3.1, 3.5).
8. INFERENCE: notifications are the weakest point of every form. Orca push is tied to agent state changes, and the phone has no answer path (`orca` 3.7, §6 item 3). A web page or a TUI needs an extra sender such as ntfy.
9. INFERENCE: an answer written from any UI must reach the section 6 audit as the owner's own words. The audit checks `AskUserQuestion` answers today (gap G1).
10. Options O1 to O6 are below, with costs.

## Findings

### F1. Orca plugin system exists and has a panel surface

- FACT: `orca plugin --help` lists `create`, `dev watch`, `install`, `open`, `shot`, `check` and more (command output).
- FACT: the bundled guide `orca skills get orca-plugin-authoring` lists "A sidebar panel of lists, forms, buttons, status" (`sandboxed-ui`, TSX with `"ui": "components"`), "A panel backed by its own Node code, storage or settings" (`trusted-worker`, template `worker-panel`) and "Reacting to workspace or agent status changes" (`trusted-worker`, events).
- FACT: the guide says "No build step": `.ts` and `.tsx` load as written; panels import only `orca` and relative files; `ORCA plugin dev watch --check --shot` reloads on save and writes a PNG of the panel.
- FACT: code-running plugins need user approval (`approval_required`, exit 3). Content-only plugins load without it.
- FACT: the guide says "Sidebar cards, task sources, connections, MCP servers and skills are reserved and not buildable yet".
- FACT: a public catalog of plugins exists (`stablyai/orca-plugins`): themes, `sqlite-browser`, `http`, `spreadsheet`, `orca-runner` and others. No inbox or agent-mail plugin is in the list (GitHub API listing of `plugins/`, 2026-11-17).
- FACT: Orca is MIT licensed, 127,636 stars, pushed 2026-11-17 (GitHub API).
- INFERENCE: the plugin API is new (needs engines.orca at least 1.4.246) and changes by minor version; upkeep follows Orca releases.

### F2. What a plugin can read and do (host API 1.10)

All from `orca skills get orca-plugin-authoring --reference references/host-api.md`.

- FACT, read: `workspace.list` (every workspace and project, `includeStatus` gives `state` working, permission, done, active or inactive, plus `unread` and `terminalCount`); `agents.list` (state working, blocked, waiting or done, and the dispatched task title); `project.list`; `terminal.list`; `terminal.read` (newest 2000 lines); `agent.listSessions` (titles, token counts; never the conversation).
- FACT, events: `agent.status.changed`, `workspace.created`, `workspace.removed`, `workspace.changed`. A panel needs no manifest entry for them.
- FACT, act: `terminal.sendText` with `enter`, `terminal.focus`, `workspace.open`, `agent.launch`, `agent.resume`, `automation.create`, `notifications.show`, `statusBar.update`.
- FACT: a panel cannot type into a terminal; only a worker with `terminal:send` can (guide). A panel reaches its worker with `plugin.request`.
- FACT: there is no host method for orchestration mail. The method list has no `inbox`, `check`, `reply`, `ask` or `gate`.
- FACT: `workspace.list` states "on every host Orca reaches", so one panel can show all three project groups when they are Orca projects.
- INFERENCE: with only the host API, a panel is a status board plus "jump to terminal" plus "type an answer into the coordinator's terminal". It does not read the mailbox.

### F3. The worker could close the gap (UNTESTED)

- FACT: a `trusted-worker` `main` is a Node module run in an "out-of-process plugin worker"; "Bare imports resolve as Node does" (guide, manifest reference). `plugin test` and `plugin check` are described as "unsandboxed: only for code you trust" (`orca plugin --help`).
- FACT: the manifest capability list has no "run a command" capability (host-api capabilities list).
- INFERENCE, UNTESTED: a worker may use Node `child_process` to run `orca orchestration inbox --json`, `gate-list` and `reply`. This was not tested, and the consent screen may show it. If it works, one plugin holds the whole inbox inside Orca. If it fails, the Orca-view form needs a small local helper process next to it (the web or TUI form), or only shows status.
- FACT: a worker with `main` and status bar items is kept running while enabled, "so a worker can poll and update its items without an event or a hook" (`statusBar.update`). INFERENCE: this gives an always-visible "N waiting" count in the Orca status bar with no model turns.

### F4. Local web page

- FACT: Orca has a built-in browser tab scoped to a worktree, driven by `orca browser` commands and by the `orca-cli` guide; the guide says to use it for local pages. So a local web page can be shown inside Orca with no plugin (`orca skills get orca-cli`, section Built-In Browser).
- FACT: `orca serve` starts a headless Orca runtime server with `--port` and `--bind`; `--allow-public` and `--refuse-public` exist (`orca serve --help`). INFERENCE: this is Orca's own server, not a place to host a custom page.
- FACT: the mobile app is in beta and has an Agents tab and push (`orca` 3.7). INFERENCE: a web page reached over a private network address could be the phone answer path that Orca lacks; this needs a bind address choice and an access rule. UNTESTED.
- FACT: `orca artifacts share` publishes an HTML or Markdown file "with your Orca account" (command list). Not read further. INFERENCE: this is a hosted share, not a live local view; do not use it for private mail.
- INFERENCE: reading is by a small local server that runs the CLI and returns JSON. Answering is one POST that runs `reply` or `gate-resolve`. Live updates by server-sent events or a short refresh.
- INFERENCE: no new data store is needed. The page is a view.

### F5. Claude Code mod with a side panel

All facts from the plugin-authoring skill and its types file for this build.

- FACT: a mod is TSX loaded by the session; a pane opens with `$.ui.open({ id })` and is drawn by a `ui.render` hook. "Seats from 144 columns, or 110 as `$.ui.open`'s doc says, and waits below that" (types, `UiOpenResult`).
- FACT: `$.process.run(argv)` runs a command on the host and returns `{ exitCode, stdout, stderr }` (timeout 30 s default, 10 min at most); `$.process.spawn` streams output. Marked "CLI only".
- FACT: the mod also has `$.clock` (timers), `$.ui.toast`, `$.ui.status`, `$.audio.play`, `$.command.register` and prompt hooks (skill table).
- FACT: a mod lives in a session. `$.state` is per session and `$.store` persists across sessions; a reload restarts module variables (skill text).
- FACT: hot reload needs the person's answer to "Turn on the mods Claude writes in this session?" in most permission modes (skill text).
- FACT: the skill says the mod can answer a prompt: `prompt.submit` rewrite and `command.run` return text.
- INFERENCE: a mod pane in the central session reads the mailbox with `$.process.run(["orca","orchestration","inbox",...])` on a timer and answers by the same command. It shows only in that one terminal, beside the central session. It does not show in other sessions or on the phone.
- INFERENCE: a timer inside the session means polling in a model-free hook. The CLAUDE.md "no polling" rule (section 12) is about filler commands in the model's turns. Whether a mod timer breaks it is the owner's call.
- INFERENCE: it works only while that Claude Code session is open, in a terminal at least 110 or 144 columns wide. Orca terminal panes may be narrower; not measured.
- UNTESTED: the mod was not built or loaded, by the rules of this task.

### F6. Terminal user interface

- FACT: Textual (Python): MIT, 37,678 stars, pushed 2026-11-09. README: "Run your apps in the terminal or a web browser", and "Any Textual app may be served with `textual serve`" (GitHub API; README).
- FACT: Bubble Tea (Go, MIT, 45,756 stars, pushed 2026-11-12), Ink (TypeScript with React, MIT, 40,293 stars, pushed 2026-11-13) and Ratatui (Rust, MIT, 23,339 stars, pushed 2026-11-17) are the other mature TUI libraries (GitHub API). README text of the last three was not read.
- FACT: cmux has `cmux feed tui` for its Feed, and shows items in a sidebar and in desktop notifications with inline actions (`oss` 3.1). cmux is GPL and macOS only.
- INFERENCE: a TUI reads and answers like the web page: it runs the CLI and shows rows. It can run in an Orca terminal tab, in a tmux pane, or over SSH. It costs one process while open and nothing when closed.
- INFERENCE: a TUI has no built-in push. Notification comes from Orca's idle alert on the coordinator terminal, from `notifications.show` of a plugin, or from a sender such as ntfy (`oss` 3.4).

### F7. Notifications, by form

- FACT: Orca notifies on agent working-to-idle with a system notification, sound, chip and bell; `worktree set --unread` puts a dot; phone push mirrors desktop notifications (`orca` 3.7).
- FACT: a plugin can call `notifications.show` and `statusBar.update`, and can listen for `agent.status.changed` (F2). `agents.list` has the state `blocked` and `waiting`.
- INFERENCE: the Orca plugin is the one form with a native desktop alert, a status-bar count and an unread dot, without a sender. It does not reach the phone, because push mirrors Orca's own events (`orca` 3.7, UNTESTED for plugin alerts).
- FACT: ntfy (Apache-2.0, 35,613 stars) sends a push to a phone from any script; claude-ntfy-hook and Lucarne add Approve and Deny buttons (`oss` 3.4). INFERENCE: this is the usual add-on for the web, TUI and mod forms.
- FACT: Claude Code `Notification` hook types include `permission_prompt`, `idle_prompt`, `agent_needs_input` (`oss` 3.3). A mod can also use `$.ui.toast` and `$.audio.play` (F5).

### F8. Resource cost

No process was started here, so these are design facts, not measurements.

- FACT: Orca already runs. A components panel needs no extra OS process; a worker is one out-of-process Node module, kept running only if it has status bar items (F3). INFERENCE: the cheapest form on process count.
- FACT: the mod runs inside a Claude Code session that the central coordinator already needs (`$.process.run` on a timer, no model call). INFERENCE: no extra process besides the short `orca` child.
- INFERENCE: a TUI is one process while open. A web page is one long-running server plus a browser tab. Both run a CLI call per refresh; the `inbox` result is local SQLite (`orca` 3.3), so each call is small. Scale of `inbox` with many Runs is unknown (`orca` §6 item 6).
- FACT: `load` F6 counted 1,496 notices and 1,422 asks in 38 days. INFERENCE: that is about 40 asks per day, so one refresh every few seconds is far above the data rate; a 15 to 30 second refresh or an event trigger would do.
- UNTESTED: memory of each form was not measured. The owner asked for lower PC use; a measurement task could follow.

### F9. The answer path and the audit

- FACT: answers go through `orca orchestration reply --id <msg_id> --body <text>` and `gate-resolve --id <gate_id> --resolution <text>` (`orca` 3.4, 3.5).
- FACT: `AskUserQuestion` answers are the source the audit checks for cap `extension` and `size-approval` events (CLAUDE.md section 6, ledger text: "S5 checks that the quote is in an AskUserQuestion answer").
- INFERENCE: an answer typed in a web page, TUI or panel is not an `AskUserQuestion` answer. For a decision that needs the owner's own words, the central session must still ask with `AskUserQuestion` itself, or the audit rule must accept a recorded answer from the inbox. This is a rule change outside this research (also `orca` option G).
- FACT: Squadra records "the exact words to answer" and a recommendation (`oss` 3.5); `decision --owner-words` is its verb. INFERENCE: a design to copy for the record.
- UNTESTED: whether `reply` works from a process that is not the coordinator of that Run.

### F10. What each form reads

| Need | Web page | TUI | Orca plugin | Claude Code mod |
|---|---|---|---|---|
| Mailbox (`inbox`, `gate-list`) | CLI by a local server | CLI | worker CLI (UNTESTED); not in host API | `$.process.run` |
| Sessions and states | `worktree ps --json` | same | host API `workspace.list`, `agents.list` (native) | CLI |
| Transcripts | files, if allowed | files | not given by the API (`agent.listSessions` gives titles only) | files |
| Answer | `reply` by POST | `reply` | worker `reply` (UNTESTED), or type into terminal | `$.process.run` |
| Where it shows | any browser, even Orca's tab | any terminal | Orca desktop sidebar | one session's terminal |
| Phone | possible by private network (UNTESTED) | over SSH | Orca mobile unknown for plugins | no |

INFERENCE for the table; rows 2 and 3 of the plugin column are FACT (F2).

## Existing tools and what they cover

The "do not reinvent the wheel" check, by need.

| Need | Existing thing | Covers | Does not cover |
|---|---|---|---|
| Mail store, ask, reply, gates | Orca orchestration (`orca` 3) | all data and the answer commands | a view that ranks "needs the owner" (`orca` §6 item 1) |
| Sessions, states, unread | Orca `worktree ps`, `agents.list`, `workspace.list` | list and status of every workspace | the question text |
| Native desktop panel | Orca plugin panel | draws inside Orca, hot reload, shots, tests | reading the mailbox from the host API |
| Status count | Orca `statusBar.update` | an always-visible item | detail view |
| Alerts | Orca bell, sound, unread dot, mobile push | on idle | a push for a mailbox item (INFERENCE) |
| Alerts, phone | ntfy; Lucarne; Channels permission relay (`oss` 3.4) | push with buttons | mapping to Orca replies |
| TUI toolkit | Textual, Bubble Tea, Ink, Ratatui (F6) | widgets, tables, input | domain logic |
| One code base for TUI and web | Textual `textual serve` | same app in a browser | access control, phone use |
| Inbox UX designs | cmux Feed, Novadeck, Hermes IDE, Squadra (`oss` 3.1, 3.5) | patterns | code reuse (GPL, GPL, BSL; Squadra MIT but a different data model) |
| Side panel in a session | Claude Code mod (F5) | pane, timer, process call | other sessions, phone |
| Chat bridge from a session | Claude Code Channels (`oss` 3.1) | forward prompts to a chat | Orca mail |

INFERENCE: nothing found is a finished inbox for the Orca mailbox. The missing piece is a thin view and a ranking rule, not a data layer.

## Options for the owner

Costs are INFERENCE unless marked. The options are not exclusive. No ranking is given.

- **O1. Orca plugin, status only.** A components panel plus a status-bar count from `agents.list` and `workspace.list` (all host API facts). Shows which sessions are blocked, waiting or unread across the three groups, and jumps to the terminal. Cost: no mailbox text; the owner answers in the session terminal. Lowest build effort and no extra process. Depends on a stable plugin API (Orca 1.4.x).
- **O2. Orca plugin with a worker that runs the CLI.** O1 plus `inbox`, `gate-list` and `reply` through the worker (F3). Cost: depends on an UNTESTED fact; needs the owner's approval of a code-running plugin; a spike of about one task would test it. Gives native alerts, status count and answers in one place, and no web server.
- **O3. Local web page in Orca's built-in browser tab.** A small local server runs the CLI and serves a page; Orca shows it. Cost: one long-running process and a port; a page to write and keep; access control if it is reachable from the phone. Works outside Orca too and can serve the phone through a private network.
- **O4. TUI built with Textual, also served to a browser.** One code base for terminal and web (`textual serve`). Cost: Python and Textual as new dependencies; `textual serve` on a phone is UNTESTED; push still needs ntfy.
- **O5. Claude Code mod pane in the central session.** `$.process.run` on a timer, a pane beside the central session. Cost: only in that terminal and at the width floor; reload rules; the timer and the no-polling rule need the owner's reading; no phone.
- **O6. Mix by job.** For example: O1 or O2 as the desktop view, ntfy as the phone push, and the answer by the coordinator through `AskUserQuestion`. Cost: two or three small parts to keep and test; clear split of roles.

## Gaps and open questions

- G1. Audit: an answer from an inbox UI is not an `AskUserQuestion` answer (F9). The owner must say how the audit records the owner's words for cap and size decisions.
- G2. UNTESTED: whether a plugin worker may run the `orca` CLI (F3). One small spike answers it.
- G3. UNTESTED: whether `reply` and `gate-resolve` work from a process that is not the Run's coordinator (also `orca` §6 item 5).
- G4. Not read: the plugin reference files `components.md`, `recipes.md` in full, and the public `orca-plugins` sources; so panel limits (rows, refresh, size) are unknown.
- G5. Not measured: memory and CPU of every form. Numbers here are design facts.
- G6. Not known: whether Orca mobile shows a plugin panel; `orca` 3.7 says only that the phone has an Agents tab.
- G7. Not read: Novadeck, Hermes IDE and cmux source for how they get their items; only READMEs (`oss`).
- G8. Whether `inbox` previews of 200 characters suffice for a ranked list, or `--full` per item is needed (`orca` 3.3).
- G9. The owner's rule on a mod or server timer and the "no polling" rule (CLAUDE.md section 12) was not decided.
- G10. Ranking rule ("what needs the owner first") is not decided here; Gas Town severity and Hermes "waited longest" are the designs seen (`oss` 3.2, 3.5).

## Sources read and sources that failed

Read, local (read-only):
- `orca --help`, `orca plugin --help`, `orca serve --help`, `orca artifacts --help`, `orca browser --help`, `orca skills list`.
- Bundled guides: `orca skills get orca-plugin-authoring` (main guide, `references/host-api.md`, `references/events.md`, grep of `references/manifest.md` and `references/recipes.md`); grep of `orca skills get orca-cli` for the built-in browser.
- The Claude Code plugin-authoring skill and its types file (`UiOpenResult`, `$.ui.open`, `$.process`).
- Prior research: `docs/research/orca-inbox-orca.md`, `orca-inbox-oss.md`, `orca-inbox-load.md`.
- `orca plugin list --json` (first lines only: installed plugins are themes; no inbox plugin).

Read, public:
- GitHub API metadata for `Textualize/textual`, `charmbracelet/bubbletea`, `vadimdemedes/ink`, `ratatui/ratatui`, `stablyai/orca`; the Textual README (web serving lines); the directory listing of `stablyai/orca-plugins/plugins`.

Failed or not done:
- A loop over several `gh api` calls was denied by the read-only hook (a gh subcommand built by a variable); the calls were rerun one by one.
- Bubble Tea, Ink and Ratatui READMEs were not read; only API metadata.
- No process, plugin, mod or server was started; no CLI call that changes state ran (`inbox` and `gate-list` were not run either).
- The public Orca docs pages (activity, plugins) were not fetched; plugin facts come from the guides bundled with the installed CLI.
