#!/usr/bin/env python3
"""Pick the safe formatter tool for a source form and print one JSON object.

Usage: python3 detect_formatter.py <repo root> --form template|sql
           [--tags <t1,t2,...>] [--tool <name>]

`--form template` is a postgres.js template, `--form sql` a `.sql` file.
`--tags` is the tag list (for the Prettier `embeddedSqlTags` check) and
`--tool` is the `[formatter] tool` value of the rules file. The detector reads
only files at the repo root and runs no formatter (it runs `node` only to
resolve a Prettier config that is not plain data).

Exit code: 0 when it ran, 2 for a usage error (one line on stderr, nothing on
stdout).
"""
import json
import os
import subprocess
import sys
import tomllib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sql_text import UsageError, parse_arguments, usage_failure  # noqa: E402

TEMPLATE_TOOL = "prettier-plugin-embed"
SQL_TOOLS = ("sqlfluff", "pgFormatter", "prettier-plugin-sql", "sql-formatter")
CHAIN = ("prettier-plugin-embed", "prettier-plugin-sql")
DEFAULT_EMBEDDED_TAGS = ["sql"]
NODE_TIMEOUT = 30

# The order of the Prettier docs: the first file that exists decides.
PRETTIER_FILES = (
    "package.json", "package.yaml", ".prettierrc", ".prettierrc.json", ".prettierrc.yaml",
    ".prettierrc.yml", ".prettierrc.json5", ".prettierrc.js", ".prettierrc.ts", ".prettierrc.mjs",
    ".prettierrc.cjs", ".prettierrc.mts", ".prettierrc.cts", ".prettierrc.toml",
    "prettier.config.js", "prettier.config.ts", "prettier.config.mjs", "prettier.config.cjs",
    "prettier.config.mts", "prettier.config.cts",
)

NODE_SCRIPT = """
let prettier;
try { prettier = require(require.resolve("prettier", { paths: [process.cwd()] })); }
catch (error) { console.error("no prettier in the repo: " + error.message); process.exit(3); }
prettier.resolveConfig(process.argv[1]).then(
  (config) => console.log(JSON.stringify(config === null ? {} : config)),
  (error) => { console.error(String(error)); process.exit(4); }
);
"""


class Repo:
    def __init__(self, root, form):
        self.root = root
        self.form = form
        self.notes = []
        self._package = None
        self._prettier = None

    def path(self, name):
        return os.path.join(self.root, name)

    def note(self, text):
        if text not in self.notes:
            self.notes.append(text)

    def isfile(self, name):
        return os.path.isfile(self.path(name))

    def package(self):
        """The parsed package.json (a dict), or {} when it is missing or unreadable."""
        if self._package is None:
            self._package = {}
            if self.isfile("package.json"):
                try:
                    with open(self.path("package.json"), encoding="utf-8") as handle:
                        data = json.load(handle)
                except (OSError, ValueError) as error:
                    self.note("package.json cannot be read: %s" % error)
                else:
                    if isinstance(data, dict):
                        self._package = data
                    else:
                        self.note("package.json is not a JSON object")
        return self._package

    def dependencies(self):
        names = set()
        for key in ("dependencies", "devDependencies"):
            section = self.package().get(key)
            if isinstance(section, dict):
                names.update(section)
        return names

    def prettier_config(self):
        """The Prettier config as a dict ({} when there is none or it cannot be read)."""
        if self._prettier is None:
            self._prettier = self._read_prettier()
        return self._prettier

    def _read_prettier(self):
        for name in PRETTIER_FILES:
            if name == "package.json":
                if "prettier" not in self.package():
                    continue
                value = self.package()["prettier"]
                return value if isinstance(value, dict) else self._resolve_with_node()
            if not self.isfile(name):
                continue
            if name in (".prettierrc", ".prettierrc.json"):
                data = self._json_object(name)
                return data if data is not None else self._resolve_with_node()
            if name == ".prettierrc.toml":
                try:
                    with open(self.path(name), "rb") as handle:
                        return tomllib.load(handle)
                except (OSError, tomllib.TOMLDecodeError) as error:
                    self.note("Prettier config %s cannot be read: %s" % (name, error))
                    return {}
            return self._resolve_with_node()
        return {}

    def _json_object(self, name):
        try:
            with open(self.path(name), encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _resolve_with_node(self):
        dummy = os.path.join(self.root, "index.ts" if self.form == "template" else "query.sql")
        try:
            result = subprocess.run(
                ["node", "-e", NODE_SCRIPT, dummy], cwd=self.root, capture_output=True,
                text=True, encoding="utf-8", stdin=subprocess.DEVNULL, timeout=NODE_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            self.note("Prettier config cannot be resolved: %s" % error)
            return {}
        if result.returncode != 0:
            lines = result.stderr.strip().splitlines()
            self.note("Prettier config cannot be resolved: %s" % (lines[0] if lines else "node failed"))
            return {}
        try:
            data = json.loads(result.stdout)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            self.note("Prettier config cannot be resolved: the result is not a JSON object")
            return {}
        return data

    def plugins(self):
        value = self.prettier_config().get("plugins")
        return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def find_template_tool(repo):
    """(found list, reason) for form template."""
    dependencies = repo.dependencies()
    plugins = repo.plugins()
    language = repo.prettier_config().get("language")
    missing = []
    signals = []
    for plugin in CHAIN:
        if plugin in dependencies:
            signals.append("package.json: " + plugin)
        else:
            missing.append("%s is not in package.json" % plugin)
    for plugin in CHAIN:
        if plugin in plugins:
            signals.append("Prettier config plugins: " + plugin)
        else:
            missing.append("%s is not in the Prettier config plugins" % plugin)
    if language == "postgresql":
        signals.append('Prettier config language: "postgresql"')
    elif language is None:
        missing.append("no language option in the Prettier config")
    else:
        missing.append('language is %s, not "postgresql"' % json.dumps(language))
    if missing:
        return [], "no template tool: " + "; ".join(missing)
    return [{"tool": TEMPLATE_TOOL, "signals": signals}], None


def sqlfluff_signal(repo):
    if repo.isfile(".sqlfluff"):
        return [".sqlfluff"]
    if repo.isfile("pyproject.toml"):
        try:
            with open(repo.path("pyproject.toml"), "rb") as handle:
                data = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError) as error:
            repo.note("pyproject.toml cannot be read: %s" % error)
            return []
        tool = data.get("tool")
        if isinstance(tool, dict) and isinstance(tool.get("sqlfluff"), dict):
            return ["pyproject.toml: [tool.sqlfluff]"]
    return []


def find_sql_tools(repo):
    found = []
    signals = sqlfluff_signal(repo)
    if signals:
        found.append({"tool": "sqlfluff", "signals": signals})
    if repo.isfile(".pg_format"):
        found.append({"tool": "pgFormatter", "signals": [".pg_format"]})
    if "prettier-plugin-sql" in repo.plugins():
        found.append({"tool": "prettier-plugin-sql", "signals": ["Prettier config plugins: prettier-plugin-sql"]})
    signals = []
    if repo.isfile(".sql-formatter.json"):
        signals.append(".sql-formatter.json")
    if "sql-formatter" in repo.dependencies():
        signals.append("package.json: sql-formatter")
    if signals:
        found.append({"tool": "sql-formatter", "signals": signals})
    return found


def choose(form, found, tool_value):
    """(chosen, reason, override) from the found tools and the rules file value."""
    fits = (TEMPLATE_TOOL,) if form == "template" else SQL_TOOLS
    override = None
    if tool_value is not None:
        if tool_value in fits:
            if any(item["tool"] == tool_value for item in found):
                return (
                    tool_value,
                    "the rules file names it",
                    {"tool": tool_value, "used": True,
                     "reason": "the rules file names a safe tool that is installed and fits"},
                )
            why = "has no signal in the repo"
        elif tool_value in (TEMPLATE_TOOL,) + SQL_TOOLS:
            why = "does not fit the form"
        else:
            why = "not a safe tool name"
        override = {"tool": tool_value, "used": False, "reason": why}
    if found:
        return found[0]["tool"], "found by " + ", ".join(found[0]["signals"]), override
    return "none", None, override


def detect(root, form, tags, tool_value):
    repo = Repo(root, form)
    none_reason = None
    if form == "template":
        found, none_reason = find_template_tool(repo)
    else:
        found = find_sql_tools(repo)
        none_reason = "no safe formatter tool has a signal in the repo"
    chosen, reason, override = choose(form, found, tool_value)
    if chosen == "none":
        reason = none_reason
    embedded = None
    uncovered = []
    if form == "template" and found:
        option = repo.prettier_config().get("embeddedSqlTags")
        if isinstance(option, list) and all(isinstance(item, str) for item in option):
            embedded = option
        else:
            embedded = list(DEFAULT_EMBEDDED_TAGS)
        uncovered = [tag for tag in (tags or []) if tag not in embedded]
    return {
        "form": form,
        "found": found,
        "chosen": chosen,
        "reason": reason,
        "override": override,
        "embedded_sql_tags": embedded,
        "uncovered_tags": uncovered,
        "notes": repo.notes,
    }


def main(argv):
    try:
        positional, options = parse_arguments(argv[1:], 1, single=("--form", "--tags", "--tool"))
        root = positional[0]
        if not os.path.isdir(root):
            raise UsageError("not a folder: " + root)
        form = options.get("--form", [None])[0]
        if form not in ("template", "sql"):
            raise UsageError("--form is required: template or sql")
        tags = None
        if "--tags" in options:
            tags = [tag for tag in options["--tags"][0].split(",") if tag]
            if not tags:
                raise UsageError("--tags needs at least one tag")
        tool_value = options.get("--tool", [None])[0]
    except UsageError as error:
        return usage_failure(error)
    print(json.dumps(detect(root, form, tags, tool_value), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
