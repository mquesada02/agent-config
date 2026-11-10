#!/usr/bin/env python3
"""The only path of the sql skill to a database: `pg_run explain` for one SELECT, and `pg_run facts`.

Usage: python3 pg_run.py explain --repo <repo root> --service <name> --mode select [--statement <sql>]
       python3 pg_run.py facts --repo <repo root> --service <name> --names <table.column> [<table.column> ...]

With no `--statement` the statement is read from stdin. The order of work: the
allowlist check (`allowlist.py`), the select guard (`sql_guard.py`), the server
version probe, then the explain run: `psql -X -w` with `service=<name>` and the
session options in the conninfo, `BEGIN READ ONLY`, `EXPLAIN (ANALYZE ...
FORMAT JSON)`, `ROLLBACK`. It prints one JSON object. Every error text is
redacted: the output has no key that holds raw `psql` text.

`facts` takes no statement. It checks the allowlist, probes the version, and runs one fixed catalog query
in one read-only transaction (a script on stdin). The names (`table.column` or `schema.table.column`) reach
the server only as the value of a psql variable. It prints the nullability and the type of each column,
or `missing`: catalog metadata only. A name of another shape, or with a character that is not printable
ASCII, is `missing` and is never sent; when no name is sent there is no `psql` call at all.

Exit code: 0 when `ok` is true, 1 when `ok` is false, 2 for a usage error (one
line on stderr, nothing on stdout). Needs Python 3.11 or newer (tomllib).
"""
import argparse
import json
import os
import re
import string
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import allowlist  # noqa: E402
import sql_guard  # noqa: E402

DEFAULT_TIMEOUTS = (
    ("statement_timeout", "30s"),
    ("lock_timeout", "2s"),
    ("idle_in_transaction_session_timeout", "10s"),
    ("transaction_timeout", "60s"),
)
TRANSACTION_TIMEOUT_VERSION = 170000
EXPLICIT_BUFFERS_BELOW = 180000
CONNECT_TIMEOUT = "10"
DROPPED_ENV = (
    "PGPASSWORD", "PGSERVICE", "PGOPTIONS", "PGHOST", "PGHOSTADDR", "PGPORT", "PGUSER", "PGDATABASE",
    "LANGUAGE", "LC_MESSAGES", "LANG",
)
MESSAGE_LIMIT = 2000

# Redaction. A placeholder stands for the service name until the last step, so that a
# service named like an object word cannot change how a later quote is read.
PLACEHOLDER = "\x00"
# The lookbehind makes a match start only at the start of a run of scheme characters, so a long run is
# scanned once. The whole run before `://` is replaced (also a digit or a sign before the scheme).
URI = re.compile(r"(?<![A-Za-z0-9+.-])[A-Za-z0-9+.-]*://\S*")
CONNINFO_KEYS = (
    "host", "hostaddr", "port", "user", "dbname", "password", "passfile", "service", "options",
    "sslcert", "sslkey", "sslrootcert", "sslcrl",
)
ASSIGNMENT = re.compile(
    r"\b(?:" + "|".join(CONNINFO_KEYS) + r")\b[ \t]*=[ \t]*(?:'(?:\\.|[^'\\])*(?:'|$)|\"(?:\\.|[^\"\\])*(?:\"|$)|\S+)", re.IGNORECASE
)
ADDRESS = re.compile(r"\((?:\d{1,3}(?:\.\d{1,3}){3}|[0-9A-Fa-f]*:[0-9A-Fa-f:.]*(?:%[^)\s]*)?)\)")
PORT_DIGITS = re.compile(r"(\bport[ \t]+)\d+", re.IGNORECASE)
QUOTED = re.compile(r'"[^"\n]*(?:"|$)')
OBJECT_WORDS = frozenset(
    "relation table column function type schema sequence index view constraint operator alias".split()
)
BLOCK_PREFIXES = ("LINE ", "HINT:", "DETAIL:", "CONTEXT:", "QUERY:")


def redact(text, service):
    """`text` with every connection value replaced by the service name."""
    lines = []
    in_block = False
    for line in text.split("\n"):
        if line.startswith("ERROR:"):
            in_block = True
        elif in_block and not (not line.strip() or line[0] in " \t" or line.startswith(BLOCK_PREFIXES)):
            in_block = False
        line = URI.sub(PLACEHOLDER, line)
        line = ASSIGNMENT.sub(PLACEHOLDER, line)
        line = ADDRESS.sub(PLACEHOLDER, line)
        line = PORT_DIGITS.sub(lambda match: match.group(1) + PLACEHOLDER, line)
        if not (in_block and line.startswith("LINE ")):
            line = QUOTED.sub(lambda match: quoted_text(line, match, in_block), line)
        lines.append(line)
    return "\n".join(lines).replace(PLACEHOLDER, service)


def quoted_text(line, match, in_block):
    """The text for one double-quoted part of `line`: itself when it names an object of the user's query."""
    if in_block and word_before(line, match.start()).lower() in OBJECT_WORDS:
        return match.group()
    return PLACEHOLDER


def word_before(line, end):
    """The run of ASCII letters that ends at `end` (blanks skipped), found backwards so that it costs only its length."""
    while end and line[end - 1].isspace():
        end -= 1
    start = end
    while start and line[start - 1] in string.ascii_letters:
        start -= 1
    return line[start:end]


def session_options(version, overrides):
    """The `-c` options and the timeouts sent. `version` None means the probe (no `transaction_timeout`)."""
    timeouts = {}
    for name, default in DEFAULT_TIMEOUTS:
        if name == "transaction_timeout" and (version is None or version < TRANSACTION_TIMEOUT_VERSION):
            continue
        timeouts[name] = overrides.get(name, default)
    flags = ["default_transaction_read_only=on", "standard_conforming_strings=on"]
    flags += [f"{name}={value}" for name, value in timeouts.items()]
    return " ".join(f"-c {flag}" for flag in flags), timeouts


def psql_env():
    env = {name: value for name, value in os.environ.items() if name not in DROPPED_ENV}
    env["PGCONNECT_TIMEOUT"] = CONNECT_TIMEOUT
    env["LC_ALL"] = "C"  # the redaction reads English messages and ASCII quotes only
    return env


class Failure(Exception):
    """A failed step; `result` is the final JSON result of the run."""

    def __init__(self, result):
        super().__init__(result["error"])
        self.result = result


def run_psql(service, options, flags, commands, stdin=None):
    """Stdout of one `psql` run, or a Failure with the redacted error. `stdin` is the script of a run with no `-c`."""
    argv = ["psql", "-X", "-w", *flags]
    for command in commands:
        argv += ["-c", command]
    argv.append(f"service={service} options='{options}'")
    try:
        done = subprocess.run(argv, capture_output=True, text=True, errors="replace", env=psql_env(), input=stdin)
    except FileNotFoundError:
        raise Failure({"ok": False, "error": "psql_failed", "message": "psql was not found on PATH"})
    except (OSError, ValueError):  # ValueError: a NUL byte in an argument
        raise Failure({"ok": False, "error": "psql_failed", "message": "psql could not be run"})
    if done.returncode == 0:
        return done.stdout
    if done.returncode == 2:
        kind = "connection_failed"
    elif re.search(r"^ERROR:", done.stderr, re.MULTILINE):
        kind = "statement_failed"
    else:
        kind = "psql_failed"
    message = redact(done.stderr, service)[:MESSAGE_LIMIT]
    raise Failure({"ok": False, "error": kind, "message": message})


def bad_output(message):
    return Failure({"ok": False, "error": "bad_output", "message": message})


def server_version(service, overrides):
    """The server version number, from a read-only probe session with the base timeouts."""
    probe_options, _ = session_options(None, overrides)
    probe = run_psql(service, probe_options, ["-At", "-q", "-v", "ON_ERROR_STOP=1"], ["SHOW server_version_num"])
    if not re.fullmatch(r"\d{1,9}", probe.strip()):
        raise bad_output("The server version number is not an integer.")
    return int(probe.strip())


def explain(service, statement, overrides):
    version = server_version(service, overrides)
    options, timeouts = session_options(version, overrides)
    buffers = "ANALYZE, BUFFERS" if version < EXPLICIT_BUFFERS_BELOW else "ANALYZE"
    out = run_psql(
        service, options, ["-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"],
        ["BEGIN READ ONLY", f"EXPLAIN ({buffers}, FORMAT JSON) {statement}", "ROLLBACK"],
    )
    try:
        plan = json.loads(out)
    except (ValueError, RecursionError):  # not JSON, or nested too deeply
        plan = None
    if not isinstance(plan, list):
        raise bad_output("The explain run did not return one JSON plan list.")
    return {
        "ok": True, "action": "explain", "service": service, "mode": "select",
        "server_version_num": version, "ran": "analyze", "reason": "select mode always analyzes",
        "timeouts": timeouts, "warnings": [], "plan": plan,
    }


def check_allowed(args):
    """(access, None) when the service is allowlisted, else (None, the `not_allowed` result)."""
    access = allowlist.read_allowlist(args.repo)
    if not access["access"]:
        return None, {"ok": False, "error": "not_allowed", "reason": access["reason"]}
    if args.service not in access["services"]:
        return None, {"ok": False, "error": "not_allowed", "reason": "service_not_listed"}
    return access, None


# The fixed catalog query of `facts`. The names reach the server only as the value of the psql variable
# `names` (a JSON array that psql quotes as a string literal), never as part of this text.
FACTS_SCRIPT = """BEGIN READ ONLY;
WITH req AS (
  SELECT (e->>0)::int AS i, e->>1 AS s, e->>2 AS t, e->>3 AS c
  FROM json_array_elements(:'names'::json) AS e
)
SELECT coalesce(json_agg(json_build_object(
  'i', req.i,
  'nullable', CASE WHEN cl.relkind IN ('v', 'm') THEN NULL ELSE NOT a.attnotnull END,
  'type', format_type(a.atttypid, a.atttypmod)
) ORDER BY req.i), '[]'::json)
FROM req
JOIN pg_class cl ON cl.relname = req.t AND cl.relkind IN ('r', 'p', 'f', 'v', 'm')
JOIN pg_namespace n ON n.oid = cl.relnamespace
JOIN pg_attribute a ON a.attrelid = cl.oid AND a.attname = req.c AND a.attnum > 0 AND NOT a.attisdropped
WHERE CASE WHEN req.s IS NULL THEN pg_table_is_visible(cl.oid) ELSE n.nspname = req.s END;
ROLLBACK;
"""


def parse_name(name):
    """(schema or None, table, column) of a `table.column` or `schema.table.column` name, else None."""
    if any(not 32 <= ord(char) <= 126 for char in name):
        return None
    parts = name.split(".")
    if len(parts) not in (2, 3) or not all(parts):
        return None
    return (parts[0] if len(parts) == 3 else None, *parts[-2:])


def fact_rows(out, count):
    """The rows of the facts query as a dict from index to its fact, or a bad_output Failure."""
    try:
        rows = json.loads(out)
    except (ValueError, RecursionError):
        rows = None
    found = {}
    if not isinstance(rows, list):
        raise bad_output("The facts run did not return one JSON list.")
    for row in rows:
        index = row.get("i") if isinstance(row, dict) else None
        if (
            type(index) is not int or not 0 <= index < count
            or row.get("nullable") not in (True, False, None) or not isinstance(row.get("type"), str)
        ):
            raise bad_output("The facts run returned a row that is not valid.")
        found[index] = {"nullable": row["nullable"], "type": row["type"]}
    return found


def facts(service, parsed, overrides):
    """The facts of the names in `parsed` (a dict name -> parts or None), from one read-only catalog run."""
    sent = list(dict.fromkeys(parts for parts in parsed.values() if parts))
    found = {}
    if sent:
        version = server_version(service, overrides)
        options, _ = session_options(version, overrides)
        payload = json.dumps([[index, *parts] for index, parts in enumerate(sent)])
        out = run_psql(
            service, options, ["-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-v", f"names={payload}"], [],
            stdin=FACTS_SCRIPT,
        )
        found = fact_rows(out, len(sent))
    index = {parts: number for number, parts in enumerate(sent)}
    return {
        "ok": True, "action": "facts", "service": service,
        "facts": {name: found.get(index.get(parts), {"missing": True}) for name, parts in parsed.items()},
    }


def run_facts(args):
    access, refusal = check_allowed(args)
    if refusal:
        return refusal
    parsed = {name: parse_name(name) for name in args.names}
    try:
        return facts(args.service, parsed, access["timeouts"].get(args.service, {}))
    except Failure as failure:
        return failure.result


def run_explain(args):
    access, refusal = check_allowed(args)
    if refusal:
        return refusal
    statement = args.statement
    if statement is None:
        statement = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    sql, refusal = sql_guard.check_select(statement)
    if refusal:
        return {"ok": False, "error": "refused", **refusal}
    try:
        return explain(args.service, sql, access["timeouts"].get(args.service, {}))
    except Failure as failure:
        return failure.result


def parser():
    top = argparse.ArgumentParser(prog="pg_run.py")
    actions = top.add_subparsers(dest="action", required=True)
    sub = actions.add_parser("explain")
    sub.add_argument("--repo", required=True)
    sub.add_argument("--service", required=True)
    sub.add_argument("--mode", required=True, choices=["select"])
    sub.add_argument("--statement")
    sub = actions.add_parser("facts")
    sub.add_argument("--repo", required=True)
    sub.add_argument("--service", required=True)
    sub.add_argument("--names", required=True, nargs="+")
    return top


def main(argv):
    args = parser().parse_args(argv)
    result = run_facts(args) if args.action == "facts" else run_explain(args)
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
