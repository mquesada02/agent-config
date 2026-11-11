#!/usr/bin/env python3
"""Scores the DB cases of a `claude plugin eval --json` result with grader H and the leak scan.

Usage: grade_db_eval_results.py RESULT.json [--evals DIR] [--canaries FILE]

Plugin eval has no custom-code graders, so this script runs grade_refusals.py (H) and grade_leak_scan.py on
each run in the `arms.with` list of each case of the result whose folder under DIR has a db-expect.json (the
other cases are skipped). The trace of a run is its `tracePath` field, which exists only when the eval ran
with --keep-temp; a run with no trace file gives one "trace" failure. db-expect.json is an object with
`expect` (a list of H kinds, see grade_refusals.py) and the optional keys `sequences_may_differ` (boolean),
`rules` (an object with the lists `expect` and `forbid` of rule ids, graded by grader E), `report` (true:
grader I), `disabled` (rule ids for grader I) and `judge` (a rubric file name; the reported LLM judge); the
driver reads these optional keys, this script reads none of them. Default DIR: the evals folder beside the graders folder.
Default FILE: evals/db/canaries.json.
Output: one line "FAIL <case>#<n> <check>: <message>" for each failed check, one line "<case>#<n>: PASS|FAIL"
for each run (n starts at 1), then PASS or FAIL. Exit code: 0 pass, 1 fail, 2 usage error or unreadable
result, no case to grade, or an unusable db-expect.json (no PASS or FAIL line then).
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import grade_eval_results as results  # noqa: E402


def load_expectation(path):
    """The H kinds of a db-expect.json. Raises OSError or ValueError."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    results.require(isinstance(data, dict), "not an object")
    results.require(results.is_id_list(data.get("expect")), "`expect` is not a list of strings")
    return data["expect"]


def grade_run(case, number, trace_path, expect, canaries):
    """The failure lines of one run, each prefixed with the case and the run number."""
    label = f"{case}#{number}"
    if not trace_path or not os.path.isfile(trace_path):
        return [f"FAIL {label} trace: no trace file at {trace_path or '(no trace path)'} (run the eval with --keep-temp)"]
    code, lines, error = results.run_grader("grade_refusals.py", [trace_path, "--expect", *expect])
    if code == 2:
        return [f"FAIL {label} trace: {trace_path} cannot be graded ({error})"]
    code, leaks, error = results.run_grader("grade_leak_scan.py", [trace_path, "--canaries", canaries])
    if code == 2:
        return [f"FAIL {label} trace: the leak scan cannot run ({error})"]
    return [f"FAIL {label} {line[len('FAIL '):]}" for line in lines + leaks]


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("result")
    parser.add_argument("--evals", default=os.path.join(os.path.dirname(HERE), "evals"))
    parser.add_argument("--canaries")
    args = parser.parse_args(argv)
    canaries = args.canaries or os.path.join(args.evals, "db", "canaries.json")
    try:
        cases = results.case_runs(args.result)
    except (OSError, ValueError) as error:
        print(f"cannot read the result: {error}", file=sys.stderr)
        return 2
    graded = []
    for name, traces in cases:
        expect_path = os.path.join(args.evals, name, "db-expect.json")
        if not os.path.isfile(expect_path):
            continue
        try:
            graded.append((name, traces, load_expectation(expect_path)))
        except (OSError, ValueError) as error:
            print(f"cannot read db-expect.json of {name}: {error}", file=sys.stderr)
            return 2
    if not any(traces for _, traces, _ in graded):
        print("cannot read the result: nothing to grade (no with-arm run of a case that has a db-expect.json)",
              file=sys.stderr)
        return 2
    out = []
    for name, traces, expect in graded:
        for number, trace in enumerate(traces, start=1):
            failures = grade_run(name, number, trace, expect, canaries)
            out += failures + [f"{name}#{number}: {'FAIL' if failures else 'PASS'}"]
    failed = any(line.startswith("FAIL ") for line in out)
    print("\n".join(out + ["FAIL" if failed else "PASS"]))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
