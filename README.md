# agent-config

My personal [Claude Code](https://claude.com/claude-code) configuration: global
rules, skills, hooks, and settings. The repository is the `~/.claude` folder
itself.

## What is tracked

The `.gitignore` file ignores everything and then allows these files:

| Path | What it is |
|---|---|
| `CLAUDE.md` | Global rules that Claude Code reads in every session |
| `settings.json` | Claude Code settings: plugins, permissions, hooks, output style |
| `hooks/force-model-invocation.sh` | Startup hook: keeps plugin and claude.ai skills model-invocable after updates |
| `scripts/update-orca-skills.sh` | Updates the Orca skills to a pinned commit, on request |
| `skills/*/SKILL.md` | My skills (see [Third-party content](#third-party-content)) |
| `README.md`, `LICENSE`, `THIRD_PARTY_NOTICES.md` | This file and the license texts |

Everything else stays local. This includes session logs, credentials, caches,
other hook scripts, and `skills/synced/` (skills that claude.ai syncs).

## Set up on a new machine

1. Install Claude Code, then move any existing `~/.claude` folder out of the way.
2. Clone this repository as `~/.claude`:

   ```bash
   git clone git@github.com:mquesada02/agent-config.git ~/.claude
   ```

3. Install the tools that the settings and hooks use:
   - [Orca](https://github.com/stablyai/orca). The `CLAUDE.md` rules use it for
     worktrees and task delegation, and it installs its own hooks.
   - [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp). Its
     installer creates the `hooks/cbm-*` scripts that `settings.json` runs.
   - Node.js, for the status line, which runs through `npx`.
   - bash 4.4 or newer, git 2.32 or newer, `tar`, `grep`, `awk` and GNU coreutils
     (for `sort -V`). The hooks and the update script use them.
4. Start Claude Code and run `/plugin` to install any plugin from
   `enabledPlugins` that is missing.

## Update the Orca skills

The Orca skills are pinned to one stablyai/orca commit. Nothing downloads them
automatically. To update them:

1. Pick a new commit on https://github.com/stablyai/orca and copy its full SHA.
2. Run `~/.claude/scripts/update-orca-skills.sh <SHA>`.
3. Review `git -C ~/.claude diff HEAD -- skills/`.
4. Commit only if the changes look right, and name the Orca commit in the message.

To reject an update instead, return each skill folder to the last commit:
`git -C ~/.claude restore --staged --worktree --source=HEAD -- skills/<name>`.
This also removes the files that the update added. The script can download
them again.

The script uses only git: it downloads that one commit into a temporary folder
and swaps the three skill folders only after all of them downloaded. The
previous folders stay in that temporary folder, in `/tmp`.

## Safety notes

- Never put secrets (API keys, tokens) in `settings.json`, for example in an
  `env` block. The file is committed. Use your shell environment instead.
- Never commit `skills/synced/`. claude.ai re-syncs it, and it can contain
  skills that an organization shares.
- Claude Code and Orca rewrite `settings.json`. Review the diff before you
  commit it.

## Third-party content

These files are copies of content from other projects. They keep their original
licenses, and the license of this repository does not cover them. The full
license texts are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

| File | Source | License |
|---|---|---|
| `CLAUDE.md`, sections 1 to 4 | [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) | MIT (stated in its README) |
| `skills/computer-use` | [stablyai/orca](https://github.com/stablyai/orca) | MIT |
| `skills/orca-cli` | [stablyai/orca](https://github.com/stablyai/orca) | MIT |
| `skills/orchestration` | [stablyai/orca](https://github.com/stablyai/orca) | MIT |
| `skills/codebase-memory` | [DeusData/codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) | MIT |

## License

[MIT](LICENSE), for my own files only. See [Third-party content](#third-party-content)
for the files that it does not cover.
