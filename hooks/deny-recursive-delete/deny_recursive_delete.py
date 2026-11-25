#!/usr/bin/env python3
# PreToolUse guard (Bash): no session runs a recursive delete. Added for issue #641: CLAUDE.md section 13 forbids it, and the audit check S9
# finds it in the transcripts, but only after it ran, so one slip fails the audit of that branch for good.
#
# Who is covered: every session (main sessions, Orca workers and subagents). A user's `!` command is not a hook call and stays free.
# What is denied: what S9 reports as a recursive delete, read by the same function (`recursive_delete_problems` of the audit script).
# `git rm -r` without `-f` and the cleanup command (a script, not a delete command in the call) pass.
# Fail open, on purpose: this hook runs on every Bash call, so a command that the reader cannot split, a missing file or a crash allows the
# call. S9 still reports "evidence unavailable" for a command that it cannot read.
import importlib.machinery
import importlib.util
import json
import os
import sys

HOOKS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT = os.path.join(HOOKS, "workflow-audit", "audit")
SHARED = os.path.join(HOOKS, "bash-reader", "bash_reader.py")
DENY_NOTICE = "recursive deletes are not allowed (CLAUDE.md section 13): move the folder to /tmp or use a new folder for the next probe"


def load_audit():
    """The audit script as a module, loaded through the shared reader module. No `.pyc` is written."""
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec = importlib.util.spec_from_file_location("bash_reader_for_deny_recursive_delete", SHARED)
        shared = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(shared)
        return shared.load_audit(AUDIT, "audit_for_deny_recursive_delete")
    finally:
        sys.dont_write_bytecode = previous


def main():
    try:
        data = json.load(sys.stdin)
        command = data["tool_input"]["command"]
        if data.get("tool_name", "Bash") != "Bash" or not isinstance(command, str):
            return 0
        problems = load_audit().recursive_delete_problems(command)
    except Exception:  # fail open: see the top of this file
        return 0
    if problems:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": f"Blocked by ~/.claude/hooks/deny-recursive-delete/deny_recursive_delete.py ({problems[0]}): {DENY_NOTICE}"}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
