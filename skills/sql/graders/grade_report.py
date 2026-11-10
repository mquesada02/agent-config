#!/usr/bin/env python3
"""Report-layout grader (I) for a `/sql optimize` report (the report contract of optimize.md).

Usage: grade_report.py REPORT [--disabled ID...]

REPORT is a path, or - for stdin. Checks: title, summary, sections, disabled, tables, rows, numbering,
counts, unique, where, approve, rewrite. With --disabled, the ids of the `Disabled rules:` line must be
exactly that set. In every case no table row may hold a disabled id of the line.
Output: one line "FAIL <check>: <message>" for each failed check, then PASS or FAIL.
Exit code: 0 pass, 1 fail, 2 usage error or unreadable report (no PASS or FAIL line then).
"""
import argparse
import re
import sys

TITLE = re.compile(r"^# sql optimize: \S")
SUMMARY = re.compile(r"^\*\*Result: ([0-9]{1,9}) critical, ([0-9]{1,9}) required, ([0-9]{1,9}) suggestions?\.\*\*$")
COLUMNS = ["#", "Rule", "Where", "Problem", "Fix"]
HEADINGS = {"critical": "## Critical", "required": "## Required", "suggestion": "## Suggestions"}
SEVERITIES = list(HEADINGS)
APPROVE_HEADING = "## Approve"
APPROVE_FINDINGS = "Reply with the findings to fix: `all`, `none`, a list such as `1,3,5`, or a range such as `1-12`."
APPROVE_ZERO = "There is nothing to approve."
REWRITE_LABEL = "Rewrite (unproven: no database):"
RULE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")
PLACE = re.compile(r"^(\S+):([1-9][0-9]*)(?:-([1-9][0-9]*))?$")
DISABLED_LINE = re.compile(r"^Disabled rules: (.*)\.$")
UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


def read_report(path):
    if path == "-":
        return sys.stdin.buffer.read().decode("utf-8")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def split_row(line):
    return [cell.strip() for cell in UNESCAPED_PIPE.split(line.strip()[1:-1])]


def grade(text, disabled_flag):
    lines = [line.strip() for line in text.splitlines()]
    failures = []

    def fail(check, message):
        failures.append(f"FAIL {check}: {message}")

    non_blank = [i for i, line in enumerate(lines) if line]
    heading_at = {name: next((i for i, line in enumerate(lines) if line == heading), None)
                  for name, heading in HEADINGS.items()}
    approve_at = next((i for i, line in enumerate(lines) if line == APPROVE_HEADING), None)

    # title: the first non-blank line
    title_at = non_blank[0] if non_blank else None
    if title_at is None or not TITLE.match(lines[title_at]):
        fail("title", "the first line is not `# sql optimize: <scope>`")

    # summary: the line after the title
    counts = None
    summary_at = next((i for i, line in enumerate(lines) if SUMMARY.match(line)), None)
    if summary_at is None:
        fail("summary", "no line like **Result: N critical, N required, N suggestions.**")
    else:
        counts = dict(zip(SEVERITIES, (int(n) for n in SUMMARY.match(lines[summary_at]).groups())))
        if len(non_blank) < 2 or summary_at != non_blank[1]:
            fail("sections", "the summary is not the line after the title")

    # sections: every `## ` heading is known, in contract order, Approve last
    headings = [(i, line) for i, line in enumerate(lines) if line.startswith("## ")]
    allowed = list(HEADINGS.values()) + [APPROVE_HEADING]
    for _, line in headings:
        if line not in allowed:
            fail("sections", f"unknown heading: {line}")
    known = [allowed.index(line) for _, line in headings if line in allowed]
    if known != sorted(known):
        fail("sections", "the tables are not in the order critical, required, suggestions")
    if known and len(known) != len(set(known)):
        fail("sections", "a heading appears twice")
    if not headings or headings[-1][1] != APPROVE_HEADING:
        fail("approve", "the last section is not ## Approve")

    # lines between the summary and the first heading: Disabled rules and Note lines only
    first_heading = headings[0][0] if headings else len(lines)
    disabled_ids, disabled_lines = [], 0
    if summary_at is not None:
        for line in lines[summary_at + 1:first_heading]:
            if not line:
                continue
            found = DISABLED_LINE.match(line)
            if line.startswith("Disabled rules:"):
                disabled_lines += 1
                disabled_ids = found.group(1).split(", ") if found else [line[len("Disabled rules:"):].strip()]
            elif not line.startswith("Note:"):
                fail("sections", f"a line that is not a Disabled rules line or a Note line: {line[:60]}")
    if disabled_lines > 1:
        fail("disabled", "more than one Disabled rules line")
    if disabled_lines:
        if not all(RULE_ID.match(i) for i in disabled_ids):
            fail("disabled", "the Disabled rules line is not ids separated by `, ` and a final `.`")
        if len(disabled_ids) != len(set(disabled_ids)):
            fail("disabled", "a disabled id is named twice")
    if disabled_flag is not None:
        if not disabled_lines:
            fail("disabled", "no Disabled rules line, but --disabled names ids")
        elif set(disabled_ids) != set(disabled_flag):
            fail("disabled", f"the Disabled rules line names {sorted(set(disabled_ids))}, not {sorted(disabled_flag)}")

    # tables
    rows = {severity: [] for severity in SEVERITIES}
    for severity in SEVERITIES:
        at = heading_at[severity]
        if at is None:
            if counts is not None and counts[severity] > 0:
                fail("tables", f"no {severity} table, but the summary counts {counts[severity]}")
            continue
        if counts is not None and counts[severity] == 0:
            fail("tables", f"a {severity} table exists, but the summary counts 0")
        block = []
        for line in lines[at + 1:]:
            if line.startswith("## "):
                break
            if line:
                block.append(line)
        is_row = [bool(line.startswith("|") and line.endswith("|") and len(line) > 1) for line in block[:2]]
        if len(block) < 2 or not all(is_row) or split_row(block[0]) != COLUMNS or not set(block[1]) <= set("|-: "):
            fail("tables", f"the {severity} table has not the header {COLUMNS} and a separator row")
        for line in block[2:]:
            if not (line.startswith("|") and line.endswith("|") and len(line) > 1):
                fail("rows", f"a line of the {severity} table is not a complete row: {line[:60]}")
                continue
            cells = split_row(line)
            if len(cells) != len(COLUMNS) or not all(cells):
                fail("rows", f"a row of the {severity} table has not {len(COLUMNS)} filled cells: {line[:60]}")
                continue
            rows[severity].append(cells)
    all_rows = [cells for severity in SEVERITIES for cells in rows[severity]]

    # counts
    if counts is not None:
        for severity in SEVERITIES:
            if len(rows[severity]) != counts[severity] and heading_at[severity] is not None:
                fail("counts", f"{severity}: {len(rows[severity])} rows, the summary counts {counts[severity]}")

    # numbering: 1..n in table order
    numbers = [int(cells[0]) if re.fullmatch("[0-9]{1,9}", cells[0]) else None for cells in all_rows]
    if numbers != list(range(1, len(numbers) + 1)):
        fail("numbering", f"the numbers are {numbers}, not 1..{len(numbers)} in table order")

    # unique: one rule id in each Rule cell, and each id in one row only
    seen = set()
    for cells in all_rows:
        rule = cells[1]
        if not RULE_ID.match(rule):
            fail("unique", f"the Rule cell {rule!r} is not one rule id")
        elif rule in seen:
            fail("unique", f"{rule} appears in more than one row")
        seen.add(rule)
        if rule in disabled_ids:
            fail("disabled", f"{rule} is disabled and has a row")

    # where: places of the form <path>:<line> or <path>:<line>-<line>
    for cells in all_rows:
        for place in cells[2].split(", "):
            found = PLACE.match(place)
            if not found or (found.group(3) and int(found.group(3)) < int(found.group(2))):
                fail("where", f"{cells[1]}: {place!r} is not <path>:<line> or <path>:<line>-<line>")

    # rewrite: a Fix cell with the word Rewrite starts with the label and holds `database diff`
    for cells in all_rows:
        fix = cells[4]
        if re.search(r"\bRewrite\b", fix):
            if not fix.startswith(REWRITE_LABEL):
                fail("rewrite", f"{cells[1]}: the Fix cell does not start with `{REWRITE_LABEL}`")
            if "database diff" not in fix:
                fail("rewrite", f"{cells[1]}: the Fix cell does not name the missing `database diff`")

    # approve: the text of the contract
    if approve_at is not None and headings and headings[-1][1] == APPROVE_HEADING:
        body = " ".join(line for line in lines[approve_at + 1:] if line)
        expected = APPROVE_FINDINGS if all_rows else APPROVE_ZERO
        if body != expected:
            fail("approve", f"the approval text is not: {expected}")
    return failures


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report")
    parser.add_argument("--disabled", nargs="*", default=None, metavar="ID")
    args = parser.parse_args(argv)
    try:
        text = read_report(args.report)
    except (OSError, UnicodeDecodeError) as error:
        print(f"cannot read the report: {error}", file=sys.stderr)
        return 2
    failures = grade(text, args.disabled)
    print("\n".join(failures + ["FAIL" if failures else "PASS"]))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
