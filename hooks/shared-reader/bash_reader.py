# The bash command reader that the Bash tool-call hooks share (hooks/subagent-readonly/block_subagent_writes.py and
# hooks/worktree-branch/check_branch_name.py). It loads the reader of hooks/workflow-audit/audit and walks the wrapped forms of a command
# (`bash -c`, `eval`, a pipeline, a `&&` chain, a substitution). Each hook adds its own deny rules in a subclass of CommandWalker.
# A fix to the walk is made here once. A hook is run with `python3 -I`, so it adds this folder to `sys.path` itself.
import importlib.machinery
import importlib.util
import os
import sys

AUDIT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workflow-audit", "audit")


def load_reader(module_name):
    """The audit script as a module: it has no `.py` extension, and its `__main__` guard makes the load safe. No `.pyc` is written."""
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        loader = importlib.machinery.SourceFileLoader(module_name, AUDIT)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = previous


class CommandWalker:
    """The walk over a command text. A subclass defines `substitution_bodies`, `command_reason` and `segment_reason`."""

    def __init__(self, audit):
        self.audit = audit

    def wrapped_reason(self, rest, depth):
        """The deny reason of the command that `eval` or a shell `-c` runs; `rest` is the words after the program word. None if no command."""
        if not rest:
            return None
        option = next((position for position, argument in enumerate(rest)
                       if self.audit.SHELL_COMMAND_OPTION.fullmatch(argument)), None)
        if option is not None and option + 1 < len(rest):
            return self.command_reason(rest[option + 1], depth + 1)
        return None

    def eval_reason(self, rest, depth):
        return self.command_reason(" ".join(rest), depth + 1) if rest else None

    def read_reason(self, command, depth):
        """The deny reason for a command text, or None. Raises when the text cannot be read."""
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
        return self.items_reason(items, depth)

    def items_reason(self, items, depth):
        """The deny reason of a rule that reads the whole split text (segments and separators), or None. A subclass may define it."""
        return None
