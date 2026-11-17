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


OPERATOR = "<<<"  # the here-string operator
FD_PREFIX = re.compile(r"\{\w+\}|\d+|&")
SHORT_CLUSTER = re.compile(r"-[A-Za-z]+")
VALUE_CLUSTER = re.compile(r"[-+][A-Za-z]*[oO][A-Za-z]*")  # `-o` or `-O` anywhere in the cluster takes the next word as its value
EXPANSION = re.compile(r"[$`]")  # a word with an expansion can become no word: bash then reads standard input
VALUE_LONG_OPTIONS = frozenset(("--rcfile", "--init-file"))
CLOSING_GROUP_CHARS = frozenset(");&\n")


def has_command_option(audit, arguments):
    """(a) True when the words after a shell name give a `-c` text to `command_script`. The words are cut at the first `--`: it ends the
    options, so a `-c` after it is a positional word."""
    cut = arguments.index("--") if "--" in arguments else len(arguments)
    return command_script(audit, arguments[:cut]) is not None


def reads_standard_input(audit, arguments):
    """(b) True when a shell with no `-c` option reads its commands from standard input, by the script argument rule. `arguments` are the
    words after the shell name. A redirection word is dropped. A `-` or a short cluster with `s` ends the scan: it reads standard input."""
    words = [word for _, word in audit._significant(arguments)]
    index = 0
    while index < len(words):
        word = words[index]
        if word == "-" or (SHORT_CLUSTER.fullmatch(word) and "s" in word):
            return True
        if VALUE_CLUSTER.fullmatch(word) or word in VALUE_LONG_OPTIONS:
            index += 2
        elif word == "--":
            return index + 1 >= len(words) or bool(EXPANSION.search(words[index + 1]))
        elif not word.startswith(("-", "+")):
            return bool(EXPANSION.search(word))
        else:
            index += 1
    return True


def here_string_texts(words):
    """(c) The text of each here-string in the words. A word is cut at each `<<<` (the operator may follow other text, `>f<<<text`). The text
    is what follows each operator start, overlapping starts included (`<<<a<<<<b` reads `a<<<<b`, `<b` and `b`, as a text may end in `<`).
    When the word holds more operators (`<<<a<<<b`) each piece is a text too, as the quote state is lost.
    A word that ends in an operator takes the next word whole as its text, whatever that word is. That word is also scanned as a normal word, so
    its own operators are cut too (`<<< x<<<y` reads `x<<<y` and `y`). An operator with no next word has no text."""
    texts, index = [], 0
    while index < len(words):
        word = words[index]
        index += 1
        if OPERATOR not in word:
            continue
        pieces = word.split(OPERATOR)
        for start in re.finditer("(?=" + OPERATOR + ")", word):
            text = word[start.start() + len(OPERATOR):]
            if text:
                texts.append(text)
        if len(pieces) > 2:
            texts.extend(piece for piece in pieces[1:] if piece)
        if word.endswith(OPERATOR) and index < len(words):
            texts.append(words[index])
    return list(dict.fromkeys(texts))


def _lone_amp(items, index):
    return 0 <= index < len(items) and items[index] == "&"


def _item_before_group(items, index):
    """The index of the list item that a run of substitution groups ends at `index` (a `)` string) follows, else `index` itself."""
    while index >= 0 and isinstance(items[index], str) and ")" in items[index]:
        depth = items[index].count(")") - items[index].count("(")
        index -= 1
        while depth > 0 and index >= 0:
            if isinstance(items[index], str):
                depth += items[index].count(")") - items[index].count("(")
            index -= 1
    return index


def _linked(left, right):
    """A lone `&` between two list items belongs to a redirection (`2>&1`, `&>file`) when the left item ends with `<` or `>` or the
    right item starts with `>`. The words are read as they are, quoted or not: an over-read takes the fail-closed side."""
    return bool(left and right and (left[-1].endswith(("<", ">")) or right[0].startswith(">")))


def segment_chain(audit, items, position):
    """(e) The positions of the list items that belong to the same command as the item at `position`: the splitter cuts at the `&` of a
    redirection. The item itself, and the items reached through a lone `&` to the left and to the right, repeatedly."""
    chain = [position]
    current = position
    while _lone_amp(items, current - 1):
        left = _item_before_group(items, current - 2)
        if left < 0 or not isinstance(items[left], list) or not _linked(items[left], items[current]):
            break
        chain.insert(0, left)
        current = left
    current = position
    while True:
        separator = audit._next_separator(items, current)
        if not (_lone_amp(items, separator) and separator + 1 < len(items) and isinstance(items[separator + 1], list)):
            break
        if not _linked(items[current], items[separator + 1]):
            break
        current = separator + 1
        chain.append(current)
    return chain


def clobber_words(audit, items, position):
    """(h) The words of the items that follow the chain of the segment at `position` through the `|` of a clobber redirection (`>|file`): the
    splitter cuts there, as it cuts at a pipe, but no pipe is meant when the last word before the `|` ends with `>`. The words are for the
    here-string scan only, never for the pipe or standard-input rules: an over-read (`echo ">" | cat <<<text`) takes the fail-closed side."""
    words = []
    current = segment_chain(audit, items, position)[-1]
    while True:
        separator = audit._next_separator(items, current)
        following = separator + 1
        if not (items[current] and items[current][-1].endswith(">") and separator < len(items) and items[separator] == "|"
                and following < len(items) and isinstance(items[following], list)):
            return words
        chain = segment_chain(audit, items, following)
        words.extend(word for item in chain for word in items[item])
        current = chain[-1]


def split_shell_word(audit, words):
    """(f) The words, with a shell word that is fused with a redirection (`bash<<<x`, `/bin/bash>/dev/null`) replaced by the shell word and the
    rest. The base name is taken of the part before the first `<` or `>` only. No other word changes."""
    result = []
    for word in words:
        cut = next((index for index, char in enumerate(word) if char in "<>"), -1)
        if cut > 0 and os.path.basename(word[:cut]) in audit.SHELLS:
            result.extend((word[:cut], word[cut:]))
        else:
            result.append(word)
    return result


def split_fused_redirection(words):
    """(g) The words, with a word that is fused with a redirection (`-s>`, `-x<<<text`, `pipefail>`) replaced by the text before the
    redirection and the rest. A word whose part before its first `<` or `>` is empty or a file-descriptor prefix (`2`, `{fd}`, `&`) is
    already a redirection word and stays. No word is changed or removed."""
    result, operand = [], False
    for word in words:
        cut = next((index for index, char in enumerate(word) if char in "<>"), -1)
        if operand:  # the text of a spaced here-string stays whole: it holds a command text, not a fused redirection
            result.append(word)
            operand = False
            continue
        parts = [word[:cut], word[cut:]] if cut > 0 and not FD_PREFIX.fullmatch(word[:cut]) else [word]
        operand = parts[-1].endswith(OPERATOR)  # a word that ends in an operator (`<<<`, `0<<<`, `-s<<<`, `<<<a<<<`) takes the next word as its text
        result.extend(parts)
    return result


def _pipe_token(token):
    """True for a separator token that is a pipe: after its leading closing-group characters it starts with `|` and not `||`."""
    rest = token.lstrip("".join(CLOSING_GROUP_CHARS))
    return rest.startswith("|") and not rest.startswith("||")


def _closing_count(token):
    count = 0
    for char in token:
        if char not in CLOSING_GROUP_CHARS:
            break
        count += char == ")"
    return count


def _in_group(audit, items, position):
    """True when the item at `position` is inside a substitution group that follows an outer segment."""
    index = 0
    while index < len(items):
        after = audit._next_separator(items, index) if isinstance(items[index], list) else index + 1
        if index < position < after:
            return True
        index = max(after, index + 1)
    return False


def pipe_producer(audit, items, position):
    """(d) What feeds the shell segment at `position` through a pipe: `(False, None)` when no pipe does, `(True, words)` with the words of the
    producer (a chain, its words in item order) when the lookup finds it, `(True, None)` when a pipe feeds it and no single producer is
    found (another producer). A segment inside a substitution group has no pipe here: the walk reads the group body as its own text."""
    if _in_group(audit, items, position):
        return False, None
    first = segment_chain(audit, items, position)[0]
    before = first - 1
    while before >= 0 and isinstance(items[before], str) and items[before] and set(items[before]) == {"("}:
        before -= 1
    if before < 0 or not isinstance(items[before], str) or not _pipe_token(items[before]):
        return False, None
    pipe = before
    index = 0
    while index < first:
        if not isinstance(items[index], list):
            index += 1
            continue
        chain = segment_chain(audit, items, index)
        last = chain[-1]
        separator = audit._next_separator(items, last)
        if chain[0] == index and separator <= pipe:
            closers = 0
            scan = separator
            while scan < pipe and isinstance(items[scan], str) and set(items[scan]) <= CLOSING_GROUP_CHARS:
                closers += items[scan].count(")")
                scan += 1
            if scan == pipe:
                closers += _closing_count(items[pipe])
                opens, back = 0, index - 1
                while back >= 0 and isinstance(items[back], str):
                    opens += items[back].count("(")
                    back -= 1
                if opens < closers:
                    return True, None
                return True, [word for item in chain for word in items[item]]
        index = audit._next_separator(items, index)
    return True, None


class Walk:
    """The walk over a command text. `rules` is the object of a hook. It must have these methods:
      command_reason(command, depth)        the public reason of the hook for a command text (the walk calls it for each nested text)
      depth_reason()                        the reason when the nesting is deeper than `MAX_SHELL_DEPTH` (the hook picks text and type)
      unreadable_reason(command, depth, error)  the reason when a text cannot be read (the hook's own failure rule)
      substitution_bodies(word)             the reader of substitution bodies (a hook can replace the accurate one of this module)
      first_word_reason(words)              a reason from the first word of a segment, or None (runs before the naming-only skip)
      segment_reason(words, items, position, depth)  OPTIONAL: a reason for a whole segment, called right after first_word_reason and before
                                            the naming-only skip (a hook that has it reads a segment that the skip would hide)
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
        before_skip = getattr(rules, "segment_reason", None)
        if before_skip is not None:
            reason = before_skip(words, items, position, depth)
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
