#!/usr/bin/env python3
# PreToolUse guard (Bash): every session branch has a Conventional Branch name `<type>/<description>` (issue #573, CLAUDE.md section 10).
# Orca names a branch with its configured prefix unless `orca worktree create` gets `--branch`, and `orchestration worker-start --name`
# turns a slash into a hyphen, so a worker gets its worktree from `worktree create --branch` first and `worker-start --worktree path:<path>`.
# What is denied, for every session (a main session, a worker and a subagent):
#   - `orca worktree create` without `--branch`, or with a name that breaks the rule (BRANCH_NAME below);
#   - `orca orchestration worker-start` with `--worktree new-child` or `--worktree new-top-level`.
# Every Orca CLI form counts (`orca`, `orca-ide`, `orca-dev`, a full path, `$ORCA_CLI_COMMAND`). The command is read with the shared bash
# command reader of the workflow-audit gates, so a wrapped form (`bash -c`, `eval`, a pipeline, a `&&` chain, a substitution) counts.
# The walk over wrapped forms follows the one of hooks/subagent-readonly/block_subagent_writes.py, which has its own deny rules.
# A command that the reader cannot split is denied only when its raw text names one of the two gated commands.
import importlib.machinery
import importlib.util
import json
import os
import re
import sys

AUDIT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workflow-audit", "audit")
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
SUBSTITUTION_START = re.compile(r"\$\(|`")
GATED_TEXT =re.compile(r"worker-start|worktree\W+create")
CREATE_NOTICE = "Pass --branch <type>/<description> (type: feat, fix, chore, hotfix, release or research), as CLAUDE.md section 10 says."
START_NOTICE = ("worker-start cannot name a branch. Create the worktree with `orca worktree create --branch <type>/<description> "
                "--parent-worktree <your worktree>`, then use `worker-start --worktree path:<that path>` (CLAUDE.md section 10).")


def load_reader():
    """The audit script as a module: it has no `.py` extension, and its `__main__` guard makes the load safe. No `.pyc` is written."""
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        loader = importlib.machinery.SourceFileLoader("audit_for_worktree_branch", AUDIT)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = previous


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
        self.create_head = audit._cli_head(self.is_orca, CREATE_VALUE_OPTIONS, ["worktree", "create"])
        self.start_head = audit._cli_head(self.is_orca, audit.ORCA_VALUE_OPTIONS, ["orchestration", "worker-start"])

    def is_orca(self, word):
        return self.audit._is_orca(word) or word in CLI_VARIABLES

    def orca_reason(self, words):
        """The deny reason of a command that starts with the program word `words[0]`, or None."""
        head = self.create_head(words)
        if head is not None:
            arguments = words[len(head):]
            if self.audit._is_help(arguments):
                return None
            names = option_values(arguments, "--branch", CREATE_VALUE_OPTIONS)
            if not names:
                return f"orca worktree create has no --branch. {CREATE_NOTICE}"
            for name in names:
                if not BRANCH_NAME.fullmatch(name):
                    return f"the branch name {name!r} breaks the Conventional Branch rule. {CREATE_NOTICE}"
            return None
        head = self.start_head(words)
        if head is not None:
            values = option_values(words[len(head):], "--worktree", self.audit.ORCA_VALUE_OPTIONS)
            if any(value in NEW_WORKTREES for value in values):
                return f"worker-start with a new worktree gives a hyphen name. {START_NOTICE}"
        return None

    def segment_reason(self, segment, depth):
        words = self.audit._command_words(segment)
        if not words or os.path.basename(words[0]) in self.audit.NAMING_ONLY_COMMANDS:
            return None
        for index, word in enumerate(words):
            rest = words[index + 1:]
            reason = None
            if self.is_orca(word):
                reason = self.orca_reason(words[index:])
            elif os.path.basename(word) == "eval" and rest:
                reason = self.command_reason(" ".join(rest), depth + 1)
            elif os.path.basename(word) in self.audit.SHELLS:
                option = next((position for position, argument in enumerate(rest)
                               if self.audit.SHELL_COMMAND_OPTION.fullmatch(argument)), None)
                if option is not None and option + 1 < len(rest):
                    reason = self.command_reason(rest[option + 1], depth + 1)
            if reason:
                return reason
        return None

    def substitution_bodies(self, word):
        """The text of each `$(...)` and backtick substitution in a word. The splitter does not open one inside double quotes."""
        bodies, position = [], 0
        while (found := SUBSTITUTION_START.search(word, position)):
            if found.group() == "`":
                end = self.audit._backtick_end(word, found.end())
                bodies.append(word[found.end():end])
                position = end + 1
            else:
                end = self.audit._paren_end(word, found.end())
                bodies.append(word[found.end():end - 1])
                position = end
        return bodies

    def command_reason(self, command, depth=0):
        """The deny reason for a command text, or None. A text that cannot be read is denied when it names a gated command."""
        if depth > self.audit.MAX_SHELL_DEPTH:
            return "shell commands are nested too deep to read"
        try:
            text = self.audit._join_as_bash(self.audit.strip_data_heredocs(command, self.audit.DATA_COMMANDS))
            for segment in (item for item in self.audit.split_command(text) if isinstance(item, list)):
                reason = self.segment_reason(segment, depth)
                for word in segment:
                    for body in ([] if reason else self.substitution_bodies(word)):
                        reason = reason or self.command_reason(body, depth + 1)
                if reason:
                    return reason
            return None
        except Exception as error:  # a ValueError of the reader, a RecursionError, or any other failure
            if GATED_TEXT.search(command):
                return f"the command cannot be read ({type(error).__name__}) and names a gated Orca command"
            return None


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
