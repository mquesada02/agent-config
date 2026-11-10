#!/usr/bin/env python3
"""Read the user-local database allowlist of a repo and print one JSON object.

Usage: python3 allowlist.py <repo root> [--check-services]

The allowlist file is `$XDG_CONFIG_HOME/sql-skill/allowlist.toml` (an empty or
relative `XDG_CONFIG_HOME` counts as unset: `~/.config/sql-skill/allowlist.toml`).
The key is the normalized URL of the remote `origin`; with no `origin`, the
absolute git common dir as git prints it. Needs Python 3.11 or newer (tomllib).

With access the output has `access` true, `key`, `services` and `timeouts`
(service name to its override object). With no access it has `access` false,
`key`, `services` [], `timeouts` {} and `reason` (`no_repo`, `missing_file`,
`unreadable_file`, `malformed_file` or `no_entry`); `malformed_file` adds
`detail`. `--check-services` adds `service_check`: the service file is read for
`[name]` header lines only (never any value), and the password file is never
opened.

Exit code: 0 for every result, 2 for a usage error (one line on stderr).
"""
import json
import os
import re
import subprocess
import sys
import tomllib

SERVICE_NAME = re.compile(r"[A-Za-z0-9_.-]+")
TIMEOUT_VALUE = re.compile(r"([0-9]+)(?:ms|s|min|h|d)?")
TIMEOUT_KEYS = (
    "statement_timeout",
    "lock_timeout",
    "idle_in_transaction_session_timeout",
    "transaction_timeout",
)
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://(.*)$", re.S)
BRACKET_HOST = re.compile(r"^(\[[^\]]*\])(?::[0-9]*)?$")
HEADER = re.compile(r"^\s*\[(.+)\]\s*$")


class Malformed(Exception):
    pass


def normalize(url):
    """The key of a remote URL (story 25): lowercase host; no scheme, user info or port;
    scp form `host:path` as `host/path`; no trailing `.git` or `/`."""
    url = url.strip()
    scheme = SCHEME.match(url)
    if scheme:
        host_part, _, path = scheme.group(1).partition("/")
    elif not url.startswith("/") and ":" in url.split("/", 1)[0]:
        host_part, _, path = url.partition(":")
    else:
        return strip_suffixes(url)
    host_part = host_part.rsplit("@", 1)[-1]
    bracket = BRACKET_HOST.match(host_part)
    host = bracket.group(1) if bracket else re.sub(r":[0-9]*$", "", host_part)
    host = host.lower()
    path = path.lstrip("/")
    return strip_suffixes(f"{host}/{path}" if host else f"/{path}")


def strip_suffixes(key):
    while True:
        new = key.rstrip("/")
        if new.endswith(".git"):
            new = new[: -len(".git")]
        if new == key:
            return key
        key = new


def git(repo, *args):
    # surrogateescape: a path or URL with a byte that is not UTF-8 must not raise
    try:
        done = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, errors="surrogateescape")
    except OSError:  # git is not installed: the key cannot be computed
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def repo_key(repo):
    """The key of the repo, or None when the folder is not a git repo."""
    common = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common:
        return None
    origin = git(repo, "remote", "get-url", "origin")
    return normalize(origin) if origin else common


def allowlist_path():
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    base = xdg if xdg and os.path.isabs(xdg) else os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "sql-skill", "allowlist.toml")


def check_timeout(service, name, value):
    if name not in TIMEOUT_KEYS:
        raise Malformed(f"timeouts.{service}: unknown timeout {name!r}")
    match = TIMEOUT_VALUE.fullmatch(value) if isinstance(value, str) else None
    if not match or not match.group(1).strip("0"):  # no int(): a huge digit string raises ValueError
        raise Malformed(f"timeouts.{service}.{name}: not a timeout like 30s (zero is not allowed)")


def validate(entry):
    """The services and the timeout overrides of a repo entry, or Malformed."""
    if not isinstance(entry, dict):
        raise Malformed("the entry of the repo key is not a table")
    unknown = sorted(set(entry) - {"services", "timeouts"})
    if unknown:
        raise Malformed(f"unknown key in the entry: {', '.join(map(repr, unknown))}")
    services = entry.get("services")
    if not isinstance(services, list) or not all(
        isinstance(s, str) and SERVICE_NAME.fullmatch(s) for s in services
    ):
        raise Malformed("services must be a list of names made of letters, digits, _ . -")
    timeouts = entry.get("timeouts", {})
    if not isinstance(timeouts, dict):
        raise Malformed("timeouts must be a table")
    for service, overrides in timeouts.items():
        if not isinstance(overrides, dict):
            raise Malformed(f"timeouts.{service} must be a table")
        for name, value in overrides.items():
            check_timeout(service, name, value)
    return services, {s: timeouts[s] for s in services if s in timeouts}


def no_access(key, reason, detail=None):
    result = {"access": False, "key": key, "services": [], "timeouts": {}, "reason": reason}
    if detail:
        result["detail"] = detail
    return result


def read_allowlist(repo):
    key = repo_key(repo)
    if key is None:
        return no_access(None, "no_repo")
    try:
        with open(allowlist_path(), "rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        return no_access(key, "missing_file")
    except OSError:
        return no_access(key, "unreadable_file")
    except ValueError as error:  # TOMLDecodeError and UnicodeDecodeError
        return no_access(key, "malformed_file", str(error))
    except RecursionError:  # a deeply nested file
        return no_access(key, "malformed_file", "the file is nested too deeply")
    if key not in data:
        return no_access(key, "no_entry")
    try:
        services, timeouts = validate(data[key])
    except Malformed as error:
        return no_access(key, "malformed_file", str(error))
    return {"access": True, "key": key, "services": services, "timeouts": timeouts}


def check_services(services):
    """Which of `services` have no `[name]` header in the PG service file (names only)."""
    path = os.environ.get("PGSERVICEFILE") or os.path.join(os.path.expanduser("~"), ".pg_service.conf")
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            headers = {m.group(1) for m in map(HEADER.match, handle) if m}
    except FileNotFoundError:
        return {"service_file": "missing", "missing": list(services)}
    except OSError:
        return {"service_file": "unreadable", "missing": list(services)}
    return {"service_file": "found", "missing": [s for s in services if s not in headers]}


def main(argv):
    arguments = [a for a in argv if a != "--check-services"]
    if len(arguments) != 1 or arguments[0].startswith("-"):
        print("usage: allowlist.py <repo root> [--check-services]", file=sys.stderr)
        return 2
    result = read_allowlist(arguments[0])
    if "--check-services" in argv:
        result["service_check"] = check_services(result["services"])
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
