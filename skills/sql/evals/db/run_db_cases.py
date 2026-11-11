#!/usr/bin/env python3
"""Hand-run DB driver: the eval cases that need the real Docker database.

Usage: run_db_cases.py [--case GLOB] [--runs N] [--out FOLDER] [--max-budget-usd USD]

It starts the two Docker databases (db_eval.py setup) into a new temp state folder, and for each case under
evals/db/cases and each run: copies the case's repo into a new work folder (git init, origin remote),
takes the snapshots, runs `claude -p` (model sonnet) in that folder, takes the snapshots again, then grades
the stream-json transcript with grader H (grade_refusals.py, the `expect` list of the case's db-expect.json),
the leak scan (grade_leak_scan.py) and grader G (grade_db_unchanged.py) on each version. The session
loads the skill folder as a plugin, with no user or project settings, no CLAUDE.md and no MCP server
(`--setting-sources ""`, CLAUDE_CODE_DISABLE_CLAUDE_MDS=1, `--strict-mcp-config`), no session file, and
the tools Skill, Read and Bash limited to python3 on five scripts of the skill (rules_file.py, extract.py,
allowlist.py, pg_run.py, plan_findings.py). The environment sets PGSERVICEFILE, PGPASSFILE and XDG_CONFIG_HOME
to the state folder and drops every other PG* variable. Optional keys of db-expect.json: `rules` (grader E on
the final message), `report` (true: grader I on the final message), `disabled` (rule ids, passed to grader I
as --disabled) and `judge` (the file name of a rubric in this folder: one `claude -p` call with no tools scores
the explanation and the fix text of the final message, and prints "JUDGE <case>#<n>: <score>/5 <reason>", or
"JUDGE <case>#<n>: not scored (<reason>)"; a JUDGE line never changes a PASS or FAIL line or the exit code). The login of `claude` comes from the real HOME (a temp HOME has
no login); the driver writes nothing there. The teardown runs once, in a finally block, on every exit path
(also SIGTERM and Ctrl-C). Needs docker and psql on PATH (pg_run runs psql on the host).
The default of --out is a new temp folder, printed at the start; it holds the transcripts and snapshots.
Output: one line "FAIL <case>#<n> <check>: <message>" for each failure, one line "<case>#<n>: PASS|FAIL"
for each run, then PASS or FAIL. Exit code: 0 pass, 1 fail or a stop (a message on stderr), 2 usage error.
"""
import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import db_eval  # noqa: E402

SKILL_DIR = db_eval.SKILL_DIR
sys.path.insert(0, os.path.join(SKILL_DIR, "graders"))

import grade_eval_results as results  # noqa: E402
CASES = os.path.join(HERE, "cases")
SCRIPTS = ("rules_file", "extract", "allowlist", "pg_run", "plan_findings")
CLAUDE_SECONDS = 900
JUDGE_SECONDS = 300
JUDGE_SCORE = re.compile(r"(?m)^SCORE:\s*([0-5])\s*/\s*5\b[ \t:.-]*(.*)$")


def allowed_tools():
    return ["Skill", "Read"] + [f"Bash(python3 {SKILL_DIR}/scripts/{name}.py:*)" for name in SCRIPTS]


def claude_argv(prompt, budget):
    argv = [
        "claude", "-p", prompt, "--model", "sonnet", "--output-format", "stream-json", "--verbose",
        "--no-session-persistence", "--plugin-dir", SKILL_DIR, "--setting-sources", "", "--strict-mcp-config",
        "--permission-mode", "dontAsk", "--tools", "Skill,Read,Bash",
    ]
    if budget:
        argv += ["--max-budget-usd", budget]
    return argv + ["--allowedTools", *allowed_tools()]


def claude_env(state):
    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    env.update({
        "PGSERVICEFILE": os.path.join(state, "pg_service.conf"),
        "PGPASSFILE": os.path.join(state, "pgpass"),
        "XDG_CONFIG_HOME": os.path.join(state, "xdg"),
        "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
    })
    return env


def grader(script, *args, stdin=None):
    return results.run_grader(script, list(args), stdin=stdin)


def grade_final_message(label, trace, expectation):
    """The failure lines of grader E (the `rules` key) and grader I (the `report` key, with `disabled`) on the
    final message of the transcript. A missing final message is one failure line."""
    checks = []
    if "rules" in expectation:
        rules = expectation["rules"]
        checks.append(("grade_rule_ids.py", ["-", "--expect", *rules["expect"], "--forbid", *rules["forbid"]]))
    if expectation.get("report"):
        checks.append(("grade_report.py", ["-", *(["--disabled", *expectation["disabled"]] if expectation.get("disabled") else [])]))
    if not checks:
        return []
    message = results.final_message(trace)
    if message is None:
        return [f"FAIL {label} trace: no final message in {trace}"]
    lines = []
    for script, args in checks:
        code, found, error = grader(script, *args, stdin=message)
        lines += [f"FAIL {label} {line[len('FAIL '):]}" for line in found]
        if code == 2:
            lines.append(f"FAIL {label} {script}: cannot grade ({error})")
    return lines


def judge_argv(prompt):
    return ["claude", "-p", prompt, "--model", "sonnet", "--no-session-persistence", "--setting-sources", "",
            "--strict-mcp-config", "--tools", ""]


def judge_env():
    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] = "1"
    return env


def judge_line(label, trace, rubric_name, cwd):
    """One JUDGE line: the score of the explanation and the fix text of the final message against the rubric.
    It is reported, never scored. The call has no tools, no session file and no database file or variable."""
    message = results.final_message(trace)
    if message is None:
        return f"JUDGE {label}: not scored (no final message)"
    try:
        with open(os.path.join(HERE, rubric_name), encoding="utf-8") as handle:
            rubric = handle.read()
        done = subprocess.run(judge_argv(f"{rubric}\n\n---\nThe final message to score:\n\n{message}"), cwd=cwd,
                              env=judge_env(), capture_output=True, text=True, timeout=JUDGE_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"JUDGE {label}: not scored ({type(error).__name__})"
    if done.returncode != 0:
        return f"JUDGE {label}: not scored (exit code {done.returncode})"
    found = JUDGE_SCORE.search(done.stdout)
    if not found:
        return f"JUDGE {label}: not scored (no score line)"
    return f"JUDGE {label}: {found.group(1)}/5 {found.group(2).strip()}".rstrip()


def grade_run(label, trace, expectation, before, after):
    """The failure lines of one run."""
    lines = []
    for script, args in (
        ("grade_refusals.py", [trace, "--expect", *expectation["expect"]]),
        ("grade_leak_scan.py", [trace, "--canaries", db_eval.CANARIES]),
    ):
        code, found, error = grader(script, *args)
        lines += [f"FAIL {label} {line[len('FAIL '):]}" for line in found]
        if code == 2:
            lines.append(f"FAIL {label} {script}: cannot grade ({error})")
    lines += grade_final_message(label, trace, expectation)
    for version in db_eval.VERSIONS:
        args = [before[version], after[version]]
        if expectation.get("sequences_may_differ"):
            args.append("--sequences-may-differ")
        code, found, error = grader("grade_db_unchanged.py", *args)
        lines += [f"FAIL {label} (postgres {version}) {line[len('FAIL '):]}" for line in found]
        if code == 2:
            lines.append(f"FAIL {label} grade_db_unchanged.py: cannot grade ({error})")
    return lines


def run_case(state, case_folder, number, out, budget):
    name = os.path.basename(case_folder)
    label = f"{name}#{number}"
    with open(os.path.join(case_folder, "db-expect.json"), encoding="utf-8") as handle:
        expectation = json.load(handle)
    with open(os.path.join(case_folder, "prompt.txt"), encoding="utf-8") as handle:
        prompt = handle.read().strip()
    work = os.path.join(out, f"{name}-{number}-work")
    db_eval.prepare_repo(case_folder, work)
    before = {v: os.path.join(out, f"{name}-{number}-before-{v}.json") for v in db_eval.VERSIONS}
    after = {v: os.path.join(out, f"{name}-{number}-after-{v}.json") for v in db_eval.VERSIONS}
    for version in db_eval.VERSIONS:
        db_eval.snapshot(state, version, before[version])
    trace = os.path.join(out, f"{name}-{number}.jsonl")
    failures = []
    try:
        with open(trace, "w", encoding="utf-8") as handle:
            done = subprocess.run(claude_argv(prompt, budget), cwd=work, env=claude_env(state), stdout=handle,
                                  stderr=subprocess.PIPE, text=True, timeout=CLAUDE_SECONDS)
        if done.returncode != 0:
            failures.append(f"FAIL {label} claude: exit code {done.returncode}")
    except subprocess.TimeoutExpired:
        failures.append(f"FAIL {label} claude: no answer in {CLAUDE_SECONDS} seconds")
    for version in db_eval.VERSIONS:
        db_eval.snapshot(state, version, after[version])
    judges = [judge_line(label, trace, expectation["judge"], out)] if expectation.get("judge") else []
    return failures + grade_run(label, trace, expectation, before, after), judges


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--case", default="*")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--out")
    parser.add_argument("--max-budget-usd")
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be 1 or more")
    cases = sorted(os.path.join(CASES, name) for name in os.listdir(CASES) if fnmatch.fnmatch(name, args.case))
    if not cases:
        parser.error(f"no case matches {args.case}")
    missing = [tool for tool in ("docker", "psql") if shutil.which(tool) is None]
    if missing:
        print(f"run_db_cases: {', '.join(missing)} not found on PATH", file=sys.stderr)
        return 1
    out = args.out or tempfile.mkdtemp(prefix="sqlskill-dbout-")
    os.makedirs(out, exist_ok=True)
    state = tempfile.mkdtemp(prefix="sqlskill-dbstate-")
    print(f"run_db_cases: transcripts and snapshots in {out}", file=sys.stderr)
    output, stop = [], db_eval.install_stop_handlers()
    code = 0
    try:
        db_eval.setup(state)
        for case_folder in cases:
            for number in range(1, args.runs + 1):
                failures, judges = run_case(state, case_folder, number, out, args.max_budget_usd)
                label = f"{os.path.basename(case_folder)}#{number}"
                output += failures + [f"{label}: {'FAIL' if failures else 'PASS'}"] + judges
    except db_eval.Stopped as stopped:
        code = stopped.code
        print("run_db_cases: stopped", file=sys.stderr)
    except db_eval.Failure as failure:
        code = 1
        print(f"run_db_cases: {failure}", file=sys.stderr)
    finally:
        stop()
        try:
            code = max(code, db_eval.teardown(state))
        except db_eval.Failure as failure:
            print(f"run_db_cases: {failure}", file=sys.stderr)
            code = max(code, 1)
    failed = any(line.startswith("FAIL ") for line in output)
    if output:
        print("\n".join(output + ["FAIL" if failed else "PASS"]))
    return max(code, 1 if failed else 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
