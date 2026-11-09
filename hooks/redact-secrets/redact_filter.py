"""Monitor line filter: read lines on stdin, write each line with its secret values replaced by ***.

The PreToolUse rewrite hook (redact_pre.py) pipes every Monitor command through this script. Each line goes
through redact_rules.redact and is flushed at once. Five multi-line secrets keep state:
- A PEM private-key block is held from its BEGIN line to its END line. When it ends, the filter writes the
  joined line as redact_rules writes it: the text of the BEGIN line before BEGIN, ***, and the text of the END
  line after END, judged with the line prefix of the BEGIN line. So a keyed value that holds the block is masked
  as one value, with the text after END. A state that the text after END opens (a BEGIN line, an empty key, a
  block scalar header, an open JSON object or array) works as on a normal line; a held key line is the joined
  line, and its key column is measured on the text after END only. At 200 held lines with no END (the held-line
  cap), the held lines are dropped, one *** line is written, and every further line up to and including the
  END line is dropped. The filter keeps the line prefix and the text before BEGIN of the BEGIN line, and judges
  whether BEGIN stands in a masked keyed value: the keyed rules, run on that text followed by a word, read the
  word as the start or a part of the value of a secret key. If it does, the text after END is dropped up to the
  next BEGIN marker on that line, and from that marker on the line is a normal line. If it does not, the text
  after END is a normal line. The exception is a block scalar header line that holds the BEGIN marker (see the
  YAML block scalar bullet): its block state has priority over both. A PEM block with no END line before the end
  of the input writes nothing of its held lines.
  A block whose BEGIN line also opens a JSON object or array under a matched key (`{"key": {"k": "` and the
  BEGIN line) keeps another path: the filter keeps the bracket depth and whether the BEGIN line is inside a JSON
  string. The text after the END line is scanned from that depth, so the JSON state goes on after the END line
  until the brackets balance. This holds for a held block and for a block past the cap. A held block writes the
  line ending of the END line when the brackets stay open.
- A JSON object or array under a matched key that does not close on its line: the redacted line is written,
  and every following line is dropped until the brackets balance. The key can be a plain double-quoted key or a
  key written with escaped quotes (`{\\"key\\": {`), and a swallowed key of either form. In this state a bracket
  inside a PEM block does not count: a complete BEGIN to END pair on the line becomes *** before the scan, as in redact_rules, and the first BEGIN
  line with no END line on the line stops the scan, keeps the depth and drops the lines up to its END line;
  then the JSON state goes on after the END line. A string that the BEGIN line left open at the end of the
  END line stays open on the next lines (as redact_rules reads it), up to the line that holds its closing quote.
- A YAML block scalar under a matched key (`key: |` or `key: >`): `key: ***` is written, and every following
  line that is empty or indented more than the key is dropped. The key can be quoted (`'key': |`,
  `"key": |`) and the header can have node properties (`key: !!str |`, `key: &a |`). The key indent is the
  column of the key's first character (its opening quote for a quoted key). By the PEM rule of the drop states, a
  dropped line with a BEGIN line and no END line drops up to its END line and the text after it (a complete
  BEGIN to END pair on the line becomes *** first, so only a BEGIN line left over starts the drop); another
  BEGIN line with no END line in that text goes on to the next END line, or to the end of the input, then the
  block state goes on. The PEM body and the END line need no indent. The key can be a swallowed key: a key in a
  value that an earlier value masks to the line end (`"key": abc "key": |`) opens this state, with its own
  column as the key indent (the rescan rule of redact_rules, decided by redact_rules.later_line_state).
  The state goes on after a PEM block too when the BEGIN marker is on a block scalar header line (`key: | BEGIN`):
  a block scalar header line that holds a BEGIN marker takes its state from redact_rules.later_line_state, run on
  the text before the BEGIN marker. After the END line the lines that are empty or indented more than the key are
  dropped, as in redact_rules. The text after the END marker stays part of the joined line and is hidden whatever
  its indent. This state has priority over a state that the text after END opens, and past the held-line cap it
  drops the text after END as well. A BEGIN marker on its own block line is the PEM rule above.
- A matched key with an empty value (`key:` and nothing after it but node properties): the key line is held
  for one line. If the next line is hidden by the empty-key rule of redact_rules (blank, indented deeper than
  the key, or at the key indent and starting with `- `), the key line is written as `key: ***` and every
  following hidden line is dropped, up to the first other line. Otherwise the key line is written as a normal
  line, so is a held key line at the end of the input. This state has the PEM rule of the drop states too: a
  hidden line with a BEGIN line and no END line drops up to its END line and the text after it, and another
  BEGIN line with no END line in that text goes on to the next END line, then the state goes on. The key
  indent is measured on the text after the PEM rule. For a key on the rest of a line after a dropped state it
  is measured on the rest only, so the filter can hide more lines than redact_rules does there (fail-closed).
  The key can be a swallowed key (`key: abc 'key':`): it opens this state with its own column, and the key line is
  written as redact_rules writes it, so the mask of the first key covers the swallowed key.
- A plain double-quoted matched key with an empty value (`"key":`), the pending JSON value state: the key line
  is held with the blank lines after it, up to the first non-blank line. If that line starts a JSON value (see
  redact_rules), the key line, the blank lines and the value line are written, the value masked as the
  same-line rule masks it (a string `"***"` unless the value guard keeps it, `{}` and `[]` and a token stay)
  and the rest of the line is a normal line; an object or array that does not close on the line enters the
  JSON drop state. Otherwise the empty-key rule above applies from the key line, with each held blank line
  hidden. A value line with a BEGIN line and no END line is never a JSON value, with one exception: an object
  or array that is still open at the BEGIN line (the key is live) is one value. The key line and the blank
  lines are written, the value line is written as its indent and `"***"`, the lines up to the END line are
  dropped, and the JSON drop state goes on after the END line (the PEM then JSON rule above). At the end of
  the input the key line is written as `"key": ***` when a blank line was held, else unchanged; held blank
  lines are not written. The key can be a swallowed key (`"key": abc "key":`): it opens this state like a key that
  is not swallowed, so a next-line JSON value is masked and the key line is written as redact_rules writes it.
The text that follows the end of a state on the same line is handled as a normal line, so it can start a new
state. That text is a rest of a line, and a key in a rest is judged with the line prefix: the text before the
rest on its line, as redact_rules.redact sees that line (spec 334, decision 12). The prefix of a rest after a
PEM END line is the prefix of the BEGIN line, the text before the BEGIN marker (earlier complete pairs shown as
***) and ***; after the closing bracket of a dropped JSON object it is the prefix of the closing line and the
text of that line before the rest; after the value of a next-line JSON value it is the original text of the
value line before the rest. A rest is never at a line start position, so a prose key in it stays, and the
empty-key and block scalar detection of a rest uses the same line prefix: a prose key in a rest opens neither
state. The filter keeps the prefix of a held rest line and of a PEM block past the held-line cap. Held or
dropped lines at the end of the input are never written, except a held key line of the empty-key and pending
JSON value states (see above). The filter fails closed: on any error it writes nothing
more and exits non-zero, so the pipe ends and no unfiltered text reaches the model.

Test switch: when REDACT_SECRETS_TEST_SLEEP is exactly `fail`, the filter raises an error before it reads or
writes anything. Any other value has no effect.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import redact_rules  # noqa: E402

CAP = 200
# New constants: redact_rules has only the combined PEM_BLOCK pattern.
BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")
COMPLETE_PEM = re.compile(BEGIN.pattern + r".*?" + END.pattern)  # one line: a pair on a single line
MASK_LINE = redact_rules.MASK + "\n"


def split_ending(line):
    """(body, ending) of a line: the ending is `\\r\\n`, `\\n` or empty."""
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    return line, ""


def scan_brackets(text, depth, start=0, in_string=False):
    """Count `{ [` and `} ]` from `start`, strings ignored. Return (depth, index after the closing bracket,
    in-string state at the end).

    The index is -1 while the depth stays above 0. A JSON string does not span lines, so a normal call starts
    outside a string. The text after a PEM block in a string starts inside it (in_string=True).
    """
    index = start
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if in_string:
            in_string = char != '"'
        elif char == '"':
            in_string = True
        elif char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
            if depth <= 0:
                return 0, index + 1, in_string
        index += 1
    return depth, -1, in_string


def has_unclosed_begin(body):
    """Whether the last BEGIN line of the line has no END line after it."""
    begins = list(BEGIN.finditer(body)) if "-----BEGIN" in body else []
    return bool(begins) and END.search(body, begins[-1].end()) is None


def masked_pairs(body):
    """The line with every complete BEGIN to END pair replaced by ***, as redact_rules does first.

    A BEGIN line that is left has no END line after it on the line. The first one is where redact_rules
    starts its PEM block, so a bracket inside a complete pair is never a bracket of the JSON.
    """
    return COMPLETE_PEM.sub(redact_rules.MASK, body) if "-----BEGIN" in body else body


def before_first_begin(body):
    """The text before the first BEGIN line that has no END line after it on the line (pairs masked first)."""
    shown = masked_pairs(body)
    return shown[: BEGIN.search(shown).start()]


def unclosed_json_depth(body):
    """(open depth, in-string state) of the first matched plain JSON key whose value bracket does not close
    on the line, or (0, False). A bracket inside a complete BEGIN to END pair is not counted."""
    body = masked_pairs(body)
    for match in redact_rules.KEY_OCCURRENCE.finditer(body):
        key = match.group("jkey")
        if key is None or match.group("jq") != '"' or not redact_rules.is_secret_key(key):
            continue
        start = match.end()
        if start < len(body) and body[start] in "{[":
            depth, closed, in_string = scan_brackets(body, 0, start)
            if closed < 0:
                return depth, in_string
    return 0, False


def begin_in_masked_value(before, prefix):
    """Whether a BEGIN marker after the text `before` stands in a masked keyed value.

    That is the case when the keyed rules of redact_rules, run on `before` (with its line prefix) followed by a
    value that the value guard never keeps, read that value as the start or a part of the value of a secret key.
    The value is a word, so a probe that is gone from the result stood in a masked value.
    """
    probe = "pemprobe"
    return probe not in redact_rules.redact(before + probe, prefix)


class LineFilter:
    def __init__(self):
        self.handler = self.normal_line  # the method for the current state
        self.held = []
        self.depth = 0
        self.key_indent = 0
        self.pem_resume = None  # the state to resume after the END line of a PEM block in a hidden line
        self.pem_depth = 0  # the open JSON depth that a PEM block started in (0: none), kept to its END line
        self.pem_in_string = False  # whether that BEGIN line is inside a JSON string
        self.string_open = False  # the JSON drop state goes on inside a string that a PEM block left open
        self.begin_prefix = ""  # the line prefix of the BEGIN line of the held PEM block
        self.pem_prefix = ""  # the line prefix of the rest after the END line of a PEM block (held or dropped)
        self.held_head = ""  # the joined line before the held key line: a PEM block that ended before it
        self.held_origin = ""  # the line prefix of the joined line (held_head and the held key line)
        self.pem_in_value = False  # past the held-line cap: the BEGIN marker stands in a masked keyed value
        # the key column of the block scalar header line that holds the BEGIN marker of the held block (None: no
        # block state), kept to the END line of the last block, where the block state starts
        self.pem_block_column = None

    def feed(self, line):
        """The text to write for one input line (may be empty)."""
        return self.handler(line)

    def finish(self):
        """The text to write at the end of the input: a held key line is written as redact(text) writes it.

        That is `"key": ***` when a blank line was held by the pending JSON value state (the empty-key rule
        hides blank lines), and the key line as a normal line otherwise. Held blank lines are never written.
        """
        if self.handler not in (self.empty_key_hold, self.json_pending):
            return ""
        body, ending = split_ending(self.held[0])
        if len(self.held) > 1:
            return self.key_line(body, " ") + ending
        return self.key_line(body) + ending

    def key_line(self, key_body, probe=None):
        """The held key line as redact_rules writes it: joined with `held_head`. With `probe` (a line after it) the
        first line of the result is written. The probe is shifted by the length of the head, so that the empty-key
        rule reads its indent against the key column of the joined line, which is the key column of the rest
        (the column that the filter measured) plus the length of the head."""
        if probe is None:
            return redact_rules.redact(self.held_head + key_body, self.held_origin)
        text = self.held_head + key_body + "\n" + " " * len(self.held_head) + probe
        return redact_rules.redact(text, self.held_origin).split("\n", 1)[0]

    def normal_line(self, line, prefix="", head=""):
        """A normal line. `prefix` is the line prefix of `head + line`: empty for a whole line.

        `head` is the text of the joined line before `line`, when `line` is the rest after the END line of a PEM
        block (see pem_hold). The line is judged as the rest, with the line prefix `prefix + head`, so a state that
        it opens measures its key column on the rest only. The text that is written is the joined line.
        """
        body, ending = split_ending(line)
        rest_prefix = prefix + head
        if has_unclosed_begin(body):
            self.pem_depth, self.pem_in_string = unclosed_json_depth(before_first_begin(body))
            self.begin_prefix = prefix
            self.pem_in_value = False  # set at the held-line cap of this block
            if self.pem_block_column is None:  # a carried block state (a second BEGIN marker after END) stays
                # the one decision of redact_rules: only a block state of the text before BEGIN goes on after END
                state = redact_rules.later_line_state(before_first_begin(body), rest_prefix)
                if state is not None and state.rule == "block":
                    self.pem_block_column = state.column
            self.pem_prefix = rest_prefix + before_first_begin(body) + redact_rules.MASK
            self.handler = self.pem_hold
            self.held = [head + line]
            return ""
        # the one decision of redact_rules: which key of the line opens a state (a swallowed key too), which state
        state = redact_rules.later_line_state(body, rest_prefix)
        if state is not None:
            if state.rule == "json_open":
                self.handler = self.json_drop
                self.depth = scan_brackets(masked_pairs(body), 0, state.value_start)[0]
            elif state.rule == "block":
                self.handler = self.yaml_drop
                self.key_indent = state.column
            else:
                # a plain double-quoted key may be followed by a JSON value on a later line
                self.handler = self.json_pending if state.rule == "empty_json" else self.empty_key_hold
                self.held = [line]
                self.held_head = head
                self.held_origin = prefix
                self.key_indent = state.column
                return ""
        return redact_rules.redact(head + body, prefix) + ending

    def rest_after_drop(self, rest_line, prefix=""):
        """Handle the text that follows the end of a dropped state on the same line as a normal line.

        An empty rest writes nothing. (After a PEM END line the rest is a normal line even when it is empty,
        because the held block was written without a line ending.) `prefix` is the line prefix of the rest.
        """
        if split_ending(rest_line)[0].strip() == "":
            return ""
        return self.normal_line(rest_line, prefix)

    def pem_hold(self, line):
        end = END.search(line)
        if end is not None:
            block = "".join(self.held) + line[: end.end()]
            self.handler = self.normal_line
            if self.pem_depth > 0:
                self.pem_block_column = None  # the JSON path has priority
                return redact_rules.redact(block, self.begin_prefix) + self.json_after_pem(line[end.end():], True)
            # the joined line: the text before the BEGIN marker and *** (the head), then the rest after the END marker
            head = redact_rules.PEM_BLOCK.sub(redact_rules.MASK, block)
            rest = line[end.end():]
            if self.pem_block_column is not None and not has_unclosed_begin(rest):
                # a block scalar header line that holds the BEGIN marker: the block state has priority over a state
                # that the rest opens, so the rest is only part of the joined line, and the lines after it go to the
                # block state
                self.key_indent, self.pem_block_column = self.pem_block_column, None
                self.handler = self.yaml_drop
                body, ending = split_ending(rest)
                return redact_rules.redact(head + body, self.begin_prefix) + ending
            return self.normal_line(rest, self.begin_prefix, head)
        if len(self.held) + 1 >= CAP:
            self.handler = self.pem_drop
            before = before_first_begin(split_ending(self.held[0])[0])
            self.pem_in_value = begin_in_masked_value(before, self.begin_prefix)
            return MASK_LINE
        self.held.append(line)
        return ""

    def pem_drop(self, line):
        end = END.search(line)
        if end is None:
            return ""
        if self.pem_resume is not None:
            # the block was in a hidden line of a drop state: the rest of the END line is hidden too, and another
            # unclosed BEGIN line in it goes on to the next END line before the drop state goes on
            if not has_unclosed_begin(line[end.end():]):
                self.handler, self.pem_resume = self.pem_resume, None
            return ""
        if self.pem_depth > 0:
            self.pem_block_column = None  # the JSON path has priority
            return self.json_after_pem(line[end.end():], False)
        if self.pem_block_column is not None:
            # a block scalar header line that holds the BEGIN marker (fail closed past the cap): the rest of the END
            # line is part of the header, so it is dropped like a hidden line of the block state, and the block state
            # goes on after it. The block state has priority over the keyed value rule below.
            self.key_indent, self.pem_block_column = self.pem_block_column, None
            return self.hide_line(split_ending(line[end.end():])[0], self.yaml_drop)
        self.handler = self.normal_line
        rest = line[end.end():]
        if self.pem_in_value:
            # the BEGIN marker stood in a masked keyed value: the rest is part of it, up to the next BEGIN marker
            begin = BEGIN.search(rest)
            return "" if begin is None else self.normal_line(rest[begin.start():], self.pem_prefix)
        return self.rest_after_drop(rest, self.pem_prefix)

    def json_scan(self, line, in_string, after, prefix=""):
        """The scan of the JSON drop state on a line. Return (text to write, whether the brackets closed).

        Complete BEGIN to END pairs on the line become *** first, as redact_rules does, so a bracket inside a PEM
        block is not counted. The first BEGIN line that has no END line on the line stops the scan: the depth and
        the in-string state are kept, and the lines up to the END line are dropped. When the brackets close, the
        text after the closing bracket is handled by `after` with its line prefix: `prefix` (the line prefix of
        this line) and the text of this line before the rest.
        """
        body, ending = split_ending(line)
        shown = masked_pairs(body)
        begin = BEGIN.search(shown) if "-----BEGIN" in shown else None
        limit = len(shown) if begin is None else begin.start()
        # a string that a PEM block left open stays open on the next line, as redact_rules reads it
        carried, self.string_open = in_string, False
        self.depth, closed, in_string = scan_brackets(shown[:limit], self.depth, 0, in_string)
        if closed >= 0:
            self.handler = self.normal_line
            return after(shown[closed:] + ending, prefix + shown[:closed]), True
        if begin is not None:
            self.pem_depth, self.pem_in_string = self.depth, in_string
            self.pem_prefix = prefix + shown[: begin.start()] + redact_rules.MASK
            self.handler = self.pem_drop
        else:
            self.string_open = carried and in_string
        return "", False

    def json_drop(self, line):
        return self.json_scan(line, self.string_open, self.rest_after_drop)[0]

    def json_after_pem(self, rest, held):
        """The JSON drop state goes on after the END line of a PEM block that began inside an open object or array.

        `rest` is the text after the END line. A held block was written without a line ending, so the rest is a
        normal line (it carries the ending even when empty), and the ending of the END line is written when the
        brackets stay open. A dropped block already ended its *** line, so an empty rest writes nothing.
        """
        self.depth, self.pem_depth = self.pem_depth, 0
        in_string, self.pem_in_string = self.pem_in_string, False
        self.handler = self.json_drop
        text, closed = self.json_scan(
            rest, in_string, self.normal_line if held else self.rest_after_drop, self.pem_prefix
        )
        if held and not closed:
            text += split_ending(rest)[1]
        return text

    def hide_line(self, body, state):
        """Drop a line that the drop state `state` hides. The PEM rule of the drop states: a BEGIN line with no
        END line drops up to its END line, then the drop state goes on."""
        self.pem_depth = 0
        if has_unclosed_begin(body):
            self.pem_resume = state
            self.handler = self.pem_drop
        else:
            self.handler = state
        return ""

    def empty_key_hold(self, line):
        """The line after an empty secret key decides: hidden (the key line is masked) or shown (normal lines)."""
        key_body, key_ending = split_ending(self.held[0])
        body, _ = split_ending(line)
        if redact_rules.hidden_by_empty_key(body, self.key_indent):
            # The key line and the next line go through redact together, so that the key line is written as redact
            # writes it. A blank line becomes one space, so that text follows the line break and redact sees a
            # following line.
            probe = body if body.strip() != "" else " "
            self.hide_line(body, self.empty_key_drop)
            return self.key_line(key_body, probe) + key_ending
        self.handler = self.normal_line
        return self.key_line(key_body) + key_ending + self.normal_line(line)

    def json_pending(self, line):
        """A plain double-quoted empty secret key is held with the blank lines after it. The first non-blank line
        decides: a JSON value is masked as one value, anything else takes the empty-key rule from the key line."""
        body, ending = split_ending(line)
        if body.strip() == "":
            self.held.append(line)
            return ""
        key_body, key_ending = split_ending(self.held[0])
        blanks = self.held[1:]
        # a complete PEM block is masked before the rules look at the line; an unclosed one is no JSON value
        unclosed = has_unclosed_begin(body)
        shown = body if unclosed else redact_rules.PEM_BLOCK.sub(redact_rules.MASK, body)
        indent = len(shown) - len(shown.lstrip(" \t"))
        written_key = self.key_line(key_body)  # the text that is written is the joined line
        if unclosed:
            # an object or array that is still open at its BEGIN line is one value: redact masks it to its close
            before = before_first_begin(body)
            depth, closed, in_string = scan_brackets(before, 0, indent)
            if before[indent : indent + 1] in ("{", "[") and closed < 0:
                self.pem_depth, self.pem_in_string = depth, in_string
                self.pem_prefix = before + redact_rules.MASK  # the value line is a full line: its prefix is empty
                self.handler = self.pem_drop
                masked_value = before[:indent] + '"' + redact_rules.MASK + '"' + ending
                return written_key + key_ending + "".join(blanks) + masked_value
        self.handler = self.normal_line
        if not unclosed and redact_rules.starts_json_value(shown, indent):
            return written_key + key_ending + "".join(blanks) + self.json_value_line(shown, ending, indent)
        # a line with an unclosed BEGIN line is hidden even at the key indent: its value must not be written
        hidden = unclosed or redact_rules.hidden_by_empty_key(body, self.key_indent)
        if blanks or hidden:
            # a held blank line is a hidden line: it becomes one space, so that redact sees a following line.
            # A line with an unclosed BEGIN line is no JSON value, but redact would read it as one after the PEM
            # rule, so the one space stands in for it too.
            probe = " " if blanks or unclosed else body
            written_first = self.key_line(key_body, probe) + key_ending
            if hidden:
                return written_first + self.hide_line(body, self.empty_key_drop)
            return written_first + self.normal_line(line)
        return written_key + key_ending + "".join(blanks) + self.normal_line(line)

    def json_value_line(self, shown, ending, start):
        """A JSON value at `start` of a line after its key, redacted as the same-line rule does it.

        The rest of the line (the text after the value) is handled as a normal line with the line prefix: the
        original text of the line before the rest. When the value stays, the whole line is a normal line. An
        object or array that does not close on the line writes the masked line and enters the JSON drop state.
        """
        if shown[start] in "{[":
            depth, closed, _ = scan_brackets(shown, 0, start)
            if closed < 0:
                self.handler = self.json_drop
                self.depth = depth
                return shown[:start] + '"' + redact_rules.MASK + '"' + ending
        end, replacement = redact_rules.json_value_end(shown, start, '"')
        if replacement is None:
            return self.normal_line(shown + ending)
        return shown[:start] + replacement + self.normal_line(shown[end:] + ending, shown[:end])

    def empty_key_drop(self, line):
        body, _ = split_ending(line)
        if redact_rules.hidden_by_empty_key(body, self.key_indent):
            return self.hide_line(body, self.empty_key_drop)
        self.handler = self.normal_line
        return self.normal_line(line)

    def yaml_drop(self, line):
        body, _ = split_ending(line)
        indent = len(body) - len(body.lstrip(" \t"))
        if body.strip() == "" or indent > self.key_indent:
            return self.hide_line(body, self.yaml_drop)
        self.handler = self.normal_line
        return self.normal_line(line)


def main():
    if os.environ.get("REDACT_SECRETS_TEST_SLEEP") == "fail":
        raise RuntimeError("test switch")
    line_filter = LineFilter()
    stdout = sys.stdout.buffer
    for raw in iter(sys.stdin.buffer.readline, b""):
        text = line_filter.feed(raw.decode("utf-8", "surrogateescape"))
        if text:
            stdout.write(text.encode("utf-8", "surrogateescape"))
            stdout.flush()
    text = line_filter.finish()
    if text:
        stdout.write(text.encode("utf-8", "surrogateescape"))
        stdout.flush()


def run():
    try:
        main()
    except BrokenPipeError:
        # the reader closed stdout: send any further flush to /dev/null so Python does not print a traceback
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)
        sys.exit(1)
    except Exception as error:
        # the class name only: an error message could hold a part of the input
        sys.stderr.write("redact_filter.py failed: %s\n" % type(error).__name__)
        sys.exit(1)


if __name__ == "__main__":
    run()
