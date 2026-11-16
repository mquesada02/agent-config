#!/usr/bin/env python3
"""Rewrite one `pg` statement of a JavaScript or TypeScript file and print one JSON object.

Usage: python3 write_back_pg.py <file> --index <n> --sql-file <path> (--output <path> | --stdout)
           [--tags <t1,t2,...>] [--receivers <r1,r2,...>]

`--index` is the position of the statement in the `statements` list that
`extract.py` prints for <file> with the same `--tags` and `--receivers`.
`--sql-file` holds the new SQL value, exactly as it goes between the quotes,
except for the tail rule: when the value is written as a template and holds a
line feed, the text after its last line feed (only spaces and tabs) is replaced
by the indent of the line of <file> that holds the start of the replaced span
(the Write tool removes trailing spaces, so the caller cannot write that indent).
The script writes <file> with that statement replaced to `--output` (a new path) and
never writes <file>: the caller copies the output over it. With `--stdout` the
script writes no file, and the JSON holds the new file text in `text` (for a
shell that cannot write any file). An `--output` that cannot be written gives
exit code 2 and a stderr line that starts with the text of OUTPUT_FAILURE.

A `+` chain becomes one untagged template. A quoted string becomes an untagged
template when the new value has a line feed or a carriage return, and keeps its
quote character otherwise. An untagged template stays one. A followed `const` is
rewritten at its definition.

The script refuses, and writes nothing, when the statement is not a `pg`
statement, is `dynamic`, is a chain with a comment between its pieces, or when
the new value differs from the old one in anything but whitespace and keyword
case (checks `extract`, `index`, `not_pg`, `dynamic`, `chain_comment`,
`value_changed`, `round_trip`). The refusal is JSON with `ok` false, a `check`
and a `reason`.

Exit code: 0 when `ok` is true, 1 for a refusal (the JSON is still printed), 2 for
a usage error (one line on stderr, nothing on stdout, nothing written).
"""
import json
import os
import re
import string
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import extract  # noqa: E402
import sql_text  # noqa: E402

OUTPUT_FAILURE = "cannot write output file:"
BLANKS = " \t\n\r\f"
IDENT_START = "A-Za-z_\x80-\U0010ffff"
WORD = re.compile(rf"[{IDENT_START}][{IDENT_START}0-9$]*")
NUMBER = re.compile(r"[0-9][0-9.]*(?:[eE][-+]?[0-9]+)?")
PLACEHOLDER = re.compile(r"\$[0-9]+")
DOLLAR_TAG = re.compile(rf"\$(?:[{IDENT_START}][{IDENT_START}0-9]*)?\$")
OPERATOR_CHARS = frozenset("+-*/<>=~!@#%^&|`?")
PREFIX_WORDS = frozenset("BXNEU")
UPPER = str.maketrans(string.ascii_lowercase, string.ascii_uppercase)


class Refused(Exception):
    def __init__(self, check, reason):
        super().__init__(reason)
        self.check = check
        self.reason = reason


# --- the SQL items of a value ------------------------------------------------


def quoted_end(text, start, backslash):
    """The index after the quoted text that opens at `start` (the end of the text when it is not closed)."""
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


def block_comment_end(text, start):
    depth = 1
    index = start + 2
    while index < len(text) and depth:
        if text.startswith("/*", index):
            depth += 1
            index += 2
        elif text.startswith("*/", index):
            depth -= 1
            index += 2
        else:
            index += 1
    return index


def lex(text):
    """The items of a SQL value as (kind, raw, glued, line_break) tuples: whitespace is dropped.

    `glued` is true when no blank or comment stands between the item and the one before it, and
    `line_break` is true when a line break does."""
    items = []
    index = 0
    length = len(text)
    blank = False
    line_break = False
    while index < length:
        char = text[index]
        if char in BLANKS:
            blank = True
            line_break = line_break or char in "\r\n"
            index += 1
            continue
        start = index
        if text.startswith("--", index):
            end = index
            while end < length and text[end] not in "\r\n":
                end += 1
            kind, index = "comment", end
        elif text.startswith("/*", index):
            kind, index = "comment", block_comment_end(text, index)
        elif char == "'":
            kind, index = "string", quoted_end(text, index, False)
        elif char == '"':
            kind, index = "qident", quoted_end(text, index, False)
        elif char == "$":
            if match := PLACEHOLDER.match(text, index):
                kind, index = "param", match.end()
            elif tag := DOLLAR_TAG.match(text, index):
                close = text.find(tag.group(), tag.end())
                kind, index = "string", length if close < 0 else close + len(tag.group())
            else:
                kind, index = "punct", index + 1
        elif match := WORD.match(text, index):
            if match.group() in ("e", "E") and text.startswith("'", match.end()):
                kind, index = "string", quoted_end(text, match.end(), True)
            else:
                kind, index = "word", match.end()
        elif match := NUMBER.match(text, index):
            kind, index = "number", match.end()
        elif char in OPERATOR_CHARS:
            end = index + 1
            while end < length and text[end] in OPERATOR_CHARS and not text.startswith(("--", "/*"), end):
                end += 1
            kind, index = "operator", end
        elif text.startswith("::", index):
            kind, index = "punct", index + 2
        else:
            kind, index = "punct", index + 1
        items.append((kind, text[start:index], not blank and bool(items), line_break))
        blank = False
        line_break = False
    return items


def words_match(old, new):
    if old == new:
        return True
    folded = old.translate(UPPER)
    return folded == new.translate(UPPER) and folded in sql_text.KEYWORD_SET


def glue_matters(before, item):
    """True when white space between the two items changes what SQL reads: a number or a `$n` next to
    a word, a number, a `$n` or a dot (`.5` and `. 5`, `1 a` and `1a`)."""
    if before[0] in ("number", "param"):
        other = item
    elif item[0] in ("number", "param"):
        other = before
    else:
        return False
    return other[0] in ("number", "word", "param") or other[1] == "."


def first_difference(old_text, new_text):
    """None when the two values are the same SQL up to whitespace and keyword case, else a description."""
    old_items = lex(old_text)
    new_items = lex(new_text)
    for position in range(max(len(old_items), len(new_items))):
        old = old_items[position] if position < len(old_items) else None
        new = new_items[position] if position < len(new_items) else None
        if old is None or new is None or old[0] != new[0]:
            return position, old, new
        if old[0] == "word":
            if not words_match(old[1], new[1]):
                return position, old, new
        elif old[1] != new[1]:
            return position, old, new
        if position > 0 and glue_matters(old_items[position - 1], old) and old[2] != new[2]:
            return position, old, new
        if (
            position >= 2 and old[0] in ("string", "qident") and old_items[position - 1][1] == "&"
            and old_items[position - 2][1] in ("U", "u")
            and (old[2] != new[2] or old_items[position - 1][2] != new_items[position - 1][2])
        ):
            return position, old, new
        if old[0] == "string" and position > 0:
            before = old_items[position - 1]
            if before[0] == "string" and old[3] != new[3]:
                return position, old, new
            if (before[0] == "word" and before[1].upper() in PREFIX_WORDS or before[1] == "&") and old[2] != new[2]:
                return position, old, new
    return None


def describe(item):
    return "nothing" if item is None else "%s %s" % (item[0], json.dumps(item[1][:60], ensure_ascii=False))


# --- the new literal ------------------------------------------------------------


def encode_template(value):
    body = value.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${").replace("\r", "\\r")
    return "`" + body + "`"


def closing_indent(value, text, first):
    """The tail rule: a template value that holds a line feed ends with the indent of the line of
    `text` that holds the offset `first` (the Write tool removes trailing spaces, so the caller
    cannot write it). A tail with any other character is left as it is."""
    cut = value.rfind("\n") + 1
    if cut == 0 or value[cut:].strip(" \t"):
        return value
    line_start = text.rfind("\n", 0, first) + 1
    indent = re.match(r"[ \t]*", text[line_start:]).group()
    return value[:cut] + indent


def encode_string(value, quote):
    body = value.replace("\\", "\\\\").replace(quote, "\\" + quote)
    body = body.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return quote + body + quote


# --- the file ---------------------------------------------------------------------


def has_comment(source, tokens, first, end):
    """True when the source of the chain [first, end) holds a comment (the tokenizer drops comments,
    so a gap between two consecutive tokens that is not white space is one). A template piece runs
    from its `tpl` token to its `tpl_end` token, and its body is not a gap."""
    inside = [token for token in tokens if token[2] >= first and token[3] <= end]
    previous_end = first
    skip_to = None
    for kind, _, start, stop in inside:
        if skip_to is not None:
            if kind == "tpl_end":
                skip_to, previous_end = None, stop
            continue
        if source.text[previous_end:start].strip():
            return True
        previous_end = stop
        if kind == "tpl":
            skip_to = stop
    return bool(source.text[previous_end:end].strip())


class Context:
    """The command line of one run."""

    def __init__(self, argv):
        # `--stdout` takes no value, and parse_arguments accepts only options that take one.
        self.stdout = "--stdout" in argv
        if argv.count("--stdout") > 1:
            raise sql_text.UsageError("--stdout is given twice")
        argv = [argument for argument in argv if argument != "--stdout"]
        positional, options = sql_text.parse_arguments(
            argv, 1, single=("--index", "--sql-file", "--output", "--tags", "--receivers")
        )
        self.path = os.path.abspath(positional[0])
        if not os.path.isfile(self.path):
            raise sql_text.UsageError("not a file: " + positional[0])
        self.extension = os.path.splitext(self.path)[1].lower()
        if self.extension not in extract.JS_EXTENSIONS:
            raise sql_text.UsageError("unsupported file form: " + positional[0])
        for name in ("--index", "--sql-file"):
            if name not in options:
                raise sql_text.UsageError(name + " is required")
        if self.stdout == ("--output" in options):
            raise sql_text.UsageError("give exactly one of --output and --stdout")
        if not re.fullmatch(r"[0-9]{1,9}", options["--index"][0]):
            raise sql_text.UsageError("--index needs a non-negative whole number of at most 9 digits")
        self.index = int(options["--index"][0])
        self.output = None
        if not self.stdout:
            self.output = os.path.abspath(options["--output"][0])
            if os.path.realpath(self.output) == os.path.realpath(self.path):
                raise sql_text.UsageError("--output is the file itself")
            if os.path.lexists(self.output):
                raise sql_text.UsageError("--output already exists: " + options["--output"][0])
        try:
            with open(options["--sql-file"][0], "rb") as handle:
                self.value = handle.read().decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise sql_text.UsageError("cannot read the --sql-file: %s" % error)
        self.tags = options.get("--tags", [None])[0]
        if self.tags is not None and not [tag for tag in self.tags.split(",") if tag]:
            raise sql_text.UsageError("--tags needs at least one tag")
        self.receivers = options.get("--receivers", [None])[0]
        if self.receivers is not None:
            sql_text.check_receivers(self.receivers)
        try:
            self.tag_list = extract.name_list("--tags", self.tags, "tag names")
            self.receiver_list = extract.name_list("--receivers", self.receivers, "receiver names")
        except extract.UsageError as error:
            raise sql_text.UsageError(error)
        self.jsx = self.extension in extract.JSX_EXTENSIONS
        self.tsx = self.extension == ".tsx"


def read_text(path):
    with open(path, "rb") as handle:
        text = handle.read().decode("utf-8")
    bom = text.startswith("\ufeff")
    return bom, text[1:] if bom else text


def read_in_process(context, source, spans=None):
    try:
        return extract.extract_js_file(
            source, context.tag_list, context.jsx, context.tsx, context.receiver_list, spans
        )[3]
    except extract.ExtractError as error:
        raise Refused("extract", "the extractor cannot read the file: %s" % error.message)


def rewrite(context, report):
    """Fill `report` and return the new file text, with the BOM of the file. Raises Refused."""
    data, message = sql_text.run_extractor(context.path, context.tags, context.receivers)
    if data is None:
        raise Refused("extract", "the extractor cannot read the file: %s" % message)
    statements = data["statements"]
    if context.index >= len(statements):
        raise Refused("index", "the index %d is out of range: the file has %d statements" % (context.index, len(statements)))
    statement = statements[context.index]
    if statement["source"] != "pg":
        raise Refused("not_pg", "the statement at index %d is not a pg statement (source %s)" % (context.index, statement["source"]))
    if statement["pg"]["dynamic"]:
        raise Refused("dynamic", "the statement at index %d is dynamic: it is never formatted" % context.index)

    bom, text = read_text(context.path)
    spans = {}
    source = extract.Source(text)
    found = read_in_process(context, source, spans)
    if len(found) != len(statements) or found[context.index]["source"] != "pg" or found[context.index]["text"] != statement["text"]:
        raise Refused("extract", "the in-process read of the file does not agree with the extractor output")
    first, end = spans[context.index]
    kind = statement["pg"]["kind"]
    report.update(
        from_kind=kind, start_line=source.line(first), end_line=source.line(end - 1),
        const_name=statement["pg"]["const_name"],
    )

    if kind == "chain":
        tokens, _ = extract.tokenize_js(source, context.jsx, context.tsx)
        if has_comment(source, tokens, first, end):
            raise Refused("chain_comment", "the chain has a comment between its pieces: one template cannot hold it")
    difference = first_difference(statement["text"], context.value)
    if difference is not None:
        position, old, new = difference
        raise Refused(
            "value_changed",
            "the new value differs from the old one at item %d: %s became %s" % (position + 1, describe(old), describe(new)),
        )

    value = context.value
    if kind == "literal" and "\n" not in value and "\r" not in value:
        quote = text[first]
        literal, to_kind = encode_string(value, quote), "literal"
    else:
        value = closing_indent(value, text, first)
        literal, to_kind = encode_template(value), "template"
    new_text = text[:first] + literal + text[end:]

    try:
        again = read_in_process(context, extract.Source(new_text))
    except Refused as refusal:
        raise Refused("round_trip", refusal.reason)
    result = again[context.index] if len(again) == len(found) else None
    if (
        result is None or result["source"] != "pg" or result["pg"]["kind"] != to_kind
        or result["pg"]["dynamic"] or result["text"] != value
    ):
        raise Refused("round_trip", "the extractor does not read the new text back as the new value")
    report.update(
        to_kind=to_kind, became_template=kind != "template" and to_kind == "template", changed=new_text != text
    )
    return ("\ufeff" if bom else "") + new_text


def main(argv):
    try:
        context = Context(argv[1:])
    except sql_text.UsageError as error:
        return sql_text.usage_failure(error)
    report = {
        "ok": True, "check": None, "reason": None, "file": context.path, "index": context.index,
        "from_kind": None, "to_kind": None, "became_template": None, "changed": False, "output": None,
        "text": None, "start_line": None, "end_line": None, "const_name": None,
    }
    try:
        new_text = rewrite(context, report)
        if context.stdout:
            report.update(text=new_text)
        else:
            created = False
            try:
                with open(context.output, "xb") as handle:
                    created = True
                    handle.write(new_text.encode("utf-8"))
            except FileExistsError:
                return sql_text.usage_failure("--output already exists: " + context.output)
            except OSError as error:
                if created:
                    try:
                        os.unlink(context.output)
                    except OSError:
                        pass
                return sql_text.usage_failure("%s %s" % (OUTPUT_FAILURE, error))
            report.update(output=context.output)
    except Refused as refusal:
        report.update(ok=False, check=refusal.check, reason=refusal.reason)
    sys.stdout.buffer.write((json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
