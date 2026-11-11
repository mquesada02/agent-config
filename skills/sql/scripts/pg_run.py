#!/usr/bin/env python3
"""The only path of the sql skill to a database: `pg_run explain` for one SELECT or one write statement, and `pg_run facts`.

Usage: python3 pg_run.py explain --repo <repo root> --service <name> --mode select|write [--statement <sql>]
       python3 pg_run.py facts --repo <repo root> --service <name> --names <table.column> [<table.column> ...]

With no `--statement` the statement is read from stdin. The order of work: the
allowlist check (`allowlist.py`), the guard of the mode (`sql_guard.py`), the server
version probe, then the explain run: `psql -X -w` with `service=<name>` and the
session options in the conninfo. In select mode it is `BEGIN READ ONLY`, `EXPLAIN (ANALYZE ...
FORMAT JSON)`, `ROLLBACK`. It prints one JSON object. Every error text is
redacted: the output has no key that holds raw `psql` text.

Write mode (`--mode write`) takes one `INSERT`, `UPDATE`, `DELETE` or `MERGE`. It sets no
`default_transaction_read_only`. A discovery run (`EXPLAIN (VERBOSE, FORMAT JSON)` in `BEGIN READ WRITE`
... `ROLLBACK`) finds the written tables; a catalog check finds the user triggers and rules of every reached
table. With none, and none of the guard's scan names (see `sql_guard.py`), the run is `EXPLAIN (ANALYZE,
BUFFERS, FORMAT JSON)`; otherwise it is a plain `EXPLAIN (FORMAT JSON)` and `downgrade` says why. Every write
run ends in `ROLLBACK`. The output has `ran`, `reason`, `downgrade` and `warnings` (`["sequence"]` when the
`ANALYZE` run moved a sequence counter, which `ROLLBACK` does not undo).

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


def session_options(version, overrides, mode="select"):
    """The `-c` options and the timeouts sent. `version` None means the probe (no `transaction_timeout`).
    Write mode sets no `default_transaction_read_only`: its transaction is `BEGIN READ WRITE` and ends in `ROLLBACK`."""
    timeouts = {}
    for name, default in DEFAULT_TIMEOUTS:
        if name == "transaction_timeout" and (version is None or version < TRANSACTION_TIMEOUT_VERSION):
            continue
        timeouts[name] = overrides.get(name, default)
    flags = [] if mode == "write" else ["default_transaction_read_only=on"]
    flags.append("standard_conforming_strings=on")
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


# The fixed catalog check of write mode. The targets reach the server only as the values of the psql variables
# `targets` (JSON `[verb, name]` pairs from the guard) and `plan_targets` (JSON `[operation, schema, name]`
# triples from the discovery plan), never as part of this text. The reached tables are the targets, their
# partitions and inheritance children, the children of a foreign key with a CASCADE, SET NULL or SET DEFAULT
# action, and the base tables of every view (nested views included). The recursive term has one self-join;
# its `UNION` removes duplicates, so a cycle of foreign keys ends.
CATALOG_SCRIPT = """BEGIN READ ONLY;
WITH RECURSIVE start(oid) AS (
  SELECT to_regclass(e->>1)::oid
  FROM json_array_elements(:'targets'::json) AS e
  UNION
  SELECT c.oid
  FROM json_array_elements(:'plan_targets'::json) AS e
  JOIN pg_namespace n ON n.nspname = e->>1
  JOIN pg_class c ON c.relnamespace = n.oid AND c.relname = e->>2
),
reached(oid) AS (
  SELECT oid FROM start WHERE oid IS NOT NULL
  UNION
  SELECT x.oid
  FROM reached r CROSS JOIN LATERAL (
    SELECT i.inhrelid AS oid FROM pg_inherits i WHERE i.inhparent = r.oid
    UNION ALL
    SELECT f.conrelid FROM pg_constraint f
    WHERE f.contype = 'f' AND f.confrelid = r.oid
      AND (f.confdeltype IN ('c', 'n', 'd') OR f.confupdtype IN ('c', 'n', 'd'))
    UNION ALL
    SELECT d.refobjid FROM pg_rewrite w
    JOIN pg_depend d ON d.classid = 'pg_rewrite'::regclass AND d.objid = w.oid
      AND d.refclassid = 'pg_class'::regclass
    WHERE w.ev_class = r.oid AND w.rulename = '_RETURN' AND d.refobjid <> r.oid
  ) AS x
),
hits AS (
  SELECT 'trigger' AS kind, format('%I.%I', n.nspname, c.relname) AS name
  FROM pg_trigger t
  JOIN pg_class c ON c.oid = t.tgrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE t.tgrelid IN (SELECT oid FROM reached) AND t.tgenabled <> 'D'
    AND (NOT t.tgisinternal OR (t.tgparentid <> 0 AND (
      t.tgconstraint = 0 OR EXISTS (SELECT 1 FROM pg_constraint k WHERE k.oid = t.tgconstraint AND k.contype = 't')
    )))
  UNION
  SELECT 'rule', format('%I.%I', n.nspname, c.relname)
  FROM pg_rewrite w
  JOIN pg_class c ON c.oid = w.ev_class
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE w.ev_class IN (SELECT oid FROM reached) AND w.rulename <> '_RETURN'
),
inserted(oid) AS (
  SELECT to_regclass(e->>1)::oid
  FROM json_array_elements(:'targets'::json) AS e
  WHERE e->>0 IN ('insert', 'merge')
  UNION
  SELECT c.oid
  FROM json_array_elements(:'plan_targets'::json) AS e
  JOIN pg_namespace n ON n.nspname = e->>1
  JOIN pg_class c ON c.relnamespace = n.oid AND c.relname = e->>2
  WHERE lower(e->>0) IN ('insert', 'merge')
)
SELECT json_build_object(
  'hits', coalesce((SELECT json_agg(json_build_object('kind', kind, 'name', name) ORDER BY kind, name) FROM hits), '[]'::json),
  'sequence', EXISTS (
    SELECT 1 FROM pg_attribute a
    LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
    WHERE a.attrelid IN (SELECT oid FROM inserted WHERE oid IS NOT NULL)
      AND a.attnum > 0 AND NOT a.attisdropped
      AND (a.attidentity <> '' OR pg_get_expr(d.adbin, d.adrelid) LIKE '%nextval(%')
  )
);
ROLLBACK;
"""


def plan_list(out, message):
    """The plan list of an EXPLAIN run, or a bad_output Failure."""
    try:
        plan = json.loads(out)
    except (ValueError, RecursionError):  # not JSON, or nested too deeply
        plan = None
    if not isinstance(plan, list):
        raise bad_output(message)
    return plan


def relation_of(entry):
    """`(schema, name)` of a plan node or a `Target Tables` entry when both are strings, else None."""
    if isinstance(entry, dict) and isinstance(entry.get("Schema"), str) and isinstance(entry.get("Relation Name"), str):
        return entry["Schema"], entry["Relation Name"]
    return None


def discovery_targets(out):
    """The `[operation, schema, name]` triples of every `ModifyTable` node of the discovery plan (any depth).
    It fails closed: an odd plan, a node with no usable relation, or no `ModifyTable` node at all is bad_output."""
    message = "The discovery run did not return a plan with a usable ModifyTable node."
    found = []
    stack = []
    for item in plan_list(out, message):
        if not isinstance(item, dict) or not isinstance(item.get("Plan"), dict):
            raise bad_output(message)
        stack.append(item["Plan"])
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            stack.extend(node.values())
            if node.get("Node Type") != "ModifyTable":
                continue
            operation = node.get("Operation")
            relations = [relation_of(node)] if relation_of(node) else []
            tables = node.get("Target Tables")
            if tables is not None:
                if not isinstance(tables, list) or not tables or any(relation_of(t) is None for t in tables):
                    raise bad_output(message)
                relations += [relation_of(t) for t in tables]
            if not isinstance(operation, str) or not relations:
                raise bad_output(message)
            found += [[operation, schema, name] for schema, name in relations]
        elif isinstance(node, list):
            stack.extend(node)
    if not found:
        raise bad_output(message)
    return found


def parse_catalog(out):
    """`(hits, sequence)` of the catalog run, or a bad_output Failure."""
    try:
        data = json.loads(out)
    except (ValueError, RecursionError):
        data = None
    hits = data.get("hits") if isinstance(data, dict) else None
    if (
        not isinstance(hits, list) or type(data.get("sequence")) is not bool
        or any(
            not isinstance(hit, dict) or hit.get("kind") not in ("trigger", "rule") or not isinstance(hit.get("name"), str)
            for hit in hits
        )
    ):
        raise bad_output("The catalog run did not return one valid result.")
    return [{"kind": hit["kind"], "name": hit["name"]} for hit in hits], data["sequence"]


def downgrade_reason(downgrade):
    functions = [hit["name"] for hit in downgrade if hit["kind"] == "function"]
    tables = sorted({hit["name"] for hit in downgrade if hit["kind"] != "function"})
    if functions:
        return "the statement calls " + ", ".join(functions)
    return "a reached table has a user trigger or a rule: " + ", ".join(tables)


def explain_write(service, checked, overrides):
    """One write statement: discovery, the catalog check, then `ANALYZE` or a plain EXPLAIN, always rolled back."""
    version = server_version(service, overrides)
    options, timeouts = session_options(version, overrides, "write")
    flags = ["-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"]
    sql = checked["sql"]
    discovery = run_psql(service, options, flags, ["BEGIN READ WRITE", f"EXPLAIN (VERBOSE, FORMAT JSON) {sql}", "ROLLBACK"])
    plan_targets = discovery_targets(discovery)
    downgrade = [{"kind": "function", "name": name} for name in checked["scan"]]
    sequence = checked["nextval"]
    if not downgrade:
        catalog = run_psql(
            service, options,
            flags + ["-v", f"targets={json.dumps(checked['targets'])}", "-v", f"plan_targets={json.dumps(plan_targets)}"],
            [], stdin=CATALOG_SCRIPT,
        )
        downgrade, found_sequence = parse_catalog(catalog)
        sequence = sequence or found_sequence
    if downgrade:
        ran, reason, text = "explain", downgrade_reason(downgrade), "EXPLAIN (FORMAT JSON)"
    else:
        buffers = "ANALYZE, BUFFERS" if version < EXPLICIT_BUFFERS_BELOW else "ANALYZE"
        ran, reason, text = "analyze", "no trigger, rule or external call on the reached tables", f"EXPLAIN ({buffers}, FORMAT JSON)"
    out = run_psql(service, options, flags, ["BEGIN READ WRITE", f"{text} {sql}", "ROLLBACK"])
    return {
        "ok": True, "action": "explain", "service": service, "mode": "write",
        "server_version_num": version, "ran": ran, "reason": reason,
        "timeouts": timeouts, "downgrade": downgrade,
        "warnings": ["sequence"] if sequence and ran == "analyze" else [],
        "plan": plan_list(out, "The explain run did not return one JSON plan list."),
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
    if args.mode == "write":
        checked, refusal = sql_guard.check_write(statement)
        if refusal:
            return {"ok": False, "error": "refused", **refusal}
        try:
            return explain_write(args.service, checked, access["timeouts"].get(args.service, {}))
        except Failure as failure:
            return failure.result
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
    sub.add_argument("--mode", required=True, choices=["select", "write"])
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
