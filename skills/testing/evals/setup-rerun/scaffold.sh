#!/usr/bin/env bash
# Copies the fixture repo into the empty workspace and makes it a git repo. Run by plugin eval with --scaffold.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
cp -r "$here/repo/." .
git init -q
