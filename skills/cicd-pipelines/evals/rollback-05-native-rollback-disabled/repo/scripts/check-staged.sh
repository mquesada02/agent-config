#!/usr/bin/env bash
set -euo pipefail
sha="$1"
count="$(gh api "repos/$GITHUB_REPOSITORY/deployments?sha=$sha&environment=staging" --jq 'length')"
test "$count" -gt 0 || { echo "::error::Staging has no deployment of $sha"; exit 1; }
