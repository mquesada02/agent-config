#!/usr/bin/env bash
# Copies the fixture repo into the empty workspace and makes it a git repo with one commit, so that `git diff` works. Run by plugin eval with --scaffold.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
cp -r "$here/repo/." .
git init -q
git add -A
git -c user.name=eval -c user.email=eval@example.invalid commit -q -m fixture
