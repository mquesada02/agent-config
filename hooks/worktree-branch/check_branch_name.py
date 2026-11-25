#!/usr/bin/env python3
# PreToolUse guard (Bash): every session branch has a Conventional Branch name `<type>/<description>` (issue #573, CLAUDE.md section 10).
# Orca names a branch with its configured prefix unless `orca worktree create` gets `--branch`, and `orchestration worker-start --name`
# turns a slash into a hyphen, so a worker gets its worktree from `worktree create --branch` first and `worker-start --worktree path:<path>`.
# What is denied, for every session (a main session, a worker and a subagent):
#   - `orca worktree create` without `--branch`, or with a name that breaks the rule (BRANCH_NAME below);
#   - `orca orchestration worker-start` with `--worktree new-child` or `--worktree new-top-level`, or with a `--worktree` value that holds
#     one of `$`, a backtick, `*`, `?`, `[` or `{` (a variable, substitution, glob or brace expansion could build a new-worktree name);
#   - a word that holds `$` as the program word before `worktree create` or `orchestration worker-start` (`$X worktree create`): the
#     rule of that command applies to it. A backtick program word (`` `cmd` worktree create ``) is not covered.
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
# The shell rules: the text of an echo or printf that is piped to a shell, and of a here-string, is read as a command text.
ECHO_PRINTF = ("echo", "printf")
ECHO_OPTION = re.compile(r"-[neE]+")
TEXT_UNREADABLE = re.compile(r"[\\$`]")
FORMAT_UNREADABLE = re.compile(r"[%\\$`]")
# A `--worktree` value that a variable, a command substitution, a backtick form, a glob or a brace expansion builds (decision 708).
BUILT_VALUE = re.compile(r"[$`*?\[{]")
BUILT_NOTICE = "Write the literal value, for example `--worktree path:<that path>`; a built value is denied (CLAUDE.md section 10)."
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
        self.strict = 0  # above 0 while a text that is fed to a shell is read: a nested text that cannot be read is denied
        self.doubt = False  # set by a pipe from another producer into a shell; `command_reason` decides it at the end of its level
        self.create_head = audit._cli_head(self.is_program, CREATE_VALUE_OPTIONS, ["worktree", "create"])
        self.start_head = audit._cli_head(self.is_program, audit.ORCA_VALUE_OPTIONS, ["orchestration", "worker-start"])

    def is_orca(self, word):
        return self.audit._is_orca(word) or word in CLI_VARIABLES

    def is_program(self, word):
        """The program word of a create or worker-start command: an Orca word, or a word that a variable can fill (`$X worktree create`)."""
        return self.is_orca(word) or "$" in word

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

    def start_reason(self, words):
        """The reason for a worker-start command, from all its words (the option may sit before the subcommand words). A value that a
        variable, a substitution, a glob or a brace expansion builds could hold a new worktree name, so it is denied."""
        values = option_values(words, "--worktree", self.audit.ORCA_VALUE_OPTIONS)
        if any(value in NEW_WORKTREES for value in values):
            return f"worker-start with a new worktree gives a hyphen name. {START_NOTICE}"
        if any(BUILT_VALUE.search(value) for value in values):
            return f"worker-start with a --worktree value that holds one of $ ` * ? [ {{ could hold a new worktree. {BUILT_NOTICE}"
        return None

    def orca_reason(self, words):
        """The deny reason of a command that starts with the program word `words[0]`, or None."""
        if self.create_head(words) is not None:
            return self.create_command_reason(words)
        head = self.start_head(words)
        return None if head is None else self.start_reason(words)

    def create_command_reason(self, words):
        """The deny reason of a create command that starts with `words[0]`, or None when it is no create command."""
        head = self.create_head(words)
        return None if head is None else self.create_reason(words[len(head):])

    # The rules that the shared walk (hooks/bash-reader/bash_reader.py) asks of a hook.
    def first_word_reason(self, words):
        return None

    def segment_reason(self, words, items, position, depth):
        """The shell rules for a segment whose first word is a redirection word. The walk skips a segment whose first word has a naming-only
        base name (`>/tmp/echo bash <<<"..."`), so it would never give `word_reason` the shell word."""
        significant = self.audit._significant(words)
        if significant and significant[0][0] == 0:
            return None
        for index in range(len(words)):
            reason = self.shell_reason(words, index, items, position, depth)
            if reason:
                return reason
        return None

    def word_reason(self, words, index, items, position, depth):
        if self.is_orca(words[index]):
            return self.orca_reason(words[index:])
        if "$" in words[index]:
            reason = self.orca_reason(words[index:])
            if reason:
                return reason
        return self.shell_reason(words, index, items, position, depth)

    def depth_reason(self):
        return "shell commands are nested too deep to read"

    def unreadable_reason(self, command, depth, error):
        """A text that cannot be read is denied when it names a gated command, and always inside a text that is fed to a shell."""
        if self.strict:
            return f"a text that is fed to a shell cannot be read ({type(error).__name__})"
        if GATED_TEXT.search(command):
            return f"the command cannot be read ({type(error).__name__}) and names a gated Orca command"
        return None

    def substitution_bodies(self, word):
        return self.shared.substitution_bodies(self.audit, word)

    def command_reason(self, command, depth=0):
        """The deny reason for a command text, or None. A pipe from another producer into a shell is a doubt: it denies only when the raw text
        of this command level names a gated command. The flag is kept per level, so a nested text decides on its own raw text."""
        saved, self.doubt = self.doubt, False
        try:
            reason = self.walk.command_reason(command, depth)
            if reason is None and self.doubt and GATED_TEXT.search(command):
                reason = "a shell reads a pipe from a producer that the hook cannot read, and the command names a gated Orca command"
            return reason
        finally:
            self.doubt = saved

    # The shell rules: the text that a shell receives through a here-string or through an echo or printf pipe is read as a command text.
    def is_shell_word(self, word):
        return os.path.basename(word) in self.audit.SHELLS or len(self.shared.split_shell_word(self.audit, [word])) == 2

    def chain_words(self, items, position):
        """The words of the chain of the segment at `position` as (owner position, word), in item order."""
        return [(item, word) for item in self.shared.segment_chain(self.audit, items, position) for word in items[item]]

    def fed_reason(self, text, depth):
        """The reason of a text that is fed to a shell: it is read one level deeper, and a nested text that cannot be read is denied."""
        self.strict += 1
        try:
            return self.command_reason(text, depth + 1)
        finally:
            self.strict -= 1

    def shell_reason(self, words, index, items, position, depth):
        audit, shared = self.audit, self.shared
        if not self.is_shell_word(words[index]):
            return None
        raw = items[position]
        chain = self.chain_words(items, position)
        start = next(number for number, (item, _) in enumerate(chain) if item == position) + len(raw) - len(words) + index
        head, owners, shell = [], [], 0  # the words up to the shell word, the list item of each, and the place of the shell word
        for number, (item, word) in enumerate(chain[:start + 1]):
            parts = shared.split_shell_word(audit, [word])
            if number == start:
                shell = len(head)
            head.extend(parts)
            owners.extend([item] * len(parts))
        tail = [word for _, word in chain[start + 1:]]  # not split at a shell name: the text of a spaced here-string stays whole
        # A fused word after the shell word (`-s>&2`, `-s<<<text`) must not hide it. The words after the shell word are split in one pass,
        # with the rest of a fused shell word in front (`bash>&2`, `bash<<< "text"`): the text of a spaced here-string stays whole, and the
        # target of a redirection stays after its operator, where `_significant` drops it.
        arguments = shared.split_fused_redirection(head[shell:] + tail)[1:]
        flat = head[:shell + 1] + arguments
        if shared.has_command_option(audit, arguments):
            return None
        command = audit._significant(audit._command_words(head))
        if command:
            owner = owners[len(head) - len(audit._command_words(head)) + command[0][0]]
            if os.path.basename(command[0][1]) in audit.NAMING_ONLY_COMMANDS and owner == position:
                return None  # a shell name that is an argument of a naming-only command (`grep -q bash <<<"$list"`) is no shell
        clobbered = shared.split_fused_redirection(shared.clobber_words(audit, items, position))  # `bash >|file <<<text`: cut at the `|`
        for text in shared.here_string_texts(flat + clobbered):
            reason = self.fed_text_reason(text, depth)
            if reason:
                return reason
        if shared.reads_standard_input(audit, arguments):
            return self.pipe_reason(items, position, depth)
        return None

    def fed_text_reason(self, text, depth):
        if self.shared.EXPANSION.search(text):
            return "a here-string text that is fed to a shell cannot be read (it holds an expansion or a command substitution)"
        return self.fed_reason(text, depth)

    def pipe_reason(self, items, position, depth):
        piped, producer = self.shared.pipe_producer(self.audit, items, position)
        if not piped:
            return None
        command = self.audit._command_words(producer) if producer else []
        name = os.path.basename(command[0]) if command else None
        if name in ECHO_PRINTF:
            text, readable = self.echo_printf_text(name, command[1:])
            if not readable:
                return f"the {name} text that is piped to a shell cannot be read (an escape, an expansion or a command substitution)"
            return self.fed_reason(text, depth)
        self.doubt = True
        if self.earlier_unreadable_text(items, position):
            return "an echo or printf text before this pipe into a shell cannot be read, and the pipe producer is unknown"
        return None

    def earlier_unreadable_text(self, items, position):
        """True when a segment before the shell holds an echo or printf word whose text cannot be read (the second part of the rule for
        another producer: the producer lookup can name the wrong producer)."""
        first = self.shared.segment_chain(self.audit, items, position)[0]
        for index in range(first):
            if not isinstance(items[index], list):
                continue
            words = [word for _, word in self.chain_words(items, index)]
            for number, word in enumerate(words):
                name = os.path.basename(word)
                if name in ECHO_PRINTF and not self.echo_printf_text(name, words[number + 1:])[1]:
                    return True
        return False

    def echo_printf_text(self, name, arguments):
        """(text, readable) of an echo or printf command, from the words after its name. The text is not readable when it holds an escape, an
        expansion or a command substitution, or when an option changes it (echo -e) or where it goes (printf -v)."""
        words = [word for _, word in self.audit._significant(arguments)]
        if name == "echo":
            escapes = False
            while words and ECHO_OPTION.fullmatch(words[0]):
                escapes = escapes or "e" in words[0]
                words = words[1:]
            return " ".join(words), not escapes and not any(TEXT_UNREADABLE.search(word) for word in words)
        if not words:
            return "", True
        if words[0] == "--":
            words = words[1:]
        elif words[0].startswith("-"):
            return words[0], False
        text = words[0] if words else ""
        return text, not FORMAT_UNREADABLE.search(text)


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
