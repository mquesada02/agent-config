#!/usr/bin/env python3
# PreToolUse guard (Bash): every session branch has a Conventional Branch name `<type>/<description>` (issue #573, CLAUDE.md section 10).
# Orca names a branch with its configured prefix unless `orca worktree create` gets `--branch`, and `orchestration worker-start --name`
# turns a slash into a hyphen, so a worker gets its worktree from `worktree create --branch` first and `worker-start --worktree path:<path>`.
# What is denied, for every session (a main session, a worker and a subagent):
#   - `orca worktree create` without `--branch`, or with a name that breaks the rule (BRANCH_NAME below);
#   - `orca orchestration worker-start` with `--worktree new-child` or `--worktree new-top-level`.
# Every Orca CLI form counts (`orca`, `orca-ide`, `orca-dev`, a full path, `$ORCA_CLI_COMMAND`). The command is read with the shared bash
# command reader of the workflow-audit gates, so a wrapped form (`bash -c`, `eval`, a pipeline, a `&&` chain, a substitution) counts.
# The walk over wrapped forms is the one of hooks/bash-reader/bash_reader.py, which hooks/subagent-readonly/block_subagent_writes.py shares
# and which has its own deny rules. A failure to load that module is a failure of the hook (see `main`).
# A command that the reader cannot split is denied only when its raw text names one of the two gated commands.
import importlib.util
import json
import os
import re
import sys

HOOKS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT = os.path.join(HOOKS, "workflow-audit", "audit")
SHARED = os.path.join(HOOKS, "bash-reader", "bash_reader.py")
# Conventional Branch 1.1.0 (https://conventionalbranch.org/#specification) with the purpose types, plus the team type `research`:
# one `/`; lowercase letters, digits and hyphens; a dot only between two letters or digits; no leading, trailing or consecutive
# hyphen or dot. It is matched with fullmatch, so that a trailing newline is no name character.
BRANCH_NAME = re.compile(r"(?:feat|feature|fix|bugfix|hotfix|release|chore|research)/[a-z0-9]+(?:[-.][a-z0-9]+)*")
# The value options of `orca worktree create` (from `orca worktree create --help`) and the global ones.
CREATE_VALUE_OPTIONS = frozenset(f"--{name}" for name in (
    "environment", "pairing-code", "repo", "project", "host", "project-host-setup", "name", "agent", "prompt", "model", "effort", "surface",
    "retry-launch", "base-branch", "branch", "reference", "reference-site", "issue", "pr", "linear-issue", "gitlab-issue", "gitlab-mr",
    "comment", "setup", "parent-worktree", "parent-environment"))
NEW_WORKTREES = ("new-child", "new-top-level")
CLI_VARIABLES = ("$ORCA_CLI_COMMAND", "${ORCA_CLI_COMMAND}")
GATED_TEXT = re.compile(r"worker-start|worktree\W+create")
CREATE_NOTICE = "Pass --branch <type>/<description> (type: feat, fix, chore, hotfix, release or research), as CLAUDE.md section 10 says."
START_NOTICE = ("worker-start cannot name a branch. Create the worktree with `orca worktree create --branch <type>/<description> "
                "--parent-worktree <your worktree>`, then use `worker-start --worktree path:<that path>` (CLAUDE.md section 10).")


def load_shared():
    """The shared reader module, loaded by its file path (the hook runs with `python3 -I`). No `.pyc` is written. It keeps no state."""
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec = importlib.util.spec_from_file_location("bash_reader_for_worktree_branch", SHARED)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = previous


def load_reader():
    """The audit script as a module, loaded by the shared reader module."""
    return load_shared().load_audit(AUDIT, "audit_for_worktree_branch")


def option_values(arguments, name, value_options):
    """The values of the option `name` in the arguments (`--name value` and `--name=value`). A value option takes the next word, so a
    word that is the value of another option is no option. `--` ends the options."""
    values, index = [], 0
    while index < len(arguments):
        word = arguments[index]
        if word == "--":
            break
        if word == name:
            values.append(arguments[index + 1] if index + 1 < len(arguments) else "")
            index += 2
        elif word.startswith(f"{name}="):
            values.append(word[len(name) + 1:])
            index += 1
        else:
            index += 2 if word in value_options else 1
    return values


class BranchRules:
    def __init__(self, audit):
        self.audit = audit
        self.shared = load_shared()
        self.walk = self.shared.Walk(audit, self)
        self.create_head = audit._cli_head(self.is_orca, CREATE_VALUE_OPTIONS, ["worktree", "create"])
        self.start_head = audit._cli_head(self.is_orca, audit.ORCA_VALUE_OPTIONS, ["orchestration", "worker-start"])

    def is_orca(self, word):
        return self.audit._is_orca(word) or word in CLI_VARIABLES

    def create_reason(self, arguments):
        if self.audit._is_help(arguments):
            return None
        names = option_values(arguments, "--branch", CREATE_VALUE_OPTIONS)
        if not names:
            return f"orca worktree create has no --branch. {CREATE_NOTICE}"
        for name in names:
            if not BRANCH_NAME.fullmatch(name):
                return f"the branch name {name!r} breaks the Conventional Branch rule. {CREATE_NOTICE}"
        return None

    def start_reason(self, arguments):
        values = option_values(arguments, "--worktree", self.audit.ORCA_VALUE_OPTIONS)
        if any(value in NEW_WORKTREES for value in values):
            return f"worker-start with a new worktree gives a hyphen name. {START_NOTICE}"
        return None

    def orca_reason(self, words):
        """The deny reason of a command that starts with the program word `words[0]`, or None."""
        head = self.create_head(words)
        if head is not None:
            return self.create_reason(words[len(head):])
        head = self.start_head(words)
        return None if head is None else self.start_reason(words[len(head):])

    # The rules that the shared walk (hooks/bash-reader/bash_reader.py) asks of a hook.
    def first_word_reason(self, words):
        return None

    def word_reason(self, words, index, items, position, depth):
        return self.orca_reason(words[index:]) if self.is_orca(words[index]) else None

    def depth_reason(self):
        return "shell commands are nested too deep to read"

    def unreadable_reason(self, command, depth, error):
        """A text that cannot be read is denied when it names a gated command."""
        if GATED_TEXT.search(command):
            return f"the command cannot be read ({type(error).__name__}) and names a gated Orca command"
        return None

    def substitution_bodies(self, word):
        return self.shared.substitution_bodies(self.audit, word)

    def command_reason(self, command, depth=0):
        """The deny reason for a command text, or None."""
        return self.walk.command_reason(command, depth)


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(data, dict) or data.get("tool_name", "Bash") != "Bash":
        return 0
    tool_input = data.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return 0
    try:
        reason = BranchRules(load_reader()).command_reason(command)
    except Exception as error:
        reason = f"the hook failed ({type(error).__name__})" if GATED_TEXT.search(command) else None
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": f"Blocked by ~/.claude/hooks/worktree-branch/check_branch_name.py: {reason}"}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
