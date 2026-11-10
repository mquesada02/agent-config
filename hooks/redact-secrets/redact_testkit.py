"""Shared helpers for the test_redact_*.py files. Tests drive redact_post.py as a subprocess, as Claude Code does."""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
POST = os.path.join(HERE, "redact_post.py")
PRE = os.path.join(HERE, "redact_pre.py")
FILTER = os.path.join(HERE, "redact_filter.py")


def bash_event(stdout, stderr=""):
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "run"},
        "tool_response": {
            "stdout": stdout,
            "stderr": stderr,
            "interrupted": False,
            "isImage": False,
            "noOutputExpected": False,
        },
    }


def filter_env(switch=None):
    """The environment of a hook run: the real one without REDACT_SECRETS_TEST_SLEEP, then switch if given."""
    env = {key: value for key, value in os.environ.items() if key != "REDACT_SECRETS_TEST_SLEEP"}
    if switch is not None:
        env["REDACT_SECRETS_TEST_SLEEP"] = switch
    return env


def run_hook(script, stdin, switch=None):
    """Run a hook script; stdin is a dict (sent as JSON) or a raw string. switch sets REDACT_SECRETS_TEST_SLEEP."""
    env = filter_env(switch)
    data = stdin if isinstance(stdin, str) else json.dumps(stdin)
    return subprocess.run(
        [sys.executable, "-I", script], input=data, capture_output=True, text=True, env=env, timeout=30
    )


def run_post(stdin, sleep=None):
    """Run the PostToolUse hook."""
    return run_hook(POST, stdin, sleep)


def updated_output(result):
    """The updatedToolOutput of a hook result, or None when the hook printed nothing."""
    if result.stdout == "":
        return None
    payload = json.loads(result.stdout)
    hook_output = payload["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "PostToolUse"
    return hook_output["updatedToolOutput"]


def redact(text):
    """Redact text through the hook (Bash stdout). Return the text the model would see."""
    result = run_post(bash_event(text))
    assert result.returncode == 0, result.stderr
    output = updated_output(result)
    return text if output is None else output["stdout"]


def bash_pre_event(command, **extra):
    """A PreToolUse event for a Bash call; extra keys become more tool_input fields."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command, **extra},
    }


def run_pre(stdin, switch=None):
    """Run the PreToolUse rewrite hook."""
    return run_hook(PRE, stdin, switch)


def monitor_pre_event(command, **extra):
    """A PreToolUse event for a Monitor call; extra keys become more tool_input fields."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Monitor",
        "tool_input": {"command": command, **extra},
    }


def run_filter(data, switch=None):
    """Run the Monitor line filter with bytes on stdin. Bytes mode keeps line endings and invalid UTF-8 exact."""
    return subprocess.run(
        [sys.executable, "-I", "-u", FILTER], input=data, capture_output=True, env=filter_env(switch), timeout=30
    )


def filt(text, switch=None):
    """The text that the Monitor filter writes for a text on stdin."""
    result = run_filter(text.encode("utf-8", "surrogateescape"), switch)
    assert result.returncode == 0, result.stderr
    return result.stdout.decode("utf-8", "surrogateescape")


def lines(*parts):
    """The parts joined as lines, each ending in a newline."""
    return "\n".join(parts) + "\n"


def normalized(text):
    """The text with each run of white space collapsed to one space."""
    return re.sub(r"\s+", " ", text)


def read_module(name):
    """The text of a file in the hook folder."""
    with open(os.path.join(HERE, name), encoding="utf-8") as handle:
        return handle.read()
