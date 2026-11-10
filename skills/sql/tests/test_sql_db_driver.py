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
argv = sys.argv[1:]
if "--tools" in argv and argv[argv.index("--tools") + 1] == "":
    with open(os.path.join(work, "claude-judge.json"), "w") as handle:
        json.dump({"argv": argv, "env": dict(os.environ), "cwd": os.getcwd()}, handle)
    judge = os.environ.get("FAKE_JUDGE_MODE", "ok")
    if judge == "fail":
        sys.exit(3)
    print("SCORE: 4/5 clear cause" if judge == "ok" else "no score here")
    sys.exit(0)
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
elif mode.startswith("facts"):
    facts = {"ok": True, "action": "facts", "service": "x", "facts": {"shop.customers.email": {"nullable": True, "type": "text"}}}
    for call_id, service in (("a", "app-pg13"), ("b", "app-pg18")):
        command = "python3 /skill/scripts/pg_run.py facts --repo . --service " + service + " --names shop.customers.email"
        events.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": call_id, "name": "Bash", "input": {"command": command}}]}})
        events.append(result(call_id, facts))
    row = "| 1 | PG-02 | src/customers.ts:5 | NOT IN over a nullable column | Use NOT EXISTS. |"
    if mode != "facts-nofinal":
        events.append({"type": "result", "result": "# sql optimize: src/customers.ts\n\n## Critical\n" + ("" if mode == "facts-norule" else row)})
REPORTS = {
    "plan02": "# sql optimize: src/report.ts\n\n**Result: 0 critical, 1 required, 0 suggestions.**\n\n## Required\n\n"
              "| # | Rule | Where | Problem | Fix |\n|---|---|---|---|---|\n"
              "| 1 | PLAN-02 | src/report.ts:5-7 | Seq Scan on events scanned 30000 rows against 10000. It reads the table to keep few rows. "
              "| Add an index on kind. |\n\n## Approve\n\n"
              "Reply with the findings to fix: `all`, `none`, a list such as `1,3,5`, or a range such as `1-12`.\n",
    "disabled": "# sql optimize: src/report.ts\n\n**Result: 0 critical, 0 required, 0 suggestions.**\n\n"
                "Disabled rules: PLAN-02.\n\n## Approve\n\nThere is nothing to approve.\n",
    "clean": "# sql optimize: src/report.ts\n\n**Result: 0 critical, 0 required, 0 suggestions.**\n\n"
             "## Approve\n\nThere is nothing to approve.\n",
}
REPORTS["plan02-bad"] = REPORTS["plan02"].split("## Approve")[0]
REPORTS["disabled-wrong"] = REPORTS["disabled"].replace("PLAN-02", "PLAN-03")
if mode in REPORTS or mode == "plan02-nofinal":
    checked = {"ok": True, "server_version_num": 130000, "analyze": True, "notes": [], "findings": [],
               "plan": [{"Plan": {"Node Type": "Result"}}]}
    for call_id, service in (("a", "app-pg13"), ("b", "app-pg18")):
        command = ("python3 /skill/scripts/pg_run.py explain --repo . --service " + service +
                   " --mode select --statement 'SELECT 1' | python3 /skill/scripts/plan_findings.py -")
        events.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": call_id, "name": "Bash", "input": {"command": command}}]}})
        events.append(result(call_id, checked))
    if mode != "plan02-nofinal":
        events.append({"type": "result", "result": REPORTS[mode]})
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

    def driver(self, *args, env=None, out=None):
        return subprocess.run([sys.executable, "-I", DRIVER, "--out", out or self.out, *args], capture_output=True,
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
            f"Bash(python3 {SKILL_DIR}/scripts/{name}.py:*)"
            for name in ("rules_file", "extract", "allowlist", "pg_run", "plan_findings")])
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

    def test_a_case_with_a_rules_key_is_graded_by_grader_e_on_the_final_message(self):
        proc = self.driver("--case", "facts-pg-02", "--runs", "1", env={"FAKE_CLAUDE_MODE": "facts"})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(proc.stdout.splitlines(), ["facts-pg-02#1: PASS", "PASS"])

    def test_a_report_without_the_expected_rule_id_fails_with_the_case_label(self):
        proc = self.driver("--case", "facts-pg-02", "--runs", "1", env={"FAKE_CLAUDE_MODE": "facts-norule"})
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout.splitlines(), [
            "FAIL facts-pg-02#1 expect:PG-02: not found in the Rule column", "facts-pg-02#1: FAIL", "FAIL"])

    def test_a_run_with_no_final_message_fails_when_the_case_has_rules(self):
        proc = self.driver("--case", "facts-pg-02", "--runs", "1", env={"FAKE_CLAUDE_MODE": "facts-nofinal"})
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(any(line.startswith("FAIL facts-pg-02#1 trace: no final message") for line in proc.stdout.splitlines()),
                        proc.stdout)

    def test_a_case_with_no_rules_key_runs_no_grader_e(self):
        proc = self.driver("--case", "plan-select", "--runs", "1")
        self.assertEqual(proc.stdout.splitlines(), ["plan-select#1: PASS", "PASS"])

    def judge(self):
        with open(os.path.join(self.work, "claude-judge.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def test_a_report_case_is_graded_by_graders_e_and_i_and_the_judge_line_is_printed(self):
        proc = self.driver("--case", "plan-02-seq-scan", "--runs", "1", env={"FAKE_CLAUDE_MODE": "plan02"})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(proc.stdout.splitlines(),
                         ["plan-02-seq-scan#1: PASS", "JUDGE plan-02-seq-scan#1: 4/5 clear cause", "PASS"])

    def test_the_judge_call_has_no_tools_no_session_no_settings_and_no_database_variable(self):
        self.driver("--case", "plan-02-seq-scan", "--runs", "1", env={"FAKE_CLAUDE_MODE": "plan02"})
        seen = self.judge()
        argv = seen["argv"]
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertEqual(argv[argv.index("--model") + 1], "sonnet")
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        for flag in ("--no-session-persistence", "--strict-mcp-config"):
            self.assertIn(flag, argv)
        self.assertNotIn("--allowedTools", argv)
        self.assertFalse([key for key in seen["env"] if key.startswith("PG")])
        prompt = argv[argv.index("-p") + 1]
        self.assertIn("SCORE: <n>/5", prompt)
        self.assertIn("| 1 | PLAN-02 |", prompt)

    def test_a_judge_that_fails_or_gives_no_score_is_reported_and_changes_no_result(self):
        for judge, text in (("fail", "not scored (exit code 3)"), ("noscore", "not scored (no score line)")):
            with self.subTest(judge=judge):
                proc = self.driver("--case", "plan-02-seq-scan", "--runs", "1", out=os.path.join(self.root, judge),
                                   env={"FAKE_CLAUDE_MODE": "plan02", "FAKE_JUDGE_MODE": judge})
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertEqual(proc.stdout.splitlines(),
                                 ["plan-02-seq-scan#1: PASS", f"JUDGE plan-02-seq-scan#1: {text}", "PASS"])

    def test_a_judge_line_does_not_hide_a_failure(self):
        proc = self.driver("--case", "plan-02-seq-scan", "--runs", "1", env={"FAKE_CLAUDE_MODE": "plan02-bad"})
        self.assertEqual(proc.returncode, 1)
        lines = proc.stdout.splitlines()
        self.assertTrue(any(line.startswith("FAIL plan-02-seq-scan#1 ") for line in lines), proc.stdout)
        self.assertIn("plan-02-seq-scan#1: FAIL", lines)
        self.assertTrue(any(line.startswith("JUDGE plan-02-seq-scan#1") for line in lines))
        self.assertEqual(lines[-1], "FAIL")

    def test_a_report_case_with_no_final_message_fails(self):
        proc = self.driver("--case", "plan-02-seq-scan", "--runs", "1", env={"FAKE_CLAUDE_MODE": "plan02-nofinal"})
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(any(line.startswith("FAIL plan-02-seq-scan#1 trace: no final message")
                            for line in proc.stdout.splitlines()), proc.stdout)
        self.assertIn("JUDGE plan-02-seq-scan#1: not scored (no final message)", proc.stdout)

    def test_the_disabled_key_is_passed_to_grader_i(self):
        proc = self.driver("--case", "plan-disabled", "--runs", "1", env={"FAKE_CLAUDE_MODE": "disabled"})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        proc = self.driver("--case", "plan-disabled", "--runs", "1", out=os.path.join(self.root, "out-wrong"),
                           env={"FAKE_CLAUDE_MODE": "disabled-wrong"})
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(any(line.startswith("FAIL plan-disabled#1 disabled") for line in proc.stdout.splitlines()),
                        proc.stdout)

    def test_a_clean_case_has_no_judge_line(self):
        proc = self.driver("--case", "plan-clean", "--runs", "1", env={"FAKE_CLAUDE_MODE": "clean"})
        self.assertEqual(proc.stdout.splitlines(), ["plan-clean#1: PASS", "PASS"])
        self.assertFalse(os.path.exists(os.path.join(self.work, "claude-judge.json")))

    def test_a_rule_case_fails_when_the_report_lacks_the_expected_rule(self):
        proc = self.driver("--case", "plan-02-seq-scan", "--runs", "1", env={"FAKE_CLAUDE_MODE": "clean"})
        self.assertEqual(proc.returncode, 1)
        self.assertIn("FAIL plan-02-seq-scan#1 expect:PLAN-02: not found in the Rule column", proc.stdout)

    def test_the_real_case_names_and_their_expectations(self):
        plans = ["plan:app-pg13", "plan:app-pg18"]
        expected = {"plan-select": plans, "facts-pg-02": ["facts:app-pg13", "facts:app-pg18"],
                    "plan-01-estimate": plans, "plan-02-seq-scan": plans, "plan-03-spill": plans,
                    "plan-04-nested-loop": plans, "plan-05-cache": plans, "plan-clean": plans,
                    "plan-disabled": plans,
                    "bad-password": ["connection_failed:app-badpw"],
                    "wrong-host": ["connection_failed:app-wronghost"]}
        rules = {"facts-pg-02": {"expect": ["PG-02"], "forbid": []},
                 "plan-01-estimate": {"expect": ["PLAN-01"], "forbid": []},
                 "plan-02-seq-scan": {"expect": ["PLAN-02"], "forbid": []},
                 "plan-03-spill": {"expect": ["PLAN-03"], "forbid": []},
                 "plan-04-nested-loop": {"expect": ["PLAN-04"], "forbid": []},
                 "plan-05-cache": {"expect": ["PLAN-05"], "forbid": []},
                 "plan-clean": {"expect": [], "forbid": [f"PLAN-0{n}" for n in range(1, 6)]},
                 "plan-disabled": {"expect": [], "forbid": ["PLAN-02"]}}
        self.assertEqual(sorted(os.listdir(CASES)), sorted(expected))
        for name, kinds in expected.items():
            with open(os.path.join(CASES, name, "db-expect.json"), encoding="utf-8") as handle:
                data = json.load(handle)
            self.assertEqual(data["expect"], kinds)
            self.assertEqual(data.get("rules"), rules.get(name))
            report = name.startswith("plan-") and name != "plan-select"
            self.assertEqual(data.get("report"), True if report else None)
            self.assertEqual(data.get("judge"), "rubric-plan.md" if report and name != "plan-clean" else None)


if __name__ == "__main__":
    unittest.main()
