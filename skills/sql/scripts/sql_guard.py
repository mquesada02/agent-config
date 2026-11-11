"""The statement guard of `pg_run` (stdlib only). It is a module, not a command.

`check_select(text)` accepts exactly one `SELECT` or `WITH ... SELECT` and refuses
everything else. It has its own small tokenizer, because it needs the text of
quoted identifiers, a report of an unterminated quote and the `U&"` form, which
`sql_text.mask` does not give. It fails closed: when a rule is in doubt, it refuses.

It returns `(sql, None)` with the statement text cut at its final `;`, or
`(None, refusal)` where `refusal` has `reason`, `message` and `static_review_only`.
The reasons are checked in this order: `empty`, `unterminated`,
`multiple_statements`, `write_statement`, `not_select`, `data_modifying`,
`forbidden_function`, `unicode_identifier`.

`check_write(text)` accepts exactly one `INSERT`, `UPDATE`, `DELETE` or `MERGE`, with an optional
`WITH` list that it reads as a grammar (it fails closed). It uses the same tokenizer. It returns
`(result, None)` where `result` has `sql`, `nextval`, `scan` and `targets`, or `(None, refusal)`.
Its reasons, in this order: `empty`, `unterminated`, `multiple_statements`, `not_write`,
`forbidden_function` (`set_config` only), `unicode_identifier`. The names in `scan` are functions
whose effect `ROLLBACK` cannot undo, or that run SQL from a string argument, so the run goes down
to a plain `EXPLAIN`. The tokens are the only input: the guard never connects.

`check_diff(text)` is the guard of one statement of `pg_run diff`. It runs `check_select`, then refuses the
names of the scan lists below (string-SQL functions and effects that `ROLLBACK` cannot undo) and unbalanced
parentheses, and returns `(result, None)` with `sql` and `order` (the sort keys of a top-level `ORDER BY`), or
`(None, refusal)` with the messages of `DIFF_MESSAGES`.
"""
import collections
import re

Token = collections.namedtuple("Token", "kind value start")

# The lexer classes of PostgreSQL (scan.l): every non-ASCII character is an identifier character, and
# only ASCII blanks (space, tab, line breaks, form feed, vertical tab) are whitespace. Python's Unicode classes (`\w`, `str.isspace`) would split tokens
# where the server does not, and could hide a `;` in a dollar-quoted string that the server never opens.
IDENT_START = "A-Za-z_\x80-\U0010ffff"
WHITESPACE = " \t\n\r\f\v"
WORD = re.compile(rf"[{IDENT_START}][{IDENT_START}0-9$]*")
LINE_END = re.compile(r"[\n\r]")  # PostgreSQL ends a `--` comment at a line feed or a carriage return
# The text between two parts of one string literal (scan.l `quotecontinue`): blanks and `--` comments,
# at least one line break, and the next opening quote (the last character of the match).
# Each group has one way to match a text (no nested quantifier on a repeated group), so a failed match is linear.
STRING_CONTINUATION = re.compile(r"[ \t\f\v]*(?:--[^\n\r]*)?[\n\r](?:[ \t\n\r\f\v]|--[^\n\r]*[\n\r])*'")
# A number takes an optional exponent and stops at the next letter, so a word that is glued to it
# (`1into`, `1e5into`) stays visible.
NUMBER = re.compile(r"[0-9][0-9.]*(?:[eE][-+]?[0-9]+)?")  # ASCII digits only: `\d` also matches Unicode digits
PLACEHOLDER = re.compile(r"\$[0-9]+")
DOLLAR_TAG = re.compile(rf"\$(?:[{IDENT_START}][{IDENT_START}0-9]*)?\$")

WRITE_WORDS = frozenset("INSERT UPDATE DELETE MERGE".split())
SELECT_WORDS = frozenset("SELECT WITH".split())
# A first token that EXPLAIN can take but that this guard does not accept: no static-only review.
ANALYZABLE_FIRST = frozenset("TABLE VALUES".split())
DATA_MODIFYING_WORDS = WRITE_WORDS | {"INTO"}
FORBIDDEN_NAMES = frozenset(["set_config", "pg_notify", "lo_export"])
FORBIDDEN_PREFIXES = ("pg_advisory", "pg_try_advisory", "dblink")

MESSAGES = {
    "empty": "The statement is empty.",
    "unterminated": "The statement has an unterminated quote, dollar-quoted string or comment.",
    "multiple_statements": "Select mode accepts one statement only.",
    "write_statement": "A write statement needs --mode write.",
    "not_select": "Select mode accepts only SELECT or WITH ... SELECT.",
    "data_modifying": "The statement holds INSERT, UPDATE, DELETE, MERGE or INTO.",
    "forbidden_function": "The statement calls a function that select mode refuses.",
    "unicode_identifier": "A Unicode-escaped identifier (U&\") is refused.",
}

# Write mode has its own message table: no write refusal carries a select-mode text.
WRITE_MESSAGES = {
    "empty": "The statement is empty.",
    "unterminated": "The statement has an unterminated quote, dollar-quoted string or comment.",
    "multiple_statements": "Write mode accepts one statement only.",
    "not_write_select": "Write mode accepts only INSERT, UPDATE, DELETE or MERGE. Use select mode for this statement.",
    "not_write_other": (
        "Write mode accepts only INSERT, UPDATE, DELETE or MERGE (with an optional WITH list). "
        "Review this statement by reading only."
    ),
    "forbidden_function": "The statement calls set_config, which write mode refuses.",
    "unicode_identifier": "A Unicode-escaped identifier (U&\") is refused.",
}

# Functions whose effect ROLLBACK cannot undo (a sequence, a session lock, a file, a remote call), or that
# run SQL from a string argument that the guard cannot scan. A hit downgrades the run to a plain EXPLAIN.
SCAN_NAMES = frozenset(["lo_export", "setval", "ts_stat", "connectby"])
SCAN_PREFIXES = ("dblink", "query_to_xml", "cursor_to_xml", "crosstab")
ADVISORY_PREFIXES = ("pg_advisory", "pg_try_advisory")


def _quoted_end(text, start, quote, backslash):
    """Index after the closing quote of the quoted text that opens at `start`, or -1."""
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
    return -1


def _escape_string_end(text, start):
    """Index after an `E'...'` string that opens at `start`, with its continuations, or -1.
    The server keeps the escape mode over a continuation (a quote, blanks and `--` comments that hold
    a line break, then a quote), so the guard must read each continued part with backslash escapes too."""
    end = _quoted_end(text, start, "'", True)
    while end != -1:
        continuation = STRING_CONTINUATION.match(text, end)
        if not continuation:
            return end
        end = _quoted_end(text, continuation.end() - 1, "'", True)
    return -1


def tokenize(text):
    """The tokens of `text` and whether a quote, dollar-quote or comment is unterminated.
    Comments give no token (an unterminated comment only sets the flag)."""
    tokens = []
    unterminated = False
    index = 0
    while index < len(text):
        char = text[index]
        if char in WHITESPACE:
            index += 1
        elif text.startswith("--", index):
            end = LINE_END.search(text, index)
            index = len(text) if end is None else end.end()
        elif text.startswith("/*", index):
            depth = 1
            index += 2
            while index < len(text) and depth:
                if text.startswith("/*", index):
                    depth += 1
                    index += 2
                elif text.startswith("*/", index):
                    depth -= 1
                    index += 2
                else:
                    index += 1
            unterminated = unterminated or depth > 0
        elif char == "'":
            end = _quoted_end(text, index, "'", False)
            if end == -1:
                tokens.append(Token("bad", "", index))
                unterminated = True
                break
            tokens.append(Token("string", text[index:end], index))
            index = end
        elif char == '"':
            end = _quoted_end(text, index, '"', False)
            if end == -1:
                tokens.append(Token("bad", "", index))
                unterminated = True
                break
            tokens.append(Token("qident", text[index + 1:end - 1].replace('""', '"'), index))
            index = end
        elif char == "$":
            placeholder = PLACEHOLDER.match(text, index)
            if placeholder:
                tokens.append(Token("param", placeholder.group(), index))
                index = placeholder.end()
            elif tag := DOLLAR_TAG.match(text, index):
                end = text.find(tag.group(), tag.end())
                if end == -1:
                    tokens.append(Token("bad", "", index))
                    unterminated = True
                    break
                tokens.append(Token("string", text[index:end + len(tag.group())], index))
                index = end + len(tag.group())
            else:
                tokens.append(Token("punct", "$", index))
                index += 1
        elif word_match := WORD.match(text, index):
            word = word_match.group()
            if word.lower() == "e" and text.startswith("'", index + 1):
                end = _escape_string_end(text, index + 1)
                if end == -1:
                    tokens.append(Token("bad", "", index))
                    unterminated = True
                    break
                tokens.append(Token("string", text[index:end], index))
                index = end
            elif word.lower() == "u" and text.startswith('&"', index + 1):
                tokens.append(Token("uamp", word, index))
                index += len(word)
            else:
                tokens.append(Token("word", word, index))
                index += len(word)
        elif number_match := NUMBER.match(text, index):
            number = number_match.group()
            tokens.append(Token("number", number, index))
            index += len(number)
        else:
            tokens.append(Token("punct", char, index))
            index += 1
    return tokens, unterminated


def _refuse(reason, static_review_only=False):
    return None, {"reason": reason, "message": MESSAGES[reason], "static_review_only": static_review_only}


def _is_semicolon(token):
    return token.kind == "punct" and token.value == ";"


def _static_review_only(first):
    """True when EXPLAIN cannot take the statement, or it must not run (DDL, VACUUM, mode changes)."""
    if first.kind == "punct" and first.value == "(":
        return False
    if first.kind == "word":
        return first.value.upper() not in ANALYZABLE_FIRST
    return True


def _forbidden_name(token):
    if token.kind not in ("word", "qident"):
        return False
    name = token.value.lower()
    return name in FORBIDDEN_NAMES or name.startswith(FORBIDDEN_PREFIXES)


def check_select(text):
    tokens, unterminated = tokenize(text)
    significant = [t for t in tokens if not _is_semicolon(t)]
    if not significant:
        return _refuse("empty")
    if unterminated:
        return _refuse("unterminated")
    semicolons = [i for i, t in enumerate(tokens) if _is_semicolon(t)]
    if semicolons and semicolons[0] != len(tokens) - 1:
        return _refuse("multiple_statements")
    first = tokens[0]
    first_word = first.value.upper() if first.kind == "word" else None
    if first_word in WRITE_WORDS:
        return _refuse("write_statement")
    if first_word not in SELECT_WORDS:
        return _refuse("not_select", _static_review_only(first))
    for token in tokens:
        if token.kind == "word" and token.value.upper() in DATA_MODIFYING_WORDS:
            return _refuse("data_modifying")
    if any(_forbidden_name(t) for t in tokens):
        return _refuse("forbidden_function")
    if any(t.kind == "uamp" for t in tokens):
        return _refuse("unicode_identifier")
    cut = tokens[semicolons[0]].start if semicolons else len(text)
    return text[:cut].strip(), None


def _write_refuse(reason, static_review_only=False, message_key=None):
    message = WRITE_MESSAGES[message_key or reason]
    return None, {"reason": reason, "message": message, "static_review_only": static_review_only}


def _is_punct(token, value):
    return token.kind == "punct" and token.value == value


def _is_word(token, word):
    return token.kind == "word" and token.value.upper() == word


def _after_parentheses(tokens, index):
    """Index after the balanced `( ... )` that opens at `index`, or -1. A string is one token, so its parentheses do not count."""
    if index >= len(tokens) or not _is_punct(tokens[index], "("):
        return -1
    depth = 0
    for position in range(index, len(tokens)):
        if _is_punct(tokens[position], "("):
            depth += 1
        elif _is_punct(tokens[position], ")"):
            depth -= 1
            if depth == 0:
                return position + 1
    return -1


def _is_write_main(tokens):
    """True when `tokens` is `WITH [RECURSIVE] name [(columns)] AS [[NOT] MATERIALIZED] (...) [, ...]` and then
    `INSERT`, `UPDATE`, `DELETE` or `MERGE`. Any other shape is False (fail closed)."""
    index = 1
    if index < len(tokens) and _is_word(tokens[index], "RECURSIVE"):
        index += 1
    while True:
        if index >= len(tokens) or tokens[index].kind not in ("word", "qident"):
            return False
        index += 1
        if index < len(tokens) and _is_punct(tokens[index], "("):
            index = _after_parentheses(tokens, index)
            if index == -1:
                return False
        if index >= len(tokens) or not _is_word(tokens[index], "AS"):
            return False
        index += 1
        if index < len(tokens) and _is_word(tokens[index], "NOT"):
            index += 1
            if index >= len(tokens) or not _is_word(tokens[index], "MATERIALIZED"):
                return False
        if index < len(tokens) and _is_word(tokens[index], "MATERIALIZED"):
            index += 1
        index = _after_parentheses(tokens, index)
        if index == -1 or index >= len(tokens):
            return False
        if _is_punct(tokens[index], ","):
            index += 1
            continue
        return tokens[index].kind == "word" and tokens[index].value.upper() in WRITE_WORDS


def _write_static_review_only(tokens):
    """False when EXPLAIN can take the statement (so the model reads the plan, not only the text)."""
    first = tokens[0]
    if _is_punct(first, "("):
        return False
    if first.kind != "word":
        return True
    word = first.value.upper()
    if word in ANALYZABLE_FIRST:
        return False
    if word in SELECT_WORDS:
        return any(t.kind == "word" and t.value.upper() in DATA_MODIFYING_WORDS for t in tokens)
    return True


def _name_text(token):
    return token.value if token.kind == "word" else '"' + token.value.replace('"', '""') + '"'


def _write_targets(tokens):
    """The `[verb, name]` pairs of every position that can name a written table, at any depth."""
    targets = []
    for index, token in enumerate(tokens):
        if token.kind != "word":
            continue
        verb = token.value.upper()
        position = index + 1
        if verb in ("INSERT", "MERGE"):
            follower = "INTO"
        elif verb == "DELETE":
            follower = "FROM"
        elif verb == "UPDATE":
            follower = None
        else:
            continue
        if follower:
            if position >= len(tokens) or not _is_word(tokens[position], follower):
                continue
            position += 1
        if position < len(tokens) and _is_word(tokens[position], "ONLY"):
            position += 1
        parts = []
        while len(parts) < 3 and position < len(tokens) and tokens[position].kind in ("word", "qident"):
            parts.append(_name_text(tokens[position]))
            if position + 1 < len(tokens) and _is_punct(tokens[position + 1], ".") and len(parts) < 3:
                position += 2
            else:
                break
        if parts:
            targets.append([verb.lower(), ".".join(parts)])
    return targets


def _scan_name(token):
    if token.kind not in ("word", "qident"):
        return None
    name = token.value.lower()
    if name in SCAN_NAMES or name.startswith(SCAN_PREFIXES):
        return name
    if name.startswith(ADVISORY_PREFIXES) and "_xact_" not in name:
        return name
    return None


def check_write(text):
    tokens, unterminated = tokenize(text)
    significant = [t for t in tokens if not _is_semicolon(t)]
    if not significant:
        return _write_refuse("empty")
    if unterminated:
        return _write_refuse("unterminated")
    semicolons = [i for i, t in enumerate(tokens) if _is_semicolon(t)]
    if semicolons and semicolons[0] != len(tokens) - 1:
        return _write_refuse("multiple_statements")
    first_word = tokens[0].value.upper() if tokens[0].kind == "word" else None
    body = tokens[:semicolons[0]] if semicolons else tokens
    if not (first_word in WRITE_WORDS or (first_word == "WITH" and _is_write_main(body))):
        static = _write_static_review_only(tokens)
        select_form = first_word in SELECT_WORDS and not static
        return _write_refuse("not_write", static, "not_write_select" if select_form else "not_write_other")
    if any(t.kind in ("word", "qident") and t.value.lower() == "set_config" for t in tokens):
        return _write_refuse("forbidden_function")
    if any(t.kind == "uamp" for t in tokens):
        return _write_refuse("unicode_identifier")
    cut = tokens[semicolons[0]].start if semicolons else len(text)
    return {
        "sql": text[:cut].strip(WHITESPACE),
        "nextval": any(
            t.kind in ("word", "qident") and t.value.lower() == "nextval" and i + 1 < len(tokens) and _is_punct(tokens[i + 1], "(")
            for i, t in enumerate(tokens)
        ),
        "scan": sorted({name for name in map(_scan_name, tokens) if name}),
        "targets": _write_targets(body),
    }, None


# `diff` has no mode, so its refusals have their own message table (as write mode has).
DIFF_MESSAGES = {
    "empty": MESSAGES["empty"],
    "unterminated": MESSAGES["unterminated"],
    "multiple_statements": "diff accepts one statement for each of --a and --b.",
    "write_statement": "diff takes a SELECT only. A rewrite of a write statement is unproven (story 61).",
    "not_select": "diff accepts only SELECT or WITH ... SELECT.",
    "data_modifying": MESSAGES["data_modifying"],
    "forbidden_function": (
        "The statement calls a function that runs SQL from a string or has an effect that a rollback cannot undo, "
        "which diff refuses."
    ),
    "unicode_identifier": MESSAGES["unicode_identifier"],
    "unbalanced_parentheses": "The parentheses of the statement are not balanced.",
}
ORDER_END_WORDS = frozenset("LIMIT OFFSET FETCH".split())
DIGITS = re.compile(r"[0-9]+")


def _diff_refuse(reason, static_review_only=False):
    return None, {"reason": reason, "message": DIFF_MESSAGES[reason], "static_review_only": static_review_only}


def _balanced(tokens):
    """True when the `(` and `)` tokens balance and no `)` comes before its `(`. A string or a quoted name is one token."""
    depth = 0
    for token in tokens:
        if _is_punct(token, "("):
            depth += 1
        elif _is_punct(token, ")"):
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _ascii_lower(text):
    return "".join(char.lower() if "A" <= char <= "Z" else char for char in text)


def _sort_key(tokens):
    """The key dict of one `ORDER BY` key (one operand, then ASC or DESC, then NULLS FIRST or LAST), or None."""
    if not tokens:
        return None
    operand, rest = tokens[0], tokens[1:]
    if operand.kind == "number" and DIGITS.fullmatch(operand.value):
        found = ("position", int(operand.value))
    elif operand.kind == "word":
        found = ("name", _ascii_lower(operand.value))
    elif operand.kind == "qident":
        found = ("name", operand.value)
    else:
        return None
    descending = False
    if rest and (_is_word(rest[0], "ASC") or _is_word(rest[0], "DESC")):
        descending = _is_word(rest[0], "DESC")
        rest = rest[1:]
    nulls = None
    if len(rest) == 2 and _is_word(rest[0], "NULLS") and (_is_word(rest[1], "FIRST") or _is_word(rest[1], "LAST")):
        nulls = rest[1].value.lower()
        rest = []
    if rest:
        return None
    return {"operand": found[0], "value": found[1], "descending": descending, "nulls": nulls}


def _order_keys(body):
    """None when the statement has no top-level `ORDER BY`, else `{"keys": [...]}` or `{"unextractable": why}`."""
    depth = 0
    starts = []
    for index, token in enumerate(body):
        if _is_punct(token, "("):
            depth += 1
        elif _is_punct(token, ")"):
            depth -= 1
        elif depth == 0 and _is_word(token, "ORDER") and index + 1 < len(body) and _is_word(body[index + 1], "BY"):
            starts.append(index + 2)
    if not starts:
        return None
    if len(starts) > 1:
        return {"unextractable": "the statement has more than one top-level ORDER BY"}
    parts, current, depth = [], [], 0
    for token in body[starts[0]:]:
        if _is_punct(token, "("):
            depth += 1
        elif _is_punct(token, ")"):
            depth -= 1
        elif depth == 0 and token.kind == "word" and token.value.upper() in ORDER_END_WORDS:
            break
        elif depth == 0 and _is_punct(token, ","):
            parts.append(current)
            current = []
            continue
        current.append(token)
    parts.append(current)
    keys = [_sort_key(part) for part in parts]
    if None in keys:
        return {"unextractable": "a sort key is not an output column name or a position"}
    return {"keys": keys}


def check_diff(text):
    """The guard of one statement of `pg_run diff`: `(result, None)` with `sql` and `order`, or `(None, refusal)`.
    It runs `check_select` (its reasons pass through with the `diff` messages), refuses the string-SQL functions
    of the write-mode scan lists and unbalanced parentheses, and extracts the sort keys of a top-level `ORDER BY`.
    `order` is None (no such `ORDER BY`), `{"keys": [...]}` or `{"unextractable": why}`."""
    sql, refusal = check_select(text)
    if refusal:
        return _diff_refuse(refusal["reason"], refusal["static_review_only"])
    tokens, _ = tokenize(text)
    semicolons = [i for i, t in enumerate(tokens) if _is_semicolon(t)]
    body = tokens[:semicolons[0]] if semicolons else tokens
    for token in body:
        if token.kind in ("word", "qident"):
            name = token.value.lower()
            if name in SCAN_NAMES or name.startswith(SCAN_PREFIXES):
                return _diff_refuse("forbidden_function")
    if not _balanced(body):
        return _diff_refuse("unbalanced_parentheses")
    return {"sql": sql, "order": _order_keys(body)}, None
