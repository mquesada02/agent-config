#!/usr/bin/env python3
"""Offer and apply the install of the Prettier SQL chain for `/sql setup`. Prints one JSON object.

Usage: python3 formatter_install.py offer <repo root> [--tags <t1,t2,...>]
       python3 formatter_install.py apply <repo root> --confirm <digest> [--tags <t1,t2,...>]

`offer` writes nothing. It offers the chain `prettier`, `prettier-plugin-embed` and
`prettier-plugin-sql` (language `postgresql`) only when the repo has a `package.json`, the
template detector chooses `none`, the Prettier `language` is unset or `postgresql`, and the
first Prettier config source is JSON that the script can edit. The package manager is the one
that the lockfile names. `apply` recomputes the offer, refuses unless the digest matches,
writes the config file and runs the install command (with no `NODE_ENV`, and
`--ignore-scripts`). The `[formatter] tool` value is not used here.

Exit code: 0 when `ok` is true, 1 when `ok` is false, 2 for a usage error (one line on stderr,
nothing on stdout). `offer` always has `ok` true.
"""
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import detect_formatter  # noqa: E402
import sql_text  # noqa: E402

PACKAGES = ("prettier", "prettier-plugin-embed", "prettier-plugin-sql")
PLUGINS = ("prettier-plugin-embed", "prettier-plugin-sql")
NEW_CONFIG = ".prettierrc.json"
PLACEHOLDER = "<chosen by the package manager>"
LOCKFILES = {
    "package-lock.json": "npm",
    "npm-shrinkwrap.json": "npm",
    "yarn.lock": "yarn",
    "pnpm-lock.yaml": "pnpm",
    "bun.lock": "bun",
    "bun.lockb": "bun",
}
COMMANDS = {
    "npm": ["npm", "install", "--save-dev", "--include=dev", "--ignore-scripts"],
    "yarn": ["yarn", "add", "--dev", "--ignore-scripts"],
    "pnpm": ["pnpm", "add", "--save-dev", "--ignore-scripts"],
    "bun": ["bun", "add", "--dev", "--ignore-scripts"],
}
INDENT = re.compile(r"^([ \t]+)\"", re.M)
STDERR_LINES = 10


def no_offer(reason):
    return {"ok": True, "offer": False, "reason": reason}


def read_json(path):
    with open(path, encoding="utf-8", newline="") as handle:
        text = handle.read()
    return text, json.loads(text)


def dump(data, old_text=None):
    """JSON text with the indent of the old text (2 spaces for a new file) and a final line end."""
    indent = 2
    if old_text:
        found = INDENT.search(old_text)
        if found:
            indent = found.group(1)
    text = json.dumps(data, indent=indent, ensure_ascii=False) + "\n"
    return text.replace("\n", "\r\n") if old_text and "\r\n" in old_text else text


def unified(name, old, new):
    return "".join(
        difflib.unified_diff(old.splitlines(True), new.splitlines(True), "a/" + name, "b/" + name)
    )


def first_source(root, package):
    """(file, config dict or None) of the first Prettier source, or (reason,) when it is not editable.

    With no source at all the file is the new `.prettierrc.json` and the config is None."""
    for name in detect_formatter.PRETTIER_FILES:
        if name == "package.json":
            if "prettier" not in package:
                continue
            if isinstance(package["prettier"], dict):
                return name, package["prettier"]
            return ("the Prettier config of package.json is not an object",)
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        if name in (".prettierrc", ".prettierrc.json"):
            try:
                _, data = read_json(path)
            except (OSError, ValueError):
                return ("the Prettier config %s is not JSON" % name,)
            if isinstance(data, dict):
                return name, data
            return ("the Prettier config %s is not a JSON object" % name,)
        return ("the Prettier config %s is not JSON" % name,)
    return NEW_CONFIG, None


def new_config(config, tags):
    config = dict(config or {})
    plugins = config.get("plugins")
    if "plugins" in config and not (isinstance(plugins, list) and all(isinstance(p, str) for p in plugins)):
        return None
    plugins = list(plugins or [])
    config["plugins"] = plugins + [name for name in PLUGINS if name not in plugins]
    config.setdefault("language", "postgresql")
    option = config.get("embeddedSqlTags")
    current = option if isinstance(option, list) and all(isinstance(t, str) for t in option) else list(
        detect_formatter.DEFAULT_EMBEDDED_TAGS
    )
    missing = [tag for tag in tags or [] if tag not in current]
    if missing:
        config["embeddedSqlTags"] = current + missing
    return config


def lockfile_manager(root):
    managers = {manager for name, manager in LOCKFILES.items() if os.path.exists(os.path.join(root, name))}
    if len(managers) == 1:
        return managers.pop(), None
    if not managers:
        return None, "no lockfile names a package manager"
    return None, "lockfiles of more than one package manager: " + ", ".join(sorted(managers))


def offer(root, tags):
    package_path = os.path.join(root, "package.json")
    if not os.path.isfile(package_path):
        return no_offer("the repo has no package.json")
    try:
        package_text, package = read_json(package_path)
    except (OSError, ValueError) as error:
        return no_offer("package.json cannot be read: %s" % error)
    if not isinstance(package, dict):
        return no_offer("package.json is not a JSON object")
    detected = detect_formatter.detect(root, "template", tags, None)
    if detected["chosen"] != "none":
        return no_offer("the repo already has a safe template tool: " + detected["chosen"])
    source = first_source(root, package)
    if len(source) == 1:
        return no_offer(source[0] + ", so setup does not edit it")
    config_file, current = source
    language = (current or {}).get("language")
    if language is not None and language != "postgresql":
        return no_offer("the Prettier language is %s, not postgresql; setup does not overwrite it" % json.dumps(language))
    config = new_config(current, tags)
    if config is None:
        return no_offer("the Prettier plugins option is not a list of names")

    present = {name for key in ("dependencies", "devDependencies") if isinstance(package.get(key), dict) for name in package[key]}
    packages = [name for name in PACKAGES if name not in present]
    manager = command = diff = None
    if packages:
        manager, reason = lockfile_manager(root)
        if manager is None:
            return no_offer(reason)
        command = COMMANDS[manager] + packages
        diff = "--- a/package.json\n+++ b/package.json\n" + "".join(
            '+    "%s": "%s",\n' % (name, PLACEHOLDER) for name in packages
        )

    if config_file == "package.json":
        old_text = package_text
        new_package = dict(package)
        new_package["prettier"] = config
        new_text = dump(new_package, package_text)
    else:
        old_text = read_json(os.path.join(root, config_file))[0] if current is not None else ""
        new_text = dump(config, old_text)
    digest = hashlib.sha256(
        json.dumps({"config_file": config_file, "config_text": new_text, "command": command}, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "ok": True,
        "offer": True,
        "package_manager": manager,
        "command": command,
        "packages": packages,
        "package_json_diff": diff,
        "config": {
            "file": config_file,
            "action": "edit" if current is not None else "create",
            "diff": unified(config_file, old_text, new_text),
        },
        "digest": digest,
        "_new_text": new_text,
    }


def read_bytes(path):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except FileNotFoundError:
        return None


def put_back(path, old):
    if old is None:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    else:
        with open(path, "wb") as handle:
            handle.write(old)


def apply(root, digest, tags):
    plan = offer(root, tags)
    if not plan["offer"]:
        return {"ok": False, "reason": "no_offer", "message": plan["reason"]}
    if plan["digest"] != digest:
        return {"ok": False, "reason": "stale_digest", "message": "the offer changed after the digest was shown"}
    path = os.path.join(root, plan["config"]["file"])
    old = read_bytes(path)
    try:
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(plan["_new_text"])
    except OSError as error:
        try:
            put_back(path, old)
        except OSError:
            pass  # the open failed before any change, so the file is as it was
        return {"ok": False, "reason": "write_failed", "message": "cannot write %s: %s" % (plan["config"]["file"], error)}
    if plan["command"] is not None:
        env = {key: value for key, value in os.environ.items() if key != "NODE_ENV"}
        try:
            done = subprocess.run(
                plan["command"], cwd=root, env=env, capture_output=True, text=True, encoding="utf-8",
                stdin=subprocess.DEVNULL,
            )
            failed, stderr = done.returncode != 0, done.stderr
        except OSError as error:
            failed, stderr = True, str(error)
        if failed:
            put_back(path, old)
            tail = "\n".join(stderr.strip().splitlines()[-STDERR_LINES:])
            return {"ok": False, "reason": "install_failed", "message": tail or "the install command failed"}
    detected = detect_formatter.detect(root, "template", tags, None)
    if detected["chosen"] == "none":
        return {"ok": False, "reason": detected["reason"] or "the detector still chooses none", "chosen": "none"}
    return {"ok": True, "chosen": detected["chosen"]}


def main(argv):
    try:
        if not argv or argv[0] not in ("offer", "apply"):
            raise sql_text.UsageError("usage: formatter_install.py offer|apply <repo root> [--confirm <digest>] [--tags <t1,t2,...>]")
        action = argv[0]
        single = ("--tags", "--confirm") if action == "apply" else ("--tags",)
        positional, options = sql_text.parse_arguments(argv[1:], 1, single=single)
        root = positional[0]
        if not os.path.isdir(root):
            raise sql_text.UsageError("not a folder: " + root)
        tags = None
        if "--tags" in options:
            tags = [tag for tag in options["--tags"][0].split(",") if tag]
            if not tags:
                raise sql_text.UsageError("--tags needs at least one tag")
        if action == "apply" and "--confirm" not in options:
            raise sql_text.UsageError("apply needs --confirm <digest>")
    except sql_text.UsageError as error:
        return sql_text.usage_failure(error)
    root = os.path.abspath(root)
    if action == "offer":
        output = offer(root, tags)
    else:
        output = apply(root, options["--confirm"][0], tags)
    output.pop("_new_text", None)
    print(json.dumps(output, indent=2))
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
