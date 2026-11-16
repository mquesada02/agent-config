#!/usr/bin/env python3
"""Measure the style of the SQL of some files and print one JSON object.

Usage: python3 measure_style.py [--tags <t1,t2,...>] [--receivers <r1,r2,...>] <file>...

Each file goes through `extract.py` (next to this script), with the same
`--tags` and `--receivers` values. The output has the counts, the majority
and the value to use for each of the five `[style]` properties. A tie, a
property with no vote, or fewer than 3 counted statements gives the default
style's value.

Exit code: 0 when the command ran (files that cannot be read are in "errors"),
2 for a usage error (one line on stderr, nothing on stdout).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sql_text  # noqa: E402

POSSIBLE = {
    "keyword_case": ["upper", "lower"],
    "clause_per_line": [True, False],
    "comma": ["trailing", "leading"],
    "alias_as": [True, False],
}
MIN_STATEMENTS = 3


def parse(argv):
    tags = None
    receivers = None
    files = []
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--tags":
            if tags is not None:
                raise sql_text.UsageError("--tags is given twice")
            if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
                raise sql_text.UsageError("--tags needs a comma-separated value")
            tags = argv[index + 1]
            index += 2
        elif argument == "--receivers":
            if receivers is not None:
                raise sql_text.UsageError("--receivers is given twice")
            if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
                raise sql_text.UsageError("--receivers needs a comma-separated value")
            receivers = sql_text.check_receivers(argv[index + 1])
            index += 2
        elif argument.startswith("-"):
            raise sql_text.UsageError("unknown option: " + argument)
        else:
            files.append(argument)
            index += 1
    if not files:
        raise sql_text.UsageError("usage: measure_style.py [--tags <t1,t2,...>] [--receivers <r1,r2,...>] <file>...")
    return tags, receivers, files


def collect(files, tags, receivers):
    counts = {name: {value: 0 for value in POSSIBLE.get(name, [])} for name in sql_text.PROPERTIES}
    errors = []
    statements = 0
    for path in files:
        data, message = sql_text.run_extractor(path, tags, receivers)
        if message is not None:
            errors.append({"file": path, "message": message})
            continue
        for statement in data["statements"]:
            found = sql_text.counted_votes(statement, data["form"])
            if found is None:
                continue
            statements += 1
            for name, vote in found.items():
                if vote is not None:
                    counts[name][vote] = counts[name].get(vote, 0) + 1
    return counts, errors, statements


def decide(name, counts, statements):
    default = sql_text.DEFAULT_STYLE[name]
    top = max(counts.values(), default=0)
    leaders = [value for value, count in counts.items() if count == top and top > 0]
    majority = leaders[0] if len(leaders) == 1 else None
    entry = {"counts": counts, "majority": majority, "value": default, "source": "default"}
    if statements < MIN_STATEMENTS:
        entry["reason"] = "few_statements"
    elif top == 0:
        entry["reason"] = "no_votes"
    elif majority is None:
        entry["reason"] = "tie"
    else:
        entry.update(value=majority, source="majority", reason=None)
    return entry


def main(argv):
    try:
        tags, receivers, files = parse(argv)
    except sql_text.UsageError as error:
        return sql_text.usage_failure(error)
    counts, errors, statements = collect(files, tags, receivers)
    properties = {name: decide(name, counts[name], statements) for name in sql_text.PROPERTIES}
    output = {
        "files": files,
        "errors": errors,
        "statements": statements,
        "properties": properties,
        "style": {name: properties[name]["value"] for name in sql_text.PROPERTIES},
    }
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
