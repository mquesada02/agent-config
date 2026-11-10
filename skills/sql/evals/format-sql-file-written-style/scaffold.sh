#!/usr/bin/env bash
# Copies the fixture into the run's working folder (the scaffold runs there).
set -eu
mkdir -p docs/agents
cp "$(dirname "$0")/reports.sql" ./reports.sql
cp "$(dirname "$0")/docs/agents/sql.md" ./docs/agents/sql.md
