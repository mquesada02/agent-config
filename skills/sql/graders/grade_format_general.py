#!/usr/bin/env python3
"""Layout grader for a `/sql format` reply in the general fallback (the section General part of format.md).

Usage: grade_format_general.py REPLY (--general | --mixed)

REPLY is a path, or - for stdin. Blank lines are ignored.

With --general the reply is one general part: the fallback sentence on line 1, the title
`# sql format (general): <scope>` on line 2, then only `Note:` lines and bullets `- <path>:<line>: <style point>`,
and the last line `The skill edits no file in general mode.`

With --mixed the reply is a general part and then the PostgreSQL format report. It is split after the first line
that equals the last line of the general part. The first part is graded as --general. The second part must not be
empty, must have no line that starts with `# sql format` (no new title) and no line that starts with `**Result:`
(no Result line), and must have a line that starts with `Formatter:` (the PostgreSQL format report).

Output: one line "FAIL <check>: <message>" for each failed check, then PASS or FAIL.
Exit code: 0 pass, 1 fail, 2 usage error or unreadable reply (no PASS or FAIL line then).
"""
import argparse
import re
import sys

FALLBACK_SENTENCE = re.compile(
    r"^General guidance: this repo uses \S.*, which the skill does not cover\. "
    r"The advice is general, with no database and no rule script\.$")
TITLE = re.compile(r"^# sql format \(general\): \S")
BULLET = re.compile(r"^- \S+:[1-9][0-9]*: \S")
LAST_LINE = "The skill edits no file in general mode."


def read_reply(path):
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def text_lines(text):
    return [line.rstrip() for line in text.splitlines() if line.strip()]


def grade_general(lines):
    failures = []

    def fail(check, message):
        failures.append(f"FAIL {check}: {message}")

    if not lines or not FALLBACK_SENTENCE.match(lines[0]):
        fail("sentence", "line 1 is not the fallback sentence")
    if len(lines) < 2 or not TITLE.match(lines[1]):
        fail("title", "line 2 is not `# sql format (general): <scope>`")
    if not lines or lines[-1] != LAST_LINE:
        fail("last-line", f"the last line is not: {LAST_LINE}")
    for line in lines[2:-1]:
        if line.startswith("Note:"):
            continue
        if line.startswith("- "):
            if not BULLET.match(line):
                fail("bullet", f"not in the form `- <path>:<line>: <style point>`: {line}")
        else:
            fail("stray", f"not a Note line or a bullet: {line}")
    return failures


def grade_mixed(text):
    lines = text_lines(text)
    if LAST_LINE not in lines:
        return [f"FAIL mixed: no line equals the general last line: {LAST_LINE}"]
    split_at = lines.index(LAST_LINE) + 1
    failures = grade_general(lines[:split_at])
    second = lines[split_at:]
    if not second:
        failures.append("FAIL postgres-part: no PostgreSQL format report after the general part")
        return failures
    if any(line.startswith("# sql format") for line in second):
        failures.append("FAIL postgres-title: the PostgreSQL part has a `# sql format` title line")
    if any(line.startswith("**Result:") for line in second):
        failures.append("FAIL postgres-result: the PostgreSQL part has a Result line")
    if not any(line.startswith("Formatter:") for line in second):
        failures.append("FAIL postgres-report: the PostgreSQL part has no `Formatter:` line")
    return failures


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("reply")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--general", action="store_true")
    mode.add_argument("--mixed", action="store_true")
    args = parser.parse_args(argv)
    try:
        text = read_reply(args.reply)
    except (OSError, UnicodeDecodeError) as error:
        print(f"cannot read the reply: {error}", file=sys.stderr)
        return 2
    failures = grade_mixed(text) if args.mixed else grade_general(text_lines(text))
    print("\n".join(failures + ["FAIL" if failures else "PASS"]))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
