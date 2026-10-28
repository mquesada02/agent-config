# Shared fixtures for the audit tests: a temporary git repo with a local bare origin, a temporary TMPDIR and a private HOME.
# Tests run the `audit` executable as a subprocess with `python3 -I`; no test imports it.
import hashlib
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


def declaration(command):
    return f"# Project\n\n### Test command\n\n```\n{command}\n```\n"


DECLARES_NONE = declaration("none")


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


ABSENT = object()  # a row key that the helper does not write


def owner_row(content, seconds, origin=ABSENT, version=VERSION, **extra):
    """A user row with a text prompt; `origin` is the whole value of the row key (a dict such as {"kind": "human"}), ABSENT writes none."""
    row = {"type": "user", "timestamp": stamp(seconds), "version": version, "message": {"role": "user", "content": content}}
    if origin is not ABSENT:
        row["origin"] = origin
    row.update(extra)
    return row


def queued_row(prompt, seconds, origin=ABSENT, version=VERSION, **extra):
    """A queued_command attachment row; `origin` is the whole value of the attachment key."""
    attachment = {"type": "queued_command", "prompt": prompt}
    if origin is not ABSENT:
        attachment["origin"] = origin
    row = {"type": "attachment", "timestamp": stamp(seconds), "version": version, "attachment": attachment}
    row.update(extra)
    return row


def ask_rows(call_id, answers, seconds, question="invented question text?"):
    """An AskUserQuestion tool_use row and the user row that answers it; `answers` is the whole toolUseResult.answers value."""
    ask = call_row("AskUserQuestion", {"questions": [{"question": question, "options": [{"label": "a"}, {"label": "b"}]}]}, call_id, seconds)
    reply = result_row(call_id, seconds + 1)
    if answers is not ABSENT:
        reply["toolUseResult"] = {"answers": answers}
    return [ask, reply]


EARLY = "2000-01-01T00:00:00.000Z"  # before every ledger event, which is stamped with the real time
LATE = "9999-01-01T00:00:00.000Z"  # after every ledger event
SONNET = "claude-sonnet-5-5"


def subagent_rows(model=SONNET, start=EARLY, version=VERSION, extra_models=()):
    """The rows of a synthetic subagent transcript: a prompt row at `start`, then one assistant row per model."""
    rows = [{"type": "user", "timestamp": start, "version": version, "message": {"role": "user", "content": "prompt"}}]
    for name in (model, *extra_models):
        message = {"content": [{"type": "text", "text": "report"}]}
        if name is not None:
            message["model"] = name
        rows.append({"type": "assistant", "timestamp": start, "version": version, "message": message})
    return rows


def event(kind, **fields):
    """A ledger event as `audit ledger` writes it. The time is EARLY unless given."""
    return {"kind": kind, "time": EARLY, **fields}


def round_event(n=1, loop="code-review", phase="correctness", reviewers=("rev1",), **extra):
    return event("round", loop=loop, phase=phase, round=n, reviewers=list(reviewers), **extra)


def finding_event(finding_id="I1", loop="code-review", phase="correctness", n=1, kind="Blocking", **extra):
    return event("finding", id=finding_id, loop=loop, phase=phase, round=n, loc="a.py:1", type=kind, reason="why", **extra)


def verdict_event(finding="I1", verifier="ver1", result="confirmed", **extra):
    return event("verdict", finding=finding, verifier=verifier, result=result, **extra)


def status_event(finding="I1", status="fixed", **extra):
    return event("status", finding=finding, status=status, **extra)


def extension_event(loop="code-review", phase="correctness", rounds=1, quote="one more round", **extra):
    return event("extension", loop=loop, phase=phase, rounds=rounds, quote=quote, **extra)


def phase_commit_event(sha, **extra):
    return event("phase-commit", sha=sha, **extra)


class AuditCase(unittest.TestCase):
    default_session = True  # register one synthetic session that edited a file in the worktree
    default_ledger = True  # start_branch writes a ledger of one round, reviewed by the default session's subagent "rev1"

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
            self.register_session("default-session", [edit_row(os.path.join(self.repo, "edited.txt"), "t1", 1)],
                                  subagents={"rev1": subagent_rows()})

    def register_session(self, session_id, rows, subagents=None, started_at="2026-10-15T12:00:00+00:00"):
        """Write a transcript (and subagent transcripts, a dict of name -> rows) and register it. Returns its path."""
        folder = os.path.join(self.root, "projects")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{session_id}.jsonl")
        self.write_rows(path, rows)
        for name, sub_rows in (subagents or {}).items():
            self.add_subagent(session_id, name, sub_rows)
        self.register_path(session_id, path, started_at)
        return path

    def add_subagent(self, session_id, name, rows=None):
        """Write the subagent transcript `name` of an already registered session. Returns its path."""
        sub_folder = os.path.join(self.root, "projects", session_id, "subagents")
        os.makedirs(sub_folder, exist_ok=True)
        path = os.path.join(sub_folder, f"agent-{name}.jsonl")
        self.write_rows(path, subagent_rows() if rows is None else rows)
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
        if self.default_ledger:
            self.write_ledger(name, [round_event()])
        return self.git("rev-parse", "HEAD")

    def ledger_file(self, branch="feature", url=None):
        key = hashlib.sha256(f"{url or self.origin}\n{branch}".encode()).hexdigest()
        return os.path.join(self.runtime, f"ledger-{key}.jsonl")

    def write_ledger(self, branch, events, url=None):
        """Write the ledger of a branch directly; an event is a dict or a raw line."""
        os.makedirs(self.runtime, exist_ok=True)
        os.chmod(self.runtime, 0o700)
        with open(self.ledger_file(branch, url), "w") as handle:
            for item in events:
                handle.write((item if isinstance(item, str) else json.dumps(item)) + "\n")

    def ledger(self, kind, *flags, worktree=None, env=None, cwd=None):
        """Run `audit ledger` as the registered default session; an `env` entry, even None, overrides that."""
        return self.audit("ledger", kind, "--worktree", worktree or self.repo, *flags,
                          env={"CLAUDE_CODE_SESSION_ID": "default-session", **(env or {})}, cwd=cwd)

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
