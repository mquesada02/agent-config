#!/usr/bin/env python3
"""Report-structure grader for a cicd-pipelines review report (the report contract of review.md).

Usage: grade_report.py REPORT

REPORT is a path, or - for stdin. Checks: summary, sections, tables, numbering, counts, unique,
flag-section, lock-note, defaults, approve, tools (a bullet for each tool: its version when on PATH, an install hint when not).
A reply whose line 1 starts with "General guidance:" is a general reply (the fallback form). Its general part
(up to a normal report title, if one follows) gets the checks general-title, general-result, general-intake,
general-columns, general-rule, general-approve and general-last-line. A normal report that follows it (a mixed
repo) gets the checks of the normal form, listed at the top.
Output: one line "FAIL <check>: <message>" for each failed check, then PASS or FAIL.
Exit code: 0 pass, 1 fail, 2 usage error or unreadable report.
"""
import argparse
import re
import sys

TITLE = re.compile(r"^# cicd-pipelines review: \S")
SUMMARY = re.compile(r"^\*\*Result: ([0-9]{1,9}) critical, ([0-9]{1,9}) required, ([0-9]{1,9}) suggestions?\.\*\*$")
COLUMNS = ["#", "Rule", "Where", "Problem", "Fix"]
HEADINGS = {"critical": "## Critical", "required": "## Required", "suggestion": "## Suggestions"}
SEVERITIES = list(HEADINGS)
FLAG = "⚑"
LOCK = "🔒"
FLAG_HEADING = "## ⚑"
LOCK_NOTE = "🔒 = a protection write."
GRAPH_HEADING = "## Job graph after the fixes"
APPROVE_HEADING = "## Approve"
APPROVE_FINDINGS = "Reply with the findings to fix: `all`, `none`, a list such as `1,3,5`, or a range such as `1-12`."
APPROVE_ZERO = "There is nothing to approve."
TOOLS = ("actionlint", "zizmor")
RULE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")
GENERAL_PREFIX = "General guidance:"
GENERAL_TITLE = re.compile(r"^# cicd-pipelines general review: \S")
GENERAL_COLUMNS = ["Rule", "Where", "Problem", "Fix"]
GENERAL_LAST = "The skill edits no file in general mode."
GENERAL_ID = re.compile(r"^GEN-[0-9]+$")
SEPARATOR_CELL = re.compile(r"^:?-+:?$")
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
    ("lock note", lambda s: s.startswith(LOCK_NOTE)),
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
            rule = cells[1].replace(FLAG, "").replace(LOCK, "").strip() if len(cells) > 1 else ""
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
    created = index["title"] is not None and lines[index["title"]].strip().endswith("(created)")
    # a created report lists the prerequisites that create does not make, with no PROTECT row
    if has_section and not any_flag and not created:
        fail("flag-section", "there is a flag section, but no row has the flag mark")

    # lock-note: the note exists exactly when a row has the lock mark (its place is part of the section order)
    any_lock = any(LOCK in cells[1] for severity in SEVERITIES for cells in rows[severity] if len(cells) > 1)
    has_note = index["lock note"] is not None
    if any_lock and not has_note:
        fail("lock-note", "a row has the lock mark, but there is no lock note")
    if has_note and not any_lock:
        fail("lock-note", "there is a lock note, but no row has the lock mark")

    # defaults: the Intake line ends with the defaults that the review used
    if index["intake"] is not None and "Defaults:" not in lines[index["intake"]]:
        fail("defaults", "the Intake line has no Defaults: part")

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


def tables(lines):
    """Each table of the lines as (header cells, data rows): a table is a run of lines that start with `|`.
    Its first row is the header, and a separator row (every cell is dashes, with optional colons) is skipped.
    An empty first cell is not a separator: that row is a data row."""
    found, current = [], None
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            current = None
            continue
        cells = split_row(stripped)
        if current is None:
            current = (cells, [])
            found.append(current)
        elif not all(SEPARATOR_CELL.match(cell) for cell in cells):
            current[1].append(cells)
    return found


def grade_general(lines):
    """The failure lines of the general part of a general reply (the form of the general review)."""
    failures = []

    def fail(check, message):
        failures.append(f"FAIL {check}: {message}")

    stripped = [line.strip() for line in lines]
    if not any(GENERAL_TITLE.match(s) for s in stripped):
        fail("general-title", "no title like # cicd-pipelines general review: <scope>")
    if not any(SUMMARY.match(s) for s in stripped):
        fail("general-result", "no line like **Result: N critical, N required, N suggestions.**")
    intake = next((s for s in stripped if s.startswith("Intake:")), None)
    if intake is None or "Defaults:" not in intake:
        fail("general-intake", "no Intake: line with a Defaults: part")
    for header, rows in tables(lines):
        if header != GENERAL_COLUMNS:
            fail("general-columns", f"the table columns are not {GENERAL_COLUMNS}")
        for cells in rows:
            if not GENERAL_ID.match(cells[0]):
                fail("general-rule", f"the Rule cell {cells[:1]} is not one GEN id")
    if APPROVE_HEADING in stripped:
        fail("general-approve", "the general part has a ## Approve section")
    last = next((s for s in reversed(stripped) if s), "")
    if last != GENERAL_LAST:
        fail("general-last-line", f"the last line of the general part is not: {GENERAL_LAST}")
    return failures


def grade_reply(text):
    """A reply whose line 1 starts with `General guidance:` is graded in two parts: the general part with the
    general-form check, and the normal report after it (a mixed repo), if any, with the existing check.
    Any other reply goes through the existing check."""
    lines = text.splitlines()
    if not lines or not lines[0].startswith(GENERAL_PREFIX):
        return grade(text)
    normal_at = first_index(lines, lambda s: bool(TITLE.match(s)))
    general = lines if normal_at is None else lines[:normal_at]
    failures = grade_general(general)
    if normal_at is not None:
        failures += grade("\n".join(lines[normal_at:]))
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
    failures = grade_reply(text)
    print("\n".join(failures + ["FAIL" if failures else "PASS"]))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
