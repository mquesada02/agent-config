# Open-source projects for the inbox and coordinator problems

Ticket 754 of map 752 (request 750). Date of reading: 2026-11-17. Builds on `docs/research/agent-workflow-comparison.md` (issue 723); it does not repeat that file.

Marks: **FACT** = taken from the source named. **INFERENCE** = our reading. Star counts, `pushed_at`, licence (SPDX) and release data come from the GitHub API (`gh api repos/OWNER/REPO` and `.../releases/latest`) on 2026-11-17, unless a line says otherwise. Doc quotes were read through a fetch tool that summarises pages with a small model, so they are near-verbatim, not byte-exact. Orca facts come only from the ticket text (worktrees, terminals, `orca orchestration` ask, reply, send, check between a coordinator and workers). Everything else said about Orca is INFERENCE.

## 1. Question

Which public projects solve: (a) one inbox for questions from many agent sessions; (b) a central coordinator over several repos; (c) routing a worker question to whoever can answer it; (d) approvals that need no person; (e) local notifications? For each: what it does, how it is built, maturity, licence, comparison with Orca. Which ideas can this setup reuse?

## 2. Short answer

1. No project does all five. The five problems split across different projects.
2. Inbox (a): cmux "Feed" is the best design reference. Its hooks park an agent request until the human answers in a UI or a desktop notification. amux, HumanLayer, Happy and Nimbalyst are next.
3. Central coordinator over repos (b): only Gas Town (a Mayor over many "rigs") documents it. Ruflo and Agor claim it; their pages give little detail.
4. Routing (c): only Gas Town documents an agent-first chain with a human last (severity, timeouts, re-escalation). mcp_agent_mail has a message bus but no escalation. Claude Code agent teams are one team per session, no nesting.
5. No-person approval (d) has three mechanisms: static rules, a second model (Claude Code auto mode, Codex auto-review, OpenHands analyzer) and deny-guards (cc-safety-net).
6. Notifications (e): Claude Code `Notification` hook plus ntfy or a chat bridge with Approve/Deny buttons (Channels permission relay, Lucarne, claude-ntfy-hook).
7. Licence risks: cmux (GPL), Claude Squad and CloudCLI (AGPL), amux (Commons Clause), Agor (BSL) and the Rust mcp_agent_mail (custom rider) are not permissive.
8. A search sweep (section 3.5) found newer projects close to Orca: Novadeck (one inbox plus agent messaging by handle; GPL-3.0), Squadra (recorded owner decisions with options and a recommendation; MIT), CAO (supervisor and workers on tmux; Apache-2.0) and Hermes IDE (worktree IDE with an attention inbox; BSL). Most other hits have under 100 stars.
9. Reusable ideas are in section 5; each needs the owner's decision.

## 3. Findings

### 3.1 Inbox for many sessions

| Project | Stars | pushed_at | Release | Licence |
|---|---|---|---|---|
| cmux (manaflow-ai/cmux) | 28809 | 2026-11-17 | v1.19.6 (2026-11-17) | NOASSERTION; README says "GPL-licensed" |
| Happy (slopus/happy) | 24679 | 2026-11-17 | cli-1.2.5 (2026-09-22) | MIT |
| HumanLayer (humanlayer/humanlayer) | 12900 | 2026-11-16 | pro-0.20.0 (2025-12-23) | Apache-2.0 |
| Vibe Kanban (BloopAI/vibe-kanban) | 28719 | 2026-11-15 | v0.1.46.* (2026-11-15) | Apache-2.0 |
| CloudCLI (siteboon/claudecodeui) | 14661 | 2026-11-16 | v1.37.9 (2026-11-16) | AGPL-3.0 |
| Nimbalyst (nimbalyst/nimbalyst) | 2083 | 2026-11-15 | v0.83.0 (2026-11-10) | MIT |
| amux (mixpeek/amux) | 562 | 2026-11-17 | v0.9.108 (2026-07-13) | NOASSERTION; "MIT License + Commons Clause" |
| CCManager (kbwo/ccmanager) | 1279 | 2026-10-27 | v4.4.11 | MIT |
| Claude Squad (smtg-ai/claude-squad) | 8823 | 2026-11-13 | v1.0.20 (2026-08-20) | AGPL-3.0 |
| Emdash (generalaction/emdash) | 6271 | 2026-11-10 | v1.2.11 | Apache-2.0 |
| Omnara (omnara-ai/omnara) | 3412 | 2026-11-17 | omnarad-v0.2.24 | Apache-2.0 |
| LangChain Agent Inbox | 1096 | 2026-09-18, archived | none | MIT |
| AgentAPI (coder/agentapi) | 1495 | 2026-09-13, archived | v0.12.2 | MIT |

Details, with sources:

- **cmux** (https://github.com/manaflow-ai/cmux; docs/feed.md, docs/agent-hooks.md in the repo). FACT: a native macOS terminal app (Swift, libghostty). An agent hook calls `cmux hooks feed`, which sends the verb `feed.push` over a unix socket. A FeedCoordinator parks the hook on a semaphore keyed by request id, for up to 120 seconds. The human answers in the Feed sidebar, a TUI (`cmux feed tui`) or a macOS notification with inline actions. Items are permission requests (Once, Always, All tools, Bypass, Deny), ExitPlanMode and AskUserQuestion. Storage is an in-memory ring buffer plus a JSONL audit file. Hooks exist for Claude and about 19 other agents. `cmux ssh` and `cmux mosh-tmux` relay hooks from remote hosts. Not read: the multi-machine-sessions and phone-push docs. vs Orca (INFERENCE): the strongest hook-based approval inbox; it has no coordinator and worker messaging. GPL limits reuse of its code.
- **HumanLayer** (https://github.com/humanlayer/humanlayer). FACT: README says it "runs coding agents (Claude Code, Codex, OpenCode, Pi) on your machines and lets your team steer them from one place". Bun monorepo, Hono API, Postgres synced with Electric, one daemon per host. The Claude plugin README says: "From the web app you can reply, stop a turn, answer permission prompts and comment on task files". Self-host is "a reference, not a supported install". The latest release is 2025-12 while pushes are daily. INFERENCE: it pivoted from an approvals SDK to team steering; it is the closest product to Orca. Server-backed, where Orca is a local IDE.
- **Happy** (https://github.com/slopus/happy; docs/backend-architecture.md). FACT: a CLI wraps Claude or Codex and mirrors the session to an E2E-encrypted phone app. Fastify and Socket.IO relay with Postgres, Redis and S3; machine daemon per host; a Cloudflare Worker sends push through APNs and FCM. The README does not describe approving a permission from the phone; docs/permission-resolution.md exists, not read.
- **Nimbalyst** (https://github.com/nimbalyst/nimbalyst). FACT: Electron workspace for Claude Code, Codex and OpenCode with parallel worktree sessions; an iOS companion app shows which agents wait for input, sends push, and takes a reply by text or voice. The sync server is a separate project. It succeeds Crystal (`stravu/crystal`, last push 2026-02-26).
- **amux** (https://github.com/mixpeek/amux; docs/self-hosting.md). FACT: one Rust binary and SQLite (axum on port 8824, event journal, SSE), tmux workers by default. README: "Watch, steer and approve from the iPhone and iPad app, the Mac app or the browser". It has a shared task board and agent-to-agent messages ("agents ask, hand off and unblock peers"); the mechanism was not read beyond the README. Created 2026-02-18; not OSI open source. Another repo, `andyrewlee/amux`, is unrelated.
- **Vibe Kanban**. FACT: `crates/executors/src/approvals.rs` defines `ExecutorApprovalService` with `create_tool_approval` and `create_question_approval`, so tool and question approvals are first class. It has an MCP crate and relay crates (INFERENCE: remote access). A worktree per task, like Orca.
- **CCManager**. FACT: a TUI over worktrees and projects, with status hooks that run shell commands (docs/status-hooks.md) and an experimental AI auto-approval verifier (`src/services/autoApprovalVerifier.ts`). INFERENCE: it detects "waiting" by screen state.
- **Claude Squad**. FACT: Go, tmux, worktrees; it hashes pane output to detect change and auto-presses Enter on the trust prompt; an AutoYes mode exists. No inbox.
- **CloudCLI, Emdash, Omnara**. CloudCLI is a web UI with web-push modules (INFERENCE: not shown to carry approvals). Emdash is an IDE-style peer; the README shows no inbox. Omnara is now a hosted agent platform and no longer the mobile approval app; only partly relevant.
- **LangChain Agent Inbox** (archived). FACT: a Next.js app that fetches LangGraph `interrupt` objects and sends human responses back; actions are accept, edit, respond, ignore. It is tied to LangGraph, not to CLI agents. Useful as a UX pattern.
- **AgentAPI** (archived). FACT: README says it is "deprecated and no longer maintained". An HTTP wrapper over a PTY; a building block only.
- **Claude Code Channels** (https://code.claude.com/docs/en/channels). FACT: "A channel is an MCP server that pushes events into your running Claude Code session". Channel servers that declare the permission relay capability "can forward these prompts to you so you can approve or deny remotely"; "Anyone who can reply through the channel can approve or deny tool use in your session". Research preview; one session each.

### 3.2 Central coordinator and routing

| Project | Stars | pushed_at | Release | Licence |
|---|---|---|---|---|
| Gas Town (gastownhall/gastown) | 18822 | 2026-11-14 | v1.2.1 (2026-06-06) | MIT |
| Beads (gastownhall/beads) | 28801 | 2026-11-17 | not checked | MIT |
| mcp_agent_mail (Dicklesworthstone) | 2237 | 2026-11-05, deprecated | not checked | NOASSERTION |
| mcp_agent_mail_rust | 260 | 2026-11-17 | not checked | NOASSERTION; "MIT+OpenAI/Anthropic Rider" |
| Ruflo (ruvnet/ruflo) | 81936 | 2026-11-17 | v3.77.1 (2026-11-13) | MIT |
| Agor (preset-io/agor) | 1494 | 2026-11-17 | v0.15.0 (2026-03-28) | NOASSERTION; README: BSL 1.1 |
| OpenAI Agents SDK | 30735 | 2026-11-17 | v0.24.0 | MIT |
| langgraph-supervisor-py | 1652 | 2026-07-15 | 0.0.31 (2025-11-19) | MIT |
| AG2 (ag2ai/ag2) | 5073 | 2026-11-17 | v1.3.2 | Apache-2.0 |
| CrewAI | 61031 | 2026-11-17 | 1.15.41 | MIT |
| OpenHands | 93647 | 2026-11-17 | v1.41.0 | MIT |
| A2A (a2aproject/A2A) | 26564 | 2026-11-17 | v1.0.1 (2026-05-28) | Apache-2.0 |
| ACP (i-am-bee/acp) | 1020 | 2025-08-25, archived | n/a | Apache-2.0 |
| ccswarm (nwiizo/ccswarm) | 157 | 2026-11-07 | v0.10.2 | MIT |

Details, with sources:

- **Gas Town** (https://github.com/gastownhall/gastown; README; docs/design/escalation.md). FACT: the Town is the parent workspace, a Mayor is "the primary AI coordinator" (a Claude Code instance), and each "rig" wraps one git repo with its agents. The Mayor "coordinates work across rigs". README: "Agents that hit blockers escalate via `gt escalate`, which creates tracked beads"; "Escalations route through Deacon -> Mayor -> Overseer based on severity." Design doc: "Each tier can resolve OR forward. The chain is tracked via bead comments." MEDIUM = bead and mail to the Mayor; HIGH = also email to the human; CRITICAL = also SMS. `stale_threshold` defaults to 4 h, `gt escalate stale` raises severity, `max_reescalations` defaults to 2, and an ack stops re-escalation. Human channels default to empty. Go CLI `gt`, hooks, mailboxes, beads as state. INFERENCE: the only documented match for both (b) and (c). The mechanism (severity, timeout, ack) is reusable as an idea; the code is MIT.
- **mcp_agent_mail** (README, raw.githubusercontent.com/Dicklesworthstone/mcp_agent_mail/main/README.md). FACT: an MCP server with `send_message(..., thread_id, ack_required)`, `fetch_inbox`, `acknowledge_message`; Git archive, SQLite index, web UI and TUI. Contact policies `open`, `auto`, `contacts_only`, `block_all`. "Overseer messages bypass normal contact policies". "An agent working in Project A is invisible to agents in Project B" unless they share a `project_key` or have contact links. It carries messages and acks; nothing routes a question or escalates on timeout. The Python repo is deprecated; the Rust successor has a custom licence rider. Closest standalone analogue to `orca orchestration` ask, send and check; no worktrees or terminals.
- **Claude Code agent teams and cross-session messaging** (https://code.claude.com/docs/en/agent-teams; .../cross-session-messaging.md). FACT: "One session acts as the team lead"; the mailbox is "a JSON file at `~/.claude/teams/{team-name}/inboxes/{agent-name}.json`"; "Teammate permission prompts appear in the lead session"; "One team per session ... You can't ... share a team across sessions"; "No nested teams"; "Lead is fixed". Cross-session: `ListAgents` and `SendMessage` over a local Unix socket; "A message ... can't approve anything"; Claude is told not to ask another session for an action that was denied in its own session and to "route that work back to you". INFERENCE: native peer of Orca messaging; it has no reply-correlated ask and no multi-coordinator structure.
- **Ruflo** (README only). FACT: claims queen-led hierarchy, federation across machines with mTLS and ed25519, and "AgentBBS rooms". INFERENCE: marketing-heavy, with no verifiable ask or escalation detail. The earlier research (723) found its own audit calls headline claims unsubstantiated. Treat as unverified.
- **Agor** (README). FACT: a web workspace; "Every piece of work is a git branch with its own working directory"; it "exposes itself over MCP, so agents can fork, spawn, schedule, and report"; Slack and GitHub gateways. No escalation chain or multi-repo coordination described. BSL 1.1, source-available.
- **Libraries** (OpenAI Agents SDK, LangGraph supervisor, AG2, CrewAI). FACT: handoffs "stay within a single run" (OpenAI); a supervisor coordinates specialist agents and can nest (LangGraph); AG2 v1 has typed channels where `consulting` is "one question, one reply, auto-closing" and a pluggable `hitl_hook` for a person (AG2 README); CrewAI delegation "is now disabled by default". INFERENCE: in-process, per run, with no terminals or persistent sessions. AG2 `consulting` and `hitl_hook` are the nearest vocabulary for ask/reply with a human fallback.
- **A2A** (https://a2a-protocol.org/latest/topics/life-of-a-task/). FACT: "When something is ambiguous, the agent returns an `input-required` state to ask the client for clarification"; the client answers in a follow-up. The protocol does not say who answers. INFERENCE: a standard shape for ask and reply; Orca's local bus is simpler. ACP is archived.
- **OpenHands** (README). FACT: one container and Agent Server per conversation; the canvas "can connect to multiple Agent Servers". No agent-to-agent routing described.
- **ccswarm** (API readme). FACT: a pipeline with a quorum of reviewer agents; "it does not resolve dissent". No question routing.

### 3.3 Approvals that need no person

| Item | Mechanism | Stars / date | Licence |
|---|---|---|---|
| Claude Code auto mode | second model reviews each action | docs, 2026-11-17 | closed source |
| Claude Code hooks | PreToolUse `permissionDecision`, PermissionRequest `decision.behavior` | docs | closed source |
| Codex approvals | `approval_policy`, sandbox, `approvals_reviewer = "auto_review"` | 135643; v0.169.0 (2026-11-13) | Apache-2.0 |
| Gemini CLI policy engine | TOML rules, priority tiers | 108901; v0.68.0 (2026-11-10) | Apache-2.0 |
| OpenHands | `ConfirmRisky` plus LLM security analyzer | 93647 | MIT |
| cc-safety-net (kenryu42) | deny-guard for destructive commands | 2061; v2.7.15 (2026-11-17) | MIT |
| claude-code-hooks-mastery (disler) | demo hooks, auto-allow read-only | 3988; pushed 2026-03-04 | none |

- **Claude Code auto mode** (https://code.claude.com/docs/en/permission-modes). FACT: "A separate classifier model reviews actions before they run, blocking anything that escalates beyond your request, targets unrecognized infrastructure, or appears driven by hostile content". "If the classifier blocks an action 3 times in a row or 20 times total, auto mode pauses and Claude Code resumes prompting." With no verdict, "Claude Code denies the action rather than run it unreviewed". `dontAsk` "auto-denies every tool call that would otherwise prompt you". Calls needing approval are denied unless an allow rule, hook, `canUseTool` callback or `--permission-prompt-tool` approves them. An allow rule or hook cannot approve recognised `rm` critical-path removals or reads from a network path.
- **Claude Code hooks** (https://code.claude.com/docs/en/hooks; first 100k of 294k characters read). FACT: `PreToolUse` returns `permissionDecision` (allow, deny, ask, defer); `PermissionRequest` returns `decision.behavior` (allow, deny); "a `PreToolUse` call stays blocked even if you return "allow"" after exit 2. Notification types include `permission_prompt`, `idle_prompt`, `agent_needs_input`, `agent_completed`. INFERENCE: the hook point where an Orca-side policy or inbox could attach.
- **Codex** (https://learn.chatgpt.com/docs/agent-approvals-security). FACT: sandbox modes read-only, workspace-write, danger-full-access; policy `on-request`, `never`, `granular`; `approvals_reviewer = "auto_review"` routes requests "through a reviewer agent"; "Auto-review uses extra model calls". The Codex `notify` option was not verified.
- **Gemini CLI** (https://raw.githubusercontent.com/google-gemini/gemini-cli/main/docs/reference/policy-engine.md). FACT: "evaluates all rules to find the highest-priority rule that matches the tool call"; decisions allow, deny, ask_user; "In non-interactive mode, this is treated as `deny`". Tiers Admin, User, Workspace, Default. The cleanest rules-only (no model) approver.
- **OpenHands** (https://docs.openhands.dev/sdk/guides/security). FACT: under `ConfirmRisky(threshold=HIGH)`, MEDIUM and LOW actions "run automatically"; `conversation.execute_tool()` "bypasses the analyzer and confirmation policy".
- **cc-safety-net**. FACT: "parses what the command does"; it "does not contain processes, set filesystem permissions, or watch network egress". INFERENCE: a deny-guard, not an approver.
- **cmux CCManager, Claude Squad**: see 3.1 (auto-approval by Enter press or AI verifier).

### 3.4 Local notifications

- **Claude Code `Notification` hook**. FACT (hooks doc): a Notification hook can return `terminalSequence` (OSC 777) for a desktop alert.
- **ntfy** (binwiederhier/ntfy; 35613 stars; v2.38.1 on 2026-11-16; Apache-2.0). FACT: "send push notifications to your phone or desktop via scripts from any computer"; self-hostable HTTP pub-sub.
- **claude-ntfy-hook** (nickknissen; 6 stars; pushed 2026-02-26; MIT). FACT: a PreToolUse hook sends an ntfy push with Allow and Deny buttons for tools on the `ask` list, and "exits with code 0 to allow the call or code 2 to block it". Tiny, but the exact pattern: blocking hook plus phone buttons.
- **Lucarne** (tuchg/Lucarne; 344 stars; pushed 2026-08-02; MIT). FACT: a daemon `lucarned` watches local agents (Claude, Codex, Copilot, Gemini and more) and posts to Telegram (a forum topic per project) and WeChat with `[Approve]` and `[Deny]` buttons; "no hooks, no skills, no MCP, no project changes".
- **claude-code-notification** (wyattjoh; 95 stars; MIT; macOS only). `terminal-notifier` (7380 stars; macOS; licence NOASSERTION). On Linux, `notify-send` was not researched.
- **Happy** push relay and **Claude Code Channels**: see 3.1.
- **disler hooks demo**: the Notification hook speaks text-to-speech; no licence in the API.

### 3.5 Search sweep (2026-11-17)

Method: `gh search repos <words> --limit N --sort stars --json fullName,stargazersCount,pushedAt,license,description` on nine word sets: "tmux agent dashboard claude"; "mcp agent mail inter-agent messaging"; "agent inbox human-in-the-loop approval"; "multi-repo coding agent orchestrator coordinator"; "claude code inbox"; "agent mailbox"; "multi-agent coordinator claude"; "claude notification approve"; "agent escalation human". Each word set matches repositories that contain all the words, so a long set returns few hits. Star counts and licence keys come from the search output. Only the projects marked "README read" had their README read (first 3500 characters, plus a keyword search for Novadeck, Squadra and CAO); for the others the only source is the one-line search description. Most hits are small (under 100 stars); stars are a weak signal of quality.

**Closest to the Orca problem (README read):**

| Project | Stars | pushed_at | Release | Licence |
|---|---|---|---|---|
| Novadeck (novadeck-org/novadeck) | 47 | 2026-11-17 | v1.6.59 (2026-11-13) | GPL-3.0; created 2026-09-19 |
| Squadra (dagoSte/squadra) | 1281 | 2026-11-12 | v3.15.1 (2026-11-09) | MIT |
| CLI Agent Orchestrator, CAO (awslabs/cli-agent-orchestrator) | 1569 | 2026-11-17 | v2.5.3 (2026-10-08) | Apache-2.0 |
| Orchvia (masonlee39/orchvia) | 18 | 2026-10-03 | not checked | MIT; created 2026-09-19 |
| Shura (mm0rsy/shura) | 0 | 2026-05-19 | not checked | Apache-2.0 |
| Hermes IDE (hermes-hq/hermes-ide) | 354 | 2026-11-16 | not checked | BSL 1.1 (README badge) |
| apra-fleet (Apra-Labs/apra-fleet) | 107 | 2026-11-17 | not checked | API "other"; README badge Apache 2.0 |
| Intaris (fpytloun/intaris) | 22 | 2026-11-08 | not checked | API "other" |

- **Novadeck** (https://github.com/novadeck-org/novadeck). FACT (README): "When an agent needs you, its question comes to one Inbox, and you answer it right there." "Every agent's permission prompts, plans and questions land in one Inbox. Most you answer with a click." Choices are Allow, always allow and Deny. "Agents message each other by handle and start their own teammates. Claude Code, Codex and Antigravity can share a team." A Messages pane shows a teammate's question to a lead and the lead's answer. Runs on macOS, Windows and Linux; "no account, no telemetry". INFERENCE: the closest public match to both gaps (inbox and agent-to-agent ask and answer in one app), but it is a terminal app and not a worktree IDE. The README does not say how the inbox is wired to the agents (hooks, MCP or process reading); that is not read. GPL-3.0 limits code reuse.
- **Squadra** (https://github.com/dagoSte/squadra). FACT (README): "one coordinates, others build, and a window that did not write the code reviews it. Assignments, decisions, executed checks and review reports stay in one shared registry on your computer." "A task starts only when its recipient confirms receiving it." "Questions with the sentence ready. When a decision is yours, you get the options, a recommendation and the exact words to answer." CLI verbs include `task`, `brief`, `ack`, `deliver`, `review`, `check`, `close` and `decision --owner-words`. A dashboard shows "requests for your input". Python standard library only; macOS and POSIX. INFERENCE: the closest design to the owner's question handling (a recorded decision with the owner's own words, option plus recommendation), and its ack-before-start rule is a pattern for dispatch. One registry per project, not a central inbox over several coordinators (not stated in the README).
- **CAO** (https://github.com/awslabs/cli-agent-orchestrator). FACT (README): "coordinates multiple AI coding CLIs so a supervisor can delegate work to specialist agents in parallel or sequence"; "runs a local `cao-server`, starts provider CLIs in isolated terminal sessions, and gives a supervisor tools for coordinating workers"; needs tmux 3.3 or later; supports Claude Code, Codex, Kiro, Copilot, OpenCode, Cursor and others; has scheduled "flows" and a web UI. INFERENCE: a maintained supervisor and worker model by a large vendor, the nearest to Orca's coordinator and worker split; the README gives no escalation chain to a human (the docs for supervisor tools were not read).
- **Orchvia** (https://github.com/masonlee39/orchvia). FACT (README): "Tasks, messages, approvals and token usage are stored in SQLite before anything runs. After a crash, work whose outcome is unknown waits for you instead of being retried." "A result counts as done only after a person or a check you registered accepts it." Agents are long-lived Claude Code and Codex sessions that message each other through a mailbox. Library with TypeScript and Python SDKs. Very new and small.
- **Shura** (https://github.com/mm0rsy/shura). FACT (README): "a multi-agent orchestration system for coordinating work across multiple repositories". Each repo gets a Product Owner agent; a Program Manager "is your only touchpoint throughout". Context is injected at dispatch, and "Agents do not share state files directly". Zero stars; a Claude Code plugin. INFERENCE: a design sketch of one central session over per-repo leads; no evidence of use.
- **Hermes IDE** (https://github.com/hermes-hq/hermes-ide). FACT (README): a desktop app with a worktree and a branch per task, "one status for every agent: working, needs approval, asked you, done, error or idle", "The attention inbox counts the agents blocked on you, and ⌘I jumps to the one that has waited longest", and a Review Desk. BSL 1.1 is source-available, not open source. INFERENCE: it matches Orca's shape (IDE, worktrees, terminals) and adds an inbox; no agent-to-agent messaging in the lines read.
- **apra-fleet** (https://github.com/Apra-Labs/apra-fleet). FACT (README): "Run a fleet of AI agents across your devices, your providers, your workflows"; agents on registered machines over SSH, with supervisors, watchdogs and dashboards; MCP compatible. INFERENCE: a multi-machine fleet model; the escalation to a human was not read.
- **Intaris** (https://github.com/fpytloun/intaris). FACT (README): evaluates tool calls against the user's stated intention; "A read-only fast path handles routine calls; other calls can go through model evaluation and, when needed, escalation"; audit trail; MCP proxy; self-hosted. It states it is "not a sandbox". Another example of a second-model approver (see 3.3).

**Other hits (search description only, not read):**

- Approval inboxes for agents: impri (6 stars, MIT), handup (3, other licence), hitly (2, Apache-2.0), agent-gate (0, MIT), human-in-the-loop-inbox (0, MIT), agent-approval-inbox-preview (0, no licence key). All are tiny; none had a README read.
- Mailboxes and buses: Tether, a local mailbox for CLI agents (29 stars, Apache-2.0); agentdrop (25, Apache-2.0); agent-mailbox-mcp (1, MIT); AAMP by larksuite, a mailbox protocol over email (123, MIT); agentcomm (17, MIT); openmeld (1428, MIT, "collaboration system for people and AI agents"); zenflow (59, Apache-2.0, workflow engine with an LLM coordinator).
- Dashboards: ai-maestro (853, MIT), recon (268, MIT, tmux-native), tmuxcc (68, MIT), agentdock (29, MIT), octomux (25, MIT, "kanban fleet view, one permi..." cut off), tmux-agent-status (25, MIT), armada (9, MIT).
- Notifiers with approval from the phone or desktop: ccnotifs (22, MIT, macOS, "Approve permission prompts directly"), claude-terminal-remote (3, MIT, ntfy), hook-me-up (2, MIT, macOS notifications with answers), claude-shadow (9, MIT, push), claudecodeui and Lucarne (see 3.1 and 3.4).
- Escalation and oversight: chap, a protocol runtime compatible with MCP and A2A (123, Apache-2.0); agentic-sidecar (65, MIT, "real-time supervision, escalation, and human"); agent-guard (25, MIT).
- INFERENCE: this sweep shows that the "one inbox for many agents" idea has many small new projects (most created in 2026). Only Novadeck, Squadra and Hermes IDE had a README read that matches Orca's problem in more than one point.

## 4. Comparison with Orca (INFERENCE)

- Orca has the agent-to-agent bus (ask, reply, send, check) and worktrees plus terminals in one IDE. No project in this set joins all of that with an inbox for the human.
- Closest on bus: mcp_agent_mail (no worktrees), amux (tmux and server based), Claude Code agent teams (one team per session).
- Closest on inbox: cmux Feed, HumanLayer, Nimbalyst.
- Only Gas Town documents a chain from worker to a human with severity and timeouts.
- INFERENCE: nothing found replaces the Orca bus; the gaps are the human inbox, the escalation chain and automatic approval.

## 5. Options for the owner

Each option is a candidate for a decision ticket. Costs are INFERENCE.

1. **Copy the Gas Town escalation model** (severity levels, per-tier resolve or forward, stale timeout, re-escalation cap, ack) as a written protocol over the existing Orca bus. Cost: a protocol spec and coordinator rules; the central session must track timers. No code reuse needed.
2. **Build an inbox on hooks, as cmux Feed does**: a hook parks the request, a local UI or desktop notification answers, an audit file records it. Cost: a local daemon plus hooks per agent; the cmux code is GPL, so copy the design only.
3. **Adopt an existing tool as the inbox** (HumanLayer, amux or Nimbalyst). Cost: a second system next to Orca, a licence check (amux and Agor are not open source), and a server to run for HumanLayer.
4. **Add an auto-approval layer in front of the inbox**: static rules (Claude Code allow rules, the Gemini TOML style) first, an auto-mode classifier second, a person last. Cost: rule upkeep; the classifier can pause after 3 blocks in a row or 20 in total, so the person stays the fallback; hard limits (critical-path `rm`) cannot be auto-approved.
5. **Notifications through ntfy or a chat bridge with Approve and Deny buttons** (claude-ntfy-hook pattern, Lucarne, Channels permission relay). Cost: a sender allowlist is mandatory ("Anyone who can reply through the channel can approve or deny tool use"); a push can approve a risky call from a phone; the owner decides which actions may be approved remotely.
6. **Do nothing new**: keep one coordinator per project group and the current ask and reply. Cost: the owner load stays.

## 6. Gaps and open questions

- The sweep of section 3.5 ran with `gh search repos` on nine word sets. It finds only repositories that match all the words in name, description or topics, so a project with other wording is missed. Only the top 12 to 15 hits by stars were listed per set. Hits other than the eight in the table were not read.
- No web search ran in the inbox subagent; non-GitHub projects (for example products on other hosts) were not searched.
- Not read: Novadeck's wiring of its inbox and its agent messaging (hooks, MCP or process reading); Squadra's handling of several registries; CAO's supervisor tools and any human-escalation docs; Hermes IDE messaging; apra-fleet escalation.
- Not read: cmux multi-machine and phone-push docs; the Happy permission flow; amux messaging code; Beads docs; LangGraph interrupt docs; langgraph-swarm; AutoGen (status not verified; the API licence field shows the docs licence); Claude Code Remote Control approval and push lines; the allow and deny rule syntax page; MCP elicitation; Pushover, Slack bots, `notify-send`; Conductor (closed source); Agent Teams versus a central coordinator in practice.
- Releases not checked: Beads, mcp_agent_mail, claude-plugins-official.
- No project was run. Maturity here means stars, `pushed_at` and releases, not quality.
- Orca's own current features were not read; all statements about Orca beyond the ticket text are INFERENCE.
- Question for the owner: does a remote phone approval count as "no person", and which actions may it approve?

## 7. Sources read and sources that failed

Read: GitHub API metadata for every repository above; READMEs of Gas Town, mcp_agent_mail, Ruflo, Agor, AG2, LangGraph supervisor, OpenHands, HumanLayer, Happy, Nimbalyst, amux, cmux (README, docs/feed.md, docs/agent-hooks.md), CCManager, Claude Squad, Emdash, Omnara, Agent Inbox, AgentAPI, ccswarm; Gas Town docs/design/escalation.md; Claude Code docs (permission-modes, hooks in part, channels, agent-teams, cross-session-messaging); Codex approvals page; Gemini CLI policy-engine doc; OpenHands security guide; OpenAI Agents SDK handoffs page; CrewAI hierarchical page; A2A life-of-a-task page.

Failed or limited:
- `gh api search/*` and `-f` flags were denied by the read-only subagent hook; the first pass was by named checks, and section 3.5 later added `gh search repos`.
- Three `gh search repos` calls and a metadata loop were blocked or needed a retry because a hook changed the command text; a loop of `gh api` calls was denied by a hook, so release data for the other sweep hits was not collected.
- `ccswarm` raw `main/README.md` returned 404; the API readme was used.
- `stravu/nimbalyst` returned 404; the right path is `nimbalyst/nimbalyst`.
- `langchain-ai/agent-inbox` has no release (404).
- Codex `docs/config.md` returned nothing on approval policy or notify.
- Claude Code Remote Control page: the response was cut off before the approval and push lines.
- The hooks page was read for its first 100k of 294k characters; the mcp_agent_mail README for its first 100k of about 141k.
- Fetch tools summarise pages, so quotes may differ in punctuation. Star counts for the notifier projects partly came from a rendered GitHub search page, not the API.
