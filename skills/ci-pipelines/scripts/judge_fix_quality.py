#!/usr/bin/env python3
"""Judges the Fix cell of each finding row of a `claude plugin eval --json` result, one row at a time.

Usage: judge_fix_quality.py RESULT.json [--evals DIR] [--case GLOB] [--judge-cmd COMMAND]

Plugin eval throws the reply of an llm judge away and shows the judge only one input. This script is the
diagnostic of the `fix-quality` judge. For each with-arm run of each case that has the `fix-quality` grader,
it reads the final message from the kept trace (`tracePath`, so the eval must have run with --keep-temp),
and asks a judge one question for each table row of that report. The question holds the row, the exact text
of the fixture workflow files (DIR/<case>/repo/.github) and, for a row marked with the flag, the flag section.
The judge answers on one line: PASS or FAIL, a colon and a short reason.
COMMAND is the judge command (default: claude -p with haiku and no tools). It reads the question on stdin.
Output: one line "<case>#<n> row <k> <RULE>: PASS|FAIL <reason>" for each row, one line
"<case>#<n>: PASS|FAIL|no rows" for each run, one line "FAIL <label> <check>: <message>" for each error, then
"rows: X of Y PASS" and "runs: A of B PASS" (a run with no rows, such as a clean report, is not counted).
Exit code: 0 all rows judged (a FAIL verdict is not an error), 1 an error (trace, judge command or judge reply), 2 usage error or unreadable result.
"""
import argparse
import fnmatch
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

# `python3 -I` does not put this folder on the import path, so load the sibling module by its path.
_spec = importlib.util.spec_from_file_location("grade_eval_results", os.path.join(HERE, "grade_eval_results.py"))
_shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_shared)
final_message = _shared.final_message

JUDGE = "fix-quality"
COLUMNS = ["#", "Rule", "Where", "Problem", "Fix"]
FLAG = "⚑"
DEFAULT_JUDGE = ["claude", "-p", "--model", "haiku", "--tools", "", "--disable-slash-commands",
                 "--no-session-persistence"]
TIMEOUT_SECONDS = 300
REPLY = re.compile(r"^(PASS|FAIL)\b[\s:.\-]*(.*)$")
CRITERION = (
    "Judge one finding row of a CI review report. The row passes when its Fix cell names a concrete edit "
    "(what to add, change, remove or rename, with the key or value when the edit needs one) and that edit, "
    "applied to the workflow files below, removes the problem in its Problem cell. A vague Fix cell, such as "
    "\"improve the name\", fails.\n"
    "A row marked with the flag passes when its Fix cell names the workflow edit and the admin steps for "
    "branch protection are in the flag section below. The skill does not change branch protection itself.\n"
    "Answer on one line: PASS or FAIL, a colon, and one short reason (at most 25 words)."
)


def judged_runs(result_path, pattern):
    """A list of (case name, [trace path of each with-arm run]) for the cases that have the judge grader.

    Raises OSError or ValueError when the file cannot be read or has not the shape of a plugin eval result."""
    with open(result_path, encoding="utf-8") as handle:
        data = json.load(handle)
    found = []
    try:
        for case in data["cases"]:
            if JUDGE in [g["name"] for g in case["graders"]] and fnmatch.fnmatch(case["name"], pattern):
                found.append((case["name"], [str(run["tracePath"]) for run in case["arms"]["with"]]))
    except (KeyError, TypeError) as error:
        raise ValueError(f"not a plugin eval result ({error!r})")
    return found


def split_row(line):
    """The cells of a table line. A pipe written as \\| stays inside its cell."""
    inner = re.sub(r"^\||(?<!\\)\|$", "", line.strip())
    return [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", inner)]


def table_rows(message):
    """The data rows of every findings table of a report. A row with a bare pipe in a cell has more than 5 cells."""
    rows, in_table = [], False
    for line in message.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            in_table = False
            continue
        cells = split_row(stripped)
        if cells == COLUMNS:
            in_table = True
        elif in_table and not all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            rows.append(cells)
    return rows


def flag_section(message):
    """The text of the `## ⚑` section of a report (heading included), or an empty string."""
    out, inside = [], False
    for line in message.splitlines():
        if line.startswith("## "):
            inside = line.startswith(f"## {FLAG}")
        if inside:
            out.append(line)
    return "\n".join(out).strip()


def workflow_text(evals, case):
    """The exact text of the files under DIR/<case>/repo/.github, each after a line with its path."""
    base = os.path.join(evals, case, "repo")
    parts = []
    for folder, _, names in sorted(os.walk(os.path.join(base, ".github"))):
        for name in sorted(names):
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as handle:
                parts.append(f"=== {os.path.relpath(path, base)} ===\n{handle.read()}")
    if not parts:
        raise FileNotFoundError(f"no file under {os.path.join(base, '.github')}")
    return "\n".join(parts)


def question(files, section, cells):
    _, rule, where, problem, fix = cells
    lines = [CRITERION, "", "Workflow files:", files, ""]
    if FLAG in rule:
        lines += ["Flag section:", section or "(the report has no flag section)", ""]
    lines += [f"Row: rule {rule} | where {where} | problem {problem} | fix {fix}"]
    return "\n".join(lines)


def ask_judge(command, text):
    """(verdict, reason) of one judge call. Raises ValueError with the message of a failed call."""
    with tempfile.TemporaryDirectory() as cwd:
        try:
            proc = subprocess.run(command, input=text, capture_output=True, text=True, cwd=cwd,
                                  timeout=TIMEOUT_SECONDS)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError(f"the judge command failed: {error}")
    if proc.returncode != 0:
        raise ValueError(f"the judge command exited {proc.returncode} ({proc.stderr.strip()[:200] or 'no message'})")
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    match = REPLY.match(lines[0]) if lines else None
    if match is None:
        raise ValueError(f"unreadable reply: {(lines[0] if lines else 'empty')[:200]}")
    return match.group(1), match.group(2).strip()


def judge_run(label, trace_path, files, command, out):
    """Judge one run. Appends the output lines to `out`. Returns (rows passed, rows judged, run passed, errors)."""
    message = final_message(trace_path)
    if message is None:
        out.append(f"FAIL {label} trace: no final message in {trace_path} (run the eval with --keep-temp)")
        return 0, 0, False, 1
    rows = table_rows(message)
    if not rows:
        out.append(f"{label}: no rows")
        return 0, 0, None, 0
    section = flag_section(message)
    passed = judged = errors = 0
    for number, cells in enumerate(rows, start=1):
        if len(cells) != len(COLUMNS):
            out.append(f"FAIL {label} row {number} table: {len(cells)} cells, not {len(COLUMNS)} (write a pipe in a cell as \\|)")
            errors += 1
            continue
        try:
            verdict, reason = ask_judge(command, question(files, section, cells))
        except ValueError as error:
            out.append(f"FAIL {label} row {number} judge: {error}")
            errors += 1
            continue
        judged += 1
        passed += verdict == "PASS"
        out.append(f"{label} row {number} {cells[1].replace(FLAG, '').strip()}: {verdict} {reason}")
    ok = errors == 0 and passed == judged
    out.append(f"{label}: {'PASS' if ok else 'FAIL'}")
    return passed, judged, ok, errors


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("result")
    parser.add_argument("--evals", default=os.path.join(os.path.dirname(HERE), "evals"))
    parser.add_argument("--case", default="*")
    parser.add_argument("--judge-cmd", default=None)
    args = parser.parse_args(argv)
    command = shlex.split(args.judge_cmd) if args.judge_cmd else DEFAULT_JUDGE
    try:
        cases = judged_runs(args.result, args.case)
    except (OSError, ValueError) as error:
        print(f"cannot read the result: {error}", file=sys.stderr)
        return 2
    if not any(traces for _, traces in cases):
        print("cannot read the result: nothing to judge (no with-arm run of a case with the fix-quality grader)",
              file=sys.stderr)
        return 2
    out, rows_passed, rows_judged, runs_passed, runs_total, errors = [], 0, 0, 0, 0, 0
    for name, traces in cases:
        try:
            files = workflow_text(args.evals, name)
        except OSError as error:
            print(f"cannot read the fixture of {name}: {error}", file=sys.stderr)
            return 2
        for number, trace in enumerate(traces, start=1):
            passed, judged, ok, failed = judge_run(f"{name}#{number}", trace, files, command, out)
            rows_passed, rows_judged, errors = rows_passed + passed, rows_judged + judged, errors + failed
            if ok is not None:
                runs_passed, runs_total = runs_passed + ok, runs_total + 1
    out += [f"rows: {rows_passed} of {rows_judged} PASS", f"runs: {runs_passed} of {runs_total} PASS"]
    print("\n".join(out))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
