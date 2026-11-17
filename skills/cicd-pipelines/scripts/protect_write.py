#!/usr/bin/env python3
"""The protection write script of the cicd-pipelines skill (the "Fix on approval" protection step).

It makes every protection read and write of that step with the `gh` CLI. It has three modes:

  protect_write.py --read <api path> [--absent-ok]   GET, print the JSON, write nothing
  protect_write.py --show <row file>                 GET, compare with `seen`, print the diff, write nothing
  protect_write.py --apply <row file>                GET, compare, write, GET again, compare

A row file is JSON with `path`, `method` (PUT or POST), `seen` (the last `--read`, or null for an absent
object) and `proposed` (the payload). Every GET result is turned into the write shape of its object, so `seen`,
`proposed`, the diff and the check after the write all use one shape.

Exit codes: 0 ok. 1 the setting changed or a write step failed (stop all remaining writes). 2 a read failed or
the row file is bad (nothing was written).
"""
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile

REPO = r"^repos/[^/]+/[^/]+"
ENVIRONMENT = re.compile(REPO + r"/environments/[^/]+$")
POLICIES = re.compile(REPO + r"/environments/[^/]+/deployment-branch-policies$")
POLICY = re.compile(REPO + r"/environments/[^/]+/deployment-branch-policies/[^/]+$")
RULESETS = re.compile(REPO + r"/rulesets$")
RULESET = re.compile(REPO + r"/rulesets/[^/]+$")
RULESET_READ_ONLY = ("id", "node_id", "source", "source_type", "current_user_can_bypass", "_links",
                     "created_at", "updated_at")


class GhError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message

    def line(self):
        return f"error: HTTP {self.code}: {self.message}"


def run_gh(args, timeout=60):
    try:
        done = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise GhError("unknown", "gh is not on PATH")
    except subprocess.TimeoutExpired:
        raise GhError("unknown", "gh did not answer in time")
    if done.returncode != 0:
        text = (done.stderr or done.stdout).strip().replace("\n", " ")
        found = re.search(r"HTTP (\d{3})", text)
        raise GhError(found.group(1) if found else "unknown", text or f"gh exited with {done.returncode}")
    return done.stdout


def decode_values(text):
    """The JSON values of a text (a paginated answer holds one value for each page)."""
    decoder, values, position = json.JSONDecoder(), [], 0
    while position < len(text):
        while position < len(text) and text[position].isspace():
            position += 1
        if position >= len(text):
            break
        value, position = decoder.raw_decode(text, position)
        values.append(value)
    return values


def merge_pages(values):
    if not values:
        return None
    if all(isinstance(value, list) for value in values):
        return [item for value in values for item in value]
    if all(isinstance(value, dict) and isinstance(value.get("branch_policies"), list) for value in values):
        merged = dict(values[0])
        merged["branch_policies"] = [item for value in values for item in value["branch_policies"]]
        return merged
    return values[0]


def get(path):
    """GET of `path` (a collection is read whole), decoded. Raises GhError."""
    text = run_gh(["api", "--paginate", path])
    try:
        return merge_pages(decode_values(text))
    except ValueError:
        raise GhError("unknown", "the answer is not JSON")


def environment_shape(data):
    rules = data.get("protection_rules") or []
    wait = next((rule.get("wait_timer", 0) for rule in rules if rule.get("type") == "wait_timer"), 0)
    required = next((rule for rule in rules if rule.get("type") == "required_reviewers"), None)
    reviewers = []
    if required:
        for entry in required.get("reviewers") or []:
            reviewers.append({"type": entry.get("type"), "id": (entry.get("reviewer") or {}).get("id")})
    return {"wait_timer": wait,
            "prevent_self_review": bool(required.get("prevent_self_review", False)) if required else False,
            "reviewers": reviewers,
            "deployment_branch_policy": data.get("deployment_branch_policy")}


def to_write_shape(path, data):
    """The write shape of a GET result, chosen by the path pattern. Any other path is returned as it is."""
    if data is None:
        return None
    if ENVIRONMENT.match(path):
        return environment_shape(data)
    if POLICIES.match(path):
        return [{"id": item.get("id"), "name": item.get("name"), "type": item.get("type")}
                for item in data.get("branch_policies", [])]
    if POLICY.match(path):
        return {"name": data.get("name"), "type": data.get("type")}
    if RULESETS.match(path):
        return [{"id": item.get("id"), "name": item.get("name"), "target": item.get("target"),
                 "enforcement": item.get("enforcement")} for item in data]
    if RULESET.match(path):
        return {key: value for key, value in data.items() if key not in RULESET_READ_ONLY}
    return data


def contains(proposed, actual):
    """True when every part of `proposed` is in `actual` (objects by key, arrays by length and order)."""
    if isinstance(proposed, dict):
        return (isinstance(actual, dict) and all(key in actual and contains(value, actual[key])
                                                   for key, value in proposed.items()))
    if isinstance(proposed, list):
        return (isinstance(actual, list) and len(actual) == len(proposed)
                and all(contains(left, right) for left, right in zip(proposed, actual)))
    return proposed == actual


def pretty(value):
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)


def diff(left, right, left_name, right_name):
    lines = difflib.unified_diff(pretty(left).splitlines(), pretty(right).splitlines(), left_name, right_name,
                                 lineterm="")
    return "\n".join(lines)


def load_row(file_name):
    try:
        with open(file_name, encoding="utf-8") as handle:
            row = json.load(handle)
        if not (isinstance(row, dict) and {"path", "method", "seen", "proposed"} <= set(row)
                and isinstance(row["path"], str) and row["method"] in ("PUT", "POST")):
            raise ValueError("the row needs path, method (PUT or POST), seen and proposed")
        return row
    except (OSError, ValueError) as error:
        print(f"error: row file: {error}")
        sys.exit(2)


def read_current(row):
    """The current object in the write shape. A 404 is None when the row expects an absent object."""
    try:
        return to_write_shape(row["path"], get(row["path"]))
    except GhError as error:
        if error.code == "404" and row["seen"] is None:
            return None
        print(error.line())
        sys.exit(2)


def history_version(path):
    if not RULESET.match(path):
        return None
    try:
        entries = get(path + "/history")
        return str(max(entry["version_id"] for entry in entries))
    except (GhError, KeyError, ValueError, TypeError):
        return "unavailable"


def print_before(before, version, path):
    print("before JSON:")
    print(pretty(before))
    if RULESET.match(path):
        print(f"history version: {version}")


def mode_read(path, absent_ok):
    try:
        print(pretty(to_write_shape(path, get(path))))
    except GhError as error:
        if absent_ok and error.code == "404":
            print("null")
            return 0
        print(error.line())
        return 2
    return 0


def mode_show(row):
    current = read_current(row)
    if current != row["seen"]:
        print("The setting changed since the last read. Current JSON against the JSON that was read:")
        print(diff(current, row["seen"], "current", "seen"))
        return 1
    print(diff(None if row["method"] == "POST" else current, row["proposed"], "current", "proposed"))
    return 0


def mode_apply(row):
    current = read_current(row)
    if current != row["seen"]:
        print("The setting changed since the diff was shown. Nothing was written. Current JSON against the JSON that was read:")
        print(diff(current, row["seen"], "current", "seen"))
        return 1
    before = None if row["method"] == "POST" else row["seen"]
    version = history_version(row["path"]) if row["method"] == "PUT" else None
    verify_path = row["path"]

    def stop(*lines):
        print("\n".join(lines))
        print_before(before, version, row["path"])
        return 1

    with tempfile.TemporaryDirectory() as folder:
        body_file = os.path.join(folder, "payload.json")
        with open(body_file, "w", encoding="utf-8") as handle:
            json.dump(row["proposed"], handle)
        try:
            answer = run_gh(["api", "-X", row["method"], row["path"], "--input", body_file])
        except GhError as error:
            return stop(error.line(), "The write failed.")
    try:
        if row["method"] == "POST":
            created = decode_values(answer)[0]["id"]
            verify_path = f"{row['path']}/{created}"
        after = to_write_shape(verify_path, get(verify_path))
    except GhError as error:
        return stop(error.line(), "The write was made, but the check after it failed.")
    except (ValueError, KeyError, IndexError, TypeError):
        return stop("The write was made, but the answer holds no id to check.")
    if not contains(row["proposed"], after):
        return stop("The setting after the write does not hold the proposed JSON:",
                    diff(after, row["proposed"], "after", "proposed"))
    print("written and verified")
    print_before(before, version, row["path"])
    return 0


def main(argv):
    if len(argv) >= 2 and argv[0] == "--read" and (len(argv) == 2 or argv[2:] == ["--absent-ok"]):
        return mode_read(argv[1], len(argv) == 3)
    if len(argv) == 2 and argv[0] in ("--show", "--apply"):
        row = load_row(argv[1])
        return mode_show(row) if argv[0] == "--show" else mode_apply(row)
    print("usage: protect_write.py --read <api path> [--absent-ok] | --show <row file> | --apply <row file>")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
