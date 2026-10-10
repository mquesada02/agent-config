#!/usr/bin/env python3
# PreToolUse guard: blocks agent tool calls that could print long-term AWS credentials into a transcript or a message.
# Added 2026-10-10 after two credential leaks from agent sessions. The owner's own `!` commands are not tool calls and
# are not affected. Exit 2 blocks the call and shows the reason to the agent.
import json
import re
import sys

BASH_PATTERNS = [
    (r"export-credentials", "aws configure export-credentials prints the secret key"),
    (r"get-session-token", "aws sts get-session-token prints secret keys"),
    (r"configure\s+get\s+\S*(aws_secret_access_key|aws_access_key_id|aws_session_token)", "aws configure get prints a credential"),
    (r"\.aws/credentials", "~/.aws/credentials holds long-term keys"),
    (r"\$\{?AWS_(SECRET_ACCESS_KEY|SESSION_TOKEN)\b", "the command expands a secret AWS variable"),
    (r"\b(printenv|env|export\s+-p|set)\b[^|;&]*\|\s*grep[^|;&]*AWS", "the command prints AWS environment variables"),
]


def block(reason: str) -> None:
    print(
        f"Blocked by ~/.claude/hooks/block-aws-credentials.py: {reason}. "
        "Never read or print AWS credentials from an agent. Write scripts with the Write tool, keep message text in "
        "single quotes or a file, and let the owner run credential steps in their own terminal.",
        file=sys.stderr,
    )
    sys.exit(2)


def main() -> None:
    data = json.load(sys.stdin)
    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}
    if tool == "Bash":
        command = tool_input.get("command") or ""
        for pattern, reason in BASH_PATTERNS:
            if re.search(pattern, command):
                block(reason)
    elif tool in ("Read", "Grep", "Glob"):
        target = " ".join(str(tool_input.get(k) or "") for k in ("file_path", "path", "pattern", "glob"))
        if re.search(r"\.aws/credentials", target):
            block("~/.aws/credentials holds long-term keys")
    sys.exit(0)


if __name__ == "__main__":
    main()
