"""Shared redaction rules: redact(text) returns the text with every secret value replaced by ***.

Pure module, no I/O. Rules (spec #277, ticket spec #281):
1. A PEM private-key block is replaced as a whole (first, so no later rule leaves its body lines).
   A BEGIN line with no END line makes everything from it to the end of the text one ***.
2. Keyed formats, tried in this order on each occurrence: JSON, env, YAML. The key name must contain
   ACCESS_KEY, SECRET, TOKEN, PASSWORD, PASSWD, PRIVATE_KEY, API_KEY or CREDENTIAL, ignoring case, _ and -.
   Only the value becomes ***; a number, true/false, null or empty value stays (value guard).
   - A single-quoted key (`'key': value`) is a YAML key with every same-line YAML value form.
   - A block scalar header (`|` or `>`) may have node properties before it: at most one tag (`!x`, `!!x`,
     `!<x>`) and one anchor (`&x`), at least one, in either order. The header, and the lines that are blank or
     indented deeper than the key, become one *** (`key: ***`, quotes kept for a quoted key). A plain
     double-quoted key and a single-quoted key open a block too; an env pair never does.
   - Two tags or two anchors are no properties: the value is masked to the end of the line.
   - A YAML key, a single-quoted key or a plain double-quoted key with an empty value (nothing after the colon
     but spaces, tabs and node properties) is fail-closed (spec 311, ticket 313). The lines after it that are
     blank, indented deeper than the key, or at exactly the key indent and starting with `- ` are hidden,
     up to the first other line at the key indent or less. When at least one line is hidden, the key line
     becomes `key: ***` (quotes kept for a quoted key; its properties are hidden too) and the hidden lines are
     removed. When no line is hidden, the text stays unchanged. The key indent is the column of the key in
     the text after the PEM rule. A nested map under the key is hidden too (accepted cost).
   - An unquoted value of more than one word after a plain double-quoted key (`"key": a b`, `"key": 42 b`)
     is masked to the end of the line. One word keeps the JSON mask.
3. Shapes with no key name: AWS key IDs, JWTs, URL passwords and vendor tokens.
"""
import re

KEY_WORDS = ("accesskey", "secret", "token", "password", "passwd", "privatekey", "apikey", "credential")
KEY_CHARS = r"[A-Za-z0-9_.\-]"
MASK = "***"

# A BEGIN line up to its END line, or to the end of the text when there is no END line.
PEM_BLOCK = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.DOTALL)
ESCAPED_QUOTE = re.compile(r'(?<!\\)\\"')

# One scan finds the earliest key occurrence. At the same key the JSON branch starts first (at its quote).
KEY_OCCURRENCE = re.compile(
    r'(?P<jq>\\?")(?P<jkey>' + KEY_CHARS + r'+)\\?"[ \t]*:[ \t]*'
    r"|(?<!" + KEY_CHARS + r")(?P<ekey>" + KEY_CHARS + r"+)="
    r"|(?<!" + KEY_CHARS + r")(?P<ykey>" + KEY_CHARS + r"+):(?=[ \t\r\n]|\Z)[ \t]*"
    r"|'(?P<skey>" + KEY_CHARS + r"+)'[ \t]*:(?=[ \t\r\n]|\Z)[ \t]*",
    re.MULTILINE,
)
# YAML node properties: at most one tag and one anchor, at least one, in either order.
TAG = r"!(?:<[^>\s]*>|[^\s,\[\]{}]*)"
ANCHOR = r"&[^\s,\[\]{}]+"
PROPERTIES = r"(?:" + TAG + r"(?:[ \t]+" + ANCHOR + r")?|" + ANCHOR + r"(?:[ \t]+" + TAG + r")?)"
# Where a block scalar header starts: optional node properties, then `|` or `>`. The filter uses it too.
BLOCK_HEADER = re.compile(r"(?:" + PROPERTIES + r"[ \t]+)?[|>]")
# An empty value: nothing but node properties, spaces and tabs up to the line end. The filter uses it too.
EMPTY_VALUE = re.compile(r"(?:" + PROPERTIES + r"[ \t]*)?(?=\r?\n|\Z)")
NUMBER = re.compile(r"[+-]?[0-9]+(\.[0-9]+)?")
BAREWORD = re.compile(r"[^,}\]\s]*")
LINE_END = re.compile(r"[^\r\n]*")

SHAPES = (
    (re.compile(r"(?:AKIA|ASIA)[A-Z0-9]{16}"), MASK),
    (re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"), MASK),
    (re.compile(r"(?P<head>[A-Za-z][A-Za-z0-9+.\-]*://[^\s:/@]+:)[^\s@/]+(?=@)"), r"\g<head>" + MASK),
    (re.compile(r"(?:ghp_|gho_|ghs_|github_pat_|sk-ant-|xox[abprs]-)[A-Za-z0-9_\-]+"), MASK),
)


def block_key(match):
    """The key name of a key occurrence that may open a block scalar, or None.

    That is a YAML key, a single-quoted key or a plain double-quoted key. An env pair and a JSON key written
    with escaped quotes never open a block. The rules and the Monitor filter both call this.
    """
    key = match.group("ykey") or match.group("skey")
    if key is None and match.group("jq") == '"':
        key = match.group("jkey")
    return key


def is_secret_key(key):
    normal = key.lower().replace("_", "").replace("-", "")
    return any(word in normal for word in KEY_WORDS)


def is_harmless(value):
    """The value guard: a number, true/false in any case, null, or empty."""
    value = value.strip()
    return value == "" or value.lower() in ("true", "false", "null") or NUMBER.fullmatch(value) is not None


def line_end(text, start):
    return LINE_END.match(text, start).end()


def find_plain_quote(text, start, limit):
    """Index of the unescaped double quote that closes a string opened before `start`, or -1."""
    index = start
    while index < limit:
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == '"':
            return index
        index += 1
    return -1


def find_escaped_quote(text, start, limit):
    """Index of the backslash of the first lone backslash-quote at or after `start`, or -1."""
    match = ESCAPED_QUOTE.search(text, start, limit)
    return match.start() if match else -1


def matching_bracket(text, start):
    """Index just after the bracket that closes the one at `start` (strings skipped), or -1."""
    depth = 0
    index = start
    in_string = False
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
            if depth == 0:
                return index + 1
        index += 1
    return -1


def json_value_end(text, start, quote):
    """Return (end, replacement) of the JSON value at `start`, or (start, None) when it stays."""
    if text.startswith('"', start) or text.startswith('\\"', start):
        value_quote = '\\"' if text.startswith('\\"', start) else '"'
        body = start + len(value_quote)
        limit = line_end(text, body)
        close = find_escaped_quote(text, body, limit) if value_quote == '\\"' else find_plain_quote(text, body, limit)
        end = limit if close < 0 else close + len(value_quote)
        inner = text[body : limit if close < 0 else close]
        if is_harmless(inner):
            return start, None
        return end, value_quote + MASK + value_quote
    if text.startswith(("{", "["), start):
        end = matching_bracket(text, start)
        end = len(text) if end < 0 else end
        if text[start + 1 : end - 1].strip() == "" and end - start >= 2 and text[end - 1] in "}]":
            return start, None
        return end, quote + MASK + quote
    end = BAREWORD.match(text, start).end()
    if is_harmless(text[start:end]):
        return start, None
    return end, quote + MASK + quote


def json_dq_key_value_end(text, start):
    """Like json_value_end for a plain double-quoted key, but an unquoted value of more than one word is
    masked to the end of the line (a YAML plain value)."""
    if text[start : start + 1] not in ('"', "{", "["):
        word_end = BAREWORD.match(text, start).end()
        after = word_end
        while after < len(text) and text[after] in " \t":
            after += 1
        if after < len(text) and text[after] not in ",}]\r\n":
            return line_end(text, start), MASK
    return json_value_end(text, start, '"')


def quoted_line_value(text, start):
    """Env and YAML quoted value at `start`: return (end, replacement) or (start, None) when it stays."""
    char = text[start]
    body = start + 1
    limit = line_end(text, body)
    close = find_plain_quote(text, body, limit) if char == '"' else text.find("'", body, limit)
    end = limit if close < 0 else close + 1
    inner = text[body : limit if close < 0 else close]
    if is_harmless(inner):
        return start, None
    return end, char + MASK + char


def plain_line_value(text, start):
    end = line_end(text, start)
    if is_harmless(text[start:end]):
        return start, None
    return end, MASK


def drop_block_scalar(text, header_end, key_indent):
    """Index after the block-scalar lines that are empty or indented more than the key line."""
    index = header_end
    while index < len(text):
        newline = text.find("\n", index)
        line_stop = len(text) if newline < 0 else newline
        line = text[index:line_stop]
        indent = len(line) - len(line.lstrip(" \t"))
        if line.strip() != "" and indent <= key_indent:
            break
        index = line_stop + 1
    return min(index, len(text))


def hidden_by_empty_key(line, key_indent):
    """Whether the empty-key rule hides a line (given without its line ending) that follows an empty secret key.

    The line is blank, indented deeper than the key, or at exactly the key indent and starting with `- `.
    The filter uses it too.
    """
    if line.strip() == "":
        return True
    indent = len(line) - len(line.lstrip(" \t"))
    return indent > key_indent or (indent == key_indent and line.startswith("- ", indent))


def empty_key_end(text, header_end, key_indent):
    """Index after the lines that the empty-key rule hides below the key line ending at `header_end`, or -1."""
    newline = text.find("\n", header_end)
    if newline < 0:
        return -1
    first = index = newline + 1
    while index < len(text):
        newline = text.find("\n", index)
        line_stop = len(text) if newline < 0 else newline
        if not hidden_by_empty_key(text[index:line_stop], key_indent):
            break
        index = line_stop + 1
    index = min(index, len(text))
    return index if index > first else -1


def empty_key(body):
    """(key indent, index of the value) of the last secret key in a line with an empty value, or None.

    The line is given without its line ending. The key indent is measured on the line after the PEM rule,
    as redact_keyed measures it. The filter uses this to find an empty secret key.
    """
    masked = PEM_BLOCK.sub(MASK, body)
    found = None
    for match in KEY_OCCURRENCE.finditer(masked):
        key = block_key(match)
        if key is not None and is_secret_key(key) and EMPTY_VALUE.match(masked, match.end()):
            found = (match.start(), match.end())
    return found


def redact_keyed(text):
    out = []
    pos = 0
    while True:
        match = KEY_OCCURRENCE.search(text, pos)
        if match is None:
            break
        if match.group("jkey") is not None:
            key, start, kind = match.group("jkey"), match.end(), "json"
        elif match.group("ekey") is not None:
            key, start, kind = match.group("ekey"), match.end(), "env"
        else:
            key, start, kind = match.group("ykey") or match.group("skey"), match.end(), "yaml"
        out.append(text[pos:start])
        pos = start
        if not is_secret_key(key):
            continue
        if kind == "json" and match.group("jq") != '"':
            end, replacement = json_value_end(text, start, match.group("jq"))
        elif block_key(match) is not None and BLOCK_HEADER.match(text, start):
            header_end = line_end(text, start)
            line_start = text.rfind("\n", 0, match.start()) + 1
            key_indent = match.start() - line_start
            end, replacement = drop_block_scalar(text, header_end, key_indent), MASK
            if end > header_end and text[header_end : header_end + 1] == "\n":
                replacement = MASK + "\n"  # the dropped lines took the newline of the key line
        elif block_key(match) is not None and EMPTY_VALUE.match(text, start):
            header_end = line_end(text, start)
            line_start = text.rfind("\n", 0, match.start()) + 1
            end = empty_key_end(text, header_end, match.start() - line_start)
            if end < 0:
                continue  # no line is hidden: the text stays unchanged
            space = "" if text[start - 1] in " \t" else " "  # `key:` has no space to keep
            replacement = space + MASK + ("\r\n" if text.startswith("\r\n", header_end) else "\n")
        elif kind == "json":
            end, replacement = json_dq_key_value_end(text, start)
        elif start < len(text) and text[start] in "\"'":
            end, replacement = quoted_line_value(text, start)
        else:
            end, replacement = plain_line_value(text, start)
        if replacement is None:
            continue
        out.append(replacement)
        pos = end
    out.append(text[pos:])
    return "".join(out)


def redact(text):
    text = PEM_BLOCK.sub(MASK, text)
    text = redact_keyed(text)
    for pattern, replacement in SHAPES:
        text = pattern.sub(replacement, text)
    return text
