#!/usr/bin/env python3
"""Hand-run two-turn runner: `/sql setup` shows the diff, waits for the user, and only then writes.

Usage: run_setup_turns.py [--case GLOB] [--runs N] [--out FOLDER] [--max-budget-usd USD] [--evals DIR]

A `claude plugin eval` case has one user turn, so each `setup-*` prompt holds the confirmation in advance.
For each case under the evals folder (default `setup-*`) and each run, this runner prepares the case with its
own scaffold, then runs two turns of one `claude -p` session (model sonnet): turn 1 is the case prompt up to its
confirmation sentence (`--session-id`), turn 2 is a plain confirmation (`--resume` of the same session id).

Turn 1 has the permission ask rule of the setup write call (the one `permissions.ask` entry for `setup_files.py write`
of the repo `settings.json`; exit code 2 when it is not there exactly once): in `claude -p` an `ask` is a deny and wins over
the bare `Bash` allow, so turn 1 can never write. Turn 1 also has the setup diff hook (the one `hooks.PreToolUse` command
of the repo `settings.json` that runs `setup_diff_prompt.py`, with `~/.claude/` replaced by the repo folder; exit code 2 when it
is not there exactly once): it answers `ask` with the plan diff, and it writes each ask or deny to the file that
SETUP_DIFF_PROMPT_LOG names (in the run's temp folder). Turn 2 runs without the rule and without the hook, as the
user's yes in the prompt.

Turn 1 checks (a failure ends the run; turn 2 does not run): `no-write` (no change call except a `setup_files.py write`
call that the permission rule or the hook denied, and the content hashes of the work folder without `.git` and of the
temp HOME folder are the same before and after), `plan` (a `setup_files.py plan` call with a readable plan result) and
`prompt-diff` (the hook log has an `ask` entry whose reason holds every added line of the diffs of the latest plan: each
diff line that starts with `+`, not the `+++` header, equals a whole line of the reason, trailing white space removed on
both sides). Turn 2 checks: `write` (a change call, or none when the case `expected.json` has `written` false), then
grader D (`grade_setup.py`, with `--diff-in-prompt`) on the combined trace of both turns with the case's `expected.json`.

Isolation: the case gets a temp HOME and a temp XDG_CONFIG_HOME under the out folder (the scaffold runs with
them). The runner refuses to start, before it creates any folder, when the out folder is the real home folder
(read from the account database) or inside it. The `claude` child keeps the real HOME only for its login (a temp
HOME is not logged in); `PGSERVICEFILE`, `XDG_CONFIG_HOME` and `TMPDIR` point to temp folders, git is cut off
from the real git config, the session has no user settings, no CLAUDE.md and no MCP server, and its tools are
Skill, Read, Glob, Grep, Write and Edit (limited to the run's folders) and Bash. Bash runs only in the Claude
Code OS sandbox (`--settings`: sandbox enabled, no unsandboxed command, writes only in the run's work, config
and tmp folders, no network), and `formatter_install.py apply` is denied. Residual risks: the child can read
files under the real HOME, and such text can land in the persisted test transcript; session persistence stays
on (`--resume` needs it), so `claude` keeps the test sessions under its own state folder in the real HOME.

Output: one line `FAIL <case>#<n> <check>: <message>` for each failed check, then `<case>#<n>: PASS|FAIL` for
each run, then a last line PASS or FAIL. The turn files are kept in the out folder as `<case>-<n>-turn1.jsonl`,
`-turn2.jsonl` and `-trace.jsonl`. Exit code: 0 all runs pass; 1 a run fails or the runner refuses to start;
2 usage error (a message on stderr, nothing on stdout). Usage errors win over the refusal to start.
"""
import argparse
import fnmatch
import hashlib
import json
import os
import pwd
import re
import subprocess
import sys
import tempfile
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
EVALS = os.path.dirname(HERE)
SKILL_DIR = os.path.dirname(EVALS)
REPO_DIR = os.path.dirname(os.path.dirname(SKILL_DIR))
sys.path.insert(0, os.path.join(SKILL_DIR, "graders"))

import grade_eval_results as results  # noqa: E402
import grade_setup  # noqa: E402

CONFIRMATION = "Show me the diff, and then confirm it and write the files."
TURN2_PROMPT = "I confirm the diff. Write the files now."
CLAUDE_SECONDS = 900
SCAFFOLD_SECONDS = 600
SANDBOX_FAILED = "Sandbox is enabled but failed to initialize"
WRITE_SCRIPT = "setup_files.py write"
HOOK_SCRIPT = "setup_diff_prompt.py"
HOOK_LOG_VARIABLE = "SETUP_DIFF_PROMPT_LOG"
HOOK_DENIAL = "Setup write check:"
# the one file under the temp HOME that `claude` itself writes in a run (the global git ignore line `**/.claude/.cc-writes/`)
CLAUDE_OWN_FILES = (os.path.join(".config", "git", "ignore"),)
KEY = "example.com/acme/shop"
PROMPT_LINE = re.compile(r"^(\s+)prompt:\s*\|[-+]?\s*$")


class Usage(Exception):
    pass


def real_home():
    return os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir)


def inside(path, folder):
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def read_prompt(case_folder):
    """The text of the `prompt: |` block under `execution:` of case.yaml. Any other form is a Usage error."""
    name = os.path.basename(case_folder)
    with open(os.path.join(case_folder, "case.yaml"), encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if re.match(r"^execution:\s*$", line))
    except StopIteration:
        raise Usage(f"{name}: case.yaml has no execution block")
    for i in range(start + 1, len(lines)):
        if lines[i].strip() and not lines[i].startswith(" "):
            break
        found = PROMPT_LINE.match(lines[i])
        if not found:
            continue
        indent = len(found.group(1))
        block = []
        for line in lines[i + 1:]:
            if line.strip() and len(line) - len(line.lstrip(" ")) <= indent:
                break
            block.append(line)
        body = [line for line in block if line.strip()]
        if not body:
            break
        margin = min(len(line) - len(line.lstrip(" ")) for line in body)
        return "\n".join(line[margin:] for line in block).strip()
    raise Usage(f"{name}: the prompt of case.yaml is not a `prompt: |` block under `execution:`")


def split_prompt(case_folder):
    """Turn 1: the case prompt before its confirmation sentence, trimmed."""
    text = read_prompt(case_folder)
    if CONFIRMATION not in text:
        raise Usage(f"{os.path.basename(case_folder)}: the prompt has no confirmation sentence")
    return text.partition(CONFIRMATION)[0].strip()


def snapshot(folder, skip_git=False, skip=()):
    """Relative path -> sha256 of every file under the folder (the top-level .git is skipped on request, and so is each
    relative path of `skip`)."""
    found = {}
    for current, dirs, files in os.walk(folder):
        if skip_git and current == folder and ".git" in dirs:
            dirs.remove(".git")
        for name in files:
            path = os.path.join(current, name)
            if os.path.relpath(path, folder) in skip:
                continue
            try:
                with open(path, "rb") as handle:
                    found[os.path.relpath(path, folder)] = hashlib.sha256(handle.read()).hexdigest()
            except OSError:
                found[os.path.relpath(path, folder)] = "unreadable"
    return found


def allowed_tools(folders):
    """Bash is listed because the auto-allow of the sandbox alone does not cover a compound command with shell
    variables in dontAsk mode; the sandbox (see sandbox_settings) is what confines it."""
    rules = ["Skill", "Read", "Glob", "Grep", "Bash"]
    for tool in ("Write", "Edit"):
        rules += [f"{tool}(/{folder}/**)" for folder in folders]
    return rules


# `apply` runs the package manager with the real HOME (it reads ~/.npmrc and writes the npm cache there)
DENIED_TOOLS = (f"Bash(python3 {SKILL_DIR}/scripts/formatter_install.py apply:*)", "Bash(*formatter_install.py apply*)")


def sandbox_settings(folders, ask=None, hook=None):
    """Bash runs only in the OS sandbox: no unsandboxed command, writes only in the run folders, no network.
    `ask`: the permission ask rules and `hook`: the `hooks` setting for turn 1 (see the module docstring); turn 2 has none."""
    settings = {"sandbox": {"enabled": True, "failIfUnavailable": True, "autoAllowBashIfSandboxed": True,
                            "allowUnsandboxedCommands": False, "filesystem": {"allowWrite": list(folders)},
                            "network": {"allowedDomains": []}}}
    if ask:
        settings["permissions"] = {"ask": list(ask)}
    if hook:
        settings["hooks"] = hook
    return json.dumps(settings)


def write_ask_rule():
    """The one `permissions.ask` entry of the repo settings.json for the setup write call. Raises Usage otherwise."""
    path = os.path.join(REPO_DIR, "settings.json")
    try:
        with open(path, encoding="utf-8") as handle:
            ask = json.load(handle)["permissions"]["ask"]
        rules = [rule for rule in ask if isinstance(rule, str) and WRITE_SCRIPT in rule]
    except (OSError, ValueError, KeyError, TypeError):
        raise Usage(f"cannot read the permissions.ask list of {path}")
    if len(rules) != 1:
        raise Usage(f"{path} needs exactly one permissions.ask entry for {WRITE_SCRIPT}, found {len(rules)}")
    return rules[0]


def setup_hook_settings():
    """The `hooks` setting for turn 1: the one `hooks.PreToolUse` command of the repo settings.json that runs the setup diff
    hook, alone in a group with the matcher of its group, with `~/.claude/` in its command replaced by the repo folder (so
    the child runs the hook of the branch under test). Raises Usage when there is not exactly one such command."""
    path = os.path.join(REPO_DIR, "settings.json")
    try:
        with open(path, encoding="utf-8") as handle:
            groups = json.load(handle)["hooks"]["PreToolUse"]
        found = [(group, entry) for group in groups for entry in group["hooks"]
                 if isinstance(entry.get("command"), str) and HOOK_SCRIPT in entry["command"]]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        found = None
    if found is None:
        raise Usage(f"cannot read the hooks.PreToolUse list of {path} (it needs one command that runs {HOOK_SCRIPT})")
    if len(found) != 1:
        raise Usage(f"{path} needs exactly one hooks.PreToolUse command that runs {HOOK_SCRIPT}, found {len(found)}")
    group, entry = found[0]
    entry = {**entry, "command": entry["command"].replace("~/.claude/", REPO_DIR + os.sep)}
    return {"PreToolUse": [{"matcher": group.get("matcher", "*"), "hooks": [entry]}]}


def sandbox_failed(text, label, turn):
    """The FAIL line when a tool result of a turn says that the sandbox failed to initialize (claude then runs Bash unsandboxed)."""
    try:
        tool_results = [event[2] for event in grade_setup.events(text) if event[0] == "result"]
    except ValueError:
        return []
    if any(SANDBOX_FAILED in str(content) for content in tool_results):
        return [f"FAIL {label} sandbox: the sandbox failed to initialize in turn {turn}, Bash may have run unsandboxed"]
    return []


def claude_argv(prompt, session, budget, folders, ask=None, hook=None):
    return ["claude", "-p", prompt, "--model", "sonnet", "--output-format", "stream-json", "--verbose",
            "--plugin-dir", SKILL_DIR, "--setting-sources", "", "--settings", sandbox_settings(folders, ask, hook),
            "--strict-mcp-config", "--permission-mode", "dontAsk", "--tools", "Skill,Read,Glob,Grep,Write,Edit,Bash",
            "--max-budget-usd", budget, *session, "--disallowedTools", *DENIED_TOOLS, "--allowedTools",
            *allowed_tools(folders)]


def claude_env(state):
    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    env.update({
        "PGSERVICEFILE": os.path.join(state["home"], ".pg_service.conf"),
        "XDG_CONFIG_HOME": state["config"],
        "TMPDIR": state["tmp"],
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
    })
    return env


def run_turn(argv, cwd, env, trace_path, turn):
    """None when the turn ran, else the claude FAIL message of the turn."""
    try:
        with open(trace_path, "w", encoding="utf-8") as handle:
            done = subprocess.run(argv, cwd=cwd, env=env, stdout=handle, stderr=subprocess.PIPE, text=True,
                                  timeout=CLAUDE_SECONDS)
    except subprocess.TimeoutExpired:
        return f"claude: no answer in {CLAUDE_SECONDS} seconds in turn {turn}"
    except OSError:
        return f"claude: cannot start in turn {turn}"
    return f"claude: exit code {done.returncode} in turn {turn}" if done.returncode != 0 else None


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def change_calls(trace):
    return [event for event in trace if event[0] == "call" and grade_setup.change_target(event[2], event[3])]


def latest_plan(trace):
    """(plan, index of its result in the trace) of the latest readable `setup_files.py plan` result, or None."""
    plan_ids, latest = set(), None
    for index, event in enumerate(trace):
        if event[0] == "call" and event[2] == "Bash" and isinstance(event[3], dict):
            command = event[3].get("command")
            if isinstance(command, str) and grade_setup.PLAN_CALL.search(command):
                plan_ids.add(event[1])
        elif event[0] == "result" and event[1] in plan_ids:
            plan = grade_setup.parse_plan(event[2])
            if plan is not None:
                latest = (plan, index)
    return latest


def denied_calls(trace):
    """The ids of the calls whose tool result says that the permission was denied (an `ask` rule or a hook `ask` is a deny in
    `claude -p`), or that the setup diff hook denied the call (its reason starts with `Setup write check:`)."""
    return {event[1] for event in trace
            if event[0] == "result" and (("Permission to use" in str(event[2]) and "has been denied" in str(event[2]))
                                         or HOOK_DENIAL in str(event[2]))}


def is_write_call(event):
    """A `setup_files.py write` call that does nothing else: a command that also redirects to a rules or allowlist file is
    another change route (change_target names such a command a write call first)."""
    target = grade_setup.change_target(event[2], event[3]) if event[0] == "call" else None
    return bool(target) and target[0] == "write" and not grade_setup.bash_changes_a_file(target[1])


def is_denied_write(event, denied):
    return is_write_call(event) and event[1] in denied


def undenied_change_calls(trace):
    """The change calls of a turn 1 that are a FAIL: all of them, except a `setup_files.py write` call that was denied."""
    denied = denied_calls(trace)
    return [event for event in change_calls(trace) if not is_denied_write(event, denied)]


def prompt_diff_problem(log_path, plan):
    """None when the hook log holds an `ask` entry whose reason has every added diff line of the latest plan, else the
    message of the `prompt-diff` FAIL. The hook runs in turn 1 only; its `ask` is the permission prompt that shows the diff."""
    try:
        text = read_text(log_path)
    except OSError:
        return "the hook did not run (no hook log)"
    asks = []
    for line in text.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("decision") == "ask" and isinstance(entry.get("reason"), str):
            asks.append(entry["reason"])
    if not asks:
        return "the hook did not run (no ask entry in the hook log)"
    reason_lines = {line.rstrip() for line in asks[-1].splitlines()}
    missing = next((line for line in grade_setup.added_lines(plan) if "+" + line not in reason_lines), None)
    if missing is not None:
        return f"the diff line {'+' + missing!r} is not in the ask of the hook"
    return None


def run_one(case_folder, number, out, budget, turn1_prompt, ask_rule, hook):
    """The failure lines of one run, each starting with FAIL."""
    name = os.path.basename(case_folder)
    label = f"{name}#{number}"
    run_folder = os.path.join(out, f"{name}-{number}")
    state = {"work": os.path.join(run_folder, "work"), "home": os.path.join(run_folder, "home"),
             "tmp": os.path.join(run_folder, "tmp")}
    state["config"] = os.path.join(state["home"], ".config")
    if os.path.exists(run_folder):
        return [f"FAIL {label} scaffold: the run folder {run_folder} exists, use a new --out"]
    for key in ("work", "config", "tmp"):
        os.makedirs(state[key], exist_ok=True)
    scaffold_env = {**os.environ, "HOME": state["home"], "XDG_CONFIG_HOME": state["config"]}
    try:
        done = subprocess.run(["bash", os.path.join(case_folder, "scaffold.sh")], cwd=state["work"], env=scaffold_env,
                              capture_output=True, text=True, timeout=SCAFFOLD_SECONDS)
    except subprocess.TimeoutExpired:
        return [f"FAIL {label} scaffold: no end in {SCAFFOLD_SECONDS} seconds"]
    if done.returncode != 0:
        first = next((line.strip() for line in done.stderr.splitlines() if line.strip()), f"exit code {done.returncode}")
        return [f"FAIL {label} scaffold: {first}"]
    with open(os.path.join(case_folder, "expected.json"), encoding="utf-8") as handle:
        expect = json.load(handle)
    before = (snapshot(state["work"], skip_git=True), snapshot(state["home"], skip=CLAUDE_OWN_FILES))
    folders = (state["work"], state["config"], state["tmp"])
    env = claude_env(state)
    hook_log = os.path.join(state["tmp"], "hook.log")
    env[HOOK_LOG_VARIABLE] = hook_log
    session = str(uuid.uuid4())
    paths = {suffix: os.path.join(out, f"{name}-{number}-{suffix}.jsonl") for suffix in ("turn1", "turn2", "trace")}

    problem = run_turn(claude_argv(turn1_prompt, ["--session-id", session], budget, folders, [ask_rule], hook), state["work"], env,
                       paths["turn1"], 1)
    if problem:
        return [f"FAIL {label} {problem}"]
    text1 = read_text(paths["turn1"])
    sandbox_line = sandbox_failed(text1, label, 1)
    if sandbox_line:
        return sandbox_line
    message = results.final_message(paths["turn1"])
    try:
        trace1 = grade_setup.events(text1)
    except ValueError:
        message = None
    if message is None:
        return [f"FAIL {label} turn1 final: no final message"]
    failures = []
    after = (snapshot(state["work"], skip_git=True), snapshot(state["home"], skip=CLAUDE_OWN_FILES))
    if undenied_change_calls(trace1):
        failures.append(f"FAIL {label} turn1 no-write: a change call in turn 1 that the permission rule did not deny")
    elif before != after:
        failures.append(f"FAIL {label} turn1 no-write: a file of the work folder or of the temp HOME changed in turn 1")
    plan_found = latest_plan(trace1)
    if plan_found is None:
        failures.append(f"FAIL {label} turn1 plan: no setup_files.py plan call with a readable plan result")
    else:
        problem = prompt_diff_problem(hook_log, plan_found[0])
        if problem is not None:
            failures.append(f"FAIL {label} turn1 prompt-diff: {problem}")
    if failures:
        return failures

    problem = run_turn(claude_argv(TURN2_PROMPT, ["--resume", session], budget, folders), state["work"], env,
                       paths["turn2"], 2)
    if problem:
        return [f"FAIL {label} {problem}"]
    text2 = read_text(paths["turn2"])
    with open(paths["trace"], "w", encoding="utf-8") as handle:
        handle.write(text1 if text1.endswith("\n") else text1 + "\n")
        handle.write(text2)
    sandbox_line = sandbox_failed(text2, label, 2)
    if sandbox_line:
        return sandbox_line
    if results.final_message(paths["turn2"]) is None:
        failures.append(f"FAIL {label} turn2 final: no final message")
    try:
        trace2 = grade_setup.events(text2)
    except ValueError:
        trace2 = None
    if trace2 is not None:
        changed = bool(change_calls(trace2))
        written = expect.get("written", True)
        if written and not changed:
            failures.append(f"FAIL {label} turn2 write: no change call in turn 2")
        elif changed and not written:
            failures.append(f"FAIL {label} turn2 write: a change call in turn 2, and the case expects no write")
    args = [paths["trace"], "--repo", state["work"], "--expect", os.path.join(case_folder, "expected.json"),
            "--diff-in-prompt"]
    if "services" in expect or expect.get("no_allowlist"):
        args += ["--allowlist", os.path.join(state["config"], "sql-skill", "allowlist.toml"), "--key", KEY]
    code, lines, error = results.run_grader("grade_setup.py", args)
    failures += [f"FAIL {label} D: {line[len('FAIL '):]}" for line in lines]
    if code == 2:
        failures.append(f"FAIL {label} D: cannot grade ({error})")
    elif code != 0 and not lines:
        failures.append(f"FAIL {label} D: grader failed with exit code {code} ({error})")
    return failures


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--case", default="setup-*")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--out")
    parser.add_argument("--max-budget-usd", default="3")
    parser.add_argument("--evals")
    args = parser.parse_args(argv)
    try:
        if args.runs < 1:
            raise Usage("--runs must be 1 or more")
        evals = os.path.realpath(args.evals or EVALS)
        if not os.path.isdir(evals):
            raise Usage(f"the evals folder does not exist: {evals}")
        cases = sorted(os.path.join(evals, name) for name in os.listdir(evals)
                       if fnmatch.fnmatch(name, args.case) and os.path.isfile(os.path.join(evals, name, "case.yaml")))
        if not cases:
            raise Usage(f"no case matches {args.case}")
        prompts = {case_folder: split_prompt(case_folder) for case_folder in cases}
        for case_folder in cases:
            for needed in ("scaffold.sh", "expected.json"):
                if not os.path.isfile(os.path.join(case_folder, needed)):
                    raise Usage(f"{os.path.basename(case_folder)}: no {needed}")
        ask_rule = write_ask_rule()
        hook = setup_hook_settings()
    except Usage as error:
        print(f"run_setup_turns: {error}", file=sys.stderr)
        return 2
    base = os.path.realpath(args.out) if args.out else os.path.realpath(tempfile.gettempdir())
    if inside(base, real_home()):
        print(f"run_setup_turns: refusing to start: {base} is the real home folder or inside it", file=sys.stderr)
        return 1
    if args.out:
        out = base
        os.makedirs(out, exist_ok=True)
    else:
        out = tempfile.mkdtemp(prefix="sqlskill-turnsout-", dir=base)
    print(f"run_setup_turns: turn files in {out}", file=sys.stderr)
    failed = False
    for case_folder in cases:
        name = os.path.basename(case_folder)
        for number in range(1, args.runs + 1):
            lines = run_one(case_folder, number, out, args.max_budget_usd, prompts[case_folder], ask_rule, hook)
            failed = failed or bool(lines)
            print("\n".join(lines + [f"{name}#{number}: {'FAIL' if lines else 'PASS'}"]), flush=True)
    print("FAIL" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
