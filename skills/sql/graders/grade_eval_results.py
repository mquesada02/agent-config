#!/usr/bin/env python3
"""Scores the `/sql optimize` cases of a `claude plugin eval --json` result with graders E, F and I.

Usage: grade_eval_results.py RESULT.json [--evals DIR]

Plugin eval has no custom-code graders, so this script runs grade_rule_ids.py (E), grade_no_change.py (F)
and grade_report.py (I) on each with-arm run of each case whose folder under DIR has an expect.json (the
other cases are skipped). The trace of a run (`tracePath` in the result) exists only when the eval ran
with --keep-temp. The final message is the `result` field of the last line of the trace. expect.json is an
object with `expect` and `forbid` (lists of rule ids) and an optional `disabled` (a list of rule ids).
Default DIR: the evals folder beside the graders folder.
Output: one line "FAIL <case>#<n> <check>: <message>" for each failed check, one line "<case>#<n>: PASS|FAIL"
for each run (n starts at 1), then PASS or FAIL. Exit code: 0 pass, 1 fail, 2 usage error or unreadable
result, no case to grade, or unusable expect.json (no PASS or FAIL line then).
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def is_id_list(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def case_runs(result_path):
    """(case name, [trace path of each with-arm run]) for each case. Raises OSError or ValueError."""
    with open(result_path, encoding="utf-8") as handle:
        data = json.load(handle)
    require(isinstance(data, dict) and isinstance(data.get("cases"), list), "no `cases` list")
    found = []
    for case in data["cases"]:
        require(isinstance(case, dict) and isinstance(case.get("name"), str), "a case has no name")
        arms = case.get("arms", {})
        runs = arms.get("with", []) if isinstance(arms, dict) else None
        require(isinstance(runs, list), f"{case['name']}: `arms.with` is not a list")
        require(all(isinstance(run, dict) and isinstance(run.get("tracePath", ""), str) for run in runs),
                f"{case['name']}: a with-arm run is not an object with a `tracePath` string")
        found.append((case["name"], [run.get("tracePath", "") for run in runs]))
    return found


def load_lists(path):
    """The expect, forbid and disabled lists of an expect.json. Raises OSError or ValueError."""
    with open(path, encoding="utf-8") as handle:
        lists = json.load(handle)
    require(isinstance(lists, dict), "not an object")
    for name in ("expect", "forbid"):
        require(is_id_list(lists.get(name)), f"`{name}` is not a list of strings")
    require(lists.get("disabled") is None or is_id_list(lists["disabled"]), "`disabled` is not a list of strings")
    return lists


def final_message(trace_path):
    """The `result` field of the last line of a trace, or None."""
    try:
        with open(trace_path, encoding="utf-8") as handle:
            lines = [line for line in handle.read().splitlines() if line.strip()]
        last = json.loads(lines[-1])
    except (OSError, ValueError, IndexError):
        return None
    result = last.get("result") if isinstance(last, dict) else None
    return result if isinstance(result, str) else None


def run_grader(script, args, stdin=None):
    """(exit code, FAIL lines, stderr) of a grader command."""
    proc = subprocess.run([sys.executable, "-I", os.path.join(HERE, script), *args],
                          input=stdin, capture_output=True, text=True)
    lines = [line for line in proc.stdout.splitlines() if line.startswith("FAIL ") and line != "FAIL"]
    return proc.returncode, lines, proc.stderr.strip()


def grade_run(case, number, trace_path, lists):
    """The failure lines of one run, each prefixed with the case and the run number."""
    label = f"{case}#{number}"
    keep = f"FAIL {label} trace: no final message in {trace_path or '(no trace path)'} (run the eval with --keep-temp)"
    if not trace_path or not os.path.isfile(trace_path):
        return [keep]
    code, change_lines, error = run_grader("grade_no_change.py", [trace_path])
    if code == 2:
        return [f"FAIL {label} trace: {trace_path} is unreadable ({error})"]
    message = final_message(trace_path)
    if message is None:
        return [keep]
    lines = change_lines
    disabled = lists.get("disabled")
    lines += run_grader("grade_report.py", ["-", *(["--disabled", *disabled] if disabled is not None else [])],
                        message)[1]
    lines += run_grader("grade_rule_ids.py", ["-", "--expect", *lists["expect"], "--forbid", *lists["forbid"]],
                        message)[1]
    return [f"FAIL {label} {line[len('FAIL '):]}" for line in lines]


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("result")
    parser.add_argument("--evals", default=os.path.join(os.path.dirname(HERE), "evals"))
    args = parser.parse_args(argv)
    try:
        cases = case_runs(args.result)
    except (OSError, ValueError) as error:
        print(f"cannot read the result: {error}", file=sys.stderr)
        return 2
    graded = []
    for name, traces in cases:
        expect_path = os.path.join(args.evals, name, "expect.json")
        if not os.path.isfile(expect_path):
            continue
        try:
            graded.append((name, traces, load_lists(expect_path)))
        except (OSError, ValueError) as error:
            print(f"cannot read expect.json of {name}: {error}", file=sys.stderr)
            return 2
    if not any(traces for _, traces, _ in graded):
        print("cannot read the result: nothing to grade (no with-arm run of a case that has an expect.json)",
              file=sys.stderr)
        return 2
    out = []
    for name, traces, lists in graded:
        for number, trace in enumerate(traces, start=1):
            failures = grade_run(name, number, trace, lists)
            out += failures + [f"{name}#{number}: {'FAIL' if failures else 'PASS'}"]
    failed = any(line.startswith("FAIL ") for line in out)
    print("\n".join(out + ["FAIL" if failed else "PASS"]))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
