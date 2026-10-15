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


class AuditCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.tmp = os.path.join(self.root, "tmp")
        self.home = os.path.join(self.root, "home")
        self.origin = os.path.join(self.root, "origin.git")
        self.repo = os.path.join(self.root, "repo")
        for folder in (self.tmp, self.home, self.repo):
            os.mkdir(folder)
        self.runtime = os.path.join(self.tmp, FOLDER_NAME)
        self.env = {
            "PATH": os.environ["PATH"], "HOME": self.home, "TMPDIR": self.tmp,
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
        }
        self.git("init", "--bare", "-b", "main", self.origin, cwd=self.root)
        self.git("init", "-b", "main", cwd=self.repo)
        self.git("remote", "add", "origin", self.origin)
        self.commit("chore: initial commit")
        self.git("push", "-u", "origin", "main")
        self.llm_path = os.path.join(self.root, "llm.json")
        self.write_llm(PASSING_LLM)

    def git(self, *args, cwd=None, check=True):
        result = subprocess.run(["git", *args], cwd=cwd or self.repo, env=self.env, capture_output=True, text=True, timeout=30)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def commit(self, message, name=None):
        name = name or f"file{len(os.listdir(self.repo))}.txt"
        with open(os.path.join(self.repo, name), "w") as handle:
            handle.write(message)
        self.git("add", name)
        self.git("commit", "-m", message)
        return self.git("rev-parse", "HEAD")

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
