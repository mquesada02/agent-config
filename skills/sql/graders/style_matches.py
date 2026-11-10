#!/usr/bin/env python3
"""Grader C: the first format run matches the style and the second run changes nothing.

Usage: python3 style_matches.py <first> <second> --style <json file>
           [--target <start>-<end>] [--tags <t1,t2,...>]

`<first>` is the file after the first run, `<second>` the file after the
second run. `--style` names a JSON file with the five `[style]` keys.
`--target` is a 1-based inclusive line range of the first file (default: the
whole file). The grader fails when the second file is not byte-identical to the
first, and when a statement of the target (a statement that starts and ends
inside it and is not a nested fragment) votes for a value other than the
expected one. A property with no vote passes. `comma` is not checked when the
expected `clause_per_line` is false.

Exit code: 0 pass, 1 fail, 2 usage error. Prints {"grader", "pass", "failures"}.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import sql_text  # noqa: E402

TYPES = {
    "keyword_case": str,
    "indent": str,
    "clause_per_line": bool,
    "comma": str,
    "alias_as": bool,
}


def load_style(path):
    try:
        with open(path, encoding="utf-8") as handle:
            style = json.load(handle)
    except (OSError, ValueError) as error:
        raise sql_text.UsageError("cannot read the style file %s: %s" % (path, error))
    if not isinstance(style, dict):
        raise sql_text.UsageError("the style file is not a JSON object")
    for key, kind in TYPES.items():
        if key not in style or not isinstance(style[key], kind):
            raise sql_text.UsageError("the style file has no valid %s" % key)
    return style


def check(first_path, target, tags, style):
    data, message = sql_text.run_extractor(first_path, tags)
    if message is not None:
        return ["%s: %s" % (first_path, message)]
    inside = [
        statement
        for statement in data["statements"]
        if statement["parent"] is None
        and (target is None or (statement["start_line"] >= target[0] and statement["end_line"] <= target[1]))
    ]
    if not inside:
        return ["no statement in the target"]
    failures = []
    for statement in inside:
        found = sql_text.votes(statement, data["form"])
        for name in sql_text.PROPERTIES:
            if name == "comma" and style["clause_per_line"] is False:
                continue
            if found[name] is not None and found[name] != style[name]:
                failures.append(
                    "statement at lines %d-%d: %s is %s, expected %s"
                    % (statement["start_line"], statement["end_line"], name, found[name], style[name])
                )
    return failures


def main(argv):
    try:
        (first_path, second_path), options = sql_text.parse_arguments(
            argv, 2, single=("--style", "--target", "--tags")
        )
        if "--style" not in options:
            raise sql_text.UsageError("--style is needed")
        style = load_style(options["--style"][0])
        target = sql_text.parse_range(options["--target"][0]) if "--target" in options else None
        try:
            first_lines = sql_text.read_lines(first_path)
        except OSError as error:
            return sql_text.finish("C", ["cannot read %s: %s" % (first_path, error)])
        if target is not None:
            sql_text.parse_range(options["--target"][0], len(first_lines))
    except sql_text.UsageError as error:
        return sql_text.usage_failure(error)
    tags = options.get("--tags", [None])[0]
    try:
        with open(first_path, "rb") as one, open(second_path, "rb") as two:
            same = one.read() == two.read()
    except OSError as error:
        return sql_text.finish("C", ["cannot read the second file: %s" % error])
    failures = [] if same else ["the second file differs from the first: the second run changed something"]
    failures += check(first_path, target, tags, style)
    return sql_text.finish("C", failures)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
