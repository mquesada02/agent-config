"""Shared helpers for the test_redact_*.py files. Tests drive redact_post.py as a subprocess, as Claude Code does."""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
POST = os.path.join(HERE, "redact_post.py")


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


def run_post(stdin, sleep=None):
    """Run the PostToolUse hook; stdin is a dict (sent as JSON) or a raw string."""
    env = {key: value for key, value in os.environ.items() if key != "REDACT_SECRETS_TEST_SLEEP"}
    if sleep is not None:
        env["REDACT_SECRETS_TEST_SLEEP"] = sleep
    data = stdin if isinstance(stdin, str) else json.dumps(stdin)
    return subprocess.run(
        [sys.executable, "-I", POST], input=data, capture_output=True, text=True, env=env, timeout=30
    )


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
