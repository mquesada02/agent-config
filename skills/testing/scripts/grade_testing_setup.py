#!/usr/bin/env python3
"""Setup grader for a `/testing setup` run: the written rules file is read through intake.py.

Usage: grade_testing_setup.py --repo <folder> --expect <json file> [--before <rules file>]

--repo is the repo folder after the run. --expect is a JSON object, all keys optional:
  set            an object from a dotted path to the value that the new file must hold (a path
                 splits at each ".", a key that holds a dot is not supported, a list is one value)
  unset          dotted paths that must be absent
  allow_missing  entries of rules.missing_sections that the intake check tolerates (the expected
                 gap: commands.<language> of a language whose test command cannot be detected)
  contains       lines that the prose outside the first toml block must hold, each as a whole line
  absent         strings that the file must not hold at all
--before is the rules file as it was before the run. Its settings come from intake.py run on a
temporary root that holds it.

Checks, in this order: intake (exit code 0, rules.found, rules.error null, no missing_sections
outside allow_missing, no unknown_ids, no disabled_without_reason), set, unset, contains, absent,
and with --before: settings (every leaf of the before settings that is not a set path is equal in
the new file; a list is a leaf) and prose (every non-blank line outside the first toml block of the
before file is a line outside that block in the new file). Every check except absent runs only
when the intake check has passed.
Output: one line "FAIL <check>: <message>" for each failed check, then a last line PASS or FAIL.
Exit code: 0 pass, 1 fail, 2 usage error (missing option, unreadable --expect or --before,
invalid JSON, unknown key, a --before file with rules.error set or not found).
intake.py is run through its CLI (the sibling script in the same folder): it is never imported.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
INTAKE = os.path.join(HERE, "intake.py")
RULES_FILE = os.path.join("docs", "agents", "testing.md")
LIST_KEYS = ("unset", "allow_missing", "contains", "absent")
EXPECT_KEYS = {"set", *LIST_KEYS}
TOML_OPEN = re.compile(r"^```toml(?:\s.*)?$")
FENCE_CLOSE = re.compile(r"^```\s*$")


class Usage(Exception):
    pass


def read_lines(path):
    with open(path, encoding="utf-8-sig") as handle:
        return [line.removesuffix("\r") for line in handle.read().split("\n")]


def split_blocks(lines):
    """(the prose lines outside the first toml block, whether a closed first block exists)."""
    for index, line in enumerate(lines):
        if TOML_OPEN.match(line):
            end = next((i for i in range(index + 1, len(lines)) if FENCE_CLOSE.match(lines[i])), None)
            if end is None:
                return lines[:index], False
            return lines[:index] + lines[end + 1:], True
    return list(lines), False


def run_intake(repo):
    """(JSON object or None, exit code, stderr) of intake.py run on a repo folder."""
    done = subprocess.run([sys.executable, "-I", INTAKE, repo], capture_output=True, text=True, encoding="utf-8")
    try:
        data = json.loads(done.stdout)
    except ValueError:
        data = None
    return (data if isinstance(data, dict) else None), done.returncode, done.stderr.strip()


def load_expect(path):
    try:
        with open(path, encoding="utf-8") as handle:
            expect = json.load(handle)
    except (OSError, ValueError) as error:
        raise Usage(f"cannot read --expect {path!r}: {error}")
    if not isinstance(expect, dict):
        raise Usage("--expect must be a JSON object")
    unknown = sorted(set(expect) - EXPECT_KEYS)
    if unknown:
        raise Usage(f"unknown --expect key: {', '.join(unknown)}")
    if "set" in expect and not isinstance(expect["set"], dict):
        raise Usage("--expect set must be an object")
    for key in LIST_KEYS:
        value = expect.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise Usage(f"--expect {key} must be a list of strings")
    return expect


def same(held, expected):
    """Equality that also needs the same type at every level: a boolean never equals a number, and an integer never equals a float."""
    if isinstance(held, dict) and isinstance(expected, dict):
        return held.keys() == expected.keys() and all(same(held[key], expected[key]) for key in held)
    if isinstance(held, list) and isinstance(expected, list):
        return len(held) == len(expected) and all(same(a, b) for a, b in zip(held, expected))
    return type(held) is type(expected) and held == expected


def lookup(settings, dotted):
    """(found, value) of a dotted path in nested dicts."""
    node = settings
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


def leaves(node, prefix=""):
    """(dotted path, value) of every leaf: a table is walked, any other value (a list too) is a leaf."""
    if isinstance(node, dict) and node:
        for key, value in node.items():
            yield from leaves(value, f"{prefix}.{key}" if prefix else key)
    elif prefix:
        yield prefix, node


def before_state(path):
    """(settings, prose lines) of the before file. Raises Usage when it cannot be used."""
    try:
        lines = read_lines(path)
    except (OSError, ValueError) as error:
        raise Usage(f"cannot read --before {path!r}: {error}")
    prose, closed = split_blocks(lines)
    with tempfile.TemporaryDirectory() as root:
        target = os.path.join(root, RULES_FILE)
        os.makedirs(os.path.dirname(target))
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
        data, _, stderr = run_intake(root)
    if data is None or data["rules"]["error"] is not None or not data["rules"]["found"] or not closed:
        raise Usage(f"--before file is not a readable rules file: {stderr or 'rules.error set or no toml block'}")
    return data["rules"]["settings"], prose


def grade(repo, expect, before):
    failures = []
    data, code, stderr = run_intake(repo)
    path = os.path.join(repo, RULES_FILE)
    try:
        lines = read_lines(path) if os.path.isfile(path) else [""]
    except (OSError, ValueError):
        lines = [""]  # intake.py reports the same file as rules.error
    text = "\n".join(lines)
    problems = []
    if data is None:
        problems.append(f"intake.py exit code {code}, no JSON: {stderr}")
    else:
        rules = data["rules"]
        if not rules["found"]:
            problems.append("the rules file does not exist")
        if rules["error"] is not None:
            error = rules["error"]
            problems.append(f"rules.error: {error['message']} (line {error['line']})")
        missing = [name for name in rules["missing_sections"] if name not in expect.get("allow_missing", [])]
        if missing and rules["error"] is None:
            problems.append(f"missing sections: {', '.join(missing)}")
        if rules["unknown_ids"]:
            problems.append(f"unknown ids: {', '.join(rules['unknown_ids'])}")
        if rules["disabled_without_reason"]:
            problems.append(f"disabled without a reason line: {', '.join(rules['disabled_without_reason'])}")
    failures += [f"FAIL intake: {problem}" for problem in problems]

    for needle in expect.get("absent", []):
        if needle in text:
            failures.append(f"FAIL absent: the file holds {needle!r}")
    if problems:
        return failures

    settings = data["rules"]["settings"]
    prose, _ = split_blocks(lines)
    for dotted, value in expect.get("set", {}).items():
        found, held = lookup(settings, dotted)
        if not found:
            failures.append(f"FAIL set: {dotted} is absent")
        elif not same(held, value):
            failures.append(f"FAIL set: {dotted} is {held!r}, expected {value!r}")
    for dotted in expect.get("unset", []):
        if lookup(settings, dotted)[0]:
            failures.append(f"FAIL unset: {dotted} is present")
    for line in expect.get("contains", []):
        if line not in prose:
            failures.append(f"FAIL contains: no prose line {line!r}")
    if before is not None:
        before_settings, before_prose = before
        approved = list(expect.get("set", {}))
        for dotted, value in leaves(before_settings):
            if any(dotted == item or dotted.startswith(item + ".") for item in approved):
                continue
            found, held = lookup(settings, dotted)
            if not found or not same(held, value):
                failures.append(f"FAIL settings: {dotted} was {value!r} and is {held if found else 'absent'!r}")
        kept = set(prose)
        for line in before_prose:
            if line.strip() and line not in kept:
                failures.append(f"FAIL prose: the line {line!r} was lost")
    return failures


def main(argv):
    parser = argparse.ArgumentParser(prog="grade_testing_setup.py")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--expect", required=True)
    parser.add_argument("--before")
    args = parser.parse_args(argv)
    try:
        expect = load_expect(args.expect)
        before = before_state(args.before) if args.before is not None else None
    except Usage as error:
        print(f"usage: {error}", file=sys.stderr)
        return 2
    failures = grade(args.repo, expect, before)
    for line in failures:
        print(line)
    print("FAIL" if failures else "PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
