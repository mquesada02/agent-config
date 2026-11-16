#!/usr/bin/env python3
"""Find the SQL of a source file and print one JSON object.

Usage: python3 extract.py <file> [--tags <t1,t2,...>] [--receivers <r1,r2,...>]

The file form comes from the extension: `.sql` (statements) or a JavaScript or
TypeScript extension (postgres.js tagged templates and `pg` statements). For
each template or statement the output has its source (`sql`, `template` or
`pg`), its line range, its tag, its text and its interpolations, each with a
position (`value`, `fragment` or `keyword`). A `pg` statement is the SQL that
the first argument of the `query()` call of a `pg` receiver gives: a string, a
template, a `+` chain, the `text` of a config object, the first argument of
`new Query`, `new Cursor` or `new QueryStream`, or a name that is followed to a
same-file `const`. The SQL may have a part that is not a literal: the statement
is then `dynamic`. A `pg` statement also has a `pg` object (see the spec of the
`pg` source form). The output lists the tags that the file shows (tag
detection), the `pg` receivers that it shows (receiver detection) and
`not_followed`, the calls whose first argument gives no statement, each with its
line. The given receivers are added to the detected ones; they never replace
them.

Exit code: 0 when the file was read, 1 when "error" is set (the JSON is still
printed), 2 for a usage error (one line on stderr, nothing on stdout).
"""
import bisect
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sql_guard  # noqa: E402

JS_EXTENSIONS = (".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx")
JSX_EXTENSIONS = (".jsx", ".tsx")
SQL_EXTENSION = ".sql"

REGEX_KEYWORDS = frozenset(
    "return typeof instanceof in of new delete void throw case do else yield await".split()
)
CLASS_MODIFIERS = frozenset(
    "public private protected readonly static declare override abstract".split()
)
MAX_TYPE_ARGUMENT_TOKENS = 200
MAX_TYPE_ANNOTATION_TOKENS = 60

VALUE_WORDS = frozenset(
    (
        "SELECT DISTINCT FROM JOIN ON USING WHERE AND OR NOT IN EXISTS ANY ALL BY SET VALUES "
        "INTO UPDATE LIMIT OFFSET RETURNING CASE WHEN THEN ELSE IS LIKE BETWEEN AS"
    ).split()
)
CLAUSE_START_WORDS = frozenset(
    (
        "WHERE AND OR JOIN INNER LEFT RIGHT FULL CROSS NATURAL GROUP ORDER HAVING LIMIT OFFSET "
        "UNION RETURNING"
    ).split()
)
NOT_NAME_WORDS = VALUE_WORDS | CLAUSE_START_WORDS | {"CONFLICT"}

NUMBER = re.compile(r"(?:\d|\.\d)[\w.]*")
TEMPLATE_SPECIAL = re.compile(r"[\\`$]")
JSX_TEXT_SPECIAL = re.compile(r"[<{]")
# The rule of the TypeScript parser for `.tsx`: after `<`, an optional `const` and a name, a `,`,
# an `=` that is not `=>`, or `extends` followed by something other than `=`, `>` or `/` makes a
# generic arrow function. Every other `<` before a name starts JSX.
GENERIC_ARROW = re.compile(
    r"<\s*(?:const\s+)?(?:[^\W\d]|\$)[\w$]*\s*(?:,|=(?!>)|extends(?![\w$])\s*[^=>/\s])"
)
DOLLAR_QUOTE = re.compile(r"\$(?:[^\W\d]\w*)?\$")
PARAMETER = re.compile(r"\$\d+")
SQL_OPERATOR_CHARS = frozenset("+-*/<>=~!@#%^&|?:\\")


class ExtractError(Exception):
    def __init__(self, message, line):
        super().__init__(message)
        self.message = message
        self.line = line


class UsageError(Exception):
    pass


def is_name(text):
    return bool(text) and text.replace("$", "_").isidentifier()


def name_end(text, start):
    """End of the name that starts at `start` (the is_name rule), or `start` when none starts there."""
    if text[start] != "$" and not text[start].isidentifier():
        return start
    end = start + 1
    while end < len(text) and (text[end] == "$" or ("a" + text[end]).isidentifier()):
        end += 1
    return end


def is_tag_chain(text):
    return bool(text) and all(is_name(part) for part in text.split("."))


class Source:
    def __init__(self, text):
        self.text = text
        self.newlines = [i for i, c in enumerate(text) if c == "\n"]

    def line(self, offset):
        return bisect.bisect_left(self.newlines, offset) + 1

    def column(self, offset):
        index = bisect.bisect_left(self.newlines, offset)
        start = self.newlines[index - 1] + 1 if index else 0
        return offset - start + 1


# ---------------------------------------------------------------- SQL scan


class SqlLexer:
    """Tokenize SQL text. Interpolations are atoms (or flagged literal ones)."""

    def __init__(self, text, find_interpolation):
        self.text = text
        self.find = find_interpolation  # offset -> end offset or None
        self.tokens = []  # (kind, text, start, end)
        self.interpolations = []  # {"start", "end", "literal"}

    def mark(self, start, end, literal):
        self.interpolations.append({"start": start, "end": end, "literal": literal})
        return len(self.interpolations) - 1

    def literal_interpolation(self, j):
        end = self.find(j)
        if end is None:
            return None
        self.mark(j, end, True)
        return end

    def run(self):
        text, n = self.text, len(self.text)
        i = 0
        while i < n:
            c = text[i]
            if c.isspace():
                i += 1
                continue
            end = self.find(i)
            if end is not None:
                index = self.mark(i, end, False)
                self.tokens.append(("interp", index, i, end))
                i = end
                continue
            if text.startswith("--", i):
                i = self.line_comment(i)
            elif text.startswith("/*", i):
                i = self.block_comment(i)
            elif c == "'":
                i = self.string(i)
            elif c == '"':
                i = self.quoted_identifier(i)
            elif c == "$" and DOLLAR_QUOTE.match(text, i):
                i = self.dollar_quote(i)
            elif c == "$" and PARAMETER.match(text, i):
                m = PARAMETER.match(text, i)
                self.tokens.append(("param", m.group(0), i, m.end()))
                i = m.end()
            elif c.isdecimal() or (c == "." and text[i + 1 : i + 2].isdecimal()):
                m = NUMBER.match(text, i)
                self.tokens.append(("num", m.group(0), i, m.end()))
                i = m.end()
            elif c.isidentifier() or (c == "$" and text[i + 1 : i + 2] != "{"):
                i = self.word(i)
            elif c in SQL_OPERATOR_CHARS:
                i = self.operator(i)
            elif c in "(),.;[]":
                self.tokens.append(("punct", c, i, i + 1))
                i += 1
            else:
                self.tokens.append(("other", c, i, i + 1))
                i += 1
        return self.tokens, self.interpolations

    def line_comment(self, i):
        text, n = self.text, len(self.text)
        j = i + 2
        while j < n and text[j] != "\n":
            end = self.literal_interpolation(j)
            j = end if end is not None else j + 1
        return j

    def block_comment(self, i):
        text, n = self.text, len(self.text)
        depth, j = 1, i + 2
        while j < n and depth:
            end = self.literal_interpolation(j)
            if end is not None:
                j = end
            elif text.startswith("/*", j):
                depth, j = depth + 1, j + 2
            elif text.startswith("*/", j):
                depth, j = depth - 1, j + 2
            else:
                j += 1
        return min(j, n)

    def string(self, i):
        text, n = self.text, len(self.text)
        last = self.tokens[-1] if self.tokens else None
        escapes = bool(last and last[0] == "word" and last[1] in ("E", "e") and last[3] == i)
        j = i + 1
        while j < n:
            end = self.literal_interpolation(j)
            if end is not None:
                j = end
                continue
            c = text[j]
            if c == "'":
                if text[j + 1 : j + 2] == "'":
                    j += 2
                    continue
                j += 1
                break
            j += 2 if escapes and c == "\\" else 1
        j = min(j, n)
        self.tokens.append(("str", text[i:j], i, j))
        return j

    def quoted_identifier(self, i):
        text, n = self.text, len(self.text)
        j = i + 1
        while j < n:
            end = self.literal_interpolation(j)
            if end is not None:
                j = end
                continue
            if text[j] == '"':
                if text[j + 1 : j + 2] == '"':
                    j += 2
                    continue
                j += 1
                break
            j += 1
        j = min(j, n)
        self.tokens.append(("qid", text[i:j], i, j))
        return j

    def dollar_quote(self, i):
        text, n = self.text, len(self.text)
        delimiter = DOLLAR_QUOTE.match(text, i).group(0)
        j = i + len(delimiter)
        while j < n:
            end = self.literal_interpolation(j)
            if end is not None:
                j = end
            elif text.startswith(delimiter, j):
                j += len(delimiter)
                break
            else:
                j += 1
        j = min(j, n)
        self.tokens.append(("str", text[i:j], i, j))
        return j

    def word(self, i):
        text, n = self.text, len(self.text)
        j = i
        while j < n and (("a" + text[j]).isidentifier() or (text[j] == "$" and text[j + 1 : j + 2] != "{")):
            j += 1
        self.tokens.append(("word", text[i:j], i, j))
        return j

    def operator(self, i):
        text, n = self.text, len(self.text)
        j = i
        while j < n and text[j] in SQL_OPERATOR_CHARS:
            if j > i and (text.startswith("--", j) or text.startswith("/*", j)):
                break
            j += 1
        self.tokens.append(("op", text[i:j], i, j))
        return j


def word_of(token):
    return token[1].upper() if token and token[0] == "word" else None


def is_value_before(tokens, k):
    before = tokens[k - 1] if k > 0 else None
    if before is None:
        return False
    kind, text = before[0], before[1]
    if kind == "op":
        if text == "*":
            return not star_is_name(tokens, k - 1)
        return True
    if kind == "punct":
        return text in ("(", ",")
    return word_of(before) in VALUE_WORDS


def star_is_name(tokens, index):
    previous = tokens[index - 1] if index > 0 else None
    if previous is None:
        return False
    return word_of(previous) == "SELECT" or (previous[0] == "punct" and previous[1] in (",", "."))


def is_complete(tokens, k):
    before = tokens[k - 1] if k > 0 else None
    if before is None:
        return False
    kind, text = before[0], before[1]
    if kind in ("qid", "str", "num", "param", "interp"):
        return True
    if kind == "punct":
        return text == ")"
    if kind == "op":
        return text == "*" and star_is_name(tokens, k - 1)
    if kind == "word":
        return text.upper() not in NOT_NAME_WORDS
    return False


def starts_clause_or_ends(tokens, k):
    after = tokens[k + 1] if k + 1 < len(tokens) else None
    if after is None:
        return True
    if after[0] == "punct" and after[1] == ")":
        return True
    word = word_of(after)
    if word in CLAUSE_START_WORDS:
        return True
    if word == "ON":
        return word_of(tokens[k + 2] if k + 2 < len(tokens) else None) == "CONFLICT"
    return False


def classify(tokens, k):
    if is_value_before(tokens, k):
        return "value"
    if is_complete(tokens, k) and starts_clause_or_ends(tokens, k):
        return "fragment"
    return "keyword"


def assign_positions(tokens, interpolations):
    """Set "position" on each interpolation that sits in `tokens` (one statement)."""
    for k, token in enumerate(tokens):
        if token[0] == "interp":
            interpolations[token[1]]["position"] = classify(tokens, k)


# ---------------------------------------------------------------- sql form


def sql_placeholder_finder(source):
    text = source.text
    n = len(text)

    def find(i):
        if not text.startswith("${", i):
            return None
        depth, k = 1, i + 2
        while k < n:
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
                if depth == 0:
                    return k + 1
            k += 1
        raise ExtractError("unterminated ${ placeholder", source.line(i))

    return find


def extract_sql_file(source):
    tokens, interpolations = SqlLexer(source.text, sql_placeholder_finder(source)).run()
    groups, current = [], []
    for token in tokens:
        if token[0] == "punct" and token[1] == ";":
            if current:
                groups.append(current)
            current = []
        else:
            current.append(token)
    if current:
        groups.append(current)
    statements = []
    # The lexer appends interpolations in source order, so each statement owns one slice.
    starts = [interpolation["start"] for interpolation in interpolations]
    for group in groups:
        start, end = group[0][2], group[-1][3]
        assign_positions(group, interpolations)
        own = [
            interpolation_record(source, interpolation, interpolation.get("position", "keyword"))
            for interpolation in interpolations[bisect.bisect_left(starts, start) : bisect.bisect_left(starts, end)]
        ]
        statements.append(
            {
                "source": "sql",
                "tag": None,
                "start_line": source.line(start),
                "end_line": source.line(end - 1),
                "text": source.text[start:end],
                "parent": None,
                "interpolations": own,
            }
        )
    return statements


def interpolation_record(source, interpolation, position):
    start = interpolation["start"]
    end = interpolation["end"]
    return {
        "line": source.line(start),
        "column": source.column(start),
        "expression": source.text[start + 2 : end - 1].strip(),
        "position": position,
    }


# ----------------------------------------------------------------- js form


class Template:
    def __init__(self, start, enclosing, token_index):
        self.start = start
        self.end = None
        self.enclosing = enclosing
        self.token_index = token_index
        self.interpolations = []  # {"start", "end"}
        self.tag = None


def tokenize_js(source, jsx=False, tsx=False):
    """Return (tokens, templates). Raises ExtractError on an unterminated construct.

    With `jsx`, a JSX element is scanned as one unit (its text and attribute strings make no
    JavaScript token). With `tsx`, the TypeScript generic arrow forms are not JSX.
    """
    text, n = source.text, len(source.text)
    tokens, templates = [], []
    # ["tpl", Template], ["expr", Template, depth], ["jsx", enclosing, state, open element starts]
    # or ["jexpr", enclosing, depth]. `enclosing` is the Template that holds the frame, or None.
    stack = []
    i = 0
    while i < n:
        top = stack[-1] if stack else None
        if top is not None and top[0] == "tpl":
            record = top[1]
            while True:
                m = TEMPLATE_SPECIAL.search(text, i)
                if m is None:
                    i = n
                    break
                j = m.start()
                c = text[j]
                if c == "\\":
                    i = j + 2
                elif c == "`":
                    record.end = j
                    tokens.append(("tpl_end", "`", j, j + 1))
                    stack.pop()
                    i = j + 1
                    break
                elif text.startswith("${", j):
                    record.interpolations.append({"start": j, "end": None})
                    tokens.append(("ibeg", "${", j, j + 2))
                    stack.append(["expr", record, 0])
                    i = j + 2
                    break
                else:
                    i = j + 1
            continue
        if top is not None and top[0] == "jsx":
            i = scan_jsx(text, stack, tokens, i)
            continue
        c = text[i]
        if c.isspace():
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            if j < 0:
                if stack:
                    raise unterminated_frame(source, stack)
                raise ExtractError("unterminated block comment", source.line(i))
            i = j + 2
        elif c in "'\"":
            j = i + 1
            while j < n:
                d = text[j]
                if d == "\\":
                    j += 3 if text.startswith("\r\n", j + 1) else 2
                    continue
                if d == c:
                    j += 1
                    break
                if d == "\n":
                    break
                j += 1
            j = min(j, n)
            tokens.append(("str", text[i:j], i, j))
            i = j
        elif c == "`":
            record = Template(i, stack[-1][1] if stack else None, len(tokens))
            templates.append(record)
            tokens.append(("tpl", "`", i, i + 1))
            stack.append(["tpl", record])
            i += 1
        elif jsx and c == "<" and jsx_starts(text, i, tokens, tsx):
            stack.append(["jsx", stack[-1][1] if stack else None, "tag", [i]])
            i += 1
        elif c == "/" and slash_starts_regex(tokens):
            i = scan_regex(text, i, tokens)
        elif (end := name_end(text, i)) > i:
            tokens.append(("name", text[i:end], i, end))
            i = end
        elif c.isdecimal() or (c == "." and text[i + 1 : i + 2].isdecimal()):
            m = NUMBER.match(text, i)
            tokens.append(("num", m.group(0), i, m.end()))
            i = m.end()
        else:
            if text.startswith("=>", i):
                tokens.append(("p", "=>", i, i + 2))
                i += 2
            elif text.startswith("...", i):
                tokens.append(("p", "...", i, i + 3))
                i += 3
            elif text.startswith("?.", i) and not text[i + 2 : i + 3].isdecimal():
                tokens.append(("p", "?.", i, i + 2))
                i += 2
            else:
                if c == "{" and stack and stack[-1][0] in ("expr", "jexpr"):
                    stack[-1][2] += 1
                elif c == "}" and stack and stack[-1][0] in ("expr", "jexpr"):
                    if stack[-1][2] == 0:
                        if stack[-1][0] == "expr":
                            record = stack[-1][1]
                            record.interpolations[-1]["end"] = i + 1
                            tokens.append(("iend", "}", i, i + 1))
                        else:
                            tokens.append(("p", "}", i, i + 1))
                        stack.pop()
                        i += 1
                        continue
                    stack[-1][2] -= 1
                tokens.append(("p", c, i, i + 1))
                i += 1
    if stack:
        raise unterminated_frame(source, stack)
    return tokens, templates


def unterminated_frame(source, stack):
    """The error for the frames that are still open at the end of the file: the innermost decides."""
    if stack[-1][0] in ("tpl", "expr"):
        first = next(frame for frame in stack if frame[0] in ("tpl", "expr"))
        return ExtractError("unterminated template literal", source.line(first[1].start))
    frame = next(frame for frame in reversed(stack) if frame[0] == "jsx")
    return ExtractError("unterminated JSX element", source.line(frame[3][-1]))


def jsx_starts(text, i, tokens, tsx):
    """True when the `<` at `i` starts a JSX element (or a fragment), not a comparison or a type."""
    if not (slash_starts_regex(tokens) or after_export_default(tokens)):
        return False
    if tokens and punct(tokens[-1], "<"):
        return False
    if after_postfix_operator(tokens):
        return False
    if i + 1 >= len(text) or (text[i + 1] != ">" and name_end(text, i + 1) == i + 1):
        return False
    return not (tsx and GENERIC_ARROW.match(text, i))


def after_export_default(tokens):
    """The words `export default` right before an element or a regex: `export default <p/>`."""
    return len(tokens) > 1 and name_is(tokens[-1], "default") and name_is(tokens[-2], "export")


def after_postfix_operator(tokens):
    """The last two tokens are a postfix `++` or `--` (two joined punctuation tokens after a value).

    A `<` or a `/` after it is a comparison or a division."""
    if len(tokens) < 3:
        return False
    first, second = tokens[-2], tokens[-1]
    return (
        first[0] == "p"
        and second[0] == "p"
        and first[1] == second[1]
        and first[1] in ("+", "-")
        and first[3] == second[2]
        and not regex_can_follow(tokens[-3])
    )


def scan_jsx(text, stack, tokens, i):
    """Advance the JSX frame on top of `stack` from `i`; return the new position."""
    frame = stack[-1]
    n = len(text)
    opens = frame[3]
    if frame[2] == "text":
        m = JSX_TEXT_SPECIAL.search(text, i)
        if m is None:
            return n
        j = m.start()
        if text[j] == "{":
            return open_container(stack, tokens, frame, j)
        if text.startswith("</", j):
            k = text.find(">", j)
            if k < 0:
                return n
            opens.pop()
            return close_element(stack, tokens, frame, k + 1)
        opens.append(j)
        frame[2] = "tag"
        return j + 1
    while i < n:
        c = text[i]
        if c in "\"'":
            k = text.find(c, i + 1)
            if k < 0:
                return n
            i = k + 1
        elif c == "{":
            return open_container(stack, tokens, frame, i)
        elif c == ">":
            frame[2] = "text"
            return i + 1
        elif text.startswith("/>", i):
            opens.pop()
            return close_element(stack, tokens, frame, i + 2)
        else:
            i += 1
    return n


def open_container(stack, tokens, frame, i):
    stack.append(["jexpr", frame[1], 0])
    tokens.append(("p", "{", i, i + 1))
    return i + 1


def close_element(stack, tokens, frame, end):
    """An element ended at `end`. When no element is open, the JSX frame ends as one value token."""
    if frame[3]:
        frame[2] = "text"
    else:
        stack.pop()
        tokens.append(("jsx", "", end, end))
    return end


def slash_starts_regex(tokens):
    if not tokens:
        return True
    if after_export_default(tokens):
        return True
    if after_postfix_operator(tokens):
        return False
    return regex_can_follow(tokens[-1])


def regex_can_follow(token):
    """True when a `/` right after this one token starts a regex."""
    kind, text = token[0], token[1]
    if kind in ("num", "str", "regex", "tpl_end", "jsx"):
        return False
    if kind == "name":
        return text in REGEX_KEYWORDS
    if kind == "p":
        return text not in (")", "]", "}")
    return True


def scan_regex(text, i, tokens):
    n = len(text)
    j, in_class = i + 1, False
    while j < n and text[j] != "\n":
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if in_class:
            if c == "]":
                in_class = False
        elif c == "[":
            in_class = True
        elif c == "/":
            j += 1
            break
        j += 1
    j = min(j, n)
    while j < n and (text[j].isalnum() or text[j] in "_$"):
        j += 1
    tokens.append(("regex", text[i:j], i, j))
    return j


def tag_chain(tokens, index):
    """The tag chain right before the template token at `index`, or None."""
    j = index - 1
    if j >= 0 and tokens[j][0] == "p" and tokens[j][1] == ">":
        depth, count = 0, 0
        while j >= 0 and count < MAX_TYPE_ARGUMENT_TOKENS:
            token = tokens[j]
            if token[0] == "p" and token[1] == ">":
                depth += 1
            elif token[0] == "p" and token[1] == "<":
                depth -= 1
                if depth == 0:
                    break
            j -= 1
            count += 1
        if j < 0 or depth != 0 or count >= MAX_TYPE_ARGUMENT_TOKENS:
            return None
        j -= 1
    return chain_ending_at(tokens, j)


def chain_ending_at(tokens, j):
    if j < 0 or tokens[j][0] != "name":
        return None
    parts = [tokens[j][1]]
    k = j - 1
    while k >= 1 and tokens[k][0] == "p" and tokens[k][1] == "." and tokens[k - 1][0] == "name":
        parts.insert(0, tokens[k - 1][1])
        k -= 2
    if k >= 0 and tokens[k][0] == "p" and tokens[k][1] in (".", "?."):
        return None
    return ".".join(parts), k + 1


def punct(token, text):
    return token[0] == "p" and token[1] == text


def name_is(token, text):
    return token[0] == "name" and token[1] == text


class Detector:
    def __init__(self, tokens, given_tags):
        self.tokens = tokens
        self.given = set(given_tags)
        self.factory_names = {}  # name -> offset
        self.tags = {}  # tag -> first offset
        self.in_class = self.class_flags()

    def at(self, i):
        return self.tokens[i] if 0 <= i < len(self.tokens) else ("eof", "", -1, -1)

    def class_flags(self):
        flags, stack, pending, depth = [], [], False, 0
        for k, token in enumerate(self.tokens):
            flags.append(bool(stack) and stack[-1] == "class")
            if name_is(token, "class"):
                # A member name (x.class), an object key or shorthand (class:, class,, class}),
                # a method name (class() {}) and the like are not the class keyword.
                before, after = self.at(k - 1), self.at(k + 1)
                member = any(punct(before, p) for p in (".", "?."))
                plain_name = any(punct(after, p) for p in (":", ",", "}", "=", "(", ")", ";", "."))
                if not member and not plain_name:
                    pending, depth = True, 0
            # In the header, a brace inside <...>, (...) or [...] is not the class body.
            elif pending and any(punct(token, p) for p in ("<", "(", "[")):
                depth += 1
            elif pending and depth and any(punct(token, p) for p in (">", ")", "]")):
                depth -= 1
            elif punct(token, "{"):
                is_body = pending and depth == 0
                stack.append("class" if is_body else "block")
                if is_body:
                    pending = False
            # A method parameter list or a call in the class body is not the class body.
            elif punct(token, "(") and stack and stack[-1] in ("class", "parens"):
                stack.append("parens")
            elif punct(token, ")") and stack and stack[-1] == "parens":
                stack.pop()
            elif punct(token, "}") and stack:
                stack.pop()
        return flags

    def add_tag(self, tag, offset):
        if tag not in self.tags or offset < self.tags[tag]:
            self.tags[tag] = offset

    def run(self):
        self.find_factories()
        self.find_variables()
        self.find_transactions()
        ordered = sorted(self.tags, key=lambda tag: self.tags[tag])
        names = sorted(self.factory_names, key=lambda name: self.factory_names[name])
        return ordered, names

    # form 1
    def find_factories(self):
        t = self.tokens
        for i, token in enumerate(t):
            if name_is(token, "import") and not (punct(self.at(i + 1), "(") or punct(self.at(i + 1), ".")):
                self.find_import(i)
            elif token[0] == "name" and token[1] in ("const", "let", "var"):
                self.find_require(i)

    def find_import(self, i):
        t = self.tokens
        j = i + 1
        if name_is(self.at(j), "type"):
            nxt = self.at(j + 1)
            if nxt[0] == "name" and nxt[1] != "from":
                return
        k = j
        while k < min(len(t) - 1, j + 80) and not punct(t[k], ";"):
            if name_is(t[k], "from") and t[k + 1][0] == "str":
                break
            k += 1
        else:
            return
        if not (k < len(t) - 1 and name_is(t[k], "from") and t[k + 1][0] == "str"):
            return
        if t[k + 1][1].strip("'\"") != "postgres":
            return
        segment = t[j:k]
        if segment and segment[0][0] == "name":
            self.factory_names.setdefault(segment[0][1], segment[0][2])
        for m in range(len(segment) - 2):
            if name_is(segment[m], "default") and name_is(segment[m + 1], "as") and segment[m + 2][0] == "name":
                self.factory_names.setdefault(segment[m + 2][1], segment[m + 2][2])

    def find_require(self, i):
        window = [self.at(i + d) for d in range(8)]
        if not (
            window[1][0] == "name"
            and punct(window[2], "=")
            and name_is(window[3], "require")
            and punct(window[4], "(")
            and window[5][0] == "str"
            and window[5][1].strip("'\"") == "postgres"
            and punct(window[6], ")")
        ):
            return
        if punct(window[7], "("):
            self.add_tag(window[1][1], window[1][2])
        else:
            self.factory_names.setdefault(window[1][1], window[1][2])

    # forms 2 and 3
    def factories(self):
        return set(self.factory_names) | {"postgres"}

    def find_variables(self):
        factories = self.factories()
        for i, token in enumerate(self.tokens):
            if token[0] != "name":
                continue
            if not self.assigned_from_factory(i, factories):
                continue
            bound = self.binding(i)
            if bound is not None:
                self.add_tag(*bound)

    def binding(self, i):
        """(name, offset) that the assignment of the name token `i` binds, or None.

        A name after `const`, `let` or `var`, a plain assignment, a member form after `.`, and
        a non-static class field (`this.NAME`) bind; an object key (`NAME:`) and a static field do not."""
        t = self.tokens
        token = t[i]
        previous = self.at(i - 1)
        if punct(previous, ":") and not self.is_clause_colon(i - 1):
            return None
        if previous[0] == "name" and previous[1] in ("const", "let", "var"):
            return token[1], token[2]
        if punct(previous, "."):
            found = chain_ending_at(t, i)
            return None if found is None else (found[0], t[found[1]][2])
        if self.in_class[i]:
            return None if self.is_static(i) else ("this." + token[1], token[2])
        return token[1], token[2]

    def declares_after_comma(self, i):
        """True when the comma before the name token `i` separates the declarators of a `const`, `let`
        or `var` or the parameters of a parameter list; false for an object literal or an array."""
        depth = 0
        for k in range(i - 1, -1, -1):
            token = self.tokens[k]
            if token[0] == "p" and token[1] in ")]}":
                depth += 1
            elif token[0] == "p" and token[1] in "([{":
                if depth == 0:
                    return token[1] == "("
                depth -= 1
            elif depth == 0 and token[0] == "name" and token[1] in ("const", "let", "var"):
                return True
            elif depth == 0 and punct(token, ";"):
                return False
        return False

    def is_clause_colon(self, c):
        """True when the colon at `c` ends a `case X:` or `default:` clause or a statement label,
        so that the name after it starts a statement; false for an object value or a type annotation."""
        label = self.at(c - 1)
        if name_is(label, "default") or name_is(self.at(c - 2), "case"):
            return True
        starts_statement = punct(self.at(c - 2), ";") or punct(self.at(c - 2), "}") or self.at(c - 2)[0] == "eof"
        return label[0] == "name" and starts_statement and not self.in_class[c - 1]

    def is_static(self, i):
        j = i - 1
        while j >= 0 and self.tokens[j][0] == "name" and self.tokens[j][1] in CLASS_MODIFIERS:
            if self.tokens[j][1] == "static":
                return True
            j -= 1
        return False

    def assigned_from_factory(self, i, factories):
        """NAME [: type] = [await] FACTORY( ... starting at the name token `i`."""

        def is_factory_call(j, awaited):
            callee = self.at(j)
            return callee[0] == "name" and callee[1] in factories and punct(self.at(j + 1), "(")

        return self.assigned_from(i, is_factory_call)

    def assigned_from(self, i, matches):
        """NAME [: type] = [await] ... starting at the name token `i`.

        `matches(j, awaited)` judges the value that starts at token `j` (after the `await`, if any)."""
        t = self.tokens
        j = i + 1
        if punct(self.at(j), ":"):
            # Only a declaration, a parameter or a class field has a type annotation: a case
            # clause, a statement label and the like have a colon but no annotation.
            before = self.at(i - 1)
            declared = (
                (self.in_class[i] and not punct(before, "?"))
                or punct(before, "(")
                or (punct(before, ",") and self.declares_after_comma(i))
                or (before[0] == "name" and before[1] in ("const", "let", "var") + tuple(CLASS_MODIFIERS))
            )
            if not declared:
                return False
            depth, count = 0, 0
            j += 1
            while j < len(t) and count < MAX_TYPE_ANNOTATION_TOKENS:
                token = t[j]
                if token[0] == "p":
                    if token[1] in "<([{":
                        depth += 1
                    elif token[1] in ">)]}":
                        depth -= 1
                        if depth < 0:
                            return False
                    elif token[1] == ";" or (token[1] == "," and depth <= 0):
                        return False
                    elif token[1] == "=" and depth <= 0:
                        break
                j += 1
                count += 1
            else:
                return False
        if not punct(self.at(j), "="):
            return False
        nxt = self.at(j + 1)
        if punct(nxt, "="):
            return False
        j += 1
        awaited = name_is(self.at(j), "await")
        if awaited:
            j += 1
        return matches(j, awaited)

    # form 4
    def find_transactions(self):
        while True:
            before = len(self.tags)
            known = set(self.tags) | self.given
            t = self.tokens
            for i in range(1, len(t) - 2):
                if not (punct(t[i], ".") and name_is(t[i + 1], "begin") and punct(t[i + 2], "(")):
                    continue
                receiver = chain_ending_at(t, i - 1)
                if receiver is None or receiver[0] not in known:
                    continue
                parameter = self.callback_parameter(i + 3)
                if parameter is not None:
                    self.add_tag(parameter[1], parameter[2])
            if len(self.tags) == before:
                return

    def callback_parameter(self, j):
        if self.at(j)[0] == "str" and punct(self.at(j + 1), ","):
            j += 2
        if name_is(self.at(j), "async"):
            j += 1
        first = self.at(j)
        if first[0] == "name" and first[1] != "function" and punct(self.at(j + 1), "=>"):
            return first
        if punct(first, "("):
            parameter = self.at(j + 1)
            if parameter[0] == "name" and self.arrow_follows(j):
                return parameter
            return None
        if name_is(first, "function"):
            k = j + 1
            if self.at(k)[0] == "name":
                k += 1
            if punct(self.at(k), "(") and self.at(k + 1)[0] == "name":
                return self.at(k + 1)
        return None

    def arrow_follows(self, j):
        depth = 0
        for k in range(j, len(self.tokens)):
            token = self.tokens[k]
            if punct(token, "("):
                depth += 1
            elif punct(token, ")"):
                depth -= 1
                if depth == 0:
                    following = self.at(k + 1)
                    return punct(following, "=>") or punct(following, ":")
        return False


PG_CONSTRUCTORS = ("Pool", "Client")
SUBMITTABLE_MODULES = {"pg-cursor": "Cursor", "pg-query-stream": "QueryStream"}


class ReceiverDetector(Detector):
    """Find the `pg` receivers of a file: the variables, member forms and class fields whose
    `.query(...)` calls send SQL to a `pg` connection.

    It reuses the binding rules of the postgres.js tag detector (`binding`, `assigned_from`)."""

    def __init__(self, tokens, given_receivers):
        super().__init__(tokens, [])
        self.given = set(given_receivers)
        self.objects = {}  # name -> "pg" or "native" (a `pg` module object)
        self.constructors = set()  # names of the `Pool` and `Client` classes
        self.submittables = {}  # local name -> "Query", "Cursor" or "QueryStream" (never a receiver)
        self.receivers = {}  # receiver -> first offset

    def add_receiver(self, name, offset):
        if name not in self.receivers or offset < self.receivers[name]:
            self.receivers[name] = offset

    def run(self):
        self.find_imports()
        self.find_submittable_modules()
        self.find_declarations()
        for i, token in enumerate(self.tokens):
            if token[0] == "name" and self.assigned_from(i, self.is_new_constructor):
                bound = self.binding(i)
                if bound is not None:
                    self.add_receiver(*bound)
        while self.find_derived():
            pass
        return sorted(self.receivers, key=lambda name: self.receivers[name])

    # the import forms of `pg`
    def find_imports(self):
        t = self.tokens
        for i, token in enumerate(t):
            if not name_is(token, "import") or punct(self.at(i + 1), "(") or punct(self.at(i + 1), "."):
                continue
            if self.at(i + 1)[0] == "name" and punct(self.at(i + 2), "="):
                # import pg = require('pg')
                if self.is_require(i + 3):
                    self.objects[t[i + 1][1]] = "pg"
                continue
            found = self.import_from(i)
            if found is not None and found[0] == "pg":
                self.import_clause(found[1])

    def import_from(self, i):
        """(module, clause tokens) of the `import` at token `i`, or None when it has no `from` clause."""
        t = self.tokens
        k = i + 1
        # a side-effect import (`import 'x'`) has no clause: the scan ends at the next `import`
        while k < min(len(t) - 1, i + 80) and not punct(t[k], ";") and not (k > i + 1 and name_is(t[k], "import")):
            if name_is(t[k], "from") and t[k + 1][0] == "str":
                break
            k += 1
        else:
            return None
        if not (k < len(t) - 1 and name_is(t[k], "from") and t[k + 1][0] == "str"):
            return None
        return t[k + 1][1].strip("'\""), t[i + 1 : k]

    def import_clause(self, segment):
        type_only = False
        if segment and name_is(segment[0], "type") and len(segment) > 1:
            if segment[1][0] == "name":
                return  # import type Name from 'pg': a type, never a value
            segment = segment[1:]
            type_only = True
        braces = False
        item_type = False
        k = 0
        while k < len(segment):
            token = segment[k]
            if punct(token, "{"):
                braces = True
            elif punct(token, "}"):
                braces = False
            elif punct(token, "*") and k + 2 < len(segment) and name_is(segment[k + 1], "as"):
                self.objects[segment[k + 2][1]] = "pg"
                k += 2
            elif token[0] == "name" and not braces:
                self.objects[token[1]] = "pg"
            elif token[0] == "name" and braces:
                if (
                    name_is(token, "type")
                    and k + 1 < len(segment)
                    and segment[k + 1][0] == "name"
                    and not name_is(segment[k + 1], "as")
                ):
                    item_type = True  # `type Name`: a type-only item
                    k += 1
                    continue
                local = token[1]
                if k + 2 < len(segment) and name_is(segment[k + 1], "as") and segment[k + 2][0] == "name":
                    local = segment[k + 2][1]
                    k += 2
                self.bind_member(token[1], local, "pg", type_only or item_type)
                item_type = False
            k += 1

    def bind_member(self, member, local, owner, type_only=False):
        """`local` holds the member `member` of a `pg` object of kind `owner`."""
        if member in PG_CONSTRUCTORS:
            self.constructors.add(local)
        elif member == "native" and owner == "pg":
            self.objects[local] = "native"
        elif member == "Query" and not type_only:
            self.submittables[local] = "Query"

    def is_require(self, j, module="pg"):
        """`require('<module>')` starts at token `j`."""
        t = self.tokens
        return (
            name_is(self.at(j), "require")
            and punct(self.at(j + 1), "(")
            and self.at(j + 2)[0] == "str"
            and t[j + 2][1].strip("'\"") == module
            and punct(self.at(j + 3), ")")
        )

    # `pg-cursor` and `pg-query-stream`: the local name of the default export is a submittable class
    def find_submittable_modules(self):
        t = self.tokens
        for i, token in enumerate(t):
            if name_is(token, "import") and not (punct(self.at(i + 1), "(") or punct(self.at(i + 1), ".")):
                if self.at(i + 1)[0] == "name" and punct(self.at(i + 2), "="):
                    # import Cursor = require('pg-cursor')
                    for module, class_name in SUBMITTABLE_MODULES.items():
                        if self.is_require(i + 3, module):
                            self.submittables[t[i + 1][1]] = class_name
                    continue
                found = self.import_from(i)
                if found is None or found[0] not in SUBMITTABLE_MODULES:
                    continue
                segment = found[1]
                if segment and name_is(segment[0], "type"):
                    continue  # a type-only import
                local = None
                if len(segment) >= 3 and punct(segment[0], "*") and name_is(segment[1], "as"):
                    local = segment[2][1]
                elif segment and segment[0][0] == "name":
                    local = segment[0][1]
                if local is not None:
                    self.submittables[local] = SUBMITTABLE_MODULES[found[0]]
            elif token[0] == "name" and token[1] in ("const", "let", "var") and self.at(i + 1)[0] == "name":
                if punct(self.at(i + 2), "="):
                    for module, class_name in SUBMITTABLE_MODULES.items():
                        if self.is_require(i + 3, module):
                            self.submittables[t[i + 1][1]] = class_name

    def submittable_at(self, j):
        """(class, index of its `(`) of the `new X(...)` or `new X<...>(...)` that starts at token `j`
        when `X` is a submittable class, else None."""
        if not name_is(self.at(j), "new"):
            return None
        j += 1
        name = self.at(j)
        if name[0] != "name":
            return None
        if name[1] in self.submittables:
            class_name, k = self.submittables[name[1]], j + 1
        elif name[1] in self.objects:
            kind, k = self.objects[name[1]], j + 1
            if kind == "pg" and punct(self.at(k), ".") and name_is(self.at(k + 1), "native"):
                k += 2
            if not (punct(self.at(k), ".") and name_is(self.at(k + 1), "Query")):
                return None
            class_name, k = "Query", k + 2
        else:
            return None
        closing = type_arguments_close(self.tokens, k)
        if closing is not None:
            k = closing + 1
        if not punct(self.at(k), "("):
            return None
        return class_name, k

    def resolve(self, j):
        """The value of the expression that starts at token `j`: ("pg" | "native", end) for a
        `pg` module object, ("constructor", end) for `Pool` or `Client`, or None."""
        if self.is_require(j):
            kind, k = "pg", j + 4
        elif self.at(j)[0] == "name" and self.at(j)[1] in self.objects:
            kind, k = self.objects[self.at(j)[1]], j + 1
        elif self.at(j)[0] == "name" and self.at(j)[1] in self.constructors:
            return "constructor", j + 1
        else:
            return None
        while punct(self.at(k), ".") and self.at(k + 1)[0] == "name":
            member = self.at(k + 1)[1]
            if member == "native" and kind == "pg":
                kind = "native"
            elif member in PG_CONSTRUCTORS:
                return "constructor", k + 2
            elif member == "Query":
                return "query", k + 2
            else:
                return None
            k += 2
        return kind, k

    # const pg = require('pg'); const { Pool } = pg; const Pool = require('pg').Pool; ...
    def find_declarations(self):
        t = self.tokens
        while True:
            before = (len(self.objects), len(self.constructors))
            for i, token in enumerate(t):
                if not (token[0] == "name" and token[1] in ("const", "let", "var")):
                    continue
                first = self.at(i + 1)
                if first[0] == "name" and punct(self.at(i + 2), "="):
                    found = self.resolve(i + 3)
                    if found is None:
                        continue
                    if found[0] == "constructor":
                        self.constructors.add(first[1])
                    elif found[0] == "query":
                        self.submittables[first[1]] = "Query"
                    else:
                        self.objects[first[1]] = found[0]
                elif punct(first, "{"):
                    self.destructure(i + 2)
            if before == (len(self.objects), len(self.constructors)):
                return

    def destructure(self, j):
        """The object pattern whose first item is at token `j`: `{ Pool, Client: C, native } = source`."""
        t = self.tokens
        items = []
        k = j
        while k < len(t) and not punct(t[k], "}"):
            if t[k][0] == "name":
                member, local = t[k][1], t[k][1]
                if punct(self.at(k + 1), ":") and self.at(k + 2)[0] == "name":
                    local = t[k + 2][1]
                    k += 2
                items.append((member, local))
            k += 1
        if not punct(self.at(k + 1), "="):
            return
        found = self.resolve(k + 2)
        if found is None or found[0] in ("constructor", "query"):
            return
        for member, local in items:
            self.bind_member(member, local, found[0])

    # NAME = [await] new <constructor>(...), and nothing after the call: `new Pool().query(...)` gives
    # a query result, not a pool
    def is_new_constructor(self, j, awaited):
        t = self.tokens
        if not name_is(self.at(j), "new"):
            return False
        j += 1
        name = self.at(j)
        if name[0] != "name":
            return False
        if name[1] in self.constructors:
            opening = j + 1
        elif name[1] in self.objects:
            kind, k = self.objects[name[1]], j + 1
            if kind == "pg" and punct(self.at(k), ".") and name_is(self.at(k + 1), "native"):
                k += 2
            if not (punct(self.at(k), ".") and self.at(k + 1)[0] == "name" and t[k + 1][1] in PG_CONSTRUCTORS):
                return False
            opening = k + 2
        else:
            return False
        if not punct(self.at(opening), "("):
            return False
        closing = match_close(t, opening)
        return closing is not None and not any(punct(self.at(closing + 1), p) for p in (".", "?.", "[", "("))

    # clients that a receiver gives: await <receiver>.connect(), .connect().then(client => ...),
    # .connect((err, client, release) => ...)
    def find_derived(self):
        t = self.tokens
        known = set(self.receivers) | self.given
        before = len(self.receivers)
        for i, token in enumerate(t):
            if token[0] == "name" and self.assigned_from(i, lambda j, awaited: awaited and self.is_connect_call(j, known)):
                bound = self.binding(i)
                if bound is not None:
                    self.add_receiver(*bound)
        for i in range(1, len(t) - 2):
            if not (punct(t[i], ".") and name_is(t[i + 1], "connect") and punct(t[i + 2], "(")):
                continue
            receiver = chain_ending_at(t, i - 1)
            if receiver is None or receiver[0] not in known:
                continue
            if punct(self.at(i + 3), ")"):
                if punct(self.at(i + 4), ".") and name_is(self.at(i + 5), "then") and punct(self.at(i + 6), "("):
                    parameters, wanted = self.callback_parameters(i + 7), 0
                else:
                    continue
            else:
                parameters, wanted = self.callback_parameters(i + 3), 1
            if parameters is not None and wanted < len(parameters) and parameters[wanted] is not None:
                self.add_receiver(parameters[wanted][1], parameters[wanted][2])
        return len(self.receivers) > before

    def is_connect_call(self, j, known):
        """`<receiver>.connect()` at token `j`, not followed by a member access."""
        t = self.tokens
        parts = []
        while self.at(j)[0] == "name":
            parts.append(t[j][1])
            if punct(self.at(j + 1), "."):
                j += 2
            else:
                j += 1
                break
        if len(parts) < 2 or parts[-1] != "connect" or ".".join(parts[:-1]) not in known:
            return False
        if not (punct(self.at(j), "(") and punct(self.at(j + 1), ")")):
            return False
        return not (punct(self.at(j + 2), ".") or punct(self.at(j + 2), "?."))

    def callback_parameters(self, j):
        """The first token of each parameter of the callback that starts at token `j` (None for a
        destructured one), or None when no callback starts there."""
        t = self.tokens
        if name_is(self.at(j), "async"):
            j += 1
        first = self.at(j)
        if first[0] == "name" and first[1] != "function" and punct(self.at(j + 1), "=>"):
            return [first]
        if name_is(first, "function"):
            j += 1
            if self.at(j)[0] == "name":
                j += 1
        if not punct(self.at(j), "("):
            return None
        if not name_is(first, "function") and not self.arrow_follows(j):
            return None
        parameters, depth, fresh = [], 0, True
        for k in range(j, len(t)):
            token = t[k]
            if token[0] == "p" and token[1] in "([{<":
                depth += 1
                if depth > 1 and fresh:
                    parameters.append(None)
                    fresh = False
            elif token[0] == "p" and token[1] in ")]}>":
                depth -= 1
                if depth == 0:
                    return parameters
            elif depth == 1 and punct(token, ","):
                fresh = True
            elif depth == 1 and fresh and token[0] == "name":
                parameters.append(token)
                fresh = False
            elif depth == 1 and fresh and not punct(token, "..."):
                parameters.append(None)
                fresh = False
        return None


# ---------------------------------------------------------------- pg statements


def match_close(tokens, i):
    """Index of the token that closes the bracket token at `i`, or None."""
    depth = 0
    for k in range(i, len(tokens)):
        token = tokens[k]
        if token[0] == "ibeg" or (token[0] == "p" and token[1] in "([{"):
            depth += 1
        elif token[0] == "iend" or (token[0] == "p" and token[1] in ")]}"):
            depth -= 1
            if depth == 0:
                return k
    return None


def string_is_terminated(raw):
    """A quoted string token that holds its closing quote: two characters or more, the last one is
    the opening quote, and an even run of backslashes stands before it."""
    if len(raw) < 2 or raw[-1] != raw[0]:
        return False
    run = 0
    while len(raw) - 2 - run > 0 and raw[len(raw) - 2 - run] == "\\":
        run += 1
    return run % 2 == 0


SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v"}
HEX_DIGITS = "0123456789abcdefABCDEF"


def decode_literal(source, start, end, template):
    """Decode the JavaScript literal body `source.text[start:end]` (between the quotes).

    Returns (text, lines): the decoded value and, for each of its characters, the source line of
    the character or of the escape that made it. A lone surrogate becomes U+FFFD; a surrogate pair
    becomes one character."""
    body = source.text
    chars, lines = [], []
    line = source.line(start)
    i = start
    while i < end:
        c = body[i]
        here = line
        if c == "\\" and i + 1 < end:
            n = body[i + 1]
            i += 2
            if n in SIMPLE_ESCAPES:
                chars.append(SIMPLE_ESCAPES[n])
            elif n in "01234567":
                limit = 3 if n in "0123" else 2
                digits = n
                while len(digits) < limit and i < end and body[i] in "01234567":
                    digits += body[i]
                    i += 1
                chars.append(chr(int(digits, 8)))
            elif n == "x" and i + 1 < end and body[i] in HEX_DIGITS and body[i + 1] in HEX_DIGITS:
                chars.append(chr(int(body[i : i + 2], 16)))
                i += 2
            elif n == "u" and i < end and body[i] == "{":
                close = body.find("}", i, end)
                digits = body[i + 1 : close] if close > 0 else ""
                if digits and all(d in HEX_DIGITS for d in digits) and int(digits, 16) <= 0x10FFFF:
                    chars.append(chr(int(digits, 16)))
                    i = close + 1
                else:
                    chars.append("u")
            elif n == "u" and i + 3 < end and all(d in HEX_DIGITS for d in body[i : i + 4]):
                chars.append(chr(int(body[i : i + 4], 16)))
                i += 4
            elif n == "\r" and i < end and body[i] == "\n":
                i += 1
                line += 1
                continue
            elif n in "\r  ":
                continue
            elif n == "\n":
                line += 1
                continue
            else:
                chars.append(n)
            lines.append(here)
            continue
        i += 1
        if template and c == "\r":
            if i < end and body[i] == "\n":
                i += 1
                line += 1
            chars.append("\n")
        else:
            chars.append(c)
            if c == "\n":
                line += 1
        lines.append(here)
    return join_surrogates(chars, lines)


def join_surrogates(chars, lines):
    text, kept = [], []
    k = 0
    while k < len(chars):
        c = chars[k]
        if "\ud800" <= c <= "\udbff" and k + 1 < len(chars) and "\udc00" <= chars[k + 1] <= "\udfff":
            text.append(chr(0x10000 + ((ord(c) - 0xD800) << 10) + (ord(chars[k + 1]) - 0xDC00)))
            kept.append(lines[k])
            k += 2
            continue
        text.append("�" if "\ud800" <= c <= "\udfff" else c)
        kept.append(lines[k])
        k += 1
    return "".join(text), kept


def line_starts_of(text, lines, closing_line):
    """For each line of `text` (split at "\\n"), the source line where it starts."""
    starts, index = [], 0
    for part in text.split("\n"):
        starts.append(lines[index] if index < len(text) else closing_line)
        index += len(part) + 1
    return starts


def statement_count(text):
    """The number of statements of `text`: the groups of tokens that a semicolon outside strings,
    quoted names, dollar quotes and comments separates."""
    tokens, _ = sql_guard.tokenize(text)
    count, open_group = 0, False
    for token in tokens:
        if token.kind == "punct" and token.value == ";":
            open_group = False
        elif not open_group:
            count, open_group = count + 1, True
    return count


def callback_starts(detector, j):
    """True when the expression at token `j` is a function: an arrow function, a `function`
    expression, or the same with `async`."""
    return detector.callback_parameters(j) is not None


def values_of(tokens, detector, e):
    """(values_length, values_present) of the call whose first argument ends before the token `e`."""
    if not punct(tokens[e], ","):
        return 0, False
    s = e + 1
    first = detector.at(s)
    if punct(first, ")"):
        return 0, False
    if callback_starts(detector, s):
        return 0, False
    if punct(first, "["):
        close = match_close(tokens, s)
        after = detector.at(close + 1) if close is not None else None
        if close is not None and (
            punct(after, ",") or punct(after, ")") or name_is(after, "as") or name_is(after, "satisfies")
        ):
            return array_length(tokens, s, close), True
    return None, True


def type_arguments_end(tokens, k, close):
    """The index of the `>` that closes the type arguments opened by the `<` at `k`, or None.

    A `<` is an opening only when it follows a name with no space and its `>` ends the element or
    is followed by `(`, as in `Map<K, V>` or `f<T>(x)`; `a < b` and `a<b, c>d` are comparisons."""
    if not (punct(tokens[k], "<") and tokens[k - 1][0] == "name" and tokens[k - 1][3] == tokens[k][2]):
        return None
    depth = 0
    for m in range(k, close):
        if punct(tokens[m], "<"):
            depth += 1
        elif punct(tokens[m], ">"):
            depth -= 1
            if depth == 0:
                after = tokens[m + 1] if m + 1 < len(tokens) else None
                closes = m + 1 >= close or any(punct(after, p) for p in ("(", ",", ")", "]"))
                return m if closes else None
    return None


def array_length(tokens, s, close):
    """The element count of the array literal from `[` at `s` to `]` at `close`; None with a spread."""
    if close == s + 1:
        return 0
    depth, commas, spread, fresh = 0, 0, False, True
    skip_to = s
    for k in range(s + 1, close):
        if k <= skip_to:
            continue
        token = tokens[k]
        end = type_arguments_end(tokens, k, close)
        if end is not None:
            skip_to = end
            fresh = False
            continue
        if token[0] == "ibeg" or (token[0] == "p" and token[1] in "([{"):
            depth += 1
        elif token[0] == "iend" or (token[0] == "p" and token[1] in ")]}"):
            depth -= 1
        elif depth == 0 and punct(token, ","):
            commas += 1
            fresh = True
            continue
        elif depth == 0 and fresh and punct(token, "..."):
            spread = True
        fresh = False
    if spread:
        return None
    trailing = punct(tokens[close - 1], ",")
    return commas + 1 - (1 if trailing else 0)


def type_arguments_close(tokens, k):
    """The index of the `>` that closes the type arguments opened by the `<` at `k`, or None.

    A `<` opens type arguments when it follows a name with no space and its matching `>` (nested
    pairs counted) comes within MAX_TYPE_ARGUMENT_TOKENS tokens."""
    if not (k > 0 and punct(tokens[k], "<") and tokens[k - 1][0] == "name" and tokens[k - 1][3] == tokens[k][2]):
        return None
    depth = 0
    for m in range(k, min(len(tokens), k + MAX_TYPE_ARGUMENT_TOKENS)):
        if punct(tokens[m], "<"):
            depth += 1
        elif punct(tokens[m], ">"):
            depth -= 1
            if depth == 0:
                return m
    return None


NOTHING = object()  # the call gives no statement and is not listed
NOT_FOLLOWED = object()  # the call is listed in `not_followed`
OBJECT_BEFORE = frozenset(["(", ",", "=", "?", "[", "+", "-", "*", "/", "%", "!", "&", "|", "^", "~", "<", "..."])
OBJECT_AFTER_NAMES = frozenset(
    "return typeof await yield in of const let var import export default throw void delete case new".split()
)
NOT_PARAMETER_NAMES = frozenset("if for while switch case catch with return typeof await new in of else do".split())
PARAMETER_MODIFIERS = frozenset("public private protected readonly override accessor declare".split())
NOT_OPERAND_NAMES = frozenset(
    "typeof await new in of instanceof void delete yield return throw extends as satisfies".split()
)
EXPRESSION_BEFORE = frozenset(
    ["=", "(", ",", ":", "?", "[", "&", "|", "+", "-", "*", "/", "%", "!", "<", ">", "^", "~", "=>", "..."]
)
EXPRESSION_BEFORE_NAMES = frozenset("return typeof await yield in of new case throw void delete".split())
DECIMAL_INTEGER = re.compile(r"[0-9]+\Z")


class Value:
    """The SQL text that some calls give: one statement."""

    def __init__(self, key, kind, first, text, start_line, end_line, line_starts, dynamic, interpolations=(), end=None):
        self.key = key
        self.kind = kind
        self.first = first
        self.end = end  # the offset after the last character of the value
        self.text = text
        self.start_line = start_line
        self.end_line = end_line
        self.line_starts = line_starts
        self.dynamic = dynamic
        self.interpolations = list(interpolations)
        self.const_name = None

    def statement(self):
        return {
            "source": "pg",
            "tag": None,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "text": self.text,
            "parent": None,
            "interpolations": self.interpolations,
            "pg": {
                "kind": self.kind,
                "const_name": self.const_name,
                "line_starts": self.line_starts,
                "dynamic": self.dynamic,
                "statement_count": None if self.dynamic else statement_count(self.text),
                "calls": [],
            },
        }


class Use:
    """What one call gives to a statement: its `calls` entry without the line."""

    def __init__(self, value, call, length=0, present=False, name=None, rows=None, query_mode=None):
        self.value = value
        self.call = call
        self.length = length
        self.present = present
        self.name = name
        self.rows = rows
        self.query_mode = query_mode


class Declaration:
    def __init__(self, name, lo, hi, index, value_start=None):
        self.name = name
        self.lo, self.hi = lo, hi  # the tokens that hold the scope of the name
        self.index = index  # the token of the declaration
        self.value_start = value_start  # the first token of the value of `const NAME = <value>`


class PgCalls:
    """The `<receiver>.query(...)` calls of a file and the statements that their first arguments give.

    The first argument is a config object, a submittable (`new Query`, `new Cursor`, `new QueryStream`),
    a string, a template, a `+` chain, or a name that is followed to a same-file `const`. A call that
    gives no statement is listed in `not_followed`."""

    def __init__(self, source, tokens, spans, detector, receivers, tags):
        self.source = source
        self.tokens = tokens
        self.spans = spans  # the token index of a template token -> its Template
        self.detector = detector
        self.receivers = receivers
        self.tags = set(tags)
        self.starts = {token[2]: k for k, token in enumerate(tokens)}
        self.span_starts = {self.starts[record.end]: k for k, record in spans.items() if record.end in self.starts}
        self.statements = {}  # key -> [first offset, statement, end offset]
        self.not_followed = []
        self.constants = {}  # declaration token index -> result of `const_result`
        self.declarations = None  # name -> [Declaration], built when a call has a name argument

    def at(self, i):
        return self.detector.at(i)

    def span_end(self, k):
        """The index of the closing token of the template whose first token is `k`."""
        return self.starts[self.spans[k].end]

    # ------------------------------------------------------------------ calls

    def run(self):
        """(the (offset, statement, end offset) triples, the `not_followed` list) of the file."""
        t = self.tokens
        for i, token in enumerate(t):
            if not (name_is(token, "query") and (punct(self.at(i - 1), ".") or punct(self.at(i - 1), "?."))):
                continue
            receiver = chain_ending_at(t, i - 2)
            if receiver is None or receiver[0] not in self.receivers:
                continue
            p = i + 1
            if punct(self.at(p), "<"):
                closing = None
                depth, count = 0, 0
                while p < len(t) and count < MAX_TYPE_ARGUMENT_TOKENS:
                    if punct(t[p], "<"):
                        depth += 1
                    elif punct(t[p], ">"):
                        depth -= 1
                        if depth == 0:
                            closing = p
                            break
                    p += 1
                    count += 1
                if closing is None:
                    continue
                p = closing + 1
            if not punct(self.at(p), "("):
                continue
            outcome = self.call(p)
            line = self.source.line(token[2])
            if outcome is NOT_FOLLOWED:
                self.not_followed.append({"line": line})
            elif isinstance(outcome, Use):
                self.add_use(outcome, line)
        return [tuple(entry) for entry in self.statements.values()], self.not_followed

    def add_use(self, use, line):
        value = use.value
        if value.key not in self.statements:
            self.statements[value.key] = [value.first, value.statement(), value.end]
        self.statements[value.key][1]["pg"]["calls"].append(
            {
                "line": line,
                "call": use.call,
                "values_length": use.length,
                "values_present": use.present,
                "name": use.name,
                "rows": use.rows,
                "query_mode": use.query_mode,
            }
        )

    def call(self, p):
        """NOTHING, NOT_FOLLOWED or the Use of the call whose `(` is at `p`."""
        t = self.tokens
        s = p + 1
        if punct(self.at(s), ")"):
            return NOTHING
        e = self.item_end(s)
        if e >= len(t) or not (punct(t[e], ",") or punct(t[e], ")")):
            return NOT_FOLLOWED
        tag = self.tagged(s, e)
        if tag is not None:
            return NOTHING if tag in self.tags else NOT_FOLLOWED
        if punct(t[s], "{"):
            close = match_close(t, s)
            if close is not None and self.config_ends(close, e):
                return self.config(s, close, "config")
        if name_is(t[s], "new"):
            found = self.detector.submittable_at(s)
            if found is not None:
                close = match_close(t, found[1])
                if close is not None and close + 1 == e:
                    return self.submittable(found[0], found[1], close)
        result = self.text_expression(s, e)
        if isinstance(result, Value):
            length, present = values_of(t, self.detector, e)
            return Use(result, "direct", length, present)
        return result if result is NOTHING or isinstance(result, Use) else NOT_FOLLOWED

    def config_ends(self, close, e):
        """True when nothing but a type clause (`as T`, `satisfies T`) stands between the `}` at
        `close` and the end `e` of the argument."""
        after = self.at(close + 1)
        return close + 1 == e or (close + 1 < e and (name_is(after, "as") or name_is(after, "satisfies")))

    # ------------------------------------------------------- argument scanning

    def item_end(self, k, semicolon=False):
        """The index of the first `,` (or `;` when asked) at depth 0 from token `k`, or of the first
        closing bracket that has no opening one; the length of the tokens when none comes."""
        t = self.tokens
        n = len(t)
        while k < n:
            token = t[k]
            if token[0] == "tpl":
                k = self.span_end(k) + 1
                continue
            if token[0] == "p":
                c = token[1]
                if c in ("(", "[", "{"):
                    close = match_close(t, k)
                    if close is None:
                        return n
                    k = close + 1
                    continue
                if c in (")", "]", "}") or c == "," or (semicolon and c == ";"):
                    return k
                if c == "<":
                    closing = type_arguments_close(t, k)
                    if closing is not None:
                        k = closing + 1
                        continue
            k += 1
        return n

    def value_end(self, k):
        """The index after the expression that starts at token `k` (a `const` value): it ends at a `,`,
        a `;`, an unmatched closing bracket, the end of the file, or a name that starts a statement on a
        later line (the line break after an operand ends the expression)."""
        t = self.tokens
        n = len(t)
        start = k
        while k < n:
            token = t[k]
            if token[0] == "tpl":
                k = self.span_end(k) + 1
                continue
            if token[0] == "p":
                c = token[1]
                if c in ("(", "[", "{"):
                    close = match_close(t, k)
                    if close is None:
                        return n
                    k = close + 1
                    continue
                if c in (")", "]", "}", ",", ";"):
                    return k
                if c == "<":
                    closing = type_arguments_close(t, k)
                    if closing is not None:
                        k = closing + 1
                        continue
            elif token[0] == "name" and k > start and token[1] not in ("as", "satisfies") and self.ends_operand(k - 1):
                if self.source.line(token[2]) > self.source.line(t[k - 1][3] - 1):
                    return k
            k += 1
        return n

    def ends_operand(self, k):
        token = self.tokens[k]
        if token[0] in ("str", "num", "tpl_end", "regex"):
            return True
        if token[0] == "name":
            if token[1] == "void" and k > 0 and self.tokens[k - 1][0] == "p" and self.tokens[k - 1][1] in ("=>", ":"):
                return True  # the type `void` after `=>` or `:`, not the operator
            return token[1] not in NOT_OPERAND_NAMES
        return token[0] == "p" and token[1] in (")", "]", "}")

    def tagged(self, s, e):
        """The tag of the tagged template that the tokens [s, e) are, or None."""
        t = self.tokens
        if e - 1 <= s or t[e - 1][0] != "tpl_end" or (e - 1) not in self.span_starts:
            return None
        found = tag_chain(t, self.span_starts[e - 1])
        return found[0] if found is not None and found[1] == s else None

    # --------------------------------------------------------------- the text

    def literal_piece(self, a, b):
        """"str" for one terminated string token, "tpl" for one template, else None, for [a, b)."""
        t = self.tokens
        if b - a == 1 and t[a][0] == "str":
            return "str" if string_is_terminated(t[a][1]) else None
        if t[a][0] == "tpl" and self.span_end(a) == b - 1:
            return "tpl"
        return None

    def chain_pieces(self, s, e):
        """The operands [a, b) of the chain that the tokens [s, e) are, or None when they are not one."""
        t = self.tokens
        pieces, start, k, plus = [], s, s, False
        while k < e:
            token = t[k]
            if token[0] == "tpl":
                k = self.span_end(k) + 1
                continue
            if token[0] == "str":
                if not string_is_terminated(token[1]):
                    return None
            elif token[0] in ("name", "num"):
                pass
            elif token[0] == "p" and token[1] in (".", "?."):
                pass
            elif token[0] == "p" and token[1] in ("(", "[", "{"):
                close = match_close(t, k)
                if close is None or close >= e:
                    return None
                k = close + 1
                continue
            elif token[0] == "p" and token[1] == "<" and (closing := type_arguments_close(t, k)) is not None:
                k = closing + 1
                continue
            elif token[0] == "p" and token[1] == "+":
                if k == start:
                    return None
                pieces.append((start, k))
                start, plus = k + 1, True
            else:
                return None
            k += 1
        if start >= e:
            return None
        pieces.append((start, e))
        return pieces if plus else None

    def read_value(self, s, e, strict=False):
        """The Value that the tokens [s, e) are (a string, a template or a chain with a string or a
        template operand), or None. With `strict`, a chain must be all-literal."""
        t = self.tokens
        kind = self.literal_piece(s, e)
        if kind == "str":
            return self.string_value(s)
        if kind == "tpl":
            return self.template_value(s)
        pieces = self.chain_pieces(s, e)
        if pieces is None:
            return None
        kinds = [self.literal_piece(a, b) for a, b in pieces]
        if not any(kinds):
            return None
        dynamic = any(k is None or (k == "tpl" and self.spans[a].interpolations) for (a, _), k in zip(pieces, kinds))
        if strict and dynamic:
            return None
        first, last = t[s][2], t[e - 1][3] - 1
        if dynamic:
            text = self.source.text[first : last + 1]
            line = self.source.line(first)
            line_starts = [line + index for index in range(text.count("\n") + 1)]
            return Value(("lit", s), "chain", first, text, line, self.source.line(last), line_starts, True, end=last + 1)
        texts, lines = [], []
        for (a, _), k in zip(pieces, kinds):
            if k == "str":
                piece, piece_lines = decode_literal(self.source, t[a][2] + 1, t[a][3] - 1, False)
            else:
                piece, piece_lines = decode_literal(self.source, self.spans[a].start + 1, self.spans[a].end, True)
            texts.append(piece)
            lines += piece_lines
        text = "".join(texts)
        line_starts = line_starts_of(text, lines, self.source.line(last))
        return Value(
            ("lit", s), "chain", first, text, self.source.line(first), self.source.line(last), line_starts, False,
            end=last + 1,
        )

    def string_value(self, k):
        token = self.tokens[k]
        first, last = token[2], token[3] - 1
        text, lines = decode_literal(self.source, first + 1, last, False)
        line_starts = line_starts_of(text, lines, self.source.line(last))
        return Value(
            ("lit", k), "literal", first, text, self.source.line(first), self.source.line(last), line_starts, False,
            end=last + 1,
        )

    def template_value(self, k):
        record = self.spans[k]
        first, last = record.start, record.end
        if not record.interpolations:
            text, lines = decode_literal(self.source, first + 1, last, True)
            line_starts = line_starts_of(text, lines, self.source.line(last))
            return Value(
                ("lit", k), "template", first, text, self.source.line(first), self.source.line(last), line_starts,
                False, end=last + 1,
            )
        text, interpolations = template_interpolations(self.source, record)
        for found, item in zip(interpolations, record.interpolations):
            found["start"] = item["start"] - first - 1
            found["end"] = item["end"] - first - 1
        line = self.source.line(first)
        line_starts = [line + index for index in range(text.count("\n") + 1)]
        return Value(
            ("lit", k), "template", first, text, line, self.source.line(last), line_starts, True, interpolations,
            end=last + 1,
        )

    def text_expression(self, s, e):
        """The Value of the text expression [s, e) (a string, a template, a chain or a name that is
        followed to a `const`), a Use (a name that holds a submittable), NOTHING (a tagged template of
        the tag list) or NOT_FOLLOWED."""
        tag = self.tagged(s, e)
        if tag is not None:
            return NOTHING if tag in self.tags else NOT_FOLLOWED
        value = self.read_value(s, e)
        if value is not None:
            return value
        if e == s + 1 and self.tokens[s][0] == "name":
            return self.name_result(s)
        return NOT_FOLLOWED

    # ------------------------------------------------------------ config object

    def properties(self, s, close):
        """{key: (value start, value end, property start)} of the config object [s, close], or None
        when it has a spread or a computed key (a method has no value: (None, None, start))."""
        found = {}
        k = s + 1
        while k < close:
            end = self.item_end(k)
            if end > close:
                return None
            if k < end:
                prop = self.property(k, end)
                if prop is None:
                    return None
                found[prop[0]] = prop[1:]
            k = end + 1
        return found

    def property(self, k, end):
        t = self.tokens
        if punct(t[k], "...") or punct(t[k], "["):
            return None
        first = k
        if t[k][0] == "name" and t[k][1] in ("async", "get", "set") and k + 1 < end and t[k + 1][0] in ("name", "str"):
            k += 1
        token = t[k]
        if token[0] == "name" or token[0] == "num":
            key = token[1]
        elif token[0] == "str" and string_is_terminated(token[1]):
            key = decode_literal(self.source, token[2] + 1, token[3] - 1, False)[0]
        else:
            return None
        if k + 1 == end:
            return (key, k, end, first) if token[0] == "name" and first == k else None
        if punct(t[k + 1], ":") and k + 2 < end:
            return key, k + 2, end, first
        if punct(t[k + 1], "(") or punct(t[k + 1], "<"):
            return key, None, None, first
        return None

    def property_text(self, prop, integer=False):
        """The value of a `name`, `rows` or `queryMode` property: its literal, or {"expression": source}."""
        if prop is None:
            return None
        t = self.tokens
        vs, ve, first = prop
        if vs is None:
            return {"expression": self.expression_text(first, self.item_end(first))}
        if ve - vs == 1 and t[vs][0] == "str" and string_is_terminated(t[vs][1]):
            return decode_literal(self.source, t[vs][2] + 1, t[vs][3] - 1, False)[0]
        if ve - vs == 1 and integer and t[vs][0] == "num" and DECIMAL_INTEGER.match(t[vs][1]):
            return int(t[vs][1])
        if t[vs][0] == "tpl" and self.span_end(vs) == ve - 1 and not self.spans[vs].interpolations:
            return decode_literal(self.source, self.spans[vs].start + 1, self.spans[vs].end, True)[0]
        return {"expression": self.expression_text(vs, ve)}

    def expression_text(self, a, b):
        t = self.tokens
        return self.source.text[t[a][2] : t[b - 1][3]].strip()

    def config(self, s, close, call):
        """The Use of the config object [s, close]: `call` is "config" or "submittable"."""
        t = self.tokens
        found = self.properties(s, close)
        if found is None or "text" not in found or found["text"][0] is None:
            return NOT_FOLLOWED
        vs, ve, _ = found["text"]
        result = self.text_expression(vs, ve)
        if result is NOTHING:
            return NOTHING
        if not isinstance(result, Value):
            return NOT_FOLLOWED
        length, present = 0, False
        if "values" in found:
            length, present = None, True
            vs, ve, _ = found["values"]
            if vs is not None and punct(t[vs], "["):
                close_array = match_close(t, vs)
                if close_array is not None and self.config_ends(close_array, ve):
                    length = array_length(t, vs, close_array)
        return Use(
            result,
            call,
            length,
            present,
            self.property_text(found.get("name")),
            self.property_text(found.get("rows"), integer=True),
            self.property_text(found.get("queryMode")),
        )

    # ------------------------------------------------------------ submittables

    def submittable(self, class_name, opening, close):
        """The Use of `new <class>(...)` with its `(` at `opening` and `)` at `close`."""
        t = self.tokens
        s = opening + 1
        if s == close:
            return NOT_FOLLOWED
        e = self.item_end(s)
        if e > close:
            return NOT_FOLLOWED
        if punct(t[s], "{"):
            end_config = match_close(t, s)
            if class_name != "Query" or end_config is None or not self.config_ends(end_config, e):
                return NOT_FOLLOWED
            return self.config(s, end_config, "submittable")
        result = self.text_expression(s, e)
        if result is NOTHING:
            return NOTHING
        if not isinstance(result, Value):
            return NOT_FOLLOWED
        length, present = values_of(t, self.detector, e)
        return Use(result, "submittable", length, present)

    # -------------------------------------------------------------- names, const

    def name_result(self, k):
        """The result of the name token `k` used as SQL: a Value, a Use (a name that holds a
        submittable), NOTHING or NOT_FOLLOWED."""
        declaration = self.resolve(self.tokens[k][1], k)
        if declaration is None or declaration.value_start is None or declaration.index > k:
            return NOT_FOLLOWED
        if declaration.index not in self.constants:
            self.constants[declaration.index] = self.const_result(declaration)
        return self.constants[declaration.index]

    def const_result(self, declaration):
        t = self.tokens
        vs = declaration.value_start
        ve = self.value_end(vs)
        if vs >= ve:
            return NOT_FOLLOWED
        if name_is(t[vs], "new"):
            found = self.detector.submittable_at(vs)
            if found is not None:
                close = match_close(t, found[1])
                if close is not None and close + 1 == ve:
                    return self.submittable(found[0], found[1], close)
            return NOT_FOLLOWED
        tag = self.tagged(vs, ve)
        if tag is not None:
            return NOTHING if tag in self.tags else NOT_FOLLOWED
        value = self.read_value(vs, ve, strict=True)
        if value is None:
            return NOT_FOLLOWED
        value.key = ("const", declaration.index)
        value.const_name = declaration.name
        return value

    def resolve(self, name, k):
        """The innermost declaration of `name` whose scope holds the token `k`, or None when there is
        none or two equally inner ones."""
        if self.declarations is None:
            self.declarations = {}
            for declaration in self.scan_declarations():
                self.declarations.setdefault(declaration.name, []).append(declaration)
        best, tied = None, False
        for declaration in self.declarations.get(name, ()):
            if not declaration.lo <= k <= declaration.hi:
                continue
            if best is None or declaration.hi - declaration.lo < best.hi - best.lo:
                best, tied = declaration, False
            elif declaration.hi - declaration.lo == best.hi - best.lo:
                tied = True
        return None if tied else best

    # ----------------------------------------------------------------- scopes

    def is_block(self, k):
        """True when the `{` at token `k` opens a block (a function or class body, a control
        statement, a bare block) and not an object literal or a pattern."""
        previous = self.at(k - 1)
        if previous[0] == "p":
            if previous[1] in OBJECT_BEFORE:
                return False
            if previous[1] == ":":
                return self.detector.is_clause_colon(k - 1)
            return True
        if previous[0] == "ibeg":
            return False
        if previous[0] == "name":
            if previous[1] == "void" and punct(self.at(k - 2), ":"):
                return True  # the return type `void`, so the `{` opens the body
            return previous[1] not in OBJECT_AFTER_NAMES
        return True

    def scan_blocks(self):
        """(the end of each block by its `{`, the innermost enclosing block (lo, hi) of each token)."""
        t = self.tokens
        n = len(t)
        closes, stack = {}, []
        for k, token in enumerate(t):
            if punct(token, "{"):
                stack.append(k)
            elif punct(token, "}") and stack:
                opening = stack.pop()
                if self.is_block(opening):
                    closes[opening] = k
        for opening in stack:
            if self.is_block(opening):
                closes[opening] = n - 1
        scope_of, open_blocks = [], []
        for k in range(n):
            if open_blocks and open_blocks[-1][1] == k:
                scope_of.append(open_blocks.pop())
            else:
                scope_of.append(open_blocks[-1] if open_blocks else (0, n - 1))
            if k in closes:
                open_blocks.append((k, closes[k]))
        return closes, scope_of

    def scan_declarations(self):
        t = self.tokens
        n = len(t)
        self.closes, self.scope_of = self.scan_blocks()
        found = []
        file_scope = (0, n - 1)
        for k, token in enumerate(t):
            previous = self.at(k - 1)
            if punct(previous, ".") or punct(previous, "?."):
                continue
            if token[0] == "name":
                word = token[1]
                if word in ("const", "let", "var"):
                    self.declare_variables(k, found)
                elif word == "import" and not (punct(self.at(k + 1), "(") or punct(self.at(k + 1), ".")):
                    for name, index in self.import_names(k):
                        found.append(Declaration(name, file_scope[0], file_scope[1], index))
                elif word in ("function", "class") or (word in ("enum", "namespace", "module") and self.at(k + 1)[0] == "name"):
                    self.declare_named(k, found)
                elif word == "catch" and punct(self.at(k + 1), "("):
                    self.declare_catch(k, found)
                elif punct(self.at(k + 1), "=>") and word != "function":
                    body = self.body_range(k)
                    if body is not None:
                        found.append(Declaration(word, body[0], body[1], k))
            elif punct(token, "(") and self.is_parameter_list(k):
                close = match_close(t, k)
                body = self.body_range(close)
                scope = body if body is not None else (k, min(self.item_end(close, semicolon=True), n - 1))
                for name, index in self.parameter_names(k, close):
                    found.append(Declaration(name, scope[0], scope[1], index))
        return found

    def block_end(self, opening):
        return self.closes.get(opening, len(self.tokens) - 1)

    def declare_variables(self, k, found):
        t = self.tokens
        kind = t[k][1]
        if not (self.at(k + 1)[0] == "name" or punct(self.at(k + 1), "{") or punct(self.at(k + 1), "[")):
            return
        header = punct(self.at(k - 1), "(") and (
            name_is(self.at(k - 2), "for") or (name_is(self.at(k - 2), "await") and name_is(self.at(k - 3), "for"))
        )
        if header:
            close = match_close(t, k - 1)
            after = (close if close is not None else k) + 1
            hi = self.block_end(after) if punct(self.at(after), "{") else self.value_end(after)
            scope = (k - 1, min(hi, len(t) - 1))
        else:
            scope = self.scope_of[k]
        j = k + 1
        while j < len(t):
            names, plain = [], False
            if t[j][0] == "name":
                names, plain = [(t[j][1], j)], True
                j += 1
            elif punct(t[j], "{") or punct(t[j], "["):
                names = self.pattern_names(j)
                close = match_close(t, j)
                if close is None:
                    break
                j = close + 1
            else:
                break
            vs = None
            if punct(self.at(j), ":"):
                m, depth, count = j + 1, 0, 0
                while m < len(t) and count < MAX_TYPE_ANNOTATION_TOKENS:
                    token = t[m]
                    if token[0] == "p":
                        if token[1] in ("(", "[", "{"):
                            depth += 1
                        elif token[1] in (")", "]", "}"):
                            depth -= 1
                            if depth < 0:
                                break
                        elif token[1] == ";" or (token[1] == "," and depth == 0):
                            break
                        elif token[1] == "=" and depth == 0 and not punct(self.at(m + 1), "="):
                            vs = m + 1
                            break
                        elif token[1] == "<":
                            closing = type_arguments_close(t, m)
                            if closing is not None:
                                count += closing - m
                                m = closing
                    m += 1
                    count += 1
                j = vs - 1 if vs is not None else m
            elif punct(self.at(j), "=") and not punct(self.at(j + 1), "="):
                vs = j + 1
            for name, index in names:
                value = vs if (kind == "const" and plain and vs is not None) else None
                found.append(Declaration(name, scope[0], scope[1], index, value))
            if vs is not None:
                j = self.value_end(vs)
            if punct(self.at(j), ",") and (
                self.at(j + 1)[0] == "name" or punct(self.at(j + 1), "{") or punct(self.at(j + 1), "[")
            ):
                j += 1
                continue
            break

    def declare_named(self, k, found):
        """A `function`, `class`, `enum`, `namespace` or `module` name."""
        t = self.tokens
        word = t[k][1]
        j = k + 1
        if word == "function" and punct(self.at(j), "*"):
            j += 1
        if self.at(j)[0] != "name" or t[j][1] in ("extends", "implements"):
            return
        if word in ("namespace", "module") and not (punct(self.at(j + 1), "{") or punct(self.at(j + 1), ".")):
            return
        if word == "enum" and not punct(self.at(j + 1), "{"):
            return
        previous = self.at(k - 1)
        expression = word in ("function", "class") and (
            (previous[0] == "p" and previous[1] in EXPRESSION_BEFORE)
            or (previous[0] == "name" and previous[1] in EXPRESSION_BEFORE_NAMES)
        )
        if not expression:
            scope = self.scope_of[k]
        elif word == "function":
            parameters = j + 1
            closing = type_arguments_close(t, parameters)
            if closing is not None:
                parameters = closing + 1
            close = match_close(t, parameters) if punct(self.at(parameters), "(") else None
            body = self.body_range(close) if close is not None else None
            if body is None:
                return
            scope = body
        else:
            opening = j + 1
            while opening < len(t) and not punct(t[opening], "{"):
                opening += 1
            if opening >= len(t):
                return
            scope = (opening, self.block_end(opening))
        found.append(Declaration(t[j][1], scope[0], scope[1], j))

    def declare_catch(self, k, found):
        t = self.tokens
        close = match_close(t, k + 1)
        if close is None or not punct(self.at(close + 1), "{"):
            return
        scope = (close + 1, self.block_end(close + 1))
        j = k + 2
        if t[j][0] == "name":
            names = [(t[j][1], j)]
        elif punct(t[j], "{") or punct(t[j], "["):
            names = self.pattern_names(j)
        else:
            names = []
        for name, index in names:
            found.append(Declaration(name, scope[0], scope[1], index))

    def import_names(self, k):
        """(name, token) of each binding of the `import` at token `k`."""
        t = self.tokens
        if self.at(k + 1)[0] == "name" and punct(self.at(k + 2), "=") and not name_is(self.at(k + 1), "type"):
            return [(t[k + 1][1], k + 1)]
        found = self.detector.import_from(k)
        if found is None:
            return []
        segment = found[1]
        names = []
        if segment and name_is(segment[0], "type") and len(segment) > 1:
            return names  # a type-only import binds no value
        base = k + 1
        braces = False
        j = 0
        while j < len(segment):
            token = segment[j]
            if punct(token, "{"):
                braces = True
            elif punct(token, "}"):
                braces = False
            elif punct(token, "*") and j + 2 < len(segment) and name_is(segment[j + 1], "as"):
                names.append((segment[j + 2][1], base + j + 2))
                j += 2
            elif token[0] == "name" and braces:
                if (
                    name_is(token, "type")
                    and j + 1 < len(segment)
                    and segment[j + 1][0] == "name"
                    and not name_is(segment[j + 1], "as")
                ):
                    j += 2
                    continue
                if j + 2 < len(segment) and name_is(segment[j + 1], "as") and segment[j + 2][0] == "name":
                    names.append((segment[j + 2][1], base + j + 2))
                    j += 2
                else:
                    names.append((token[1], base + j))
            elif token[0] == "name":
                names.append((token[1], base + j))
            j += 1
        return names

    def pattern_names(self, j):
        """(name, token) of each name that the object or array pattern at token `j` binds."""
        t = self.tokens
        close = match_close(t, j)
        names = []
        if close is None:
            return names
        is_object = punct(t[j], "{")
        k = j + 1
        while k < close:
            end = min(self.item_end(k), close)
            a = k
            if a < end and punct(t[a], "..."):
                a += 1
            if is_object:
                m = a
                while m < end:
                    if punct(t[m], ":"):
                        a = m + 1
                        break
                    if t[m][0] == "p" and t[m][1] in ("(", "[", "{"):
                        closing = match_close(t, m)
                        m = (closing if closing is not None else end) + 1
                        continue
                    m += 1
            if a < end:
                if t[a][0] == "name":
                    names.append((t[a][1], a))
                elif punct(t[a], "{") or punct(t[a], "["):
                    names += self.pattern_names(a)
            k = end + 1
        return names

    def scan_return_type(self, j):
        """Scan from token `j` after a `)` and a `:`: (kind, index) with kind "arrow" or "brace" and the
        index of the `=>` or the `{` when one comes first, "stop" for a `;`, `}` or `)` at depth 0,
        "long" when none comes in 60 tokens. A `{` after `:`, `|`, `&`, `<`, `,` or `?` is an object
        type and is skipped."""
        t = self.tokens
        depth = 0
        k = j
        while k < min(len(t), j + MAX_TYPE_ANNOTATION_TOKENS):
            token = t[k]
            if token[0] == "p":
                if token[1] in ("(", "["):
                    depth += 1
                elif token[1] in (")", "]"):
                    if depth == 0:
                        return "stop", k
                    depth -= 1
                elif depth == 0 and token[1] == "=>":
                    return "arrow", k
                elif depth == 0 and token[1] == "{":
                    if k > 0 and (
                        (t[k - 1][0] == "p" and t[k - 1][1] in (":", "|", "&", "<", ",", "?"))
                        or (t[k - 1][0] == "name" and t[k - 1][1] in ("is", "keyof", "extends"))
                    ):
                        closing = match_close(t, k)
                        if closing is None:
                            return "stop", k
                        k = closing
                    else:
                        return "brace", k
                elif depth == 0 and token[1] in (";", "}"):
                    return "stop", k
            k += 1
        return ("long" if j + MAX_TYPE_ANNOTATION_TOKENS <= len(t) else "stop"), k

    def is_parameter_list(self, k):
        """True when the `(` group at token `k` is the parameter list of a function or a method."""
        t = self.tokens
        close = match_close(t, k)
        if close is None:
            return False
        q = k - 1
        closing = None
        if punct(self.at(q), ">"):
            depth = 0
            for m in range(q, max(-1, q - MAX_TYPE_ARGUMENT_TOKENS), -1):
                if punct(t[m], ">"):
                    depth += 1
                elif punct(t[m], "<"):
                    depth -= 1
                    if depth == 0:
                        closing = m
                        break
            if closing is not None:
                q = closing - 1
        if name_is(self.at(q), "function"):
            return True
        if punct(self.at(q), "*") and name_is(self.at(q - 1), "function"):
            return True
        if self.at(q)[0] == "name" and (
            name_is(self.at(q - 1), "function") or (punct(self.at(q - 1), "*") and name_is(self.at(q - 2), "function"))
        ):
            return True
        after = self.at(close + 1)
        if punct(after, "=>"):
            return True
        if punct(after, ":"):
            return self.scan_return_type(close + 2)[0] in ("arrow", "brace", "long")
        if punct(self.at(q), "?"):
            q -= 1  # an optional method: `n?(q) {`
        before = self.at(q - 1)
        return (
            punct(after, "{")
            and (self.at(q)[0] in ("name", "str", "num") or punct(self.at(q), "]"))
            and self.at(q)[1] not in NOT_PARAMETER_NAMES
            and not (punct(before, ".") or punct(before, "?.") or name_is(before, "new"))
        )

    def parameter_names(self, k, close):
        """(name, token) of each parameter of the parameter list [k, close]."""
        t = self.tokens
        names = []
        j = k + 1
        while j < close:
            while j < close:
                if punct(t[j], "@"):
                    j += 1
                    while j < close and (t[j][0] == "name" or punct(t[j], ".")):
                        j += 1
                    if j < close and punct(t[j], "("):
                        end_call = match_close(t, j)
                        j = (end_call if end_call is not None else close) + 1
                    continue
                if (
                    t[j][0] == "name"
                    and t[j][1] in PARAMETER_MODIFIERS
                    and j + 1 < close
                    and (t[j + 1][0] == "name" or punct(t[j + 1], "{") or punct(t[j + 1], "["))
                ):
                    j += 1
                    continue
                break
            if j < close and punct(t[j], "..."):
                j += 1
            if j < close:
                if t[j][0] == "name":
                    names.append((t[j][1], j))
                elif punct(t[j], "{") or punct(t[j], "["):
                    names += self.pattern_names(j)
            j = self.item_end(j) + 1
        return names

    def body_range(self, c):
        """(lo, hi) of the body of the function whose parameter list ends at token `c` (the `)`, or the
        name of a single arrow parameter), or None when no body is found."""
        t = self.tokens
        j = c + 1
        if punct(self.at(j), ":"):
            kind, j = self.scan_return_type(j + 1)
            if kind not in ("arrow", "brace"):
                return None
        if punct(self.at(j), "=>"):
            j += 1
            if punct(self.at(j), "{"):
                return j, self.block_end(j)
            return j, max(j, min(self.value_end(j), len(t)) - 1)
        if punct(self.at(j), "{"):
            return j, self.block_end(j)
        return None


def find_pg_statements(source, tokens, templates, detector, receivers, tags):
    """The (offset, statement, end offset) triples of the `<receiver>.query(...)` calls whose first argument is
    followed (see PgCalls), and the list of the calls that are not."""
    by_index = {template.token_index: template for template in templates}
    return PgCalls(source, tokens, by_index, detector, receivers, tags).run()


def extract_js_file(source, given_tags, jsx=False, tsx=False, given_receivers=None, spans=None):
    """With a dict as `spans`, the call fills it with `statement index -> (start offset, end offset)`
    of the SQL value of each `pg` statement (character offsets in `source.text`, the end exclusive)."""
    tokens, templates = tokenize_js(source, jsx, tsx)
    detector = Detector(tokens, given_tags if given_tags is not None else [])
    detected, factory_names = detector.run()
    tags = given_tags if given_tags is not None else detected
    given_receivers = given_receivers if given_receivers is not None else []
    receiver_detector = ReceiverDetector(tokens, given_receivers)
    detected_receivers = receiver_detector.run()
    receivers = detected_receivers + [name for name in given_receivers if name not in detected_receivers]
    reported = []
    for template in templates:
        found = tag_chain(tokens, template.token_index)
        if found is not None and found[0] in tags:
            template.tag = found[0]
            reported.append(template)
    entries = [(template.start, template) for template in reported]
    pg_entries, not_followed = find_pg_statements(source, tokens, templates, receiver_detector, set(receivers), tags)
    ends = {id(statement): end for _, statement, end in pg_entries}
    entries += [(offset, statement) for offset, statement, _ in pg_entries]
    entries.sort(key=lambda entry: entry[0])
    index_of = {id(item): k for k, (_, item) in enumerate(entries) if isinstance(item, Template)}
    statements = []
    for offset, item in entries:
        if not isinstance(item, Template):
            if spans is not None:
                spans[len(statements)] = (offset, ends[id(item)])
            statements.append(item)
            continue
        parent = item.enclosing
        while parent is not None and id(parent) not in index_of:
            parent = parent.enclosing
        statements.append(template_statement(source, item, None if parent is None else index_of[id(parent)]))
    return detected, factory_names, tags, statements, detected_receivers, receivers, not_followed


def template_interpolations(source, template):
    """(body, interpolation records) of a template: the text between the backticks, as written."""
    base = template.start + 1
    body = source.text[base : template.end]
    spans = {item["start"] - base: item["end"] - base for item in template.interpolations}
    tokens, found = SqlLexer(body, lambda i: spans.get(i)).run()
    assign_positions(tokens, found)
    positions = {item["start"]: item.get("position", "keyword") for item in found}
    interpolations = [
        interpolation_record(source, item, positions.get(item["start"] - base, "keyword"))
        for item in template.interpolations
    ]
    return body, interpolations


def template_statement(source, template, parent):
    body, interpolations = template_interpolations(source, template)
    return {
        "source": "template",
        "tag": template.tag,
        "start_line": source.line(template.start),
        "end_line": source.line(template.end),
        "text": body,
        "parent": parent,
        "interpolations": interpolations,
    }


# ------------------------------------------------------------------- main


def name_list(option, value, what):
    """The names of a comma-separated option value (each a name or a dotted member form), no repeats."""
    if value is None:
        return None
    names = []
    for element in value.split(","):
        element = element.strip(" ")
        if not is_tag_chain(element):
            raise UsageError("%s needs %s joined by commas, got: %s" % (option, what, value))
        if element not in names:
            names.append(element)
    return names


def parse_arguments(argv):
    file_argument = None
    values = {"--tags": None, "--receivers": None}
    i = 0
    while i < len(argv):
        argument = argv[i]
        if argument in values:
            if values[argument] is not None or i + 1 >= len(argv):
                raise UsageError(argument + " needs exactly one value")
            values[argument] = argv[i + 1]
            i += 2
            continue
        if argument.startswith("-") and argument != "-":
            raise UsageError("unknown option: " + argument)
        if file_argument is not None:
            raise UsageError("exactly one file argument is needed")
        file_argument = argument
        i += 1
    if file_argument is None:
        raise UsageError("usage: extract.py <file> [--tags <t1,t2,...>] [--receivers <r1,r2,...>]")
    tags = name_list("--tags", values["--tags"], "tag names")
    receivers = name_list("--receivers", values["--receivers"], "receiver names")
    extension = os.path.splitext(file_argument)[1].lower()
    if extension == SQL_EXTENSION:
        form = "sql"
    elif extension in JS_EXTENSIONS:
        form = "js"
    else:
        raise UsageError("unsupported file form: " + (extension or file_argument))
    return file_argument, tags, receivers, form, extension in JSX_EXTENSIONS, extension == ".tsx"


def result(
    file_argument, form, error=None, detected=(), factory_names=(), tags=(), statements=(),
    detected_receivers=(), receivers=(), not_followed=(),
):
    return {
        "file": file_argument,
        "form": form,
        "detected_tags": list(detected),
        "factory_names": list(factory_names),
        "tags": list(tags),
        "detected_receivers": list(detected_receivers),
        "receivers": list(receivers),
        "statements": list(statements),
        "not_followed": list(not_followed),
        "error": error,
    }


def main(argv):
    try:
        file_argument, tags, receivers, form, jsx, tsx = parse_arguments(argv)
    except UsageError as error:
        sys.stderr.write(str(error).replace("\n", " ") + "\n")
        return 2
    try:
        with open(file_argument, "rb") as handle:
            text = handle.read().decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        output = result(file_argument, form, {"message": "cannot read the file: " + str(error), "line": None})
        return emit(output, 1)
    if text.startswith("\ufeff"):
        text = text[1:]
    source = Source(text)
    try:
        if form == "sql":
            output = result(file_argument, form, statements=extract_sql_file(source))
        else:
            (
                detected, factory_names, matched, statements, detected_receivers, matched_receivers, not_followed
            ) = extract_js_file(source, tags, jsx, tsx, receivers)
            output = result(
                file_argument, form, None, detected, factory_names, matched, statements,
                detected_receivers, matched_receivers, not_followed,
            )
    except ExtractError as error:
        output = result(file_argument, form, {"message": error.message, "line": error.line})
        return emit(output, 1)
    return emit(output, 0)


def emit(output, code):
    sys.stdout.buffer.write((json.dumps(output, ensure_ascii=False) + "\n").encode("utf-8"))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
