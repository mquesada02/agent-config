#!/usr/bin/env python3
"""Rule-id grader for a cicd-pipelines review report.

Usage: grade_rule_ids.py REPORT [--expect ID...] [--forbid ID...]

REPORT is a path, or - for stdin. The grader reads the Rule cell of each table row
(never prose): the second cell of a table whose header starts with a `#` column, else the first cell.
It passes when every --expect token is found and no --forbid token is found.
Output: one line "FAIL <kind>:<id>: <message>" for each failed check, then PASS or FAIL.
Exit code: 0 pass, 1 fail, 2 usage error or unreadable report.
"""
import argparse
import sys

FLAG = "⚑"
LOCK = "🔒"


def read_report(path):
    if path == "-":
        return sys.stdin.buffer.read().decode("utf-8")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def rule_tokens(text):
    """The Rule cell of each table row, without the flag mark. The header and separator rows are skipped.

    A table is a run of lines that start with `|`, and its first row is the header. The Rule cell is the second
    cell when the first header cell is `#` (the normal report), else the first cell (the general reply)."""
    tokens = set()
    rule_at = None  # the index of the Rule cell in the table that is being read; None before its header row
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            rule_at = None
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if rule_at is None:
            rule_at = 1 if cells[0] == "#" else 0
            continue
        if len(cells) <= rule_at or set(cells[0]) <= set("-: "):
            continue
        tokens.add(cells[rule_at].replace(FLAG, "").replace(LOCK, "").strip())
    return tokens


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report")
    parser.add_argument("--expect", nargs="*", default=[], metavar="ID")
    parser.add_argument("--forbid", nargs="*", default=[], metavar="ID")
    args = parser.parse_args(argv)
    try:
        tokens = rule_tokens(read_report(args.report))
    except (OSError, UnicodeDecodeError) as error:
        print(f"cannot read the report: {error}", file=sys.stderr)
        return 2
    failures = [f"FAIL expect:{rule}: not found in the Rule column"
                for rule in args.expect if rule not in tokens]
    failures += [f"FAIL forbid:{rule}: found in the Rule column"
                 for rule in args.forbid if rule in tokens]
    print("\n".join(failures + ["FAIL" if failures else "PASS"]))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
