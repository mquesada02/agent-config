#!/usr/bin/env python3
"""PreToolUse hook on Bash: the permission prompt of the `/sql setup` write call shows the real diff.

The hook reads the hook input JSON on stdin. A command that does not call the setup script `write` step
passes with no output. A write call must be exactly one simple command:

    [XDG_CONFIG_HOME=value] python3 [-I] <path>/setup_files.py write <repo> --proposal <file> --confirm <digest>

Any other variable prefix is denied, and <path> must lead to the setup_files.py of the sql skill in the same
tree as this hook (TRUSTED_SCRIPT): the hook runs `plan` unsandboxed before the prompt, so it never runs a
script or a loader variable that the model chose.

The hook runs `setup_files.py plan` for the same repo and proposal, checks the plan digest against
`--confirm`, and answers `ask` with the full diff of the plan in the decision reason, so that Claude Code
shows the diff in the permission prompt. Every error is a `deny` with a reason that starts with
`Setup write check:`; the hook never prints an allow and never crashes open (`decide` catches every
exception). Exit code 0 always.

Run log: when the environment variable SETUP_DIFF_PROMPT_LOG names a file, the hook appends one JSON line
{"decision": "ask" or "deny", "reason": "..."} for every ask or deny that it prints (the two-turn runner
of the sql skill reads it). A log write error never changes the decision.
"""
import json
import os
import re
import shlex
import subprocess
import sys

PLAN_SECONDS = 15
LOG_VARIABLE = "SETUP_DIFF_PROMPT_LOG"
SCRIPT_NAME = "setup_files.py"
# The hook runs `plan` outside the sandbox and before the permission prompt, so it runs only this script, never a path or a
# variable that the model chose: the loader variables (LD_PRELOAD, LD_AUDIT, ...) would load model code into that run.
TRUSTED_SCRIPT = os.path.realpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "skills", "sql",
                                               "scripts", SCRIPT_NAME))
ALLOWED_VARIABLES = ("XDG_CONFIG_HOME",)
# The raw text that the permission ask rule of ticket 509 matched (the script name, then write). The hook replaces that rule
# (a rule and a hook that both ask show only the rule text in the prompt, never the diff), so it must refuse every command
# that this text matches and that is not the exact write form.
RAW_WRITE = re.compile(re.escape(SCRIPT_NAME) + r"\W+write\b")
DENY_PREFIX = "Setup write check: "
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
OPERATOR = re.compile(r"^[();<>|&]+$")
FORM = "[XDG_CONFIG_HOME=value] python3 [-I] <path>/setup_files.py write <repo> --proposal <file> --confirm <digest>"
FORM_HELP = "call write alone, as one simple command in this form: " + FORM


class Refusal(Exception):
    """A check failed: `decide` turns it into a deny with this reason."""


def deny(reason):
    return {"decision": "deny", "reason": DENY_PREFIX + reason}


def split_words(command):
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def calls_write(words):
    return any(os.path.basename(word) == SCRIPT_NAME and index + 1 < len(words) and words[index + 1] == "write"
               for index, word in enumerate(words))


def parse_write(words):
    """(assignments, script, repo, proposal, confirm) of the exact write form; raises Refusal for any other form."""
    if any(OPERATOR.match(word) for word in words):
        raise Refusal("this is a compound command, a pipe or a redirect; " + FORM_HELP)
    index = 0
    assignments = {}
    while index < len(words) and ASSIGNMENT.match(words[index]):
        name, _, value = words[index].partition("=")
        assignments[name] = value
        index += 1
    if index >= len(words) or words[index] != "python3":
        raise Refusal("the command does not start with python3; " + FORM_HELP)
    index += 1
    if index < len(words) and words[index] == "-I":
        index += 1
    if index + 1 >= len(words) or os.path.basename(words[index]) != SCRIPT_NAME or words[index + 1] != "write":
        raise Refusal("the script is not called directly with write; " + FORM_HELP)
    script = words[index]
    rest = words[index + 2:]
    if not rest or rest[0].startswith("--"):
        raise Refusal("the repo folder is missing after write; " + FORM_HELP)
    repo, options = rest[0], rest[1:]
    found = {}
    while options:
        if options[0] not in ("--proposal", "--confirm") or len(options) < 2 or options[0] in found:
            raise Refusal("unexpected, repeated or incomplete words after the repo folder; " + FORM_HELP)
        found[options[0]] = options[1]
        options = options[2:]
    if set(found) != {"--proposal", "--confirm"}:
        raise Refusal("the command needs --proposal and --confirm; " + FORM_HELP)
    return assignments, script, repo, found["--proposal"], found["--confirm"]


def run_plan(script, repo, proposal, assignments, cwd, plan_seconds):
    """The decoded plan; raises Refusal when the plan cannot give a digest."""
    env = dict(os.environ)
    env.update(assignments)
    try:
        done = subprocess.run([sys.executable, "-I", script, "plan", repo, "--proposal", proposal],
                              capture_output=True, text=True, timeout=plan_seconds, cwd=cwd, env=env)
    except subprocess.TimeoutExpired:
        raise Refusal("plan did not end in %s seconds" % plan_seconds)
    except OSError as error:
        raise Refusal("plan could not start: %s" % error)
    try:
        plan = json.loads(done.stdout)
    except ValueError:
        plan = None
    if not isinstance(plan, dict):
        raise Refusal("plan printed no JSON object (exit code %s)" % done.returncode)
    if plan.get("ok") is not True:
        raise Refusal("plan refused: %s" % (plan.get("message") or plan.get("reason") or "no message"))
    if done.returncode != 0:
        raise Refusal("plan has ok true but exit code %s" % done.returncode)
    if not isinstance(plan.get("digest"), str):
        raise Refusal("plan has no digest")
    return plan


def diff_text(plan):
    texts = []
    for name in ("rules_file", "allowlist"):
        part = plan.get(name)
        diff = part.get("diff") if isinstance(part, dict) else None
        if isinstance(diff, str) and diff.strip():
            texts.append(diff.rstrip("\n"))
    return "\n\n".join(texts) if texts else "no file changes"


def decide(hook_input, plan_seconds=PLAN_SECONDS):
    """The decision dictionary {"decision", "reason"} (ask or deny), or None for a pass. Never raises."""
    try:
        return decide_checked(hook_input, plan_seconds)
    except Refusal as refusal:
        return deny(str(refusal))
    except Exception as error:  # fail closed: a bug in the hook is a deny, never an allow
        return deny("internal error in the hook: %s: %s" % (type(error).__name__, error))


def decide_checked(hook_input, plan_seconds):
    if not isinstance(hook_input, dict):
        raise Refusal("the hook input is not a JSON object")
    if hook_input.get("tool_name") != "Bash":
        return None
    tool_input = hook_input.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        raise Refusal("the Bash call has no command text")
    if SCRIPT_NAME not in command:
        return None
    try:
        words = split_words(command)
    except ValueError as error:
        raise Refusal("the command cannot be split into shell words (%s)" % error)
    if not (RAW_WRITE.search(command) or calls_write(words)):
        return None
    if "\n" in command or "\r" in command:
        raise Refusal("the command is not one line; " + FORM_HELP)
    assignments, script, repo, proposal, confirm = parse_write(words)
    cwd = hook_input.get("cwd") if isinstance(hook_input.get("cwd"), str) else None
    repo, proposal = os.path.expanduser(repo), os.path.expanduser(proposal)
    if not (os.path.isabs(repo) and os.path.isabs(proposal)):
        raise Refusal("the repo folder and the proposal file must be absolute paths")
    refused = [name for name in assignments if name not in ALLOWED_VARIABLES]
    if refused:
        raise Refusal("the variable %s is not allowed before python3; only %s may be set. %s"
                    % (refused[0], ", ".join(ALLOWED_VARIABLES), FORM_HELP))
    script = os.path.expanduser(script)
    full = script if os.path.isabs(script) else os.path.join(cwd or os.getcwd(), script)
    if os.path.realpath(full) != TRUSTED_SCRIPT:
        raise Refusal("the script %s is not the sql skill setup_files.py of this hook tree (%s)" % (script, TRUSTED_SCRIPT))
    if not os.path.isfile(full):
        raise Refusal("the script %s was not found" % script)
    plan = run_plan(TRUSTED_SCRIPT, repo, proposal, assignments, cwd, plan_seconds)
    if plan["digest"] != confirm:
        raise Refusal("the digest differs from the plan: the files changed after the plan. "
                    "Run plan again, then call write with the new digest")
    return {"decision": "ask", "reason": "Diff to confirm:\n" + diff_text(plan)}


def log(decision):
    path = os.environ.get(LOG_VARIABLE)
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(decision) + "\n")
    except OSError:
        pass


def main():
    try:
        data = json.loads(sys.stdin.read())
    except ValueError:
        data = None
    decision = decide(data)
    if decision is None:
        return 0
    log(decision)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": decision["decision"],
        "permissionDecisionReason": decision["reason"]}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
