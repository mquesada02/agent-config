"""Shared redaction rules: redact(text) returns the text with every secret value replaced by ***.

Pure module, no I/O. Rules (spec #277, ticket spec #281):
1. A PEM private-key block is replaced as a whole (first, so no later rule leaves its body lines).
   A BEGIN line with no END line makes everything from it to the end of the text one ***.
2. Keyed formats, tried in this order on each occurrence: JSON, env, YAML. The key name must contain
   ACCESS_KEY, SECRET, TOKEN, PASSWORD, PASSWD, PRIVATE_KEY, API_KEY or CREDENTIAL, ignoring case, _ and -.
   Only the value becomes ***; a number, true/false, null or empty value stays (value guard).
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
    r"|(?<!" + KEY_CHARS + r")(?P<ykey>" + KEY_CHARS + r"+):(?=[ \t\r\n]|\Z)[ \t]*",
    re.MULTILINE,
)
NUMBER = re.compile(r"[+-]?[0-9]+(\.[0-9]+)?")
BAREWORD = re.compile(r"[^,}\]\s]*")
LINE_END = re.compile(r"[^\r\n]*")

SHAPES = (
    (re.compile(r"(?:AKIA|ASIA)[A-Z0-9]{16}"), MASK),
    (re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"), MASK),
    (re.compile(r"(?P<head>[A-Za-z][A-Za-z0-9+.\-]*://[^\s:/@]+:)[^\s@/]+(?=@)"), r"\g<head>" + MASK),
    (re.compile(r"(?:ghp_|gho_|ghs_|github_pat_|sk-ant-|xox[abprs]-)[A-Za-z0-9_\-]+"), MASK),
)


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
            key, start, kind = match.group("ykey"), match.end(), "yaml"
        out.append(text[pos:start])
        pos = start
        if not is_secret_key(key):
            continue
        if kind == "json":
            quote = match.group("jq")
            end, replacement = json_value_end(text, start, quote)
        elif start < len(text) and text[start] in "|>" and kind == "yaml":
            header_end = line_end(text, start)
            line_start = text.rfind("\n", 0, match.start()) + 1
            key_indent = match.start() - line_start
            end, replacement = drop_block_scalar(text, header_end, key_indent), MASK
            if end > header_end and text[header_end : header_end + 1] == "\n":
                replacement = MASK + "\n"  # the dropped lines took the newline of the key line
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
