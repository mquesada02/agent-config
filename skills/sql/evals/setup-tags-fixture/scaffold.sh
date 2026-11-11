#!/usr/bin/env bash
# Copies the fixture repo into the run's working folder (the scaffold runs there), makes it a git repo with
# an origin remote, and writes a PG service file with the section [app-dev] under the run's HOME. It starts no
# container, installs nothing and refuses to run with the real HOME or the real XDG config folder.
set -eu
case_dir="$(dirname "$0")"
real_home="$(realpath -m -- "$(python3 -c 'import os, pwd; print(pwd.getpwuid(os.getuid()).pw_dir)')")"
config_base="${XDG_CONFIG_HOME:-${HOME:-}/.config}"
for folder in "${HOME:-}" "$config_base"; do
  # Compare resolved paths: a symlink or a dot-dot path to the real home must not pass.
  if [ -n "$folder" ]; then folder="$(realpath -m -- "$folder")"; fi
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
