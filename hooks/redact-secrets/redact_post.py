"""PostToolUse hook: replace secret values in the output of Bash, Read and Grep with ***.

It reads the event JSON on stdin, redacts every string value of `tool_response` (the shape of the tool
output is kept) and prints `hookSpecificOutput.updatedToolOutput` when a value changed. It prints nothing
when nothing changed. It fails closed: on any error, or after 5 seconds, it prints the fixed notice
`[output hidden: redaction hook failed: <error class>]` in the tool's own shape, never a part of the output.

Residual risks (the later tickets add theirs to this comment):
- The secret stays in the command text (`tool_input`), in OpenTelemetry and analytics, and in the
  background task output file on disk.
- The PreToolUse rewrite hook (redact_pre.py) adds ` || echo command-failed` to a Bash command so that a
  failed command reaches this hook. An explicit `exit N` in the command ends the shell before the suffix,
  so its output reaches the model through PostToolUseFailure, unredacted.
- With the rewrite, the model sees `command-failed`, not the exit code number, and a failed call no longer
  has the native error flag.
- Some commands (a heredoc, a last line that ends with `;`, `&`, a backslash, `|`, `||` or `&&`, a comment) are
  refused once by the rewrite hook and must be rephrased.
- A numeric-only secret under a matched key passes the value guard.
- For an event that cannot be read at all, the notice is in the Bash shape. For a Read or Grep call,
  Claude Code ignores a notice of the wrong shape and shows the original output.
- The Monitor pipe (redact_pre.py and redact_filter.py) covers only the last pipeline of the Monitor command:
  in `a; b` the output of `a` is not filtered, and in `a | b` the stderr of `a` is not redirected into the filter.
- Monitor commands are not checked by the audit gate or by block-aws-credentials.py, whose matchers do not
  include Monitor.
- In the Monitor filter, a PEM block with no END line and an unclosed JSON object or array under a matched key
  hide the rest of the stream (the fail-closed choice; they never leak it). When the PEM block began inside the
  object or array, the JSON state goes on after a PEM block's END line, so the lines of the object after it are
  not written.
- In the Monitor filter, a false positive of a state (for example `echo "see <key>: |"`) can hide following lines.
- In the Monitor filter, an empty matched key on the rest of a line after a dropped PEM or JSON state uses the
  column of the rest only, so it can hide more lines than the shared rules do.
- In the Monitor filter, a PEM block that began in a value other than an object or array under a matched key (a
  JSON string, an env value, a YAML plain value) is not tracked past its END line: a secret in the text after
  the END line can be written. A BEGIN line inside a YAML block scalar with an unindented PEM body leaks too.
  A next-line JSON string with a BEGIN line and no END line differs between the two seams (fail-closed).
- An unquoted YAML key counts only at a line start position or a flow-mapping position (spec 334). A secret
  after an unquoted YAML key in mid-line prose is not masked by the keyed rules (the shape rules still apply).
  A key after a tab after a tool prefix is prose. A grep path with a space is no grep prefix.
  The grep context lines (`path-N-`), `? ` complex keys and flow sequences are no line start.
  A word, a colon and a space before a key looks like a grep prefix, so a prose name after `Note: ` at the
  line start stays masked.
- MCP tools, WebFetch and subagent results are not redacted.

Test switch: when REDACT_SECRETS_TEST_SLEEP holds a number of seconds, the hook sleeps that long before it
redacts. A non-number fails closed with ValueError. Unset, it has no effect.
"""
import json
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import redact_rules  # noqa: E402

WATCHDOG_SECONDS = 5
NOTICE = "[output hidden: redaction hook failed: {}]"


class Timeout(Exception):
    pass


class MalformedEvent(Exception):
    pass


def on_alarm(signum, frame):
    raise Timeout()


def redact_value(value):
    if isinstance(value, str):
        return redact_rules.redact(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in value.items()}
    return value


def tool_shape(event):
    """Bash, Read or Grep: from tool_name when known, else from the keys of tool_response, else Bash."""
    if isinstance(event, dict):
        if event.get("tool_name") in ("Bash", "Read", "Grep"):
            return event["tool_name"]
        response = event.get("tool_response")
        if isinstance(response, dict):
            for key, shape in (("stdout", "Bash"), ("file", "Read"), ("mode", "Grep")):
                if key in response:
                    return shape
    return "Bash"


def notice_response(event, error_class):
    notice = NOTICE.format(error_class)
    shape = tool_shape(event)
    if shape == "Read":
        return {
            "type": "text",
            "file": {"filePath": "", "content": notice, "numLines": 1, "startLine": 1, "totalLines": 1},
        }
    if shape == "Grep":
        response = event.get("tool_response") if isinstance(event, dict) else None
        mode = response.get("mode") if isinstance(response, dict) else None
        if mode == "files_with_matches":
            return {"mode": mode, "filenames": [notice], "numFiles": 1, "totalFiles": 1}
        if mode == "count":
            return {"mode": mode, "numFiles": 0, "filenames": [], "content": notice, "numMatches": 0}
        return {"mode": "content", "numFiles": 0, "filenames": [], "content": notice, "numLines": 1, "totalLines": 1}
    return {"stdout": notice, "stderr": "", "interrupted": False, "isImage": False, "noOutputExpected": False}


def emit(updated_output):
    payload = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": updated_output}}
    sys.stdout.write(json.dumps(payload))
    sys.stdout.flush()


def run(state):
    """Return the redacted tool_response when a value changed, else None. Raise on any failure.

    The parsed event goes into state["event"], so the failure notice can pick the tool's shape.
    """
    text = sys.stdin.buffer.read().decode("utf-8")
    try:
        event = json.loads(text)
    except ValueError:
        raise MalformedEvent() from None
    if not isinstance(event, dict):
        raise MalformedEvent()
    state["event"] = event
    sleep = os.environ.get("REDACT_SECRETS_TEST_SLEEP")
    if sleep:
        seconds = float(sleep)
        if seconds > 0:
            time.sleep(seconds)
    response = event.get("tool_response")
    redacted = redact_value(response)
    return redacted if redacted != response else None


def main():
    state = {}
    signal.signal(signal.SIGALRM, on_alarm)
    signal.alarm(WATCHDOG_SECONDS)
    try:
        redacted = run(state)
        signal.alarm(0)
        if redacted is not None:
            emit(redacted)
    except Exception as error:  # fail closed on any error, the watchdog (Timeout) included
        signal.alarm(0)
        emit(notice_response(state.get("event"), type(error).__name__))
    return 0


if __name__ == "__main__":
    sys.exit(main())
