#!/usr/bin/env bash
# Fail unless staging has a successful deployment of this commit.
# Usage: check-staged.sh <sha>   (needs GITHUB_REPOSITORY and a token that can read deployments)
set -euo pipefail

sha="${1:-}"
repo="${GITHUB_REPOSITORY:-}"
if [ -z "$sha" ] || [ -z "$repo" ]; then
  echo "::error::The commit SHA and GITHUB_REPOSITORY must be set, so the staging check cannot run"
  exit 1
fi

ids="$(gh api "repos/$repo/deployments?sha=$sha&environment=staging" --jq '.[].id')"
for id in $ids; do
  state="$(gh api "repos/$repo/deployments/$id/statuses" --jq '.[0].state')"
  if [ "$state" = "success" ]; then
    exit 0
  fi
done
echo "::error::No successful staging deploy of $sha"
exit 1
