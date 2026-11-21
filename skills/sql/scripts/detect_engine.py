#!/usr/bin/env python3
"""Decide the database engine of a repo, or of one file, and print one JSON object.

Usage: python3 detect_engine.py <repo root> [--file <path>] [--request <engine name>]

`--file` is a path in the repo (relative to the root, or absolute). `--request` is the engine that
the user's request names. The script reads the rules file, the root `package.json`, the text files
of the repo (for connection string schemes) and the driver imports of the `--file` file. It runs
no tool and makes no database connection. It never prints a connection string: only driver names,
scheme names and file paths.

Output keys: `engine` (lowercase, or null when the skill must ask), `signal` (`paths`, `name`,
`import`, `repo`, `request` or `default`, or null), `ask` (null, `clash` or `no_signal`) and
`evidence` (every signal found, each with `signal`, `engine` and `source`).

Exit code: 0 when it ran, 2 for a usage error (one line on stderr, nothing on stdout).
"""
import json
import os
import posixpath
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rules_file  # noqa: E402
import sql_text  # noqa: E402
from detect_formatter import Repo  # noqa: E402
from extract import JS_EXTENSIONS  # noqa: E402

DRIVERS = {
    "pg": "postgres", "postgres": "postgres", "pg-promise": "postgres",
    "mysql": "mysql", "mysql2": "mysql",
    "better-sqlite3": "sqlite", "sqlite3": "sqlite",
    "mssql": "sqlserver", "tedious": "sqlserver",
    "oracledb": "oracle",
}
SCHEMES = (
    ("postgres://", "postgres"), ("postgresql://", "postgres"), ("mysql://", "mysql"),
    ("sqlite:", "sqlite"), ("mssql://", "sqlserver"), ("sqlserver://", "sqlserver"),
)
SCHEME_PATTERNS = [
    (scheme, engine, re.compile(r"(?<![\w+.\-])" + re.escape(scheme) + r"(?=\S)", re.I))
    for scheme, engine in SCHEMES
]
ALIASES = {"postgresql": "postgres"}

SKIPPED_FOLDERS = frozenset(("node_modules", "dist", "build", "coverage"))
MAX_FILES = 1000
MAX_READ = 1024 * 1024
BINARY_PROBE = 8 * 1024

IMPORT_PATTERNS = [
    re.compile(r"""\bimport\s+(?:[\w$*{},\s]+?\bfrom\s*)?(['"])([^'"\n]+)\1"""),
    re.compile(r"""\bexport\s+[\w$*{},\s]+?\bfrom\s*(['"])([^'"\n]+)\1"""),
    re.compile(r"""\brequire\s*\(\s*(['"])([^'"\n]+)\1\s*\)"""),
    re.compile(r"""\bimport\s*\(\s*(['"])([^'"\n]+)\1\s*\)"""),
]


def canonical(name):
    """The engine key of a name: trimmed, lowercase, and `postgresql` is `postgres`."""
    lowered = name.strip().lower()
    return ALIASES.get(lowered, lowered)


def relative_file(root, file):
    """The path of `file` relative to `root` with `/` as separator, or a UsageError."""
    if not file.strip():
        raise sql_text.UsageError("--file needs a path")
    relative = os.path.relpath(os.path.normpath(os.path.join(root, file)), root)
    if relative == os.pardir or relative.startswith(os.pardir + os.sep) or relative == os.curdir:
        raise sql_text.UsageError("--file is not a file inside the repo: " + file)
    return relative.replace(os.sep, "/")


def clean_folder(folder):
    """The folder of a `paths` entry in clean form, or None when it is not valid."""
    folder = folder.strip()
    if not folder or folder.startswith("/") or ".." in folder.split("/"):
        return None
    return posixpath.normpath(folder)


def rules_signals(root, file):
    """(the `paths` evidence or None, the `name` evidence or None) of the rules file."""
    settings = rules_file.read_rules(root)["settings"]
    section = settings.get("engine")
    if not isinstance(section, dict):
        return None, None
    name_entry = None
    name = section.get("name")
    if isinstance(name, str) and name.strip():
        engine = canonical(name)
        name_entry = {"signal": "name", "engine": engine, "source": "engine.name"}
    path_entry = None
    paths = section.get("paths")
    if file is not None and isinstance(paths, list):
        best = -1
        for entry in paths:
            if not isinstance(entry, str) or "=" not in entry:
                continue
            raw_folder, _, raw_engine = entry.rpartition("=")
            folder = clean_folder(raw_folder)
            if folder is None or not raw_engine.strip():
                continue
            if folder != "." and file != folder and not file.startswith(folder + "/"):
                continue
            length = 0 if folder == "." else len(folder)
            if length > best:
                best = length
                engine = canonical(raw_engine)
                path_entry = {"signal": "paths", "engine": engine, "source": f"engine.paths {folder}={engine}"}
    return path_entry, name_entry


def strip_comments(text):
    """The text with the `//` and `/* */` comments removed. Strings are kept; regex literals are not parsed."""
    out = []
    index, length = 0, len(text)
    while index < length:
        char = text[index]
        if char in "'\"`":
            end = index + 1
            while end < length and text[end] != char:
                if text[end] == "\\":
                    end += 1
                elif text[end] == "\n" and char != "`":
                    break
                end += 1
            out.append(text[index:end + 1])
            index = end + 1
        elif text.startswith("//", index):
            end = text.find("\n", index)
            index = length if end < 0 else end
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            out.append(" ")
            index = length if end < 0 else end + 2
        else:
            out.append(char)
            index += 1
    return "".join(out)


def read_text(path):
    """The first MiB of a file as text, or None when it cannot be read or is binary."""
    try:
        with open(path, "rb") as handle:
            data = handle.read(MAX_READ)
    except OSError:
        return None
    if b"\0" in data[:BINARY_PROBE]:
        return None
    return data.decode("utf-8", "replace")


def import_entries(root, file):
    """One evidence entry per driver that the JS or TS file imports (sorted by driver name)."""
    if file is None or not file.endswith(JS_EXTENSIONS):
        return []
    text = read_text(os.path.join(root, file))
    if text is None or not any(driver in text for driver in DRIVERS):
        return []
    source = strip_comments(text)
    drivers = set()
    for pattern in IMPORT_PATTERNS:
        for match in pattern.finditer(source):
            module = match.group(2)
            if module.startswith((".", "/", "@")):
                continue
            package = module.split("/")[0]
            if package in DRIVERS:
                drivers.add(package)
    return [
        {"signal": "import", "engine": DRIVERS[driver], "source": f"import {driver} in {file}"}
        for driver in sorted(drivers)
    ]


def find_files(root):
    found = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIPPED_FOLDERS and not d.startswith(".")]
        for name in files:
            found.append(os.path.relpath(os.path.join(folder, name), root).replace(os.sep, "/"))
    return sorted(found)[:MAX_FILES]


def scheme_entries(root):
    """One evidence entry per distinct scheme found in the text files, with the first path."""
    first = {}
    for path in find_files(root):
        full = os.path.join(root, path)
        if os.path.islink(full):
            continue
        text = read_text(full)
        if text is None:
            continue
        for scheme, engine, pattern in SCHEME_PATTERNS:
            if scheme not in first and pattern.search(text):
                first[scheme] = (engine, path)
        if len(first) == len(SCHEMES):
            break
    return [
        {"signal": "repo", "engine": first[scheme][0], "source": f"scheme {scheme} in {first[scheme][1]}"}
        for scheme, _ in SCHEMES
        if scheme in first
    ]


def dependency_entries(root):
    names = sorted(name for name in Repo(root, None).dependencies() if name in DRIVERS)
    return [{"signal": "repo", "engine": DRIVERS[name], "source": f"dependency {name}"} for name in names]


def decide(paths_entry, name_entry, imports, repo_entries, request):
    """(engine, signal, ask) by the order of signals of spec 920."""
    if paths_entry:
        return paths_entry["engine"], "paths", None
    if name_entry:
        return name_entry["engine"], "name", None
    import_engines = {entry["engine"] for entry in imports}
    repo_engines = {entry["engine"] for entry in repo_entries}
    repo_signal = repo_signal_name = None
    if len(import_engines) == 1:
        repo_signal, repo_signal_name = next(iter(import_engines)), "import"
    elif len(repo_engines) == 1:
        repo_signal, repo_signal_name = next(iter(repo_engines)), "repo"
    if request and repo_signal and request != repo_signal:
        return None, None, "clash"
    if repo_signal:
        return repo_signal, repo_signal_name, None
    if request:
        return request, "request", None
    if len(repo_engines) >= 2:
        return None, None, "no_signal"
    return "postgres", "default", None


def detect(root, file, request):
    paths_entry, name_entry = rules_signals(root, file)
    imports = import_entries(root, file)
    repo_entries = dependency_entries(root) + scheme_entries(root)
    engine, signal, ask = decide(paths_entry, name_entry, imports, repo_entries, request)
    evidence = [entry for entry in (paths_entry, name_entry) if entry] + imports + repo_entries
    if request:
        evidence.append({"signal": "request", "engine": request, "source": "request"})
    return {"engine": engine, "signal": signal, "ask": ask, "evidence": evidence}


def main(argv):
    try:
        positional, options = sql_text.parse_arguments(argv, 1, single=("--file", "--request"))
        root = positional[0]
        if not os.path.isdir(root):
            raise sql_text.UsageError("not a folder: " + root)
        root = os.path.abspath(root)
        file = relative_file(root, options["--file"][0]) if "--file" in options else None
        request = None
        if "--request" in options:
            request = canonical(options["--request"][0])
            if not request:
                raise sql_text.UsageError("--request needs an engine name")
    except sql_text.UsageError as error:
        return sql_text.usage_failure(error)
    print(json.dumps(detect(root, file, request), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
