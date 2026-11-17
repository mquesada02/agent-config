# Configurable workflow: what and at which levels

Date of reading: 2026-11-17. Marks: **FACT** = quoted or read at a primary source (the source is named). **INFERENCE** = our reading. **UNTESTED** = not run. Part of the research for the central coordinator session (ticket 778 of the map 752). This file answers the question. It makes no decision for the owner.

All local paths below are tracked files of this repository. "The user instructions file" means the global CLAUDE.md of the owner; its sections are cited as "section N".

## 1. Question

Which parts of the workflow should be configurable, and at which levels (global, project group, repo)? For each part: where the setting lives today, what Claude Code supports natively (settings scopes, CLAUDE.md layering, plugins), how hooks and the audit read it, and how to stop a setting from weakening a safety rule.

## 2. Short answer

1. Today almost every workflow setting is prose in the user instructions file (global level) or a constant inside the audit code. Only the test command is a per-repo declaration that code reads.
2. The audit hard-codes the review caps (5 and 3 rounds) and the Sonnet check. A per-repo or per-group change of these needs a code change in the audit, not a text change.
3. Claude Code has four settings scopes plus managed settings. It has no "project group" scope.
4. CLAUDE.md files do not override each other. They are concatenated, and a conflict between two files is resolved by the model "arbitrarily". Prose is not a safe place for a rule that a lower level may change.
5. A group level can be built from existing features: a shared folder plus `@path` imports, `.claude/rules/` symlinks, or additional directories. This is INFERENCE: not run.
6. Hooks from all scopes merge. A lower scope cannot remove a hook of a higher scope. This helps keep safety rules.
7. Managed settings (a system file) beat every other scope. They are the only native lock. On a single-owner PC they also lock the owner's own sessions.
8. Safe design (INFERENCE): split settings into "tunable" (a repo or group may change them) and "fixed" (global only, enforced by code). Let a lower level only tighten a tunable value (a floor or a ceiling set by the global level).
9. No existing tool covers a workflow-level configuration with floors and ceilings. The native scopes cover tool settings only. The workflow knobs need one small machine-readable file plus a reader in the audit.
10. A real hole today: the audit reads the declared test command from the branch under audit (section F6). Any config file read the same way has the same hole.

## 3. Findings

### F1. Where each candidate setting lives today

| Candidate | Where it lives today | Read by code? |
| --- | --- | --- |
| Models per role | Section 9 says "use Sonnet". `settings.json` keys `model`, `fallbackModel`, `effortLevel`. Per call, the `model` field of the Agent tool. | Yes, partly: the audit has `SONNET = "claude-sonnet-5-5"` (`hooks/workflow-audit/audit_support.py`, line 113) and check S7 reads session models. A hook (`hooks/forked-skills/block_forked_skills.py`) denies forked skills that would not run on Sonnet. |
| Review rounds and caps | Section 6 text (5 and 3 rounds) | Yes: `PHASE_CAPS = {"correctness": 5, "final": 3}` (`hooks/workflow-audit/audit`, line 33). Extensions are ledger events (`extension`), so the owner can raise one cap per loop phase at run time. |
| Which section 7 steps run | Section 7 text, including the "small task under about 150 changed lines" exception | Partly: the audit item L5 judges the small-task estimate (`hooks/workflow-audit/auditor-brief.md`). `size-approval` events record an owner-approved larger size. The audit has a sanity bound `MAX_APPROVED_LINES = 100000`. |
| Test command | A heading `### Test command` with one fenced block in `.claude/CLAUDE.md`, `CLAUDE.md` or `AGENTS.md` of each repo | Yes: `TEST_COMMAND_HEADING` and `DECLARATION_FILES` (`hooks/workflow-audit/audit`, lines 126-127). The audit demands exactly one such block. |
| Worker limits | Section 15 text ("at most 2 workers, passed on the command line") | Yes, partly: the audit has a table of runner names and their worker flags (`hooks/workflow-audit/audit`, line 141). |
| Audit checks | Code: checks S1 to S10 and XC in `hooks/workflow-audit/audit`; items L1 to L6 in `hooks/workflow-audit/auditor-brief.md` | They are the code. |
| Notification rules | `settings.json` keys `agentPushNotifEnabled` and `preferredNotifChannel`. The Orca hooks in `settings.json`. | By Claude Code and Orca, not by the audit. |
| Delegation rights of coordinators | Sections 7 and 11 text. The subagent write block is a hook (`hooks/subagent-readonly/block_subagent_writes.py`). | Partly: the hook enforces "subagents never write remote state". The rest (who may merge, who may extend a cap) is prose. |

FACT, source: the files named in the table. The `settings.json` key names come from reading the owner's user settings file (keys listed: `model`, `fallbackModel`, `effortLevel`, `autoCompactWindow`, `agentPushNotifEnabled`, `preferredNotifChannel`, `hooks`, `permissions`, `enabledPlugins`).

INFERENCE: the settings split into three kinds. Kind A is prose that a model follows (models, step choice, delegation rights). Kind B is a constant in code (caps, Sonnet id, size bound). Kind C is a declaration read by code (test command). A configurable workflow needs every knob to move to kind C, or its prose to be backed by a code check.

### F2. Claude Code settings scopes

FACT, source https://code.claude.com/docs/en/settings: four files plus managed settings. User (`~/.claude/settings.json`), shared project (`.claude/settings.json`), project local (`.claude/settings.local.json`), managed (`managed-settings.json` and other delivery ways).

FACT (same page): precedence, highest first: "managed settings, command line, project local, shared project, user".

FACT (same page): "When you set the same list key, such as `permissions.allow`, in more than one file, Claude Code combines the lists instead of picking one." Four model keys are exceptions with their own rules (`fallbackModel`, `modelPicker`, `availableModels`, `modelSettings`).

FACT (same page): a worktree uses the local settings file "at the main checkout's root". INFERENCE: the project-local scope is shared by all worktrees of one repo, and it can hold per-repo overrides without a commit.

FACT (same page): some keys never apply from a repository file (the page lists scopes "User", "User or managed", "Managed" in its settings index). Example: `permissions.defaultMode` values `auto` and `bypassPermissions` "don't take effect from project or local settings".

FACT (same page): `--settings <file-or-json>` applies "above your user, project, and local files and below managed settings". INFERENCE: a launcher (the one that starts a coordinator or worker) can inject a per-group settings file with `--settings`. This gives a group level without a new native scope. UNTESTED.

FACT (same page): "A key at a higher level overrides the same key" for scalars. Settings files are strict JSON with no comments.

There is no group scope. FACT by absence: the page lists no group, folder-set or workspace scope.

### F3. CLAUDE.md layering

FACT, source https://code.claude.com/docs/en/memory:
- Claude Code loads `CLAUDE.md` and `CLAUDE.local.md` "from your current working directory and every directory above it".
- "All discovered files are concatenated into context rather than overriding each other." Order runs from the filesystem root down to the working directory.
- Files in subdirectories load on demand, when Claude reads a file there.
- "If two instructions contradict each other, Claude may pick one arbitrarily."
- User rules in `~/.claude/rules/` load before project rules. "Neither set overrides the other: if a user rule and a project rule conflict, Claude may follow either one."
- `@path/to/import` syntax expands an imported file into the CLAUDE.md that names it.
- `.claude/rules/` accepts path-scoped rules (a `paths:` field) and symlinks, so "you can maintain a shared set of rules and link them into multiple projects". Project symlinks need a one-time approval; rules in `~/.claude/rules/` do not.
- `claudeMdExcludes` skips named files at any settings layer. It cannot exclude a managed CLAUDE.md.
- With an environment variable set, the CLAUDE.md files of an additional directory also load (the page names the variable; we did not read its name in full).
- The page says CLAUDE.md is "context, not enforced configuration. To block an action regardless of what Claude decides, use a PreToolUse hook."

INFERENCE: a repo-level section 6 cap written in a repo CLAUDE.md does not override the global section 6. The model sees both and may follow either. So prose cannot carry a configurable knob that must be exact.

INFERENCE: the worktrees of the owner live in a workspace folder of the Orca application, not under a group folder. So the "directory above" walk does not reach a folder that groups repos by project. A group CLAUDE.md therefore needs an `@import` or a symlink in each repo, or an additional directory. UNTESTED. See `docs/research/orca-inbox-orca.md` section 3.9 (repos, folder workspaces, groups) for what Orca itself stores.

### F4. Hooks: what they see and how scopes combine

FACT, source https://code.claude.com/docs/en/hooks: a command hook receives JSON on stdin with `session_id`, `cwd`, `transcript_path`, `permission_mode`, `effort`, and for subagents `agent_id` and `agent_type`. `cwd` is the worktree root after the session enters a worktree.

FACT (same page): "Hook entries merge across settings levels rather than replacing each other: user, project, and local settings add their own hooks without removing managed ones." The same handler in two files runs once. `disableAllHooks` "can't disable managed hooks".

FACT (same page): `allowManagedHooksOnly` in managed settings blocks "user, project, local, and plugin hooks".

INFERENCE: a hook can find its repo from `cwd` (for example by the repo root and the remote), then read a per-repo or per-group file. Nothing native reads a config for a hook; the hook must do it. Hooks run on every tool call, so the read must be cheap (one small file, no network).

FACT: the audit already does this for the test command. It reads declaration files from the worktree path it is given (`hooks/workflow-audit/audit`, function `_declared_command`).

### F5. Plugins

FACT, source https://code.claude.com/docs/en/plugins-reference: a plugin can bundle skills, commands, agents, hooks, MCP servers, monitors and workflows. It cannot ship a CLAUDE.md that loads as context: "A `CLAUDE.md` at the plugin root isn't loaded as context". Instructions must go in a skill.

FACT (same page): `userConfig` lets a plugin ask the user for values on enable. Non-sensitive values are saved under `pluginConfigs` in the user `settings.json`. Hooks of the plugin receive them as `CLAUDE_PLUGIN_OPTION_<KEY>` environment variables. A string option may carry `options` (a fixed list) and `min`/`max` bounds for numbers.

INFERENCE: `userConfig` gives a typed, bounded, user-level knob that a plugin hook can read. It is user-scope only, so it does not give a group or repo level by itself. It does give validation (a `number` with `min` and `max` is a built-in floor and ceiling). UNTESTED: whether the value can also be set in project settings (the page says `pluginConfigs` is read from "settings files" listed on the settings reference page; we did not read that list).

### F6. How the audit reads config, and the hole in it

FACT: `_declared_command(worktree)` reads `.claude/CLAUDE.md`, `CLAUDE.md` and `AGENTS.md` from the worktree path that the audit receives (`hooks/workflow-audit/audit`, lines 126-127 and 840-855). The worktree is the branch under audit.

INFERENCE: a branch can change its own declared test command, and the audit will accept the new one. For a test command this is intended (a repo owns its test command). For a safety knob it is a hole: a change in the same PR would weaken the check that judges the PR. Any new config file must be read from the base branch (the PR target), or from a path outside the repo, not from the audited tree. The audit already receives `--base <PR target>`, so a read of `git show origin/<base>:<path>` is possible. UNTESTED.

### F7. Safety rules that must not be tunable

INFERENCE, from sections 0, 6, 8, 13 and 16 of the user instructions file and the hooks listed in F1. These protect the owner from a weakened workflow:
- Every workflow agent runs on Sonnet (audit S7 and the forked-skills hook).
- Subagents never write remote state (the subagent-readonly hook).
- A PR needs a passing audit record (the PR gate in the audit hooks).
- No recursive delete; secrets redaction; branch name rules.
- Blocking findings need quoted evidence (audit L1).
- A cap extension needs the owner's own words (audit S5).

Tunable (INFERENCE): test command; worker limit (down only); notification channel; which of the optional steps a docs-only change skips; the `small task` line count; the model of non-audited helper roles outside the workflow (if the owner decides).

### F8. Prior research that bears on this

FACT, sources in `docs/research/`: `orca-inbox-haiku.md` finds Haiku is not safe as the only review gate and keeps workers on Sonnet. So a "model per role" knob has little room today: the safe value is Sonnet for every audited role. `agent-workflow-comparison.md` (proposals P1 to P8) lists step-skipping ideas (P3 sizes the steps by checkable facts; P5 limits the verifier). These are the main reasons for a "which steps run" knob. `orca-inbox-tests.md` and `orca-inbox-load.md` bear on the worker limit and test command knobs. We did not re-read them for this ticket beyond their summaries.

## 4. Existing tools and what they cover

| Need | Existing thing | Covers? |
| --- | --- | --- |
| User and repo scopes for tool settings | Claude Code settings files and precedence (F2) | Yes for tool settings (model, permissions, hooks, env). Not for workflow knobs, because only the audit reads those. |
| Group scope | None native | No. Build from `--settings` injection by the launcher, or shared files plus `@import` or symlinks (F2, F3). UNTESTED. |
| Layered instructions | CLAUDE.md layering, `.claude/rules/`, `@import` (F3) | Layering yes. Exact override no ("may pick one arbitrarily"). |
| A lock that a repo cannot lift | Managed settings, `allowManagedHooksOnly`, `allowManagedPermissionRulesOnly`, managed CLAUDE.md (F2, F3, F4) | Yes. Cost: a system-level file that also applies to the owner's own sessions; it needs a privileged write. |
| Floors and ceilings for a value | A `userConfig` number with `min` and `max`; `maxEffortLevel` (lowest cap wins, from any scope) (F2, F5) | Only for those keys. The settings page shows the pattern "stricter value wins" for about a dozen keys (its "Exceptions" table). It is not a general feature. |
| Hook reads a config | Nothing ready-made; the hook reads a file | No. Each hook (or one shared reader module) must do it. |
| Typed config with validation | `claude plugin validate`, JSON schema for settings | For settings and plugin manifests only. |
| Workflow-level config tools (Open source) | Our earlier survey (`orca-inbox-oss.md`) found no project that covers a per-level workflow configuration. We did not run a new open-source search for this ticket. | UNTESTED for this ticket. |

## 5. Options for the owner

These are not ranked. Each has a cost.

**O1. Keep the text as it is; move nothing.**
Config stays prose in the global file, and caps stay constants. Cost: no group or repo level exists. A repo that needs a different value must change code or ask the owner each time (the current extension flow).

**O2. One small JSON file per level, read by one shared reader in the audit and the hooks.**
Files: a global file (in the tracked config repo), an optional group file, an optional repo file in the base branch. The reader merges them with a rule per key: "tighten only" (the lower level may only choose a stricter value) or "global only". Cost: one new module and tests; every hook that wants a knob must call it; a schema to keep. This matches F7: the global file holds the floors and ceilings.

**O3. Use only the native scopes plus a launcher.**
The launcher that starts coordinators passes `--settings <group file>` and per-repo values come from `.claude/settings.json`. Knobs go in custom keys of `env` (for example a `WORKFLOW_*` variable) that hooks read. Cost: custom `env` keys carry no schema or floor; a project file can set them, so a repo can weaken a knob unless the hook clamps it. Group scope depends on the launcher always being used (UNTESTED). Settings files cannot hold comments.

**O4. Managed settings for the fixed rules, files for the tunable ones.**
Put the F7 rules in a managed settings file and a managed CLAUDE.md, so no repo can lift them. Use O2 or O3 for the tunable knobs. Cost: privileged write to a system folder; the owner's own sessions are also locked, so an owner override (the `!` commands the instructions use today) needs a separate path; managed files are outside this repo and need their own sync step.

**O5. A plugin with `userConfig` for the tunable knobs.**
Typed values with `min` and `max`, read as `CLAUDE_PLUGIN_OPTION_*` by plugin hooks. Cost: user scope only, so no group or repo level; the audit lives outside the plugin today, so it would not read these values unless it reads `settings.json`.

**O6. Make only a short list of knobs configurable first.**
Start with the test command (already per repo), the small-task line count and the worker limit. Keep caps, models and the audit checks fixed (F7). Cost: cap and step variation stay manual until a second phase.

Combinations are possible (for example O2 plus O4). No option removes the need to read the repo file from the base branch (F6).

## 6. Gaps and open questions

1. UNTESTED: that `--settings` injection by a launcher reaches Orca workers and subagents. We did not start any session.
2. UNTESTED: that an `@import` in a repo CLAUDE.md of a path outside the repo loads in an Orca worktree, and passes the approval dialog for workers (no user to approve).
3. We did not read the full settings reference, so the full list of keys with their allowed scopes is not checked here. The set of keys that "never apply from a repository file" needs one pass before any design relies on it.
4. The name of the environment variable that loads CLAUDE.md of additional directories was not read in full.
5. The audit has no knob reader. How many of its 17 checks (S1 to S10, XC, L1 to L6) take a value that could vary is not counted.
6. Whether the owner wants the repo level to tighten only, or to loosen too (for example a docs-only repo with no test command). This is a decision ticket.
7. Which knob changes need an audit of their own (a PR that edits a config file should itself face the stricter of the old and new value).
8. No measurement of the cost of a config read in a hook on each tool call. INFERENCE: small for one cached JSON file; UNTESTED.

## 7. Sources read and sources that failed

Read:
- https://code.claude.com/docs/en/settings (full)
- https://code.claude.com/docs/en/memory (read through a fetch tool; the page text was saved to a file and searched by keyword; not read line by line)
- https://code.claude.com/docs/en/hooks (first 100,000 of 294,068 characters)
- https://code.claude.com/docs/en/plugins-reference (full)
- Tracked files: the user instructions file (headings and sections 6, 7, 9, 11, 15), `hooks/workflow-audit/audit` (constants, `_declared_command`, check list), `hooks/workflow-audit/audit_support.py`, `hooks/workflow-audit/auditor-brief.md`, the hook folders list, and the key names of the owner's user settings file.
- Prior research: `docs/research/orca-inbox-haiku.md` (full), `docs/research/agent-workflow-comparison.md` and `docs/research/orca-inbox-orca.md` (headings only).

Failed or not read:
- https://code.claude.com/docs/en/settings-reference (not fetched).
- https://code.claude.com/docs/en/managed-settings (not fetched; managed facts come from the settings page).
- The last 194,068 characters of the hooks page.
- `docs/research/orca-inbox-oss.md`, `orca-inbox-load.md`, `orca-inbox-tests.md`, `orca-inbox-reliab.md` and the sandbox research doc were not read for this ticket.
