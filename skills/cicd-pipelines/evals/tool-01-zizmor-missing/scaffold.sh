#!/usr/bin/env bash
# Copies the fixture repo into the empty workspace. Run by plugin eval with --scaffold.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
cp -r "$here/repo/." .
