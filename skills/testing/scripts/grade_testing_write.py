#!/usr/bin/env python3
"""Write grader for a `/testing write` run (the report contract of write.md).

Usage: grade_testing_write.py REPORT [--repo DIR] [--expect FILE] [--before DIR]

REPORT is a path, or - for stdin. The report checks always run: title, result line, notes,
sections, tables, Command and Run result lines, counts, Found bugs, Kept failing, and the
empty-scope and failed-intake forms.
--repo and --expect are given together. They add the repo checks on the folder after the run.
--before is the fixture repo as it was before the run. It is needed when --expect holds the key
product or existing.
--expect is a JSON object. The key tests (a list of the written test files, relative to the repo)
is required. The other keys are optional, and an absent key means no check:
  product          product files that must equal the same file under --before
  existing         test files that existed before: each non-blank line of the --before copy must
                   appear in the written file, in the same order
  grouped          an object from a test file path to true or false (a recorded group selects the
                   file and its Group cells name one, or its Group cells are none). For a `.rs`
                   file a `--test <target>` flag selects the files of that target, and a group
                   with a crate flag, a doc flag, an unreadable selector or a name filter selects none)
  fallback         none, detected or error
  error_line       the line number that the Rules file error line must name (needed with error)
  result           an object from a test file path to the expected run result word
                   (pass, fail or not run)
  bugs             test names that must be in Found bugs with a Source (an empty list means no
                   Found bugs section may exist)
  command_contains a string that every Command line must hold
Output: one line "FAIL <check>: <message>" for each failed check, then a last line PASS or FAIL.
Exit code: 0 pass, 1 fail, 2 usage error or unreadable input.
The grader reads the rules file itself with tomllib (imported only for the grouped check). It never
calls intake.py.
"""
import argparse
import fnmatch
import json
import os
import re
import shlex
import sys

TITLE = re.compile(r"^# testing write: (\S.*)$")
RESULT = re.compile(
    r"^\*\*Result: ([0-9]{1,9}) files, ([0-9]{1,9}) pass, ([0-9]{1,9}) fail, "
    r"([0-9]{1,9}) not run, ([0-9]{1,9}) bugs\.\*\*$"
)
EMPTY_SCOPE = "No product file in scope. Name the files to test."
FAILED_INTAKE = re.compile(r"^Intake failed: \S.*\.$")
NO_GROUP = re.compile(r"^No group: (rust|typescript|general)(?:, (?:rust|typescript|general))*\. Tests are placed at the named or derived path\.$")
NOT_WRITTEN = re.compile(
    r"^Not written: (\S+) \((no test location is known|no test point|"
    r"no test case has a source for its expected value)\)\.$"
)
FALLBACK_PREFIXES = ("Detected for this run: ", "Rules file error: ")
FILE_COLUMNS = ["Test", "Point", "Kind", "Size", "Group", "Reason"]
BUG_COLUMNS = ["File", "Test", "Where", "Expected", "Source"]
KEPT_COLUMNS = ["File", "Test", "Reason"]
KINDS = ("unit", "integration", "property", "snapshot")
SIZES = ("small", "medium", "large")
PLACE = re.compile(r"\S+:\d+")
RUN_RESULT = re.compile(r"^Run result: (pass|fail \((.+)\)|not run \((.+)\))$")
EXISTING = " (existing)"
EXPECT_KEYS = {
    "tests", "product", "existing", "grouped", "fallback", "error_line", "result", "bugs",
    "command_contains",
}
SETUP_MENTION = "/testing setup"
RULES_FILE = os.path.join("docs", "agents", "testing.md")
LANGUAGES = {
    ".rs": "rust", ".ts": "typescript", ".tsx": "typescript", ".js": "typescript",
    ".mjs": "typescript", ".cjs": "typescript",
}
NAME_FLAGS = (
    "-t", "-k", "-g", "-p", "--grep", "--filter", "--test-name-pattern", "--testNamePattern",
    "--package", "--project", "--exact", "--skip",
)
RUST_UNREADABLE = (
    "--lib", "--bin", "--bins", "--tests", "--example", "--examples", "--bench", "--benches", "--all-targets",
    "-E", "--filterset", "--exclude", "--skip", "--exact", "--ignored", "--include-ignored", "--run-ignored",
)
RUST_VALUE_FLAGS = (
    "-j", "--test-threads", "-P", "--profile", "-F", "--features", "--retries", "--target", "--manifest-path",
)
ASSERTION = re.compile(r"\b(assert|expect|should)|\bt\.(Error|Errorf|Fatal|Fatalf)\(", re.IGNORECASE)


class Usage(Exception):
    pass


def split_row(line):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def parse_table(body):
    """(header cells, data rows) of the first table in a list of lines."""
    header, rows = None, []
    for line in body:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = split_row(stripped)
        if header is None:
            header = cells
        elif not set(cells[0]) <= set("-: "):
            rows.append(cells)
    return header, rows


def check_report(text):
    """(failures, model). The model holds what the repo checks need from the report."""
    lines = text.splitlines()
    failures = []

    def fail(check, message):
        failures.append(f"FAIL {check}: {message}")

    model = {"files": {}, "bugs": [], "kept": [], "lines": lines}
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    title = TITLE.match(lines[first].strip()) if first is not None else None
    if title is None:
        fail("title", "the first line is not like # testing write: <scope>")
        scope = []
    else:
        scope = [] if title.group(1) == "none" else title.group(1).split(", ")
    result_at = next((i for i, line in enumerate(lines) if RESULT.match(line.strip())), None)
    counts = None
    if result_at is None:
        fail("result", "no line like **Result: N files, N pass, N fail, N not run, N bugs.**")
    else:
        counts = [int(n) for n in RESULT.match(lines[result_at].strip()).groups()]
        if first is not None and result_at < first:
            fail("result", "the Result line is before the title")

    headings = [(i, line.strip()) for i, line in enumerate(lines) if line.strip().startswith("## ")]
    first_heading = headings[0][0] if headings else len(lines)
    start = (result_at + 1) if result_at is not None else 0

    # notes
    notes = []
    for i in range(start, first_heading):
        stripped = lines[i].strip()
        if not stripped:
            continue
        if stripped == EMPTY_SCOPE or FAILED_INTAKE.match(stripped):
            notes.append(("form", stripped))
        elif stripped.startswith(FALLBACK_PREFIXES):
            notes.append(("a", stripped))
        elif NO_GROUP.match(stripped):
            notes.append(("b", stripped))
        elif NOT_WRITTEN.match(stripped):
            notes.append(("c", stripped))
        else:
            fail("notes", f"unknown line between the Result line and the first section: {stripped!r}")
    names = [name for name, _ in notes]
    for name in ("a", "b"):
        if names.count(name) > 1:
            fail("notes", f"the {'fallback' if name == 'a' else 'No group'} line appears more than once")
    order = [name for name in names if name != "form"]
    if order != sorted(order):
        fail("notes", "the note lines are not in the order fallback, No group, Not written")
    not_written = [NOT_WRITTEN.match(line).group(1) for name, line in notes if name == "c"]
    for path in dict.fromkeys(not_written):
        if not_written.count(path) > 1:
            fail("notes", f"Not written appears more than once for {path}")
    for path in not_written:
        if path not in scope:
            fail("notes", f"Not written names {path}, which is not in the title scope")
    forms = [line for name, line in notes if name == "form"]
    if not scope:
        if len(forms) != 1 or len(notes) != 1:
            fail("forms", "the scope none needs exactly one line: the empty-scope line or the Intake failed line")
        if headings:
            fail("forms", "an empty-scope or failed-intake report has no section")
        if counts is not None and any(counts):
            fail("forms", "an empty-scope or failed-intake report has all zero counts")
        return failures, model
    if forms:
        fail("forms", "the empty-scope and failed-intake lines need the scope none")

    # the one mention of the setup command
    for index, line in enumerate(lines):
        if SETUP_MENTION in line and not line.strip().startswith(FALLBACK_PREFIXES):
            fail("notes", f"line {index + 1} mentions {SETUP_MENTION}, which only the fallback line may")
    if sum(line.count(SETUP_MENTION) for line in lines) > 1:
        fail("notes", f"{SETUP_MENTION} is mentioned more than once")

    # sections
    file_sections, bug_at, kept_at, ranks = [], None, None, []
    for position, (i, heading) in enumerate(headings):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        body = lines[i + 1:end]
        if heading.startswith("## File: ") and len(heading) > len("## File: "):
            file_sections.append((heading[len("## File: "):].strip(), body))
            ranks.append(0)
        elif heading == "## Found bugs":
            if bug_at is not None:
                fail("sections", "## Found bugs appears twice")
            bug_at = body
            ranks.append(1)
        elif heading == "## Kept failing":
            if kept_at is not None:
                fail("sections", "## Kept failing appears twice")
            kept_at = body
            ranks.append(2)
        else:
            fail("sections", f"unknown section: {heading}")
    if ranks != sorted(ranks):
        fail("sections", "the sections are not in the order File sections, Found bugs, Kept failing")
    paths = [path for path, _ in file_sections]
    if len(set(paths)) != len(paths):
        fail("sections", "a ## File: section appears twice for the same path")
    if file_sections and len(set(not_written)) >= len(scope):
        fail("notes", "every product file is not written, so the report has no file section")

    # file sections
    for path, body in file_sections:
        header, rows = parse_table(body)
        if header != FILE_COLUMNS:
            fail("tables", f"{path}: the table columns are not {FILE_COLUMNS}")
        if not rows:
            fail("tables", f"{path}: the table has no row")
        for cells in rows:
            if len(cells) != len(FILE_COLUMNS):
                fail("tables", f"{path}: a row has {len(cells)} cells, not {len(FILE_COLUMNS)}")
                continue
            if cells[2] not in KINDS:
                fail("tables", f"{path}: the Kind cell {cells[2]!r} is not one of {', '.join(KINDS)}")
            if cells[3] not in SIZES:
                fail("tables", f"{path}: the Size cell {cells[3]!r} is not one of {', '.join(SIZES)}")
        commands = [line.strip() for line in body if line.strip().startswith("Command:")]
        results = [line.strip() for line in body if line.strip().startswith("Run result:")]
        if len(commands) != 1 or commands[0] == "Command:":
            fail("command", f"{path}: needs exactly one Command: <command> line, found {len(commands)}")
        if len(results) != 1:
            fail("run result", f"{path}: needs exactly one Run result line, found {len(results)}")
        word, held = None, []
        match = RUN_RESULT.match(results[0]) if len(results) == 1 else None
        if len(results) == 1 and match is None:
            fail("run result", f"{path}: the Run result line {results[0]!r} has no valid form")
        if match:
            word = "pass" if match.group(1) == "pass" else ("fail" if match.group(2) else "not run")
            held = [n.strip() for n in (match.group(2) or "").split(", ") if n.strip()]
        if len(commands) == 1 and commands[0] == "Command: none" and word in ("pass", "fail"):
            fail("command", f"{path}: Command: none needs Run result: not run, found {word}")
        for name in held:
            if name.endswith(EXISTING) and name[:-len(EXISTING)] in [c[0] for c in rows if c]:
                fail("run result", f"{path}: {name!r} has the suffix {EXISTING.strip()!r} but is a new test")
        model["files"][path] = {
            "rows": rows,
            "command": commands[0][len("Command:"):].strip() if len(commands) == 1 else None,
            "word": word,
            "held": held,
        }

    # Found bugs and Kept failing
    bug_rows, kept_rows = [], []
    if bug_at is not None:
        header, bug_rows = parse_table(bug_at)
        if header != BUG_COLUMNS:
            fail("found bugs", f"the table columns are not {BUG_COLUMNS}")
        if not bug_rows:
            fail("found bugs", "the section has no row")
    if kept_at is not None:
        header, kept_rows = parse_table(kept_at)
        if header != KEPT_COLUMNS:
            fail("kept failing", f"the table columns are not {KEPT_COLUMNS}")
        if not kept_rows:
            fail("kept failing", "the section has no row")
    for cells in bug_rows:
        if len(cells) != len(BUG_COLUMNS):
            fail("found bugs", f"a row has {len(cells)} cells, not {len(BUG_COLUMNS)}")
            continue
        file, test, where, _expected, source = cells
        model["bugs"].append({"file": file, "test": test, "source": source})
        if not PLACE.search(where):
            fail("found bugs", f"{test}: the Where cell {where!r} has no <path>:<line> place")
        if not source:
            fail("found bugs", f"{test}: the Source cell is empty")
        entry = model["files"].get(file)
        if entry is None:
            fail("found bugs", f"{test}: the File cell {file!r} is not a ## File: section")
        elif test not in [c[0] for c in entry["rows"] if c]:
            fail("found bugs", f"{test}: not a row of the table of {file}")
        elif test not in entry["held"]:
            fail("found bugs", f"{test}: not named in the fail result of {file}")
    for cells in kept_rows:
        if len(cells) != len(KEPT_COLUMNS):
            fail("kept failing", f"a row has {len(cells)} cells, not {len(KEPT_COLUMNS)}")
            continue
        file, test, _reason = cells
        model["kept"].append({"file": file, "test": test})
        entry = model["files"].get(file)
        if entry is None:
            fail("kept failing", f"{test}: the File cell {file!r} is not a ## File: section")
        elif test == "(file)":
            if file not in entry["held"]:
                fail("kept failing", f"(file): {file} is not named in the fail result of {file}")
        elif test not in [c[0] for c in entry["rows"] if c]:
            fail("kept failing", f"{test}: not a row of the table of {file}")
        elif test not in entry["held"]:
            fail("kept failing", f"{test}: not named in the fail result of {file}")

    # No group line: present exactly when a row has Group none
    any_none = any(len(c) == len(FILE_COLUMNS) and c[4] == "none" for e in model["files"].values() for c in e["rows"])
    if any_none and "b" not in names:
        fail("notes", "a test has Group none, but the report has no No group line")
    if not any_none and "b" in names:
        fail("notes", "the report has a No group line, but no test has Group none")

    # counts
    if counts is not None:
        words = [entry["word"] for entry in model["files"].values()]
        expected = [len(words), words.count("pass"), words.count("fail"), words.count("not run"), len(bug_rows)]
        labels = ["files", "pass", "fail", "not run", "bugs"]
        for label, want, have in zip(labels, expected, counts):
            if want != have:
                fail("counts", f"{label}: the report holds {want}, the Result line says {have}")
    return failures, model


def read_report(path):
    if path == "-":
        return sys.stdin.buffer.read().decode("utf-8")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def load_expect(path, has_before):
    try:
        with open(path, encoding="utf-8") as handle:
            expect = json.load(handle)
    except (OSError, ValueError) as error:
        raise Usage(f"cannot read --expect {path!r}: {error}")
    if not isinstance(expect, dict):
        raise Usage("--expect must be a JSON object")
    unknown = sorted(set(expect) - EXPECT_KEYS)
    if unknown:
        raise Usage(f"unknown --expect key: {', '.join(unknown)}")

    def is_list(value):
        return isinstance(value, list) and all(isinstance(item, str) for item in value)

    if not is_list(expect.get("tests")) or not expect["tests"]:
        raise Usage("--expect needs the key tests: a non-empty list of paths")
    for key in ("product", "existing", "bugs"):
        if key in expect and not is_list(expect[key]):
            raise Usage(f"--expect key {key} must be a list of strings")
    if "grouped" in expect and not (
        isinstance(expect["grouped"], dict) and all(isinstance(v, bool) for v in expect["grouped"].values())
    ):
        raise Usage("--expect key grouped must be an object from a path to true or false")
    if "result" in expect and not (
        isinstance(expect["result"], dict)
        and all(v in ("pass", "fail", "not run") for v in expect["result"].values())
    ):
        raise Usage("--expect key result must be an object from a path to pass, fail or not run")
    if "fallback" in expect and expect["fallback"] not in ("none", "detected", "error"):
        raise Usage("--expect key fallback must be none, detected or error")
    if "command_contains" in expect and not isinstance(expect["command_contains"], str):
        raise Usage("--expect key command_contains must be a string")
    if "error_line" in expect and (isinstance(expect["error_line"], bool) or not isinstance(expect["error_line"], int)):
        raise Usage("--expect key error_line must be an integer")
    if expect.get("fallback") == "error" and "error_line" not in expect:
        raise Usage("--expect key fallback error needs the key error_line")
    if ("product" in expect or "existing" in expect) and not has_before:
        raise Usage("--expect keys product and existing need --before")
    return expect


def read_lines(path):
    with open(path, encoding="utf-8-sig") as handle:
        return [line.removesuffix("\r") for line in handle.read().split("\n")]


def toml_groups(repo):
    """The groups of the first toml block of the rules file, or None when it cannot be read."""
    try:
        import tomllib
    except ImportError:
        raise Usage("the grouped check needs Python 3.11 or newer (tomllib)")
    try:
        lines = read_lines(os.path.join(repo, RULES_FILE))
    except (OSError, UnicodeDecodeError):
        return None
    start = next((i for i, line in enumerate(lines) if re.match(r"^```toml(?:\s.*)?$", line)), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^```\s*$", lines[i])), None)
    if end is None:
        return None
    try:
        data = tomllib.loads("\n".join(lines[start + 1:end]))
    except tomllib.TOMLDecodeError:
        return None
    groups = data.get("groups")
    return groups if isinstance(groups, list) else None


def rust_group_selects(command, path):
    """Whether a Rust group command selects a file for write (the Write rule of the Rust entry).

    A group selects a file when it has no crate scope, doc flag, unreadable selector or name filter,
    and it has no --test target or one of its targets holds the file."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
        tokens = tokens[1:]
    if tokens[:1] != ["cargo"]:
        return False
    words = tokens[1:]
    if words[:1] == ["nextest"]:
        words = words[2:]
    elif words[:1] == ["test"]:
        words = words[1:]
    else:
        return False
    flat = []
    for token in words:
        if token.startswith("--") and "=" in token:
            flat.extend(token.split("=", 1))
        else:
            flat.append(token)
    targets = []
    index = 0
    while index < len(flat):
        token = flat[index]
        if token == "--":
            index += 1
        elif token in ("-p", "--package", "--doc") or token in RUST_UNREADABLE:
            return False
        elif token == "--test":
            if index + 1 < len(flat):
                targets.append(flat[index + 1])
            index += 2
        elif token in RUST_VALUE_FLAGS:
            index += 2
        elif token.startswith("-"):
            index += 1
        else:
            return False
    return not targets or any(
        re.search(r"(^|/)tests/" + re.escape(target) + r"(\.rs$|/)", path) for target in targets
    )


VITEST_EXEC = (["npx", "vitest"], ["pnpm", "exec", "vitest"], ["yarn", "vitest"], ["bunx", "vitest"])
VITEST_SUBCOMMANDS = ("run", "watch", "dev", "related", "list", "bench")
VITEST_FIXED_FLAGS = ("--run", "--silent", "--no-color", "--passWithNoTests", "--no-file-parallelism", "--update", "-u", "--coverage")
VITEST_SELECTOR_FLAGS = ("-t", "--testNamePattern", "--project", "-p")
VITEST_VALUE_FLAGS = ("--maxWorkers", "--reporter", "--outputFile", "--retry", "--dir") + VITEST_SELECTOR_FLAGS
VITEST_NO_UPDATE = ("none", "false")


def vitest_group_selects(command, path):
    """Whether a plain Vitest group command selects a file for write (the write column of the TypeScript entry).

    Returns None when the command is not an exec form of Vitest, so the caller keeps the old reading."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
        tokens = tokens[1:]
    words = next((tokens[len(prefix):] for prefix in VITEST_EXEC if tokens[:len(prefix)] == prefix), None)
    if words is None:
        return None
    flat = []
    for token in words:
        if token.startswith("-") and "=" in token:
            flat.extend(token.split("=", 1))
        else:
            flat.append(token)
    subcommand = next((t for t in flat if t in VITEST_SUBCOMMANDS), None)
    if subcommand in ("watch", "dev", "related", "list", "bench"):
        return False
    if subcommand is None and "--run" not in flat:
        return False
    operands, directories = [], []
    index = 0
    while index < len(flat):
        token = flat[index]
        if token == subcommand:
            index += 1
        elif token == "--dir":
            if index + 1 >= len(flat):
                return False
            directories.append(flat[index + 1])
            index += 2
        elif token in ("--watch", "-w"):
            return False
        elif token in ("-u", "--update"):
            if index + 1 < len(flat) and flat[index + 1] in VITEST_NO_UPDATE:
                index += 2
            else:
                return False
        elif token in VITEST_SELECTOR_FLAGS:
            return False
        elif token in VITEST_VALUE_FLAGS:
            index += 2
        elif token in VITEST_FIXED_FLAGS:
            index += 1
        elif token.startswith("-") or re.search(r":\d+$", token):
            return False
        else:
            operands.append(token)
            index += 1
    below = not directories or any(vitest_below(directory, path) for directory in directories)
    return below and (not operands or any(operand in path for operand in operands))


def vitest_below(directory, path):
    """Whether a path is the directory or below it (a leading ./ and a trailing / are dropped)."""
    directory = (directory[2:] if directory.startswith("./") else directory).rstrip("/")
    return directory in ("", ".") or path == directory or path.startswith(directory + "/")


JEST_EXEC = (["npx", "jest"], ["pnpm", "exec", "jest"], ["yarn", "jest"], ["bunx", "jest"])
JEST_FIXED_FLAGS = (
    "--ci", "--runInBand", "-i", "--verbose", "--json", "--silent", "--coverage", "--passWithNoTests",
    "--watchman", "--no-watchman", "--cache", "--no-cache", "--runTestsByPath",
)
JEST_FIXED_VALUE_FLAGS = ("--maxWorkers", "-w", "--outputFile", "--reporters")
JEST_UPDATE_MODES = ("-u", "--updateSnapshot", "--updateSnapshot=true")


def flat_tokens(words, boolean_flags=()):
    """Split a `--flag=value` word into two tokens; keep every other word, and a `--flag=value` of a boolean flag, whole."""
    flat = []
    for token in words:
        if token.startswith("-") and "=" in token and token.split("=", 1)[0] not in boolean_flags:
            flat.extend(token.split("=", 1))
        else:
            flat.append(token)
    return flat


def command_words(command, exec_forms):
    """The words after the exec form of a command (leading NAME=value words dropped), or None."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
        tokens = tokens[1:]
    return next((tokens[len(prefix):] for prefix in exec_forms if tokens[:len(prefix)] == prefix), None)


WRAPPER_MARKERS = ("&&", "||", ";", "|", "$(", "`", ">", "<")


def has_wrapper_marker(command):
    """Whether a command holds a shell marker outside quotes (the entry reads such a command as a wrapper)."""
    unquoted = re.sub(r"\"[^\"]*\"|'[^']*'", "", command)
    return any(marker in unquoted for marker in WRAPPER_MARKERS)


def jest_group_selects(command, path):
    """Whether a plain Jest group command selects a file for write (the write column of the TypeScript entry).

    Returns None when the command is not an exec form of Jest, so the caller keeps the old reading.
    A wrapper (a shell marker outside quotes) selects no file."""
    words = command_words(command, JEST_EXEC)
    if words is None:
        return None
    if has_wrapper_marker(command):
        return False
    if any(word in JEST_UPDATE_MODES for word in words):
        return False
    flat = flat_tokens(words, JEST_FIXED_FLAGS)
    patterns, operands, by_path = [], [], "--runTestsByPath" in flat
    index = 0
    while index < len(flat):
        token = flat[index]
        if token == "--updateSnapshot":
            index += 2
        elif token == "--testPathPatterns":
            if index + 1 >= len(flat):
                return False
            patterns.append(flat[index + 1])
            index += 2
        elif token in JEST_FIXED_VALUE_FLAGS:
            index += 2
        elif token.split("=", 1)[0] in JEST_FIXED_FLAGS:
            index += 1
        elif token.startswith("-"):
            return False
        else:
            operands.append(token)
            index += 1
    selectors = [(pattern, False) for pattern in patterns] + [(operand, by_path) for operand in operands]
    if not selectors:
        return True
    for selector, equal in selectors:
        if equal:
            continue
        if selector.startswith(("^", "/")):
            return False
        try:
            re.compile(selector)
        except re.error:
            return False
    for selector, equal in selectors:
        if equal:
            if (selector[2:] if selector.startswith("./") else selector) == path:
                return True
        elif re.search(selector, path):
            return True
    return False


NODE_FIXED_FLAGS = (
    "--test", "--test-force-exit", "--no-warnings", "--experimental-test-coverage",
)
NODE_FIXED_VALUE_FLAGS = (
    "--test-concurrency", "--test-reporter", "--test-reporter-destination", "--test-timeout",
    "--test-isolation", "--import", "--require", "-r", "--env-file",
)


def glob_regex(pattern):
    """A regular expression for a glob: `**` crosses folders, `*` and `?` do not cross `/`."""
    out, index = "", 0
    while index < len(pattern):
        char = pattern[index]
        if pattern.startswith("**/", index):
            out += "(?:.*/)?"
            index += 3
        elif pattern.startswith("**", index):
            out += ".*"
            index += 2
        elif char == "*":
            out += "[^/]*"
            index += 1
        elif char == "?":
            out += "[^/]"
            index += 1
        else:
            out += re.escape(char)
            index += 1
    return "^" + out + "$"


def node_group_selects(command, path):
    """Whether a plain `node --test` group command selects a file for write (the write column of the TypeScript entry).

    Returns None when the command is not a `node` command with a `--test` token, so the caller keeps the old reading."""
    words = command_words(command, (["node"],))
    if words is None or "--test" not in re.split(r"[\s;|&<>`$()]+", command):
        return None
    if has_wrapper_marker(command):
        return False
    flat = flat_tokens(words)
    operands = []
    index = 0
    while index < len(flat):
        token = flat[index]
        if token in NODE_FIXED_VALUE_FLAGS:
            index += 2
        elif token in NODE_FIXED_FLAGS:
            index += 1
        elif token.startswith("-"):
            return False
        else:
            operands.append(token)
            index += 1
    if not operands:
        return True
    for operand in operands:
        operand = operand[2:] if operand.startswith("./") else operand
        if vitest_below(operand, path) or re.search(glob_regex(operand), path):
            return True
    return False


def selecting_groups(groups, path):
    """Names of the recorded groups that select a file. A name filter or a project flag skips a group."""
    language = LANGUAGES.get(os.path.splitext(path)[1])
    names = []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("name"), str):
            continue
        if group.get("language") != language or not isinstance(group.get("command"), str):
            continue
        if language == "rust":
            if rust_group_selects(group["command"], path):
                names.append(group["name"])
            continue
        selected = None
        for reader in (vitest_group_selects, jest_group_selects, node_group_selects):
            selected = reader(group["command"], path)
            if selected is not None:
                break
        if selected is not None:
            if selected:
                names.append(group["name"])
            continue
        try:
            tokens = shlex.split(group["command"])
        except ValueError:
            continue
        if any(t.split("=", 1)[0] in NAME_FLAGS for t in tokens):
            continue
        operands = [t for t in tokens[1:] if not t.startswith("-") and (("/" in t) or any(c in t for c in "*?["))]
        if not operands:
            names.append(group["name"])
            continue
        for operand in operands:
            operand = operand[2:] if operand.startswith("./") else operand
            if path == operand or path.startswith(operand.rstrip("/") + "/") or fnmatch.fnmatch(path, operand):
                names.append(group["name"])
                break
    return names


def check_repo(repo, before, expect, model):
    failures = []

    def fail(check, message):
        failures.append(f"FAIL {check}: {message}")

    files = model["files"]
    for path in expect["tests"]:
        full = os.path.join(repo, path)
        try:
            with open(full, encoding="utf-8") as handle:
                content = handle.read()
        except (OSError, UnicodeDecodeError):
            fail("tests", f"{path}: the test file does not exist or is not readable")
            continue
        if not ASSERTION.search(content):
            fail("tests", f"{path}: the file holds no assert, expect, should, t.Error or t.Fatal")
    for path in expect.get("product", []):
        try:
            with open(os.path.join(repo, path), "rb") as now, open(os.path.join(before, path), "rb") as was:
                same = now.read() == was.read()
        except OSError:
            fail("product", f"{path}: cannot read the file after or before the run")
            continue
        if not same:
            fail("product", f"{path}: the product file changed")
    for path in expect.get("existing", []):
        try:
            was = [line for line in read_lines(os.path.join(before, path)) if line.strip()]
            now = [line for line in read_lines(os.path.join(repo, path)) if line.strip()]
        except (OSError, UnicodeDecodeError):
            fail("existing", f"{path}: cannot read the file after or before the run")
            continue
        position = 0
        for line in was:
            while position < len(now) and now[position] != line:
                position += 1
            if position == len(now):
                fail("existing", f"{path}: the line {line!r} of the file before the run is missing or moved")
                break
            position += 1
    grouped = expect.get("grouped", {})
    if grouped:
        groups = toml_groups(repo) or []
        for path, want in grouped.items():
            entry = files.get(path)
            if entry is None:
                fail("grouped", f"{path}: the report has no ## File: section for it")
                continue
            cells = {row[4] for row in entry["rows"] if len(row) == len(FILE_COLUMNS)}
            if want:
                selecting = selecting_groups(groups, path)
                if not selecting:
                    fail("grouped", f"{path}: no recorded group of the rules file selects it")
                elif not cells or not cells <= set(selecting):
                    fail("grouped", f"{path}: the Group cells {sorted(cells)} do not all name a selecting group {selecting}")
            elif cells != {"none"}:
                fail("grouped", f"{path}: the Group cells are {sorted(cells)}, not none")
    for path, want in expect.get("result", {}).items():
        entry = files.get(path)
        if entry is None:
            fail("result", f"{path}: the report has no ## File: section for it")
        elif entry["word"] != want:
            fail("result", f"{path}: the run result is {entry['word']}, not {want}")
    if "bugs" in expect:
        if not expect["bugs"] and model["bugs"]:
            fail("bugs", "the report has a ## Found bugs section, but none is expected")
        for name in expect["bugs"]:
            rows = [bug for bug in model["bugs"] if bug["test"] == name]
            if not rows:
                fail("bugs", f"{name}: not in the ## Found bugs section")
            elif not any(bug["source"] for bug in rows):
                fail("bugs", f"{name}: the Source cell is empty")
    wanted = expect.get("command_contains")
    if wanted is not None:
        for path, entry in files.items():
            if entry["command"] is None or wanted not in entry["command"]:
                fail("command_contains", f"{path}: the Command line does not hold {wanted!r}")
        if not files:
            fail("command_contains", "the report has no Command line")
    if "fallback" in expect:
        failures.extend(check_fallback(model["lines"], expect))
    return failures


def check_fallback(lines, expect):
    failures = []
    detected = [line for line in lines if line.strip().startswith("Detected for this run: ")]
    errors = [line.strip() for line in lines if line.strip().startswith("Rules file error: ")]
    mentions = sum(line.count(SETUP_MENTION) for line in lines)
    want = expect["fallback"]

    def fail(message):
        failures.append(f"FAIL fallback: {message}")

    if want == "none":
        if detected or errors:
            fail("the report has a fallback line, but none is expected")
        if mentions:
            fail(f"the report mentions {SETUP_MENTION}, but no fallback is expected")
    elif want == "detected":
        if len(detected) != 1 or errors:
            fail("the report needs exactly one Detected for this run: line and no Rules file error: line")
        if mentions != 1:
            fail(f"the report needs exactly one mention of {SETUP_MENTION}, found {mentions}")
    else:
        if len(errors) != 1 or detected:
            fail("the report needs exactly one Rules file error: line and no Detected for this run: line")
        elif f" (line {expect['error_line']}). " not in errors[0]:
            fail(f"the Rules file error: line does not name ' (line {expect['error_line']}).'")
        if mentions != 1:
            fail(f"the report needs exactly one mention of {SETUP_MENTION}, found {mentions}")
    return failures


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report")
    parser.add_argument("--repo")
    parser.add_argument("--expect")
    parser.add_argument("--before")
    args = parser.parse_args(argv)
    try:
        if (args.repo is None) != (args.expect is None):
            raise Usage("--repo and --expect are given together")
        if args.before is not None and args.repo is None:
            raise Usage("--before needs --repo and --expect")
        expect = None
        if args.expect is not None:
            expect = load_expect(args.expect, args.before is not None)
            if not os.path.isdir(args.repo):
                raise Usage(f"--repo {args.repo!r} is not a folder")
            if args.before is not None and not os.path.isdir(args.before):
                raise Usage(f"--before {args.before!r} is not a folder")
        try:
            text = read_report(args.report)
        except (OSError, UnicodeDecodeError) as error:
            raise Usage(f"cannot read the report: {error}")
        failures, model = check_report(text)
        if expect is not None:
            failures.extend(check_repo(args.repo, args.before, expect, model))
    except Usage as error:
        print(str(error), file=sys.stderr)
        return 2
    print("\n".join(failures + ["FAIL" if failures else "PASS"]))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
