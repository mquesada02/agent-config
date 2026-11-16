"""Readers for the skill's Markdown files (a helper module, not a test file)."""
import glob
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
RULES = os.path.join(SKILL, "rules")
EVALS = os.path.join(SKILL, "evals")
PREFIXES = {
    "naming": "NAME", "job-graph": "GRAPH", "cost": "COST",
    "security": "SEC", "monorepo": "MONO", "maintainability": "MAINT",
}
LEVELS = ("critical", "required", "suggestion")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def frontmatter(path):
    """The key/value pairs of the `---` block at the top of a file. Quotes are removed, lists stay text."""
    match = re.match(r"^---\n(.*?)\n---\n", read(path), re.S)
    assert match, f"{path} has no frontmatter"
    values = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            quote = value[0]
            value = value[1:-1].replace(quote * 2, quote) if quote == "'" else value[1:-1]
        values[key.strip()] = value
    return values


def rule_files():
    """Map of rule file name (without .md) to its path."""
    return {os.path.basename(p)[:-3]: p for p in sorted(glob.glob(os.path.join(RULES, "*.md")))}


def rule_entries(path):
    """The entries of a rule file: a list of (id, {field: text}). An entry is a `### ID` heading and its bullets."""
    entries = []
    for block in re.split(r"^### ", read(path), flags=re.M)[1:]:
        heading, _, body = block.partition("\n")
        fields = {}
        for match in re.finditer(r"^- \*\*(\w+):\*\* (.*(?:\n(?!- \*\*|### ).*)*)", body, re.M):
            fields[match.group(1)] = match.group(2).strip()
        entries.append((heading.strip(), fields))
    return entries


def all_rules():
    """List of (rule file name, id, fields) for every rule entry."""
    return [(name, rule_id, fields)
            for name, path in rule_files().items()
            for rule_id, fields in rule_entries(path)]


def level(fields):
    """The level of a rule: the leading word of its Severity bullet."""
    return fields["Severity"].split()[0].strip(",;:()").lower()
