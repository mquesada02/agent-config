"""PreToolUse rewrite hook: make a failed Bash command reach the PostToolUse redaction hook, and filter Monitor.

A Bash command that exits non-zero goes to PostToolUseFailure, where the output is not redacted. This hook
appends ` || echo command-failed` to the command, so the call always exits 0. The suffix holds no quotes, no
`$`, no `{ }` group and no glob character, because Claude Code checks the permission rules against the
rewritten command. The hook strips trailing whitespace first, so the suffix lands on the last non-empty line.
It denies a command whose last line is not safe to append to (a heredoc anywhere, a last line that ends with
`;`, `&`, `\\`, `|`, `||` or `&&`, or a comment), with a reason that names the cause. A comment is a `#` that
starts a word outside every quote: the check scans the whole command and ignores a `#` inside quotes. When it
cannot be sure (a quote still open at the end, a `$(`, `${` or backtick), it denies on the plain `#` pattern.
It returns `updatedInput`
with every other input field unchanged and never sets `permissionDecision: "allow"`, so permission prompts
and rules still apply. A command that already ends with the suffix (the model resent a rewritten call) passes
unchanged, so the suffix never stacks. An empty command, a call with no string command and a tool other than
Bash and Monitor pass unchanged. A Bash call with `run_in_background: true` passes unchanged too: its tool result
holds no command output, and its task notification must keep the real exit code (#295).

For a Monitor call it appends ` 2>&1 | python3 -I -u ~/.claude/hooks/redact-secrets/redact_filter.py` instead
(the line filter redact_filter.py redacts each line of the watched output), after the same trailing-whitespace
strip and the same unsafe-last-line check, and with every other input field unchanged. The pipe covers only
the last pipeline of the Monitor command.

The hook is registered with `"onFailure": "block"`, so a failure of the hook (an unreadable event, an error)
blocks the tool call.

Test switch: when REDACT_SECRETS_TEST_SLEEP is exactly `fail`, the hook exits 1. Any other value has no
effect (the PostToolUse hook alone reads a number from this variable).
"""
import json
import os
import re
import sys

SUFFIXES = {
    "Bash": " || echo command-failed",
    "Monitor": " 2>&1 | python3 -I -u ~/.claude/hooks/redact-secrets/redact_filter.py",
}
REASON_PREFIX = "redact_pre.py: "
# `<<` with no `<` directly before or after it: a heredoc. A here-string (`<<<`) is safe.
HEREDOC = re.compile(r"(?<!<)<<(?!<)")
# Longest first, so `&&` is named before `&` and `||` before `|`.
ENDINGS = ("&&", "||", ";", "&", "\\", "|")
COMMENT = re.compile(r"^\s*#|\s#")
# A `#` starts a comment only at the start of a word: after the line start, whitespace or a shell operator.
WORD_START_BEFORE = " \t\r\n;&|()<>"
TRAILING = " \t\r\n"

ADVICE = {
    "heredoc": "write the text to a file with the Write tool and read the file instead",
    "ending": "remove the trailing operator or put a command after it",
    "comment": "remove the comment or move it to its own earlier line",
}


def last_line_has_comment(command):
    """True when the last line of the command holds a real shell comment.

    It scans the whole command, because a quote can open on an earlier line. It tracks single quotes, double
    quotes, `$'...'` strings and backslash escapes. A `#` is a comment only at the start of a word outside every
    quote. It fails closed: when it cannot be sure (a quote still open at the end, or a command substitution
    `$(`, a backtick or a `${` anywhere outside single quotes), the result of the plain COMMENT pattern stands.
    """
    last_line_start = command.rfind("\n") + 1
    fallback = COMMENT.search(command[last_line_start:]) is not None
    state = None  # None (unquoted), "'", '"' or "$'"
    escaped = -1
    i = 0
    while i < len(command):
        char = command[i]
        if state == "'":
            if char == "'":
                state = None
        elif char == "\\":
            i += 1
            if state is None:
                # the escaped character is part of a word, so it does not end one (a line continuation does)
                escaped = i if command[i:i + 1] != "\n" else -1
        elif state == "$'":
            if char == "'":
                state = None
        elif char == "`" or command.startswith(("$(", "${"), i):
            return fallback
        elif state == '"':
            if char == '"':
                state = None
        elif char == "'":
            state = "'"
        elif char == '"':
            state = '"'
        elif command.startswith("$'", i):
            state = "$'"
            i += 1
        elif char == "#" and (i == 0 or (command[i - 1] in WORD_START_BEFORE and escaped != i - 1)):
            if i >= last_line_start:
                return True
            # a comment on an earlier line: its quotes are not quotes, so skip to the end of that line
            i = command.index("\n", i)
            continue
        i += 1
    if state is not None:
        return fallback
    return False


def unsafe_cause(command):
    """(cause phrase, advice) when the last line of the command is not safe to append to, else None."""
    if HEREDOC.search(command):
        return "heredoc", ADVICE["heredoc"]
    last_line = command.rsplit("\n", 1)[-1]
    for ending in ENDINGS:
        if last_line.endswith(ending):
            return "last line ends with `%s`" % ending, ADVICE["ending"]
    if last_line_has_comment(command):
        return "comment on the last line", ADVICE["comment"]
    return None


def deny(cause, advice):
    reason = "%s%s. Rephrase the command without it: %s, then retry." % (REASON_PREFIX, cause, advice)
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def decide(event):
    """The hook output for one event, or None when the call passes unchanged."""
    tool_name = event.get("tool_name")
    # a tool_name that is not a string (unhashable) must pass unchanged, not raise in the dict lookup
    suffix = SUFFIXES.get(tool_name) if isinstance(tool_name, str) else None
    if suffix is None:
        return None
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict) or not isinstance(tool_input.get("command"), str):
        return None
    if tool_name == "Bash" and tool_input.get("run_in_background") is True:
        return None
    command = tool_input["command"].rstrip(TRAILING)
    if command == "":
        return None
    if command.endswith(suffix):
        return None  # a resent, already rewritten command: appending again would stack the suffix
    unsafe = unsafe_cause(command)
    if unsafe is not None:
        return deny(*unsafe)
    updated = dict(tool_input)
    updated["command"] = command + suffix
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": updated}}


def main():
    if os.environ.get("REDACT_SECRETS_TEST_SLEEP") == "fail":
        sys.exit(1)
    event = json.load(sys.stdin)
    if not isinstance(event, dict):
        sys.exit(1)
    output = decide(event)
    if output is not None:
        print(json.dumps(output))


if __name__ == "__main__":
    main()
