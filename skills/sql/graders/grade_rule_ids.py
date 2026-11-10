#!/usr/bin/env python3
"""Rule-id grader (E) for a `/sql optimize` report.

Usage: grade_rule_ids.py REPORT [--expect ID...] [--forbid ID...]

REPORT is a path, or - for stdin. The grader reads the Rule cell of each table row (never prose).
It passes when every --expect id is found and no --forbid id is found.
Output: one line "FAIL <kind>:<id>: <message>" for each failed check, then PASS or FAIL.
Exit code: 0 pass, 1 fail, 2 usage error or unreadable report (no PASS or FAIL line then).
"""
import argparse
import re
import sys

UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


def read_report(path):
    if path == "-":
        return sys.stdin.buffer.read().decode("utf-8")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def rule_ids(text):
    """The Rule cell of each table row. The header row and the separator row are skipped."""
    found = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in UNESCAPED_PIPE.split(stripped.strip("|"))]
        if len(cells) < 2 or cells[0] == "#" or set(cells[0]) <= set("-: "):
            continue
        found.add(cells[1])
    return found


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report")
    parser.add_argument("--expect", nargs="*", default=[], metavar="ID")
    parser.add_argument("--forbid", nargs="*", default=[], metavar="ID")
    args = parser.parse_args(argv)
    try:
        found = rule_ids(read_report(args.report))
    except (OSError, UnicodeDecodeError) as error:
        print(f"cannot read the report: {error}", file=sys.stderr)
        return 2
    failures = [f"FAIL expect:{rule}: not found in the Rule column" for rule in args.expect if rule not in found]
    failures += [f"FAIL forbid:{rule}: found in the Rule column" for rule in args.forbid if rule in found]
    print("\n".join(failures + ["FAIL" if failures else "PASS"]))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
