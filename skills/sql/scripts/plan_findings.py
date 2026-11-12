#!/usr/bin/env python3
"""The PLAN-* findings of a JSON query plan, with fixed thresholds (rules PLAN-01..PLAN-05 of dialects/postgres.md).

Usage: python3 plan_findings.py [PLAN] [--server-version-num N]

PLAN is a file path, or `-`, or absent: the plan is then read from stdin. The input is the JSON that
`pg_run.py explain` prints (an object with `plan` and `server_version_num`), or a bare EXPLAIN (FORMAT JSON)
document (a list whose first item has a `Plan` key). A `pg_run` object with `ok` false is passed on as
`pg_run_failed`, so a pipe from the plan call keeps the failure. Every number is read as a JSON number that may
be fractional (PostgreSQL 18). The script uses only the standard library, opens no connection and writes no file.

Output: one line of JSON that starts with {"ok": ...}. With ok true: server_version_num, analyze, notes,
findings (each: rule, node, path, measured, threshold) and plan (the input plan, unchanged). When the input is
a `pg_run` object with mode `select` or `write`, the keys `ran`, `reason`, `downgrade` and `warnings` of the input are
passed through (a key that the input lacks is left out). A finding has no
severity: the severity is in the dialect module. A plan with no actual values gives no finding and a note.
Text that is not JSON, a number that is not finite (NaN, Infinity, 1e999) or too large, or a plan nested too deep
gives ok false and error bad_input.
Exit code: 0 when ok is true, 1 when ok is false, 2 for a usage error (one line on stderr, nothing on stdout).
"""
import argparse
import json
import math
import sys

MIN_ACTUAL_ROWS = 1000
MAX_RATIO = 10
MIN_SCANNED_ROWS = 10000
MIN_REMOVED_RATIO = 0.9
MAX_HASH_BATCHES = 1
MIN_INNER_LOOPS = 1000
MIN_READ_BLOCKS = 1000
MAX_HIT_RATIO = 0.9
RUN_KEYS = ("ran", "reason", "downgrade", "warnings")
RUN_MODES = ("select", "write")


class Usage(Exception):
    pass


def number(node, key):
    """The value of `key` when it is a JSON number (also a fractional one), else None."""
    value = node.get(key)
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def children(node):
    plans = node.get("Plans")
    return [child for child in plans if isinstance(child, dict)] if isinstance(plans, list) else []


def kind_of(node):
    kind = node.get("Node Type")
    return kind if isinstance(kind, str) else "Unknown"


def label(node):
    kind = kind_of(node)
    relation = node.get("Relation Name")
    return f"{kind} on {relation}" if isinstance(relation, str) and relation else kind


def has_actual(node):
    return number(node, "Actual Rows") is not None or any(has_actual(child) for child in children(node))


def finding(rule, node, path, measured, threshold):
    return {"rule": rule, "node": label(node), "path": path, "measured": measured, "threshold": threshold}


def plan_01(node, path):
    rows, estimate, loops = number(node, "Actual Rows"), number(node, "Plan Rows"), number(node, "Actual Loops")
    if rows is None or estimate is None or loops is None:
        return []
    actual, estimated = rows * loops, estimate * loops
    if actual < MIN_ACTUAL_ROWS:
        return []
    larger, smaller = max(actual, estimated), min(actual, estimated)
    ratio = larger / smaller if smaller else None
    if ratio is not None and ratio < MAX_RATIO:
        return []
    return [finding("PLAN-01", node, path, {"actual_rows": actual, "estimated_rows": estimated, "ratio": ratio},
                    {"min_actual_rows": MIN_ACTUAL_ROWS, "ratio": MAX_RATIO})]


def plan_02(node, path):
    if node.get("Node Type") != "Seq Scan":
        return []
    rows, removed, loops = number(node, "Actual Rows"), number(node, "Rows Removed by Filter"), number(node, "Actual Loops")
    if rows is None or removed is None or loops is None or rows + removed <= 0:
        return []
    scanned, ratio = (rows + removed) * loops, removed / (rows + removed)
    if scanned < MIN_SCANNED_ROWS or ratio < MIN_REMOVED_RATIO:
        return []
    return [finding("PLAN-02", node, path, {"scanned_rows": scanned, "removed_ratio": ratio},
                    {"min_scanned_rows": MIN_SCANNED_ROWS, "min_removed_ratio": MIN_REMOVED_RATIO})]


def plan_03(node, path):
    measured = {}
    method = node.get("Sort Method")
    if isinstance(method, str) and method.lower().startswith("external"):
        measured["sort_method"] = method
    batches = number(node, "Hash Batches")
    if batches is not None and batches > MAX_HASH_BATCHES:
        measured["hash_batches"] = batches
    written = number(node, "Temp Written Blocks")
    if written is not None:
        # The buffer counts of a node include its children, so only the blocks above the children's sum count.
        added = written - sum(number(child, "Temp Written Blocks") or 0 for child in children(node))
        if added > 0:
            measured["temp_written_blocks"] = added
    if not measured:
        return []
    return [finding("PLAN-03", node, path, measured, {"hash_batches": MAX_HASH_BATCHES, "temp_written_blocks": 0})]


def plan_04(node, path):
    if node.get("Node Type") != "Nested Loop":
        return []
    kids = children(node)
    inner = next((child for child in kids if child.get("Parent Relationship") == "Inner"), None)
    if inner is None and len(kids) >= 2:
        inner = kids[1]
    loops = number(inner, "Actual Loops") if inner is not None else None
    if loops is None or loops < MIN_INNER_LOOPS:
        return []
    return [finding("PLAN-04", node, path, {"inner_loops": loops, "inner_node": label(inner)},
                    {"min_inner_loops": MIN_INNER_LOOPS})]


def plan_05(root, notes):
    hits, reads = number(root, "Shared Hit Blocks"), number(root, "Shared Read Blocks")
    if hits is None or reads is None:
        notes.append("no buffer counts at the root node, so PLAN-05 does not apply")
        return []
    total = hits + reads
    if reads < MIN_READ_BLOCKS or total <= 0 or hits / total >= MAX_HIT_RATIO:
        return []
    return [finding("PLAN-05", root, [kind_of(root)], {"shared_hit_blocks": hits, "shared_read_blocks": reads,
                                                       "hit_ratio": hits / total},
                    {"min_shared_read_blocks": MIN_READ_BLOCKS, "max_hit_ratio": MAX_HIT_RATIO})]


NODE_RULES = (plan_01, plan_02, plan_03, plan_04)


def walk(node, path, found):
    path = path + [kind_of(node)]
    if number(node, "Actual Loops") != 0:
        for rule in NODE_RULES:
            found.extend(rule(node, path))
    for child in children(node):
        walk(child, path, found)


def analyze_plan(plan, version):
    root = plan[0]["Plan"]
    notes, found = [], []
    analyze = has_actual(root)
    if not analyze:
        notes.append("the plan has no actual values (no ANALYZE), so no PLAN-* rule applies")
    else:
        walk(root, [], found)
        found.extend(plan_05(root, notes))
    return {"ok": True, "server_version_num": version, "analyze": analyze, "notes": notes,
            "findings": found, "plan": plan}


def failure(error, message):
    return {"ok": False, "error": error, "message": message}


def evaluate(document, version_argument):
    """The result object for a parsed JSON document."""
    if isinstance(document, dict) and "ok" in document:
        if document["ok"] is not True:
            return {"ok": False, "error": "pg_run_failed", "source_error": document.get("error"), "source": document}
        plan, version = document.get("plan"), number(document, "server_version_num")
    else:
        plan, version = document, version_argument
    if not (isinstance(plan, list) and plan and isinstance(plan[0], dict) and isinstance(plan[0].get("Plan"), dict)):
        return failure("bad_input", "the document is not an EXPLAIN (FORMAT JSON) plan: no Plan node")
    result = analyze_plan(plan, version)
    if isinstance(document, dict) and document.get("mode") in RUN_MODES:
        # A select or write run says which EXPLAIN ran and why, and its warnings: pass them on, so that
        # the piped call shows a downgrade and the sequence warning. A key the input lacks is left out.
        result.update({key: document[key] for key in RUN_KEYS if key in document})
    return result


def reject_constant(name):
    raise ValueError(f"{name} is not JSON")


def finite_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"{text} is not a finite number")
    return value


def run(text, version_argument):
    """The result object and its output line for the input text."""
    try:
        # NaN and Infinity are not JSON, and a number like 1e999 is read as infinity: a non-finite number would make the
        # output line invalid JSON, and NaN fails every comparison. allow_nan=False catches a value that a rule computes.
        document = json.loads(text, parse_constant=reject_constant, parse_float=finite_float)
        result = evaluate(document, version_argument)
        return result, json.dumps(result, allow_nan=False)
    except RecursionError:
        result = failure("bad_input", "the plan is nested too deep")
    except (ValueError, OverflowError):
        result = failure("bad_input", "the input is not JSON, or it holds a number that is not finite or too large")
    return result, json.dumps(result)


def read_text(path):
    try:
        if path is None or path == "-":
            return sys.stdin.buffer.read().decode("utf-8", errors="replace")
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError as error:
        raise Usage(f"cannot read {path}: {error.strerror}")


class OneLineParser(argparse.ArgumentParser):
    """A usage error is one line on stderr and exit 2; there is no help output (-h is a usage error)."""

    def error(self, message):
        raise Usage(message)


def main(argv):
    parser = OneLineParser(prog="plan_findings.py", add_help=False)
    parser.add_argument("plan", nargs="?")
    parser.add_argument("--server-version-num", type=int)
    try:
        args = parser.parse_args(argv)
        text = read_text(args.plan)
    except Usage as error:
        # A line break inside an echoed argument or path would make a second stderr line.
        print("plan_findings.py: " + " ".join(str(error).splitlines()), file=sys.stderr)
        return 2
    result, line = run(text, args.server_version_num)
    print(line)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
