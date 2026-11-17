# The home repo pattern for a project group (ticket 788, map 752)

Date of reading: 2026-11-17. Research only; no config was changed.

Labels: FACT (with source), INFERENCE (our reasoning), UNTESTED (not run; the brief forbids tests and installs). A search result is INFERENCE, not FACT, unless the page itself was read. Project groups use neutral labels: a work group of about 20 repos, a second product group of 4 repos, a personal group of 8 repos.

## Question

How does the "home repo" pattern apply to a project group of many repos? What is the pattern, what does it give a group (shared memory, rules, configuration, skills, the coordinator's working folder), and what are its costs and limits? Which needs of the sibling research docs `docs/research/orca-inbox-group-memory.md` (776), `orca-inbox-repo-memory.md` (777) and `orca-inbox-config.md` (778) does it cover or not? How does it fit git worktrees, Orca workspaces, the Claude Code memory folders and the public-repo rule? Are there other public uses of the same idea?

## Short answer

1. The pattern is one git repo that holds shared skills, `AGENTS.md`, steering files and shared docs. Its `AGENTS.md` has one pointer line per other repo. The owner starts sessions in it. FACT (F1).
2. It is a convention made of plain files. It has no software, no lock, no merge rule and no memory feature. FACT by absence (F1, F2).
3. It covers "rules, skills and docs shared by the group" well, and "where a coordinator starts" well. It covers "group memory that sessions write" only if the memory is tracked files in the home repo (F6).
4. Its reach ends at the session start folder. A worker that starts in a child repo worktree does not load the home repo's `AGENTS.md`, rules or skills unless an import, a symlink or an extra folder brings them in. INFERENCE from the Claude Code memory page (F4).
5. Claude Code keeps one auto memory folder per git repo, shared by its worktrees. So a session in the home repo has a group-level auto memory with no setting. The sessions in child repos do not share it. INFERENCE (F5).
6. A home repo is a git repo, so every change is a commit. Under the owner's rules (section 8, every task ends in a PR) a memory edit costs a worktree and a PR. FACT from the rules; cost INFERENCE (F7).
7. The public-repo rule needs the home repo to be private, or to hold generic text only. Pointer lines hold names and remotes. INFERENCE (F8).
8. Other public uses exist, with the same core and different extras: a meta-repo with `repos.yaml` and `active-work/` (F9), a central standards repo distributed by symlinks, imports or submodules (F10), a workspace folder with layered `CLAUDE.md` files (F11). None is a tool you install.
9. The article states its scale: about 20 repos works with direct pointers; about 400 needs one file per area. FACT (F1). It says nothing on concurrent writers, token cost or memory size.
10. The owner decides whether the home repo is the group folder of 776, a tracked sibling of it, or a separate thing (section Options).

## Findings

### F1. What the pattern is

- FACT: "A Home Repo is one repository that holds your skills, your AGENTS.md and your shared docs." "Its AGENTS.md holds a navigation pointer to each of your other repos." Source: https://www.aihero.dev/the-home-repo-pattern (read 2026-11-17).
- FACT: the problem it names: an agent started in one repo sees only that repo, so each repo gets duplicate skills and setup, and cross-repo planning suffers. Same page.
- FACT: the home repo holds skills used across repos, `AGENTS.md` with pointers, steering files, shared docs (coding standards first, then a glossary and system-wide decisions), optionally a small Markdown wiki, and later tooling. Child repos keep what is true of that repo alone: own `AGENTS.md`, build and test commands, repo docs. Code, history, remote and issue tracker stay in each repo. Same page.
- FACT: pointer line template: "<name> (<what it is>): <local path>. Clone from <remote> if missing." Same page.
- FACT: use: sessions start in the home repo, including for features that span repos. If a pointed repo exists at its path, the agent works there; if not, it clones it. Each repo is cloned once, and each feature gets a git worktree inside that clone, so several agents can work in one repo. Same page.
- FACT: setup is a four-step prompt (inventory repos, inventory shared material, agree a plan, apply it). The agent stays read-only until the plan is approved, leaves `.env` files unread, and does not push. Same page.
- FACT: scale. About 20 repos: direct pointers work. Around 400: "one pointer per repo is too many decisions for the agent", so use one file per business area (progressive disclosure). Thousands: a skills marketplace. Git submodules: workable at about 5 to 10 repos, but plain pointers do the same job. A monorepo is a good fit when available; the home repo substitutes when you cannot have one, for example when public and private repos mix. Same page.
- FACT: the dictionary entry for the term (https://www.aihero.dev/ai-coding-dictionary/home-repo) came back as HTTP 404 on direct fetch. A search snippet quotes it: skills copied into many repos drift apart; the fix is one copy and an `AGENTS.md` that points at each repo. This snippet is INFERENCE about the entry, not a read of it.
- FACT: the article names two example repositories (mattpocock/skills, mattpocock/sandcastle). The skills repo says "Skills for Real Engineers. Straight from my .agents directory.", MIT licence (GitHub API metadata). We did not read its files for a home-repo skill; a code search was refused by the read-only hook.
- INFERENCE: the article is one author's guide, not a specification. It is the primary source for the term, and it gives no measurement of cost or quality.

### F2. What the pattern does not include

- FACT by absence: the article describes no memory mechanism, no write rule for several sessions, no lock, no staleness check, no config levels and no leak control. It covers instructions, skills and docs, and who starts where.
- INFERENCE: so it answers the "where does shared text live and who reads it first" question. The open questions of 776, 777 and 778 (concurrent writes, size limits, floors and ceilings, outgoing leaks) stay open.

### F3. The group-level need, mapped

| Need from the sibling docs | Home repo gives it? |
| --- | --- |
| Shared rules and conventions of a group (778 group level) | Yes, as tracked files, for sessions that load them (F4) |
| Shared skills of a group | Yes, as one copy in the home repo; reach depends on F4 |
| Group memory that sessions read (776) | Yes, if it is a short tracked file or the home repo's auto memory (F5, F6) |
| Group memory that sessions write at once (776 F5) | No. Git gives merge and review, not live writes (F7) |
| Per-repo memory seen by a coordinator (777) | Partly: a pointer line per repo names the path to read (F6) |
| Coordinator working folder | Yes. The coordinator's session starts there (F1) |
| Group scope for settings and workflow knobs (778) | Partly: a file there can hold them; a repo session must be pointed at it (F4, F12) |
| Keep sensitive names out of public repos (776 F6) | Only if the home repo is private or generic (F8) |

### F4. Reach: what a session loads

- FACT: Claude Code loads `CLAUDE.md` and `CLAUDE.local.md` from the working folder and every folder above it. Files are concatenated. Source: https://code.claude.com/docs/en/memory (as read in `orca-inbox-config.md` F3).
- FACT: `@path` imports, `.claude/rules/` symlinks and `--add-dir` with `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1` bring a file or folder outside the working folder into a session. Imports outside the working folder need a one-time approval. Source: same page, as read in `orca-inbox-group-memory.md` F4.
- FACT: in a worktree, `CLAUDE.md` files and `.claude/rules/` load from the worktree. Source: https://code.claude.com/docs/en/worktrees, as read in `orca-inbox-repo-memory.md` F7.
- INFERENCE: a worker whose folder is a worktree of a child repo has no home repo above it. It does not load the home repo's `AGENTS.md`, rules or skills. The article says "start your sessions there", so it assumes the coordinator starts in the home repo and then works in child clones. It does not cover separate worker sessions that start in child repos. UNTESTED.
- INFERENCE: to reach those workers, each child repo needs a git-ignored `CLAUDE.local.md` with one `@` import of the home repo file, or the launcher passes `--add-dir`. This is the same wiring that 776 (O2) and 778 (O2, O3) already list. The home repo does not remove that wiring; it names the file to import.
- INFERENCE: Orca workers run in worktrees under the Orca workspace folder, not under a group folder (`orca-inbox-config.md` F3). So "the folder above" never reaches a home repo there.

### F5. Fit with Claude Code auto memory

- FACT: each git repo gets one auto memory folder; all its worktrees share it. Files are machine-local. `autoMemoryDirectory` moves it. Source: https://code.claude.com/docs/en/memory (as read in 776 F2 and 777 F1).
- INFERENCE: sessions that start in the home repo (any worktree of it) share one auto memory folder with no setting. That is a native group memory for the coordinator and for any session started in the home repo. It stays machine-local and outside every git repo, so it keeps names off any remote. Child-repo sessions do not read it.
- INFERENCE: this auto memory has the limits of 776: first 200 lines or 25 KB of `MEMORY.md` load, and no documented lock for two writers (776 F3, F5). The home repo adds nothing to these.
- INFERENCE: tracked files in the home repo and the home repo's auto memory are two stores with two lifetimes. Tracked files are for decisions and rules the owner wants reviewed. Auto memory is for what Claude learns. The pattern does not say which goes where.

### F6. Fit with the memory options of 776 and 777

- 776 O1 (group folder, `autoMemoryDirectory` per repo): the home repo's own auto memory is a free variant for sessions started there. For other repos it still needs the per-repo setting. INFERENCE.
- 776 O2 (read-only group file imported by each repo): the home repo is a natural place for that file, with git history and review. Cost: a PR per edit (F7). INFERENCE.
- 776 O6 (state in the tracker, memory holds stable facts): matches the article's own split (shared docs and decisions in the home repo; each repo keeps its issue tracker). FACT from F1; fit is INFERENCE.
- 777 O1 (coordinator reads repo memory by absolute path): the pointer line is the index that O1 needs. The article's template has a local path; a memory path would be a second path per line. INFERENCE.
- 777 O3 (tracked memory in the repo): the home repo is the same idea one level up, for group facts. Same costs: PR per change, visible to readers, stale on branches that lack the commit (777 F7). INFERENCE.
- 777 O4 (one folder per group): the home repo is a tracked folder per group, but Claude Code cannot make a tracked repo-relative folder the auto memory folder (777 F8). So it is a different store, not the same one. INFERENCE.

### F7. Costs and limits

- FACT: under the owner's rules, every task in a git repo ends with a PR, after a review loop and an audit, and work happens in a worktree (user instructions, sections 6, 8, 10). A change to the home repo follows them. Small edits cost that full flow unless the owner exempts them. INFERENCE for the size of the cost: the rules record about 9 to 10 minutes per test and review run in `docs/research/` earlier tickets; the exact figure for a docs-only change is not measured here.
- INFERENCE: concurrent edits of one tracked file by several sessions are caught at merge, not prevented. Branches diverge; a fact merged on the default branch reaches a worker only when its branch has it (777 F7).
- FACT: the article itself notes limits of scale (about 400 repos) and that submodules are not needed (F1).
- Token cost is about the size of the loaded text. A pointer line of about 30 words is about 40 tokens (rough estimate, UNTESTED), so 20 pointers cost about 800 tokens in a session that loads the file. A session that loads the whole shared docs folder pays more; the article does not bound it. INFERENCE.
- FACT (F11): another write-up warns that a large context chain can cost more than a focused prompt for a narrow fix, and that the docs go stale without upkeep.

### F8. Public-repo rule

- FACT: the owner's rule is that a public repo gets generic content only, with neutral labels for groups (map 752, "Notes").
- INFERENCE: a pointer line holds a repo name, its purpose and its remote. For a private group those are the sensitive names. So the home repo of a group with private names must be private, and its text must never be copied into a public issue or PR. The leak path is the session that copies a line, as in 776 F6, not the file.
- INFERENCE: one home repo per group, not one for all groups. A single home repo for all three groups would put work names beside personal names in one history. The article says a home repo can be personal or team-shared and that groups beyond about 20 repos get one file per area (F1). It does not discuss separation between employers or visibility levels. Another write-up warns that mixing companies and personal projects in one entry point risks exposure (F11).
- INFERENCE: the hook that scans outgoing `gh` text for private names (776 O7) is still needed. A home repo does not provide it.

### F9. Public use 1: an agents meta-repo with a repo map and tracking files

- FACT: a team built a dedicated context repo for six SDK repos, then reused it for a second product line. It holds `AGENTS.md` (repo map, conventions, links), `repos.yaml` (machine-readable paths, languages, build and test commands, CI names), `conventions/`, `workflows/` (multi-repo playbooks), `scripts/` (CLI wrappers), and `active-work/` plus `archive/` (multi-session epics). Source: http://blog.rubbad.uk/2026/03/05/blog-agents-meta-repo-pattern.html (redirected from seylox.github.io; read 2026-11-17). Author and team are not named here.
- FACT: they report that auto memory holds only a pointer to the active epic ("too flat" for progress), and that active-work documents hold dated session logs and decisions. They report an early version spent tokens on too much documentation; the fix was a short `AGENTS.md` that links out. They list drift, human review of plans, and per-repo docs still being needed. Same source.
- INFERENCE: this is the closest public match to the group needs: it adds a machine-readable repo table (which a hook or script can read, unlike prose) and a place for effort state. It is one team's report, with no measurement.

### F10. Public use 2: a central standards repo distributed to many repos

- FACT: a practitioner guide (no named author, marked "established", last reviewed 2026-06-12) describes one canonical repo of standards with `AGENTS.md`, `skills/`, `conventions/`, `policies/`, `templates/`, `generators/`, `dist/`. Repos consume it by symlink, `@` import, fan-out copy, package manager or platform plugin. Its worked example pins a git submodule to a tag, copies files with a pre-commit hook and diffs them in CI to catch drift. Source: https://agentpatterns.ai/workflows/central-repo-shared-agent-standards/ (read 2026-11-17).
- FACT: it lists limits: overhead for small setups, slow for fast-changing work, forced consensus, bloat at scale (one cited analysis: 22% of 673 skills failed structural checks), advisory only without CI checks, and an evaluation where LLM-written context files slightly lowered task success (not significant) and raised inference cost by 20 to 23%. Same source; the cited studies were not read.
- INFERENCE: this differs from the home repo in one point. It pushes files into each repo (pinned, checked in CI), where the home repo points at repos and keeps them untouched. It answers F4 (reach) by copying, at the cost of copies that can drift and a sync step.

### F11. Public use 3: a workspace folder with layered context files

- FACT: one author describes a single workspace folder holding all organizations, products and repos, with four levels of `CLAUDE.md` (workspace, organization, product, repo). Rule: "every fact lives on exactly one level". The agent reads the chain along the task path. `CLAUDE.local.md` holds personal details. Source: https://dev.to/vains/one-entry-point-for-your-coding-agent-organizing-multi-repo-multi-product-context-52nd (read 2026-11-17).
- FACT: limits named: savings are not guaranteed; a narrow fix is cheaper with a focused prompt; setup and upkeep cost effort; the model sees product code, so check data policies; mixing companies and personal projects in one entry point risks exposure. Same source.
- INFERENCE: the layering works because Claude Code loads `CLAUDE.md` files from folders above the working folder (F4). In the owner's setup, worktrees live in the Orca workspace folder, so this layering would need the workspace folder to be a real parent of the repos. That is an Orca question (see 776 and `orca-inbox-orca.md` 3.9).
- Search result list (INFERENCE only, not read): the same search also returned posts on a canonical-skills folder shared by symlinks, a dotfiles-style repo of agent scripts with a global pointer file, and a shared-skills registry with version pins. Titles suggest the same family; their claims were not checked.

### F12. Fit with Orca and git worktrees

- FACT: Orca's folder workspace can hold several git repos; worktrees created with `--repo` from a folder workspace attach to it; a folder workspace can be addressed as a coordinator. Orca has no named group object. Source: `orca-inbox-orca.md` section 3.9 (prior research).
- INFERENCE: a home repo can be one of the repos of that folder workspace, or its own repo. The coordinator session for a group would start in a worktree of the home repo (rule: never work in the main checkout, section 10). Each child repo keeps its own worktrees for workers, as the article describes (one clone, one worktree per feature).
- INFERENCE: the owner's rule that every ticket worker gets a child worktree of the coordinator's worktree fits, because the coordinator worktree would be a worktree of the home repo. The git base of a worker is still its own repo's default branch.
- UNTESTED: whether a worker's child worktree can have a parent in another repo for this layout. Prior research says `worktree create` can name a parent in another project on the same host (`orca-inbox-orca.md` 3.9).
- INFERENCE: the home repo has its own auto memory folder per repo (F5) and its own `.claude/settings.local.json`, shared by its worktrees (`orca-inbox-config.md` F2). So group-level settings for sessions started in the home repo have a place without a new scope. They do not reach sessions started elsewhere.
- INFERENCE: for config (778 F6), a file in the home repo is outside the audited tree of a child repo PR. An audit that reads the knob file from the home repo's default branch avoids the "branch edits its own check" hole. UNTESTED: the audit does not read such a file today.

## Existing tools and what they cover (do not reinvent the wheel)

| Need | Existing thing | Covers it? |
| --- | --- | --- |
| One place for shared skills, rules, docs | The home repo convention (F1); a central standards repo (F10) | Yes, as convention; no software to build |
| Reach from a session in a child repo | `@` import in `CLAUDE.local.md`, `.claude/rules` symlink, `--add-dir` with the env flag (F4) | Yes, native; one-time approval for external imports |
| Machine-readable repo table | `repos.yaml` pattern of the meta-repo (F9) | Yes as a pattern; no reader exists in the audit |
| Group-level auto memory for sessions in one folder | Claude Code auto memory of the home repo (F5) | Yes for sessions started there |
| Safe concurrent writes to shared memory | Git merge for tracked files; MCP memory server lock (777 F9) | Partly; not live |
| Version pinning and drift checks of shared files | Submodule plus CI diff (F10) | Yes, with extra moving parts |
| Setup of the pattern | The article's four-step agent prompt (F1) | Yes; read-only until approved |
| Leak control of private names | None in the pattern | No. A hook is still needed (776 O7) |

What nothing existing covers: a rule for which session may write which home repo file, a retention rule for finished efforts, and scanning outgoing public text. These are policy, as 776 found.

## Options for the owner

Each option states its cost. None is ranked. They can combine.

- **O1. Home repo as a tracked, private group repo for stable text.** It holds the group `AGENTS.md` with pointer lines, shared rules, decisions and glossary. Sessions in child repos reach it by a git-ignored `CLAUDE.local.md` import. Cost: one private repo per group (3 repos); wiring in about 20 + 4 + 8 child repos; a PR flow for each edit; the whole imported file loads in every session, so it needs a size budget; no live write safety.
- **O2. Home repo as the coordinator's start folder only.** The coordinator session starts in a worktree of the home repo and uses its auto memory and tracked files. Child repos are not wired. Cost: no reach for workers; the coordinator must put needed facts in each worker brief, which costs tokens per worker; the memory stays machine-local.
- **O3. Home repo plus a machine-readable repo table.** O1 or O2, plus a `repos.yaml`-style file that scripts and hooks read (paths, test commands, memory path). Cost: one file to keep true; a reader to write if a hook uses it; drifts if not maintained.
- **O4. Central standards repo with pinned copies in each repo.** Shared files copied into child repos at a pinned tag, checked in CI. Cost: a sync step, a CI check and a PR per upgrade in each repo; copies can drift between upgrades; the child repo then holds shared text, which matters for public repos.
- **O5. No home repo; group folder outside every repo (776 O1 or O2).** Plain folder and native settings only. Cost: no git history or review for group text; wiring still needed in each repo; sensitive names stay local. This is the baseline the home repo is compared with.
- **O6. Keep state in the tracker; use the home repo for rules and decisions only.** Matches 776 O6 and the article's split. Cost: depends on the tracker staying the source of truth; one extra lookup per session.

## Gaps and open questions

1. UNTESTED: whether a `CLAUDE.local.md` import of a file in another repo loads in an Orca worker with no user to approve the one-time dialog (also gap 2 of 778).
2. UNTESTED: whether sessions started in different worktrees of the home repo share one auto memory folder as the docs say, and what two writers do.
3. Not read: the files of the example repositories named in the article; the dictionary entry (404); the cited studies in F10; the other search results of F11.
4. Not measured: real token cost of a pointer file and of shared docs per session. Measure with `/context` in a scratch session.
5. The article gives no rule for retiring finished-effort text. 776 asks the same.
6. Decision for the owner: one home repo per group, or one per visibility level, and whether it is private.
7. Decision for the owner: whether edits to the home repo follow the full section 8 PR flow, or a lighter path (this touches the audit rules and is outside this ticket).
8. Decision for the owner: whether the home repo and the group memory of 776 are one thing or two.

## Sources read and sources that failed

Read (2026-11-17):
- https://www.aihero.dev/the-home-repo-pattern (full text via the fetch tool; summary form, not verbatim except the quoted lines)
- http://blog.rubbad.uk/2026/03/05/blog-agents-meta-repo-pattern.html (after a 301 from the original host)
- https://agentpatterns.ai/workflows/central-repo-shared-agent-standards/
- https://dev.to/vains/one-entry-point-for-your-coding-agent-organizing-multi-repo-multi-product-context-52nd
- Sibling docs in the same folder: `orca-inbox-group-memory.md`, `orca-inbox-repo-memory.md`, `orca-inbox-config.md` (full); prior doc `orca-inbox-orca.md` section 3.9.
- GitHub API repository metadata of the skills repo named in the article (description and licence only).
- The Claude Code memory, worktrees and settings pages were not re-fetched; their facts are cited through the sibling docs.

Failed or not read:
- https://www.aihero.dev/ai-coding-dictionary/home-repo returned HTTP 404; only a search snippet exists (INFERENCE).
- A GitHub code search in the skills repo was refused by the read-only hook; no home-repo skill file was read.
- The first fetch of the meta-repo post stopped at a redirect and needed a second call.
- Other search results (canonical skills folder, dotfiles-style agent scripts, skills registry, shared agent config tools) were not opened.
