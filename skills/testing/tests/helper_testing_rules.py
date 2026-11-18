"""Helpers for the testing skill tests (a helper module, not a test file)."""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SCRIPT = os.path.join(SKILL, "scripts", "intake.py")
REPO = os.path.dirname(os.path.dirname(SKILL))
FENCE = "```"
SECTIONS = ["languages", "commands", "groups", "runner", "layout", "libraries"]
SEEDS = {
    "ASSERT-01": "critical", "ASSERT-02": "critical", "ASSERT-03": "critical",
    "RUN-01": "critical", "RS-01": "critical",
    "RUN-02": "required", "RUN-03": "required", "RUN-04": "required", "PAR-01": "required",
    "PAR-02": "required", "GRP-01": "required", "TS-01": "required",
    "RUN-05": "suggestion", "DBL-01": "suggestion",
}

PARTS = {
    "languages": '[[languages]]\nname = "rust"\nroot = "."\n\n[[languages]]\nname = "typescript"\nroot = "web"\n',
    "commands.rust": '[commands.rust]\ntest = "cargo nextest run"\n',
    "commands.typescript": '[commands.typescript]\ntest = "npx vitest run"\n',
    "groups": (
        '[[groups]]\nname = "unit"\nlanguage = "rust"\nsize = "small"\ncommand = "cargo nextest run --lib"\n\n'
        '[[groups]]\nname = "web"\nlanguage = "typescript"\nsize = "small"\ncommand = "npx vitest run"\n'
    ),
    "runner.rust": '[runner.rust]\nname = "nextest"\n',
    "runner.typescript": '[runner.typescript]\nname = "vitest"\n',
    "layout.rust": '[layout.rust]\ntest_paths = ["tests"]\n',
    "layout.typescript": '[layout.typescript]\ntest_paths = ["web/test"]\n',
    "libraries.rust": '[libraries.rust]\nproperty = "proptest"\n',
    "libraries.typescript": '[libraries.typescript]\nfakes = "vitest"\n',
    "limits": "[limits]\nsmall_ms = 100\n",
    "rules": "[rules]\ndisabled = []\n",
}


def block(drop=(), top="", extra="", replace=None):
    """A complete TOML block. `drop` lists the part names to leave out, `top` goes before the
    first table, `extra` after the last part, and `replace` maps a part name to its new text."""
    parts = dict(PARTS)
    parts.update(replace or {})
    body = "\n".join(text for name, text in parts.items() if name not in drop)
    return top + body + extra


FULL_BLOCK = block()


def doc(block, prose_before="", prose_after=""):
    return f"# Test rules\n\n{prose_before}{FENCE}toml\n{block}{FENCE}\n\n{prose_after}"


class Repo:
    """A temporary repo root. Call close() or use addCleanup(repo.close)."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def close(self):
        self._tmp.cleanup()

    def write(self, text, raw=False):
        folder = os.path.join(self.root, "docs", "agents")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "testing.md")
        if not raw:
            text = text.encode("utf-8")
        with open(path, "wb") as handle:
            handle.write(text)
        return path


    def put(self, path, content=""):
        """Write any file (text or bytes) at a repo-relative path; the folders are made."""
        full = os.path.join(self.root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as handle:
            handle.write(content if isinstance(content, bytes) else content.encode("utf-8"))
        return full


def run_script(*args):
    return subprocess.run(
        [sys.executable, "-I", SCRIPT, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def run_json(repo_root, *extra):
    """(rules, detected, exit code) of the script run on a repo root."""
    done = run_script(repo_root, *extra)
    data = json.loads(done.stdout)
    return data["rules"], data["detected"], done.returncode
