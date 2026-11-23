#!/usr/bin/env python3
"""Report-layout grader (I) for a `/sql optimize` report (the report contract of optimize.md).

Usage: grade_report.py REPORT [--disabled ID...] [--general | --mixed]

REPORT is a path, or - for stdin. Checks: title, summary, sections, disabled, tables, rows, numbering,
counts, unique, where, approve, rewrite. With --disabled, the ids of the `Disabled rules:` line must be
exactly that set, and --disabled with no id means that the report has no `Disabled rules:` line. In every
case no table row may hold a disabled id of the line.

With --general the report is one general part (the form of the section General part of optimize.md): the
fallback sentence, the title `# sql optimize (general): <scope>`, the Result line, GEN rows whose Rule cell
is `GEN-NN (<Source>)`, no `## Approve` section, no `Rewrite` in a Fix cell, and the last line
`The skill edits no file in general mode.` With --mixed the report is a general part and then a PostgreSQL
report: it is split at the first line that matches `# sql optimize: <scope>`, the first part is graded as
--general and the second part as the PostgreSQL report. With --mixed, the --disabled ids that start with
`GEN-` go to the general part and the other ids go to the PostgreSQL part (a part with no id must have no
`Disabled rules:` line).

Output: one line "FAIL <check>: <message>" for each failed check, then PASS or FAIL.
Exit code: 0 pass, 1 fail, 2 usage error, unreadable report or a general module with no `## Sources`
section (no PASS or FAIL line then).
"""
import argparse
import functools
import os
import re
import sys

TITLE = re.compile(r"^# sql optimize: \S")
GENERAL_TITLE = re.compile(r"^# sql optimize \(general\): \S")
FALLBACK_SENTENCE = re.compile(
    r"^General guidance: this repo uses \S.*, which the skill does not cover\. "
    r"The advice is general, with no database and no rule script\.$")
GENERAL_LAST_LINE = "The skill edits no file in general mode."
GENERAL_RULE_CELL = re.compile(r"^(GEN-[0-9]{2}) \((.+)\)$")
GENERAL_MODULE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dialects", "general.md")
SUMMARY = re.compile(r"^\*\*Result: ([0-9]{1,9}) critical, ([0-9]{1,9}) required, ([0-9]{1,9}) suggestions?\.\*\*$")
COLUMNS = ["#", "Rule", "Where", "Problem", "Fix"]
HEADINGS = {"critical": "## Critical", "required": "## Required", "suggestion": "## Suggestions"}
SEVERITIES = list(HEADINGS)
APPROVE_HEADING = "## Approve"
APPROVE_FINDINGS = "Reply with the findings to fix: `all`, `none`, a list such as `1,3,5`, or a range such as `1-12`."
APPROVE_ZERO = "There is nothing to approve."
REWRITE_LABELS = (
    "Rewrite (proven: database diff and repo tests):",
    "Rewrite (proven by the database diff only: no repo tests ran):",
    "Rewrite (partial proof by the database diff: order not checked, ties):",
    "Rewrite (partial proof by the database diff: order not checked, sort keys):",
    "Rewrite (partial proof by the database diff: order not checked, B order):",
    "Rewrite (unproven: no database):",
    "Rewrite (unproven: the database diff failed):",
    "Rewrite (unproven: write statement, no database diff):",
    "Rewrite (unproven: statement not complete, no database diff):",
)
RULE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")
PLACE = re.compile(r"^(\S+):([1-9][0-9]*)(?:-([1-9][0-9]*))?$")
DISABLED_LINE = re.compile(r"^Disabled rules: (.*)\.$")
UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


def read_report(path):
    if path == "-":
        return sys.stdin.buffer.read().decode("utf-8")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def is_row(line):
    return len(line) > 1 and line.startswith("|") and line.endswith("|")


def split_row(line):
    return [cell.strip() for cell in UNESCAPED_PIPE.split(line.strip()[1:-1])]


@functools.lru_cache(maxsize=None)
def general_sources():
    """The names of the `## Sources` entries of the general module, and `skill rule`."""
    with open(GENERAL_MODULE, encoding="utf-8") as handle:
        text = handle.read()
    heading = re.search(r"^## Sources[ \t]*$", text, re.M)
    if not heading:
        raise ValueError(f"the general module has no ## Sources section: {GENERAL_MODULE}")
    return set(re.findall(r"^- \*\*(.+?):\*\*", text[heading.end():], re.M)) | {"skill rule"}


def grade(text, disabled_flag, general=False):
    lines = [line.strip() for line in text.splitlines()]
    failures = []

    def fail(check, message):
        failures.append(f"FAIL {check}: {message}")

    non_blank = [i for i, line in enumerate(lines) if line]

    # general part: the fallback sentence is line 1, the last line is fixed, and it is not part of a table
    offset = 0
    if general:
        offset = 1
        if not non_blank or not FALLBACK_SENTENCE.match(lines[non_blank[0]]):
            fail("fallback", "the first line is not the fallback sentence")
        if not non_blank or lines[non_blank[-1]] != GENERAL_LAST_LINE:
            fail("last", f"the last line is not `{GENERAL_LAST_LINE}`")
        else:
            lines = lines[:non_blank[-1]]
            non_blank = non_blank[:-1]

    heading_at = {name: next((i for i, line in enumerate(lines) if line == heading), None)
                  for name, heading in HEADINGS.items()}
    approve_at = next((i for i, line in enumerate(lines) if line == APPROVE_HEADING), None)

    # title: the first non-blank line (the second line of a general part)
    title_at = non_blank[offset] if len(non_blank) > offset else None
    title_form = GENERAL_TITLE if general else TITLE
    if title_at is None or not title_form.match(lines[title_at]):
        fail("title", "the title line is not `# sql optimize (general): <scope>`" if general
             else "the first line is not `# sql optimize: <scope>`")

    # summary: the line after the title
    counts = None
    summary_at = next((i for i, line in enumerate(lines) if SUMMARY.match(line)), None)
    if summary_at is None:
        fail("summary", "no line like **Result: N critical, N required, N suggestions.**")
    else:
        counts = dict(zip(SEVERITIES, (int(n) for n in SUMMARY.match(lines[summary_at]).groups())))
        if len(non_blank) < offset + 2 or summary_at != non_blank[offset + 1]:
            fail("sections", "the summary is not the line after the title")

    # sections: every `## ` heading is known, in contract order, Approve last (never in a general part)
    headings = [(i, line) for i, line in enumerate(lines) if line.startswith("## ")]
    allowed = list(HEADINGS.values()) + ([] if general else [APPROVE_HEADING])
    for _, line in headings:
        if line not in allowed:
            fail("sections", f"unknown heading: {line}")
    known = [allowed.index(line) for _, line in headings if line in allowed]
    if known != sorted(known):
        fail("sections", "the tables are not in the order critical, required, suggestions")
    if known and len(known) != len(set(known)):
        fail("sections", "a heading appears twice")
    if not general and (not headings or headings[-1][1] != APPROVE_HEADING):
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
        if not disabled_flag:
            if disabled_lines:
                fail("disabled", "a Disabled rules line, but no disabled id is expected")
        elif not disabled_lines:
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
        if (len(block) < 2 or not all(is_row(line) for line in block[:2])
                or split_row(block[0]) != COLUMNS or not set(block[1]) <= set("|-: ")):
            fail("tables", f"the {severity} table has not the header {COLUMNS} and a separator row")
        for line in block[2:]:
            if not is_row(line):
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
    # (a general row holds the GEN id and its Source in parentheses, and the Source is one of the module)
    seen = set()
    sources = general_sources() if general else None
    for cells in all_rows:
        rule = cells[1]
        if general:
            found = GENERAL_RULE_CELL.match(rule)
            if not found:
                fail("unique", f"the Rule cell {rule!r} is not `GEN-NN (<Source>)`")
                continue
            rule = found.group(1)
            if found.group(2) not in sources:
                fail("unique", f"{rule}: the Source {found.group(2)!r} is not an entry of the general module or `skill rule`")
        elif not RULE_ID.match(rule):
            fail("unique", f"the Rule cell {rule!r} is not one rule id")
            continue
        if rule in seen:
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

    # rewrite: a Fix cell with the word Rewrite starts with one of the labels of the module and holds `database diff`
    # (a general part has no rewrite at all)
    for cells in all_rows:
        fix = cells[4]
        if re.search(r"\bRewrite\b", fix):
            if general:
                fail("rewrite", f"{cells[1]}: a general part has no rewrite")
                continue
            if not fix.startswith(REWRITE_LABELS):
                fail("rewrite", f"{cells[1]}: the Fix cell does not start with one of the rewrite labels of the module")
            if "database diff" not in fix:
                fail("rewrite", f"{cells[1]}: the Fix cell does not hold the words `database diff`")

    # approve: the text of the contract
    if not general and approve_at is not None and headings[-1][1] == APPROVE_HEADING:
        body = " ".join(line for line in lines[approve_at + 1:] if line)
        expected = APPROVE_FINDINGS if all_rows else APPROVE_ZERO
        if body != expected:
            fail("approve", f"the approval text is not: {expected}")
    return failures


def grade_mixed(text, disabled_flag):
    """A general part, then a PostgreSQL report that starts at its own title line."""
    lines = text.splitlines()
    split_at = next((i for i, line in enumerate(lines) if TITLE.match(line.strip())), None)
    if split_at is None:
        return ["FAIL mixed: no PostgreSQL title line `# sql optimize: <scope>` after the general part"]
    general_flag = pg_flag = None
    if disabled_flag is not None:
        general_flag = [i for i in disabled_flag if i.startswith("GEN-")]
        pg_flag = [i for i in disabled_flag if not i.startswith("GEN-")]
    first = "\n".join(lines[:split_at])
    second = "\n".join(lines[split_at:])
    return (grade(first, general_flag, general=True) + grade(second, pg_flag))


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report")
    parser.add_argument("--disabled", nargs="*", default=None, metavar="ID")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--general", action="store_true")
    mode.add_argument("--mixed", action="store_true")
    args = parser.parse_args(argv)
    try:
        text = read_report(args.report)
    except (OSError, UnicodeDecodeError) as error:
        print(f"cannot read the report: {error}", file=sys.stderr)
        return 2
    try:
        if args.mixed:
            failures = grade_mixed(text, args.disabled)
        else:
            failures = grade(text, args.disabled, general=args.general)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    print("\n".join(failures + ["FAIL" if failures else "PASS"]))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
