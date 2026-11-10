#!/usr/bin/env python3
"""Plan and write the rules file and the allowlist file of `/sql setup`. Prints one JSON object.

Usage: python3 setup_files.py services <name>...
       python3 setup_files.py plan <repo root> --proposal <json file>
       python3 setup_files.py write <repo root> --proposal <json file> --confirm <digest>

`services` checks the names against the PG service file (the `[name]` headers only; the password
file is never opened). `plan` writes nothing: it prints the new text of the two files, their
diffs, the conflicts with the existing files and a digest of the new texts. `write` recomputes
the plan and writes both files only when its digest equals `--confirm`.

The proposal is a JSON object with optional `settings` (a table of the tables `style`,
`formatter`, `sources` and `rules`), `prose_rules` (a list of rule texts to append) and
`services` (a list of PG service names). An existing file is edited in place: only a replaced key
line changes, and rule texts are appended.

Exit code: 0 when `ok` is true, 1 when `ok` is false, 2 for a usage error (one line on stderr,
nothing on stdout).
"""
import difflib
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
import tomllib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import allowlist  # noqa: E402
import rules_file  # noqa: E402
import sql_text  # noqa: E402

SETTING_SECTIONS = rules_file.SECTIONS
DEFAULTS = {
    "style": dict(sql_text.DEFAULT_STYLE),
    "formatter": {"tool": "none"},
    "sources": {"tags": []},
    "rules": {"disabled": []},
}
REPO_RULES_HEADING = "## Repo rules"
BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")
SECTION_HEADER = re.compile(r"^\s*\[\s*([A-Za-z0-9_-]+)\s*\]\s*(?:#.*)?$")
KEY_LINE = re.compile(r"^(\s*)([A-Za-z0-9_-]+)\s*=")
BULLET = re.compile(r"^\s*[-*]\s+(.*\S)\s*$")
HEADING = re.compile(r"^#{1,6}\s")
REPO_RULES = re.compile(r"^##\s+Repo rules\s*$")
BOM = b"\xef\xbb\xbf"
FILE_MODE = 0o600
FOLDER_MODE = 0o700


class Refusal(Exception):
    """A plan that cannot be made (`ok` false)."""

    def __init__(self, reason, message, **extra):
        super().__init__(message)
        self.output = {"ok": False, "reason": reason, "message": message, **extra}


# --- values ------------------------------------------------------------------


def same(left, right):
    """Equality with the types checked (True is not 1)."""
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(same(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(same(a, b) for a, b in zip(left, right))
    return type(left) is type(right) and left == right


def toml_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    return repr(value)


def scalar(value):
    return isinstance(value, (str, bool, int)) or (isinstance(value, float) and math.isfinite(value))


def parse_proposal(data):
    if not isinstance(data, dict):
        raise sql_text.UsageError("the proposal is not a JSON object")
    unknown = set(data) - {"settings", "prose_rules", "services"}
    if unknown:
        raise sql_text.UsageError("unknown key in the proposal: " + ", ".join(sorted(unknown)))
    settings = data.get("settings", {})
    if not isinstance(settings, dict):
        raise sql_text.UsageError("settings must be a table of tables")
    for section, table in settings.items():
        if section not in SETTING_SECTIONS or not isinstance(table, dict):
            raise sql_text.UsageError("settings.%s is not one of the tables %s" % (section, ", ".join(SETTING_SECTIONS)))
        for key, value in table.items():
            if not BARE_KEY.fullmatch(key):
                raise sql_text.UsageError("settings.%s: bad key %r" % (section, key))
            if not (scalar(value) or (isinstance(value, list) and all(scalar(item) for item in value))):
                raise sql_text.UsageError("settings.%s.%s must be a string, boolean, number or a list of them" % (section, key))
    rules = data.get("prose_rules", [])
    if not isinstance(rules, list) or not all(isinstance(r, str) and r.strip() and "\n" not in r and "\r" not in r for r in rules):
        raise sql_text.UsageError("prose_rules must be a list of one-line texts")
    services = data.get("services")
    if services is not None:
        if not isinstance(services, list) or not all(
            isinstance(s, str) and allowlist.SERVICE_NAME.fullmatch(s) for s in services
        ):
            raise sql_text.UsageError("services must be a list of names made of letters, digits, _ . -")
        services = list(dict.fromkeys(services))
    return settings, [rule.strip() for rule in rules], services


# --- text files --------------------------------------------------------------


class TextFile:
    """The text of a file as lines that keep their own line end, with its BOM and first line end."""

    def __init__(self, raw):
        self.bom = raw.startswith(BOM)
        text = raw[len(BOM):].decode("utf-8") if self.bom else raw.decode("utf-8")
        self.lines = re.findall(r"[^\n]*\n|[^\n]+", text)
        first = next((line for line in self.lines if line.endswith("\n")), "\n")
        self.eol = "\r\n" if first.endswith("\r\n") else "\n"

    def content(self, index):
        return self.lines[index].rstrip("\n").removesuffix("\r")

    def make(self, content):
        return content + self.eol

    def terminate_last(self):
        if self.lines and not self.lines[-1].endswith("\n"):
            self.lines[-1] += self.eol

    def text(self):
        return "".join(self.lines)


def apply_edits(lines, edits):
    """`edits` is a list of (position, removed count, new lines, priority); applied from the end."""
    lines = list(lines)
    for position, removed, new, _ in sorted(edits, key=lambda e: (-e[0], e[3])):
        lines[position:position + removed] = new
    return lines


def unified(name, old, new):
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), "a/" + name, "b/" + name))


def read_raw(path):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except FileNotFoundError:
        return None


# --- rules file --------------------------------------------------------------


def read_with_reader(text, bom=False):
    """The result of `rules_file.py` for this text."""
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, rules_file.RULES_FILE)
        os.makedirs(os.path.dirname(path))
        with open(path, "wb") as handle:
            handle.write((BOM if bom else b"") + text.encode("utf-8"))
        return rules_file.read_rules(folder)


def new_rules_text(settings, prose_rules):
    lines = ["# SQL rules", "", "```toml"]
    for index, section in enumerate(SETTING_SECTIONS):
        table = dict(DEFAULTS[section])
        table.update(settings.get(section, {}))
        if index:
            lines.append("")
        lines.append("[%s]" % section)
        lines.extend("%s = %s" % (key, toml_value(value)) for key, value in table.items())
    lines += ["```", "", REPO_RULES_HEADING, ""]
    lines.extend("- " + rule for rule in prose_rules)
    return "\n".join(lines) + "\n"


def value_span(content, start):
    """Index of the last line of the value that starts on line `start` of the block content."""
    for end in range(start, len(content)):
        try:
            tomllib.loads("\n".join(content[start:end + 1]) + "\n")
        except tomllib.TOMLDecodeError:
            continue
        return end
    return start


def scan_block(content):
    """The `[name]` tables of a block: header line, keys (line span) and the line of the last key."""
    sections = {}
    current = None
    index = 0
    while index < len(content):
        line = content[index]
        header = SECTION_HEADER.match(line)
        if header:
            current = header.group(1)
            sections.setdefault(current, {"header": index, "keys": {}, "last": index})
            index += 1
            continue
        if line.lstrip().startswith("["):
            current = None
            index += 1
            continue
        key = KEY_LINE.match(line)
        if key:
            end = value_span(content, index)
            if current in sections:
                sections[current]["keys"][key.group(2)] = (index, end, key.group(1))
                sections[current]["last"] = end
            index = end + 1
            continue
        index += 1
    return sections


def edit_block(file, proposal, current, conflicts):
    """The edits that put the proposal into the first toml block of an existing file."""
    lines = [file.content(i) for i in range(len(file.lines))]
    block = rules_file.toml_blocks(lines)[0]
    first = block.opening
    content = block.content
    sections = scan_block(content)
    edits = []
    for section, table in proposal.items():
        if not table:
            continue
        if section not in sections:
            added = []
            if content and content[-1].strip():
                added.append(file.make(""))
            added.append(file.make("[%s]" % section))
            added.extend(file.make("%s = %s" % (key, toml_value(value))) for key, value in table.items())
            edits.append((first + len(content), 0, added, 0))
            continue
        info = sections[section]
        inserted = []
        for key, value in table.items():
            if key in info["keys"]:
                start, end, indent = info["keys"][key]
                old = current.get(section, {}).get(key)
                if not same(old, value):
                    conflicts.append(
                        {"target": "rules_file", "section": section, "key": key, "current": old, "proposed": value}
                    )
                    last_line = file.lines[first + end]
                    terminator = last_line[len(last_line.rstrip("\r\n")):] or file.eol
                    edits.append((first + start, end - start + 1, ["%s%s = %s%s" % (indent, key, toml_value(value), terminator)], 1))
            else:
                inserted.append(file.make("%s = %s" % (key, toml_value(value))))
        if inserted:
            edits.append((first + info["last"] + 1, 0, inserted, 1))
    return edits, block


def structural_lines(file):
    """Indexes of the lines that are Markdown structure: not inside a fenced code block or an HTML
    comment, and not a fence or comment marker line."""
    found = set()
    fence = None
    comment = False
    for index in range(len(file.lines)):
        line = file.content(index).strip()
        if comment:
            comment = "-->" not in line
        elif fence:
            if line.startswith(fence):
                fence = None
        elif line.startswith(("```", "~~~")):
            fence = line[:3]
        elif line.startswith("<!--"):
            comment = "-->" not in line
        else:
            found.add(index)
    return found


def prose_edits(file, rules, block):
    """The edits that append rule texts, and the lists of appended and skipped texts."""
    existing = {m.group(1) for m in map(BULLET.match, (file.content(i) for i in range(len(file.lines)))) if m}
    appended, skipped = [], []
    for rule in dict.fromkeys(rules):
        if rule in existing:
            skipped.append(rule)
        else:
            appended.append(rule)
    if not appended:
        return [], appended, skipped
    bullets = [file.make("- " + rule) for rule in appended]
    inside = set(range(block.opening - 1, block.opening + len(block.content) + 1)) if block else set()
    structure = structural_lines(file)
    outside = [i for i in range(len(file.lines)) if i not in inside and i in structure]
    heading = next((i for i in outside if REPO_RULES.match(file.content(i))), None)
    if heading is None:
        file.terminate_last()
        lead = [file.make("")] if file.lines and file.content(len(file.lines) - 1).strip() else []
        return [(len(file.lines), 0, lead + [file.make(REPO_RULES_HEADING), file.make("")] + bullets, 0)], appended, skipped
    end = next((i for i in outside if i > heading and HEADING.match(file.content(i))), len(file.lines))
    last = None
    for i in outside:
        if heading < i < end and BULLET.match(file.content(i)):
            last = i
    if last is None:
        if heading + 1 < len(file.lines) and not file.content(heading + 1).strip():
            return [(heading + 2, 0, bullets, 0)], appended, skipped
        return [(heading + 1, 0, [file.make("")] + bullets, 0)], appended, skipped
    position = last + 1
    while position < end and file.content(position).strip() and file.content(position)[0] in " \t" and not BULLET.match(file.content(position)):
        position += 1
    file.terminate_last()
    return [(position, 0, bullets, 0)], appended, skipped


def plan_rules(repo, settings, rules):
    path = os.path.join(repo, rules_file.RULES_FILE)
    raw = read_raw(path)
    result = {"conflicts": [], "appended": [], "skipped": []}
    if raw is None:
        old_text, bom = "", False
        result["appended"] = list(dict.fromkeys(rules))
        new_text = new_rules_text(settings, result["appended"])
        expected = {}
        for section in SETTING_SECTIONS:
            expected[section] = dict(DEFAULTS[section])
            expected[section].update(settings.get(section, {}))
    else:
        read = rules_file.read_rules(repo)
        if read["error"]:
            raise Refusal("malformed_rules_file", "%s: %s" % (rules_file.RULES_FILE, read["error"]["message"]), error=read["error"])
        try:
            file = TextFile(raw)
        except UnicodeDecodeError as error:
            raise Refusal("malformed_rules_file", "cannot read %s: %s" % (rules_file.RULES_FILE, error))
        old_text, bom = "".join(file.lines), file.bom
        current = read["settings"]
        lines = [file.content(i) for i in range(len(file.lines))]
        blocks = rules_file.toml_blocks(lines)
        edits = []
        if blocks:
            block_edits, block = edit_block(file, settings, current, result["conflicts"])
            edits += block_edits
            expected = json.loads(json.dumps(current, default=str))
            for section, table in settings.items():
                expected.setdefault(section, {}).update(table)
        else:
            block = None
            structure = structural_lines(file)
            heading = next((i for i in sorted(structure) if HEADING.match(file.content(i))), None)
            position = 0 if heading is None else heading + 1
            table_lines = new_rules_text(settings, []).split("\n")
            toml_lines = table_lines[table_lines.index("```toml"):table_lines.index("```", 3) + 1]
            added = ([file.make("")] if heading is not None else []) + [file.make(line) for line in toml_lines]
            nxt = position
            if nxt < len(file.lines) and file.content(nxt).strip():
                added.append(file.make(""))
            elif heading is None:
                added.append(file.make(""))
            edits.append((position, 0, added, 1))
            expected = {}
            for section in SETTING_SECTIONS:
                expected[section] = dict(DEFAULTS[section])
                expected[section].update(settings.get(section, {}))
        more, result["appended"], result["skipped"] = prose_edits(file, rules, block)
        file.lines = apply_edits(file.lines, edits + more)
        new_text = file.text()
    reread = read_with_reader(new_text, bom)
    if reread["error"]:
        raise Refusal("write_check_failed", "the new rules file cannot be read back: " + reread["error"]["message"])
    if not same(reread["settings"], json.loads(json.dumps(expected, default=str))):
        raise Refusal("write_check_failed", "the new rules file does not hold the old settings plus the proposal")
    result.update(path=path, exists=raw is not None, text=new_text, bom=bom, old=old_text,
                  warnings=[f"{rule_id} is disabled with no reason line" for rule_id in reread["disabled_without_reason"]])
    return result


# --- allowlist ---------------------------------------------------------------


def header_path(line):
    """The key path of a table header line, or None when the line is not a table header."""
    if not line.lstrip().startswith("[") or line.lstrip().startswith("[["):
        return None
    try:
        data = tomllib.loads(line + "\n")
    except tomllib.TOMLDecodeError:
        return None
    parts = []
    while isinstance(data, dict) and len(data) == 1:
        name, data = next(iter(data.items()))
        parts.append(name)
    return parts


def entry_lines(key, services, timeouts, file):
    lines = [file.make("[%s]" % json.dumps(key)), file.make("services = " + toml_value(services))]
    for service in services:
        if service in timeouts:
            lines.append(file.make(""))
            lines.append(file.make("[%s.timeouts.%s]" % (json.dumps(key), json.dumps(service))))
            lines.extend(file.make("%s = %s" % (name, toml_value(value))) for name, value in timeouts[service].items())
    return lines


def minimal_entry_edits(file, key, services, dropped):
    """The edits that change only the `services` line of the entry and remove the timeouts tables of the
    dropped services, so that every comment stays. None when the entry has another layout."""
    lines = [file.content(i) for i in range(len(file.lines))]
    headers = [(i, header_path(line)) for i, line in enumerate(lines) if header_path(line) is not None]
    ends = {i: (headers[n + 1][0] if n + 1 < len(headers) else len(lines)) for n, (i, _) in enumerate(headers)}
    edits = []
    main = None
    for index, parts in headers:
        if parts[0] != key:
            continue
        if parts == [key]:
            main = index
        elif len(parts) == 3 and parts[1] == "timeouts":
            if parts[2] in dropped:
                last = index
                for probe in range(index + 1, ends[index]):
                    if lines[probe].strip() and not lines[probe].lstrip().startswith("#"):
                        last = probe
                edits.append((index, last - index + 1, [], 0))
        else:
            return None
    if main is None:
        return None
    for index in range(main + 1, ends[main]):
        match = KEY_LINE.match(lines[index])
        if match and match.group(2) == "services":
            last = value_span(lines, index)
            edits.append((index, last - index + 1, [file.make(match.group(1) + "services = " + toml_value(services))], 0))
            return edits
    return None


def plan_allowlist(repo, services, conflicts):
    key = allowlist.repo_key(repo)
    if key is None:
        raise Refusal("not_a_git_repo", "%s is not a git repo, so it has no allowlist key" % repo)
    path = allowlist.allowlist_path()
    raw = read_raw(path)
    try:
        data = tomllib.loads(raw.decode("utf-8-sig")) if raw is not None else {}
    except (ValueError, RecursionError) as error:
        raise Refusal("malformed_allowlist", "%s: %s" % (path, error))
    timeouts = {}
    if key in data:
        try:
            old_services, timeouts = allowlist.validate(data[key])
        except allowlist.Malformed as error:
            raise Refusal("malformed_allowlist", "%s: %s" % (path, error))
        if old_services != services:
            conflicts.append({"target": "allowlist", "section": "entry", "key": "services", "current": old_services, "proposed": services})
        for service in old_services:
            if service not in services and service in timeouts:
                conflicts.append({"target": "allowlist", "section": "timeouts", "key": service, "current": timeouts[service], "proposed": None})
    kept = {service: timeouts[service] for service in services if service in timeouts}
    file = TextFile(raw if raw is not None else b"")
    owned = []
    for index in range(len(file.lines)):
        parts = header_path(file.content(index))
        if parts and parts[0] == key:
            end = index
            probe = index + 1
            while probe < len(file.lines) and header_path(file.content(probe)) is None:
                if file.content(probe).strip() and not file.content(probe).lstrip().startswith("#"):
                    end = probe
                probe += 1
            owned.append((index, end))
    new = entry_lines(key, services, kept, file)
    if len(owned) >= 1 and key in data and not any(c["target"] == "allowlist" for c in conflicts):
        edits = []  # the entry already equals the proposal: the text stays byte for byte
    elif len(owned) >= 1 and key in data and (
        edits := minimal_entry_edits(file, key, services, set(old_services) - set(services))
    ) is not None:
        pass
    elif owned:
        edits = [(owned[0][0], owned[0][1] - owned[0][0] + 1, new, 0)]
        edits += [(start, end - start + 1, [], 0) for start, end in owned[1:]]
    else:
        file.terminate_last()
        lead = [file.make("")] if file.lines and file.content(len(file.lines) - 1).strip() else []
        edits = [(len(file.lines), 0, lead + new, 0)]
    old_text = "".join(file.lines)
    file.lines = apply_edits(file.lines, edits)
    new_text = file.text()
    try:
        reread = tomllib.loads(new_text)
        allowlist.validate(reread.get(key))
    except (ValueError, allowlist.Malformed) as error:
        raise Refusal("write_check_failed", "the new allowlist cannot be read back: %s" % error)
    expected = dict(data)
    expected[key] = {"services": services, **({"timeouts": kept} if kept else {})}
    if not same(reread, json.loads(json.dumps(expected, default=str))) and not same(reread, expected):
        raise Refusal("write_check_failed", "the new allowlist does not equal the old data with this key replaced")
    return {"path": path, "key": key, "exists": raw is not None, "text": new_text, "old": old_text, "bom": file.bom}


# --- plan and write ----------------------------------------------------------


def plan(repo, proposal):
    settings, rules, services = proposal
    repo = os.path.abspath(repo)
    rules_part = plan_rules(repo, settings, rules)
    conflicts = rules_part["conflicts"]
    output = {"ok": True}
    files = [{"path": rules_file.RULES_FILE, "text": rules_part["text"]}]
    output["rules_file"] = {
        "path": rules_part["path"], "exists": rules_part["exists"], "changed": rules_part["text"] != rules_part["old"],
        "diff": unified(rules_file.RULES_FILE, rules_part["old"], rules_part["text"]), "text": rules_part["text"],
    }
    check = None
    warnings = list(rules_part["warnings"])
    if services:
        part = plan_allowlist(repo, services, conflicts)
        output["allowlist"] = {
            "path": part["path"], "key": part["key"], "exists": part["exists"], "changed": part["text"] != part["old"],
            "diff": unified(part["path"], part["old"], part["text"]), "text": part["text"],
        }
        files.append({"path": part["path"], "text": part["text"]})
        check = allowlist.check_services(services)
        warnings += ["the service %s is not in the PG service file" % name for name in check["missing"]]
    output.update(
        conflicts=conflicts, appended_rules=rules_part["appended"], skipped_rules=rules_part["skipped"],
        warnings=warnings, service_check=check,
        digest=hashlib.sha256(json.dumps({"files": files}, sort_keys=True).encode("utf-8")).hexdigest(),
    )
    output["_bom"] = {"rules_file": rules_part["bom"], "allowlist": output.get("allowlist") and part["bom"]}
    return output


def write_temp(target, text, bom, mode):
    folder = os.path.dirname(target)
    handle, temp = tempfile.mkstemp(dir=folder, prefix=".sql-setup-")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write((BOM if bom else b"") + text.encode("utf-8"))
        if os.path.exists(target):
            shutil.copymode(target, temp)
        else:
            os.chmod(temp, mode)
    except OSError:
        try:
            os.remove(temp)
        except OSError:
            pass
        raise
    return temp


def write(repo, proposal, confirm):
    output = plan(repo, parse_proposal(proposal))
    if output["digest"] != confirm:
        return {"ok": False, "reason": "stale_digest", "message": "the files changed after the diff was shown"}
    boms = output["_bom"]
    jobs = [(output["rules_file"], boms["rules_file"], 0o666 & ~current_umask())]
    if "allowlist" in output:
        jobs.append((output["allowlist"], boms["allowlist"], FILE_MODE))
    jobs = [(entry, bom, mode) for entry, bom, mode in jobs if entry["changed"]]
    made_folders, temps, replaced = [], [], []
    try:
        for entry, bom, mode in jobs:
            folder = os.path.dirname(entry["path"])
            missing = []
            probe = folder
            while not os.path.isdir(probe):
                missing.append(probe)
                probe = os.path.dirname(probe)
            if missing:
                is_allowlist = entry is output.get("allowlist")
                for path in reversed(missing):
                    os.mkdir(path, FOLDER_MODE if is_allowlist and path == folder else 0o777)
                    made_folders.append(path)
            temps.append(write_temp(entry["path"], entry["text"], bom, mode))
        for (entry, _, _), temp in zip(jobs, temps):
            old = read_raw(entry["path"])
            replaced.append((entry["path"], old))
            os.replace(temp, entry["path"])
    except OSError as error:
        stayed = []
        for path, old in reversed(replaced):
            try:
                if old is None:
                    os.remove(path)
                else:
                    with open(path, "wb") as handle:
                        handle.write(old)
            except OSError:
                stayed.append(path)
        for temp in temps:
            try:
                os.remove(temp)
            except OSError:
                pass
        for path in reversed(made_folders):
            try:
                os.rmdir(path)
            except OSError:
                pass
        message = "cannot write the files: %s" % error
        if stayed:
            message += " (the file that stayed changed: %s)" % ", ".join(stayed)
        return {"ok": False, "reason": "write_failed", "message": message}
    return {"ok": True, "written": [entry["path"] for entry, _, _ in jobs]}


def current_umask():
    mask = os.umask(0)
    os.umask(mask)
    return mask


# --- command line -----------------------------------------------------------


def load_proposal(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as error:
        raise sql_text.UsageError("cannot read the proposal %s: %s" % (path, error))


def main(argv):
    try:
        if not argv or argv[0] not in ("services", "plan", "write"):
            raise sql_text.UsageError("usage: setup_files.py services <name>... | plan <repo> --proposal <file> | write <repo> --proposal <file> --confirm <digest>")
        action = argv[0]
        if action == "services":
            names = argv[1:]
            if not names or not all(allowlist.SERVICE_NAME.fullmatch(name) for name in names):
                raise sql_text.UsageError("services needs names made of letters, digits, _ . -")
            print(json.dumps({"ok": True, "service_check": allowlist.check_services(names)}))
            return 0
        single = ("--proposal", "--confirm") if action == "write" else ("--proposal",)
        positional, options = sql_text.parse_arguments(argv[1:], 1, single=single)
        repo = positional[0]
        if not os.path.isdir(repo):
            raise sql_text.UsageError("not a folder: " + repo)
        if "--proposal" not in options or (action == "write" and "--confirm" not in options):
            raise sql_text.UsageError("%s needs --proposal%s" % (action, " and --confirm" if action == "write" else ""))
        data = load_proposal(options["--proposal"][0])
        parsed = parse_proposal(data)
    except sql_text.UsageError as error:
        return sql_text.usage_failure(error)
    try:
        output = plan(repo, parsed) if action == "plan" else write(repo, data, options["--confirm"][0])
    except Refusal as refusal:
        output = refusal.output
    output.pop("_bom", None)
    print(json.dumps(output))
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
