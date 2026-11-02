"""Monitor line filter: read lines on stdin, write each line with its secret values replaced by ***.

The PreToolUse rewrite hook (redact_pre.py) pipes every Monitor command through this script. Each line goes
through redact_rules.redact and is flushed at once. Three multi-line secrets keep state:
- A PEM private-key block is held from its BEGIN line to its END line and written as one *** (the text
  before BEGIN and after END is kept). At 200 held lines with no END, the held lines are dropped, one ***
  line is written, and every further line up to and including the END line is dropped.
- A JSON object or array under a matched key that does not close on its line: the redacted line is written,
  and every following line is dropped until the brackets balance.
- A YAML block scalar under a matched key (`key: |` or `key: >`): `key: ***` is written, and every following
  line that is empty or indented more than the key is dropped.
The text that follows the end of a state on the same line is handled as a normal line, so it can start a new
state. Held or dropped lines at the end of the input are never written. The filter fails closed: on any
error it writes nothing more and exits non-zero, so the pipe ends and no unfiltered text reaches the model.

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
LINE_ENDING = re.compile(r"\r?\n\Z")
MASK_LINE = redact_rules.MASK + "\n"


def split_ending(line):
    """(body, ending) of a line: the ending is `\\r\\n`, `\\n` or empty."""
    match = LINE_ENDING.search(line)
    if match is None:
        return line, ""
    return line[: match.start()], match.group()


def scan_brackets(text, depth, start=0):
    """Count `{ [` and `} ]` from `start`, strings ignored. Return (depth, index after the closing bracket).

    The index is -1 while the depth stays above 0. The in-string state starts outside a string on each call,
    because a JSON string does not span lines.
    """
    in_string = False
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
                return 0, index + 1
        index += 1
    return depth, -1


def unclosed_json_depth(body):
    """The open depth of the first matched plain JSON key whose value bracket does not close on the line, or 0."""
    for match in redact_rules.KEY_OCCURRENCE.finditer(body):
        key = match.group("jkey")
        if key is None or match.group("jq") != '"' or not redact_rules.is_secret_key(key):
            continue
        start = match.end()
        if start < len(body) and body[start] in "{[":
            depth, closed = scan_brackets(body, 0, start)
            if closed < 0:
                return depth
    return 0


def yaml_block_indent(body):
    """The key column of the first matched `key: |` or `key: >` in the line, or None."""
    for match in redact_rules.KEY_OCCURRENCE.finditer(body):
        key = match.group("ykey")
        if key is None or not redact_rules.is_secret_key(key):
            continue
        start = match.end()
        if start < len(body) and body[start] in "|>":
            return match.start()
    return None


class LineFilter:
    NORMAL, PEM_HOLD, PEM_DROP, JSON_DROP, YAML_DROP = range(5)

    def __init__(self):
        self.state = self.NORMAL
        self.held = []
        self.depth = 0
        self.key_indent = 0

    def feed(self, line):
        """The text to write for one input line (may be empty)."""
        handler = {
            self.NORMAL: self.normal_line,
            self.PEM_HOLD: self.pem_hold,
            self.PEM_DROP: self.pem_drop,
            self.JSON_DROP: self.json_drop,
            self.YAML_DROP: self.yaml_drop,
        }[self.state]
        return handler(line)

    def normal_line(self, line):
        body, ending = split_ending(line)
        begins = list(BEGIN.finditer(body))
        if begins and END.search(body, begins[-1].end()) is None:
            self.state = self.PEM_HOLD
            self.held = [line]
            return ""
        depth = unclosed_json_depth(body)
        if depth > 0:
            self.state = self.JSON_DROP
            self.depth = depth
            return redact_rules.redact(body) + ending
        indent = yaml_block_indent(body)
        if indent is not None:
            self.state = self.YAML_DROP
            self.key_indent = indent
            return redact_rules.redact(body) + ending
        return redact_rules.redact(body) + ending

    def rest_after(self, rest_line, empty_writes_ending):
        """Handle the text that follows the end of a state on the same line as a normal line."""
        body, ending = split_ending(rest_line)
        if body.strip() == "" and not empty_writes_ending:
            return ""
        return self.normal_line(rest_line)

    def pem_hold(self, line):
        end = END.search(line)
        if end is not None:
            head = "".join(self.held) + line[: end.end()]
            self.held = []
            self.state = self.NORMAL
            return redact_rules.redact(head) + self.rest_after(line[end.end():], True)
        if len(self.held) + 1 >= CAP:
            self.held = []
            self.state = self.PEM_DROP
            return MASK_LINE
        self.held.append(line)
        return ""

    def pem_drop(self, line):
        end = END.search(line)
        if end is None:
            return ""
        self.state = self.NORMAL
        return self.rest_after(line[end.end():], False)

    def json_drop(self, line):
        body, ending = split_ending(line)
        self.depth, closed = scan_brackets(body, self.depth)
        if closed < 0:
            return ""
        self.state = self.NORMAL
        return self.rest_after(body[closed:] + ending, False)

    def yaml_drop(self, line):
        body, _ = split_ending(line)
        indent = len(body) - len(body.lstrip(" \t"))
        if body.strip() == "" or indent > self.key_indent:
            return ""
        self.state = self.NORMAL
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


def run():
    try:
        main()
    except BrokenPipeError:
        # the reader closed stdout: send any further flush to /dev/null so Python does not print a traceback
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(1)
    except Exception as error:
        # the class name only: an error message could hold a part of the input
        sys.stderr.write("redact_filter.py failed: %s\n" % type(error).__name__)
        sys.exit(1)


if __name__ == "__main__":
    run()
