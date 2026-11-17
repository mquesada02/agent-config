# Sessions without a terminal UI, keeping the harness

Ticket 779, map 752 (request 750). Date of reading: 2026-11-17. Claude Code version read: 2.1.326 (`claude --version`). Orca version read: 1.4.261. Marks: **FACT** = read in a named source. **INFERENCE** = our reading. **UNTESTED** = a command that would start a session or change state was not run, by the rules of this task. This file makes no decision for the owner.

Neutral labels: "a work group of about 20 repos", "a second product group of 4 repos", "a personal group of 8 repos". "TUI" means terminal user interface. "SDK" means the Claude Agent SDK. "Harness" means hooks, permissions, skills, memory, `CLAUDE.md` and the audit.

## Question

Can coordinators or workers run without a terminal UI and keep the harness? Compare headless Claude Code (`claude -p`, stream-JSON), the SDK, and Orca terminals. For each: what it saves, what it breaks or changes, how the owner still sees and answers questions, and the cost to switch. The prior research gives the load (`orca-inbox-load.md`), the Orca features (`orca-inbox-orca.md`) and the restart failures (`orca-inbox-reliab.md`). This file does not repeat them.

## Short answer

1. FACT: Claude Code has four ways to run without the TUI: `claude -p` (one run), `claude -p` with stream-JSON on stdin and stdout (a long run with a host program), the SDK (a library that runs the same binary), and background sessions (`claude --bg`, run by a supervisor process).
2. FACT: `-p` and the SDK load the same user, project and local settings, hooks, skills, `CLAUDE.md` and auto memory as the TUI. Only `--bare` skips them. The harness is kept by default.
3. FACT: Orca already runs Claude without a terminal. Its "Chat UI" starts Claude through the bundled SDK with all three setting sources. A worker can have no terminal; `worker-read --source transcript` reads it.
4. FACT: a headless run has no one to answer a prompt. `AskUserQuestion` is removed or denied unless a host answers it. A host is an SDK `canUseTool` callback, a `--permission-prompt-tool`, or an Orca chat card.
5. FACT: auto mode works in `-p` runs, but repeated classifier blocks do not stop for a prompt. The action is dropped and the run goes on.
6. FACT: the context-handoff hook starts a successor with Orca terminal commands. Its own text says headless runs are skipped (`CLAUDE_CODE_SESSION_ATTENDED=0`) and auto-compact is the backstop. So a headless coordinator or worker has no handoff.
7. INFERENCE: removing the TUI saves terminal rendering, one pseudo-terminal and one open tab per session. It does not save model tokens: the context, the tools and the hooks are the same. No measurement exists; we ran none.
8. FACT: `claude --bg` runs sessions with no terminal open. The owner can list, read, reply and attach. A permission dialog needs an attach. It is a research preview.
9. GAP: no source says whether the audit reads a headless transcript the same way, or whether an Orca mailbox wake works for a headless coordinator. Both need a test.
10. INFERENCE: Orca's own chat surface for workers keeps the harness and needs no new code. It changes where the owner answers.

## Findings

### F1. `claude -p` keeps the harness unless `--bare` is set

- FACT: "Without `--bare`, `claude -p` discovers and loads them as an interactive session would, including anything configured in the working directory or `~/.claude`." Hooks, skills, custom commands, subagents, plugins, MCP servers, auto memory and `CLAUDE.md` are in that list. (https://code.claude.com/docs/en/headless, "Start faster with bare mode".)
- FACT: `--bare` skips hooks, LSP, plugin sync, attribution, auto memory, background prefetches, keychain reads and `CLAUDE.md` discovery. It reads no OAuth login: auth is `ANTHROPIC_API_KEY` or `apiKeyHelper`. (`claude --help`, option `--bare`; same docs page.) INFERENCE: `--bare` breaks the harness and the subscription login, so no workflow session can use it.
- FACT: user-invoked skills work in `-p`: "Include `/skill-name` in the prompt string and Claude Code expands it before running." Built-in terminal-only commands such as `/login` are not available. (same page, "Create a commit".)
- FACT: a `-p` run shows no workspace trust dialog and no per-server approval prompt. (same page.) INFERENCE: a project hook runs without the trust step, so a worktree that the session did not check can run its hooks.
- FACT: `--no-session-persistence` stops the session from being saved; "they can't be resumed (only works with --print)". The default saves it. (`claude --help`.)
- FACT: `--continue` and `--resume <id>` resume a `-p` session. `--resume` also takes the path of a `.jsonl` transcript file. (headless page, "Continue conversations".)
- FACT: after the model turn ends and stdin is closed, a `-p` run stays open for background commands, subagents, Monitor watches and `/loop` wakeups; a 10-minute idle cap applies (`CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS`). `--bare` turns background tasks off. (same page, "Background tasks at exit".)
- FACT: SIGTERM ends a run with exit code 143 and leaves the turn unfinished; `SessionEnd` hooks still run. `CLAUDE_CODE_RESUME_INTERRUPTED_TURN=1` continues an interrupted turn on resume. (same page, "Stop a run with SIGTERM".)

### F2. Stream-JSON: a long-lived headless session with a host

- FACT: `--input-format stream-json` gives "realtime streaming input"; `--output-format stream-json` gives newline-delimited events; `--include-hook-events` adds hook lifecycle events; `--replay-user-messages` echoes input; `--include-partial-messages` adds token chunks; `--forward-subagent-text` adds subagent text. (`claude --help`.)
- FACT: `system/init` is the first event; it lists the model, tools, MCP servers, loaded plugins and a `capabilities` array. (headless page, "Read session metadata".)
- FACT: `--permission-prompts <host|none>` says who answers prompts. With `none`, "anything that would prompt is denied automatically". With a host, the run waits for the host. `--permission-prompt-tool` names an MCP tool as the host. (`claude --help`; headless page, "Turn off permission prompts in unattended runs".)
- FACT: with `--permission-prompts none`, "Claude Code removes the tools that need an answer from a person, such as `AskUserQuestion`". Without a host, `AskUserQuestion` is "denied even when an allow rule matches" in `dontAsk` mode. (headless page.)
- FACT: since v2.1.302, a `-p` or SDK run with no permission mode set starts in Manual mode; a call that needs approval is denied unless an allow rule, a hook, `canUseTool` or `--permission-prompt-tool` approves it. (https://code.claude.com/docs/en/permission-modes.) INFERENCE: a headless worker must pass `--permission-mode auto` as the TUI sessions of this setup do (the local `settings.json` sets `defaultMode` to auto; a `-p` run reads it as a setting, which this file did not test).
- FACT: the cost of a run is reported: `--output-format json` has `total_cost_usd` and a per-model split; `--max-budget-usd` caps a `-p` run. The figures are "client-side estimates". (headless page; `claude --help`.)

### F3. Auto mode in headless runs

- FACT: auto mode is available on all plans for the models Sonnet 4.6 and later, Opus 4.6 and later, Haiku 5.5 and Fable. `-p --permission-mode auto` works; the classifier reviews each action. (https://code.claude.com/docs/en/permission-modes, "Auto mode in `-p` (headless) runs".)
- FACT: "A non-interactive `-p` run without a `--permission-prompt-tool` has no prompt to fall back to. When repeated blocks reach a threshold, the action doesn't run and Claude keeps working. Claude Code doesn't stop the run." The thresholds are 3 in a row or 20 in total. (same page.)
- FACT: if the server gives no safety verdict, Claude Code denies the action in `-p` runs. (same page.)
- FACT: in this setup's own sessions a hook changed a Bash call after review and the classifier returned no verdict (seen in this task's first Bash calls; the error text says to retry the same input). INFERENCE: a headless run would turn that no-verdict case into a plain denial, with no retry step.
- INFERENCE: the setup's rule "stop and ask the owner" for cap extensions, failed audits and merges has no TUI to stop at. A headless session needs an explicit ask path (F7).

### F4. The SDK loads the harness by default, and adds callbacks

- FACT: "When you omit `settingSources`, `query()` reads the same filesystem settings as the Claude Code CLI: user, project, and local settings, CLAUDE.md files, and `.claude/` skills, agents, and commands." (https://code.claude.com/docs/en/agent-sdk/claude-code-features.)
- FACT: filesystem hooks from `settings.json` run beside programmatic hooks; both fire in subagents; callback input carries `agent_id` and `agent_type`. TypeScript adds `SessionStart`, `SessionEnd`, `TeammateIdle` and `TaskCompleted`. (same page.)
- FACT: auto memory loads regardless of `settingSources`. The agent writes memories with `Write` and `Edit`, so those tools must be on. (same page, "What settingSources does not control".)
- FACT: the SDK "runs the Claude Code binary" (https://code.claude.com/docs/en/agent-sdk/overview). It is a library over `claude -p` with stream-JSON. INFERENCE: its token use per model call is the same as the TUI for the same context.
- FACT: skills must be files; "the SDK does not have a programmatic API for registering skills". (claude-code-features page.)
- FACT: agent teams are "a CLI feature"; they are "not directly configured via SDK options". (same page, "Choose the right feature".)
- FACT: `canUseTool` fires for a tool that needs approval and for `AskUserQuestion`. "The callback can stay pending indefinitely"; for a long wait a `PreToolUse` hook can return a `defer` decision so the process exits and resumes later from the saved session. `AskUserQuestion` is "not currently available in subagents". (https://code.claude.com/docs/en/agent-sdk/user-input.)
- FACT: a `PermissionRequest` hook can send a notification (Slack, email, push) when Claude waits for approval. (same page.) INFERENCE: this is a native hook point for the inbox: the host or a hook can write the question to the owner's inbox.
- FACT: SDK terms: "Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or rate limits" for their products; the SDK page tells builders to use API-key auth. (agent-sdk/overview.) UNTESTED: whether the owner's own local use with a subscription login is allowed for an SDK program is not stated on the page read. Ask Anthropic or read the usage terms before any switch. The Orca bundle (F5) sets the `claude_code` entry point and runs the installed CLI; see F5 for what that implies.

### F5. Orca already runs Claude without a terminal

- FACT: `orca agent launch --agent <id> [--surface chat|terminal]` starts "as a chat or a terminal per your settings". `worker-start` follows "the user's own setting for new agent tabs; there is no flag for it". (`orca agent launch --help`; `orca orchestration worker-start --help`.)
- FACT: "Not every worker has a terminal. Read output with worker-read --source auto or --source transcript, which always work; --source terminal is refused when there is none, and orca terminal verbs do not accept every worker handle." The orchestration verbs "cover all of them". (`orca orchestration worker-start --help`, Notes.)
- FACT: Orca Chat UI lists Claude among the agents with a structured chat. It launches the agent "with the Command and Arguments saved for that agent". It renders `AskUserQuestion` as a question card; the owner answers through the composer and Submit; this also works on a paired or headless host. State is kept in Orca, so a chat tab can be restored after an app restart. (https://orca.dev/docs/agents/native-chat, read through a fetch tool that summarizes.)
- FACT: the installed Orca server bundle contains the Claude Agent SDK launcher: default options `settingSources: ["user","project","local"]`, `systemPrompt: {type:"preset",preset:"claude_code"}`, `includePartialMessages`, `supportedDialogKinds: []`, and an environment that sets `CLAUDE_CODE_ENTRYPOINT` to `sdk-ts`. A second function builds `-p --input-format stream-json --output-format stream-json --verbose` arguments. (the bundle file `orcad-server.js` of the installed Orca; minified, short strings only.)
- INFERENCE: an Orca chat worker is a Claude SDK or stream-JSON process. It loads the user and project hooks, `CLAUDE.md`, skills and memory by the SDK default (F4). So a chat worker keeps the harness. UNTESTED: whether the hooks of this setup (audit, branch, readonly, context) behave the same there, and whether the transcript file lands in the same place.
- FACT: Orca's own status hooks are separate: `orca agent hooks status|on|off` manages them; "Claude's `CLAUDE.md` and Codex's `AGENTS.md`... are left alone". (`orca agent hooks --help`; https://orca.dev/docs/agents/hooks-memory.)
- FACT: `orca serve` starts "an Orca runtime server without opening a desktop window"; `--supervise` is for service managers; the default runtime keeps terminals in a daemon. Chat works "on a paired Remote Orca Server or headless host". (`orca serve --help`; native-chat page.) INFERENCE: a central session on a headless Orca host is possible; the local PC only needs to be on (map note).
- FACT: Orca mailbox and `check`, `ask`, `reply`, `send --to run:<id>` work "identically" for every worker kind (worker-start notes quoted above). UNTESTED for a headless coordinator: `check --wait` and the wake text need a live agent session (`orca-inbox-orca.md` section 6, item 4).

### F6. Background sessions: `claude --bg`

- FACT: `claude --bg "<prompt>"` starts a session "straight to the background"; `claude agents` lists them (`--json` for scripts); `attach`, `logs`, `stop`, `respawn`, `rm` manage them. `--bg` cannot combine with `-p`. (`claude --help`; https://code.claude.com/docs/en/agent-view.)
- FACT: "Background sessions don't need any terminal open to keep working. A separate supervisor process runs them." The supervisor restarts a process that exits unexpectedly, stops finished or waiting sessions that nobody attached for about an hour (the conversation stays on disk and resumes on attach or reply), and survives sleep. Pinning keeps a process running. Shutdown stops running sessions; waiting ones stay under "Needs input". (agent-view page.)
- FACT: a background session reads settings from its working directory "the same as if you had started `claude` there". Hooks are not described in general. The `Notification` hook fires with `agent_needs_input` or `agent_completed`. (agent-view page.) INFERENCE: it is a normal Claude Code process, so the harness loads; not tested.
- FACT: the owner peeks at a waiting session, types a reply, or presses a choice number. "Permission prompts and other dialogs aren't answered by a reply... To answer the dialog, attach." (agent-view page.) INFERENCE: with auto mode on, few permission dialogs reach the owner; a question card still does.
- FACT: each session "uses your subscription quota independently". Row summaries come from a Haiku-class model, billed as a short request. (agent-view page.) INFERENCE: this adds small non-Sonnet calls outside the workflow roles; the map rule says no audited workflow step uses a non-Sonnet model. These summaries are not a workflow step, but the owner should confirm.
- FACT: state lives in a jobs folder under the Claude config folder; the page warns it "isn't a stable interface"; use `claude agents --json`. The feature is a research preview and has `disableAgentView`. (agent-view page.)
- UNTESTED: how a `--bg` session cooperates with an Orca Run, mailbox or worktree. Orca does not start it; the Orca `ORCA_*` environment and the mailbox handle are not set for it.

### F7. What the TUI gives that headless loses

- FACT: the context-handoff hook skips a run when `CLAUDE_CODE_SESSION_ATTENDED` is `0`, and when the hook input has an `agent_id`. The environment name is "an undocumented variable" in the hook's own comment. (hook source, first lines and the early return in `main`.) The handoff launcher uses `terminal create`, `terminal wait` and `terminal send` and the handle from `ORCA_TERMINAL_HANDLE`. (its launch tests.) CLAUDE.md section 11 says: "Headless sessions are covered too. The hook skips them; auto-compact is their backstop."
- INFERENCE: a headless coordinator or worker never hands off at 40 percent of the context window. It runs until auto-compact. `--autocompact <auto|tokens>` sets the window (`claude --help`). The owner's rule "context is never a reason to stop" is met by this path, but the handoff note (a successor with a clean context) is lost.
- FACT: the audit's session start hook records a `transcript_path` for each session, and the audit reads those transcripts; its tests carry the Claude Code version they cover (2.1.301; local Claude Code is 2.1.326, and the auditor brief says untested versions give a warning only). (workflow-audit support file and auditor brief.) UNTESTED: a `-p` or SDK session writes the same `.jsonl` transcript with the same record shapes. INFERENCE: it should, since the SDK runs the same binary. A test on a scratch folder is needed before any switch.
- FACT: the audit's test rule S2 counts the exact declared test command run after the last edit, and an auto-backgrounded call can pass with empty output (`orca-inbox-tests.md` F1, F4). In a `-p` run, a command that reaches its timeout "stops instead of moving to the background" only under `--bare`; otherwise the cut-off to the background applies, and `-p` "can exit with code 0 before the command finishes" for a subagent command. (headless page, "Give a long subagent command more time".) INFERENCE: headless adds a second path to the same false-pass risk (issue 729). It also gives the fix: `BASH_DEFAULT_TIMEOUT_MS`.
- FACT: `!` commands are typed by the owner in the TUI. The audit says a test the owner runs with `!` does not count for S2, and the owner runs `! gh pr merge` and `! gh pr create` 786 times (`orca-inbox-load.md` F5). A headless session has no `!` prompt. INFERENCE: the owner would run these in their own shell. The sessions need no change, but "give the owner the command" must still reach the owner (the inbox).
- FACT: the owner's answers today are 3,363 `AskUserQuestion` replies, 88 percent the recommended option (`orca-inbox-load.md` F3). In a headless session that tool needs a host (F2, F4).

### F8. What the TUI costs (the saving)

- FACT: local `ps` at reading time: 30 interactive `claude` processes, average resident memory about 412 MB each, about 12 GB in total on a PC with 31 GB. Seven of the largest sit near 460 to 600 MB. (command: `ps -eo rss=,args=` over processes named `claude`; counts only.)
- UNTESTED: how much of that 412 MB is the terminal UI. No source states it, and we started no headless session to compare. INFERENCE: the Node process, the context and the tool state remain in a headless run. The saving is a fraction of that number, plus the Orca terminal and its pseudo-terminal.
- FACT: the TUI render and Orca's terminal view cost CPU only while they draw. The idle CPU of the 30 processes is 1 to 6 percent each at reading time. (same `ps` command.) INFERENCE: the idle load is small; the test and review runs dominate (`orca-inbox-load.md`, F2 of tests).
- INFERENCE: tokens are the same. The model sees the same system prompt, `CLAUDE.md`, memory, skills list and tool results. `--exclude-dynamic-system-prompt-sections` improves prompt-cache reuse across users (`claude --help`); it is not a headless saving.

## Existing tools and what they cover (the "do not reinvent the wheel" check)

| Need | Existing tool | Covers it? |
|---|---|---|
| Run Claude with no TUI | `claude -p`, stream-JSON, SDK, `claude --bg` (F1, F2, F4, F6) | Yes, the run itself |
| Keep hooks, skills, `CLAUDE.md`, memory | Default `-p` and SDK loading (F1, F4) | Yes, unless `--bare` or `settingSources: []` |
| Worker with no terminal, with mailbox, transcript, restart | Orca Chat UI worker (F5) | Yes for workers; `worker-read --source transcript` reads it |
| Owner answers `AskUserQuestion` outside the TUI | Orca question card (F5); SDK `canUseTool` (F4); `claude --bg` peek and reply (F6) | Yes, in three different places |
| Owner is told that a session waits | `PermissionRequest` and `Notification` hooks (F4, F6); Orca bell and push (`orca-inbox-orca.md` 3.7) | Partly; no ranked list across Runs |
| A headless host as a long-lived process | `orca serve --supervise` (F5); the `claude --bg` supervisor (F6) | Yes, for the process |
| Handoff for a headless session | None; auto-compact only (F7) | No |
| Audit evidence from a headless transcript | None tested | Unknown (F7) |
| Wake a headless coordinator on Orca mail | None tested; `Monitor` with `check --peek --wait` is a candidate (`orca-inbox-orca.md` 3.13) | Unknown |

### Open-source projects (search on 2026-11-17)

Sources: the GitHub API and each README. Where a README is silent on hooks, the cell says INFERENCE. No source code was read.

| Project | License | Last release or activity | How it runs the agent | Hooks and settings | How a human answers |
|---|---|---|---|---|---|
| CloudCLI UI (https://github.com/siteboon/claudecodeui) | AGPL-3.0 | v1.37.9, 2026-11-16 | Web and mobile UI over Claude Code. INFERENCE: through the SDK or the CLI. | FACT (README): uses the same MCP servers, permissions, settings and sessions as Claude Code. INFERENCE: hooks load too. | Browser or phone UI; FACT (README): manages sessions remotely. |
| claude-code-webui (https://github.com/sugyan/claude-code-webui) | MIT | 0.1.56, 2025-09-18; last push 2026-05-29 | FACT (README): needs the Claude CLI; streams chat from a local backend. | INFERENCE: the local CLI loads the settings. The README does not say. | FACT (README): permission dialogs on desktop and mobile. |
| Happy (https://github.com/slopus/happy) | MIT | CLI beta 2026-10-09; last push 2026-11-17 | FACT (README): the CLI "wraps the Claude Code and Codex harnesses", with a relay server and a mobile app. | INFERENCE: it wraps the real harness, so hooks stay. The README does not say. | FACT (README): phone app with push notifications. |
| opcode (https://github.com/winfunc/opcode) | AGPL-3.0 | v0.2.0, 2025-08-31; last push 2026-11-06 | FACT (README): desktop GUI that runs background agents. INFERENCE: it starts the CLI. | FACT (README): per-agent file and network permissions. Hooks: not stated. | Desktop GUI. |
| Claude Squad (https://github.com/smtg-ai/claude-squad) | AGPL-3.0 | v1.0.20, 2026-08-20; last push 2026-11-13 | FACT (README): one tmux session per agent (a pseudo-terminal approach). | INFERENCE: the full terminal UI runs, so hooks and settings load. | FACT (README): terminal UI that switches between sessions. |
| Claude Agent SDK for Python (https://github.com/anthropics/claude-agent-sdk-python) | MIT | v0.2.183, 2026-11-16 | SDK that drives Claude Code from code. INFERENCE: it starts the CLI as a subprocess. | INFERENCE: it can load project settings and hooks (see F-section on `settingSources`). | The host code answers, through permission callbacks. INFERENCE. |

- FACT: three web or mobile front ends (CloudCLI UI, claude-code-webui, Happy) let a human approve tools from a phone or a browser.
- INFERENCE: none of these projects routes questions from many workers into one shared inbox. Each is a per-session UI.
- INFERENCE: the READMEs rarely say whether hooks load. A source or docs check is needed before the spec relies on any of them.

## Options for the owner

Each option has its cost. They are not exclusive. This file makes no ranking.

- **O1. Workers in Orca Chat UI, coordinators stay in terminals.** Set the Chat setting for Claude, or pass `--surface chat` to `agent launch`. Workers keep the harness through the SDK default; their asks and transcripts work as for all workers. Cost: the owner answers worker questions in a chat tab or through the coordinator, not in a terminal; the handoff hook and the `terminal send` recovery steps do not apply to a worker with no terminal (the reliability research assumed terminals: `orca-inbox-reliab.md`); the hooks, the audit transcript and S2 need one test run in a scratch folder first. Smallest code change: none for the harness.
- **O2. Coordinators and workers as `claude --bg` sessions.** Cost: no Orca Run, mailbox or worktree link is created by it (UNTESTED); a permission dialog needs an attach; idle sessions are stopped after about an hour and resume on a reply; the feature is a research preview; summaries use a Haiku-class call; each session uses quota independently.
- **O3. A host program on the SDK or stream-JSON that owns the sessions and writes the inbox.** The host answers `canUseTool` and `AskUserQuestion` itself, writes each question to the central inbox, and sends the owner's answer back; a `PreToolUse` `defer` lets a process exit while it waits. Cost: new code that nothing existing covers: the inbox link, the auto-mode block counter, a handoff replacement and the transcript path for the audit. The SDK page says it is for apps "you operate". Any use with a subscription login needs a terms check (F4).
- **O4. Keep terminals, remove only the open terminal per session.** Use the `orca serve --supervise` host and Chat UI on it, with the owner's view in the inbox. Cost: one more long-lived service; the local PC must stay on (the map allows it).
- **O5. Keep the TUI for coordinators and the central session; headless only for review subagents and verifiers.** They are already read-only subagents of the loop session (CLAUDE.md section 11), so they use no terminal today. Cost: no saving beyond today; no change to the harness.
- **O6. Add a measured step first.** A scratch test (outside every worktree) with the same hook set: one `claude -p` run, one SDK run, one Orca chat worker, one `claude --bg` session. Compare memory, CPU, hook firing, transcript shape, audit read and the wake on Orca mail. Cost: about a day of work and some quota; it gives the numbers that this file lacks.

## Gaps and open questions

1. No measurement of memory or CPU for headless against TUI. Only the TUI average (F8) is measured.
2. Whether this setup's hooks (audit, branch, readonly, redact, context) all run and block the same way in `-p`, SDK, chat and `--bg` sessions. The docs say settings hooks load; nothing says each event fires the same.
3. Whether the audit reads the transcript of a headless or chat session, and whether S2 sees the test result. Issue 729 may grow.
4. Whether `CLAUDE_CODE_SESSION_ATTENDED` is set to `0` by `-p`, by the SDK, by Orca chat and by `--bg`. The hook comment calls it undocumented. If unset, a headless session could run the handoff launcher and call `terminal create` with no terminal.
5. Whether a headless coordinator wakes on Orca mail, and whether a `Monitor` or an asynchronous hook can wake an idle SDK session.
6. How Orca chat treats a `permission-prompt` or `AskUserQuestion` in a subagent. The SDK page says `AskUserQuestion` is unavailable in subagents.
7. Whether a chat or headless worker counts for the Orca restart recovery: the prior research found no code that restarts a dead worker terminal (`orca-inbox-reliab.md` F8).
8. Terms of use for an own SDK program on a subscription login (F4).
9. The Orca docs page on "Remote Orca Servers" was not read. Chat UI behavior on a headless host rests on one sentence of the native-chat page.
10. Which Claude Code agent view limitations apply: the "Limitations" section of the agent-view page was cut off in the fetch.

## Sources read and sources that failed

Read, local (read-only):
- `claude --help`, `claude --version`; `orca --help`, `orca orchestration worker-start --help`, `orca agent launch --help`, `orca serve --help`, `orca agent hooks --help`, `orca agent-context --json` (searched for terminal-less and headless notes).
- The context-handoff hook source and its launch tests, the workflow-audit support file and auditor brief, and the tracked `settings.json` (hook event names and `defaultMode` only), in the tracked config repository.
- The installed Orca server bundle `orcad-server.js` (minified; short strings only: the SDK launcher defaults, the stream-JSON argument builder, the list of environment names it clears).
- `ps` and `free` for memory and CPU counts.
- Prior research in `docs/research/`: `orca-inbox-orca.md`, `orca-inbox-load.md`, and by reference `orca-inbox-tests.md` and `orca-inbox-reliab.md` (their sections quoted above were taken from the load file's summaries and the orca file; the tests and reliab files were not re-read in full).

Read, public (through a fetch tool that summarizes with a small model; quotes can differ slightly from the page):
- https://code.claude.com/docs/en/headless
- https://code.claude.com/docs/en/agent-sdk/overview
- https://code.claude.com/docs/en/agent-sdk/claude-code-features
- https://code.claude.com/docs/en/agent-sdk/user-input
- https://code.claude.com/docs/en/permission-modes (first 100,000 characters of 120,338)
- https://code.claude.com/docs/en/agent-view (first 100,000 characters of 146,212)
- https://orca.dev/docs/agents/native-chat, https://orca.dev/docs/agents/hooks-memory, https://orca.dev/docs/cli/orchestration (no headless or no-terminal text on the last)

Failed or not done:
- https://code.claude.com/docs/en/background-agents returned 404; the agent-view page replaced it.
- https://orca.dev/docs returned the home page only; the chat page was found by its link.
- Not run, by the rules of this task: any `claude -p`, SDK, `--bg` or Orca chat session, any `orca orchestration` command that changes state, any container or test run. Every behavior claim about a live headless session is therefore UNTESTED unless a doc line is quoted.
- No subagent was started. The task needed reading a few pages and local files, which a direct fetch does with less cost.
