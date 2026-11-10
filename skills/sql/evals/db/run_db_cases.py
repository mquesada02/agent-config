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
the tools Skill, Read and Bash limited to python3 on four scripts of the skill (rules_file.py, extract.py,
allowlist.py, pg_run.py). The environment sets PGSERVICEFILE, PGPASSFILE and XDG_CONFIG_HOME to the state
folder and drops every other PG* variable. The login of `claude` comes from the real HOME (a temp HOME has
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
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import db_eval  # noqa: E402

SKILL_DIR = db_eval.SKILL_DIR
GRADERS = os.path.join(SKILL_DIR, "graders")
CASES = os.path.join(HERE, "cases")
SCRIPTS = ("rules_file", "extract", "allowlist", "pg_run")
CLAUDE_SECONDS = 900


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


def prepare_work_folder(case_folder, work):
    shutil.copytree(os.path.join(case_folder, "repo"), work)
    for argv in (["git", "init", "-q"], ["git", "remote", "add", "origin", db_eval.ORIGIN]):
        if subprocess.run(argv, cwd=work, capture_output=True).returncode != 0:
            raise db_eval.Failure(f"{' '.join(argv[:2])} failed in {work}")


def grader(script, *args):
    done = subprocess.run([sys.executable, "-I", os.path.join(GRADERS, script), *args],
                          capture_output=True, text=True)
    lines = [line for line in done.stdout.splitlines() if line.startswith("FAIL ") and line != "FAIL"]
    return done.returncode, lines, done.stderr.strip()


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
    prepare_work_folder(case_folder, work)
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
    return failures + grade_run(label, trace, expectation, before, after)


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
                failures = run_case(state, case_folder, number, out, args.max_budget_usd)
                label = f"{os.path.basename(case_folder)}#{number}"
                output += failures + [f"{label}: {'FAIL' if failures else 'PASS'}"]
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
