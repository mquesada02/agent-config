#!/usr/bin/env python3
"""Scores the review cases of a `claude plugin eval --json` result with the two Python graders.

Usage: grade_eval_results.py RESULT.json [--evals DIR]

Plugin eval has no custom-code graders, so this script runs grade_report.py and grade_rule_ids.py on the
final message of each with-arm run of each review case (a case that has the section-summary grader). The
final message is the `result` field of the last line of the run's trace (`tracePath` in the result), and
the trace exists only when the eval ran with --keep-temp. The expect and forbid lists come from
DIR/<case>/expect.json (default DIR: the evals folder beside the scripts folder).
Output: one line "FAIL <case>#<n> <check>: <message>" for each failed check, one line "<case>#<n>: PASS|FAIL"
for each run, then PASS or FAIL. Exit code: 0 pass, 1 fail, 2 usage error or unreadable result.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REVIEW_MARKER = "section-summary"


def final_message(trace_path):
    """The `result` field of the last line of a trace, or None when the trace is missing or has none."""
    try:
        with open(trace_path, encoding="utf-8") as handle:
            lines = [line for line in handle.read().splitlines() if line.strip()]
        last = json.loads(lines[-1])
    except (OSError, ValueError, IndexError):
        return None
    result = last.get("result") if isinstance(last, dict) else None
    return result if isinstance(result, str) else None


def run_grader(script, args, text):
    proc = subprocess.run([sys.executable, "-I", os.path.join(HERE, script), *args],
                          input=text, capture_output=True, text=True)
    return [line for line in proc.stdout.splitlines() if line.startswith("FAIL ") and line != "FAIL"]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def review_runs(result_path):
    """The review cases of a result as a list of (case name, [trace path of each with-arm run]).

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
        if REVIEW_MARKER not in [g.get("name") for g in graders]:
            continue
        arms = case.get("arms", {})
        require(isinstance(arms, dict) and isinstance(arms.get("with", []), list),
                f"{case['name']}: `arms.with` is not a list")
        runs = arms.get("with", [])
        require(all(isinstance(run, dict) and isinstance(run.get("tracePath", ""), str) for run in runs),
                f"{case['name']}: a with-arm run is not an object with a `tracePath` string")
        found.append((case["name"], [run.get("tracePath", "") for run in runs]))
    return found


def load_lists(evals, case):
    """The expect and forbid lists of a case. Raises OSError or ValueError when expect.json is unusable."""
    with open(os.path.join(evals, case, "expect.json"), encoding="utf-8") as handle:
        lists = json.load(handle)
    require(isinstance(lists, dict), "not an object")
    for key in ("expect", "forbid"):
        require(isinstance(lists.get(key), list) and all(isinstance(rule, str) for rule in lists[key]),
                f"`{key}` is not a list of strings")
    return lists


def grade_run(case, number, trace_path, lists):
    """The failure lines of one run, each prefixed with the case and the run number."""
    label = f"{case}#{number}"
    message = final_message(trace_path)
    if message is None:
        return [f"FAIL {label} trace: no final message in {trace_path} (run the eval with --keep-temp)"]
    lines = run_grader("grade_report.py", ["-"], message)
    lines += run_grader("grade_rule_ids.py", ["-", "--expect", *lists["expect"], "--forbid", *lists["forbid"]], message)
    return [f"FAIL {label} {line[len('FAIL '):]}" for line in lines]


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("result")
    parser.add_argument("--evals", default=os.path.join(os.path.dirname(HERE), "evals"))
    args = parser.parse_args(argv)
    try:
        cases = review_runs(args.result)
    except (OSError, ValueError) as error:
        print(f"cannot read the result: {error}", file=sys.stderr)
        return 2
    out, failed = [], False
    for name, traces in cases:
        try:
            lists = load_lists(args.evals, name)
        except (OSError, ValueError) as error:
            print(f"cannot read expect.json of {name}: {error}", file=sys.stderr)
            return 2
        for number, trace in enumerate(traces, start=1):
            failures = grade_run(name, number, trace, lists)
            out += failures + [f"{name}#{number}: {'FAIL' if failures else 'PASS'}"]
            failed = failed or bool(failures)
    print("\n".join(out + ["FAIL" if failed else "PASS"]))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
