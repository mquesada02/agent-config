#!/usr/bin/env bash
# Copies the fixture repo into the empty workspace. Run by plugin eval with --scaffold.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
cp -r "$here/repo/." .
npm install --no-audit --no-fund --silent
git init -q
git add -A
git -c user.name=x -c user.email=x@example.invalid commit -q -m fixture
