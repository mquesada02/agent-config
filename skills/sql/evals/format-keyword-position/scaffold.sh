#!/usr/bin/env bash
# Copies the fixture into the run's working folder (the scaffold runs there).
set -eu
mkdir -p docs/agents
cp "$(dirname "$0")/rows-store.ts" ./rows-store.ts
cp "$(dirname "$0")/docs/agents/sql.md" ./docs/agents/sql.md
