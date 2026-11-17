# Per-repo memory: alternatives to one memory folder per working folder

Part of map #752, ticket #777. Date: 2026-11-17. Research only; no config was changed.

## Question

Today a session sees a repo's memory only when it starts in that repo's folder. Claude Code keeps one auto memory folder per git repo. What are the alternatives? Four were named: a coordinator that reads or writes another repo's memory folder, memory files tracked in the repo, an index that the group memory links to, and a memory service. For each: correctness (stale or conflicting writes), harness support, token cost, and fit with the group memory.

Labels: FACT (with source), INFERENCE (reasoned from facts), UNTESTED (not run here). "Group memory" means the shared memory per project group that the map plans. Project groups use neutral labels: a work group of about 20 repos, a second product group of 4 repos, a personal group of 8 repos.

## Short answer

1. Claude Code has no native cross-repo memory read. Auto memory is machine-local, one folder per git repo, shared by all worktrees of that repo (F1).
2. Every alternative below is built from plain files plus native settings. The Read tool can open any folder that permissions allow, so a coordinator can read another repo's memory today (F3, F4).
3. Topic files load on demand; only the first 200 lines or 25 KB of `MEMORY.md` load at start (F2). So an index of one line per repo costs little: for 20 repos about 3 KB, about 750 tokens (INFERENCE).
4. The risky part is writing, not reading. Claude Code documents no lock or merge for auto memory (F5). Two writers on one `MEMORY.md` can lose an edit (INFERENCE, UNTESTED).
5. A safe write rule: one writer per file. The coordinator writes only its own files in the group memory and sends repo facts to the repo session as mail; or it writes new topic files and never edits another repo's `MEMORY.md` (O1, O3).
6. Tracked memory in the repo (`docs/`, `CLAUDE.md` import, or subagent project memory) gives git merge and review, but it costs a PR per change and shows the text to anyone who reads the repo (F6, F7).
7. `autoMemoryDirectory` takes only an absolute path or `~/...`, so it cannot point to a repo-relative folder (F8). One folder per group is possible, and it merges all repos of the group into one memory.
8. A memory service exists (the official MCP knowledge-graph server, with a lock file). It adds tool calls and a second store beside auto memory. The Claude API memory tool is for API apps, not for Claude Code (F9, F10).
9. Existing tools cover reading and storage. Nothing existing covers cross-repo write coordination or staleness checks; the spec would build only a small convention for these.
10. This doc makes no choice. Section "Options for the owner" gives trade-offs.

## Findings

### F1. Auto memory is per repo, local to the machine, shared by worktrees

- FACT: "Each project gets its own memory directory at `~/.claude/projects/<project>/memory/`. The `<project>` path is derived from the git repository, so all worktrees and subdirectories within the same repo share one auto memory directory." "Auto memory is machine-local ... Files are not shared across machines or cloud environments." Source: https://code.claude.com/docs/en/memory (section "Storage location").
- FACT: the folder holds a `MEMORY.md` index and one topic file per memory. Claude Code does not load topic files at start; Claude reads them with its normal file tools when needed. Same page, section "How it works".
- FACT: memory files are excluded from the transcript retention sweep. Same page.
- INFERENCE: a coordinator in another folder gets none of this by default. That is the gap in the question.
- FACT (local, generic): a mature repo's `MEMORY.md` can reach about 57 lines and 12 KB, which is about 3,000 tokens at 4 bytes per token (INFERENCE for the token figure). Every session of that repo pays this at start.

### F2. Load limits

- FACT: "The first 200 lines of `MEMORY.md`, or the first 25KB, whichever comes first, are loaded at the start of every conversation." Claude Code warns when a write puts the file near or over the limit. Source: memory page, "How it works".
- INFERENCE: a group memory that lists 20 repos, one line each, fits far below the limit. A group memory that copies repo facts into itself does not.

### F3. A session can read outside its working folder

- FACT: the setting `permissions.blockReadsOutsideWorkingDirectories` exists; when it is on, file tools may not read outside the working folders. Claude Code also loads no auto memory from a folder chosen by a repo-supplied settings file while that setting is on. Sources: https://code.claude.com/docs/en/settings (exceptions table) and the memory page.
- FACT: `permissions.additionalDirectories` and the `--add-dir` flag add folders to the working set. By default, CLAUDE.md files from added folders are not loaded. Setting `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1` loads their `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md` and `.claude/rules/*.md` (rules with a `paths` field excepted). Source: memory page, "Load from additional directories".
- FACT: this env variable covers CLAUDE.md files, not auto memory folders. The memory page lists no equivalent for auto memory.
- INFERENCE: with the permission rules the owner already uses, a coordinator can Read another repo's memory folder by absolute path. The path is derivable (F4). The read is not blocked by the harness unless the block setting is on. UNTESTED here.

### F4. The memory path is predictable

- FACT: transcripts live at `~/.claude/projects/<project>/<session-id>.jsonl`, where `<project>` is the working folder path with non-alphanumeric characters replaced by `-` (truncated to 200 characters plus a hash if longer). Source: https://code.claude.com/docs/en/sessions ("Where transcripts are stored").
- FACT: the memory page says the folder is derived from the git repository. The sessions page says the transcript folder is derived from the working folder.
- INFERENCE: for a session started at the repo root, both names should match. For a worktree, the memory page says the folder is shared with the main repo, so the name comes from the repo, not the worktree path. The exact rule for a worktree was not tested. A coordinator should find the folder by listing, not by computing a name. UNTESTED.
- FACT (local): this machine has many project folders, so a listing needs a filter. A group index with explicit paths avoids the search.

### F5. No documented lock or merge for auto memory

- FACT: the memory, sessions and subagent pages describe no lock, version check or merge for memory files. Claude Code only records a `modified` ISO 8601 timestamp in the frontmatter of a memory file it writes. Source: memory page, "How it works".
- FACT: the sessions page says that two terminals that resume one session both write to one transcript, and messages can go missing. Source: sessions page, "Branch a session". This is a transcript case, not a memory case.
- INFERENCE: a write by the coordinator to a repo's `MEMORY.md` while a repo session also edits it can lose one edit (last write wins). The `modified` field lets a reader see how old a fact is. It does not stop a conflict. UNTESTED.

### F6. Memory tracked in the repo: the native mechanisms

- FACT: `CLAUDE.md` files in the repo are shared through source control. They can import files with `@path`. Relative paths resolve from the file that holds the import. Imports are expanded and loaded with the CLAUDE.md, so they do not reduce its context cost. Imports nest to four hops. Source: memory page, "Import additional files" and "Size".
- FACT: a path-scoped rule in `.claude/rules/` loads only when Claude works on matching files. Rules without `paths` load at launch. Source: memory page, "Organize rules".
- FACT: a subagent with the `memory: project` field gets `.claude/agent-memory/<name>/`, described as "shareable via version control". Its first 200 lines or 25 KB of `MEMORY.md` go into that subagent's prompt. It is part of auto memory: turning auto memory off disables it. Source: https://code.claude.com/docs/en/sub-agents ("Enable persistent memory").
- FACT: the main conversation's auto memory is not loaded into subagents. Same page, "What loads at startup".
- INFERENCE: a tracked file in the repo gets git history, review and merge conflict handling for free. The cost is the repo's change flow. Under the local workflow every change ends in a PR, so a memory edit costs a worktree, a review loop and a PR (CLAUDE.md sections 6, 8, 10; cited from the repo's own rules). That is too heavy for small facts (INFERENCE).
- INFERENCE: a tracked file is visible to every reader of that repo. A public repo can hold only generic text there.

### F7. Where a tracked memory file is read from in a worktree

- FACT: in a worktree, `CLAUDE.md` files and `.claude/rules/` load from the worktree. Untracked skills, agents and commands read through from the main checkout in some cases. Source: https://code.claude.com/docs/en/worktrees ("What worktrees share with the main checkout").
- FACT: a subagent that runs in its own worktree takes its instruction files from the main conversation, not from the worktree. Same page.
- INFERENCE: a tracked memory file differs per branch. A fact merged on the default branch reaches a worker only after the worker's branch has it. Auto memory (untracked, shared by all worktrees) does not have this lag.

### F8. `autoMemoryDirectory` and `CLAUDE_CODE_PROJECT_DIR_NAME` move or merge memory

- FACT: `autoMemoryDirectory` can be set in user, project, local, policy or `--settings`. "The value must be an absolute path or start with `~/`." A project setting is honored under the workspace trust rule. Source: memory page, "Storage location".
- FACT: `CLAUDE_CODE_PROJECT_DIR_NAME` (1 to 64 letters, digits, hyphen or underscore; needs `CLAUDE_CONFIG_DIR`; read from the shell environment only; v2.1.234 or later) makes "projects launched with that config directory share one auto memory directory". It also stores transcripts under that name. Source: sessions page, "Name the project directory yourself".
- INFERENCE: both give one shared folder for many repos, which is a group memory by construction. Neither gives a per-repo folder that a coordinator can see. A repo-relative path cannot be set, so a tracked folder cannot be the auto memory folder.
- INFERENCE: with one shared folder, repo facts and group facts mix, and the 200-line / 25 KB limit applies to the whole group (F2). Topic files per repo keep it manageable.

### F9. The official memory MCP server is a shared store with a lock

- FACT: `@modelcontextprotocol/server-memory` keeps a knowledge graph (entities, relations, observations) in `memory.jsonl`; `MEMORY_FILE_PATH` sets the file. Tools: create/delete entities, relations, observations; `read_graph`, `search_nodes`, `open_nodes`. Write tools take an exclusive lock file `<memory file>.lock`; a write that cannot get the lock in 60 seconds fails instead of overwriting. Network filesystems that ignore exclusive create are unsafe. Source: https://github.com/modelcontextprotocol/servers/tree/main/src/memory (README).
- FACT: each client starts its own server process, so clients that share one file are separate writers, serialized by the lock. Same source.
- INFERENCE: a graph with one entity per repo solves the cross-repo read and write and the conflict problem. It is a second store beside auto memory: it is not loaded at start, and a session must call a tool to read it. Each call adds tokens. It adds a Node.js dependency (the README requires Node.js 24 or later). UNTESTED.
- Not read: other third-party memory servers. The oss research (`orca-inbox-oss.md`) covered inbox and coordinator projects, not memory services.

### F10. The Claude API memory tool does not apply to Claude Code sessions

- FACT: the memory tool is client-side. Claude asks for file operations under `/memories`; "your application" runs them. The page tells the implementer to block path traversal. Source: https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool.
- INFERENCE: it is a building block for apps that call the API. Claude Code already has auto memory. The coordinator sessions in this setup are Claude Code sessions, so this tool adds nothing for them.

### F11. Subagent and worker memory

- FACT: the main conversation's auto memory is not given to subagents; a subagent's own memory is a separate folder (F6). Source: sub-agents page.
- INFERENCE: a worker started in a repo worktree is a full session, not a subagent. It loads that repo's auto memory (F1). A review subagent does not, so a coordinator must put needed repo facts in the subagent's brief. This matters for token cost: facts in the brief are paid per subagent.

### F12. Orca gives status lines, not memory

- FACT: `orca worktree set --comment` sets a short status line on the workspace card. `orca orchestration inbox` lists mail across mailboxes. Sources: `orca --help`; `orca-inbox-orca.md` sections 3.3 and 3.8.
- INFERENCE: mail is the right channel for a coordinator to hand a repo fact to a repo session ("please record this"). A comment is too short to be memory.

## Existing tools and what they cover

| Need | Existing tool or feature | Covers it? |
| --- | --- | --- |
| Per-repo notes that load at start | Claude Code auto memory (F1, F2) | Yes, for the session that starts in that repo |
| Read another repo's notes | Read tool by absolute path; `--add-dir` for CLAUDE.md only (F3) | Yes for reading, if permissions allow; no auto-load |
| Notes in version control | `CLAUDE.md`, `@path` imports, `.claude/rules/`, subagent `memory: project` (F6) | Yes, with a PR per change |
| One folder for a group | `autoMemoryDirectory`, `CLAUDE_CODE_PROJECT_DIR_NAME` (F8) | Yes, merges repos; no per-repo view |
| Index of repo memories | Plain `MEMORY.md` lines with paths (F2) | Yes; Claude Code does not check that a link is fresh |
| Safe concurrent writes | Memory MCP server lock (F9); git merge for tracked files (F6) | Partly: each needs a new component or a PR |
| Staleness hint | `modified` frontmatter field (F5) | Partly: shows age only |
| Ask a repo session to record a fact | Orca mail (F12) | Yes |
| Cross-repo write guard, link checker | None found | No |

Result: the spec needs to build only a short convention (who may write which file) and, if wanted, a small link and age check. It builds no memory store.

## Options for the owner

Each option can combine with the others. Costs are estimates (INFERENCE) unless marked.

### O1. Coordinator reads repo memory directly; writes only to the group memory

- How: the group memory has one index line per repo with the absolute path of that repo's memory index. The coordinator reads on demand. Repo facts go to the repo's own session as mail.
- Correctness: no cross-writer conflict, because each folder keeps one writer. A read can be stale; the `modified` field shows age.
- Harness: works with Read today (F3). Fails if `blockReadsOutsideWorkingDirectories` is on. UNTESTED.
- Tokens: about 3 KB for the index of 20 repos at start. Each repo read costs the size of the file read, only when needed.
- Fit: the group memory stays small and holds group facts only. Repo facts keep one source of truth.
- Cost: the repo session must act on mail. A repo session that is not running cannot record a fact until it starts.

### O2. Coordinator writes into repo memory folders directly

- How: the coordinator edits topic files (and the index) of each repo.
- Correctness: risk of lost edits when a repo session writes at the same time (F5). Lower risk if the coordinator only creates new topic files and the repo session adds the index line.
- Harness: no lock or merge. A write outside the working folder may be blocked by `blockWritesOutsideWorkingDirectories`. UNTESTED.
- Tokens: same as O1.
- Fit: faster hand-off, but two writers per folder break the one-writer rule that keeps O1 safe.
- Cost: needs a rule list for which files each side may edit, and a check, which nothing existing provides.

### O3. Tracked memory files in the repo

- How: `docs/` or `.claude/` files, imported by `CLAUDE.md` with `@path`, or `memory: project` for named subagents (F6).
- Correctness: git history, review and merge. A fact is stale on branches that lack it (F7).
- Harness: native. Imports cost tokens in every session of that repo, because they load in full (F6).
- Tokens: the whole imported file at every start; path-scoped rules lower this.
- Fit: the group memory can link to the file path in the repo. The facts leave the machine-local store, so other machines can read them.
- Cost: a PR per change; text is visible to everyone who reads the repo. Not for private notes in a public repo.

### O4. One folder per project group

- How: set `autoMemoryDirectory` per group, or `CLAUDE_CODE_PROJECT_DIR_NAME` with a config folder per group (F8).
- Correctness: many sessions write one `MEMORY.md`; the same lost-edit risk as O2, across more writers.
- Harness: native settings. The env variable also moves transcripts and the config folder, which is a large side effect.
- Tokens: the 200-line / 25 KB limit covers all repos of the group together (F2). A group of about 20 repos fills it sooner.
- Fit: this is the group memory itself. It removes the per-repo view.
- Cost: repo facts and group facts mix; a repo session loads facts of other repos, which costs tokens it may not need.

### O5. Memory service (knowledge graph over MCP)

- How: run the official memory server with one file per group; sessions call its tools (F9).
- Correctness: a lock serializes writes; a stale fact is still possible, because entities carry no age field in the README (INFERENCE).
- Harness: MCP is native. The server needs Node.js 24 or later.
- Tokens: tool schemas plus a call per read or write. Not loaded at start, so a session must be told to query it.
- Fit: a second store beside auto memory and the group memory. Two places to look.
- Cost: a dependency to run; the quality of retrieval for this use is UNTESTED.

### O6. Do nothing new for repo memory; keep decisions in the issue tracker

- How: durable facts already live in issues and in the map (INFERENCE from the map's "Decisions so far" list). The coordinator reads issues with `gh`.
- Correctness: issues have history and one canonical text.
- Tokens: a read per issue, only on need.
- Fit: the group memory keeps only pointers (issue numbers).
- Cost: issue text is not loaded at start; small facts (tool quirks, local paths) have no home.

## Gaps and open questions

- UNTESTED: whether a Read of another repo's memory folder works in the owner's permission mode, and which exact folder name a worktree session uses (F3, F4). A 5-minute test on a scratch repo would settle both.
- UNTESTED: whether Claude Code writes memory files atomically. If it writes a temp file and renames, a lost update is rarer than assumed (F5). The docs do not say.
- Not read: the hooks docs. A SessionStart hook could inject a repo's memory index into a coordinator. This is untested and was out of the sources read here.
- Not decided here: the size of the group memory and what it holds. That is a separate ticket of the map. This doc only gives the repo-memory link options.
- Open for the owner: is cross-machine sharing wanted? If not, auto memory plus O1 needs no repo change. If yes, only O3 or O5 (with a shared file) reach it, because auto memory is machine-local (F1).
- Open for the owner: should private facts about a public repo go in repo memory at all? Under O3 they cannot.

## Sources read and sources that failed

Read (all fetched 2026-11-17):

- https://code.claude.com/docs/en/memory (full page, saved locally and searched)
- https://code.claude.com/docs/en/sessions (full page)
- https://code.claude.com/docs/en/worktrees (full page)
- https://code.claude.com/docs/en/sub-agents (sections on persistent memory and what loads at startup; the last 16 KB of the page were not read)
- https://code.claude.com/docs/en/settings (full page; it holds no memory keys, only precedence rules and the exceptions table)
- https://github.com/modelcontextprotocol/servers/tree/main/src/memory (README)
- https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool (full page)
- `orca --help` (read-only) and the repo's prior research docs `orca-inbox-orca.md` (sections 3.3, 3.8) and `orca-inbox-oss.md` (scope check only)
- The repo's own `CLAUDE.md` rules (sections 6, 8, 10), cited by section number

Failed or not read:

- https://code.claude.com/docs/en/settings-reference (not fetched; keys `autoMemoryDirectory` and `autoMemoryEnabled` were taken from the memory page instead)
- https://code.claude.com/docs/en/hooks (not read)
- One shell call that listed local research folders was refused by the auto mode classifier because a hook rewrote its input. Its result was not used.
- No third-party memory service other than the official MCP server was read.
