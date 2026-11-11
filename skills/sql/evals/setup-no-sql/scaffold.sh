#!/usr/bin/env bash
# Copies the fixture repo (no SQL) into the run's working folder (the scaffold runs there) and makes it a git
# repo with an origin remote. It writes nothing else, starts no container and installs nothing.
set -eu
case_dir="$(dirname "$0")"
cp -R "$case_dir/repo/." .
git init -q
git remote add origin https://example.com/acme/shop.git
