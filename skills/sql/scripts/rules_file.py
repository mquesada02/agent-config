#!/usr/bin/env python3
"""Read the repo SQL rules file and print one JSON object.

Usage: python3 rules_file.py <repo root>

Reads docs/agents/sql.md of the repo. Needs Python 3.11 or newer (tomllib).
Exit code: 0 when the file was read (or does not exist), 1 when "error" is
set (the JSON is still printed), 2 for a usage error.
"""
import collections
import json
import os
import re
import sys
import tomllib

SECTIONS = ("style", "formatter", "sources", "rules")
CATALOG = (
    [f"PGJS-{n:02d}" for n in range(1, 5)]
    + [f"PG-{n:02d}" for n in range(1, 11)]
    + [f"PLAN-{n:02d}" for n in range(1, 6)]
)
RULES_FILE = os.path.join("docs", "agents", "sql.md")
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

    missing = []
    settings = dict(parsed)
    for name in SECTIONS:
        if not isinstance(settings.get(name), dict):
            settings.pop(name, None)
            missing.append(name)
    after_block = block.opening + len(block.content) + 1
    prose = lines[: block.opening - 1] + lines[after_block:]
    candidates, unknown = disabled_entries(settings)
    without_reason = [rule_id for rule_id in candidates if not has_reason(rule_id, prose)]
    return result(True, settings, missing, without_reason, unknown)


def main(argv):
    if len(argv) != 2 or not os.path.isdir(argv[1]):
        print("usage: rules_file.py <repo root>", file=sys.stderr)
        return 2
    try:
        output = read_rules(argv[1])
        text = json.dumps(output, indent=2, default=str, allow_nan=False)
    except (RecursionError, ValueError):
        output = failure("the settings cannot be read as JSON (nan, inf or nesting too deep)", None)
        text = json.dumps(output, indent=2)
    print(text)
    return 1 if output["error"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
