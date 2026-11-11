#!/usr/bin/env python3
"""Refusal grader (H) for a DB eval run: the refusals and the failures of `pg_run` happen.

Usage: grade_refusals.py TRACE --expect KIND[:ARG] ...

TRACE is a path, or - for stdin: a stream-json trace (a plugin eval trace or the output of
`claude -p --output-format stream-json`), a file of JSON lines. A line of type `assistant` holds
`message.content`, a list of items; a call is an item of type `tool_use`. A line of type `user` holds the
items of type `tool_result`, tied to a call by `tool_use_id`. A `pg_run` call is a Bash call whose command
holds `pg_run.py`. The result of such a call is the JSON object that starts with `{"ok":` in the text of its
tool result (the eval shell can add text around it). A result with no such object is not a `pg_run` result.

Kinds (each needs at least one such result, except `no_connection`):
- not_allowed[:SERVICE]    `error` is `not_allowed` (of a call with `--service SERVICE` when given)
- refused[:REASON]         `error` is `refused` (with the guard `reason` REASON when given)
- connection_failed[:SERVICE]  `error` is `connection_failed`
- plan[:SERVICE]           `ok` is true and `plan` is a non-empty list
- facts[:SERVICE]          `ok` is true and `facts` is a non-empty object
- analyzed[:SERVICE]       `ok` is true, `plan` is a non-empty list and `ran` is `analyze` (a write-mode run)
- sequence_warning[:SERVICE]  `ok` is true and `warnings` holds `sequence`
- downgraded[:SERVICE]     `ok` is true, `ran` is `explain`, `reason` is a non-empty string and `plan` is a
                           non-empty list (a write-mode run that went down to a plain EXPLAIN)
  The input of the three write kinds is the first `{"ok":` object of the tool result: on the piped call it is
  the output of `plan_findings.py`, which passes `ran`, `reason`, `downgrade` and `warnings` through.
- diff[:SERVICE]           `ok` is true and `equal` is a boolean (the output of `pg_run.py diff`, used directly)
- no_connection:SERVICE    every `pg_run` call with `--service SERVICE` has an `error` of `not_allowed`;
                           the run may have no such call

Always: no Bash call runs a database client by hand (the first word of a command segment is psql, pg_dump,
pg_isready, pgcli, createdb, dropdb or docker), and, unless `plan`, `analyzed`, `sequence_warning` or
`downgraded` or `diff` is expected, no `pg_run` result has `ok` true (when `facts` is expected, an `ok` result with a
non-empty `facts` object is allowed too). The segment
split is the one of grade_no_change.py.
Output: one line "FAIL <check>: <message>" for each failure, then PASS or FAIL.
Exit code: 0 pass, 1 fail, 2 usage error (an unknown kind, or no_connection with no SERVICE) or an
unreadable trace (a line that is not JSON, or no `assistant` line); a message on stderr, no PASS or FAIL line.
"""
import argparse
import json
import os
import re
import sys

KINDS = (
    "not_allowed", "refused", "connection_failed", "plan", "facts", "analyzed", "sequence_warning", "downgraded",
    "diff", "no_connection",
)
OK_KINDS = ("plan", "analyzed", "sequence_warning", "downgraded", "diff")
CLIENTS = ("psql", "pg_dump", "pg_isready", "pgcli", "createdb", "dropdb", "docker")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
SEGMENT_SPLIT = re.compile(r"[|;&\n]")
SERVICE_ARGUMENT = re.compile(r"--service[ =]+['\"]?([A-Za-z0-9_.-]+)")
RESULT_START = re.compile(r'\{"ok":')


class Usage(Exception):
    pass


def read_trace(path):
    if path == "-":
        return sys.stdin.buffer.read().decode("utf-8")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def result_text(content):
    """The text of a tool result content: a string, or a list of text items."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(item.get("text", "") for item in content if isinstance(item, dict))
    return ""


def parse_trace(text):
    """(Bash commands in order, {tool_use_id: command}, {tool_use_id: result text}). Raises ValueError."""
    commands, by_id, results, assistant_lines = [], {}, {}, 0
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
        if data.get("type") == "assistant":
            assistant_lines += 1
        for item in content if isinstance(content, list) else []:
            if not isinstance(item, dict):
                continue
            if data.get("type") == "assistant" and item.get("type") == "tool_use" and item.get("name") == "Bash":
                command = item.get("input", {}).get("command") if isinstance(item.get("input"), dict) else None
                if isinstance(command, str):
                    commands.append(command)
                    by_id[item.get("id")] = command
            elif data.get("type") == "user" and item.get("type") == "tool_result":
                results[item.get("tool_use_id")] = result_text(item.get("content"))
    if not assistant_lines:
        raise ValueError("no line of type assistant")
    return commands, by_id, results


def first_object(text):
    """The JSON object that starts with {"ok": in the text, or None."""
    decoder = json.JSONDecoder()
    for match in RESULT_START.finditer(text):
        try:
            value, _ = decoder.raw_decode(text, match.start())
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def pg_run_results(by_id, results):
    """[(service or None, result object)] for each pg_run call that has a pg_run result."""
    found = []
    for call_id, command in by_id.items():
        if "pg_run.py" not in command or call_id not in results:
            continue
        result = first_object(results[call_id])
        if result is not None:
            match = SERVICE_ARGUMENT.search(command)
            found.append((match.group(1) if match else None, result))
    return found


def client_calls(commands):
    """The commands that start a database client by hand."""
    found = []
    for command in commands:
        for segment in SEGMENT_SPLIT.split(command):
            words = segment.split()
            while words and (ASSIGNMENT.match(words[0]) or words[0] in ("sudo", "env")):
                words.pop(0)
            if words and os.path.basename(words[0]) in CLIENTS:
                found.append(command)
                break
    return found


def parse_kind(spec):
    kind, _, argument = spec.partition(":")
    if kind not in KINDS:
        raise Usage(f"unknown kind: {kind}")
    if kind == "no_connection" and not argument:
        raise Usage("no_connection needs :SERVICE")
    return kind, argument or None


def has_plan(result):
    """True for an ok result that has a non-empty `plan` list."""
    return result.get("ok") is True and isinstance(result.get("plan"), list) and bool(result["plan"])


def has_facts(result):
    """True for an ok result that has a non-empty `facts` object."""
    return result.get("ok") is True and isinstance(result.get("facts"), dict) and bool(result["facts"])


def has_diff(result):
    """True for an ok result of `pg_run diff`: `equal` is a boolean."""
    return result.get("ok") is True and type(result.get("equal")) is bool


def is_analyzed(result):
    return has_plan(result) and result.get("ran") == "analyze"


def has_sequence_warning(result):
    return result.get("ok") is True and isinstance(result.get("warnings"), list) and "sequence" in result["warnings"]


def is_downgraded(result):
    reason = result.get("reason")
    return has_plan(result) and result.get("ran") == "explain" and isinstance(reason, str) and bool(reason)


OK_CHECKS = {
    "plan": has_plan, "facts": has_facts, "analyzed": is_analyzed, "sequence_warning": has_sequence_warning,
    "downgraded": is_downgraded, "diff": has_diff,
}


def matches(kind, argument, service, result):
    """True when one pg_run result is of the expected kind (for `refused` the argument is the reason)."""
    if kind in OK_CHECKS:
        return OK_CHECKS[kind](result) and (argument is None or service == argument)
    if result.get("error") != kind:
        return False
    if kind == "refused":
        return argument is None or result.get("reason") == argument
    return argument is None or service == argument


def check(kind, argument, calls):
    """The FAIL line of one expected kind, or None."""
    if kind == "no_connection":
        bad = any(service == argument and result.get("error") != "not_allowed" for service, result in calls)
        return f"FAIL connection: a call of {argument} did not end with not_allowed" if bad else None
    if any(matches(kind, argument, service, result) for service, result in calls):
        return None
    return f"FAIL expected: {kind}{':' + argument if argument else ''} not found"


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("trace")
    parser.add_argument("--expect", nargs="*", default=[])
    args = parser.parse_args(argv)
    try:
        expected = [parse_kind(spec) for spec in args.expect]
    except Usage as error:
        print(f"usage: {error}", file=sys.stderr)
        return 2
    try:
        commands, by_id, results = parse_trace(read_trace(args.trace))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        print(f"cannot read the trace: {error}", file=sys.stderr)
        return 2
    calls = pg_run_results(by_id, results)
    failures = [line for line in (check(kind, argument, calls) for kind, argument in expected) if line]
    failures += [f"FAIL client: {command.strip()[:120]!r}" for command in client_calls(commands)]
    kinds = {kind for kind, _ in expected}
    if not kinds.intersection(OK_KINDS):
        failures += [f"FAIL unexpected-ok: a pg_run result has ok true ({service or 'no service'})"
                     for service, result in calls
                     if result.get("ok") is True and not ("facts" in kinds and has_facts(result))]
    print("\n".join(failures + ["FAIL" if failures else "PASS"]))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
