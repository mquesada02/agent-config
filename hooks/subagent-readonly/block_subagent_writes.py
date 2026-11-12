#!/usr/bin/env python3
# PreToolUse guard (Bash): a subagent must not change remote state. Added for issue #71 after a review subagent ran
# `gh api -X PUT` from the runbook that it reviewed and created a GitHub environment that nobody approved.
# A prompt that says "read-only" is a request, not a block; this hook is the block.
#
# Who is covered: a call whose hook input carries `agent_id` (a subagent started with the Agent tool). A main session and an Orca
# worker (a full session) have no `agent_id`, so every command passes for them.
# What is denied: a deny-list of remote-write forms of `gh`, `git push`, `terraform` and `aws` (see the tables below). The command is read
# with the shared bash command reader of the workflow-audit gates, so a wrapped form (`bash -c`, `eval`, a pipeline, a `&&` chain, a
# substitution) counts. A command that the reader cannot split is denied (fail closed), as are a command or subcommand word that a variable or a
# substitution builds.
# KNOWN GAP (accepted by the owner): a write hidden in a script that the subagent runs (`bash push.sh`) is not caught here. Nor is a
# write made by a tool that is not on the deny-list (`kubectl`, `docker`, `python -c ...`). The `autoMode` rule in settings.json is the
# second layer for those.
import importlib.machinery
import importlib.util
import json
import os
import re
import sys

AUDIT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workflow-audit", "audit")
DENY_NOTICE = ("A subagent must not change remote state. Do not run this command. Report the need as a finding in your review "
               "instead; the owner runs it.")
UNRESOLVABLE_WORD = re.compile(r"[$`*?]")


def unresolved_reason(names, what):
    """The deny reason when a word is built by a variable, a substitution or a pattern (the hook cannot read what it names), else None."""
    if any(UNRESOLVABLE_WORD.search(name) for name in names):
        return f"a {what} that a variable, a substitution or a pattern builds"
    return None


# `gh <group> <verb>`: the verbs of each group that change something on GitHub.
GH_WRITE_VERBS = {
    "alias": {"set", "import", "delete"},  # a subagent never needs an alias; an alias can hide a write (`pr merge`)
    "pr": {"create", "new", "merge", "edit", "close", "comment", "review", "ready", "reopen", "lock", "unlock", "update-branch", "revert"},
    "issue": {"create", "edit", "close", "comment", "reopen", "delete", "lock", "unlock", "pin", "unpin", "transfer", "develop"},
    "repo": {"edit", "create", "delete", "fork", "rename", "archive", "unarchive", "sync", "set-default"},
    "release": {"create", "delete", "edit", "upload", "delete-asset"},
    "secret": {"set", "delete", "remove"},
    "variable": {"set", "delete"},
    "label": {"create", "edit", "delete", "clone"},
    "workflow": {"run", "enable", "disable"},
    "run": {"rerun", "cancel", "delete"},
    "gist": {"create", "edit", "delete", "rename"},
    "cache": {"delete"},
    "ssh-key": {"add", "delete"},
    "gpg-key": {"add", "delete"},
    "codespace": {"create", "delete", "edit", "stop", "rebuild"},
    "project": {"create", "edit", "delete", "close", "copy", "link", "unlink", "mark-template", "field-create", "field-delete",
                "item-add", "item-archive", "item-create", "item-delete", "item-edit"},
}
GH_VALUE_OPTIONS = frozenset(("-R", "--repo", "--hostname"))
# `terraform [-chdir=...] <subcommand>`
TERRAFORM_WRITE = {"apply", "destroy", "import", "force-unlock"}
TERRAFORM_STATE_WRITE = {"rm", "mv", "push"}
AWS_READ_VERB = re.compile(r"(?:get|list|describe|head)-.+")
AWS_VALUE_OPTIONS = frozenset(("--profile", "--region", "--output", "--endpoint-url", "--query", "--color", "--ca-bundle",
                               "--cli-read-timeout", "--cli-connect-timeout", "--cli-binary-format", "--cli-input-json",
                               "--cli-input-yaml"))


def load_reader():
    """The audit script as a module: it has no `.py` extension, and its `__main__` guard makes the load safe. No `.pyc` is written."""
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        loader = importlib.machinery.SourceFileLoader("audit_for_subagent_readonly", AUDIT)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = previous


def positional(words, value_options):
    """The words that are no option, and no value of a value option. `--` ends the options."""
    found, index, options = [], 0, True
    while index < len(words):
        word = words[index]
        if options and word == "--":
            options = False
        elif options and word.startswith("-") and len(word) > 1:
            if word in value_options:
                index += 1
        else:
            found.append(word)
        index += 1
    return found


def gh_reason(words):
    """The deny reason of the words after `gh`, or None."""
    names = positional(words, GH_VALUE_OPTIONS)[:2]
    reason = unresolved_reason(names, "gh subcommand")
    if reason:
        return reason
    if names[:1] == ["api"]:
        return gh_api_reason(words)
    if len(names) == 2 and names[1] in GH_WRITE_VERBS.get(names[0], ()):
        return f"gh {names[0]} {names[1]} changes GitHub"
    return None


def gh_api_reason(words):
    for index, word in enumerate(words):
        if word == "--":
            break
        if word in ("-X", "--method"):
            method = words[index + 1] if index + 1 < len(words) else ""
        elif word.startswith("--method="):
            method = word[len("--method="):]
        elif word.startswith("-X") and not word.startswith("--"):
            method = word[2:].removeprefix("=")
        else:
            method = None
        if method is not None and method.upper() != "GET":
            return f"gh api with the method {method!r} changes GitHub"
        if word == "--input" or word.startswith("--input="):
            return "gh api --input sends a request body (POST)"
        if (word in ("-f", "-F", "--field", "--raw-field") or word.startswith(("--field=", "--raw-field="))
                or (word.startswith(("-f", "-F")) and not word.startswith("--"))):
            return "gh api with field flags sends fields (POST by default)"
    return None


def terraform_reason(words):
    names = positional(words, ())[:2]
    reason = unresolved_reason(names, "terraform subcommand")
    if reason:
        return reason
    if names[:1] and names[0] in TERRAFORM_WRITE:
        return f"terraform {names[0]} changes remote state"
    if names[:1] == ["state"] and len(names) == 2 and names[1] in TERRAFORM_STATE_WRITE:
        return f"terraform state {names[1]} changes remote state"
    return None


def aws_reason(words):
    names = positional(words, AWS_VALUE_OPTIONS)[:2]
    reason = unresolved_reason(names, "aws operation")
    if reason:
        return reason
    if len(names) == 2 and not AWS_READ_VERB.fullmatch(names[1]):
        return f"aws {names[0]} {names[1]} is not a read operation (get-*, list-*, describe-*, head-*)"
    return None


class DenyRules:
    def __init__(self, audit):
        self.audit = audit

    def git_reason(self, words):
        rest = self.audit._git_command(words)
        if rest is None:
            return None
        first = self.audit._words(rest[:1])
        return unresolved_reason(first, "git subcommand") or ("git push changes the remote" if first == ["push"] else None)

    def segment_reason(self, segment, depth):
        words = self.audit._command_words(segment)
        if not words:
            return None
        first = os.path.basename(words[0])
        reason = unresolved_reason([first], "command word")
        if reason:
            return reason
        if first in self.audit.NAMING_ONLY_COMMANDS:
            return None
        for index, word in enumerate(words):
            name = os.path.basename(word)
            rest = words[index + 1:]
            reason = None
            if self.audit._is_gh(word):
                reason = gh_reason(rest)
            elif name == "terraform":
                reason = terraform_reason(rest)
            elif name == "aws":
                reason = aws_reason(rest)
            elif name == "git" or name in self.audit.DASHED_GIT:
                reason = self.git_reason(words[index:])
            elif name == "eval" and rest:
                reason = self.command_reason(" ".join(rest), depth + 1)
            elif name in self.audit.SHELLS:
                option = next((position for position, argument in enumerate(rest)
                               if self.audit.SHELL_COMMAND_OPTION.fullmatch(argument)), None)
                if option is not None and option + 1 < len(rest):
                    reason = self.command_reason(rest[option + 1], depth + 1)
            if reason:
                return reason
        return None

    def substitution_bodies(self, word):
        """The text of each `$(...)` and backtick substitution in a word. The splitter does not open one inside double quotes."""
        bodies = []
        for found in re.finditer(r"\$\(|`", word):
            if found.group() == "`":
                end = self.audit._backtick_end(word, found.end())
                bodies.append(word[found.end():end])
            else:
                end = self.audit._paren_end(word, found.end())
                bodies.append(word[found.end():end - 1])
        return bodies

    def command_reason(self, command, depth=0):
        """The deny reason for a command text, or None. Raises nothing: what cannot be read is denied."""
        if depth > self.audit.MAX_SHELL_DEPTH:
            return f"shell commands nested deeper than {self.audit.MAX_SHELL_DEPTH}"
        try:
            text = self.audit._join_as_bash(self.audit.strip_data_heredocs(command, self.audit.DATA_COMMANDS))
            items = self.audit.split_command(text)
            for segment in (item for item in items if isinstance(item, list)):
                reason = self.segment_reason(segment, depth)
                if reason:
                    return reason
                for word in segment:
                    for body in self.substitution_bodies(word):
                        reason = self.command_reason(body, depth + 1)
                        if reason:
                            return reason
        except Exception as error:  # a ValueError of the reader, a RecursionError, or any other failure
            return f"the command cannot be read ({type(error).__name__})"
        return None


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0  # no input to read: the hook cannot tell a subagent from a main session
    if not isinstance(data, dict) or not data.get("agent_id") or data.get("tool_name", "Bash") != "Bash":
        return 0
    tool_input = data.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    try:
        reason = (DenyRules(load_reader()).command_reason(command) if isinstance(command, str)
                  else "the hook input holds no command text")
    except Exception as error:
        reason = f"the hook failed ({type(error).__name__})"
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": f"Blocked by ~/.claude/hooks/subagent-readonly/block_subagent_writes.py: {reason}. {DENY_NOTICE}"}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
