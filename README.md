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
| `hooks/update-orca-skills.sh` | Startup hook: refreshes the Orca skills once a day |
| `skills/*/SKILL.md` | My skills (see [Third-party skills](#third-party-skills)) |

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
   - Node.js (for `npx`), plus `flock`, `grep`, `awk` and `timeout` (on Linux,
     these are in util-linux and coreutils).
4. Start Claude Code and run `/plugin` to install any plugin from
   `enabledPlugins` that is missing.

## Safety notes

- Never put secrets (API keys, tokens) in `settings.json`, for example in an
  `env` block. The file is committed. Use your shell environment instead.
- Never commit `skills/synced/`. claude.ai re-syncs it, and it can contain
  skills that an organization shares.
- Claude Code and Orca rewrite `settings.json`. Review the diff before you
  commit it.

## Third-party skills

These skills are copies of files from other projects. They keep their original
licenses, and the license of this repository does not cover them:

| Skill | Source | License |
|---|---|---|
| `skills/computer-use` | [stablyai/orca](https://github.com/stablyai/orca) | MIT |
| `skills/orca-cli` | [stablyai/orca](https://github.com/stablyai/orca) | MIT |
| `skills/orchestration` | [stablyai/orca](https://github.com/stablyai/orca) | MIT |
| `skills/codebase-memory` | [DeusData/codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) | MIT |

## License

[MIT](LICENSE), for my own files only. See [Third-party skills](#third-party-skills)
for the files that it does not cover.
