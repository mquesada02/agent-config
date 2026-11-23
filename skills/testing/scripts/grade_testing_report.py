#!/usr/bin/env python3
"""Report grader for a testing review report (the report contract of review.md).

Usage: grade_testing_report.py REPORT

REPORT is a path, or - for stdin. Checks: title, summary, sections, tables, numbering, counts,
where, ids, severities, notes, approve.
Output: one line "FAIL <check>: <message>" for each failed check (a passing check prints
nothing), then a last line PASS or FAIL.
Exit code: 0 pass, 1 fail, 2 usage error, unreadable report or unreadable catalogue source.
The catalogue ids and severities come from the CATALOG constant of intake.py, which is read
from its source (the script is never imported).
"""
import argparse
import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TITLE = re.compile(r"^# testing review: \S")
SUMMARY = re.compile(r"^\*\*Result: ([0-9]{1,9}) critical, ([0-9]{1,9}) required, ([0-9]{1,9}) suggestions?\.\*\*$")
COLUMNS = ["#", "Rule", "Where", "Problem", "Fix"]
HEADINGS = {"critical": "## Critical", "required": "## Required", "suggestion": "## Suggestions"}
SEVERITIES = list(HEADINGS)
APPROVE_HEADING = "## Approve"
APPROVE_TEXT = "Reply with the findings to fix: `all`, `none`, a list such as `1,3,5`, or a range such as `1-12`."
MARKS = ("⚑", "🔒")
PLACE = re.compile(r"\S+:\d+(?:-\d+)?")
# The note lines, in report order: (name, line prefix). The fallback line (d) has two forms.
NOTES = [
    ("a", ("Disabled (reason recorded, not checked): ",)),
    ("b", ("No reason line, checked anyway: ",)),
    ("c", ("Unknown ids in rules.disabled, ignored: ",)),
    ("d", ("Detected for this run: ", "Rules file error: ")),
    ("e", ("Not checked: ",)),
]
ID_LIST_NOTES = ("a", "b", "c")


def load_catalog():
    """The CATALOG constant of intake.py. Raises ValueError when the source cannot give it."""
    path = os.path.join(HERE, "intake.py")
    try:
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
    except (OSError, UnicodeDecodeError, SyntaxError) as error:
        raise ValueError(f"cannot read {path}: {error}") from error
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "CATALOG" for target in node.targets
        ):
            try:
                return ast.literal_eval(node.value)
            except ValueError as error:
                raise ValueError(f"{path} has a CATALOG constant that is not a literal") from error
    raise ValueError(f"{path} has no CATALOG constant")


def read_report(path):
    if path == "-":
        return sys.stdin.buffer.read().decode("utf-8")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


def split_row(line):
    """The cells of a table row. An escaped pipe (backslash, pipe) stays inside its cell."""
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    cells = UNESCAPED_PIPE.split(body)
    if len(cells) > 1 and not cells[-1].strip():
        cells.pop()
    return [cell.strip() for cell in cells]


def parse_table(lines, heading_index):
    """(header cells, data rows) of the table under a heading, up to the next ## heading."""
    header, rows = None, []
    for line in lines[heading_index + 1:]:
        stripped = line.strip()
        if stripped.startswith("## "):
            break
        if not stripped.startswith("|"):
            continue
        cells = split_row(stripped)
        if header is None:
            header = cells
        elif not set(cells[0]) <= set("-: "):
            rows.append(cells)
    return header, rows


def note_ids(line, prefix):
    body = line.strip()[len(prefix):].rstrip(".")
    return [item.strip() for item in body.split(",") if item.strip()]


def grade(text, catalog):
    lines = text.splitlines()
    failures = []

    def fail(check, message):
        failures.append(f"FAIL {check}: {message}")

    def first_index(test):
        return next((i for i, line in enumerate(lines) if test(line.strip())), None)

    title_at = first_index(lambda s: bool(TITLE.match(s)))
    summary_at = first_index(lambda s: bool(SUMMARY.match(s)))
    if title_at is None:
        fail("title", "no line like # testing review: <scope>")
    elif title_at != next((i for i, line in enumerate(lines) if line.strip()), None):
        fail("title", "the title is not the first line")

    counts = None
    if summary_at is None:
        fail("summary", "no line like **Result: N critical, N required, N suggestions.**")
    else:
        found = SUMMARY.match(lines[summary_at].strip())
        counts = dict(zip(SEVERITIES, (int(n) for n in found.groups())))
        if title_at is not None and summary_at < title_at:
            fail("summary", "the Result line is before the title")

    # sections: only the four known ## headings, and no flag or lock mark
    headings = [(i, line.strip()) for i, line in enumerate(lines) if line.strip().startswith("## ")]
    known = list(HEADINGS.values()) + [APPROVE_HEADING]
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") and not stripped.startswith("## ") and i != title_at:
            fail("sections", f"unknown heading: {stripped}")
    for _, heading in headings:
        if heading not in known:
            fail("sections", f"unknown section: {heading}")
    order = [known.index(heading) for _, heading in headings if heading in known]
    if order != sorted(order):
        fail("sections", "sections are not in the order Critical, Required, Suggestions, Approve")
    if len(set(heading for _, heading in headings)) != len(headings):
        fail("sections", "a section appears twice")
    for mark in MARKS:
        if mark in text:
            fail("sections", f"the report has the mark {mark}, which this report does not use")

    # tables
    table_at = {s: next((i for i, h in headings if h == HEADINGS[s]), None) for s in SEVERITIES}
    rows = {}
    for severity in SEVERITIES:
        at = table_at[severity]
        if at is None:
            rows[severity] = []
            if counts is not None and counts[severity] > 0:
                fail("tables", f"no {severity} table, but the summary counts {counts[severity]}")
            continue
        header, rows[severity] = parse_table(lines, at)
        if counts is not None and counts[severity] == 0:
            fail("tables", f"a {severity} table exists, but the summary counts 0")
        if header != COLUMNS:
            fail("tables", f"the {severity} table columns are not {COLUMNS}")

    # numbering: 1..n with no gap across the tables, in severity order
    numbers = []
    for severity in SEVERITIES:
        for cells in rows[severity]:
            numbers.append(int(cells[0]) if re.fullmatch("[0-9]{1,9}", cells[0]) else None)
    if numbers != list(range(1, len(numbers) + 1)):
        fail("numbering", f"the numbers are {numbers}, not 1..{len(numbers)} in severity order")

    # counts
    if counts is not None:
        for severity in SEVERITIES:
            if len(rows[severity]) != counts[severity]:
                fail("counts", f"{severity}: {len(rows[severity])} rows, the summary counts {counts[severity]}")

    # where, ids, severities
    seen = set()
    for severity in SEVERITIES:
        for cells in rows[severity]:
            if len(cells) != len(COLUMNS):
                fail("tables", f"a {severity} row has {len(cells)} cells, not {len(COLUMNS)}")
                continue
            if not PLACE.search(cells[2]):
                fail("where", f"the Where cell {cells[2]!r} has no <path>:<line> place")
            rule = cells[1]
            if rule not in catalog:
                fail("ids", f"the Rule cell {rule!r} is not exactly one catalogue id")
                continue
            if rule in seen:
                fail("ids", f"{rule} appears twice")
            seen.add(rule)
            if catalog[rule] != severity:
                fail("severities", f"{rule} is {catalog[rule]} in the catalogue, but sits in the {severity} table")

    # notes: between the Result line and the first table, each at most once, in order
    first_heading = headings[0][0] if headings else len(lines)
    start = (summary_at + 1) if summary_at is not None else 0
    note_lines = []
    for i in range(start, first_heading):
        stripped = lines[i].strip()
        for name, prefixes in NOTES:
            prefix = next((p for p in prefixes if stripped.startswith(p)), None)
            if prefix:
                note_lines.append((name, prefix, stripped))
    for i in range(first_heading, len(lines)):
        stripped = lines[i].strip()
        for name, prefixes in NOTES:
            if any(stripped.startswith(p) for p in prefixes):
                fail("notes", f"note line ({name}) is after a table, not before the first section")
    names = [name for name, _, _ in note_lines]
    for name in dict.fromkeys(names):
        if names.count(name) > 1:
            fail("notes", f"note line ({name}) appears more than once")
    if names != sorted(names):
        fail("notes", "the note lines are not in the order " + ", ".join(f"({name})" for name, _ in NOTES))
    placed = {}
    for name, prefix, stripped in note_lines:
        if name in ID_LIST_NOTES:
            for rule in note_ids(stripped, prefix):
                placed.setdefault(rule, set()).add(name)
    for rule, where in sorted(placed.items()):
        if len(where) > 1:
            fail("notes", f"{rule} is in more than one of the lines (a), (b), (c)")
    for rule, where in sorted(placed.items()):
        if "a" in where and rule in seen:
            fail("notes", f"{rule} is in line (a), so it is not checked, but the report has a row for it")

    # approve: present and exact with at least one row, absent with zero rows
    total = sum(counts.values()) if counts is not None else sum(len(r) for r in rows.values())
    approve_at = next((i for i, h in headings if h == APPROVE_HEADING), None)
    if total == 0:
        if approve_at is not None:
            fail("approve", "a report with zero rows has no ## Approve section")
    elif approve_at is None:
        fail("approve", "a report with rows has no ## Approve section")
    else:
        if headings[-1][1] != APPROVE_HEADING:
            fail("approve", "the last section is not ## Approve")
        body = " ".join(line.strip() for line in lines[approve_at + 1:] if line.strip())
        if body != APPROVE_TEXT:
            fail("approve", f"the approval text is not: {APPROVE_TEXT}")

    return failures


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report")
    args = parser.parse_args(argv)
    try:
        text = read_report(args.report)
    except (OSError, UnicodeDecodeError) as error:
        print(f"cannot read the report: {error}", file=sys.stderr)
        return 2
    try:
        catalog = load_catalog()
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    failures = grade(text, catalog)
    print("\n".join(failures + ["FAIL" if failures else "PASS"]))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
