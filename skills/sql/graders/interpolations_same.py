#!/usr/bin/env python3
"""Grader A: a format run kept every `${...}` of every statement.

Usage: python3 interpolations_same.py <before> <after> [--tags <t1,t2,...>]

Both files go through `scripts/extract.py`. The grader passes when both files
have the same statements (same count, same tag) and each statement lists the
same interpolations, each with the same expression and the same clause.

Exit code: 0 pass, 1 fail, 2 usage error. Prints {"grader", "pass", "failures"}.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import sql_text  # noqa: E402


def summarize(path, tags):
    data, message = sql_text.run_extractor(path, tags)
    if message is not None:
        return None, "%s: %s" % (path, message)
    return [(s, sql_text.interpolation_clauses(s)) for s in data["statements"]], None


def compare(before, after):
    failures = []
    if len(before) != len(after):
        failures.append(
            "the before file has %d statements and the after file has %d" % (len(before), len(after))
        )
        return failures
    for (old, old_list), (new, new_list) in zip(before, after):
        where = "statement at lines %d-%d of the after file" % (new["start_line"], new["end_line"])
        if old["tag"] != new["tag"]:
            failures.append("%s: the tag is %r, it was %r" % (where, new["tag"], old["tag"]))
        elif old_list != new_list:
            for position in range(max(len(old_list), len(new_list))):
                was = old_list[position] if position < len(old_list) else None
                now = new_list[position] if position < len(new_list) else None
                if was != now:
                    failures.append(
                        "%s: interpolation %d is %s, it was %s"
                        % (where, position + 1, describe(now), describe(was))
                    )
                    break
    return failures


def describe(entry):
    if entry is None:
        return "missing"
    return "${%s} in clause %r" % entry


def main(argv):
    try:
        (before_path, after_path), options = sql_text.parse_arguments(argv, 2, single=("--tags",))
    except sql_text.UsageError as error:
        return sql_text.usage_failure(error)
    tags = options.get("--tags", [None])[0]
    before, problem = summarize(before_path, tags)
    after, other = summarize(after_path, tags)
    failures = [text for text in (problem, other) if text]
    if not failures:
        failures = compare(before, after)
    return sql_text.finish("A", failures)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
