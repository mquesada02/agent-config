#!/usr/bin/env bash
# Copies the fixture into the run's working folder (the scaffold runs there).
set -eu
cp "$(dirname "$0")/notes-store.ts" ./notes-store.ts
