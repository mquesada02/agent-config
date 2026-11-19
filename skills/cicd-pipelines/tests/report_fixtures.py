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


LOCK_NOTE = ("🔒 = a protection write. The row uses the 2-step flow: after the approval, the skill shows the "
             "current and the proposed JSON and asks for a yes before each write.")


def row(rule, where="ci.yml:3", flag=False, lock=False):
    return (rule, where, "A problem.", "A fix.", flag, lock)


def table(rows, start):
    lines = [HEADER, SEPARATOR]
    for offset, (rule, where, problem, fix, flag, lock) in enumerate(rows):
        cell = " ".join([rule] + (["⚑"] if flag else []) + (["🔒"] if lock else []))
        lines.append(f"| {start + offset} | {cell} | {where} | {problem} | {fix} |")
    return lines


def make_report(critical=(), required=(), suggestion=(), summary=None, tools=None,
                approve=None, flag_section=None, graph=True, intake=True, checks=True, lock_note=None):
    """Build a valid report. Keyword arguments switch one point of the contract off or change it."""
    groups = {"critical": list(critical), "required": list(required), "suggestion": list(suggestion)}
    total = sum(len(rows) for rows in groups.values())
    any_flag = any(r[4] for rows in groups.values() for r in rows)
    any_lock = any(r[5] for rows in groups.values() for r in rows)
    lines = ["# cicd-pipelines review: all workflows", ""]
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
    if lock_note if lock_note is not None else any_lock:
        lines += [LOCK_NOTE, ""]
    if flag_section if flag_section is not None else any_flag:
        lines += ["## ⚑ Admin steps", "",
                  "1. Remove the old required checks.", "2. Add the required check `CI passed`.", ""]
    if graph:
        lines += ["## Job graph after the fixes", "", FENCE, "lint ─┐", "test ─┴─ ci-passed", FENCE, ""]
    lines += ["## Approve", "", approve or (APPROVE_FINDINGS if total else APPROVE_ZERO), ""]
    return "\n".join(lines)


GENERAL_HEADER = "| Rule | Where | Problem | Fix |"
GENERAL_SEPARATOR = "|---|---|---|---|"
GENERAL_LAST = "The skill edits no file in general mode."


def general_row(rule, where="repo"):
    return (rule, where, "A problem.", "A fix.")


def make_general_report(critical=(), required=(), suggestion=(), normal=None, line1=None, title=None,
                        summary=None, intake=None, header=None, last=None, approve=False):
    """Build a valid general review reply. Keyword arguments switch one point of the form off or change it.

    `normal` is a normal report (text) that follows the general part. For line1, title, summary, intake,
    header and last, None gives the valid line and "" leaves the line out."""
    groups = {"critical": list(critical), "required": list(required), "suggestion": list(suggestion)}
    first = ("General guidance: this repo uses Rust, which the skill does not cover. "
             "The advice comes from the cited sources, with no rule check.") if line1 is None else line1
    lines = [first, ""] if first else []
    head = "# cicd-pipelines general review: all CI files" if title is None else title
    lines += [head, ""] if head else []
    count = summary if summary is not None else (
        f"**Result: {len(groups['critical'])} critical, {len(groups['required'])} required, "
        f"{len(groups['suggestion'])} suggestions.**")
    lines += [count, ""] if count else []
    info = "Intake: Rust, GitHub Actions. Defaults: none." if intake is None else intake
    lines += [info, ""] if info else []
    for severity in ("critical", "required", "suggestion"):
        rows = groups[severity]
        if rows:
            lines += [HEADINGS[severity], "", header or GENERAL_HEADER, GENERAL_SEPARATOR]
            lines += [f"| {' | '.join(r)} |" for r in rows] + [""]
    if approve:
        lines += ["## Approve", "", APPROVE_FINDINGS, ""]
    lines += [GENERAL_LAST if last is None else last, ""] if last != "" else []
    if normal is not None:
        lines += [normal]
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
