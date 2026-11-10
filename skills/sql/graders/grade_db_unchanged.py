#!/usr/bin/env python3
"""Database-unchanged grader (G): the tables are the same before and after a DB eval case.

Usage: grade_db_unchanged.py BEFORE AFTER [--sequences-may-differ]

BEFORE and AFTER are snapshot files written by `evals/db/db_eval.py snapshot`: a JSON object with `tables`
(table name to the checksum of its rows) and `sequences` (sequence name to its last value, or null).
The grader fails for a table whose checksum differs and for a table in only one file. Without the flag
it also fails for a sequence whose value differs and for a sequence in only one file. With the flag the
sequences may differ (the case that expects the sequence warning), and the tables still must not.
Output: one line "FAIL <kind>: <message>" for each difference, then PASS or FAIL.
Exit code: 0 pass, 1 fail, 2 usage error or an unreadable snapshot (a message on stderr, no PASS or FAIL line).
"""
import argparse
import json
import sys


def read_snapshot(path):
    """The snapshot object. Raises OSError, UnicodeDecodeError or ValueError."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    for key in ("tables", "sequences"):
        if not isinstance(data.get(key), dict):
            raise ValueError(f"no `{key}` object")
    return data


def differences(before, after, kind):
    """The FAIL lines for one section (`tables` or `sequences`) of two snapshots."""
    label = "table" if kind == "tables" else "sequence"
    lines = []
    for name in sorted(set(before[kind]) | set(after[kind])):
        if name not in before[kind] or name not in after[kind]:
            lines.append(f"FAIL {label}: {name} missing in one snapshot")
        elif before[kind][name] != after[kind][name]:
            lines.append(f"FAIL {label}: {name} changed")
    return lines


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("before")
    parser.add_argument("after")
    parser.add_argument("--sequences-may-differ", action="store_true")
    args = parser.parse_args(argv)
    try:
        before, after = read_snapshot(args.before), read_snapshot(args.after)
    except (OSError, UnicodeDecodeError, ValueError) as error:
        print(f"cannot read the snapshot: {error}", file=sys.stderr)
        return 2
    failures = differences(before, after, "tables")
    if not args.sequences_may_differ:
        failures += differences(before, after, "sequences")
    print("\n".join(failures + ["FAIL" if failures else "PASS"]))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
