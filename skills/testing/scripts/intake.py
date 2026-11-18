#!/usr/bin/env python3
"""Read the repo test rules file and print one JSON object.

Usage: python3 intake.py <repo root> [file ...]

Reads docs/agents/testing.md of the repo and prints {"rules": {...}, "detected": {}}.
The "detected" part is a placeholder in this version. The [file ...] arguments are
accepted and ignored. Needs Python 3.11 or newer (tomllib).
Exit code: 0 when the rules file was read (or does not exist), 1 when "rules.error"
is set (the JSON is still printed), 2 for a usage error.
"""
import collections
import json
import os
import re
import sys
import tomllib

SECTIONS = ("languages", "commands", "groups", "runner", "layout", "libraries")
ARRAY_SECTIONS = ("languages", "groups")
PER_LANGUAGE_SECTIONS = ("commands", "runner", "layout", "libraries")
LANGUAGES = ("rust", "typescript")
CATALOG = {
    "ASSERT-01": "critical",
    "ASSERT-02": "critical",
    "ASSERT-03": "critical",
    "RUN-01": "critical",
    "RS-01": "critical",
    "RUN-02": "required",
    "RUN-03": "required",
    "RUN-04": "required",
    "PAR-01": "required",
    "PAR-02": "required",
    "GRP-01": "required",
    "TS-01": "required",
    "RUN-05": "suggestion",
    "DBL-01": "suggestion",
}
RULES_FILE = os.path.join("docs", "agents", "testing.md")
TOML_OPEN = re.compile(r"^```toml(?:\s.*)?$")
POSITION = re.compile(r"\s*\(at (?:line \d+, column \d+|end of document)\)$")
FENCE_CLOSE = re.compile(r"^```\s*$")


def unique(items):
    return list(dict.fromkeys(items))


def result(found, settings=None, missing=None, without_reason=None, unknown=None, error=None):
    return {
        "found": found,
        "settings": settings or {},
        "missing_sections": list(SECTIONS) if missing is None else missing,
        "disabled_without_reason": without_reason or [],
        "unknown_ids": unknown or [],
        "error": error,
    }


def failure(message, line):
    return result(True, error={"message": message, "line": line})


Block = collections.namedtuple("Block", "opening content closed")


def toml_blocks(lines):
    """Each `toml` fenced block: the 1-based line of its opening fence, its content lines
    and whether it is closed."""
    blocks = []
    index = 0
    while index < len(lines):
        if TOML_OPEN.match(lines[index]):
            start = index
            index += 1
            content = []
            while index < len(lines) and not FENCE_CLOSE.match(lines[index]):
                content.append(lines[index])
                index += 1
            blocks.append(Block(start + 1, content, index < len(lines)))
        index += 1
    return blocks


def parse_error_line(error, content):
    line = getattr(error, "lineno", None)
    if line is None:
        match = re.search(r"line (\d+)", str(error))
        line = int(match.group(1)) if match else len(content)
    return line


def has_reason(rule_id, prose):
    pattern = re.compile(rf"^\s*(?:[-*]\s+)?{re.escape(rule_id)}[:—]\s*\S")
    return any(pattern.match(line) for line in prose)


def disabled_entries(settings):
    """(known candidates, unknown texts) from rules.disabled."""
    rules = settings.get("rules")
    if not isinstance(rules, dict) or "disabled" not in rules:
        return [], []
    value = rules["disabled"]
    if not isinstance(value, list):
        return [], [json.dumps(value, default=str)]
    candidates, unknown = [], []
    for entry in value:
        if isinstance(entry, str) and entry in CATALOG:
            candidates.append(entry)
        else:
            unknown.append(entry if isinstance(entry, str) else json.dumps(entry, default=str))
    return unique(candidates), unique(unknown)


def is_array_of_tables(value):
    return isinstance(value, list) and all(isinstance(item, dict) for item in value)


def counted_languages(settings):
    """The languages of [[languages]], in file order. None are counted when the section is
    absent or of the wrong type."""
    entries = settings.get("languages")
    if not is_array_of_tables(entries):
        return []
    names = [entry.get("name") for entry in entries]
    return unique(name for name in names if name in LANGUAGES)


def check_sections(settings):
    """The missing_sections list. Drops each required section that is absent or of the wrong
    type from settings."""
    counted = counted_languages(settings)
    missing = []
    for name in SECTIONS:
        value = settings.get(name)
        valid = is_array_of_tables(value) if name in ARRAY_SECTIONS else isinstance(value, dict)
        if not valid:
            settings.pop(name, None)
            missing.append(name)
            continue
        if name not in PER_LANGUAGE_SECTIONS:
            continue
        for language in counted:
            entry = value.get(language)
            if not isinstance(entry, dict):
                missing.append(f"{name}.{language}")
            elif name == "commands":
                test = entry.get("test")
                if not isinstance(test, str) or not test.strip():
                    missing.append(f"{name}.{language}")
    return missing


def read_rules(repo):
    path = os.path.join(repo, RULES_FILE)
    try:
        os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return result(False)
    except OSError as error:
        return failure(f"cannot read {RULES_FILE}: {error}", None)
    try:
        with open(path, encoding="utf-8-sig") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as error:
        return failure(f"cannot read {RULES_FILE}: {error}", None)

    # Only "\n" ends a line, as in an editor (splitlines also splits on form feed and others).
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    blocks = toml_blocks(lines)
    if not blocks:
        return result(True)
    block = blocks[0]
    if not block.closed:
        return failure("a toml block has no closing fence", block.opening)
    try:
        parsed = tomllib.loads("\n".join(block.content) + "\n")
    except tomllib.TOMLDecodeError as error:
        message = POSITION.sub("", str(error))
        return failure(f"toml parse error: {message}", block.opening + parse_error_line(error, block.content))
    if len(blocks) > 1:
        return failure("more than one toml block", blocks[1].opening)

    settings = dict(parsed)
    missing = check_sections(settings)
    after_block = block.opening + len(block.content) + 1
    prose = lines[: block.opening - 1] + lines[after_block:]
    candidates, unknown = disabled_entries(settings)
    without_reason = [rule_id for rule_id in candidates if not has_reason(rule_id, prose)]
    return result(True, settings, missing, without_reason, unknown)


def main(argv):
    if len(argv) < 2 or not os.path.isdir(argv[1]):
        print("usage: intake.py <repo root> [file ...]", file=sys.stderr)
        return 2
    try:
        rules = read_rules(argv[1])
        text = json.dumps({"rules": rules, "detected": {}}, indent=2, default=str, allow_nan=False)
    except (RecursionError, ValueError):
        rules = failure("the settings cannot be read as JSON (nan, inf or nesting too deep)", None)
        text = json.dumps({"rules": rules, "detected": {}}, indent=2)
    print(text)
    return 1 if rules["error"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
