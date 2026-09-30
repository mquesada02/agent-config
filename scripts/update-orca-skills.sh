#!/usr/bin/env bash
# Update the Orca skills (computer-use, orca-cli, orchestration) in
# ~/.claude/skills to one stablyai/orca commit. Run it by hand: nothing
# downloads automatically. It does not commit; review `git diff HEAD`, then commit.
#
# Only git runs: no npm package is involved. The commit must be a full SHA,
# because branches and tags can move.
#
# Usage: ~/.claude/scripts/update-orca-skills.sh <40-character commit SHA>
set -euo pipefail

ORCA_URL=https://github.com/stablyai/orca.git
SKILLS=(computer-use orca-cli orchestration)
REPO="$HOME/.claude"

die() { echo "error: $*" >&2; exit 1; }

ref=${1:-}
if (( $# != 1 )) || [[ ! $ref =~ ^[0-9a-f]{40}$ ]]; then
  echo "usage: $0 <full 40-character stablyai/orca commit SHA>" >&2
  exit 2
fi

# `mapfile -d` below needs bash 4.4.
if (( BASH_VERSINFO[0] < 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] < 4) )); then
  die "bash >= 4.4 is required, but this is bash $BASH_VERSION"
fi
# GIT_CONFIG_GLOBAL below needs git 2.32; older git would silently ignore it.
git_version=$(git --version | awk '{print $3}')
if [[ $(printf '%s\n' 2.32.0 "$git_version" | sort -V | head -n1) != 2.32.0 ]]; then
  die "git >= 2.32 is required, but this is git $git_version"
fi

paths=("${SKILLS[@]/#/skills/}")
# The update replaces these folders, so uncommitted edits there would be lost.
changes=$(git -C "$REPO" status --porcelain -- "${paths[@]}")
[[ -z $changes ]] || die "uncommitted changes in ${paths[*]}. Commit or restore them first:
$changes"

# Download the commit into a temporary folder. Nothing in $REPO changes until
# every skill folder is there. Ignore global and system git config, so a
# `url.*.insteadOf` rule cannot redirect the download. The folder is in /tmp,
# which the system clears.
tmp=$(mktemp -d)
(
  export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
  git -C "$tmp" init -q
  git -C "$tmp" fetch -q --depth 1 --filter=blob:none "$ORCA_URL" "$ref"
  [[ $(git -C "$tmp" rev-parse FETCH_HEAD) == "$ref" ]] || die "fetched commit is not $ref"
  for p in "${paths[@]}"; do
    git -C "$tmp" cat-file -e "FETCH_HEAD:$p/SKILL.md" 2>/dev/null || die "commit $ref has no $p/SKILL.md"
  done
  mkdir "$tmp/new"
  git -C "$tmp" archive FETCH_HEAD -- "${paths[@]}" | tar -x -C "$tmp/new"
)

# Swap the folders. The old ones move to $tmp/old instead of being deleted.
warn_mixed() {
  echo "Update failed: the skills may be mixed. Check: git -C $REPO status -- ${paths[*]}" >&2
}
trap warn_mixed ERR
trap 'warn_mixed; exit 130' INT TERM
mkdir -p "$tmp/old/skills" "$REPO/skills"
for p in "${paths[@]}"; do
  if [[ -e $REPO/$p || -L $REPO/$p ]]; then mv "$REPO/$p" "$tmp/old/$p"; fi
  mv "$tmp/new/$p" "$REPO/$p"
done
trap - ERR INT TERM  # the swap is complete; later failures are not "mixed"

# Mark only untracked files as intent-to-add (this stages no content), then diff
# against HEAD so new, changed and deleted files all show.
# Write to a file first: a failure inside `< <(...)` would be invisible to `set -e`.
git -C "$REPO" ls-files -z --others --exclude-standard -- "${paths[@]}" > "$tmp/untracked"
mapfile -d '' -t new_files < "$tmp/untracked"
if (( ${#new_files[@]} )); then
  git -C "$REPO" add --intent-to-add -- "${new_files[@]}"
fi
echo
git -C "$REPO" diff HEAD --stat -- "${paths[@]}"
echo "Review: git -C $REPO diff HEAD -- ${paths[*]}"
if (( ${#new_files[@]} )); then
  echo "New files are marked intent-to-add (nothing is staged): ${new_files[*]}"
fi
echo "Then commit, and name Orca commit $ref in the message."
echo "The previous skill folders are in $tmp/old until the system clears /tmp."
