#!/usr/bin/env bash
# Copies the fixture into the run's working folder (the scaffold runs there) and installs the
# pinned formatter packages there. Nothing is installed globally or in the real HOME.
set -eu
source_dir="$(dirname "$0")"
mkdir -p docs/agents
cp "$source_dir/reports.sql" ./reports.sql
cp "$source_dir/.prettierrc.json" ./.prettierrc.json
cp "$source_dir/package.json" ./package.json
cp "$source_dir/package-lock.json" ./package-lock.json
cp "$source_dir/docs/agents/sql.md" ./docs/agents/sql.md
# The formatter packages are devDependencies. A shell with NODE_ENV=production makes `npm ci`
# skip them and still exit 0, so ask for them with --include=dev. Check the install, retry
# twice, and fail the run loudly when the tool is missing.
for attempt in 1 2 3; do
  npm ci --include=dev --cache "$PWD/.npm-cache" --no-audit --no-fund --ignore-scripts
  if [ -x node_modules/.bin/prettier ]; then
    exit 0
  fi
done
echo "the formatter install failed: node_modules/.bin/prettier is missing" >&2
exit 1
