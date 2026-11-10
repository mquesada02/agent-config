#!/usr/bin/env bash
# Copies the fixture repo (with its existing rules file) into the run's working folder (the scaffold runs there),
# makes it a git repo with an origin remote, and writes a PG service file with the section [app-dev] under the
# run's HOME and an allowlist with the service app-dev for the repo key under the run's XDG config folder. It starts
# no container, installs nothing and refuses to run with the real HOME or the real XDG config folder.
set -eu
case_dir="$(dirname "$0")"
real_home="$(python3 -c 'import os, pwd; print(pwd.getpwuid(os.getuid()).pw_dir)')"
config_base="${XDG_CONFIG_HOME:-${HOME:-}/.config}"
for folder in "${HOME:-}" "$config_base"; do
  case "$folder" in
    "" | "$real_home" | "$real_home"/*)
      echo "refusing to run: HOME or XDG_CONFIG_HOME is unset or is the real home folder" >&2
      exit 1
      ;;
  esac
done
cp -R "$case_dir/repo/." .
git init -q
git remote add origin https://example.com/acme/shop.git
printf '[app-dev]\nhost=localhost\nport=5432\ndbname=app\nuser=app_reader\n' > "$HOME/.pg_service.conf"
mkdir -p "$config_base/sql-skill"
printf '["example.com/acme/shop"]\nservices = ["app-dev"]\n' > "$config_base/sql-skill/allowlist.toml"
