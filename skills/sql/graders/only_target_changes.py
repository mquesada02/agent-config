#!/usr/bin/env python3
"""Grader B: a format run changed only the target lines.

Usage: python3 only_target_changes.py <before> <after> --target <start>-<end> [--target ...]

Each target is a 1-based inclusive line range of the before file. The lines
outside the ranges are the fixed segments. The grader passes when the after
file starts with the first segment, ends with the last one, and holds each
segment between them in order (matched left to right, each at its earliest
position after the previous one). The files are read as plain lines.

Exit code: 0 pass, 1 fail, 2 usage error. Prints {"grader", "pass", "failures"}.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import sql_text  # noqa: E402


def read(path):
    try:
        return sql_text.read_lines(path), None
    except OSError as error:
        return None, "cannot read %s: %s" % (path, error)


def segments_of(before, ranges):
    segments = []
    position = 0
    for start, end in ranges:
        segments.append(before[position:start - 1])
        position = end
    segments.append(before[position:])
    return segments


def find(lines, segment, position):
    for index in range(position, len(lines) - len(segment) + 1):
        if lines[index:index + len(segment)] == segment:
            return index
    return -1


def first_difference(expected, actual):
    for index, line in enumerate(expected):
        if index >= len(actual) or actual[index] != line:
            return index + 1
    return len(expected) + 1


def compare(before, after, ranges):
    segments = segments_of(before, ranges)
    first, last, middle = segments[0], segments[-1], segments[1:-1]
    if after[:len(first)] != first:
        return ["a line before the first target changed (first difference at line %d)" % first_difference(first, after)]
    position = len(first)
    for number, segment in enumerate(middle, 1):
        found = find(after, segment, position)
        if found < 0:
            return ["the lines between target %d and target %d changed or moved" % (number, number + 1)]
        position = found + len(segment)
    tail = len(after) - len(last)
    if tail < position or after[tail:] != last:
        return ["a line after the last target changed or was removed"]
    return []


def main(argv):
    try:
        (before_path, after_path), options = sql_text.parse_arguments(argv, 2, many=("--target",))
        if "--target" not in options:
            raise sql_text.UsageError("at least one --target is needed")
        ranges = [sql_text.parse_range(value) for value in options["--target"]]
        before, problem = read(before_path)
        if before is not None:
            ranges = [sql_text.parse_range(value, len(before)) for value in options["--target"]]
            for (_, end), (start, _) in zip(ranges, ranges[1:]):
                if start <= end:
                    raise sql_text.UsageError("the targets overlap or are not in ascending order")
    except sql_text.UsageError as error:
        return sql_text.usage_failure(error)
    if before is None:
        return sql_text.finish("B", [problem])
    after, problem = read(after_path)
    if after is None:
        return sql_text.finish("B", [problem])
    return sql_text.finish("B", compare(before, after, ranges))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
