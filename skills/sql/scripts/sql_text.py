"""Shared SQL text helpers of the `sql` skill (stdlib only).

This module owns the masking of a statement text, the keyword, clause word and
anchor word lists, and the vote of one statement for each `[style]` property.
`measure_style.py` and the graders import it; no other file copies a list or a
vote rule. It also holds the small helpers that the commands share: the
extractor runner, the line reader and the `<start>-<end>` range parser.
"""
import json
import os
import re
import subprocess
import sys

KEYWORDS = "SELECT DISTINCT FROM WHERE AND OR NOT IN IS NULL AS ON USING JOIN INNER LEFT RIGHT FULL OUTER CROSS NATURAL GROUP BY ORDER HAVING LIMIT OFFSET UNION ALL INTERSECT EXCEPT INSERT INTO VALUES UPDATE SET DELETE RETURNING WITH CASE WHEN THEN ELSE END LIKE ILIKE BETWEEN EXISTS ASC DESC ANY OVER PARTITION CONFLICT DO NOTHING MERGE"
CLAUSE_WORDS = "SELECT INSERT UPDATE DELETE FROM WHERE GROUP HAVING ORDER LIMIT OFFSET SET VALUES RETURNING"
ANCHOR_WORDS = "SELECT FROM JOIN ON WHERE GROUP HAVING ORDER LIMIT OFFSET UNION RETURNING SET VALUES INTO UPDATE INSERT DELETE WITH USING"

KEYWORD_SET = frozenset(KEYWORDS.split())
CLAUSE_SET = frozenset(CLAUSE_WORDS.split())
ANCHOR_SET = frozenset(ANCHOR_WORDS.split())
COMMAND_SET = frozenset("SELECT INSERT UPDATE DELETE MERGE WITH".split())
NOT_ALIAS_SET = frozenset(
    "ON USING WHERE JOIN INNER LEFT RIGHT FULL CROSS NATURAL OUTER GROUP ORDER HAVING LIMIT "
    "OFFSET UNION INTERSECT EXCEPT RETURNING SET WINDOW FOR LATERAL FETCH WITH TABLESAMPLE "
    "AND OR VALUES".split()
)

PROPERTIES = ("keyword_case", "indent", "clause_per_line", "comma", "alias_as")
DEFAULT_STYLE = {
    "keyword_case": "upper",
    "indent": "2 spaces",
    "clause_per_line": True,
    "comma": "trailing",
    "alias_as": True,
}

EXTRACTOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extract.py")

DOLLAR_QUOTE = re.compile(r"\$(?:[^\W\d]\w*)?\$")
WORD = re.compile(r"[\w$]+")
NAME = r"[^\W\d]\w*"
TABLE = re.compile(r"(?<![\w$.])(?:FROM|JOIN)\s+" + NAME + r"(?:\." + NAME + r")*", re.I)
ALIAS_WORD = re.compile(r"\s+(" + NAME + ")")
RANGE = re.compile(r"(\d+)-(\d+)")


class UsageError(Exception):
    pass


# --- masking -------------------------------------------------------------


def _blank(span, marker):
    """`marker` then spaces, as long as `span`; line breaks stay."""
    out = []
    first = True
    for char in span:
        if char in "\r\n":
            out.append(char)
        elif first:
            out.append(marker)
            first = False
        else:
            out.append(" ")
    return "".join(out)


def _quoted_end(text, start, backslash):
    """Index after the quote that closes the quoted text whose opening quote is at `start`."""
    quote = text[start]
    index = start + 1
    while index < len(text):
        if backslash and text[index] == "\\":
            index += 2
        elif text[index] == quote:
            if text[index + 1:index + 2] == quote:
                index += 2
            else:
                return index + 1
        else:
            index += 1
    return len(text)


def _is_word_char(char):
    return char.isalnum() or char in "_$"


def _mask_interpolations(text, interpolations):
    """Step 1: the interpolations. Returns the text and the start of each one (None if not found)."""
    parts = []
    offsets = []
    position = 0
    for item in interpolations:
        pattern = re.compile(r"\$\{\s*" + re.escape(item["expression"]) + r"\s*\}")
        match = pattern.search(text, position)
        if match is None:
            offsets.append(None)
            continue
        marker = "q" if item["position"] == "value" else " "
        parts.append(text[position:match.start()])
        parts.append(_blank(match.group(), marker))
        offsets.append(match.start())
        position = match.end()
    parts.append(text[position:])
    return "".join(parts), offsets


def _mask_syntax(text):
    """Step 2: comments, strings and quoted identifiers."""
    out = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        after_word = index > 0 and _is_word_char(text[index - 1])
        if text.startswith("--", index):
            end = text.find("\n", index)
            end = length if end < 0 else end
            out.append(" " * (end - index))
            index = end
        elif text.startswith("/*", index):
            depth = 1
            end = index + 2
            while end < length and depth:
                if text.startswith("/*", end):
                    depth += 1
                    end += 2
                elif text.startswith("*/", end):
                    depth -= 1
                    end += 2
                else:
                    end += 1
            out.append(_blank(text[index:end], " "))
            index = end
        elif char == "'":
            end = _quoted_end(text, index, False)
            out.append(_blank(text[index:end], "0"))
            index = end
        elif char in "eE" and text[index + 1:index + 2] == "'" and not after_word:
            end = _quoted_end(text, index + 1, True)
            out.append(_blank(text[index:end], "0"))
            index = end
        elif char == '"':
            end = _quoted_end(text, index, False)
            out.append(_blank(text[index:end], "q"))
            index = end
        elif char == "$" and not after_word and DOLLAR_QUOTE.match(text, index):
            tag = DOLLAR_QUOTE.match(text, index).group()
            close = text.find(tag, index + len(tag))
            end = length if close < 0 else close + len(tag)
            out.append(_blank(text[index:end], "0"))
            index = end
        elif _is_word_char(char):
            end = index
            while end < length and _is_word_char(text[end]):
                end += 1
            out.append(text[index:end])
            index = end
        else:
            out.append(char)
            index += 1
    return "".join(out)


def mask(statement):
    """The masked text of a statement and the offset of each interpolation in it."""
    text, offsets = _mask_interpolations(statement["text"], statement["interpolations"])
    return _mask_syntax(text), offsets


def words(masked):
    """The words of a masked text as (word, start) pairs. A word right after a `.` is left out."""
    found = []
    for match in WORD.finditer(masked):
        word = match.group()
        if word[0].isdigit():
            continue
        if match.start() > 0 and masked[match.start() - 1] == ".":
            continue
        found.append((word, match.start()))
    return found


def is_counted(statement):
    """A statement that is not a nested fragment and that holds a command word."""
    if statement["parent"] is not None:
        return False
    return any(word.upper() in COMMAND_SET for word, _ in words(mask(statement)[0]))


def interpolation_clauses(statement):
    """For grader A: `(expression, clause)` of each interpolation, in order."""
    masked, offsets = mask(statement)
    found = [(word.upper(), start) for word, start in words(masked) if word.upper() in ANCHOR_SET]
    result = []
    for item, offset in zip(statement["interpolations"], offsets):
        clause = ""
        if offset is not None:
            for word, start in found:
                if start < offset:
                    clause = word
        result.append((item["expression"], clause))
    return result


# --- votes ---------------------------------------------------------------


def _vote_keyword_case(found):
    upper = sum(1 for word, _ in found if word.upper() in KEYWORD_SET and word == word.upper())
    lower = sum(1 for word, _ in found if word.upper() in KEYWORD_SET and word == word.lower())
    if upper == lower:
        return None
    return "upper" if upper > lower else "lower"


def _leading_width(line):
    return len(line) - len(line.lstrip(" \t"))


def _vote_indent(text, form):
    lines = text.split("\n")
    if form == "js":
        dropped = bool(lines) and lines[0].strip() == ""
        if dropped:
            lines = lines[1:]
        if len(lines) < 2:
            return None
        sample = lines if dropped else lines[1:]
        widths = [_leading_width(line) for line in sample if line.strip()]
        base = min(widths) if widths else 0
    else:
        if len(lines) < 2:
            return None
        base = 0
    indented = [line for line in lines if line.strip() and _leading_width(line) > base]
    if not indented:
        return None
    if any(line.startswith("\t") for line in indented):
        return "tab"
    return "%d spaces" % min(_leading_width(line) - base for line in indented)


def _depths(masked):
    depths = []
    depth = 0
    for char in masked:
        if char == ")":
            depth = max(0, depth - 1)
        depths.append(depth)
        if char == "(":
            depth += 1
    return depths


def _vote_clause_per_line(masked, found):
    depths = _depths(masked)
    alone = []
    previous = ""
    for word, start in found:
        upper = word.upper()
        is_clause = depths[start] == 0 and upper in CLAUSE_SET
        if upper == "FROM" and previous in ("DISTINCT", "DELETE"):
            is_clause = False
        if upper == "UPDATE" and previous in ("FOR", "DO"):
            is_clause = False
        if is_clause:
            line_start = masked.rfind("\n", 0, start) + 1
            alone.append(masked[line_start:start].strip() == "")
        previous = upper
    if len(alone) < 2:
        return None
    return all(alone)


def _vote_comma(masked):
    lines = masked.split("\n")
    trailing = sum(1 for line in lines if line.rstrip().endswith(","))
    leading = sum(1 for line in lines if line.lstrip().startswith(","))
    if trailing == leading:
        return None
    return "trailing" if trailing > leading else "leading"


def _vote_alias_as(masked):
    explicit = 0
    implicit = 0
    for table in TABLE.finditer(masked):
        match = ALIAS_WORD.match(masked, table.end())
        if match is None:
            continue
        word = match.group(1).upper()
        if word == "AS":
            if ALIAS_WORD.match(masked, match.end()):
                explicit += 1
        elif word not in NOT_ALIAS_SET:
            implicit += 1
    if explicit == implicit:
        return None
    return explicit > implicit


def votes(statement, form):
    """The vote of one statement for each property: a value, or None for no vote."""
    masked, _ = mask(statement)
    found = words(masked)
    return {
        "keyword_case": _vote_keyword_case(found),
        "indent": _vote_indent(statement["text"], form),
        "clause_per_line": _vote_clause_per_line(masked, found),
        "comma": _vote_comma(masked),
        "alias_as": _vote_alias_as(masked),
    }


# --- shared command helpers ------------------------------------------------


def run_extractor(path, tags=None):
    """Run `extract.py`. Returns (data, None), or (None, message) when the extraction fails."""
    command = [sys.executable, EXTRACTOR, path]
    if tags is not None:
        command += ["--tags", tags]
    result = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL
    )
    if result.returncode == 2:
        lines = result.stderr.strip().splitlines()
        return None, lines[0].strip() if lines else "usage error"
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return None, "the extractor printed no JSON"
    if data.get("error"):
        return None, data["error"]["message"]
    return data, None


def read_lines(path):
    """The lines of a file as bytes, each with its line end (`\\n`)."""
    with open(path, "rb") as handle:
        return re.findall(rb"[^\n]*\n|[^\n]+", handle.read())


def parse_range(value, line_count=None):
    """A `<start>-<end>` value as (start, end). With a line count, the end is checked against it."""
    match = RANGE.fullmatch(value)
    if match is None:
        raise UsageError("bad range %r: use <start>-<end>" % value)
    start, end = int(match.group(1)), int(match.group(2))
    if start < 1 or start > end or (line_count is not None and end > line_count):
        raise UsageError("range %s is not a range of lines of the file" % value)
    return start, end


def parse_arguments(argv, positional_count, single=(), many=()):
    """Split a command line into positional arguments and option values.

    Returns (positional, options) where options maps each given option to its
    list of values. Raises UsageError for a wrong number of positional
    arguments, an unknown option, an option with no value, or a repeated
    option that is not in `many`.
    """
    positional = []
    options = {}
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument.startswith("-") and len(argument) > 1:
            if argument not in single and argument not in many:
                raise UsageError("unknown option: " + argument)
            if argument in options and argument not in many:
                raise UsageError(argument + " is given twice")
            if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
                raise UsageError(argument + " needs a value")
            options.setdefault(argument, []).append(argv[index + 1])
            index += 2
        else:
            positional.append(argument)
            index += 1
    if len(positional) != positional_count:
        raise UsageError("expected %d file arguments, got %d" % (positional_count, len(positional)))
    return positional, options


def finish(letter, failures):
    """Print the report of a grader and return its exit code."""
    print(json.dumps({"grader": letter, "pass": not failures, "failures": failures}, indent=2))
    return 1 if failures else 0


def usage_failure(error):
    """Print a usage error (one line on stderr) and return exit code 2."""
    sys.stderr.write(str(error).replace("\n", " ") + "\n")
    return 2
