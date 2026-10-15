# Shared fixtures for the audit tests: a temporary git repo with a local bare origin, a temporary TMPDIR and a private HOME.
# Tests run the `audit` executable as a subprocess with `python3 -I`; no test imports it.
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIT = os.path.join(HERE, "audit")
FOLDER_NAME = "claude-workflow-audit"
PASSING_LLM = {name: {"result": "pass", "evidence": f"{name} ok"} for name in ("L1", "L2", "L3", "L4", "L5", "L6")}


VERSION = "2.1.301"
DECLARES_NONE = "# Project\n\n### Test command\n\n```\nnone\n```\n"


def stamp(seconds):
    """An ISO time `seconds` after a fixed start, as Claude Code writes it."""
    return "2026-10-15T12:%02d:%02d.000Z" % (seconds // 60, seconds % 60)


def call_row(name, tool_input, call_id, seconds, cwd=None, version=VERSION, **extra):
    row = {"type": "assistant", "timestamp": stamp(seconds), "version": version, "sessionId": "x",
           "message": {"model": "claude-opus-5-5", "content": [{"type": "tool_use", "id": call_id, "name": name, "input": tool_input}]}}
    if cwd is not None:
        row["cwd"] = cwd
    row.update(extra)
    return row


def edit_row(path, call_id, seconds, tool="Edit", **extra):
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    return call_row(tool, {key: path}, call_id, seconds, **extra)


def bash_row(command, call_id, seconds, background=False, **extra):
    tool_input = {"command": command}
    if background:
        tool_input["run_in_background"] = True
    return call_row("Bash", tool_input, call_id, seconds, **extra)


def result_row(call_id, seconds, is_error=None, version=VERSION):
    block = {"type": "tool_result", "tool_use_id": call_id, "content": "output"}
    if is_error is not None:
        block["is_error"] = is_error
    return {"type": "user", "timestamp": stamp(seconds), "version": version, "message": {"role": "user", "content": [block]}}


def notification_text(call_id, status="completed", code=0):
    summary = f'Background command "run" completed (exit code {code})' if status == "completed" else f'Background command "run" failed with exit code {code}'
    return (f"<task-notification>\n<task-id>b1</task-id>\n<tool-use-id>{call_id}</tool-use-id>\n"
            f"<status>{status}</status>\n<summary>{summary}</summary>\n</task-notification>")


def notification_user_row(call_id, seconds=0, **kwargs):
    return {"type": "user", "timestamp": stamp(seconds), "version": VERSION,
            "message": {"role": "user", "content": notification_text(call_id, **kwargs)}}


def notification_attachment_row(call_id, **kwargs):
    return {"type": "attachment", "version": VERSION, "attachment": {"type": "queued_command", "prompt": notification_text(call_id, **kwargs)}}


class AuditCase(unittest.TestCase):
    default_session = True  # register one synthetic session that edited a file in the worktree

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.tmp = os.path.join(self.root, "tmp")
        self.home = os.path.join(self.root, "home")
        self.origin = os.path.join(self.root, "origin.git")
        self.main = os.path.join(self.root, "main-checkout")
        self.repo = os.path.join(self.root, "repo")
        for folder in (self.tmp, self.home, self.main, self.repo):
            os.mkdir(folder)
        self.runtime = os.path.join(self.tmp, FOLDER_NAME)
        self.env = {
            "PATH": os.environ["PATH"], "HOME": self.home, "TMPDIR": self.tmp,
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
        }
        self.git("init", "--bare", "-b", "main", self.origin, cwd=self.root)
        # The audited worktree is a linked worktree of a separate main checkout, which stays on a detached HEAD.
        self.git("init", "-b", "main", cwd=self.main)
        self.git("remote", "add", "origin", self.origin, cwd=self.main)
        self.commit("chore: initial commit", cwd=self.main)
        with open(os.path.join(self.main, "CLAUDE.md"), "w") as handle:
            handle.write(DECLARES_NONE)
        self.git("add", "CLAUDE.md", cwd=self.main)
        self.git("commit", "-m", "docs: declare no tests", cwd=self.main)
        self.git("push", "-u", "origin", "main", cwd=self.main)
        self.git("checkout", "--detach", cwd=self.main)
        self.git("worktree", "add", self.repo, "main", cwd=self.main)
        self.llm_path = os.path.join(self.root, "llm.json")
        self.write_llm(PASSING_LLM)
        if self.default_session:
            self.register_session("default-session", [edit_row(os.path.join(self.repo, "edited.txt"), "t1", 1)])

    def register_session(self, session_id, rows, subagents=None, started_at="2026-10-15T12:00:00+00:00"):
        """Write a transcript (and subagent transcripts, a dict of name -> rows) and register it. Returns its path."""
        folder = os.path.join(self.root, "projects")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{session_id}.jsonl")
        self.write_rows(path, rows)
        for name, sub_rows in (subagents or {}).items():
            sub_folder = os.path.join(folder, session_id, "subagents")
            os.makedirs(sub_folder, exist_ok=True)
            self.write_rows(os.path.join(sub_folder, f"agent-{name}.jsonl"), sub_rows)
        self.register_path(session_id, path, started_at)
        return path

    def register_path(self, session_id, path, started_at="2026-10-15T12:00:00+00:00"):
        os.makedirs(self.runtime, exist_ok=True)
        os.chmod(self.runtime, 0o700)
        with open(os.path.join(self.runtime, "sessions.jsonl"), "a") as handle:
            handle.write(json.dumps({"session_id": session_id, "transcript_path": path, "started_at": started_at}) + "\n")

    @staticmethod
    def write_rows(path, rows):
        with open(path, "w") as handle:
            for row in rows:
                handle.write((row if isinstance(row, str) else json.dumps(row)) + "\n")

    def git(self, *args, cwd=None, check=True):
        result = subprocess.run(["git", *args], cwd=cwd or self.repo, env=self.env, capture_output=True, text=True, timeout=30)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def commit(self, message, name=None, cwd=None):
        cwd = cwd or self.repo
        name = name or f"file{len(os.listdir(cwd))}.txt"
        with open(os.path.join(cwd, name), "w") as handle:
            handle.write(message)
        self.git("add", name, cwd=cwd)
        self.git("commit", "-m", message, cwd=cwd)
        return self.git("rev-parse", "HEAD", cwd=cwd)

    def start_branch(self, name, *messages):
        """Branch off main with one commit per message, pushed with tracking. Returns the pushed tip."""
        self.git("checkout", "-b", name)
        for message in messages:
            self.commit(message)
        self.git("push", "-u", "origin", name)
        return self.git("rev-parse", "HEAD")

    def write_llm(self, content):
        with open(self.llm_path, "w") as handle:
            handle.write(content if isinstance(content, str) else json.dumps(content))

    def audit(self, *args, stdin="", env=None, cwd=None):
        full_env = dict(self.env, **(env or {}))
        full_env = {key: value for key, value in full_env.items() if value is not None}
        return subprocess.run([sys.executable, "-I", AUDIT, *args], input=stdin.encode(), env=full_env, cwd=cwd or self.root,
                              capture_output=True, timeout=60)

    def record(self, worktree=None):
        return self.audit("record", "--worktree", worktree or self.repo, "--llm", self.llm_path)

    def record_files(self):
        if not os.path.isdir(self.runtime):
            return []
        return sorted(name for name in os.listdir(self.runtime) if name.endswith(".json"))

    def item(self, sha, item_id):
        return next(item for item in self.read_record(sha)["items"] if item["id"] == item_id)

    def read_record(self, sha):
        with open(os.path.join(self.runtime, f"{sha}.json")) as handle:
            return json.load(handle)

    def gate(self, command, cwd=None, **extra):
        data = {"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
                "cwd": cwd or self.repo}
        data.update(extra)
        return self.audit("hook", "pre-tool-use", stdin=json.dumps(data))

    def denial(self, result):
        """The deny reason in a gate result, or None when the gate printed nothing (allow)."""
        self.assertEqual(result.returncode, 0, result.stderr)
        if not result.stdout:
            return None
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertEqual(output["permissionDecision"], "deny")
        return output["permissionDecisionReason"]
