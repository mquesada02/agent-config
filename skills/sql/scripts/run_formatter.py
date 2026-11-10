#!/usr/bin/env python3
"""Run a safe formatter tool on a temp copy and print one JSON object.

Usage: python3 run_formatter.py <repo root> <file> --tool <name>
           --range <start>-<end> [--range ...] --output <path> [--tags <t1,t2,...>]

The target statements are the top-level statements of <file> that lie inside a
--range. The tool runs twice on a temp copy, from the repo root, with the repo's
own config. When every check passes, the runner writes <path> (the file with
only the target statements replaced) and prints `ok` true. The runner never
writes the repo file: the caller copies <path> over it.

Exit code: 0 when `ok` is true, 1 when a check failed (the JSON is still
printed, nothing is written), 2 for a usage error (one line on stderr, nothing
on stdout).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sql_text import (  # noqa: E402
    UsageError, parse_arguments, parse_range, read_lines, run_extractor, usage_failure,
)

JS_EXTENSIONS = (".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx")
TEMPLATE_TOOLS = ("prettier-plugin-embed",)
SQL_TOOLS = ("sqlfluff", "pgFormatter", "prettier-plugin-sql", "sql-formatter")
COMMANDS = {
    "prettier-plugin-embed": "prettier",
    "prettier-plugin-sql": "prettier",
    "sqlfluff": "sqlfluff",
    "pgFormatter": "pg_format",
    "sql-formatter": "sql-formatter",
}
LOCAL_COMMANDS = ("prettier", "sql-formatter")
PLACEHOLDER = r"\$\{[^}]*\}"
PARSE_FAILURE = re.compile(
    r"parse error|parsing error|syntax ?error|parse failure|failed to parse|could(?: ?n.t| not) parse"
    r"|unparsable|unparseable",
    re.I,
)
TIMEOUT = 60


class Failed(Exception):
    def __init__(self, check, reason):
        super().__init__(reason)
        self.check = check
        self.reason = reason


def first_line(text):
    lines = text.strip().splitlines()
    return lines[0].strip()[:200] if lines else ""


def find_command(root, command):
    if command in LOCAL_COMMANDS:
        local = os.path.join(root, "node_modules", ".bin", command)
        if os.path.isfile(local) and os.access(local, os.X_OK):
            return local
    return shutil.which(command)


def raw_interpolations(statement):
    """The raw `${...}` texts of a statement, in order (the extractor's expression is stripped)."""
    text = statement["text"]
    position = 0
    found = []
    for item in statement["interpolations"]:
        match = re.compile(r"\$\{\s*" + re.escape(item["expression"]) + r"\s*\}").search(text, position)
        if match is None:
            found.append("?" + item["expression"])
            continue
        found.append(match.group())
        position = match.end()
    return found


def sql_formatter_config(root):
    path = os.path.join(root, ".sql-formatter.json")
    config = {}
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as handle:
                config = json.load(handle)
        except (OSError, ValueError) as error:
            raise Failed("tool_error", ".sql-formatter.json cannot be read: %s" % error)
        if not isinstance(config, dict):
            raise Failed("tool_error", ".sql-formatter.json is not a JSON object")
    param_types = config.get("paramTypes")
    if not isinstance(param_types, dict):
        param_types = {}
    custom = param_types.get("custom")
    param_types["custom"] = (custom if isinstance(custom, list) else []) + [{"regex": PLACEHOLDER}]
    config["paramTypes"] = param_types
    return json.dumps(config)


def build_command(tool, executable, relative, root, placeholders):
    if tool in ("prettier-plugin-embed", "prettier-plugin-sql"):
        return [executable, "--stdin-filepath", relative]
    if tool == "sqlfluff":
        return [executable, "fix", "-", "--stdin-filename", relative]
    if tool == "pgFormatter":
        command = [executable]
        config = os.path.join(root, ".pg_format")
        if os.path.isfile(config):
            command += ["-c", config]
        if placeholders:
            command += ["-p", PLACEHOLDER]
        return command + ["-"]
    command = [executable]
    if placeholders:
        command += ["--config", sql_formatter_config(root)]
    return command


def run_pass(command, source, root):
    """Run the tool with `source` (a temp file path) as stdin. Returns its stdout bytes."""
    try:
        with open(source, "rb") as stdin:
            result = subprocess.run(
                command, stdin=stdin, capture_output=True, cwd=root, timeout=TIMEOUT
            )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Failed("tool_error", "the tool could not run: %s" % error)
    stderr = result.stderr.decode("utf-8", "replace")
    if result.returncode != 0:
        raise Failed("tool_error", "the tool exited with code %d: %s" % (result.returncode, first_line(stderr)))
    if PARSE_FAILURE.search(stderr):
        raise Failed("parse_failure", "the tool printed a parse failure: %s" % first_line(stderr))
    return result.stdout


def top_level(data):
    return [statement for statement in data["statements"] if statement["parent"] is None]


def overlaps(first, second):
    return first[0] <= second[1] and second[0] <= first[1]


def regions_of(ranges):
    """Merge (start, end) ranges that share a line. The input is sorted by start."""
    merged = []
    for start, end in ranges:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def select_targets(statements, ranges):
    """The indexes of the target statements. Raises UsageError for a bad range."""
    targets = set()
    for start, end in ranges:
        inside = []
        for index, statement in enumerate(statements):
            span = (statement["start_line"], statement["end_line"])
            if span[0] >= start and span[1] <= end:
                inside.append(index)
            elif overlaps(span, (start, end)):
                raise UsageError("range %d-%d cuts the statement at lines %d-%d" % (start, end, span[0], span[1]))
        if not inside:
            raise UsageError("range %d-%d holds no statement" % (start, end))
        targets.update(inside)
    return sorted(targets)


def splice(original, formatted, pairs):
    """Lines of the result and the `ranges` entries. `pairs` holds (old span, new span) per region."""
    result = []
    entries = []
    position = 1
    for old, new in pairs:
        result += original[position - 1:old[0] - 1]
        block = list(formatted[new[0] - 1:new[1]])
        if block and not block[-1].endswith(b"\n") and old[1] < len(original):
            block[-1] += b"\n"
        entries.append({
            "start": old[0], "end": old[1],
            "new_start": len(result) + 1, "new_end": len(result) + len(block),
        })
        result += block
        position = old[1] + 1
    result += original[position - 1:]
    return result, entries


def format_file(root, path, relative, tool, ranges, tags, output):
    original = read_lines(path)
    data, message = run_extractor(path, tags)
    if data is None:
        raise Failed("extract", "the extractor cannot read the file: %s" % message)
    statements = top_level(data)
    targets = select_targets(statements, ranges)
    target_statements = [statements[index] for index in targets]
    if any(item["position"] == "keyword" for statement in target_statements for item in statement["interpolations"]):
        raise Failed("keyword_position", "a target statement has an interpolation in a keyword position")
    placeholders = any(statement["interpolations"] for statement in target_statements)
    if tool == "sqlfluff" and placeholders:
        raise Failed("sqlfluff_placeholder", "sqlfluff never runs on a target that holds an interpolation")
    executable = find_command(root, COMMANDS[tool])
    if executable is None:
        raise Failed("tool_missing", "the command %s is not in node_modules/.bin or on PATH" % COMMANDS[tool])
    command = build_command(tool, executable, relative, root, placeholders)

    suffix = os.path.splitext(path)[1]
    temps = []

    def temp_file(content):
        descriptor, name = tempfile.mkstemp(suffix=suffix)
        temps.append(name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        return name

    try:
        original_bytes = b"".join(original)
        first = run_pass(command, temp_file(original_bytes), root)
        first_path = temp_file(first)
        formatted_data, message = run_extractor(first_path, tags)
        if formatted_data is None:
            raise Failed("extract", "the extractor cannot read the tool output: %s" % message)
        formatted_statements = top_level(formatted_data)
        if len(formatted_statements) != len(statements):
            raise Failed(
                "extract",
                "the tool output has %d statements, the file has %d" % (len(formatted_statements), len(statements)),
            )
        for index in targets:
            if raw_interpolations(statements[index]) != raw_interpolations(formatted_statements[index]):
                raise Failed(
                    "interpolation_changed",
                    "the interpolations of the statement at lines %d-%d changed"
                    % (statements[index]["start_line"], statements[index]["end_line"]),
                )
        old_spans = [(s["start_line"], s["end_line"]) for s in target_statements]
        old_regions = regions_of(old_spans)
        pairs = []
        for region in old_regions:
            members = [
                formatted_statements[index]
                for index in targets
                if region[0] <= statements[index]["start_line"] and statements[index]["end_line"] <= region[1]
            ]
            new = (min(m["start_line"] for m in members), max(m["end_line"] for m in members))
            pairs.append((region, new))
        for earlier, later in zip(pairs, pairs[1:]):
            if later[1][0] <= earlier[1][1]:
                raise Failed("shared_line", "two target regions share a line in the tool output")
        for index, statement in enumerate(statements):
            if index in targets:
                continue
            for old, new in pairs:
                if overlaps((statement["start_line"], statement["end_line"]), old) or overlaps(
                    (formatted_statements[index]["start_line"], formatted_statements[index]["end_line"]), new
                ):
                    raise Failed(
                        "shared_line",
                        "the statement at lines %d-%d shares a line with a target" % (statement["start_line"], statement["end_line"]),
                    )
        second = run_pass(command, first_path, root)
        if second != first:
            raise Failed("not_stable", "the second pass changed the output of the first pass")
        lines, entries = splice(original, read_lines(first_path), pairs)
        spliced = b"".join(lines)
        try:
            with open(output, "wb") as handle:
                handle.write(spliced)
        except OSError as error:
            raise Failed("tool_error", "the output file cannot be written: %s" % error)
        return spliced != original_bytes, entries
    finally:
        for name in temps:
            try:
                os.unlink(name)
            except OSError:
                pass


def parse_command_line(argv):
    positional, options = parse_arguments(
        argv[1:], 2, single=("--tool", "--output", "--tags"), many=("--range",)
    )
    root = os.path.abspath(positional[0])
    if not os.path.isdir(root):
        raise UsageError("not a folder: " + positional[0])
    real_root = os.path.realpath(root)
    path = positional[1] if os.path.isabs(positional[1]) else os.path.join(root, positional[1])
    path = os.path.realpath(path)
    if not os.path.isfile(path):
        raise UsageError("not a file: " + positional[1])
    if os.path.commonpath([path, real_root]) != real_root:
        raise UsageError("the file is not inside the repo root: " + positional[1])
    extension = os.path.splitext(path)[1].lower()
    if extension in JS_EXTENSIONS:
        fits = TEMPLATE_TOOLS
    elif extension == ".sql":
        fits = SQL_TOOLS
    else:
        raise UsageError("unsupported file form: " + positional[1])
    if "--tool" not in options:
        raise UsageError("--tool is required")
    tool = options["--tool"][0]
    if tool not in COMMANDS:
        raise UsageError("not a safe tool: " + tool)
    if tool not in fits:
        raise UsageError("the tool %s does not fit this file form" % tool)
    if "--output" not in options:
        raise UsageError("--output is required")
    output = os.path.abspath(options["--output"][0])
    if os.path.realpath(output) == path:
        raise UsageError("--output is the file itself")
    if "--range" not in options:
        raise UsageError("at least one --range is required")
    line_count = len(read_lines(path))
    ranges = sorted(parse_range(value, line_count) for value in options["--range"])
    tags = options.get("--tags", [None])[0]
    if tags is not None and not [tag for tag in tags.split(",") if tag]:
        raise UsageError("--tags needs at least one tag")
    return root, path, os.path.relpath(path, real_root), tool, ranges, tags, output


def main(argv):
    try:
        root, path, relative, tool, ranges, tags, output = parse_command_line(argv)
        report = {"tool": tool, "file": path, "ok": True, "check": None, "reason": None,
                  "changed": False, "output": None, "ranges": []}
        try:
            changed, entries = format_file(root, path, relative, tool, ranges, tags, output)
            report.update(changed=changed, output=output, ranges=entries)
        except Failed as failure:
            report.update(ok=False, check=failure.check, reason=failure.reason)
    except UsageError as error:
        return usage_failure(error)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
