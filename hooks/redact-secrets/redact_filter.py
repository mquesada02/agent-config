"""Monitor line filter: read lines on stdin, write each line with its secret values replaced by ***.

The PreToolUse rewrite hook (redact_pre.py) pipes every Monitor command through this script. Each line goes
through redact_rules.redact and is flushed at once. Five multi-line secrets keep state:
- A PEM private-key block is held from its BEGIN line to its END line and written as one *** (the text
  before BEGIN and after END is kept). At 200 held lines with no END, the held lines are dropped, one ***
  line is written, and every further line up to and including the END line is dropped. When the BEGIN line
  also opens a JSON object or array under a matched key (`{"key": {"k": "` and the BEGIN line), the filter
  keeps the bracket depth and whether the BEGIN line is inside a JSON string. The text after the END line is
  scanned from that depth, so the JSON state goes on after the END line until the brackets balance. This holds
  for a held block and for a block past the cap. A held block writes the line ending of the END line when the
  brackets stay open.
- A JSON object or array under a matched key that does not close on its line: the redacted line is written,
  and every following line is dropped until the brackets balance. In this state a bracket inside a PEM block does not count:
  a complete BEGIN to END pair on the line becomes *** before the scan, as in redact_rules, and the first BEGIN
  line with no END line on the line stops the scan, keeps the depth and drops the lines up to its END line;
  then the JSON state goes on after the END line. A string that the BEGIN line left open at the end of the
  END line stays open on the next lines (as redact_rules reads it), up to the line that holds its closing quote.
- A YAML block scalar under a matched key (`key: |` or `key: >`): `key: ***` is written, and every following
  line that is empty or indented more than the key is dropped. The key can be quoted (`'key': |`,
  `"key": |`) and the header can have node properties (`key: !!str |`, `key: &a |`). The key indent is the
  column of the key's first character (its opening quote for a quoted key).
- A matched key with an empty value (`key:` and nothing after it but node properties): the key line is held
  for one line. If the next line is hidden by the empty-key rule of redact_rules (blank, indented deeper than
  the key, or at the key indent and starting with `- `), the key line is written as `key: ***` and every
  following hidden line is dropped, up to the first other line. Otherwise the key line is written as a normal
  line, so is a held key line at the end of the input. A hidden line with a BEGIN line and no END line drops
  up to its END line, then the state goes on. The key indent is measured on the text after the PEM rule. For a
  key on the rest of a line after a dropped state it is measured on the rest only, so the filter can hide
  more lines than redact_rules does there (fail-closed).
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
  lines are not written.
The text that follows the end of a state on the same line is handled as a normal line, so it can start a new
state. Held or dropped lines at the end of the input are never written, except a held key line of the
empty-key and pending JSON value states (see above). The filter fails closed: on any error it writes nothing
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


def key_is_live(key_body):
    """Whether the empty secret key at the end of the line is a key for redact, not swallowed by an earlier value.

    A live key masks a JSON string on the next line, so the probe line is masked; a swallowed key leaves it.
    """
    return redact_rules.redact(key_body + '\n"x"').endswith('\n"***"')


def yaml_block_indent(body):
    """The key column of the first matched key with a block scalar header in the line, or None.

    The key is a YAML key, a single-quoted key or a plain double-quoted key. The header is the one of
    redact_rules.BLOCK_HEADER: optional node properties, then `|` or `>`.
    """
    for match in redact_rules.KEY_OCCURRENCE.finditer(body):
        key = redact_rules.block_key(match)
        if key is None or not redact_rules.is_secret_key(key):
            continue
        if redact_rules.BLOCK_HEADER.match(body, match.end()):
            return match.start()
    return None


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
            return redact_rules.redact(body + "\n ").split("\n", 1)[0] + ending
        return redact_rules.redact(body) + ending

    def normal_line(self, line):
        body, ending = split_ending(line)
        if has_unclosed_begin(body):
            self.pem_depth, self.pem_in_string = unclosed_json_depth(before_first_begin(body))
            self.handler = self.pem_hold
            self.held = [line]
            return ""
        depth = unclosed_json_depth(body)[0] if "{" in body or "[" in body else 0
        if depth > 0:
            self.handler = self.json_drop
            self.depth = depth
        else:
            indent = yaml_block_indent(body) if "|" in body or ">" in body else None
            if indent is not None:
                self.handler = self.yaml_drop
                self.key_indent = indent
            else:
                found = redact_rules.empty_key(body) if ":" in body else None
                if found is not None:
                    # a plain double-quoted key may be followed by a JSON value on a later line
                    self.handler = self.json_pending if found[2] else self.empty_key_hold
                    self.held = [line]
                    self.key_indent = found[0]
                    return ""
        return redact_rules.redact(body) + ending

    def rest_after_drop(self, rest_line):
        """Handle the text that follows the end of a dropped state on the same line as a normal line.

        An empty rest writes nothing. (After a PEM END line the rest is a normal line even when it is empty,
        because the held block was written without a line ending.)
        """
        if split_ending(rest_line)[0].strip() == "":
            return ""
        return self.normal_line(rest_line)

    def pem_hold(self, line):
        end = END.search(line)
        if end is not None:
            head = "".join(self.held) + line[: end.end()]
            self.handler = self.normal_line
            if self.pem_depth > 0:
                return redact_rules.redact(head) + self.json_after_pem(line[end.end():], True)
            return redact_rules.redact(head) + self.normal_line(line[end.end():])
        if len(self.held) + 1 >= CAP:
            self.handler = self.pem_drop
            return MASK_LINE
        self.held.append(line)
        return ""

    def pem_drop(self, line):
        end = END.search(line)
        if end is None:
            return ""
        if self.pem_resume is not None:
            # the block was in a line hidden by the empty-key rule: the rest of the END line is hidden too
            self.handler, self.pem_resume = self.pem_resume, None
            return ""
        if self.pem_depth > 0:
            return self.json_after_pem(line[end.end():], False)
        self.handler = self.normal_line
        return self.rest_after_drop(line[end.end():])

    def json_scan(self, line, in_string, after):
        """The scan of the JSON drop state on a line. Return (text to write, whether the brackets closed).

        Complete BEGIN to END pairs on the line become *** first, as redact_rules does, so a bracket inside a PEM
        block is not counted. The first BEGIN line that has no END line on the line stops the scan: the depth and
        the in-string state are kept, and the lines up to the END line are dropped. When the brackets close, the
        text after the closing bracket is handled by `after`.
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
            return after(shown[closed:] + ending), True
        if begin is not None:
            self.pem_depth, self.pem_in_string = self.depth, in_string
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
        text, closed = self.json_scan(rest, in_string, self.normal_line if held else self.rest_after_drop)
        if held and not closed:
            text += split_ending(rest)[1]
        return text

    def hide_line(self, body):
        """Drop a line that the empty-key rule hides. A BEGIN line with no END line drops up to its END line."""
        self.pem_depth = 0
        if has_unclosed_begin(body):
            self.pem_resume = self.empty_key_drop
            self.handler = self.pem_drop
        else:
            self.handler = self.empty_key_drop
        return ""

    def empty_key_hold(self, line):
        """The line after an empty secret key decides: hidden (the key line is masked) or shown (normal lines)."""
        key_body, key_ending = split_ending(self.held[0])
        body, _ = split_ending(line)
        if redact_rules.hidden_by_empty_key(body, self.key_indent):
            # The key line and the next line go through redact together. The first output line is never changed
            # by the second line, so it differs from redact(key line) only when redact masked the key (an earlier
            # value on the same line can swallow it). A blank line becomes one space, so that text follows the
            # line break and redact sees a following line.
            probe = body if body.strip() != "" else " "
            first = redact_rules.redact(key_body + "\n" + probe).split("\n", 1)[0]
            if first != redact_rules.redact(key_body):
                self.hide_line(body)
                return first + key_ending
        self.handler = self.normal_line
        return redact_rules.redact(key_body) + key_ending + self.normal_line(line)

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
        plain_key = redact_rules.redact(key_body)
        if unclosed and key_is_live(key_body):
            # an object or array that is still open at its BEGIN line is one value: redact masks it to its close
            before = before_first_begin(body)
            depth, closed, in_string = scan_brackets(before, 0, indent)
            if before[indent : indent + 1] in ("{", "[") and closed < 0:
                self.pem_depth, self.pem_in_string = depth, in_string
                self.handler = self.pem_drop
                return plain_key + key_ending + "".join(blanks) + before[:indent] + '"' + redact_rules.MASK + '"' + ending
        self.handler = self.normal_line
        if not unclosed and key_is_live(key_body) and redact_rules.starts_json_value(shown, indent):
            return plain_key + key_ending + "".join(blanks) + self.json_value_line(shown, ending, indent)
        # a line with an unclosed BEGIN line is hidden even at the key indent: its value must not be written
        hidden = unclosed or redact_rules.hidden_by_empty_key(body, self.key_indent)
        if blanks or hidden:
            # a held blank line is a hidden line: it becomes one space, so that redact sees a following line.
            # A line with an unclosed BEGIN line is no JSON value, but redact would read it as one after the PEM
            # rule, so the one space stands in for it too.
            probe = " " if blanks or unclosed else body
            first = redact_rules.redact(key_body + "\n" + probe).split("\n", 1)[0]
            if first != plain_key:
                if hidden:
                    return first + key_ending + self.hide_line(body)
                return first + key_ending + self.normal_line(line)
        return plain_key + key_ending + "".join(blanks) + self.normal_line(line)

    def json_value_line(self, shown, ending, start):
        """A JSON value at `start` of a line after its key, redacted as the same-line rule does it.

        The rest of the line is handled as a normal line. An object or array that does not close on the line
        writes the masked line and enters the JSON drop state.
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
        return self.normal_line(shown[:start] + replacement + shown[end:] + ending)

    def empty_key_drop(self, line):
        body, _ = split_ending(line)
        if redact_rules.hidden_by_empty_key(body, self.key_indent):
            return self.hide_line(body)
        self.handler = self.normal_line
        return self.normal_line(line)

    def yaml_drop(self, line):
        body, _ = split_ending(line)
        indent = len(body) - len(body.lstrip(" \t"))
        if body.strip() == "" or indent > self.key_indent:
            return ""
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
