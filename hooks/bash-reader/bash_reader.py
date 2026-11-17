# The bash command reader that the Bash PreToolUse hooks share (hooks/worktree-branch/check_branch_name.py and
# hooks/subagent-readonly/block_subagent_writes.py). Each hook loads this file by its path (`spec_from_file_location`), because a hook runs
# with `python3 -I`, which gives no import path to a sibling folder. A hook loads it with its `load_shared`, which its `load_reader` and its
# rules class call. Both run inside the `try` of the hook `main`, so a load failure is a deny of that hook and never a crash.
# It holds: the loader of the workflow-audit script as a module, the reader of `$(...)` and backtick substitution bodies, and the walk over a
# command text (the nesting depth guard, the data heredoc strip, the join and the split, and the `eval` and shell `-c` extraction).
# It holds no deny rule. Each hook gives the walk its rules (see `Walk`).
import importlib.machinery
import importlib.util
import os
import re
import sys

SUBSTITUTION_START = re.compile(r"\$\(|`")


def load_audit(path, module_name):
    """The audit script as a module: it has no `.py` extension, and its `__main__` guard makes the load safe. No `.pyc` is written.
    Each hook gives its own `module_name`."""
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        loader = importlib.machinery.SourceFileLoader(module_name, path)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = previous


def substitution_bodies(audit, word):
    """The text of each `$(...)` and backtick substitution in a word. The splitter does not open one inside double quotes. Raises
    ValueError when a form is not closed."""
    bodies, position = [], 0
    while (found := SUBSTITUTION_START.search(word, position)):
        if found.group() == "`":
            end = audit._backtick_end(word, found.end())
            bodies.append(word[found.end():end])
            position = end + 1
        else:
            end = audit._paren_end(word, found.end())
            bodies.append(word[found.end():end - 1])
            position = end
    return bodies


def command_script(audit, arguments):
    """The command text that a shell runs, when the words after the shell name hold a `-c` option and a word after it, else None."""
    option = next((position for position, argument in enumerate(arguments) if audit.SHELL_COMMAND_OPTION.fullmatch(argument)), None)
    if option is not None and option + 1 < len(arguments):
        return arguments[option + 1]
    return None


class Walk:
    """The walk over a command text. `rules` is the object of a hook. It must have these methods:
      command_reason(command, depth)        the public reason of the hook for a command text (the walk calls it for each nested text)
      depth_reason()                        the reason when the nesting is deeper than `MAX_SHELL_DEPTH` (the hook picks text and type)
      unreadable_reason(command, depth, error)  the reason when a text cannot be read (the hook's own failure rule)
      substitution_bodies(word)             the reader of substitution bodies (a hook can replace the accurate one of this module)
      first_word_reason(words)              a reason from the first word of a segment, or None (runs before the naming-only skip)
      word_reason(words, index, items, position, depth)
                                            the gated head of the hook at a word position, or None. `items` are the split items of the text
                                            and `position` is the place of the segment in them, so that a rule can see the separator and
                                            the segment before it."""

    def __init__(self, audit, rules):
        self.audit = audit
        self.rules = rules

    def segment_reason(self, items, position, depth):
        audit, rules = self.audit, self.rules
        words = audit._command_words(items[position])
        if not words:
            return None
        reason = rules.first_word_reason(words)
        if reason:
            return reason
        if os.path.basename(words[0]) in audit.NAMING_ONLY_COMMANDS:
            return None
        for index, word in enumerate(words):
            reason = rules.word_reason(words, index, items, position, depth)
            if not reason:
                name, rest = os.path.basename(word), words[index + 1:]
                if name == "eval" and rest:
                    reason = rules.command_reason(" ".join(rest), depth + 1)
                elif name in audit.SHELLS:
                    script = command_script(audit, rest)
                    if script is not None:
                        reason = rules.command_reason(script, depth + 1)
            if reason:
                return reason
        return None

    def read_reason(self, command, depth):
        """The deny reason for a command text, or None. Raises when the text cannot be read."""
        audit, rules = self.audit, self.rules
        text = audit._join_as_bash(audit.strip_data_heredocs(command, audit.DATA_COMMANDS))
        items = audit.split_command(text)
        for position, item in enumerate(items):
            if not isinstance(item, list):
                continue
            reason = self.segment_reason(items, position, depth)
            if reason:
                return reason
            for word in item:
                for body in rules.substitution_bodies(word):
                    reason = rules.command_reason(body, depth + 1)
                    if reason:
                        return reason
        return None

    def command_reason(self, command, depth=0):
        """The deny reason for a command text, or None. Raises nothing: the hook decides what a text that cannot be read gives."""
        if depth > self.audit.MAX_SHELL_DEPTH:
            return self.rules.depth_reason()
        try:
            return self.read_reason(command, depth)
        except Exception as error:  # a ValueError of the reader, a RecursionError, or any other failure
            return self.rules.unreadable_reason(command, depth, error)
