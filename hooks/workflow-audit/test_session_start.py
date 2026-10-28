import datetime
import json
import os
import stat
import subprocess
import sys
import unittest

from audit_support import AUDIT, AuditCase

# Runs a script as __main__ with a folder holding a shadow `runtime_dir` module first on the search path. The driver never imports the module itself.
SHADOW_DRIVER = """
import runpy, sys
shadow, script = sys.argv[1], sys.argv[2]
sys.path.insert(0, shadow)
sys.argv = [script] + sys.argv[3:]
runpy.run_path(script, run_name="__main__")
"""


class SessionStartTest(AuditCase):
    default_session = False

    def start(self, data=None, raw=None, **kwargs):
        text = raw if raw is not None else json.dumps(data)
        return self.audit("hook", "session-start", stdin=text, **kwargs)

    def lines(self):
        with open(os.path.join(self.runtime, "sessions.jsonl")) as handle:
            return [json.loads(line) for line in handle]

    def assert_registered_nothing(self, result):
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        self.assertFalse(os.path.exists(os.path.join(self.runtime, "sessions.jsonl")))

    def test_registers_the_session(self):
        result = self.start({"session_id": "abc-123", "transcript_path": "/home/u/.claude/projects/x/abc-123.jsonl", "source": "startup"})
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        [line] = self.lines()
        self.assertEqual(set(line), {"session_id", "transcript_path", "started_at"})
        self.assertEqual((line["session_id"], line["transcript_path"]), ("abc-123", "/home/u/.claude/projects/x/abc-123.jsonl"))
        started = datetime.datetime.fromisoformat(line["started_at"])
        self.assertIsNotNone(started.tzinfo)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.runtime, "sessions.jsonl")).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.runtime).st_mode), 0o700)

    def test_each_start_appends_a_line_and_a_repeated_session_adds_another(self):
        self.start({"session_id": "one", "transcript_path": "/t/one.jsonl"})
        self.start({"session_id": "two", "transcript_path": "/t/two.jsonl"})
        self.start({"session_id": "one", "transcript_path": "/t/one.jsonl", "source": "resume"})
        self.assertEqual([line["session_id"] for line in self.lines()], ["one", "two", "one"])

    def test_a_bad_input_registers_nothing_prints_nothing_and_exits_0(self):
        cases = {
            "not json": dict(raw="nope"),
            "empty": dict(raw=""),
            "not an object": dict(raw="[]"),
            "no session id": dict(data={"transcript_path": "/t"}),
            "no transcript path": dict(data={"session_id": "a"}),
            "session id with a slash": dict(data={"session_id": "../a", "transcript_path": "/t"}),
            "session id not a string": dict(data={"session_id": 5, "transcript_path": "/t"}),
            "empty session id": dict(data={"session_id": "", "transcript_path": "/t"}),
            "transcript path not a string": dict(data={"session_id": "a", "transcript_path": 5}),
            "empty transcript path": dict(data={"session_id": "a", "transcript_path": ""}),
            "line too long": dict(data={"session_id": "a", "transcript_path": "/" + "x" * 5000}),
            "invalid utf-8": dict(raw="\xff"),
        }
        for name, kwargs in cases.items():
            with self.subTest(name):
                self.assert_registered_nothing(self.start(**kwargs))

    def test_an_unsafe_runtime_folder_registers_nothing(self):
        os.mkdir(self.runtime, 0o755)
        os.chmod(self.runtime, 0o755)
        result = self.start({"session_id": "a", "transcript_path": "/t"})
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        self.assertEqual(os.listdir(self.runtime), [])

    def test_a_symlinked_registry_file_is_not_followed(self):
        os.mkdir(self.runtime, 0o700)
        target = os.path.join(self.root, "victim.txt")
        with open(target, "w") as handle:
            handle.write("keep")
        os.symlink(target, os.path.join(self.runtime, "sessions.jsonl"))
        result = self.start({"session_id": "a", "transcript_path": "/t"})
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        with open(target) as handle:
            self.assertEqual(handle.read(), "keep")

    def test_a_registry_that_is_not_a_regular_file_is_left_alone(self):
        os.mkdir(self.runtime, 0o700)
        os.mkdir(os.path.join(self.runtime, "sessions.jsonl"))
        result = self.start({"session_id": "a", "transcript_path": "/t"})
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        self.assertEqual(os.listdir(os.path.join(self.runtime, "sessions.jsonl")), [])


class ModuleSearchPathTest(AuditCase):
    def test_the_real_runtime_dir_module_wins_over_a_shadow_module_earlier_on_the_search_path(self):
        shadow = os.path.join(self.root, "shadow")
        os.mkdir(shadow)
        with open(os.path.join(shadow, "runtime_dir.py"), "w") as handle:
            handle.write("FOLDER_NAME = 'shadow'\n")
        env = {key: value for key, value in self.env.items()}
        data = json.dumps({"session_id": "a", "transcript_path": "/t"}).encode()
        result = subprocess.run([sys.executable, "-I", "-c", SHADOW_DRIVER, shadow, AUDIT, "hook", "session-start"], input=data, env=env,
                                capture_output=True, timeout=30)
        self.assertEqual((result.returncode, result.stderr), (0, b""))
        self.assertTrue(os.path.exists(os.path.join(self.runtime, "sessions.jsonl")))

    def test_the_shadow_module_cannot_weaken_record_either(self):
        self.start_branch("feature", "feat: a")
        shadow = os.path.join(self.root, "shadow")
        os.mkdir(shadow)
        with open(os.path.join(shadow, "runtime_dir.py"), "w") as handle:
            handle.write("raise RuntimeError('the shadow module was imported')\n")
        result = subprocess.run([sys.executable, "-I", "-c", SHADOW_DRIVER, shadow, AUDIT, "record", "--worktree", self.repo, "--base", "main", "--llm", self.llm_path],
                                env=self.env, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.record_files()), 1)


if __name__ == "__main__":
    unittest.main()
