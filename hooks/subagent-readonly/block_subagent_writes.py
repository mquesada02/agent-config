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
# Also denied (issue #738): a local git command that changes HEAD, the index or the working tree (`checkout`, `reset`, `commit`, ...; see
# GIT_LOCAL_WRITE and `local_git_write`), unless every directory that it acts on (the session directory, moved by `cd` and `-C`, and the
# `--git-dir` and `--work-tree` paths) is under /tmp or the temp folder, where a verifier builds a probe repository. A directory that cannot
# be resolved is denied.
# KNOWN GAP (accepted by the owner): a write hidden in a script that the subagent runs (`bash push.sh`) is not caught here. Nor is a
# write made by a tool that is not on the deny-list (`kubectl`, `docker`, `python -c ...`). The `autoMode` rule in settings.json is the
# second layer for those.
import importlib.util
import json
import os
import re
import sys
import tempfile

HOOKS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT = os.path.join(HOOKS, "workflow-audit", "audit")
SHARED = os.path.join(HOOKS, "bash-reader", "bash_reader.py")
DENY_NOTICE = ("A subagent must not change remote state or a shared worktree. Do not run this command. Report the need as a finding in "
               "your review instead; the owner runs it. To read a file at a ref, use `git show <ref>:<path>`.")
UNRESOLVABLE_WORD = re.compile(r"[$`*?]")


class UnnamedReason(str):
    """A deny reason that names no gated command: a word that cannot be resolved, a text that cannot be read, a nesting that is too deep.
    The type is the flag, so that no decision reads the reason text. Any new reason that names no gated command must be built with this
    type, and the flag is kept only while the same object is passed on: a string operation on it (`f"{reason}..."`) returns a plain `str`."""


def unresolved_reason(names, what):
    """The deny reason when a word is built by a variable, a substitution or a pattern (the hook cannot read what it names), else None."""
    if any(UNRESOLVABLE_WORD.search(name) for name in names):
        return UnnamedReason(f"a {what} that a variable, a substitution or a pattern builds")
    return None


def names_gated_command(reason):
    """Whether a deny reason names a gated command (`gh pr merge changes GitHub`), and not a word or a text that the hook cannot read."""
    return not isinstance(reason, UnnamedReason)


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
# `git <subcommand>`: the subcommands that change HEAD, the index or the working tree of the repository that they run in (issue #738).
# `stash`, `apply`, `symbolic-ref`, `bisect`, `sparse-checkout`, `worktree`, `branch` and `tag` have read forms, so `local_git_write` reads their arguments.
GIT_LOCAL_WRITE = frozenset(("checkout", "switch", "reset", "clean", "restore", "commit", "merge", "rebase", "cherry-pick", "revert", "am",
                             "pull", "add", "rm", "mv", "update-ref", "update-index", "read-tree", "checkout-index"))
GIT_PATH_OPTIONS = ("--git-dir", "--work-tree")
GIT_BRANCH_WRITE_LONG = frozenset(("--delete", "--move", "--force"))
GIT_BRANCH_WRITE_SHORT = frozenset("dDmMf")
GIT_TAG_VALUE_OPTIONS = frozenset(("-m", "-F", "-u", "--message", "--file", "--local-user", "--cleanup", "--sort", "--format",
                                   "--points-at", "--contains", "--no-contains", "--merged", "--no-merged"))
GIT_TAG_LIST_OPTIONS = frozenset(("-l", "--list", "--contains", "--no-contains", "--points-at", "--merged", "--no-merged"))
# A local git write is allowed only in a repository under one of these folders (a probe repository of a verifier).
TEMP_ROOTS = tuple({os.path.realpath("/tmp"), os.path.realpath(tempfile.gettempdir())})
# `terraform [-chdir=...] <subcommand>`
TERRAFORM_WRITE = {"apply", "destroy", "import", "force-unlock"}
TERRAFORM_STATE_WRITE = {"rm", "mv", "push"}
AWS_READ_VERB = re.compile(r"(?:get|list|describe|head)-.+")
AWS_VALUE_OPTIONS = frozenset(("--profile", "--region", "--output", "--endpoint-url", "--query", "--color", "--ca-bundle",
                               "--cli-read-timeout", "--cli-connect-timeout", "--cli-binary-format", "--cli-input-json",
                               "--cli-input-yaml"))


def load_shared():
    """The shared reader module, loaded by its file path (the hook runs with `python3 -I`). No `.pyc` is written. It keeps no state."""
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec = importlib.util.spec_from_file_location("bash_reader_for_subagent_readonly", SHARED)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = previous


def load_reader():
    """The audit script as a module, loaded by the shared reader module."""
    return load_shared().load_audit(AUDIT, "audit_for_subagent_readonly")


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


def local_git_write(args):
    """The subcommand name of a git command that changes HEAD, the index or the working tree, else None. `args` start at the subcommand."""
    name, rest = args[0], args[1:]
    if name in GIT_LOCAL_WRITE:
        return name
    names = positional(rest, ())
    if name == "stash" and (not names or names[0] not in ("list", "show")):
        return name
    if name == "symbolic-ref" and (len(names) > 1 or {"-d", "--delete"} & set(rest)):  # `git symbolic-ref HEAD` only reads
        return name
    if (name == "bisect" and names[:1] != ["log"] and names[:1] != ["visualize"] and names[:1] != ["view"]) or (
            name == "sparse-checkout" and names[:1] != ["list"]):  # the other forms move HEAD or rewrite the working tree
        return name
    if name == "apply" and not {"--check", "--stat"} & set(rest):
        return name
    if name == "worktree" and names[:1] and names[0] in ("add", "remove"):
        return f"{name} {names[0]}"
    if name == "branch" and any(word in GIT_BRANCH_WRITE_LONG or (word.startswith("-") and not word.startswith("--")
                                                                  and GIT_BRANCH_WRITE_SHORT & set(word[1:])) for word in rest):
        return name
    if name == "tag" and positional(rest, GIT_TAG_VALUE_OPTIONS) and not any(word.split("=")[0] in GIT_TAG_LIST_OPTIONS for word in rest):
        return name
    return None


def resolve_directory(base, path):
    """The real path of `path` from the directory `base`, or None when `base` is unknown or a variable, a substitution or a pattern builds `path`."""
    if base is None or path is None or path == "-" or UNRESOLVABLE_WORD.search(path):
        return None
    return os.path.realpath(os.path.join(base, os.path.expanduser(path)))


def under_temp(directory):
    return any(directory == root or directory.startswith(root + os.sep) for root in TEMP_ROOTS)


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
    def __init__(self, audit, base=None):
        self.audit = audit
        self.walk = load_shared().Walk(audit, self)
        self.base = os.path.realpath(base or os.getcwd())  # the directory of the session when the command starts
        self.texts = {}  # nesting depth -> (the split items of the text being read, the directory where that text starts)
        self.directories = {}  # nesting depth -> the directory of the segment being read (None: a `cd` that cannot be resolved)

    def git_reason(self, words, depth):
        rest = self.audit._git_command(words)
        if rest is None:
            return None
        args = self.audit._words(rest)
        if not args:
            return None
        reason = unresolved_reason(args[:1], "git subcommand")
        if reason:
            return reason
        if args[0] == "push":
            return "git push changes the remote"
        written = local_git_write(args)
        if written is None:
            return None
        targets = self.git_targets(words, self.directories.get(depth))
        if targets is None:
            return f"git {written} acts on a directory that cannot be resolved"
        if all(under_temp(target) for target in targets):
            return None
        return f"git {written} changes a shared worktree"

    def git_targets(self, words, directory):
        """The directories that a git command acts on (the current one, moved by each `-C`, and the `--git-dir` and `--work-tree` paths),
        or None when one cannot be resolved. A dashed program (`git-branch`) has no global options."""
        paths, index = [], 1
        while os.path.basename(words[0]) == "git" and index < len(words) and words[index].startswith("-"):
            word = words[index]
            name, equals, value = word.partition("=")
            if word == "-C" or name in GIT_PATH_OPTIONS:
                if not equals:
                    index += 1
                    value = words[index] if index < len(words) else None  # a missing value cannot be resolved
                path = resolve_directory(directory, value)
                if word == "-C":
                    directory = path
                else:
                    paths.append(path)
            elif word in self.audit.GIT_VALUE_OPTIONS:
                index += 1
            index += 1
        targets = [directory, *paths]
        return None if None in targets else targets

    def segment_reason(self, words, items, position, depth):
        """No reason of its own: it records the directory of a segment, which is where its text starts, moved by each `cd` of the segments
        before it in the same text. A text that a segment nests (`bash -c`, `eval`, a substitution) starts where that segment is."""
        entry = self.texts.get(depth)
        if entry is None or entry[0] is not items:
            entry = self.texts[depth] = (items, self.directories.get(depth - 1, self.base) if depth else self.base)
        directory = entry[1]
        for item in items[:position]:
            words = self.audit._command_words(item) if isinstance(item, list) else []
            if words and os.path.basename(words[0]) in ("cd", "pushd"):
                names = positional(words[1:], ())
                directory = resolve_directory(directory, names[0] if names else "~")
        self.directories[depth] = directory

    # The rules that the shared walk (hooks/bash-reader/bash_reader.py) asks of a hook.
    def first_word_reason(self, words):
        return unresolved_reason([os.path.basename(words[0])], "command word")

    def word_reason(self, words, index, items, position, depth):
        name = os.path.basename(words[index])
        rest = words[index + 1:]
        if self.audit._is_gh(words[index]):
            return gh_reason(rest)
        if name == "terraform":
            return terraform_reason(rest)
        if name == "aws":
            return aws_reason(rest)
        if name == "git" or name in self.audit.DASHED_GIT:
            return self.git_reason(words[index:], depth)
        return None

    def depth_reason(self):
        return UnnamedReason(f"shell commands nested deeper than {self.audit.MAX_SHELL_DEPTH}")

    def unreadable_reason(self, command, depth, error):
        return self.backtick_reason(command, depth) or UnnamedReason(f"the command cannot be read ({type(error).__name__})")

    def substitution_bodies(self, word):
        """The text of each `$(...)` and backtick substitution in a word. The splitter does not open one inside double quotes.
        This is the legacy reader of this hook, and it differs from the shared reader on purpose (the move into the shared module changed
        no behavior of this hook): it raises on every backtick form, and it rescans inside a body, so it raises on a dollar-paren text that
        holds a quoted dollar-paren and visits a nested body twice."""
        bodies = []
        for found in re.finditer(r"\$\(|`", word):
            if found.group() == "`":
                end = self.audit._backtick_end(word, found.end())
                bodies.append(word[found.end():end])
            else:
                end = self.audit._paren_end(word, found.end())
                bodies.append(word[found.end():end - 1])
        return bodies

    def read_reason(self, command, depth):
        """The deny reason for a command text, or None. Raises when the text cannot be read."""
        return self.walk.read_reason(command, depth)

    def backtick_reason(self, command, depth):
        """The deny reason of a gated command that a backtick form of `command` holds, naming that command, or None. It is for a text that
        `read_reason` cannot read (`substitution_bodies` raises on every backtick form): the decision is a deny either way, and this only
        names the gated command, so that the reason is not a bare "cannot be read". A body that cannot be read itself is searched in turn."""
        if depth > self.audit.MAX_SHELL_DEPTH:
            return None
        start = command.find("`")
        while start >= 0:  # each backtick form wherever it is, a quoted one too: it is denied either way
            try:
                end = self.audit._backtick_end(command, start + 1)
            except ValueError:  # not closed: the body runs to the end of the text
                end = len(command)
            body = re.sub(r"\\([`\\$])", r"\1", command[start + 1:end])  # bash unescapes a backtick body, as `_mask_substitutions` does
            try:
                reason = self.read_reason(body, depth + 1)
            except Exception:
                reason = self.backtick_reason(body, depth + 1)
            if reason and names_gated_command(reason):
                return f"{reason}, inside a backtick form"
            start = command.find("`", end + 1)
        return None

    def command_reason(self, command, depth=0):
        """The deny reason for a command text, or None. Raises nothing: what cannot be read is denied."""
        return self.walk.command_reason(command, depth)


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
        cwd = data.get("cwd")
        reason = (DenyRules(load_reader(), cwd if isinstance(cwd, str) else None).command_reason(command) if isinstance(command, str)
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
