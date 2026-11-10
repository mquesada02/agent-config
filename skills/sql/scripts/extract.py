#!/usr/bin/env python3
"""Find the SQL of a source file and print one JSON object.

Usage: python3 extract.py <file> [--tags <t1,t2,...>]

The file form comes from the extension: `.sql` (statements) or a JavaScript or
TypeScript extension (postgres.js tagged templates). For each template or
statement the output has its line range, its tag, its text and its
interpolations, each with a position (`value`, `fragment` or `keyword`).
The output also lists the tags that the file shows (tag detection).

Exit code: 0 when the file was read, 1 when "error" is set (the JSON is still
printed), 2 for a usage error (one line on stderr, nothing on stdout).
"""
import bisect
import json
import os
import re
import sys

JS_EXTENSIONS = (".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx")
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


def tokenize_js(source):
    """Return (tokens, templates). Raises ExtractError on an unterminated construct."""
    text, n = source.text, len(source.text)
    tokens, templates = [], []
    stack = []  # ["tpl", Template] or ["expr", Template, depth]
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
                    raise ExtractError("unterminated template literal", source.line(stack[0][1].start))
                raise ExtractError("unterminated block comment", source.line(i))
            i = j + 2
        elif c in "'\"":
            j = i + 1
            while j < n:
                d = text[j]
                if d == "\\":
                    j += 2
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
                if c == "{" and stack and stack[-1][0] == "expr":
                    stack[-1][2] += 1
                elif c == "}" and stack and stack[-1][0] == "expr":
                    if stack[-1][2] == 0:
                        record = stack[-1][1]
                        record.interpolations[-1]["end"] = i + 1
                        tokens.append(("iend", "}", i, i + 1))
                        stack.pop()
                        i += 1
                        continue
                    stack[-1][2] -= 1
                tokens.append(("p", c, i, i + 1))
                i += 1
    if stack:
        raise ExtractError("unterminated template literal", source.line(stack[0][1].start))
    return tokens, templates


def slash_starts_regex(tokens):
    if not tokens:
        return True
    kind, text = tokens[-1][0], tokens[-1][1]
    if kind in ("num", "str", "regex", "tpl_end"):
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
        t = self.tokens
        factories = self.factories()
        for i, token in enumerate(t):
            if token[0] != "name":
                continue
            if not self.assigned_from_factory(i, factories):
                continue
            previous = self.at(i - 1)
            if punct(previous, ":"):
                continue
            if previous[0] == "name" and previous[1] in ("const", "let", "var"):
                self.add_tag(token[1], token[2])
            elif punct(previous, "."):
                found = chain_ending_at(t, i)
                if found is not None:
                    self.add_tag(found[0], t[found[1]][2])
            elif self.in_class[i]:
                if not self.is_static(i):
                    self.add_tag("this." + token[1], token[2])
            else:
                self.add_tag(token[1], token[2])

    def is_static(self, i):
        j = i - 1
        while j >= 0 and self.tokens[j][0] == "name" and self.tokens[j][1] in CLASS_MODIFIERS:
            if self.tokens[j][1] == "static":
                return True
            j -= 1
        return False

    def assigned_from_factory(self, i, factories):
        """NAME [: type] = [await] FACTORY( ... starting at the name token `i`."""
        t = self.tokens
        j = i + 1
        if punct(self.at(j), ":"):
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
                    elif token[1] == ";":
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
        if name_is(self.at(j), "await"):
            j += 1
        callee = self.at(j)
        return callee[0] == "name" and callee[1] in factories and punct(self.at(j + 1), "(")

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


def extract_js_file(source, given_tags):
    tokens, templates = tokenize_js(source)
    detector = Detector(tokens, given_tags if given_tags is not None else [])
    detected, factory_names = detector.run()
    tags = given_tags if given_tags is not None else detected
    reported = []
    for template in templates:
        found = tag_chain(tokens, template.token_index)
        if found is not None and found[0] in tags:
            template.tag = found[0]
            reported.append(template)
    index_of = {id(template): k for k, template in enumerate(reported)}
    statements = []
    for template in reported:
        parent = template.enclosing
        while parent is not None and id(parent) not in index_of:
            parent = parent.enclosing
        statements.append(template_statement(source, template, None if parent is None else index_of[id(parent)]))
    return detected, factory_names, tags, statements


def template_statement(source, template, parent):
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
    return {
        "tag": template.tag,
        "start_line": source.line(template.start),
        "end_line": source.line(template.end),
        "text": body,
        "parent": parent,
        "interpolations": interpolations,
    }


# ------------------------------------------------------------------- main


def parse_arguments(argv):
    file_argument, tags_value = None, None
    i = 0
    while i < len(argv):
        argument = argv[i]
        if argument == "--tags":
            if tags_value is not None or i + 1 >= len(argv):
                raise UsageError("--tags needs exactly one value")
            tags_value = argv[i + 1]
            i += 2
            continue
        if argument.startswith("-") and argument != "-":
            raise UsageError("unknown option: " + argument)
        if file_argument is not None:
            raise UsageError("exactly one file argument is needed")
        file_argument = argument
        i += 1
    if file_argument is None:
        raise UsageError("usage: extract.py <file> [--tags <t1,t2,...>]")
    tags = None
    if tags_value is not None:
        tags = []
        for element in tags_value.split(","):
            element = element.strip(" ")
            if not is_tag_chain(element):
                raise UsageError("--tags needs tag names joined by commas, got: " + tags_value)
            if element not in tags:
                tags.append(element)
    extension = os.path.splitext(file_argument)[1].lower()
    if extension == SQL_EXTENSION:
        form = "sql"
    elif extension in JS_EXTENSIONS:
        form = "js"
    else:
        raise UsageError("unsupported file form: " + (extension or file_argument))
    return file_argument, tags, form


def result(file_argument, form, error=None, detected=(), factory_names=(), tags=(), statements=()):
    return {
        "file": file_argument,
        "form": form,
        "detected_tags": list(detected),
        "factory_names": list(factory_names),
        "tags": list(tags),
        "statements": list(statements),
        "error": error,
    }


def main(argv):
    try:
        file_argument, tags, form = parse_arguments(argv)
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
            detected, factory_names, matched, statements = extract_js_file(source, tags)
            output = result(file_argument, form, None, detected, factory_names, matched, statements)
    except ExtractError as error:
        output = result(file_argument, form, {"message": error.message, "line": error.line})
        return emit(output, 1)
    return emit(output, 0)


def emit(output, code):
    sys.stdout.buffer.write((json.dumps(output, ensure_ascii=False) + "\n").encode("utf-8"))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
