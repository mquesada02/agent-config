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
    "write_statement": "A write statement needs write mode, which is not available yet.",
    "not_select": "Select mode accepts only SELECT or WITH ... SELECT.",
    "data_modifying": "The statement holds INSERT, UPDATE, DELETE, MERGE or INTO.",
    "forbidden_function": "The statement calls a function that select mode refuses.",
    "unicode_identifier": "A Unicode-escaped identifier (U&\") is refused.",
}


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
