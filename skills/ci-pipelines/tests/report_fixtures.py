"""Small report builder shared by the grader tests (a helper module, not a test file)."""
import os
import subprocess
import sys
import tempfile

from skill_files import SKILL

SCRIPTS = os.path.join(SKILL, "scripts")

FENCE = "`" * 3
HEADER = "| # | Rule | Where | Problem | Fix |"
SEPARATOR = "|---|---|---|---|---|"
APPROVE_FINDINGS = "Reply with the findings to fix: `all`, `none`, a list such as `1,3,5`, or a range such as `1-12`."
APPROVE_ZERO = "There is nothing to approve."
TOOLS_OK = [
    "- actionlint: on PATH (1.7.0)",
    "- zizmor: not on PATH. Install it with `uvx zizmor` or `brew install zizmor`.",
]
HEADINGS = {"critical": "## Critical", "required": "## Required", "suggestion": "## Suggestions"}


def row(rule, where="ci.yml:3", flag=False):
    return (rule, where, "A problem.", "A fix.", flag)


def table(rows, start):
    lines = [HEADER, SEPARATOR]
    for offset, (rule, where, problem, fix, flag) in enumerate(rows):
        cell = f"{rule} ⚑" if flag else rule
        lines.append(f"| {start + offset} | {cell} | {where} | {problem} | {fix} |")
    return lines


def make_report(critical=(), required=(), suggestion=(), summary=None, tools=None,
                approve=None, flag_section=None, graph=True, intake=True, checks=True):
    """Build a valid report. Keyword arguments switch one point of the contract off or change it."""
    groups = {"critical": list(critical), "required": list(required), "suggestion": list(suggestion)}
    total = sum(len(rows) for rows in groups.values())
    any_flag = any(r[4] for rows in groups.values() for r in rows)
    lines = ["# ci-pipelines review: all workflows", ""]
    lines.append(summary or (
        f"**Result: {len(groups['critical'])} critical, {len(groups['required'])} required, "
        f"{len(groups['suggestion'])} suggestions.**"))
    lines.append("")
    if intake:
        lines += ["Intake: pnpm, single package, private repo (2 vCPU). Defaults: none.", ""]
    if checks:
        lines += ["Required checks (branch protection + rulesets, read-only): `CI passed`.", ""]
    lines += ["Tools:"] + (TOOLS_OK if tools is None else tools) + [""]
    number = 1
    for severity in ("critical", "required", "suggestion"):
        rows = groups[severity]
        if rows:
            lines += [HEADINGS[severity], ""] + table(rows, number) + [""]
            number += len(rows)
    if flag_section if flag_section is not None else any_flag:
        lines += ["## ⚑ Branch protection change needed", "",
                  "1. Remove the old required checks.", "2. Add the required check `CI passed`.", ""]
    if graph:
        lines += ["## Job graph after the fixes", "", FENCE, "lint ─┐", "test ─┴─ ci-passed", FENCE, ""]
    lines += ["## Approve", "", approve or (APPROVE_FINDINGS if total else APPROVE_ZERO), ""]
    return "\n".join(lines)


def run_script(name, args, stdin=None):
    """Run a script of the skill through its command line. Returns (exit code, stdout, stderr)."""
    proc = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, name)] + args,
                          input=stdin, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


class TempReport:
    """A report text written in a temporary folder."""

    def __init__(self, text, name="report.md"):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, name)
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def cleanup(self):
        self.dir.cleanup()
