#!/usr/bin/env python3
"""Scores the create cases of a `claude plugin eval --json` result with check_workflow.py and actionlint.

Usage: grade_create_results.py RESULT.json [--evals DIR]

Plugin eval has no custom-code graders, so this script grades the files that a create run shows in the final
message. A create case is a case that has the grader `wrote-ci`. For each with-arm run, it reads the final
message (the `result` field of the last line of the trace at `tracePath`; the trace exists only when the eval
ran with --keep-temp), takes each fenced `yaml` block under a `### <path>` heading of the `## Created`
section, and runs check_workflow.py on it with the assertions that the `asserts` object of
DIR/<case>/expect.json lists for that path. It also runs the real `actionlint` on each written workflow
block when actionlint is on PATH. A path that the case asserts and the message does not show fails the run.
A missing actionlint prints `NOT RUN actionlint: not on PATH` and does not fail the run.
Output: one line "FAIL <case>#<n> <check>: <message>" for each failed check, one line "<case>#<n>: PASS|FAIL"
for each run, then PASS or FAIL. Exit code: 0 pass, 1 fail, 2 usage error or unreadable result.
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

# `python3 -I` does not put this folder on the import path, so load the sibling module by its path.
_spec = importlib.util.spec_from_file_location("grade_eval_results", os.path.join(HERE, "grade_eval_results.py"))
_shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_shared)
final_message, require = _shared.final_message, _shared.require

CREATE_MARKER = "wrote-ci"
WORKFLOWS = ".github/workflows/"
HEADING = re.compile(r"^#{1,6}\s")
PATH_HEADING = re.compile(r"^### (\S+)\s*$")
FENCE = re.compile(r"^```(\w*)\s*$")


def create_runs(result_path):
    """The create cases of a result as a list of (case name, [trace path of each with-arm run]).

    Raises OSError or ValueError when the file cannot be read or has not the shape of a plugin eval result."""
    with open(result_path, encoding="utf-8") as handle:
        data = json.load(handle)
    require(isinstance(data, dict) and isinstance(data.get("cases"), list), "no `cases` list")
    found = []
    for case in data["cases"]:
        require(isinstance(case, dict) and isinstance(case.get("name"), str), "a case has no name")
        graders = case.get("graders", [])
        require(isinstance(graders, list) and all(isinstance(g, dict) for g in graders),
                f"{case['name']}: `graders` is not a list of objects")
        if CREATE_MARKER not in [g.get("name") for g in graders]:
            continue
        arms = case.get("arms", {})
        runs = arms.get("with", []) if isinstance(arms, dict) else None
        require(isinstance(runs, list), f"{case['name']}: `arms.with` is not a list")
        require(all(isinstance(run, dict) and isinstance(run.get("tracePath", ""), str) for run in runs),
                f"{case['name']}: a with-arm run is not an object with a `tracePath` string")
        found.append((case["name"], [run.get("tracePath", "") for run in runs]))
    return found


def load_asserts(evals, case):
    """The `asserts` object of a case (path -> list of assertions). Raises OSError or ValueError when unusable."""
    with open(os.path.join(evals, case, "expect.json"), encoding="utf-8") as handle:
        asserts = json.load(handle).get("asserts")
    require(isinstance(asserts, dict), "`asserts` is not an object")
    for path, names in asserts.items():
        require(isinstance(names, list) and all(isinstance(name, str) for name in names),
                f"`asserts` of {path} is not a list of strings")
    return asserts


def created_blocks(message):
    """The fenced `yaml` blocks under a `### <path>` heading of the `## Created` section, as {path: text}."""
    blocks, in_created, path, fence, body = {}, False, None, None, []
    for line in message.splitlines():
        if fence is not None:
            if line.rstrip() == "```":
                if fence == "yaml" and path is not None:
                    blocks.setdefault(path, "\n".join(body) + "\n")
                fence, body = None, []
            else:
                body.append(line)
            continue
        opening = FENCE.match(line)
        if opening and in_created:
            fence = opening.group(1)
            continue
        if line.startswith("## "):
            in_created, path = line.strip() == "## Created", None
        elif line.startswith("# "):
            in_created, path = False, None
        elif in_created and (heading := PATH_HEADING.match(line)):
            path = heading.group(1)
        elif HEADING.match(line):
            path = None
    return blocks


def check_block(text, names):
    """The failure lines (without the verdict line) of check_workflow.py on a block."""
    proc = subprocess.run([sys.executable, "-I", os.path.join(HERE, "check_workflow.py"), "-", "--assert", *names],
                          input=text, capture_output=True, text=True)
    if proc.returncode == 2:
        return [f"FAIL check_workflow: exited 2 ({proc.stderr.strip() or 'no message'})"]
    return [line for line in proc.stdout.splitlines() if line.startswith("FAIL ") and line != "FAIL"]


def lint_block(path, text):
    """The failure message of the real actionlint on a workflow block, or None when it passes."""
    with tempfile.TemporaryDirectory(prefix="create-grade-") as folder:
        target = os.path.join(folder, os.path.basename(path))
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(text)
        proc = subprocess.run(["actionlint", "-no-color", target], capture_output=True, text=True)
    if proc.returncode == 0:
        return None
    return (proc.stdout.strip() or proc.stderr.strip() or f"exited {proc.returncode}").replace("\n", " | ")


def grade_run(case, number, trace_path, asserts, lint):
    """The failure lines of one run, each prefixed with the case and the run number."""
    label = f"{case}#{number}"
    message = final_message(trace_path)
    if message is None:
        return [f"FAIL {label} trace: no final message in {trace_path} (run the eval with --keep-temp)"]
    blocks = created_blocks(message)
    failures = []
    for path, names in asserts.items():
        if path not in blocks:
            failures.append(f"FAIL {label} written: {path} is asserted and the final message does not show it")
            continue
        for line in check_block(blocks[path], names):
            check, _, text = line[len("FAIL "):].partition(": ")
            failures.append(f"FAIL {label} {check}: {path}: {text}")
    if lint:
        for path, text in blocks.items():
            if path.startswith(WORKFLOWS):
                error = lint_block(path, text)
                if error:
                    failures.append(f"FAIL {label} actionlint: {path}: {error}")
    return failures


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("result")
    parser.add_argument("--evals", default=os.path.join(os.path.dirname(HERE), "evals"))
    args = parser.parse_args(argv)
    try:
        cases = create_runs(args.result)
    except (OSError, ValueError) as error:
        print(f"cannot read the result: {error}", file=sys.stderr)
        return 2
    if not any(traces for _, traces in cases):
        print("cannot read the result: nothing to grade (no with-arm run of a create case)", file=sys.stderr)
        return 2
    lint = shutil.which("actionlint") is not None
    out = []
    for name, traces in cases:
        try:
            asserts = load_asserts(args.evals, name)
        except (OSError, ValueError) as error:
            print(f"cannot read expect.json of {name}: {error}", file=sys.stderr)
            return 2
        for number, trace in enumerate(traces, start=1):
            failures = grade_run(name, number, trace, asserts, lint)
            out += failures + [f"{name}#{number}: {'FAIL' if failures else 'PASS'}"]
    if not lint:
        out.append("NOT RUN actionlint: not on PATH")
    failed = any(line.startswith("FAIL ") for line in out)
    print("\n".join(out + ["FAIL" if failed else "PASS"]))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
