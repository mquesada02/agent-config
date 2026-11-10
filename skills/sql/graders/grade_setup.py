#!/usr/bin/env python3
"""Setup grader (D) for a `/sql setup` run: the diff is shown before any write, and the written TOML is right.

Usage: grade_setup.py TRACE --repo <folder> --expect <json file> [--allowlist <file> --key <repo key>]

TRACE is a path, or - for stdin: a plugin eval trace in stream-json form (JSON lines). A line of type
`assistant` holds `message.content`, a list of items: `tool_use` (id, name, input) and `text`. A line
of type `user` holds `tool_result` items tied to a call by `tool_use_id`. `--repo` is the repo folder
after the run. `--allowlist` is the allowlist file and `--key` the repo key (so the grader needs no git
repo).

`--expect` is a JSON object, all keys optional: `written` (boolean, default true), `settings` (a table
of tables that the first toml block of the rules file must equal for those keys; a list is compared
without regard to the order of its items), `contains` (strings that the rules file must hold, each as a
whole line or a whole rule text), `absent` (strings that it must not hold), `unchanged_lines` (lines of
the old rules file; each must be a line of the new file), `services` (the services of the allowlist
entry) or `no_allowlist` true (the file has no entry for the key). `services` and `no_allowlist`
together, or either one without `--allowlist` and `--key`, is a usage error.

A change call is the tool Write, Edit or NotebookEdit on `docs/agents/sql.md` or `allowlist.toml`, a
`setup_files.py write` call, or a Bash command that names one of the two files and holds a redirect,
tee, cp, mv or sed -i. A plan call is a Bash call that runs `setup_files.py plan`. Checks: `order` (a
change call has an earlier plan result; with `written` false there is no change call), `shown` (the
assistant text after the latest plan result holds every added line of the plan diffs), `digest` (a
`write` call carries the digest of the latest plan; a Write call holds its `text`), `toml`,
`unchanged` and `allowlist`.

Output: one line "FAIL <check>: <message>" for each failure, then PASS or FAIL.
Exit code: 0 pass, 1 fail, 2 usage error or unreadable trace (a line that is not JSON, or no `assistant`
line). Exit 2 prints a message on stderr and no PASS or FAIL line.
"""
import argparse
import collections
import json
import os
import re
import sys
import tomllib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import allowlist as allowlist_reader  # noqa: E402
import rules_file  # noqa: E402

EDIT_TOOLS = ("Write", "Edit", "NotebookEdit")
RULES_SUFFIX = "docs/agents/sql.md"
ALLOWLIST_NAME = "allowlist.toml"
SEGMENT_SPLIT = re.compile(r"[|;&\n]")
FILE_NAMED = re.compile(r"docs/agents/sql\.md|allowlist\.toml")
DEV_NULL = re.compile(r"\d?>>?\s*/dev/null\b")
REDIRECT = re.compile(r">>?\s*[^\s&>]")
WRITE_CALL = re.compile(r"setup_files\.py\s+write\b")
PLAN_CALL = re.compile(r"setup_files\.py\s+plan\b")
CONFIRM = re.compile(r"--confirm(?:\s+|=)['\"]?([0-9A-Za-z]+)")
EXPECT_KEYS = {"written", "settings", "contains", "absent", "unchanged_lines", "services", "no_allowlist"}
SHORT_OPTION = re.compile(r"^-([A-Za-z]+)")


class Usage(Exception):
    pass


def read_text(path):
    if path == "-":
        return sys.stdin.buffer.read().decode("utf-8")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def result_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(item.get("text", "") for item in content if isinstance(item, dict))
    return ""


def events(text):
    """The trace as a list of (kind, ...) in order. Raises ValueError for an unreadable trace."""
    found, assistant_lines = [], 0
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except ValueError:
            raise ValueError(f"line {number} is not JSON")
        if not isinstance(data, dict):
            continue
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        items = content if isinstance(content, list) else []
        if data.get("type") == "assistant":
            assistant_lines += 1
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "tool_use":
                    found.append(("call", item.get("id"), item.get("name"), item.get("input")))
                elif item.get("type") == "text" and isinstance(item.get("text"), str):
                    found.append(("text", item["text"]))
        elif data.get("type") == "user":
            for item in items:
                if isinstance(item, dict) and item.get("type") == "tool_result":
                    found.append(("result", item.get("tool_use_id"), result_text(item.get("content"))))
    if not assistant_lines:
        raise ValueError("no line of type assistant")
    return found


def sed_in_place(words):
    for word in words:
        if word == "--in-place" or word.startswith("--in-place="):
            return True
        match = SHORT_OPTION.match(word)
        if match and "i" in match.group(1):
            return True
    return False


def bash_changes_a_file(command):
    for segment in SEGMENT_SPLIT.split(command):
        segment = DEV_NULL.sub("", segment)
        if not FILE_NAMED.search(segment):
            continue
        words = segment.split()
        if REDIRECT.search(segment) or any(os.path.basename(w) in ("tee", "cp", "mv") for w in words):
            return True
        if any(os.path.basename(w) == "sed" for w in words) and sed_in_place(words):
            return True
    return False


def change_target(name, data):
    """('write', command) / ('file', path) / ('bash', command) for a change call, else None."""
    if not isinstance(data, dict):
        return None
    if name in EDIT_TOOLS:
        path = data.get("file_path") or data.get("notebook_path") or data.get("path") or ""
        if isinstance(path, str) and (path.endswith(RULES_SUFFIX) or os.path.basename(path) == ALLOWLIST_NAME):
            return ("file", path)
    elif name == "Bash":
        command = data.get("command")
        if isinstance(command, str):
            if WRITE_CALL.search(command):
                return ("write", command)
            if bash_changes_a_file(command):
                return ("bash", command)
    return None


def parse_plan(text):
    """The first JSON object of a tool result that starts with an `ok` key, or None."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{\s*\"ok\"\s*:", text):
        try:
            value, _ = decoder.raw_decode(text, match.start())
        except ValueError:
            continue
        return value
    return None


def added_lines(plan):
    found = []
    for name in ("rules_file", "allowlist"):
        part = plan.get(name)
        diff = part.get("diff") if isinstance(part, dict) else None
        for line in (diff or "").splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                body = line[1:].rstrip()
                if body:
                    found.append(body)
    return found


def check_order_shown_digest(trace, written):
    failures = []
    plan_ids = set()
    latest = None  # (plan, index of its result)
    texts = []  # (index, text)
    for index, event in enumerate(trace):
        kind = event[0]
        if kind == "text":
            texts.append((index, event[1]))
        elif kind == "call":
            _, identifier, name, data = event
            command = data.get("command") if isinstance(data, dict) else None
            if name == "Bash" and isinstance(command, str) and PLAN_CALL.search(command):
                plan_ids.add(identifier)
            target = change_target(name, data)
            if target is None:
                continue
            what = target[1].strip()[:100]
            if not written:
                failures.append(f"FAIL order: a change call with written false: {what!r}")
                continue
            if latest is None:
                failures.append(f"FAIL order: a change call before any plan result: {what!r}")
                continue
            plan, plan_index = latest
            shown = "\n".join(t for i, t in texts if i > plan_index)
            missing = [line for line in added_lines(plan) if line not in shown]
            if missing:
                failures.append(f"FAIL shown: the diff line {missing[0]!r} was not shown before the change: {what!r}")
            if target[0] == "write":
                match = CONFIRM.search(target[1])
                if not match or match.group(1) != plan.get("digest"):
                    failures.append(f"FAIL digest: the write call has no --confirm with the latest plan digest: {what!r}")
            elif target[0] == "file" and name == "Write":
                failures.extend(check_write_content(plan, target[1], data.get("content")))
        elif kind == "result" and event[1] in plan_ids:
            plan = parse_plan(event[2])
            if plan is not None:
                latest = (plan, index)
    return failures


def check_write_content(plan, path, content):
    key = "rules_file" if path.endswith(RULES_SUFFIX) else "allowlist"
    part = plan.get(key)
    expected = part.get("text") if isinstance(part, dict) else None
    if content != expected:
        return [f"FAIL digest: the Write content of {os.path.basename(path)} differs from the text of the latest plan"]
    return []


def same_without_order(left, right):
    if isinstance(left, list) and isinstance(right, list):
        key = lambda item: json.dumps(item, sort_keys=True, default=str)  # noqa: E731
        return collections.Counter(map(key, left)) == collections.Counter(map(key, right))
    return json.dumps(left, sort_keys=True, default=str) == json.dumps(right, sort_keys=True, default=str)


def check_rules(repo, expect, written):
    path = os.path.join(repo, rules_file.RULES_FILE)
    if not written:
        return ["FAIL toml: the rules file exists but written is false"] if os.path.exists(path) else []
    if not os.path.exists(path):
        return ["FAIL toml: the rules file does not exist"]
    read = rules_file.read_rules(repo)
    if read["error"]:
        return [f"FAIL toml: the rules file cannot be read: {read['error']['message']}"]
    failures = []
    for section, table in expect.get("settings", {}).items():
        for key, value in table.items():
            got = read["settings"].get(section, {})
            if key not in got:
                failures.append(f"FAIL toml: {section}.{key} is not in the rules file")
            elif not same_without_order(got[key], value):
                failures.append(f"FAIL toml: {section}.{key} is {json.dumps(got[key])}, expected {json.dumps(value)}")
    with open(path, encoding="utf-8-sig") as handle:
        text = handle.read()
    lines = [line.rstrip("\r") for line in text.split("\n")]
    rule_texts = {m.group(1) for m in (re.match(r"^\s*[-*]\s+(.*\S)\s*$", line) for line in lines) if m}
    for wanted in expect.get("contains", []):
        if wanted not in [line.strip() for line in lines] and wanted not in rule_texts:
            failures.append(f"FAIL toml: the rules file does not hold {wanted!r}")
    for unwanted in expect.get("absent", []):
        if unwanted in text:
            failures.append(f"FAIL toml: the rules file holds {unwanted!r}")
    for line in expect.get("unchanged_lines", []):
        if line not in lines:
            failures.append(f"FAIL unchanged: the line {line!r} is not in the rules file")
    return failures


def check_allowlist(path, key, expect):
    if "services" not in expect and not expect.get("no_allowlist"):
        return []
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError) as error:
        return [f"FAIL allowlist: the allowlist file cannot be read: {error}"]
    if expect.get("no_allowlist"):
        return [f"FAIL allowlist: an entry exists for {key}"] if key in data else []
    if key not in data:
        return [f"FAIL allowlist: no entry for {key}"]
    try:
        services, _ = allowlist_reader.validate(data[key])
    except allowlist_reader.Malformed as error:
        return [f"FAIL allowlist: the entry is malformed: {error}"]
    if not same_without_order(services, expect["services"]):
        return [f"FAIL allowlist: services are {json.dumps(services)}, expected {json.dumps(expect['services'])}"]
    return []


def load_expect(path):
    try:
        with open(path, encoding="utf-8") as handle:
            expect = json.load(handle)
    except (OSError, ValueError) as error:
        raise Usage(f"cannot read --expect: {error}")
    if not isinstance(expect, dict) or set(expect) - EXPECT_KEYS:
        raise Usage("--expect must be a JSON object with the keys: " + ", ".join(sorted(EXPECT_KEYS)))
    if "written" in expect and not isinstance(expect["written"], bool):
        raise Usage("written must be true or false")
    settings = expect.get("settings", {})
    if not isinstance(settings, dict) or not all(isinstance(t, dict) for t in settings.values()):
        raise Usage("settings must be a table of tables")
    for name in ("contains", "absent", "unchanged_lines", "services"):
        value = expect.get(name, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise Usage(f"{name} must be a list of strings")
    if "services" in expect and expect.get("no_allowlist"):
        raise Usage("services and no_allowlist cannot be used together")
    return expect


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("trace")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--expect", required=True)
    parser.add_argument("--allowlist")
    parser.add_argument("--key")
    args = parser.parse_args(argv)
    try:
        expect = load_expect(args.expect)
        if ("services" in expect or expect.get("no_allowlist")) and not (args.allowlist and args.key):
            raise Usage("services and no_allowlist need --allowlist and --key")
        if not os.path.isdir(args.repo):
            raise Usage("--repo is not a folder: " + args.repo)
        trace = events(read_text(args.trace))
    except Usage as error:
        print(str(error), file=sys.stderr)
        return 2
    except (OSError, UnicodeDecodeError, ValueError) as error:
        print(f"cannot read the trace: {error}", file=sys.stderr)
        return 2
    written = expect.get("written", True)
    failures = check_order_shown_digest(trace, written)
    failures += check_rules(args.repo, expect, written)
    failures += check_allowlist(args.allowlist, args.key, expect)
    print("\n".join(failures + ["FAIL" if failures else "PASS"]))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
