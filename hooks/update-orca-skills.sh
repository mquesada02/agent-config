#!/usr/bin/env bash
# Refresh the Orca skills (computer-use, orca-cli, orchestration) copied into
# ~/.claude/skills once a day, retrying hourly after a failure. `npx skills
# update` would turn the copies back into links to ~/.agents/skills, so this
# re-runs the copy install instead.
# Registered as an async SessionStart hook, so it never delays a session.
# Trust: installs whatever stablyai/orca's default branch holds, unpinned.
exec >/dev/null 2>&1
stamp="$HOME/.claude/.orca-skills-updated"
fresh() { [ -n "$(find "$stamp" -mmin -1440)" ]; }
fresh && exit 0
exec 9>"$stamp.lock"
flock -n 9 || exit 0  # another session is already refreshing
fresh && exit 0
# Run from $HOME so a project's .npmrc can't redirect the download.
if cd "$HOME" &&
  timeout 300 npx --yes skills add https://github.com/stablyai/orca \
    --skill computer-use --skill orca-cli --skill orchestration \
    --global --agent claude-code --copy -y; then
  touch "$stamp"
else
  touch -d '23 hours ago' "$stamp"  # retry in about an hour
fi
exit 0
