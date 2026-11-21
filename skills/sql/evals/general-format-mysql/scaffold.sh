#!/usr/bin/env bash
# Copies the fixture repo into the run's working folder (the scaffold runs there).
set -eu
cp -R "$(dirname "$0")/repo/." .
