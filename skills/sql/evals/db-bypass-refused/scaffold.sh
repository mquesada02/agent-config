#!/usr/bin/env bash
# Copies the fixture repo into the run's working folder (the scaffold runs there) and writes the database files
# (service file, password file, allowlist) under the run's HOME. It starts no container.
set -eu
python3 "$(dirname "$0")/../db/db_eval.py" scaffold --case "$(dirname "$0")"
