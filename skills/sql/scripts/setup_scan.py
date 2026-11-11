#!/usr/bin/env python3
"""Scan a repo for the SQL that `/sql setup` needs and print one JSON object.

Usage: python3 setup_scan.py <repo root> [--tags <t1,t2,...>]

Walks the repo (not `.git`, `node_modules`, `dist`, `build`, `coverage`, or a
folder that starts with `.`) in sorted path order, runs `extract.py` on each
`.sql`, JavaScript or TypeScript file, and reports the files with SQL, the
statement counts per form, the detected tags and the pitfall candidates (the
catalog ids PGJS-01, PGJS-04, PG-06, PG-08 and PG-10, each with `file:line`
evidence). At most 1000 files with SQL are read.

Exit code: 0 (a file that cannot be read is in "errors"), 2 for a usage error
(one line on stderr, nothing on stdout).
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sql_text  # noqa: E402
from extract import JS_EXTENSIONS, SQL_EXTENSION  # noqa: E402

SKIPPED_FOLDERS = frozenset(("node_modules", "dist", "build", "coverage"))
MAX_FILES = 1000
MAX_EVIDENCE = 5
MAX_OFFSET = 1000

# One fixed sentence per id. None starts with the id: a line that starts with an id and `:` is
# the reason line of a disabled id (the rules file reader).
TEXTS = {
    "PGJS-01": "Pass a list to IN with a tag call such as sql(ids); never put the call in extra parentheses or pass a bare variable.",
    "PGJS-04": "Never pass a built string to the unsafe method of a tag; write a template with interpolations.",
    "PG-06": "Do not start a LIKE pattern with a percent sign when the column has an index.",
    "PG-08": "Do not use SELECT * in a template; name the columns.",
    "PG-10": "Do not page with a large OFFSET; use keyset pagination.",
}
ORDER = ("PGJS-01", "PGJS-04", "PG-06", "PG-08", "PG-10")

LIKE = re.compile(r"\bI?LIKE\s+'%", re.I)
SELECT_STAR = re.compile(r"\bSELECT\s+(?:DISTINCT\s+)?\*", re.I)
EXISTS_BEFORE = re.compile(r"\bEXISTS\s*\(\s*$", re.I)
OFFSET = re.compile(r"\bOFFSET\s+(\d+)\b", re.I)
IN_PAREN = r"(?<![\w$])IN\s*\(\s*\$\{\s*(?:%s)\s*\("
IN_BARE = r"(?<![\w$])IN\s*\$\{(?!\s*(?:%s)\s*\()"
UNSAFE = re.compile(r"(?<![\w$.])[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*\.unsafe\(")


def find_files(repo):
    found = []
    for folder, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIPPED_FOLDERS and not d.startswith(".")]
        for name in files:
            if name.endswith((SQL_EXTENSION,) + JS_EXTENSIONS):
                found.append(os.path.relpath(os.path.join(folder, name), repo).replace(os.sep, "/"))
    return sorted(found)


def line_of(start_line, text, offset):
    return start_line + text.count("\n", 0, offset)


def tag_pattern(tags):
    return "|".join(re.escape(tag) for tag in sorted(tags, key=len, reverse=True))


def statement_hits(statement, form, tags):
    """(id, line) for each pitfall in the text of one top-level statement."""
    text = statement["text"]
    start = statement["start_line"]
    hits = []
    if form == "js":
        names = tag_pattern(tags) if tags else r"(?!)"
        for pattern in (IN_PAREN % names, IN_BARE % names):
            for match in re.finditer(pattern, text, re.I):
                hits.append(("PGJS-01", line_of(start, text, match.start())))
    for match in LIKE.finditer(text):
        hits.append(("PG-06", line_of(start, text, match.start())))
    if form == "js":
        for match in SELECT_STAR.finditer(text):
            if not EXISTS_BEFORE.search(text[: match.start()]):
                hits.append(("PG-08", line_of(start, text, match.start())))
    for match in OFFSET.finditer(text):
        digits = match.group(1).lstrip("0")
        if len(digits) > len(str(MAX_OFFSET)) or (digits and int(digits) > MAX_OFFSET):  # no int() of a huge run
            hits.append(("PG-10", line_of(start, text, match.start())))
    return hits


def is_constant(source, position):
    """True when the argument that starts at `position` is a quoted string or a template with no `${`."""
    while position < len(source) and source[position].isspace():
        position += 1
    if position >= len(source) or source[position] not in "'\"`":
        return False
    quote = source[position]
    index = position + 1
    while index < len(source):
        if source[index] == "\\":
            index += 2
        elif source[index] == quote:
            break
        elif quote == "`" and source.startswith("${", index):
            return False
        else:
            index += 1
    else:
        return False
    rest = source[index + 1:].lstrip()
    return rest[:1] in (",", ")")


def unsafe_hits(source):
    hits = []
    for match in UNSAFE.finditer(source):
        if not is_constant(source, match.end()):
            hits.append(("PGJS-04", source.count("\n", 0, match.start()) + 1))
    return hits


def scan(repo, tags):
    os.chdir(repo)
    files_with_sql, errors, forms = [], [], {"template": 0, "sql": 0}
    statements, detected, truncated = 0, [], False
    hits = {rule_id: [] for rule_id in ORDER}
    for path in find_files("."):
        data, message = sql_text.run_extractor(path, tags)
        if message is not None:
            errors.append({"file": path, "message": message})
            continue
        has_statements = bool(data["statements"])
        if has_statements:
            if len(files_with_sql) == MAX_FILES:
                truncated = True
                continue
            files_with_sql.append(path)
        statements += len(data["statements"])
        form = "template" if data["form"] == "js" else "sql"
        forms[form] += len(data["statements"])
        for tag in data.get("detected_tags", []):
            if tag not in detected:
                detected.append(tag)
        file_tags = set(data.get("detected_tags", [])) | set(tags.split(",") if tags else [])
        for statement in data["statements"]:
            if statement["parent"] is None:
                for rule_id, line in statement_hits(statement, data["form"], file_tags):
                    hits[rule_id].append({"file": path, "line": line})
        if data["form"] == "js":
            try:
                with open(path, encoding="utf-8") as handle:
                    source = handle.read()
            except (OSError, UnicodeDecodeError) as error:
                errors.append({"file": path, "message": str(error)})
                continue
            for rule_id, line in unsafe_hits(source):
                hits[rule_id].append({"file": path, "line": line})
    candidates = [
        {"id": rule_id, "text": TEXTS[rule_id], "evidence": hits[rule_id][:MAX_EVIDENCE], "count": len(hits[rule_id])}
        for rule_id in ORDER
        if hits[rule_id]
    ]
    return {
        "ok": True,
        "files_with_sql": files_with_sql,
        "statements": statements,
        "forms": forms,
        "detected_tags": detected,
        "candidates": candidates,
        "errors": errors,
        "truncated": truncated,
    }


def main(argv):
    try:
        positional, options = sql_text.parse_arguments(argv, 1, single=("--tags",))
        repo = positional[0]
        if not os.path.isdir(repo):
            raise sql_text.UsageError("not a folder: " + repo)
        tags = None
        if "--tags" in options:
            tags = options["--tags"][0]
            if not [tag for tag in tags.split(",") if tag]:
                raise sql_text.UsageError("--tags needs at least one tag")
    except sql_text.UsageError as error:
        return sql_text.usage_failure(error)
    print(json.dumps(scan(os.path.abspath(repo), tags), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
