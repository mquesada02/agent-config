import json
import os
import pwd
import re
import subprocess
import sys
import tempfile
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
RUNNER = os.path.join(SKILL_DIR, "evals", "turns", "run_setup_turns.py")
REAL_EVALS = os.path.join(SKILL_DIR, "evals")

RULES_TEXT = '# SQL rules\n\n```toml\n[style]\nindent = "2 spaces"\n```\n\n- Rule one\n'
CONFIRMATION = "Show me the diff, and then confirm it and write the files."

# The fake `claude`: logs each call, then plays the turn that the scenario file describes.
FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
fake_dir = os.environ["FAKE_DIR"]
keys = ("HOME", "XDG_CONFIG_HOME", "PGSERVICEFILE", "TMPDIR", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "PGHOST")
with open(os.path.join(fake_dir, "calls.jsonl"), "a") as handle:
    handle.write(json.dumps({"argv": argv, "cwd": os.getcwd(), "env": {k: os.environ.get(k) for k in keys}}) + "\n")
with open(os.path.join(fake_dir, "scenario.json")) as handle:
    scenario = json.load(handle)
turn = scenario["turn2"] if "--resume" in argv else scenario["turn1"]
if turn.get("exit"):
    sys.exit(turn["exit"])
rules_text = scenario["rules_text"]
diff_text = "Diff to confirm:\n+line one\n+line two" if turn.get("show") else "I will write the files now."
events = []
if turn.get("plan"):
    plan = {"ok": True, "digest": "d1", "rules_file": {"diff": "--- a\n+++ b\n+line one\n+line two", "text": rules_text}}
    events.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "p1", "name": "Bash",
        "input": {"command": "python3 /skill/scripts/setup_files.py plan . --proposal /tmp/p.json"}}]}})
    events.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "p1", "content": json.dumps(plan)}]}})
events.append({"type": "assistant", "message": {"content": [{"type": "text", "text": diff_text}]}})
if turn.get("change_call"):
    events.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "w1", "name": "Write",
        "input": {"file_path": os.path.join(os.getcwd(), "docs", "agents", "sql.md"), "content": rules_text}}]}})
for path in turn.get("write_files", []):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(rules_text)
if turn.get("write_xdg"):
    target = os.path.join(os.environ["XDG_CONFIG_HOME"], "sql-skill", "allowlist.toml")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w") as handle:
        handle.write("x = 1\n")
if turn.get("sandbox_fail"):
    events.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "s1", "name": "Bash",
        "input": {"command": "python3 /skill/scripts/rules_file.py ."}}]}})
    events.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "s1",
        "content": "Sandbox is enabled but failed to initialize: Failed to create bridge sockets after 5 attempts."}]}})
if turn.get("quote_sandbox_text"):
    events.append({"type": "assistant", "message": {"content": [{"type": "text",
        "text": "The text Sandbox is enabled but failed to initialize is an error text of claude."}]}})
if not turn.get("no_result"):
    events.append({"type": "result", "result": diff_text})
for event in events:
    print(json.dumps(event))
if turn.get("garbage"):
    print("not json")
'''

CASE_YAML = """schema_version: "1.0"
name: setup-fake
execution:
  max_turns: 30
  prompt: |
    Run `/sql setup` here. Use these answers. Keep the tags.
    {confirmation} In your final message, show the whole rules file.
"""
SCAFFOLD = """#!/usr/bin/env bash
set -eu
git init -q
git remote add origin https://example.com/acme/shop.git
printf '[app-dev]\\nhost=localhost\\n' > "$HOME/.pg_service.conf"
"""
EXPECTED = {"settings": {"style": {"indent": "2 spaces"}}, "contains": ["Rule one"], "no_allowlist": True}

GOOD = {
    "rules_text": RULES_TEXT,
    "turn1": {"plan": True, "show": True},
    "turn2": {"change_call": True, "write_files": ["docs/agents/sql.md"]},
}


def scenario(turn1=None, turn2=None):
    return {"rules_text": RULES_TEXT, "turn1": {**GOOD["turn1"], **(turn1 or {})}, "turn2": {**GOOD["turn2"], **(turn2 or {})}}


class TurnsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sqlturns-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)
        self.bin = os.path.join(self.root, "bin")
        self.fake_dir = os.path.join(self.root, "fake")
        self.evals = os.path.join(self.root, "evals")
        self.out = os.path.join(self.root, "out")
        for folder in (self.bin, self.fake_dir):
            os.makedirs(folder)
        claude = os.path.join(self.bin, "claude")
        with open(claude, "w", encoding="utf-8") as handle:
            handle.write(FAKE_CLAUDE.replace("#!/usr/bin/env python3", f"#!{sys.executable}", 1))
        os.chmod(claude, 0o755)
        self.env = {**os.environ, "PATH": self.bin + os.pathsep + os.environ["PATH"], "FAKE_DIR": self.fake_dir,
                    "PGHOST": "must-be-dropped"}
        self.make_case("setup-fake")
        self.set_scenario(GOOD)

    def make_case(self, name, case_yaml=None, scaffold=SCAFFOLD, expected=EXPECTED):
        folder = os.path.join(self.evals, name)
        os.makedirs(folder, exist_ok=True)
        files = {"case.yaml": case_yaml if case_yaml is not None else CASE_YAML.format(confirmation=CONFIRMATION),
                 "scaffold.sh": scaffold, "expected.json": json.dumps(expected)}
        for file_name, text in files.items():
            with open(os.path.join(folder, file_name), "w", encoding="utf-8") as handle:
                handle.write(text)

    def set_scenario(self, data):
        with open(os.path.join(self.fake_dir, "scenario.json"), "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def run_runner(self, *args, out=None, evals=None, env=None, cwd=None):
        argv = [sys.executable, "-I", RUNNER, "--evals", evals or self.evals]
        if out != "":
            argv += ["--out", out or self.out]
        return subprocess.run(argv + list(args), capture_output=True, text=True, env={**self.env, **(env or {})},
                              cwd=cwd or self.root)

    def calls(self):
        path = os.path.join(self.fake_dir, "calls.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle.read().splitlines()]

    def fail_lines(self, proc):
        return [line for line in proc.stdout.splitlines() if line.startswith("FAIL ") and line != "FAIL"]

    def assertFail(self, proc, prefix):
        self.assertTrue(any(line.startswith(prefix) for line in proc.stdout.splitlines()), proc.stdout + proc.stderr)

    # --- FN24: the child may never apply a formatter install ---
    def test_the_child_may_never_run_formatter_install_apply(self):
        proc = self.run_runner("--runs", "1")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        argv = self.calls()[0]["argv"]
        denied = self.rules_after(argv, "--disallowedTools")
        self.assertTrue([rule for rule in denied if rule.startswith("Bash(") and "formatter_install.py apply" in rule], denied)
        allowed = self.rules_after(argv, "--allowedTools")
        self.assertFalse([rule for rule in allowed if "formatter_install" in rule], allowed)

    # --- the owner decision of 2026-11-12: Bash runs only in the OS sandbox ---
    def test_bash_runs_only_in_a_sandbox_that_writes_only_in_the_run_folders_and_has_no_network(self):
        self.run_runner("--runs", "1")
        argv = self.calls()[0]["argv"]
        settings = json.loads(argv[argv.index("--settings") + 1])["sandbox"]
        run_folder = os.path.join(self.out, "setup-fake-1")
        self.assertIs(settings["enabled"], True)
        self.assertIs(settings["autoAllowBashIfSandboxed"], True)
        self.assertIs(settings["allowUnsandboxedCommands"], False)
        self.assertEqual(settings["filesystem"]["allowWrite"],
                         [os.path.join(run_folder, "work"), os.path.join(run_folder, "home", ".config"),
                          os.path.join(run_folder, "tmp")])
        self.assertEqual(settings["network"]["allowedDomains"], [])
        self.assertIs(settings["failIfUnavailable"], True)
        # a compound command with shell variables is denied in dontAsk mode with the auto-allow alone, so Bash is listed;
        # the sandbox settings above are what confine it
        self.assertEqual([rule for rule in self.rules_after(argv, "--allowedTools") if rule.startswith("Bash")], ["Bash"])

    def rules_after(self, argv, flag):
        rules = []
        for rule in argv[argv.index(flag) + 1:]:
            if rule.startswith("--"):
                break
            rules.append(rule)
        return rules

    # --- the three cases of the brief ---
    def test_a_write_only_in_turn_2_after_the_shown_diff_passes(self):
        proc = self.run_runner("--runs", "1")
        self.assertEqual((proc.returncode, proc.stdout.splitlines()), (0, ["setup-fake#1: PASS", "PASS"]), proc.stderr)
        self.assertEqual(len(self.calls()), 2)

    def test_a_turn_1_that_writes_a_file_fails(self):
        self.set_scenario(scenario(turn1={"change_call": True, "write_files": ["docs/agents/sql.md"]}))
        proc = self.run_runner("--runs", "1")
        self.assertEqual(proc.returncode, 1)
        self.assertFail(proc, "FAIL setup-fake#1 turn1 no-write:")
        self.assertIn("setup-fake#1: FAIL", proc.stdout.splitlines())
        self.assertEqual(proc.stdout.splitlines()[-1], "FAIL")

    def test_a_turn_1_change_call_that_fails_to_write_still_fails(self):
        self.set_scenario(scenario(turn1={"change_call": True}))
        proc = self.run_runner("--runs", "1")
        self.assertFail(proc, "FAIL setup-fake#1 turn1 no-write:")

    def test_a_turn_1_write_under_the_temp_home_fails(self):
        self.set_scenario(scenario(turn1={"write_xdg": True}))
        proc = self.run_runner("--runs", "1")
        self.assertFail(proc, "FAIL setup-fake#1 turn1 no-write:")

    def test_a_turn_1_that_does_not_show_the_diff_fails(self):
        self.set_scenario(scenario(turn1={"show": False}))
        proc = self.run_runner("--runs", "1")
        self.assertEqual(self.fail_lines(proc) and [line.split(":")[0] for line in self.fail_lines(proc)],
                         ["FAIL setup-fake#1 turn1 shown"])

    def test_a_turn_1_with_no_plan_fails_with_the_plan_line_only(self):
        self.set_scenario(scenario(turn1={"plan": False}))
        proc = self.run_runner("--runs", "1")
        self.assertEqual([line.split(":")[0] for line in self.fail_lines(proc)], ["FAIL setup-fake#1 turn1 plan"])

    def test_a_turn_1_failure_makes_no_second_claude_call(self):
        self.set_scenario(scenario(turn1={"plan": False}))
        self.run_runner("--runs", "1")
        self.assertEqual(len(self.calls()), 1)

    def test_a_turn_2_without_a_write_fails_and_grader_d_still_runs(self):
        self.set_scenario(scenario(turn2={"change_call": False, "write_files": []}))
        proc = self.run_runner("--runs", "1")
        lines = self.fail_lines(proc)
        self.assertTrue(lines[0].startswith("FAIL setup-fake#1 turn2 write:"), lines)
        self.assertTrue(any(line.startswith("FAIL setup-fake#1 D: ") for line in lines[1:]), lines)

    def test_a_grader_d_exit_code_2_is_a_cannot_grade_line(self):
        self.set_scenario(scenario(turn2={"garbage": True}))
        proc = self.run_runner("--runs", "1")
        self.assertFail(proc, "FAIL setup-fake#1 D: cannot grade")

    # --- the process ---
    def test_turn_2_resumes_the_session_id_that_turn_1_was_given(self):
        self.run_runner("--runs", "1")
        first, second = self.calls()
        session = first["argv"][first["argv"].index("--session-id") + 1]
        uuid.UUID(session)
        self.assertEqual(second["argv"][second["argv"].index("--resume") + 1], session)
        self.assertNotIn("--session-id", second["argv"])

    def test_the_arguments_of_claude(self):
        self.run_runner("--runs", "1")
        argv = self.calls()[0]["argv"]
        self.assertEqual(argv[0:2], ["-p", argv[1]])
        for flag, value in (("--model", "sonnet"), ("--output-format", "stream-json"), ("--setting-sources", ""),
                            ("--permission-mode", "dontAsk"), ("--max-budget-usd", "3"), ("--plugin-dir", SKILL_DIR)):
            self.assertEqual(argv[argv.index(flag) + 1], value, flag)
        self.assertIn("--strict-mcp-config", argv)
        self.assertIn("--verbose", argv)
        self.assertNotIn("--no-session-persistence", argv)

    def test_the_turn_prompts(self):
        self.run_runner("--runs", "1")
        first, second = self.calls()
        self.assertTrue(first["argv"][1].startswith("Run `/sql setup` here."))
        self.assertTrue(first["argv"][1].endswith("Keep the tags."), first["argv"][1])
        self.assertEqual(second["argv"][1], "I confirm the diff. Write the files now.")

    def test_the_child_env_and_cwd(self):
        self.run_runner("--runs", "1")
        call = self.calls()[0]
        run_folder = os.path.join(self.out, "setup-fake-1")
        env = call["env"]
        self.assertEqual(env["HOME"], self.env["HOME"])
        self.assertEqual(env["XDG_CONFIG_HOME"], os.path.join(run_folder, "home", ".config"))
        self.assertEqual(env["PGSERVICEFILE"], os.path.join(run_folder, "home", ".pg_service.conf"))
        self.assertTrue(os.path.isfile(env["PGSERVICEFILE"]))
        self.assertEqual(env["TMPDIR"], os.path.join(run_folder, "tmp"))
        self.assertEqual(env["GIT_CONFIG_GLOBAL"], "/dev/null")
        self.assertEqual(env["GIT_CONFIG_NOSYSTEM"], "1")
        self.assertIsNone(env["PGHOST"])
        self.assertEqual(call["cwd"], os.path.join(run_folder, "work"))

    def test_a_relative_out_gives_the_child_absolute_paths(self):
        self.run_runner("--runs", "1", out="rel-out")
        env = self.calls()[0]["env"]
        for key in ("XDG_CONFIG_HOME", "PGSERVICEFILE", "TMPDIR"):
            self.assertTrue(os.path.isabs(env[key]), (key, env[key]))
            self.assertTrue(env[key].startswith(os.path.join(self.root, "rel-out") + os.sep), (key, env[key]))

    def test_the_write_and_edit_rules_name_the_run_folders(self):
        self.run_runner("--runs", "1")
        argv = self.calls()[0]["argv"]
        rules = self.rules_after(argv, "--allowedTools")
        run_folder = os.path.join(self.out, "setup-fake-1")
        for tool in ("Write", "Edit"):
            wanted = {f"{tool}(/{run_folder}/work/**)", f"{tool}(/{run_folder}/home/.config/**)", f"{tool}(/{run_folder}/tmp/**)"}
            self.assertTrue(wanted <= set(rules), (wanted, rules))
        self.assertTrue({"Skill", "Read", "Glob", "Grep"} <= set(rules))
        self.assertFalse([rule for rule in rules if rule in ("Write", "Edit")], rules)

    def test_the_turn_files_are_kept_in_the_out_folder(self):
        self.run_runner("--runs", "1")
        for suffix in ("turn1", "turn2", "trace"):
            self.assertTrue(os.path.isfile(os.path.join(self.out, f"setup-fake-1-{suffix}.jsonl")), suffix)

    def test_runs_2_prints_two_result_lines(self):
        proc = self.run_runner("--runs", "2")
        self.assertEqual(proc.stdout.splitlines(), ["setup-fake#1: PASS", "setup-fake#2: PASS", "PASS"])
        self.assertEqual(len(self.calls()), 4)

    def test_case_selects_by_glob(self):
        self.make_case("setup-other")
        proc = self.run_runner("--runs", "1", "--case", "setup-oth*")
        self.assertEqual(proc.stdout.splitlines(), ["setup-other#1: PASS", "PASS"])

    def test_a_non_zero_exit_of_claude_in_turn_1_is_a_claude_line(self):
        self.set_scenario(scenario(turn1={"exit": 3}))
        proc = self.run_runner("--runs", "1")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(self.fail_lines(proc), ["FAIL setup-fake#1 claude: exit code 3 in turn 1"])
        self.assertEqual(len(self.calls()), 1)

    def test_a_failure_of_claude_in_turn_2_skips_the_turn_2_checks_and_grader_d(self):
        self.set_scenario(scenario(turn2={"exit": 3}))
        proc = self.run_runner("--runs", "1")
        self.assertEqual(self.fail_lines(proc), ["FAIL setup-fake#1 claude: exit code 3 in turn 2"])

    def test_a_turn_with_no_result_field_is_a_final_line_and_stops_the_run(self):
        self.set_scenario(scenario(turn1={"no_result": True}))
        proc = self.run_runner("--runs", "1")
        self.assertEqual(self.fail_lines(proc), ["FAIL setup-fake#1 turn1 final: no final message"])
        self.assertEqual(len(self.calls()), 1)

    def test_a_sandbox_that_failed_to_initialize_in_turn_1_ends_the_run_with_one_line(self):
        self.set_scenario(scenario(turn1={"sandbox_fail": True}))
        proc = self.run_runner("--runs", "1")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(self.fail_lines(proc),
                         ["FAIL setup-fake#1 sandbox: the sandbox failed to initialize in turn 1, Bash may have run unsandboxed"])
        self.assertEqual(len(self.calls()), 1)

    def test_a_sandbox_that_failed_to_initialize_in_turn_2_skips_the_turn_2_checks_and_grader_d(self):
        self.set_scenario(scenario(turn2={"sandbox_fail": True}))
        proc = self.run_runner("--runs", "1")
        self.assertEqual(self.fail_lines(proc),
                         ["FAIL setup-fake#1 sandbox: the sandbox failed to initialize in turn 2, Bash may have run unsandboxed"])
        self.assertEqual(proc.stdout.splitlines()[-2:], ["setup-fake#1: FAIL", "FAIL"])

    def test_the_sandbox_error_text_in_an_assistant_message_is_not_a_sandbox_failure(self):
        self.set_scenario(scenario(turn1={"quote_sandbox_text": True}, turn2={"quote_sandbox_text": True}))
        proc = self.run_runner("--runs", "1")
        self.assertEqual((proc.returncode, proc.stdout.splitlines()), (0, ["setup-fake#1: PASS", "PASS"]), proc.stderr)

    def test_a_grader_d_crash_with_no_fail_line_is_a_d_failure_not_a_pass(self):
        wrapper = os.path.join(self.root, "crash_wrapper.py")
        with open(wrapper, "w", encoding="utf-8") as handle:
            handle.write(
                "import importlib.util, sys\n"
                f"spec = importlib.util.spec_from_file_location('runner', {RUNNER!r})\n"
                "runner = importlib.util.module_from_spec(spec)\n"
                "spec.loader.exec_module(runner)\n"
                "runner.results.run_grader = lambda script, args, stdin=None: (1, [], 'Traceback: boom')\n"
                "sys.exit(runner.main(sys.argv[1:]))\n")
        proc = subprocess.run([sys.executable, "-I", wrapper, "--evals", self.evals, "--out", self.out, "--runs", "1"],
                              capture_output=True, text=True, env=self.env, cwd=self.root)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertEqual(self.fail_lines(proc), ["FAIL setup-fake#1 D: grader failed with exit code 1 (Traceback: boom)"])

    def test_the_default_out_folder_is_resolved_when_the_temp_folder_is_a_symlink(self):
        real_tmp = os.path.join(self.root, "real_tmp")
        os.makedirs(real_tmp)
        link = os.path.join(self.root, "link_tmp")
        os.symlink(real_tmp, link)
        proc = self.run_runner("--runs", "1", out="", env={"TMPDIR": link})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        shown = re.search(r"turn files in (\S+)", proc.stderr).group(1)
        self.assertEqual(shown, os.path.realpath(shown))
        self.assertTrue(shown.startswith(real_tmp + os.sep), shown)

    def test_a_second_run_with_the_same_out_folder_is_refused_without_a_claude_call(self):
        first = self.run_runner("--runs", "1")
        self.assertEqual(first.returncode, 0, first.stderr)
        calls = len(self.calls())
        second = self.run_runner("--runs", "1")
        self.assertEqual(second.returncode, 1)
        self.assertEqual(self.fail_lines(second), [
            f"FAIL setup-fake#1 scaffold: the run folder {os.path.join(self.out, 'setup-fake-1')} exists, use a new --out"])
        self.assertEqual(len(self.calls()), calls)

    def test_a_failed_scaffold_is_a_scaffold_line_with_no_claude_call(self):
        self.make_case("setup-fake", scaffold="#!/usr/bin/env bash\necho boom >&2\nexit 3\n")
        proc = self.run_runner("--runs", "1")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(self.fail_lines(proc), ["FAIL setup-fake#1 scaffold: boom"])
        self.assertEqual(self.calls(), [])

    # --- start conditions ---
    def test_the_runner_refuses_an_out_folder_inside_the_real_home(self):
        real_home = os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir)
        target = os.path.join(real_home, "sqlturns-refuse-" + uuid.uuid4().hex)
        self.assertFalse(os.path.exists(target))
        proc = self.run_runner("--runs", "1", out=target)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(len(proc.stderr.strip().splitlines()), 1)
        self.assertEqual(proc.stdout, "")
        self.assertEqual(self.calls(), [])
        self.assertFalse(os.path.exists(target))

    def test_a_prompt_with_no_confirmation_sentence_is_a_usage_error(self):
        self.make_case("setup-fake", case_yaml=CASE_YAML.format(confirmation="Go on."))
        proc = self.run_runner("--runs", "1")
        self.assertEqual((proc.returncode, proc.stdout), (2, ""))
        self.assertEqual(self.calls(), [])
        self.assertFalse(os.path.exists(self.out))

    def test_a_prompt_that_is_not_a_block_scalar_is_a_usage_error(self):
        text = 'schema_version: "1.0"\nname: setup-fake\nexecution:\n  prompt: "Run it. ' + CONFIRMATION + '"\n'
        self.make_case("setup-fake", case_yaml=text)
        self.assertEqual(self.run_runner("--runs", "1").returncode, 2)

    def test_runs_below_1_is_a_usage_error(self):
        self.assertEqual(self.run_runner("--runs", "0").returncode, 2)

    def test_a_glob_with_no_match_and_a_missing_evals_folder_are_usage_errors(self):
        proc = self.run_runner("--runs", "1", "--case", "nothing-*")
        self.assertEqual((proc.returncode, proc.stdout), (2, ""))
        self.assertEqual(len(proc.stderr.strip().splitlines()), 1)
        proc = self.run_runner("--runs", "1", evals=os.path.join(self.root, "no-such-evals"))
        self.assertEqual((proc.returncode, proc.stdout), (2, ""))

    def test_the_prompt_of_every_case_is_checked_before_the_files_of_any_case(self):
        self.make_case("setup-a", expected=EXPECTED)
        os.remove(os.path.join(self.evals, "setup-a", "expected.json"))
        self.make_case("setup-b", case_yaml='schema_version: "1.0"\nname: setup-b\nexecution:\n  prompt: |\n    No sentence here.\n')
        proc = self.run_runner("--runs", "1", "--case", "setup-[ab]")
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("expected.json", proc.stderr)
        self.assertIn("setup-b", proc.stderr)

    def test_a_usage_error_wins_over_the_refusal_to_start(self):
        real_home = os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir)
        target = os.path.join(real_home, "sqlturns-refuse-" + uuid.uuid4().hex)
        proc = self.run_runner("--runs", "1", "--case", "nothing-*", out=target)
        self.assertEqual(proc.returncode, 2)
        self.assertFalse(os.path.exists(target))

    def test_the_real_setup_prompts_split_into_a_turn_1_with_no_confirmation(self):
        # A turn 1 with no plan stops the run at once, so only the first call and its prompt are logged.
        self.set_scenario(scenario(turn1={"plan": False}))
        for case in ("setup-rerun", "setup-tags-fixture"):
            os.remove(os.path.join(self.fake_dir, "calls.jsonl")) if os.path.exists(os.path.join(self.fake_dir, "calls.jsonl")) else None
            self.run_runner("--runs", "1", "--case", case, evals=REAL_EVALS, out=os.path.join(self.root, "real-" + case))
            prompt = self.calls()[0]["argv"][1]
            self.assertTrue(prompt.startswith("Run `/sql setup` on the repo in the current folder"), prompt)
            self.assertNotIn("confirm it", prompt)
            self.assertNotIn("write the files", prompt)
            self.assertNotIn("In your final message", prompt)
            self.assertFalse(re.search(r"\s$", prompt))


if __name__ == "__main__":
    unittest.main()
