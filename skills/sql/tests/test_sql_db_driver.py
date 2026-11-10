import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

import test_sql_db_eval as base

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
DRIVER = os.path.join(SKILL_DIR, "evals", "db", "run_db_cases.py")
CASES = os.path.join(SKILL_DIR, "evals", "db", "cases")

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys, time
work = os.environ["FAKE_DOCKER_DIR"]
with open(os.path.join(work, "claude.json"), "w") as handle:
    json.dump({"argv": sys.argv[1:], "env": dict(os.environ), "cwd": os.getcwd()}, handle)
mode = os.environ.get("FAKE_CLAUDE_MODE", "plan")
if mode == "wait":
    open(os.path.join(work, "claude-started"), "w").write("1")
    time.sleep(60)
if mode == "fail":
    sys.exit(3)
if mode == "change":
    open(os.path.join(work, "checksum"), "w").write("m2")
    mode = "plan"
def call(call_id, service):
    command = "python3 /skill/scripts/pg_run.py explain --repo . --service " + service + " --mode select"
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": call_id, "name": "Bash", "input": {"command": command}}]}}
def result(call_id, payload, extra=""):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": call_id, "content": json.dumps(payload) + extra}]}}
plan = {"ok": True, "action": "explain", "plan": [{"Plan": {"Node Type": "Result"}}]}
events = [{"type": "assistant", "message": {"content": [{"type": "text", "text": "start"}]}}]
if mode == "plan":
    events += [call("a", "app-pg13"), result("a", plan), call("b", "app-pg18"), result("b", plan)]
elif mode == "leak":
    events += [call("a", "app-pg13"), result("a", plan), call("b", "app-pg18"), result("b", plan)]
    events.append({"type": "result", "result": os.environ["FAKE_LEAK"]})
elif mode == "noplan":
    events += [call("a", "app-pg13"), result("a", plan)]
for event in events:
    print(json.dumps(event))
'''

NEEDS_TOMLLIB = base.NEEDS_TOMLLIB


class DriverTest(base.TempTest):
    def setUp(self):
        super().setUp()
        # PATH holds only the fake bin folder (so that psql can be absent), so a script cannot use env python3
        for name, text in (("docker", base.FAKE_DOCKER), ("claude", FAKE_CLAUDE)):
            self.add_script(name, text.replace("#!/usr/bin/env python3", f"#!{sys.executable}", 1))
        self.add_script("psql", "#!/bin/sh\nexit 0\n")
        os.symlink(shutil.which("git"), os.path.join(self.bin, "git"))
        self.home = os.path.join(self.root, "home")
        self.xdg = os.path.join(self.root, "xdg-home")
        os.makedirs(self.xdg)
        self.out = os.path.join(self.root, "out")
        self.env.update({"PATH": self.bin, "XDG_CONFIG_HOME": self.xdg, "PGHOST": "must-be-dropped",
                         "PGSERVICE": "must-be-dropped", "PGPASSWORD": "must-be-dropped"})

    def driver(self, *args, env=None):
        return subprocess.run([sys.executable, "-I", DRIVER, "--out", self.out, *args], capture_output=True,
                              text=True, env={**self.env, **(env or {})}, cwd=self.root)

    def claude(self):
        with open(os.path.join(self.work, "claude.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def listing(self, folder):
        found = {}
        for current, _, files in os.walk(folder):
            for name in files + ["."]:
                path = os.path.join(current, name)
                found[path] = os.stat(path).st_mtime_ns
        return found

    def test_a_passing_run_prints_pass_and_saves_the_trace(self):
        proc = self.driver("--case", "plan-select", "--runs", "1")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(proc.stdout.splitlines(), ["plan-select#1: PASS", "PASS"])
        with open(os.path.join(self.out, "plan-select-1.jsonl"), encoding="utf-8") as handle:
            self.assertIn("app-pg18", handle.read())
        self.assertTrue(os.path.isfile(os.path.join(self.out, "plan-select-1-before-13.json")))
        self.assertTrue(os.path.isfile(os.path.join(self.out, "plan-select-1-after-18.json")))

    def test_the_arguments_of_claude(self):
        self.driver("--case", "plan-select", "--runs", "1", "--max-budget-usd", "2.5")
        argv = self.claude()["argv"]
        for flag in ("--no-session-persistence", "--strict-mcp-config", "--verbose"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--model") + 1], "sonnet")
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(argv[argv.index("--tools") + 1], "Skill,Read,Bash")
        self.assertEqual(argv[argv.index("--plugin-dir") + 1], SKILL_DIR)
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "2.5")
        allowed = argv[argv.index("--allowedTools") + 1:]
        self.assertEqual(allowed, ["Skill", "Read"] + [
            f"Bash(python3 {SKILL_DIR}/scripts/{name}.py:*)" for name in ("rules_file", "extract", "allowlist", "pg_run")])
        for name in ("Edit", "Write", "NotebookEdit"):
            self.assertFalse([arg for arg in argv if name in arg])

    def test_the_budget_flag_is_absent_when_not_given(self):
        self.driver("--case", "plan-select", "--runs", "1")
        self.assertNotIn("--max-budget-usd", self.claude()["argv"])

    def test_the_environment_of_claude(self):
        self.driver("--case", "plan-select", "--runs", "1")
        seen = self.claude()
        env = seen["env"]
        pg = {key: value for key, value in env.items() if key.startswith("PG")}
        self.assertEqual(set(pg), {"PGSERVICEFILE", "PGPASSFILE"})
        state = os.path.dirname(pg["PGSERVICEFILE"])
        self.assertTrue(os.path.basename(pg["PGSERVICEFILE"]) == "pg_service.conf")
        self.assertEqual(pg["PGPASSFILE"], os.path.join(state, "pgpass"))
        self.assertEqual(env["XDG_CONFIG_HOME"], os.path.join(state, "xdg"))
        self.assertEqual(env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"], "1")
        self.assertNotIn(self.home, state)
        self.assertTrue(os.path.isfile(os.path.join(seen["cwd"], "src", "revenue.ts")))

    def test_the_work_folder_is_a_copy_of_the_case_repo_with_the_origin(self):
        self.driver("--case", "plan-select", "--runs", "1")
        work = os.path.join(self.out, "plan-select-1-work")
        url = subprocess.run(["git", "-C", work, "remote", "get-url", "origin"], capture_output=True, text=True,
                             env={"PATH": self.bin, "HOME": self.env["HOME"]}).stdout.strip()
        self.assertEqual(url, "https://example.invalid/eval/sql-db-case.git")
        self.assertTrue(os.path.isfile(os.path.join(work, "docs", "agents", "sql.md")))

    def test_no_file_appears_or_changes_in_home_or_the_xdg_folder(self):
        os.makedirs(self.home, exist_ok=True)
        before = (self.listing(self.home), self.listing(self.xdg))
        proc = self.driver("--case", "plan-select", "--runs", "1")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual((self.listing(self.home), self.listing(self.xdg)), before)

    def test_a_failing_claude_gives_exit_1_and_the_teardown_runs(self):
        proc = self.driver("--case", "plan-select", "--runs", "1", env={"FAKE_CLAUDE_MODE": "fail"})
        self.assertEqual(proc.returncode, 1)
        self.assertIn("FAIL plan-select#1 claude: exit code 3", proc.stdout)
        self.assertEqual(len(self.verbs("rm")), 2)

    def test_a_missing_expected_plan_fails_grader_h(self):
        proc = self.driver("--case", "plan-select", "--runs", "1", env={"FAKE_CLAUDE_MODE": "noplan"})
        self.assertEqual(proc.returncode, 1)
        self.assertIn("FAIL plan-select#1 expected: plan:app-pg18 not found", proc.stdout)
        self.assertTrue(proc.stdout.rstrip().endswith("FAIL"))

    def test_a_canary_in_the_transcript_fails_the_leak_scan_without_its_value(self):
        with open(os.path.join(SKILL_DIR, "evals", "db", "canaries.json"), encoding="utf-8") as handle:
            canaries = json.load(handle)
        proc = self.driver("--case", "plan-select", "--runs", "1",
                           env={"FAKE_CLAUDE_MODE": "leak", "FAKE_LEAK": canaries["password"]})
        self.assertEqual(proc.returncode, 1)
        self.assertIn("FAIL plan-select#1 leak: password", proc.stdout)
        self.assertNotIn(canaries["password"], proc.stdout + proc.stderr)

    def test_a_changed_table_fails_grader_g_with_the_version(self):
        proc = self.driver("--case", "plan-select", "--runs", "1", env={"FAKE_CLAUDE_MODE": "change"})
        self.assertEqual(proc.returncode, 1)
        for version in ("13", "18"):
            self.assertIn(f"FAIL plan-select#1 (postgres {version}) table: shop.customers changed", proc.stdout)

    def test_the_teardown_runs_when_claude_is_killed(self):
        proc = subprocess.Popen([sys.executable, "-I", DRIVER, "--out", self.out, "--case", "plan-select",
                                 "--runs", "1"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                env={**self.env, "FAKE_CLAUDE_MODE": "wait"}, cwd=self.root)
        started = os.path.join(self.work, "claude-started")
        deadline = time.monotonic() + 60
        while not os.path.exists(started) and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(os.path.exists(started))
        proc.send_signal(signal.SIGTERM)
        proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 128 + signal.SIGTERM)
        self.assertEqual(len(self.verbs("rm")), 2)

    def test_a_missing_psql_stops_with_a_message_and_starts_nothing(self):
        os.remove(os.path.join(self.bin, "psql"))
        proc = self.driver("--case", "plan-select", "--runs", "1")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("psql", proc.stderr)
        self.assertEqual(self.verbs("run"), [])

    def test_usage_errors_are_exit_2(self):
        for args in (["--case", "no-such-case"], ["--runs", "0"]):
            with self.subTest(args=args):
                self.assertEqual(self.driver(*args).returncode, 2)

    def test_the_real_case_names_and_their_expectations(self):
        expected = {"plan-select": ["plan:app-pg13", "plan:app-pg18"],
                    "bad-password": ["connection_failed:app-badpw"],
                    "wrong-host": ["connection_failed:app-wronghost"]}
        self.assertEqual(sorted(os.listdir(CASES)), sorted(expected))
        for name, kinds in expected.items():
            with open(os.path.join(CASES, name, "db-expect.json"), encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["expect"], kinds)


if __name__ == "__main__":
    unittest.main()
