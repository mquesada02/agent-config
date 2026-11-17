# Shared memory per project group (ticket 776, map 752)

## Question

How should one memory be shared by all sessions of a project group, and what should it hold? Compare four families: plain Markdown files in a group folder, the Claude Code memory folders (auto memory, `MEMORY.md` and its index), a small database, and open-source memory tools for coding agents. For each, answer five points: how sessions in different repos read and write it; how it stays small enough for the context; what happens when two sessions write at once; how sensitive names stay out of public repos; the cost. Also answer which kinds of entries belong in it.

Labels: FACT (with source), INFERENCE (reasoned from facts), UNTESTED (not run; the brief forbids tests and installs). Project groups use neutral labels: a work group of about 20 repos, a second product group of 4 repos, a personal group of 8 repos.

## Short answer

1. Claude Code already supports a memory folder that several repos share. Setting `autoMemoryDirectory` to one folder for every repo of a group gives a shared auto memory with no new tool. FACT (F2). Whether two repos can really share one folder this way is UNTESTED.
2. Claude Code loads only the first 200 lines or 25 KB of `MEMORY.md` at session start, whichever comes first. Topic files load on demand. This is the native size control. FACT (F3).
3. The native memory has no lock and no merge. Claude Code documents none, and its memory files are plain files edited with the normal file tools. INFERENCE (F5). Two sessions that write the same file at once can lose one write.
4. Sensitive names stay out of public repos when the memory folder lives outside every git repo, on the PC only. Auto memory is machine-local by design. FACT (F2). The risk is a report or PR that copies a memory line. That is a discipline and hook question, not a storage question.
5. A small database (SQLite or Dolt) fixes concurrent writes but adds a tool the agent must call, and its content is not visible in the context unless a command prints it. The best-known fit is Beads, which has `bd remember` and `bd prime`. It is a graph issue tracker first. FACT (F8).
6. The open-source memory tools (claude-mem, mem0, Basic Memory, the MCP memory server, Graphiti) mostly add a daemon, a vector store or a second model call. Basic Memory is the closest to plain Markdown, but its licence is AGPL-3.0. None of them removes the need for a curated index. FACT (F7 to F10).
7. Entries that belong in a group memory: stable facts and rules of the group, owner decisions with their date, and the state of each running effort as one line plus a pointer. Entries that do not belong: anything derivable from code or git, and any long log. INFERENCE from F1 and the Claude Code rule that auto memory skips derivable content (F1).
8. The current personal memory of the owner shows the failure mode: one flat index of 57 lines and about 12.5 KB, with some lines near 900 bytes, mixing rules, finished efforts and live efforts. It is under the 25 KB limit, but it grows each effort. FACT (F11).
9. The cheapest design to test first is a group folder of Markdown files with one short index, wired in by `autoMemoryDirectory` in each repo's local settings, plus an append-only "state" file per effort so no two sessions write the same file. This is INFERENCE and UNTESTED (O1).
10. The owner must decide: the folder layout, who may write which file, and whether a database or tool is worth its cost (section Options).

## Findings

### F1. What Claude Code memory is, and what it skips

- FACT: two mechanisms carry knowledge across sessions: `CLAUDE.md` files (written by the owner) and auto memory (written by Claude). Both load at the start of every conversation. Auto memory loads "first 200 lines or 25KB". Source: https://code.claude.com/docs/en/memory (table "CLAUDE.md vs auto memory").
- FACT: auto memory has four note types in frontmatter: `user`, `feedback`, `project` ("ongoing work, deadlines, and decisions that Claude can't derive from the code or git history") and `reference`. Claude "skips anything it can derive from the codebase". Source: same page, section "Auto memory".
- FACT: the guide says CLAUDE.md files should stay under 200 lines. Imports "don't reduce its context cost". Source: same page, section "Size" and "Import additional files".
- INFERENCE: the `project` and `reference` types already match two of the three entry kinds asked for (owner decisions, state of efforts). Stable rules fit `CLAUDE.md` or a `rules` file better than auto memory, because they are instructions, not learnings.

### F2. Where auto memory lives, and how to share one folder

- FACT: each project gets `~/.claude/projects/<project>/memory/`. "All worktrees and subdirectories within the same git repository share one auto memory directory". "Auto memory is machine-local". Files "are not shared across machines or cloud environments". Source: memory page, "Storage location".
- FACT: the setting `autoMemoryDirectory` moves the folder. The value must be an absolute path or start with `~/`. It is read from user, project, local, policy or `--settings` scope. Source: same section.
- FACT: with `permissions.blockReadsOutsideWorkingDirectories` on, Claude Code loads no auto memory from a folder chosen by a repository-supplied settings file. Source: same section.
- FACT: `CLAUDE_CODE_PROJECT_DIR_NAME` also makes sessions share one memory folder, but it works only together with `CLAUDE_CONFIG_DIR`, so it moves transcripts and the whole config folder too. Claude Code ignores it when `CLAUDE_CONFIG_DIR` is unset. Source: https://code.claude.com/docs/en/sessions, section "Name the project directory yourself".
- INFERENCE: a group folder needs `autoMemoryDirectory` set per repo, in `.claude/settings.local.json` (git-ignored). A user-level value would give one folder to every repo on the PC, so it cannot separate groups. A value in a tracked `.claude/settings.json` would put the folder path in a public repo.
- UNTESTED: that two repos with the same `autoMemoryDirectory` read and write the same files without conflict. The docs do not say it is supported; they only allow a custom path.

### F3. How the native memory stays small

- FACT: `MEMORY.md` loads its first 200 lines or 25 KB. After a write, Claude Code checks the file against both limits, reminds Claude to shorten it near the limit, and returns an error over the limit, "because everything past the limit is dropped on the next load". Topic files are not loaded at start; Claude reads them on demand. Source: memory page, "How it works".
- FACT: the limit applies only to `MEMORY.md`. A `CLAUDE.md` file loads whole up to 4 MiB. Source: same section.
- FACT: memory files are excluded from the transcript retention sweep. They stay until edited or deleted. Source: same page, "Storage location".
- FACT: the main conversation's auto memory is not loaded into subagents (a fork inherits it). A subagent can have its own memory folder through the `memory` field (`user`, `project`, `local`). Source: memory page; https://code.claude.com/docs/en/sub-agents, "Persistent memory".
- INFERENCE: a group memory read by about 20 repos needs a hard budget for its index, for example 60 lines, because every session of every repo pays its tokens at start. The 25 KB cap is about 6,000 tokens in the worst case (rough estimate, UNTESTED).

### F4. Other native ways to load a shared folder

- FACT: `CLAUDE.md` supports `@path` imports, relative or absolute, up to four hops deep. An import outside the working directory is "external": Claude Code asks once per project to approve it. User-scope files (`~/.claude/CLAUDE.md`, `~/.claude/rules/`) load imports without the dialog. Source: memory page, "Import additional files".
- FACT: the page shows the pattern for worktrees: a `CLAUDE.local.md` that imports a file from the home directory, because a git-ignored `CLAUDE.local.md` exists only in the worktree where it was created. Source: same section.
- FACT: `--add-dir` plus `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1` loads `CLAUDE.md` and `.claude/rules/*.md` (without `paths`) from an extra folder. Source: same page, "Load from additional directories".
- FACT: `.claude/rules/` accepts symlinks to a shared folder. A link target outside the working directory counts as an external import and needs the one-time approval. Source: same page, "Share rules across projects with symlinks".
- FACT: `claudeMdExcludes` skips named `CLAUDE.md` or rules files by glob. Source: same page.
- INFERENCE: for read-only, rule-like content (stable facts, owner decisions), a `CLAUDE.local.md` import of one group file is the least invasive path, because it needs no setting. Imports load the full file, so the file must be short. For read-write memory, `autoMemoryDirectory` is the native path.

### F5. Concurrent writes

- FACT: Claude Code documents memory files as plain Markdown files that Claude "reads and writes ... using its standard file tools". The pages read state no lock, no merge and no multi-writer rule. Source: memory page, "Storage location" and "How it works".
- FACT: two sessions that resume one transcript at once both write it, and messages can be lost; `--fork-session` is the fix there. Source: sessions page, "Branch a session". This shows Claude Code does not serialise concurrent writers for transcripts; it says nothing about memory files.
- INFERENCE: with two sessions editing the same `MEMORY.md` index, the last writer wins and the other line is lost. The Edit tool replaces an exact string, so two edits to different lines may both survive; two edits to the same line, or a whole-file rewrite after a size warning, can drop data.
- INFERENCE: the safest layout avoids shared mutable files. Give each effort or session one file it alone writes, and let the index list them. The index is then regenerated, not hand-edited. UNTESTED.
- FACT: tools that handle conflicts: Beads uses hash IDs ("prevent merge collisions in multi-agent/multi-branch workflows") and Dolt "cell-level merge" (F8); Basic Memory cloud has "rclone-powered ... conflict resolution" (F9). Plain git also detects conflicts on commit.

### F6. Keeping sensitive names out of public repos

- FACT: auto memory is machine-local and lives under the home folder, outside every repository (F2). Nothing in it reaches a public repo unless a session copies it.
- FACT: the local rule says a public repo gets generic content only, with neutral labels for groups (the map, "Notes").
- INFERENCE: the shared group memory must stay outside every git repo, for example in a plain folder under the home directory. A group folder placed inside a repo (even a private one) would risk a push of names. The `autoMemoryDirectory` path in a tracked settings file would itself leak a folder name, so it belongs in git-ignored local settings.
- INFERENCE: the leak path is the session, not the file. A session reads a private memory line and writes it into a public issue or doc. A hook that scans outgoing `gh` text for names from a local deny-list would cover this for any storage option. This is the same class as the existing redact hooks; it is not new for memory. UNTESTED.
- FACT: claude-mem offers `<private>` tags ("anything wrapped never gets stored") and has opt-in cloud sync, with the store in `~/.claude-mem` (F7). That protects the store, not outgoing text.

### F7. claude-mem

- FACT: a plugin with hooks and a worker service. "Runs a second agent beside it that takes notes while it works." The next session starts "with a short index of what matters" and the agent opens details on demand ("index, timeline, details"). Memory lives in `~/.claude-mem`. Cloud sync is opt-in. Anonymous analytics are on by default. An optional shared team workspace ("TeamBrain") exists. Licence shown in the repo metadata: Apache-2.0. Source: https://github.com/thedotmack/claude-mem README (read 2026-11-17).
- FACT: the installer asks to sign in to the vendor service by default and starts a trial that "asks for a payment method" for one observer option; flags such as `--provider` or `CLAUDE_MEM_ONLINE_OPTIN=false` skip it. Source: same README, "Quick Start".
- INFERENCE: it solves "remember what happened in this session" with a second model call per session. The map rules say every workflow agent stays on Sonnet and cost must fall; a second observer agent works against both. It stores observations, not curated group rules.
- UNTESTED: whether it can share one store across repos of a group, and its token cost.

### F8. Beads (`bd`)

- FACT: "Distributed graph issue tracker for AI agents, powered by Dolt". Dolt gives a "version-controlled SQL database with cell-level merge, native branching, and built-in sync via Dolt remotes". Hash-based IDs prevent merge collisions. `bd remember "insight"` stores a project memory that `bd prime` injects later. Also: ephemeral messages, threads, graph links (`relates-to`, `supersedes`), and "compaction" of old closed tasks to save context. License shown: MIT. Source: https://github.com/steveyegge/beads README (read 2026-11-17).
- FACT: the README says: "keep per-operator preferences in your harness's own memory". So its authors separate project facts (`bd remember`) from personal memory.
- INFERENCE: it overlaps with the issue tracker the owner already uses (GitHub Issues) and with the map. Using it only for memory would add a binary and a Dolt store for a small gain. It is the one tool here designed for concurrent multi-agent writes.
- UNTESTED: that `bd remember` works across several repos in one group.

### F9. Basic Memory

- FACT: knowledge "lives as Markdown files that both you and your AI can read, write"; local-first; two-way sync; search "on SQLite or" a vector store with FastEmbed embeddings; works as an MCP (Model Context Protocol) server; Obsidian reads the same files; local cross-device sync is manual ("Git, Syncthing, etc."); a paid cloud adds team workspaces and conflict resolution. Licence shown: AGPL-3.0. Source: https://github.com/basicmachines-co/basic-memory README (read 2026-11-17).
- INFERENCE: it is the closest match to "plain Markdown in a group folder" with a search tool on top. The MCP tool schemas add tokens to every session, and AGPL-3.0 limits reuse of its code in a derived tool (the owner would run it, not copy it). The search layer is useful only when the folder is too big to index by hand.

### F10. mem0, the MCP memory server, Graphiti

- FACT: mem0 is a library or server that needs an LLM ("gpt-5-mini from OpenAI as the default") to extract memories, with "single-pass ADD-only extraction" (memories accumulate; nothing is overwritten) and scopes for user, session and agent. Self-hosted server uses Docker. Apache-2.0. Source: https://github.com/mem0ai/mem0 README.
- FACT: the reference MCP memory server stores a knowledge graph of entities, relations and observations. `create_entities` skips existing names. Source: https://github.com/modelcontextprotocol/servers, `src/memory/README.md`. UNTESTED here: its file format and write locking (only the README tools list was read).
- FACT: Graphiti (getzep) is an active Apache-2.0 repository for temporal knowledge graphs (repository metadata read; its README was not read).
- INFERENCE: all three need a model or graph store to extract and rank facts. The group memory is small and owner-curated (tens of entries), so retrieval ranking has little to do. Cost without a clear gain. The default LLM of mem0 is not Sonnet, which conflicts with the "every workflow agent stays on Sonnet" note.

### F11. The owner's current memory, as a size baseline

- FACT: the current personal `MEMORY.md` has 57 lines and 12,522 bytes, with 59 files in the folder (command: `wc -l -c MEMORY.md`; `ls | wc -l`). The longest lines are 754 to 887 bytes.
- INFERENCE: it is at about half of the 25 KB limit. Its entries mix four kinds: standing rules (for example "never warn about usage"), tool facts, finished efforts with PR numbers, and running efforts with progress. Finished-effort lines are the main growth and carry no value after cleanup. A group memory with 20 repos would grow faster.
- INFERENCE: the entry kinds map to different lifetimes. Rules are stable. Decisions are stable but dated. Effort state is short-lived and should move to the tracker (the map issue) or be deleted when the effort ends.

### F12. Orca features that could carry state

- FACT (prior research, `orca-inbox-orca.md`, section 3.8): a worktree comment is a short status line on the workspace card, with a card status and an unread dot. Orca's mailbox is durable per Run. Cross-Run send was not tested (item 7).
- INFERENCE: running-effort state could live in the tracker plus a worktree comment, and not in the memory at all. That keeps the group memory to stable facts and decisions.

## Existing tools and what they cover (do not reinvent the wheel)

| Need | Existing thing | Covers it? |
| --- | --- | --- |
| One memory read by sessions in several repos | Claude Code `autoMemoryDirectory` (F2) | Yes for reading and writing the same folder, in theory. UNTESTED across repos. |
| Read-only shared rules in each repo | `CLAUDE.local.md` with `@` import, `.claude/rules` symlink, `--add-dir` with the env flag (F4) | Yes. One-time approval dialog for external imports. |
| Keep the always-loaded part small | 200 line / 25 KB `MEMORY.md` cap, topic files on demand, write-time warnings (F3) | Yes, native. |
| Safe concurrent writes | None in Claude Code (F5). Dolt/Beads, git, Basic Memory cloud. | No native cover. Layout (one writer per file) is the cheapest answer. |
| Keep names out of public repos | Machine-local folder (F2); `<private>` tags in claude-mem; the existing redact hooks | The folder, yes. Outgoing text from sessions, no. |
| Entries: decisions and effort state | Auto memory types `project` and `reference` (F1); GitHub Issues and the map; worktree comments (F12) | Yes. The tracker already holds decisions and state. |
| Search over many notes | claude-mem, Basic Memory, mem0, MCP memory server | Yes, but only needed when the folder outgrows a hand-kept index. |
| Multi-agent task graph with memory | Beads | Partly. It duplicates the tracker. |

What nothing existing covers: a rule for which session may write which group file, a retention rule that drops finished efforts, and a scan of outgoing public text for private names. These are policy, not software.

## Options for the owner

Each option states its cost. None is ranked.

- **O1. Group folder of Markdown files, native wiring.** One folder per group outside every repo. Each repo sets `autoMemoryDirectory` in git-ignored local settings. The `MEMORY.md` index stays under a fixed line budget. Each effort has its own state file that only its session writes. Cost: one-time setup in about 20 + 4 + 8 repos; behaviour across repos UNTESTED; no lock if two sessions write the index; the owner must prune finished efforts by rule.
- **O2. Read-only group file plus per-repo memory.** Keep native per-repo auto memory as is. Add one hand-curated group file, imported by each repo's `CLAUDE.local.md` (or by user-scope rules). Only the owner or the group coordinator edits it. Cost: no concurrent-write problem; sessions cannot add facts themselves; each repo needs a `CLAUDE.local.md`; the one-time approval dialog per repo; the whole file loads, so it must stay short.
- **O3. O1 or O2 plus a generated index.** A small script (or hook) rebuilds the index from the topic files' frontmatter, so no session hand-edits the index. Cost: a new script to write and test; hook rules (no heredoc, line-ending rules) apply; fixes lost writes in the index only.
- **O4. Dolt or SQLite store, with Beads.** Structured entries with hash IDs and cell-level merge. Cost: a new binary and store; agents call `bd` and the output enters the context only when printed; it overlaps with GitHub Issues; no public-repo protection beyond the folder location; MIT licence.
- **O5. Open-source memory service (claude-mem, Basic Memory, mem0).** Search and automatic capture. Cost: a daemon or MCP server on the PC; extra model calls (claude-mem observer, mem0 extraction) against the rule that all workflow agents stay on Sonnet and tokens fall; AGPL-3.0 for Basic Memory; vendor sign-in prompts in claude-mem; every tool UNTESTED here.
- **O6. Keep state out of memory.** Group memory holds only stable facts, rules and dated owner decisions. Running-effort state lives in the tracker and the worktree comment (F12), and the memory points to the map. Cost: depends on the tracker and Orca staying the source of truth; one extra lookup per session; no cost in tokens at start. Combines with O1, O2 or O3.
- **O7. Leak control by hook.** A hook checks `gh issue/pr` bodies against a local private-name list. Cost: a new hook and a list the owner maintains; false blocks; it covers every storage option above.

## Gaps and open questions

1. UNTESTED: two repos sharing one `autoMemoryDirectory`. Needs a scratch test with two throwaway folders (not run here: the brief forbids starting sessions).
2. UNTESTED: what happens when two sessions edit `MEMORY.md` at once. The pages read are silent.
3. Not known: whether the 200-line check counts the whole file or lines after frontmatter; the page says "first 200 lines or 25KB".
4. Not known: the real token cost of 60 index lines per session across 20 repos. Measure with `/context` in a scratch session.
5. Not read: the claude-mem architecture pages, Graphiti README, the MCP memory server's write path, Basic Memory's local multi-project behaviour, the `/memory` command help of the installed Claude Code.
6. Decision for the owner: who writes the group memory (the group coordinator only, or every session).
7. Decision for the owner: when a finished effort leaves the memory (at merge, at cleanup, or by age).
8. The subagent `memory` field (scope `project` or `local`) is a different folder per subagent name. Whether it helps a group is not studied.

## Sources read and sources that failed

Read:
- https://code.claude.com/docs/en/memory (full page text, saved locally; sections on CLAUDE.md, imports, rules, auto memory, AGENTS.md).
- https://code.claude.com/docs/en/sessions (session storage, retention, `CLAUDE_CODE_PROJECT_DIR_NAME`, simultaneous resume).
- https://code.claude.com/docs/en/sub-agents (persistent memory and startup context; the last 16,378 characters of the page were not read).
- READMEs and repository metadata through the GitHub API: thedotmack/claude-mem, basicmachines-co/basic-memory, mem0ai/mem0, steveyegge/beads, modelcontextprotocol/servers (`src/memory/README.md`, tools list only); metadata only for getzep/graphiti and doobidoo/mcp-memory-service.
- Prior research in the sibling research folders: `orca-inbox-orca.md` (sections 3.6 and 3.8), `orca-inbox-oss.md` (cmux `<private>`-style notes were not relevant), `orca-inbox-sandbox.md` (no memory content).
- Local facts: `wc -l -c` and `ls` on the owner's memory folder (counts only, no content copied); `orca --help` (no shared key-value or notes command in the top-level list).

Failed or not done:
- No test or install was run (brief rule). All behaviour claims about shared folders and concurrent writes are INFERENCE or UNTESTED.
- A first loop over several `gh api` calls was denied by the read-only hook; the calls were repeated one by one.
- Licence for claude-mem is as shown by the repository metadata and badge (Apache-2.0); the vendor sign-in terms were not read.
