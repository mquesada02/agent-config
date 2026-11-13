#!/usr/bin/env python3
"""The only path of the sql skill to a database: `pg_run explain` for one SELECT or one write statement, `pg_run facts`
and `pg_run diff`.

Usage: python3 pg_run.py explain --repo <repo root> --service <name> --mode select|write [--statement <sql>]
       python3 pg_run.py facts --repo <repo root> --service <name> --names <table.column> [<table.column> ...]
       python3 pg_run.py diff --repo <repo root> --service <name> --a=<sql> --b=<sql>

With no `--statement` the statement is read from stdin. The order of work: the
allowlist check (`allowlist.py`), the guard of the mode (`sql_guard.py`), the server
version probe, then the explain run: `psql -X -w` with `service=<name>` and the
session options in the conninfo. In select mode it is `BEGIN READ ONLY`, `EXPLAIN (ANALYZE ...
FORMAT JSON)`, `ROLLBACK`, after a discovery run (`EXPLAIN (VERBOSE, FORMAT JSON)`, nothing runs) whose plan the guard scans
(`sql_guard.scan_calls`) and, when the plan has a call candidate, a function check (a fixed catalog query for the VOLATILE
user functions). When the statement or the plan calls a string-SQL function (`query_to_xml*`, `cursor_to_xml*`,
`ts_stat`, `ts_rewrite`, `crosstab*`, `connectby`; see `sql_guard.py`) or a VOLATILE user function, the run is a plain
`EXPLAIN (FORMAT JSON)` and `downgrade` says why. The output has `ran`, `reason`, `downgrade` and `warnings` in both modes. It
prints one JSON object. Every error text is redacted: the output has no key that holds raw `psql` text.

Write mode (`--mode write`) takes one `INSERT`, `UPDATE`, `DELETE` or `MERGE`. It sets no
`default_transaction_read_only`. A discovery run (`EXPLAIN (VERBOSE, FORMAT JSON)` in `BEGIN READ WRITE`
... `ROLLBACK`) finds the written tables and its plan is scanned; a catalog check finds the user triggers and rules of every
reached table and reads their stored expressions (CHECK, domain, generated, policy quals, view definitions), which are
scanned; a function check finds the VOLATILE user functions among the calls. With none, and none of the guard's scan names (see
`sql_guard.py`), the run is `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`; otherwise it is a plain `EXPLAIN (FORMAT JSON)` and
`downgrade` says why. Every write run ends in `ROLLBACK`. The output has `ran`, `reason`, `downgrade` and `warnings`
(`["sequence"]` when the `ANALYZE` run moved a sequence counter, which `ROLLBACK` does not undo).

`facts` takes no statement. It checks the allowlist, probes the version, and runs one fixed catalog query
in one read-only transaction (a script on stdin). The names (`table.column` or `schema.table.column`) reach
the server only as the value of a psql variable. It prints the nullability and the type of each column,
or `missing`: catalog metadata only. A name of another shape, or with a character that is not printable
ASCII, is `missing` and is never sent; when no name is sent there is no `psql` call at all.

`diff` compares the result of SELECT A with the result of SELECT B (a rewrite of A) and returns capped row samples (at
most 20 rows in each list), never a full result. Both statements pass `sql_guard.check_diff` before any connection. Write
`--a=<sql>` with an equals sign (a value that starts with `-` and holds no space is read as an option otherwise). Every
user statement reaches the server only in a `-c` argument. Three read-only sessions: the names of the output columns and
the version (`psql --csv`, `LIMIT 0`), the column types and catalog flags (`pg_typeof` through a join that is never
true, so the statements are planned and not run), and the proof (one `SELECT` with `MATERIALIZED` CTEs named `pgrun_*`:
`EXCEPT ALL` both ways and, for a top-level `ORDER BY` of A with resolvable keys, the same over `row_number()`).

Exit code: 0 when `ok` is true, 1 when `ok` is false, 2 for a usage error (one
line on stderr, nothing on stdout). Needs Python 3.11 or newer (tomllib).
"""
import argparse
import csv
import io
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


def explain(service, checked, overrides):
    """One select statement (`checked` is the result of `sql_guard.check_select_scan`): `ANALYZE`, or a plain EXPLAIN
    when it calls a string-SQL function (in the text, or in a stored object that the plan shows), or a VOLATILE user
    function, whose text argument or body could hold SQL that `ANALYZE` would run. A statement scan hit decides at once;
    otherwise a discovery run reads the plan, and a function check looks up the call candidates of the plan."""
    version = server_version(service, overrides)
    options, timeouts = session_options(version, overrides)
    flags = ["-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"]
    downgrade = [{"kind": "function", "name": name} for name in checked["scan"]]
    if not downgrade:
        discovery = run_psql(
            service, options, flags, ["BEGIN READ ONLY", f"EXPLAIN (VERBOSE, FORMAT JSON) {checked['sql']}", "ROLLBACK"]
        )
        plan = plan_list(discovery, "The discovery run did not return one JSON plan list.")
        downgrade, calls = scan_texts(plan_strings(plan), "select", UNREADABLE_PLAN)
        if not downgrade and calls:
            downgrade = function_check(service, options, flags, calls)
    if downgrade:
        ran, reason, text = "explain", downgrade_reason(downgrade), "EXPLAIN (FORMAT JSON)"
    else:
        buffers = "ANALYZE, BUFFERS" if version < EXPLICIT_BUFFERS_BELOW else "ANALYZE"
        ran = "analyze"
        reason = "no call of a function that runs SQL from a string, and no VOLATILE user function, in the plan"
        text = f"EXPLAIN ({buffers}, FORMAT JSON)"
    out = run_psql(service, options, flags, ["BEGIN READ ONLY", f"{text} {checked['sql']}", "ROLLBACK"])
    try:
        plan = json.loads(out)
    except (ValueError, RecursionError):  # not JSON, or nested too deeply
        plan = None
    if not isinstance(plan, list):
        raise bad_output("The explain run did not return one JSON plan list.")
    return {
        "ok": True, "action": "explain", "service": service, "mode": "select",
        "server_version_num": version, "ran": ran, "reason": reason,
        "timeouts": timeouts, "downgrade": downgrade, "warnings": [], "plan": plan,
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
),
types(oid) AS (
  SELECT a.atttypid FROM pg_attribute a
  WHERE a.attrelid IN (SELECT oid FROM reached) AND a.attnum > 0 AND NOT a.attisdropped
  UNION
  SELECT x.oid
  FROM types t
  JOIN pg_type ty ON ty.oid = t.oid
  CROSS JOIN LATERAL (
    SELECT ty.typbasetype AS oid WHERE ty.typtype = 'd'
    UNION ALL
    SELECT ty.typelem WHERE ty.typcategory = 'A'
    UNION ALL
    SELECT g.rngsubtype FROM pg_range g
    WHERE g.rngtypid = ty.oid OR (to_jsonb(g)->>'rngmultitypid')::oid = ty.oid
    UNION ALL
    SELECT f.atttypid FROM pg_attribute f
    WHERE ty.typtype = 'c' AND f.attrelid = ty.typrelid AND f.attnum > 0 AND NOT f.attisdropped
  ) AS x
),
expressions(body) AS (
  SELECT pg_get_expr(k.conbin, k.conrelid) FROM pg_constraint k
  WHERE k.conrelid IN (SELECT oid FROM reached) AND k.contype = 'c' AND k.conbin IS NOT NULL
  UNION ALL
  SELECT pg_get_expr(d.adbin, d.adrelid) FROM pg_attrdef d
  JOIN pg_attribute a ON a.attrelid = d.adrelid AND a.attnum = d.adnum
  WHERE d.adrelid IN (SELECT oid FROM reached) AND a.attgenerated <> '' AND d.adbin IS NOT NULL
  UNION ALL
  SELECT pg_get_expr(k.conbin, 0) FROM pg_constraint k
  WHERE k.contypid IN (SELECT oid FROM types) AND k.contype = 'c' AND k.conbin IS NOT NULL
  UNION ALL
  SELECT pg_get_expr(p.polqual, p.polrelid) FROM pg_policy p
  WHERE p.polrelid IN (SELECT oid FROM reached) AND p.polqual IS NOT NULL
  UNION ALL
  SELECT pg_get_expr(p.polwithcheck, p.polrelid) FROM pg_policy p
  WHERE p.polrelid IN (SELECT oid FROM reached) AND p.polwithcheck IS NOT NULL
  UNION ALL
  SELECT pg_get_viewdef(v.oid) FROM pg_class v
  WHERE v.oid IN (SELECT oid FROM reached) AND v.relkind = 'v'
    AND EXISTS (
      SELECT 1 FROM pg_class w CROSS JOIN LATERAL unnest(w.reloptions) AS o
      WHERE w.oid IN (SELECT oid FROM reached) AND w.relkind = 'v' AND starts_with(o, 'check_option=')
    )
)
SELECT json_build_object(
  'hits', coalesce((SELECT json_agg(json_build_object('kind', kind, 'name', name) ORDER BY kind, name) FROM hits), '[]'::json),
  'sequence', EXISTS (
    SELECT 1 FROM pg_attribute a
    LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
    WHERE a.attrelid IN (SELECT oid FROM inserted WHERE oid IS NOT NULL)
      AND a.attnum > 0 AND NOT a.attisdropped
      AND (a.attidentity <> '' OR pg_get_expr(d.adbin, d.adrelid) LIKE '%nextval(%')
  ),
  'expressions', coalesce((SELECT json_agg(body) FROM expressions), '[]'::json)
);
ROLLBACK;
"""

# The fixed function check (#548). The call candidates reach the server only as the value of the psql variable `calls`
# (JSON `[schema or null, name]` pairs), never as part of this text. A name with no schema matches a function in any schema
# of the search path (every overload). A function is built in when its object id is below 16384 (`FirstNormalObjectId`: every
# object that `initdb` creates); every other function is user-defined. An aggregate always has the label IMMUTABLE of its
# own row, so it is reported when one of its support functions is user-defined and VOLATILE. The result is a JSON list
# of `schema.name` texts.
FUNCTION_CHECK_SCRIPT = """BEGIN READ ONLY;
WITH wanted AS (
  SELECT e->>0 AS schema_name, e->>1 AS fn_name
  FROM json_array_elements(:'calls'::json) AS e
),
found AS (
  SELECT DISTINCT p.oid, p.proname, p.prokind, p.provolatile, n.nspname
  FROM wanted w
  JOIN pg_proc p ON p.proname = w.fn_name
  JOIN pg_namespace n ON n.oid = p.pronamespace
  WHERE CASE WHEN w.schema_name IS NULL THEN n.nspname = ANY (current_schemas(true)) ELSE n.nspname = w.schema_name END
)
SELECT coalesce(json_agg(r.name ORDER BY r.name), '[]'::json)
FROM (
  SELECT DISTINCT format('%I.%I', f.nspname, f.proname) AS name
  FROM found f
  WHERE f.oid >= 16384 AND CASE WHEN f.prokind = 'a' THEN EXISTS (
    SELECT 1 FROM pg_aggregate a
    JOIN pg_proc s ON s.oid = ANY (ARRAY[
      a.aggtransfn::oid, a.aggfinalfn::oid, a.aggcombinefn::oid, a.aggserialfn::oid,
      a.aggdeserialfn::oid, a.aggmtransfn::oid, a.aggminvtransfn::oid, a.aggmfinalfn::oid
    ])
    WHERE a.aggfnoid = f.oid AND s.oid >= 16384 AND s.provolatile = 'v'
  ) ELSE f.provolatile = 'v' END
) AS r;
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
            own = relation_of(node)
            relations = [own] if own else []
            tables = node.get("Target Tables")
            if tables is not None:
                if not isinstance(tables, list) or not tables:
                    raise bad_output(message)
                listed = [relation_of(t) for t in tables]
                if None in listed:
                    raise bad_output(message)
                relations += listed
            if not isinstance(operation, str) or not relations:
                raise bad_output(message)
            found += [[operation, schema, name] for schema, name in relations]
        elif isinstance(node, list):
            stack.extend(node)
    if not found:
        raise bad_output(message)
    return found


def parse_catalog(out):
    """`(hits, sequence, expressions)` of the catalog run, or a bad_output Failure. `expressions` is a list of texts."""
    try:
        data = json.loads(out)
    except (ValueError, RecursionError):
        data = None
    hits = data.get("hits") if isinstance(data, dict) else None
    expressions = data.get("expressions") if isinstance(data, dict) else None
    if (
        not isinstance(hits, list) or type(data.get("sequence")) is not bool
        or not isinstance(expressions, list) or any(not isinstance(text, str) for text in expressions)
        or any(
            not isinstance(hit, dict) or hit.get("kind") not in ("trigger", "rule") or not isinstance(hit.get("name"), str)
            for hit in hits
        )
    ):
        raise bad_output("The catalog run did not return one valid result.")
    return [{"kind": hit["kind"], "name": hit["name"]} for hit in hits], data["sequence"], expressions


UNREADABLE_PLAN = "unreadable plan text"
UNREADABLE_EXPRESSION = "unreadable expression text"
UNREADABLE_REASON = "the plan or a stored expression has a text that the scan cannot read"


def downgrade_reason(downgrade):
    functions = [hit["name"] for hit in downgrade if hit["kind"] == "function"]
    tables = sorted({hit["name"] for hit in downgrade if hit["kind"] != "function"})
    if UNREADABLE_PLAN in functions or UNREADABLE_EXPRESSION in functions:
        return UNREADABLE_REASON
    if functions:
        return "the statement calls " + ", ".join(functions)
    return "a reached table has a user trigger or a rule: " + ", ".join(tables)


def plan_strings(plan):
    """Every string value of a plan, at any depth (a new plan key needs no change here)."""
    found = []
    stack = [plan]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, str):
            found.append(node)
    return found


def scan_texts(texts, mode, unreadable_name):
    """`(downgrade entries, call candidates)` of the texts, scanned with the lists of `sql_guard.scan_calls`.
    The entries are the sorted names on the scan list, then one entry that is named `unreadable_name` when a text cannot be read."""
    names, calls, unreadable = set(), set(), False
    for text in texts:
        found = sql_guard.scan_calls(text, mode)
        names.update(found["scan"])
        calls.update(map(tuple, found["calls"]))
        unreadable = unreadable or found["unreadable"]
    entries = [{"kind": "function", "name": name} for name in sorted(names)]
    if unreadable:
        entries.append({"kind": "function", "name": unreadable_name})
    return entries, calls


def function_check(service, options, flags, calls):
    """The `function` entries for the VOLATILE user functions among the call candidates `calls` (a set of `(schema or None, name)`)."""
    payload = json.dumps(sorted(calls, key=lambda call: (call[0] or "", call[1])))
    out = run_psql(service, options, flags + ["-v", f"calls={payload}"], [], stdin=FUNCTION_CHECK_SCRIPT)
    try:
        names = json.loads(out)
    except (ValueError, RecursionError):
        names = None
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        raise bad_output("The function check did not return one valid result.")
    return [{"kind": "function", "name": name} for name in names]


def explain_write(service, checked, overrides):
    """One write statement: discovery, the plan scan, the catalog check, the function check, then `ANALYZE` or a plain
    EXPLAIN, always rolled back. The first step that finds something skips the later ones."""
    version = server_version(service, overrides)
    options, timeouts = session_options(version, overrides, "write")
    flags = ["-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"]
    sql = checked["sql"]
    discovery = run_psql(service, options, flags, ["BEGIN READ WRITE", f"EXPLAIN (VERBOSE, FORMAT JSON) {sql}", "ROLLBACK"])
    plan_targets = discovery_targets(discovery)
    downgrade = [{"kind": "function", "name": name} for name in checked["scan"]]
    sequence = checked["nextval"]
    calls = set()
    if not downgrade:
        plan = plan_list(discovery, "The discovery run did not return a plan with a usable ModifyTable node.")
        downgrade, calls = scan_texts(plan_strings(plan), "write", UNREADABLE_PLAN)
    if not downgrade:
        catalog = run_psql(
            service, options,
            flags + ["-v", f"targets={json.dumps(checked['targets'])}", "-v", f"plan_targets={json.dumps(plan_targets)}"],
            [], stdin=CATALOG_SCRIPT,
        )
        downgrade, found_sequence, expressions = parse_catalog(catalog)
        sequence = sequence or found_sequence
        if not downgrade:
            downgrade, expression_calls = scan_texts(expressions, "write", UNREADABLE_EXPRESSION)
            calls |= expression_calls
        if not downgrade and calls:
            downgrade = function_check(service, options, flags, calls)
    if downgrade:
        ran, reason, text = "explain", downgrade_reason(downgrade), "EXPLAIN (FORMAT JSON)"
    else:
        buffers = "ANALYZE, BUFFERS" if version < EXPLICIT_BUFFERS_BELOW else "ANALYZE"
        ran = "analyze"
        reason = "no trigger, rule, external call or VOLATILE user function on the reached tables"
        text = f"EXPLAIN ({buffers}, FORMAT JSON)"
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


# The type session of `diff`. `{a}` and `{b}` are `(SELECT ARRAY[pg_typeof(...)...] ...)` scalar subqueries that read the
# column types of A and B without running them (`LEFT JOIN ... ON false`). The catalog part strips domains, arrays and ranges
# down to a leaf type and reads, for each type, its name, whether its leaf is `float4` or `float8`, and whether its leaf has an
# equality that `EXCEPT` can use (an enum, or a default btree or hash operator class whose input type is the leaf or a type
# that the leaf casts to in an implicit, binary-coercible way: an `xml` cast to `text` is binary but not implicit, and `xml` has no
# equality operator). Oids leave the server as `bigint`: the JSON of an `oid` is a string.
TYPES_SQL = """WITH RECURSIVE arrs AS (SELECT {a} AS av, {b} AS bv),
roots AS (SELECT DISTINCT unnest(av || bv)::oid AS o FROM arrs),
chain(root, cur) AS (
  SELECT o, o FROM roots
  UNION
  SELECT chain.root,
    CASE WHEN ty.typtype = 'd' THEN ty.typbasetype WHEN ty.typtype = 'r' THEN rg.rngsubtype ELSE ty.typelem END
  FROM chain
  JOIN pg_type ty ON ty.oid = chain.cur
  LEFT JOIN pg_range rg ON rg.rngtypid = ty.oid
  WHERE ty.typtype IN ('d', 'r') OR ty.typcategory = 'A'
),
leaves AS (
  SELECT c.root, c.cur AS leaf FROM chain c JOIN pg_type ty ON ty.oid = c.cur
  WHERE ty.typtype NOT IN ('d', 'r') AND ty.typcategory <> 'A'
),
info AS (SELECT DISTINCT c.cur AS oid, l.leaf FROM chain c JOIN leaves l ON l.root = c.root)
SELECT json_build_object(
  'a', (SELECT av FROM arrs),
  'b', (SELECT bv FROM arrs),
  'types', (SELECT coalesce(json_object_agg(info.oid::text, json_build_object(
    'name', format_type(info.oid, NULL),
    'float', info.leaf IN (700, 701),
    'equality', EXISTS (
      SELECT 1 FROM pg_type lt
      WHERE lt.oid = info.leaf AND (lt.typtype = 'e' OR EXISTS (
        SELECT 1 FROM pg_opclass oc JOIN pg_am am ON am.oid = oc.opcmethod
        WHERE oc.opcdefault AND am.amname IN ('btree', 'hash')
          AND (oc.opcintype = lt.oid OR EXISTS (
            SELECT 1 FROM pg_cast pc WHERE pc.castsource = lt.oid AND pc.casttarget = oc.opcintype AND pc.castmethod = 'b' AND pc.castcontext = 'i'
          ))
      ))
    ),
    'leaf', info.leaf::bigint
  )), '{{}}'::json) FROM info)
)"""
SAMPLE_LIMIT = 20


def csv_records(out):
    """The records of CSV text, with the empty ones (a statement with no output column prints an empty header)."""
    return list(csv.reader(io.StringIO(out)))


def describe_names(service, sql_a, sql_b, overrides):
    """Session 1: `(version, names of A, names of B)` from one read-only session with the base timeouts."""
    options, _ = session_options(None, overrides)
    out = run_psql(
        service, options, ["--csv", "-q", "-v", "ON_ERROR_STOP=1"],
        ["SHOW server_version_num", "BEGIN READ ONLY", f"SELECT * FROM ({sql_a}\n) AS t LIMIT 0",
         f"SELECT * FROM ({sql_b}\n) AS t LIMIT 0", "ROLLBACK"],
    )
    records = csv_records(out)
    if len(records) != 4 or len(records[1]) != 1 or not re.fullmatch(r"\d{1,9}", records[1][0].strip()):
        raise bad_output("The describe run did not return the version and two header records.")
    return int(records[1][0].strip()), records[2], records[3]


def type_array_sql(sql, count):
    """The scalar subquery that reads `pg_typeof` of each of `count` columns of `sql` as a `bigint` array, without running it."""
    columns = ", ".join(f"c{i}" for i in range(1, count + 1))
    types = ", ".join(f"pg_typeof(x.c{i})::oid::bigint" for i in range(1, count + 1))
    return f"(SELECT ARRAY[{types}] FROM (SELECT 1) AS d LEFT JOIN ({sql}\n) AS x({columns}) ON false)"


def valid_oid_list(value, count):
    return isinstance(value, list) and len(value) == count and all(type(item) is int for item in value)


def parse_types(out, count):
    """`(oids of A, oids of B, types)` of the type session, or a bad_output Failure. `types` maps an oid to its entry."""
    try:
        data = json.loads(out)
    except (ValueError, RecursionError):
        data = None
    message = "The type run did not return one valid result."
    if not isinstance(data, dict) or not isinstance(data.get("types"), dict):
        raise bad_output(message)
    if not valid_oid_list(data.get("a"), count) or not valid_oid_list(data.get("b"), count):
        raise bad_output(message)
    types = {}
    for key, entry in data["types"].items():
        if (
            not re.fullmatch(r"\d{1,10}", key) or not isinstance(entry, dict) or not isinstance(entry.get("name"), str)
            or type(entry.get("float")) is not bool or type(entry.get("equality")) is not bool
            or type(entry.get("leaf")) is not int or str(entry["leaf"]) not in data["types"]
        ):
            raise bad_output(message)
        types[int(key)] = entry
    if any(oid not in types for oid in data["a"] + data["b"]):
        raise bad_output(message)
    return data["a"], data["b"], types


def resolve_order(order, names, mismatch):
    """`(state, reason, key columns)` for the order proof: `not_applicable`, or `partial` with a reason, or `checked` with
    the 1-based key positions and their direction text. A key must name one output column of A, or be a position in range,
    and its column must have the same type in A and B."""
    if order is None:
        return "not_applicable", None, None
    if "keys" not in order:
        return "partial", "sort_keys", None
    keys = []
    for key in order["keys"]:
        if key["operand"] == "position":
            position = key["value"] if 1 <= key["value"] <= len(names) else None
        else:
            found = [index + 1 for index, name in enumerate(names) if name == key["value"]]
            position = found[0] if len(found) == 1 else None
        if position is None or position - 1 in mismatch:
            return "partial", "sort_keys", None
        text = f"c{position}" + (" DESC" if key["descending"] else "")
        keys.append((position, text + (f" NULLS {key['nulls'].upper()}" if key["nulls"] else "")))
    return "checked", None, keys


def proof_sql(sql_a, sql_b, count, text_columns, keys):
    """The proof `SELECT` of `diff`: all CTEs are `MATERIALIZED` (each statement runs once), the names start with `pgrun_`, and
    every user statement is followed by a newline before its closing parenthesis. `keys` is None or the resolved sort keys."""
    names = [f"c{i}" for i in range(1, count + 1)]
    columns = ", ".join(names)
    compared = ", ".join(f"{name}::text AS {name}" if index in text_columns else name for index, name in enumerate(names))
    parts = [
        f"pgrun_ra AS MATERIALIZED (SELECT * FROM ({sql_a}\n) AS t({columns}))",
        f"pgrun_rb AS MATERIALIZED (SELECT * FROM ({sql_b}\n) AS t({columns}))",
        f"pgrun_a AS MATERIALIZED (SELECT {compared} FROM pgrun_ra)",
        f"pgrun_b AS MATERIALIZED (SELECT {compared} FROM pgrun_rb)",
        "pgrun_oa AS MATERIALIZED (SELECT * FROM pgrun_a EXCEPT ALL SELECT * FROM pgrun_b)",
        "pgrun_ob AS MATERIALIZED (SELECT * FROM pgrun_b EXCEPT ALL SELECT * FROM pgrun_a)",
    ]
    sample = "(SELECT coalesce(json_agg(to_json(s)), '[]'::json) FROM (SELECT * FROM {name} LIMIT %d) AS s)" % SAMPLE_LIMIT
    fields = [
        "'ra', (SELECT count(*) FROM pgrun_ra)", "'rb', (SELECT count(*) FROM pgrun_rb)",
        "'oa_count', (SELECT count(*) FROM pgrun_oa)", "'ob_count', (SELECT count(*) FROM pgrun_ob)",
        "'oa', " + sample.format(name="pgrun_oa"), "'ob', " + sample.format(name="pgrun_ob"),
    ]
    if keys:
        order = ", ".join(text for _, text in keys)
        group = ", ".join(f"c{position}" for position, _ in keys)
        for side, source in (("a", "ra"), ("b", "rb")):
            parts.append(
                f"pgrun_n{side} AS MATERIALIZED (SELECT row_number() OVER (ORDER BY {order}) AS rn, * FROM pgrun_{source})"
            )
        parts.append(
            f"pgrun_xa AS MATERIALIZED (SELECT rn, {compared} FROM pgrun_na EXCEPT ALL SELECT rn, {compared} FROM pgrun_nb)"
        )
        parts.append(
            f"pgrun_xb AS MATERIALIZED (SELECT rn, {compared} FROM pgrun_nb EXCEPT ALL SELECT rn, {compared} FROM pgrun_na)"
        )
        fields += [
            f"'ties', (SELECT count(*) FROM (SELECT 1 FROM pgrun_ra GROUP BY {group} HAVING count(*) > 1) AS k)",
            "'xa_count', (SELECT count(*) FROM pgrun_xa)", "'xb_count', (SELECT count(*) FROM pgrun_xb)",
            "'xa', " + sample.format(name="pgrun_xa"), "'xb', " + sample.format(name="pgrun_xb"),
        ]
    return "WITH " + ",\n".join(parts) + "\nSELECT json_build_object(" + ", ".join(fields) + ")"


def sample_rows(value, count, numbered):
    """The sample rows of the proof as arrays in column order (`rn` first for a numbered row), or a bad_output Failure."""
    names = (["rn"] if numbered else []) + [f"c{i}" for i in range(1, count + 1)]
    if not isinstance(value, list) or len(value) > SAMPLE_LIMIT:
        raise bad_output("The proof run returned a sample that is not valid.")
    rows = []
    for row in value:
        if not isinstance(row, dict) or set(row) != set(names):
            raise bad_output("The proof run returned a sample row that is not valid.")
        rows.append([row[name] for name in names])
    return rows


def parse_proof(out, count, keyed):
    """The proof result as a dict, or a bad_output Failure. Every count is an integer; every sample is checked."""
    try:
        data = json.loads(out)
    except (ValueError, RecursionError):
        data = None
    counts = ["ra", "rb", "oa_count", "ob_count"] + (["ties", "xa_count", "xb_count"] if keyed else [])
    if not isinstance(data, dict) or any(type(data.get(name)) is not int or data[name] < 0 for name in counts):
        raise bad_output("The proof run did not return one valid result.")
    proof = {name: data[name] for name in counts}
    for name in ("oa", "ob"):
        proof[name] = sample_rows(data.get(name), count, False)
    if keyed:
        for name in ("xa", "xb"):
            proof[name] = sample_rows(data.get(name), count, True)
    return proof


def diff(service, checked_a, checked_b, overrides):
    """The `diff` action: three read-only sessions (names and version, types, the proof). See the module docstring."""
    sql_a, sql_b = checked_a["sql"], checked_b["sql"]
    version, names_a, names_b = describe_names(service, sql_a, sql_b, overrides)
    options, timeouts = session_options(version, overrides)
    head = {"ok": True, "action": "diff", "service": service, "server_version_num": version, "timeouts": timeouts}
    if not names_a or names_a != names_b:
        return {**head, "equal": False, "reason": "shape", "column_names": {"a": names_a, "b": names_b}}
    count = len(names_a)
    flags = ["-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"]
    types_text = TYPES_SQL.format(a=type_array_sql(sql_a, count), b=type_array_sql(sql_b, count))
    oids_a, oids_b, types = parse_types(
        run_psql(service, options, flags, ["BEGIN READ ONLY", types_text, "ROLLBACK"]), count
    )
    mismatch = [i for i in range(count) if oids_a[i] != oids_b[i]]
    casts = [i for i in range(count) if i not in mismatch and not types[oids_a[i]]["equality"]]
    floats = [i for i in range(count) if types[oids_a[i]]["float"] or types[oids_b[i]]["float"]]
    state, reason, keys = resolve_order(checked_a["order"], names_a, mismatch)
    proof_text = proof_sql(sql_a, sql_b, count, set(mismatch) | set(casts), keys)
    proof = parse_proof(
        run_psql(service, options, flags, ["BEGIN READ ONLY", proof_text, "ROLLBACK"]), count, keys is not None
    )
    result = {
        **head,
        "columns": {
            "a": [{"name": names_a[i], "type": types[oids_a[i]]["name"]} for i in range(count)],
            "b": [{"name": names_b[i], "type": types[oids_b[i]]["name"]} for i in range(count)],
        },
        "rows": {"a": proof["ra"], "b": proof["rb"]},
        "only_a": {"count": proof["oa_count"], "rows": proof["oa"]},
        "only_b": {"count": proof["ob_count"], "rows": proof["ob"]},
        "type_mismatch": [{"position": i + 1, "name": names_a[i]} for i in mismatch],
        "casts": [names_a[i] for i in casts],
        "floats": [names_a[i] for i in floats],
    }
    order_equal = True
    if state == "checked" and proof["ties"] >= 1:
        state, reason = "partial", "ties"
    if state == "checked":
        result["order_mismatch"] = {
            "count_a": proof["xa_count"], "count_b": proof["xb_count"], "a": proof["xa"], "b": proof["xb"],
        }
        order_equal = proof["xa_count"] == 0 and proof["xb_count"] == 0
    result["order"] = state
    if state == "partial":
        result["reason"] = reason
    result["equal"] = not mismatch and proof["oa_count"] == 0 and proof["ob_count"] == 0 and order_equal
    return result


def run_diff(args):
    access, refusal = check_allowed(args)
    if refusal:
        return refusal
    checked = {}
    for side in ("a", "b"):
        result, refusal = sql_guard.check_diff(getattr(args, side))
        if refusal:
            return {"ok": False, "error": "refused", "statement": side, **refusal}
        checked[side] = result
    try:
        return diff(args.service, checked["a"], checked["b"], access["timeouts"].get(args.service, {}))
    except Failure as failure:
        return failure.result


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
    checked, refusal = sql_guard.check_select_scan(statement)
    if refusal:
        return {"ok": False, "error": "refused", **refusal}
    try:
        return explain(args.service, checked, access["timeouts"].get(args.service, {}))
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
    sub = actions.add_parser("diff")
    sub.add_argument("--repo", required=True)
    sub.add_argument("--service", required=True)
    sub.add_argument("--a", required=True)
    sub.add_argument("--b", required=True)
    return top


def main(argv):
    args = parser().parse_args(argv)
    runners = {"facts": run_facts, "diff": run_diff, "explain": run_explain}
    result = runners[args.action](args)
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
