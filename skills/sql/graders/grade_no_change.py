#!/usr/bin/env python3
"""No-change grader (F) for a `/sql optimize` run: no file changes before the user approves.

Usage: grade_no_change.py TRACE

TRACE is a path, or - for stdin: a plugin eval trace, a file of JSON lines in stream-json form. A line of
type `assistant` holds `message.content`, a list of items. A call is an item of type `tool_use` with a
`name` and an `input`. The grader fails when a call changes a file: the tools Edit, Write and NotebookEdit,
or a Bash command that changes a file (mv, cp, rm, patch, tee, sed with an in-place option, or a redirect
that is not to /dev/null). Quotes are not parsed, so a quoted `>` counts (a false FAIL is safer than a
false PASS for a no-change check).
Output: one line "FAIL change: <message>" for each change, then PASS or FAIL.
Exit code: 0 pass, 1 fail, 2 usage error or unreadable trace (a line that is not JSON, or no `assistant`
line). Exit 2 prints a message on stderr and no PASS or FAIL line.
"""
import argparse
import json
import os
import re
import sys

EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")
CHANGING_WORDS = ("mv", "cp", "rm", "patch", "tee")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
DESCRIPTOR_COPY = re.compile(r"\d?>&[\d-]")
SEGMENT_SPLIT = re.compile(r"[|;&\n]")
REDIRECT = re.compile(r">>?\s*(\S*)")
SHORT_OPTION = re.compile(r"^-([A-Za-z]+)")


def read_trace(path):
    if path == "-":
        return sys.stdin.buffer.read().decode("utf-8")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def calls(text):
    """The (name, input) of each tool call. Raises ValueError for an unreadable trace."""
    found, assistant_lines = [], 0
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except ValueError:
            raise ValueError(f"line {number} is not JSON")
        if not isinstance(data, dict) or data.get("type") != "assistant":
            continue
        assistant_lines += 1
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for item in content if isinstance(content, list) else []:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                found.append((item.get("name"), item.get("input")))
    if not assistant_lines:
        raise ValueError("no line of type assistant")
    return found


def sed_in_place(words):
    for word in words:
        if word == "--in-place" or word.startswith("--in-place="):
            return True
        match = SHORT_OPTION.match(word)
        if match and not word.startswith("--") and "i" in match.group(1):
            return True
    return False


def bash_change(command):
    """The reason this command changes a file, or None."""
    command = DESCRIPTOR_COPY.sub("", command.replace("&>", ">"))
    for segment in SEGMENT_SPLIT.split(command):
        for match in REDIRECT.finditer(segment):
            if match.group(1) != "/dev/null":
                return f"a redirect to {match.group(1) or 'a file'}"
        words = segment.split()
        while words and (ASSIGNMENT.match(words[0]) or words[0] in ("sudo", "env")):
            words.pop(0)
        if not words:
            continue
        first = os.path.basename(words[0])
        if first in CHANGING_WORDS:
            return f"the command {first}"
        if first == "sed" and sed_in_place(words[1:]):
            return "sed with an in-place option"
    return None


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("trace")
    args = parser.parse_args(argv)
    try:
        found = calls(read_trace(args.trace))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        print(f"cannot read the trace: {error}", file=sys.stderr)
        return 2
    failures = []
    for name, data in found:
        if name in EDIT_TOOLS:
            failures.append(f"FAIL change: the {name} tool was called")
        elif name == "Bash":
            command = data.get("command") if isinstance(data, dict) else None
            reason = bash_change(command) if isinstance(command, str) else None
            if reason:
                failures.append(f"FAIL change: Bash changes a file ({reason}): {command.strip()[:120]!r}")
    print("\n".join(failures + ["FAIL" if failures else "PASS"]))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
