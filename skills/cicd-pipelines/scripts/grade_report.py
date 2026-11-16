#!/usr/bin/env python3
"""Report-structure grader for a ci-pipelines review report (the report contract of review.md).

Usage: grade_report.py REPORT

REPORT is a path, or - for stdin. Checks: summary, sections, tables, numbering, counts, unique,
flag-section, approve, tools (a bullet for each tool: its version when on PATH, an install hint when not).
Output: one line "FAIL <check>: <message>" for each failed check, then PASS or FAIL.
Exit code: 0 pass, 1 fail, 2 usage error or unreadable report.
"""
import argparse
import re
import sys

TITLE = re.compile(r"^# ci-pipelines review: \S")
SUMMARY = re.compile(r"^\*\*Result: ([0-9]{1,9}) critical, ([0-9]{1,9}) required, ([0-9]{1,9}) suggestions?\.\*\*$")
COLUMNS = ["#", "Rule", "Where", "Problem", "Fix"]
HEADINGS = {"critical": "## Critical", "required": "## Required", "suggestion": "## Suggestions"}
SEVERITIES = list(HEADINGS)
FLAG = "⚑"
FLAG_HEADING = "## ⚑"
GRAPH_HEADING = "## Job graph after the fixes"
APPROVE_HEADING = "## Approve"
APPROVE_FINDINGS = "Reply with the findings to fix: `all`, `none`, a list such as `1,3,5`, or a range such as `1-12`."
APPROVE_ZERO = "There is nothing to approve."
TOOLS = ("actionlint", "zizmor")
RULE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")
# Every section marker, in contract order: (name, test on a stripped line).
MARKERS = [
    ("title", lambda s: bool(TITLE.match(s))),
    ("summary", lambda s: bool(SUMMARY.match(s))),
    ("intake", lambda s: s.startswith("Intake:")),
    ("required checks", lambda s: s.startswith("Required checks")),
    ("tools", lambda s: s == "Tools:"),
    ("critical table", lambda s: s == HEADINGS["critical"]),
    ("required table", lambda s: s == HEADINGS["required"]),
    ("suggestion table", lambda s: s == HEADINGS["suggestion"]),
    ("flag section", lambda s: s.startswith(FLAG_HEADING)),
    ("job graph", lambda s: s == GRAPH_HEADING),
    ("approve", lambda s: s == APPROVE_HEADING),
]
ALWAYS = ["title", "summary", "intake", "required checks", "tools", "job graph", "approve"]


def read_report(path):
    if path == "-":
        return sys.stdin.buffer.read().decode("utf-8")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def first_index(lines, test):
    return next((i for i, line in enumerate(lines) if test(line.strip())), None)


def split_row(line):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


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


def grade(text):
    lines = text.splitlines()
    failures = []

    def fail(check, message):
        failures.append(f"FAIL {check}: {message}")

    index = {name: first_index(lines, test) for name, test in MARKERS}

    # summary
    counts = None
    if index["summary"] is None:
        fail("summary", "no line like **Result: N critical, N required, N suggestions.**")
    else:
        found = SUMMARY.match(lines[index["summary"]].strip())
        counts = dict(zip(SEVERITIES, (int(n) for n in found.groups())))

    # sections: the always-present ones exist, and the present ones follow the contract order
    for name in ALWAYS:
        if index[name] is None:
            fail("sections", f"missing section: {name}")
    present = [index[name] for name, _ in MARKERS if index[name] is not None]
    if present != sorted(present):
        fail("sections", "sections are not in the contract order")
    if index["job graph"] is not None:
        block = []
        for line in lines[index["job graph"] + 1:]:
            if line.strip().startswith("## "):
                break
            block.append(line.strip())
        if sum(1 for line in block if line.startswith("```")) < 2:
            fail("sections", "the job graph has no fenced sketch")

    # tables
    tables = {}
    for severity in SEVERITIES:
        at = index[f"{severity} table"]
        tables[severity] = parse_table(lines, at) if at is not None else None
        if counts is not None:
            if counts[severity] > 0 and at is None:
                fail("tables", f"no {severity} table, but the summary counts {counts[severity]}")
            if counts[severity] == 0 and at is not None:
                fail("tables", f"a {severity} table exists, but the summary counts 0")
        if at is not None and tables[severity][0] != COLUMNS:
            fail("tables", f"the {severity} table columns are not {COLUMNS}")
    table_at = [index[f"{s} table"] for s in SEVERITIES if index[f"{s} table"] is not None]
    if table_at != sorted(table_at):
        fail("tables", "tables are not in the order critical, required, suggestion")

    rows = {s: (tables[s][1] if tables[s] else []) for s in SEVERITIES}

    # numbering: 1..n with no gap, in severity order
    numbers = []
    for severity in SEVERITIES:
        for cells in rows[severity]:
            numbers.append(int(cells[0]) if re.fullmatch("[0-9]{1,9}", cells[0]) else None)
    if numbers != list(range(1, len(numbers) + 1)):
        fail("numbering", f"the numbers are {numbers}, not 1..{len(numbers)} in severity order")

    # counts: rows of each table equal the summary count
    if counts is not None:
        for severity in SEVERITIES:
            if len(rows[severity]) != counts[severity]:
                fail("counts", f"{severity}: {len(rows[severity])} rows, the summary counts {counts[severity]}")

    # unique: one rule id in each Rule cell, and each (rule id, severity) in one row only
    for severity in SEVERITIES:
        seen = set()
        for cells in rows[severity]:
            rule = cells[1].replace(FLAG, "").strip() if len(cells) > 1 else ""
            if not RULE_ID.match(rule):
                fail("unique", f"the Rule cell {cells[1:2]} is not one rule id")
            elif rule in seen:
                fail("unique", f"{rule} appears twice at severity {severity}")
            seen.add(rule)

    # flag-section: the section exists exactly when a row has the flag mark
    any_flag = any(FLAG in cells[1] for severity in SEVERITIES for cells in rows[severity] if len(cells) > 1)
    has_section = index["flag section"] is not None
    if any_flag and not has_section:
        fail("flag-section", "a row has the flag mark, but there is no flag section")
    if has_section and not any_flag:
        fail("flag-section", "there is a flag section, but no row has the flag mark")

    # approve: the last section is Approve, with the line of the contract
    headings = [line.strip() for line in lines if line.strip().startswith("## ")]
    if not headings or headings[-1] != APPROVE_HEADING:
        fail("approve", "the last section is not ## Approve")
    elif index["approve"] is not None:
        body = " ".join(line.strip() for line in lines[index["approve"] + 1:] if line.strip())
        total = sum(counts.values()) if counts is not None else sum(len(r) for r in rows.values())
        expected = APPROVE_FINDINGS if total else APPROVE_ZERO
        if body != expected:
            fail("approve", f"the approval text is not: {expected}")

    # tools: a bullet for each tool, and an install hint for each tool that is not on PATH
    if index["tools"] is not None:
        block = []
        for line in lines[index["tools"] + 1:]:
            if not line.strip():
                continue
            if not line.strip().startswith("- "):
                break
            block.append(line.strip())
        for tool in TOOLS:
            bullet = next((b for b in block if b.startswith(f"- {tool}:")), None)
            if bullet is None:
                fail("tools", f"no bullet for {tool}")
            elif "on PATH" not in bullet:
                fail("tools", f"the {tool} bullet does not say whether it is on PATH")
            elif "not on PATH" in bullet and "Install it with" not in bullet:
                fail("tools", f"{tool} is not on PATH, and the bullet has no install hint")
            elif "not on PATH" not in bullet and not re.search(r"on PATH \([^)]+\)", bullet):
                fail("tools", f"{tool} is on PATH, and the bullet has no version like (1.7.0)")

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
    failures = grade(text)
    print("\n".join(failures + ["FAIL" if failures else "PASS"]))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
