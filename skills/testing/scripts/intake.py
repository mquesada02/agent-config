#!/usr/bin/env python3
"""Read the repo test rules file, detect the repo test facts and print one JSON object.

Usage: python3 intake.py <repo root> [file ...]

Prints {"rules": {...}, "detected": {...}}. "rules" is the check of docs/agents/testing.md.
"detected" holds "languages" (name, root, manifest), "entries" (the language entry of each
[file ...] argument: rust, typescript or general) and "facts" (per language, each fact is
{value, status, source}). The script reads files only: no network, no gh, no child process,
and it never runs repo code. Needs Python 3.11 or newer (tomllib).
Exit code: 0 when the rules file was read (or does not exist), 1 when "rules.error"
is set (the JSON is still printed), 2 for a usage error (also a file outside the repo root).
"""
import collections
import datetime
import glob
import json
import math
import os
import posixpath
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
    # An absent `missing` means all six sections are missing: no file, no toml block or a read error.
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


def counted_languages(settings, fallback=()):
    """The languages of [[languages]], in file order. When the section is absent or of the
    wrong type, the detected languages (fallback) count."""
    entries = settings.get("languages")
    if not is_array_of_tables(entries):
        return list(fallback)
    names = [entry.get("name") for entry in entries]
    return unique(name for name in names if name in LANGUAGES)


def check_sections(settings, fallback=()):
    """The missing_sections list. Drops each required section that is absent or of the wrong
    type from settings."""
    counted = counted_languages(settings, fallback)
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


def read_rules(repo, fallback=()):
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

    settings = parsed
    missing = check_sections(settings, fallback)
    after_block = block.opening + len(block.content) + 1
    prose = lines[: block.opening - 1] + lines[after_block:]
    candidates, unknown = disabled_entries(settings)
    without_reason = [rule_id for rule_id in candidates if not has_reason(rule_id, prose)]
    return result(True, settings, missing, without_reason, unknown)


SKIP_DIRS = frozenset((".git", "node_modules", "target", "dist"))
KIND = {"rust": "Cargo.toml", "typescript": "package.json"}
MANIFESTS = (("Cargo.toml", "rust"), ("package.json", "typescript"))
OTHER_MANIFESTS = (
    "go.mod", "pyproject.toml", "setup.py", "pom.xml", "build.gradle", "build.gradle.kts",
    "Gemfile", "composer.json", "mix.exs", "Package.swift",
)
TS_EXTENSIONS = (".ts", ".tsx", ".js", ".mjs", ".cjs")
TEST_FILE = re.compile(r"\.(?:test|spec)\.(?:js|ts|jsx|tsx|mjs|cjs|mts|cts)$")
SCRIPT_FILE = re.compile(r"\.(?:js|ts|jsx|tsx|mjs|cjs|mts|cts)$")
NODE_TEST_STEM = re.compile(r"^(?:test|test[-.].+|.+[.\-_]test)$")
MAX_DEPTH = 8
LOCKFILES = (
    ("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("package-lock.json", "npm"),
    ("bun.lock", "bun"), ("bun.lockb", "bun"),
)
EXEC = {"npm": "npx", "pnpm": "pnpm exec", "yarn": "yarn", "bun": "bunx"}
TS_FILE_PATTERNS = {
    "vitest": ["**/*.{test,spec}.?(c|m)[jt]s?(x)"],
    "jest": ["**/__tests__/**/*.[jt]s?(x)", "**/?(*.)+(spec|test).[jt]s?(x)"],
    "node:test": ["*.test", "*-test", "*_test", "test-*", "test.*", "test/**"],
}
TS_RUNNERS = {
    "vitest": ("vitest run", "--maxWorkers", "--changed"),
    "jest": ("jest --ci", "--maxWorkers", "--onlyChanged"),
    "node:test": ("node --test", "--test-concurrency", None),
}
NO_MANIFEST = "no manifest in the language root"


def fact(value, status, source):
    return {"value": value, "status": status, "source": source}


def non_json_text(value):
    """The text of a value that JSON cannot hold (a non-finite number, a TOML date or time)."""
    if isinstance(value, float):
        return "nan" if value != value else "inf" if value > 0 else "-inf"
    if isinstance(value, datetime.datetime):
        text = value.isoformat()
        return text[:-6] + "Z" if text.endswith("+00:00") else text
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    return str(value)


def plain(value):
    """The value with every item JSON-safe (no depth rule)."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else non_json_text(value)
    if isinstance(value, list):
        return [plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    return non_json_text(value)


def safe(value, depth=1):
    """A value copied from a repo file, made JSON-safe: a container nested deeper than
    MAX_DEPTH levels is replaced by its JSON text."""
    if isinstance(value, (list, dict)):
        if depth > MAX_DEPTH:
            try:
                return json.dumps(plain(value), separators=(",", ":"), ensure_ascii=False)
            except RecursionError:
                return "<too deeply nested>"
        if isinstance(value, list):
            return [safe(item, depth + 1) for item in value]
        return {str(key): safe(item, depth + 1) for key, item in value.items()}
    return plain(value)


def read_text(path):
    """The text of a file, or None when it is not a regular file or cannot be read or decoded.
    A named pipe or a device is never opened: that could block forever."""
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8-sig") as handle:
            return handle.read()
    except (OSError, ValueError):
        return None


def load(path, parse):
    """(data, state) of a TOML or JSON file. The state is ok, missing or invalid."""
    if not os.path.isfile(path):
        return None, "missing"
    text = read_text(path)
    if text is None:
        return None, "invalid"
    try:
        data = parse(text)
    except (ValueError, RecursionError):
        return None, "invalid"
    return (data, "ok") if isinstance(data, dict) else (None, "invalid")


def walk(base):
    """Every folder under base, sorted, without the skipped folders: (folder, dirs, files)."""
    for current, dirs, names in os.walk(base):
        dirs[:] = sorted(name for name in dirs if name not in SKIP_DIRS)
        yield current, dirs, sorted(names)


def parts_of(current, base):
    rel = os.path.relpath(current, base)
    return [] if rel == "." else rel.split(os.sep)


def find_manifests(repo):
    """The folders (relative, shallowest first, then alphabetical) that hold a manifest."""
    found = {"rust": [], "typescript": []}
    for current, _, names in walk(repo):
        rel = "/".join(parts_of(current, repo)) or "."
        for manifest, language in MANIFESTS:
            if manifest in names:
                found[language].append(rel)
    for folders in found.values():
        folders.sort(key=lambda rel: (root_length(rel), rel))
    return found


def valid_root(value):
    if not isinstance(value, str) or "\x00" in value:
        return None
    root = posixpath.normpath(value)
    if root.startswith("/") or root == ".." or root.startswith("../"):
        return None
    return root


def rules_entries(rules):
    """The valid (name, root) entries of the rules file. An empty list when rules.error is set."""
    if rules["error"] is not None:
        return []
    entries = rules["settings"].get("languages")
    if not is_array_of_tables(entries):
        return []
    found = []
    for entry in entries:
        root = valid_root(entry.get("root"))
        if entry.get("name") in LANGUAGES and root is not None:
            found.append((entry["name"], root))
    return found


def list_languages(repo, entries, manifests):
    languages = []
    for name in LANGUAGES:
        roots = [root for entry_name, root in entries if entry_name == name]
        root = roots[0] if roots else (manifests[name][0] if manifests[name] else None)
        if root is None:
            continue
        manifest = posixpath.normpath(posixpath.join(root, KIND[name]))
        present = os.path.isfile(os.path.join(repo, manifest))
        languages.append({"name": name, "root": root, "manifest": manifest if present else None})
    return languages


def extension_language(rel):
    extension = posixpath.splitext(rel)[1]
    if extension == ".rs":
        return "rust"
    return "typescript" if extension in TS_EXTENSIONS else "general"


def root_length(root):
    return 0 if root == "." else root.count("/") + 1


def route(repo, entries, rel):
    held = [
        (root, name) for name, root in entries
        if root == "." or rel == root or rel.startswith(root + "/")
    ]
    if held:
        longest = max(root_length(root) for root, _ in held)
        names = {name for root, name in held if root_length(root) == longest}
        return names.pop() if len(names) == 1 else extension_language(rel)
    folder = posixpath.dirname(rel) or "."
    while True:
        here = os.path.join(repo, folder)
        known = {name for manifest, name in MANIFESTS if os.path.isfile(os.path.join(here, manifest))}
        if len(known) == 2:
            return extension_language(rel)
        if known:
            return known.pop()
        if any(os.path.isfile(os.path.join(here, manifest)) for manifest in OTHER_MANIFESTS):
            return "general"
        if folder == ".":
            return "general"
        folder = posixpath.dirname(folder) or "."


def scope_path(repo, text):
    """The repo-relative path (with /) of a file argument, or None when it is empty or
    outside the repo root. The check is lexical: no symlink is followed."""
    if text == "":
        return None
    root = os.path.abspath(repo)
    bases = [root, os.path.realpath(repo)]
    path = os.path.normpath(text if os.path.isabs(text) else os.path.join(root, text))
    for base in bases:
        if path == base or path.startswith(base.rstrip(os.sep) + os.sep):
            return os.path.relpath(path, base).replace(os.sep, "/")
    return None


def gitignore_names(repo, root, wanted):
    """(a .gitignore names one of wanted, a .gitignore exists). The .gitignore of the
    language root and of the repo root are both read."""
    exists = named = False
    folders = unique((os.path.normpath(os.path.join(repo, root)), os.path.normpath(repo)))
    for folder in folders:
        path = os.path.join(folder, ".gitignore")
        if not os.path.isfile(path):
            continue
        exists = True
        for line in (read_text(path) or "").splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "!")):
                continue
            if line.startswith("**/"):
                line = line[3:]
            elif line.startswith("/"):
                line = line[1:]
            if line.endswith("/"):
                line = line[:-1]
            named = named or line in wanted
    return named, exists


def commit_fact(library, repo, root, wanted):
    """false when a .gitignore names the files, else true. null (with the status of the
    library fact) when there is no library."""
    if library["value"] is None:
        return fact(None, library["status"], "no library, so no commit rule")
    named, exists = gitignore_names(repo, root, wanted)
    if exists:
        return fact(not named, "detected", ".gitignore")
    return fact(True, "default", "no .gitignore (default: commit the files)")


def limits_facts():
    return {
        "small_ms": fact(100, "default", "default limit of the testing skill"),
        "medium_ms": fact(1000, "default", "default limit of the testing skill"),
    }


def groups_fact():
    return fact([], "unknown", "runner configs that hold groups are code and are not run")


def rust_dependencies(data):
    names = set()
    tables = [data.get(key) for key in ("dependencies", "dev-dependencies", "build-dependencies")]
    workspace = data.get("workspace")
    tables.append(workspace.get("dependencies") if isinstance(workspace, dict) else None)
    for table in tables:
        if isinstance(table, dict):
            names.update(table)
    return names


def rust_manifests(base):
    """(readable manifests as (folder, data), the root state, the first problem text)."""
    root_data, root_state = load(os.path.join(base, "Cargo.toml"), tomllib.loads)
    manifests, problem = [], None
    if root_state == "invalid":
        problem = "Cargo.toml is not valid TOML"
    if root_state != "ok":
        return manifests, root_state, problem
    manifests.append((".", root_data))
    workspace = root_data.get("workspace")
    listed = workspace.get("members") if isinstance(workspace, dict) else None
    for pattern in listed if isinstance(listed, list) else []:
        if not isinstance(pattern, str):
            continue
        if any(char in pattern for char in "*?["):
            matches = sorted(glob.glob(os.path.join(glob.escape(base), pattern)))
            folders = [path for path in matches if os.path.isfile(os.path.join(path, "Cargo.toml"))]
        else:
            folders = [os.path.join(base, pattern)]
        for folder in folders:
            data, state = load(os.path.join(folder, "Cargo.toml"), tomllib.loads)
            rel = posixpath.normpath(os.path.relpath(folder, base).replace(os.sep, "/"))
            if state == "ok":
                manifests.append((rel, data))
            elif problem is None:
                problem = f"{rel}/Cargo.toml is " + ("missing" if state == "missing" else "not valid TOML")
    return manifests, root_state, problem


def nextest_facts(base):
    path = os.path.join(base, ".config", "nextest.toml")
    if not os.path.isfile(path):
        why = "no .config/nextest.toml"
        return {
            "profiles": fact([], "default", why), "test_groups": fact([], "default", why),
            "retries": fact({}, "default", why), "timeouts": fact({}, "default", why),
        }
    data, state = load(path, tomllib.loads)
    if state != "ok":
        why = ".config/nextest.toml is not valid TOML"
        return {
            "profiles": fact([], "unknown", why), "test_groups": fact([], "unknown", why),
            "retries": fact({}, "unknown", why), "timeouts": fact({}, "unknown", why),
        }
    profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
    groups = data.get("test-groups") if isinstance(data.get("test-groups"), dict) else {}
    retries, timeouts = {}, {}
    for name, entry in profile.items():
        if not isinstance(entry, dict):
            continue
        if "retries" in entry:
            retries[name] = safe(entry["retries"])
        limits = {key: safe(entry[key]) for key in ("slow-timeout", "global-timeout") if key in entry}
        if limits:
            timeouts[name] = limits
    source = ".config/nextest.toml"
    return {
        "profiles": fact(sorted(profile), "detected", source),
        "test_groups": fact(sorted(groups), "detected", source),
        "retries": fact(retries, "detected", source),
        "timeouts": fact(timeouts, "detected", source),
    }


def rust_test_paths(base):
    found = set()
    for current, _, names in walk(base):
        parts = parts_of(current, base)
        for name in names:
            if not name.endswith(".rs"):
                continue
            if "tests" in parts:
                found.add("/".join(parts[: len(parts) - parts[::-1].index("tests")]))
            elif "src" in parts:
                text = read_text(os.path.join(current, name))
                if text is not None and "#[cfg(test)]" in text:
                    found.add("/".join(parts[: len(parts) - parts[::-1].index("src")]))
    return sorted(found)


def rust_facts(repo, root):
    base = os.path.join(repo, root)
    nextest_present = os.path.isfile(os.path.join(base, ".config", "nextest.toml"))
    runner = (
        fact("nextest", "detected", ".config/nextest.toml") if nextest_present
        else fact("cargo test", "default", "no .config/nextest.toml")
    )
    manifests, root_state, problem = rust_manifests(base)
    unreadable = "no Cargo.toml" if root_state == "missing" else problem

    if runner["value"] == "cargo test":
        doc = fact(None, "default", "cargo test runs doc tests")
    elif root_state == "missing":
        doc = fact(None, "unknown", "no Cargo.toml")
    elif problem:
        doc = fact(None, "unknown", problem)
    else:
        libs = [data for folder, data in manifests if os.path.isfile(os.path.join(base, folder, "src", "lib.rs"))]
        usable = [data for data in libs if not (isinstance(data.get("lib"), dict) and data["lib"].get("doctest") is False)]
        if usable:
            doc = fact("cargo test --doc", "detected", "Cargo.toml and src/lib.rs")
        elif not libs:
            doc = fact(None, "default", "no src/lib.rs")
        else:
            doc = fact(None, "default", "doctest = false")
    nextest = runner["value"] == "nextest"
    commands = {
        "test": fact("cargo nextest run" if nextest else "cargo test", runner["status"], runner["source"]),
        "worker_flag": fact("-j" if nextest else "-- --test-threads", "default", "flag of the runner"),
        "changed": fact(None, "default", "neither cargo test nor nextest has a changed-files command"),
        "doc": doc,
    }

    if unreadable:
        features = fact([], "unknown", unreadable)
    else:
        names = set()
        for _, data in manifests:
            tests = data.get("test")
            for entry in tests if isinstance(tests, list) else []:
                required = entry.get("required-features") if isinstance(entry, dict) else None
                if isinstance(required, list):
                    names.update(item for item in required if isinstance(item, str))
        features = fact(sorted(names), "detected", "Cargo.toml [[test]] required-features")
    runner_facts = {"name": runner, **nextest_facts(base), "features": features}

    if root_state != "ok":
        members = fact([], "unknown", unreadable)
    else:
        root_data = manifests[0][1]
        workspace = root_data.get("workspace")
        listed = workspace.get("members") if isinstance(workspace, dict) else None
        package = root_data.get("package")
        name = package.get("name") if isinstance(package, dict) else None
        if isinstance(listed, list):
            members = fact(safe(listed), "detected", "Cargo.toml [workspace] members")
        elif isinstance(name, str):
            members = fact([name], "detected", "Cargo.toml [package] name")
        else:
            members = fact([], "detected", "Cargo.toml has no workspace members and no package name")
    layout = {
        "test_paths": fact(rust_test_paths(base), "detected", "tests folders and #[cfg(test)] in src"),
        "file_pattern": fact(["tests/*.rs", "#[cfg(test)] modules"], "default", "Rust test layout"),
        "setup_files": fact([], "default", "Rust has no runner setup files"),
        "members": members,
    }

    if unreadable:
        library = {key: fact(None, "unknown", unreadable) for key in ("property", "snapshot", "fakes", "async")}
    else:
        deps = set()
        for _, data in manifests:
            deps |= rust_dependencies(data)
        def pick(*names):
            return next((name for name in names if name in deps), None)
        source = "Cargo.toml dependency tables"
        library = {
            "property": fact(pick("proptest", "quickcheck"), "detected", source),
            "snapshot": fact(pick("insta"), "detected", source),
            "fakes": fact(pick("mockall"), "detected", source),
            "async": fact(pick("tokio", "async-std"), "detected", source),
        }
    library["commit_regressions"] = commit_fact(library["property"], repo, root, ("proptest-regressions",))
    library["commit_snapshots"] = commit_fact(library["snapshot"], repo, root, ("*.snap",))
    return {
        "commands": commands, "runner": runner_facts, "layout": layout,
        "libraries": library, "groups": groups_fact(), "limits": limits_facts(),
    }


def scan_typescript(base):
    """(first path segments of the test files, a test file imports node:test, snapshots exist)."""
    tops, imports, snapshots = set(), False, False
    for current, dirs, names in walk(base):
        parts = parts_of(current, base)
        snapshots = snapshots or "__snapshots__" in dirs
        for name in names:
            snapshots = snapshots or name.endswith(".snap")
            if TEST_FILE.search(name) or "__tests__" in parts:
                tops.add(parts[0] if parts else ".")
            if not imports and SCRIPT_FILE.search(name) and (
                    TEST_FILE.search(name) or "__tests__" in parts or "test" in parts
                    or NODE_TEST_STEM.match(os.path.splitext(name)[0])):
                text = read_text(os.path.join(current, name))
                imports = text is not None and "node:test" in text
    return sorted(tops), imports, snapshots


def typescript_facts(repo, root):
    base = os.path.join(repo, root)
    pkg, state = load(os.path.join(base, "package.json"), json.loads)
    broken = "package.json is not valid JSON"
    pkg = pkg or {}
    scripts = pkg.get("scripts") if isinstance(pkg.get("scripts"), dict) else {}
    deps = set()
    for key in ("dependencies", "devDependencies"):
        if isinstance(pkg.get(key), dict):
            deps.update(pkg[key])
    test_paths, imports, snapshots = scan_typescript(base)

    field = pkg.get("packageManager")
    manager_name = field.split("@")[0] if isinstance(field, str) else ""
    if manager_name in EXEC:
        manager = fact(manager_name, "detected", "package.json packageManager")
    else:
        manager = None
        folders = unique((base, repo))
        for lockfile, name in LOCKFILES:
            if any(os.path.isfile(os.path.join(folder, lockfile)) for folder in folders):
                manager = fact(name, "detected", lockfile)
                break
        manager = manager or fact("npm", "default", "no supported packageManager field and no lockfile")
    pm = manager["value"]
    prefix = EXEC.get(pm, "npx")

    runner_name = None
    found = [name for name in ("vitest", "jest") if name in deps]
    if len(found) == 2:
        script = scripts.get("test")
        runner_name = next((name for name in found if isinstance(script, str) and name in script), "vitest")
    elif found:
        runner_name = found[0]
    elif any(isinstance(item, str) and ("node --test" in item or "node:test" in item) for item in scripts.values()):
        runner_name = "node:test"
    if runner_name is None and imports:
        runner_name = "node:test"
    if runner_name:
        runner = fact(runner_name, "detected", "package.json dependencies, scripts or test files")
        run, flag, changed = TS_RUNNERS[runner_name]
        test_command = "node --test" if runner_name == "node:test" else f"{prefix} {run}"
        commands = {
            "test": fact(test_command, "detected", runner["source"]),
            "worker_flag": fact(flag, "default", "flag of the runner"),
            "changed": fact(changed, "default", "changed-files flag of the runner" if changed else "node:test has no changed-files flag"),
        }
        file_pattern = fact(TS_FILE_PATTERNS[runner_name], "default", "default test file patterns of the runner")
        snapshot = fact(runner_name if snapshots else None, "detected", "__snapshots__ folders and .snap files")
    else:
        why = broken if state == "invalid" else "no test runner dependency, node --test script or node:test import"
        runner = fact(None, "unknown", why)
        commands = {key: fact(None, "unknown", why) for key in ("test", "worker_flag", "changed")}
        file_pattern = fact(None, "unknown", why)
        snapshot = fact(None, "unknown", why)

    tsconfig = os.path.isfile(os.path.join(base, "tsconfig.json"))
    name = next((item for item in ("typecheck", "type-check", "tsc") if item in scripts), None)
    if name:
        commands["typecheck"] = fact(f"{pm} run {name}", "detected", "package.json scripts")
    elif "typescript" in deps or tsconfig:
        commands["typecheck"] = fact(f"{prefix} tsc --noEmit", "default", "typescript dependency or tsconfig.json")
    elif state == "invalid":
        commands["typecheck"] = fact(None, "unknown", broken)
    else:
        commands["typecheck"] = fact(
            None, "default", "no typecheck script, no typescript dependency, no tsconfig.json")

    version = None
    for filename in (".nvmrc", ".node-version"):
        for folder in unique((base, repo)):
            lines = [item.strip() for item in (read_text(os.path.join(folder, filename)) or "").splitlines()]
            first = next((item for item in lines if item), None)
            if first:
                version = fact(first, "detected", filename)
                break
        if version:
            break
    engines = pkg.get("engines")
    if version is None and isinstance(engines, dict) and "node" in engines:
        version = fact(safe(engines["node"]), "detected", "package.json engines.node")
    version = version or fact(None, "unknown", broken if state == "invalid" else "no .nvmrc, .node-version or engines.node")
    kind = pkg.get("type")
    if kind in ("module", "commonjs"):
        module_format = fact("esm" if kind == "module" else "commonjs", "detected", "package.json type")
    else:
        module_format = fact("commonjs", "default", "no type field in package.json")
    runner_facts = {"name": runner, "node_version": version, "package_manager": manager, "module_format": module_format}

    layout = {
        "test_paths": fact(test_paths, "detected", "test files under the language root"),
        "file_pattern": file_pattern,
        "setup_files": fact([], "unknown", "the runner config is code and is not run"),
    }
    why = broken if state == "invalid" else "no package.json in the language root"
    if state == "ok":
        fakes = sorted({"msw", "nock", "sinon", "@sinonjs/fake-timers"} & deps)
        library = {
            "property": fact("fast-check" if "fast-check" in deps else None, "detected", "package.json dependencies"),
            "fakes": fact(fakes, "detected", "package.json dependencies"),
        }
    else:
        library = {"property": fact(None, "unknown", why), "fakes": fact([], "unknown", why)}
    library["snapshot"] = snapshot
    library["async"] = fact(None, "default", "async is built into the language")
    library["commit_regressions"] = fact(None, "default", "TypeScript has no regression files")
    library["commit_snapshots"] = commit_fact(snapshot, repo, root, ("__snapshots__", "*.snap"))
    return {
        "commands": commands, "runner": runner_facts, "layout": layout,
        "libraries": library, "groups": groups_fact(), "limits": limits_facts(),
    }


def detect(repo, rules, scoped, manifests):
    entries = rules_entries(rules)
    languages = list_languages(repo, entries, manifests)
    build = {"rust": rust_facts, "typescript": typescript_facts}
    return {
        "languages": languages,
        "entries": {text: route(repo, entries, rel) for text, rel in scoped},
        "facts": {item["name"]: build[item["name"]](repo, item["root"]) for item in languages},
    }


def main(argv):
    if len(argv) < 2 or not os.path.isdir(argv[1]):
        print("usage: intake.py <repo root> [file ...]", file=sys.stderr)
        return 2
    repo = argv[1]
    scoped = []
    for text in argv[2:]:
        rel = scope_path(repo, text)
        if rel is None:
            print(f"usage: the file {text!r} is empty or outside the repo root", file=sys.stderr)
            return 2
        scoped.append((text, rel))
    manifests = find_manifests(repo)
    try:
        rules = read_rules(repo, [name for name in LANGUAGES if manifests[name]])
        json.dumps(rules, indent=2, default=str, allow_nan=False)
    except (RecursionError, ValueError):
        rules = failure("the settings cannot be read as JSON (nan, inf or nesting too deep)", None)
    detected = detect(repo, rules, scoped, manifests)
    print(json.dumps({"rules": rules, "detected": detected}, indent=2, default=str, allow_nan=False))
    return 1 if rules["error"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
