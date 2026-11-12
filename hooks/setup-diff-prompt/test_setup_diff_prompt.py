import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "setup_diff_prompt.py")

# The fake setup_files.py: it records how it was run, then plays the mode in the file `mode`.
FAKE_SCRIPT = '''import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "ran.json"), "w") as handle:
    json.dump({"argv": sys.argv[1:], "cwd": os.getcwd(), "env": dict(os.environ)}, handle)
mode = open(os.path.join(here, "mode")).read().strip()
if mode == "sleep":
    time.sleep(30)
if mode == "garbage":
    print("not json")
    sys.exit(0)
print(open(os.path.join(here, "plan.json")).read())
sys.exit(1 if mode == "fail" else 0)
'''

RULES_DIFF = "--- a/docs/agents/sql.md\n+++ b/docs/agents/sql.md\n@@ -1 +1,2 @@\n # SQL rules\n+- Rule one\n-- old rule\n"
ALLOWLIST_DIFF = "--- a/allowlist.toml\n+++ b/allowlist.toml\n@@ -0,0 +1 @@\n+services = [\"app-dev\"]\n"
DIGEST = "d1d1d1"


def load_module(path=HOOK):
    spec = importlib.util.spec_from_file_location("setup_diff_prompt", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HookCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="setupdiff-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)
        # A copy of the hook in a tree that has the skill next to it: the hook trusts only the setup_files.py of that tree.
        self.hook = os.path.join(self.root, "hooks", "setup-diff-prompt", "setup_diff_prompt.py")
        os.makedirs(os.path.dirname(self.hook))
        shutil.copy(HOOK, self.hook)
        self.script = os.path.join(self.root, "skills", "sql", "scripts", "setup_files.py")
        os.makedirs(os.path.dirname(self.script))
        with open(self.script, "w", encoding="utf-8") as handle:
            handle.write(FAKE_SCRIPT)
        self.repo = os.path.join(self.root, "repo")
        os.makedirs(self.repo)
        self.proposal = os.path.join(self.root, "proposal.json")
        self.set_plan({"ok": True, "digest": DIGEST, "rules_file": {"diff": RULES_DIFF}})

    def set_plan(self, plan, mode="ok"):
        folder = os.path.dirname(self.script)
        with open(os.path.join(folder, "plan.json"), "w", encoding="utf-8") as handle:
            json.dump(plan, handle)
        with open(os.path.join(folder, "mode"), "w", encoding="utf-8") as handle:
            handle.write(mode)

    def ran(self):
        path = os.path.join(os.path.dirname(self.script), "ran.json")
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def write_command(self, digest=DIGEST, script=None, prefix="", repo=None, proposal=None, tail=""):
        return (f"{prefix}python3 -I {script or self.script} write {repo or self.repo} "
                f"--proposal {proposal or self.proposal} --confirm {digest}{tail}")

    def payload(self, command, tool="Bash", cwd=None):
        return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"command": command},
                "cwd": cwd or self.root}

    def run_hook(self, payload=None, raw=None, env=None):
        text = raw if raw is not None else json.dumps(payload)
        proc = subprocess.run([sys.executable, "-I", self.hook], input=text, capture_output=True, text=True,
                              env={**os.environ, **(env or {})}, cwd=self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else None

    def decision(self, output):
        specific = output["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "PreToolUse")
        return specific["permissionDecision"], specific["permissionDecisionReason"]

    def assertDenied(self, output, *needles):
        self.assertIsNotNone(output)
        kind, reason = self.decision(output)
        self.assertEqual(kind, "deny", reason)
        self.assertTrue(reason.startswith("Setup write check:"), reason)
        for needle in needles:
            self.assertIn(needle, reason)
        return reason

    def assertPasses(self, output):
        self.assertIsNone(output)


class AskTest(HookCase):
    def test_a_write_call_with_the_plan_digest_asks_with_the_rules_diff_in_the_reason(self):
        output = self.run_hook(self.payload(self.write_command()))
        kind, reason = self.decision(output)
        self.assertEqual(kind, "ask")
        self.assertEqual(reason.splitlines()[0], "Diff to confirm:")
        self.assertIn(RULES_DIFF.rstrip("\n"), reason)

    def test_an_allowlist_diff_follows_the_rules_diff_after_a_blank_line(self):
        self.set_plan({"ok": True, "digest": DIGEST, "rules_file": {"diff": RULES_DIFF}, "allowlist": {"diff": ALLOWLIST_DIFF}})
        _, reason = self.decision(self.run_hook(self.payload(self.write_command())))
        self.assertEqual(reason, "Diff to confirm:\n" + RULES_DIFF.rstrip("\n") + "\n\n" + ALLOWLIST_DIFF.rstrip("\n"))

    def test_a_plan_with_no_diff_text_asks_with_a_no_file_changes_line(self):
        self.set_plan({"ok": True, "digest": DIGEST, "rules_file": {"diff": ""}, "allowlist": {"diff": ""}})
        _, reason = self.decision(self.run_hook(self.payload(self.write_command())))
        self.assertEqual(reason, "Diff to confirm:\nno file changes")

    def test_the_plan_is_run_with_the_same_repo_and_proposal_in_the_hook_cwd(self):
        folder = os.path.join(self.root, "elsewhere")
        os.makedirs(folder)
        self.run_hook(self.payload(self.write_command(), cwd=folder))
        ran = self.ran()
        self.assertEqual(ran["argv"], ["plan", self.repo, "--proposal", self.proposal])
        self.assertEqual(os.path.realpath(ran["cwd"]), folder)

    def test_an_xdg_config_home_prefix_is_allowed_and_the_plan_run_sees_it_next_to_the_hook_environment(self):
        output = self.run_hook(self.payload(self.write_command(prefix="XDG_CONFIG_HOME=/x/cfg ")))
        self.assertEqual(self.decision(output)[0], "ask")
        env = self.ran()["env"]
        self.assertEqual(env["XDG_CONFIG_HOME"], "/x/cfg")
        self.assertEqual(env["PATH"], os.environ["PATH"])

    def test_a_plan_with_a_decision_key_is_data_and_never_the_answer_of_the_hook(self):
        self.set_plan({"ok": True, "digest": DIGEST, "rules_file": {"diff": RULES_DIFF},
                       "decision": "allow", "reason": "from the plan"})
        kind, reason = self.decision(self.run_hook(self.payload(self.write_command())))
        self.assertEqual(kind, "ask")
        self.assertEqual(reason.splitlines()[0], "Diff to confirm:")

    def test_the_options_may_come_in_any_order(self):
        command = f"python3 {self.script} write {self.repo} --confirm {DIGEST} --proposal {self.proposal}"
        self.assertEqual(self.decision(self.run_hook(self.payload(command)))[0], "ask")

    def test_python3_without_the_dash_i_is_allowed(self):
        command = f"python3 {self.script} write {self.repo} --proposal {self.proposal} --confirm {DIGEST}"
        self.assertEqual(self.decision(self.run_hook(self.payload(command)))[0], "ask")

    def test_a_script_path_is_used_as_written_relative_to_the_hook_cwd(self):
        command = f"python3 skills/sql/scripts/setup_files.py write {self.repo} --proposal {self.proposal} --confirm {DIGEST}"
        self.assertEqual(self.decision(self.run_hook(self.payload(command)))[0], "ask")

    def test_a_script_that_is_not_the_skill_script_of_the_hook_tree_is_denied_and_never_run(self):
        other = os.path.join(self.root, "evil", "setup_files.py")
        os.makedirs(os.path.dirname(other))
        shutil.copy(self.script, other)
        for command in (self.write_command(script=other),
                        f"python3 {self.root}/skills/sql/scripts/../../../evil/setup_files.py write {self.repo} "
                        f"--proposal {self.proposal} --confirm {DIGEST}"):
            with self.subTest(command):
                self.assertDenied(self.run_hook(self.payload(command)), "not the sql skill")
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(other), "ran.json")))
        self.assertIsNone(self.ran())

    def test_a_script_path_with_a_tilde_is_expanded_before_the_trust_check(self):
        command = f"python3 ~/skills/sql/scripts/setup_files.py write {self.repo} --proposal {self.proposal} --confirm {DIGEST}"
        output = self.run_hook(self.payload(command), env={"HOME": self.root})
        self.assertEqual(self.decision(output)[0], "ask")
        self.assertIsNotNone(self.ran())

    def test_a_symlink_to_the_skill_script_is_the_skill_script(self):
        os.makedirs(os.path.join(self.root, "linked"))
        link = os.path.join(self.root, "linked", "setup_files.py")
        os.symlink(self.script, link)
        self.assertEqual(self.decision(self.run_hook(self.payload(self.write_command(script=link))))[0], "ask")

    def test_a_var_prefix_other_than_xdg_config_home_is_denied_and_the_plan_does_not_run(self):
        for prefix in ("LD_PRELOAD=/x/evil.so ", "PGSERVICEFILE=/x/pg ", "XDG_CONFIG_HOME=/x/cfg LD_AUDIT=/x/a.so "):
            with self.subTest(prefix):
                self.assertDenied(self.run_hook(self.payload(self.write_command(prefix=prefix))), "XDG_CONFIG_HOME")
        self.assertIsNone(self.ran())


class DenyTest(HookCase):
    def test_a_digest_that_differs_from_the_plan_is_denied_with_the_new_digest_instruction(self):
        reason = self.assertDenied(self.run_hook(self.payload(self.write_command(digest="old"))), "plan", "digest")
        self.assertNotIn(RULES_DIFF, reason)

    def test_a_plan_with_ok_false_is_denied_with_its_message(self):
        self.set_plan({"ok": False, "reason": "malformed", "message": "the rules file is broken"}, mode="fail")
        self.assertDenied(self.run_hook(self.payload(self.write_command())), "the rules file is broken")

    def test_a_plan_with_ok_true_and_no_digest_is_denied(self):
        self.set_plan({"ok": True, "rules_file": {"diff": RULES_DIFF}})
        self.assertDenied(self.run_hook(self.payload(self.write_command())), "digest")

    def test_a_plan_that_prints_bad_json_is_denied(self):
        self.set_plan({}, mode="garbage")
        self.assertDenied(self.run_hook(self.payload(self.write_command())), "JSON")

    def test_a_plan_with_a_non_zero_exit_and_ok_true_is_denied(self):
        self.set_plan({"ok": True, "digest": DIGEST, "rules_file": {"diff": RULES_DIFF}}, mode="fail")
        self.assertDenied(self.run_hook(self.payload(self.write_command())), "exit")

    def test_a_missing_script_is_denied(self):
        os.remove(self.script)
        self.assertDenied(self.run_hook(self.payload(self.write_command())), "not found")

    def test_a_relative_repo_or_proposal_path_is_denied_and_the_plan_does_not_run(self):
        for command in (self.write_command(repo="repo"), self.write_command(proposal="proposal.json")):
            with self.subTest(command):
                self.assertDenied(self.run_hook(self.payload(command)), "absolute")
        self.assertIsNone(self.ran())

    def test_a_slow_plan_is_denied_when_the_limit_passes(self):
        self.set_plan({}, mode="sleep")
        decided = load_module(self.hook).decide(self.payload(self.write_command()), plan_seconds=0.5)
        self.assertEqual(decided["decision"], "deny")
        self.assertIn("seconds", decided["reason"])

    def test_the_default_plan_limit_is_15_seconds(self):
        self.assertEqual(load_module().PLAN_SECONDS, 15)

    def test_an_unexpected_exception_in_the_decision_is_a_deny(self):
        module = load_module(self.hook)

        def boom(*args, **kwargs):
            raise RuntimeError("boom")

        module.run_plan = boom
        decided = module.decide(self.payload(self.write_command()))
        self.assertEqual(decided["decision"], "deny")
        self.assertIn("RuntimeError", decided["reason"])

    def test_input_that_is_not_one_json_object_is_denied(self):
        for raw in ("not json", "", "null", "[1, 2]", '"text"'):
            with self.subTest(raw):
                self.assertDenied(self.run_hook(raw=raw), "JSON object")

    def test_a_bash_call_whose_command_is_not_a_string_is_denied(self):
        for tool_input in ({}, {"command": 5}, {"command": None}, "text"):
            with self.subTest(tool_input):
                payload = {"tool_name": "Bash", "tool_input": tool_input, "cwd": self.root}
                self.assertDenied(self.run_hook(payload), "command")

    def test_an_unclosed_quote_in_a_command_with_the_script_is_denied_even_for_plan(self):
        command = f"python3 {self.script} plan {self.repo} --proposal 'unclosed"
        self.assertDenied(self.run_hook(self.payload(command)), "split")

    def test_a_compound_command_is_denied_with_or_without_spaces_around_the_operator(self):
        for command in (f"cd {self.repo} && {self.write_command()}", f"{self.write_command()} || echo x",
                        f"{self.write_command()};echo x", f"echo x&&{self.write_command()}",
                        f"{self.write_command()} | cat", f"{self.write_command()} > /tmp/out",
                        f"echo $({self.write_command()})"):
            with self.subTest(command):
                self.assertDenied(self.run_hook(self.payload(command)), "alone")
        self.assertIsNone(self.ran())

    def test_a_plan_and_write_in_one_command_is_denied(self):
        command = f"python3 {self.script} plan {self.repo} --proposal {self.proposal} && {self.write_command()}"
        self.assertDenied(self.run_hook(self.payload(command)), "alone")

    def test_extra_words_a_missing_option_and_a_repeated_option_are_denied(self):
        base = f"python3 -I {self.script} write {self.repo}"
        for command in (self.write_command(tail=" extra"), f"{base} --proposal {self.proposal}",
                        f"{base} --confirm {DIGEST}", f"{base}",
                        f"{base} --proposal {self.proposal} --proposal {self.proposal} --confirm {DIGEST}",
                        f"{base} --proposal {self.proposal} --confirm {DIGEST} --confirm {DIGEST}",
                        f"python3 -I -u {self.script} write {self.repo} --proposal {self.proposal} --confirm {DIGEST}",
                        f"echo python3 {self.script} write {self.repo} --proposal {self.proposal} --confirm {DIGEST}"):
            with self.subTest(command):
                self.assertDenied(self.run_hook(self.payload(command)))
        self.assertIsNone(self.ran())

    def test_a_command_that_holds_the_script_name_and_write_in_its_text_but_is_not_the_exact_form_is_denied(self):
        # The hook replaces the ask rule of ticket 509, which matched the raw text, so it denies what that text matched.
        inner = f"python3 {self.script} write {self.repo} --proposal {self.proposal} --confirm {DIGEST}"
        for command in (f"sh -c '{inner}'", f'bash -c "{inner}"', f"echo {self.script} write",
                        f'grep -n "{self.script} write" setup.md', f"cat '{self.script}\twrite'",
                        f"git commit -m 'run setup_files.py write later'",
                        # the removed rule glob ended with a star, so write_x and writex matched it
                        f"python3 {self.script} write_x {self.repo}", f"python3 {self.script} writex {self.repo}"):
            with self.subTest(command):
                self.assertDenied(self.run_hook(self.payload(command)), "alone")
        self.assertIsNone(self.ran())

    def test_a_tab_or_two_spaces_between_the_script_and_write_is_denied_and_the_plan_does_not_run(self):
        for separator in ("\t", "  ", " \t"):
            command = f"python3 {self.script}{separator}write {self.repo} --proposal {self.proposal} --confirm {DIGEST}"
            with self.subTest(repr(separator)):
                self.assertDenied(self.run_hook(self.payload(command)), "alone")
        self.assertIsNone(self.ran())

    def test_a_command_with_more_than_one_line_that_calls_write_is_denied(self):
        command = self.write_command()
        for text in (f"{command}\necho x", f"echo x\n{command}", f"python3 -I {self.script}\nwrite {self.repo} "
                     f"--proposal {self.proposal} --confirm {DIGEST}", f"{command}\r\necho x"):
            with self.subTest(text):
                self.assertDenied(self.run_hook(self.payload(text)), "one line")
        self.assertIsNone(self.ran())


class PassTest(HookCase):
    def test_a_plan_call_passes_with_no_output_and_does_not_run_the_plan(self):
        command = f"python3 -I {self.script} plan {self.repo} --proposal {self.proposal}"
        self.assertPasses(self.run_hook(self.payload(command)))
        self.assertIsNone(self.ran())

    def test_a_proposal_file_called_write_json_in_a_plan_call_passes(self):
        command = f"python3 {self.script} plan {self.repo} --proposal /tmp/write.json"
        self.assertPasses(self.run_hook(self.payload(command)))

    def test_services_and_other_setup_calls_pass(self):
        self.assertPasses(self.run_hook(self.payload(f"python3 {self.script} services app-dev")))
        self.assertPasses(self.run_hook(self.payload(f"python3 {self.script} plan {self.repo} --proposal /tmp/p.json | head -5")))

    def test_commands_without_the_script_pass_even_with_unbalanced_quotes(self):
        for command in ("ls -la", "git status", "echo 'unclosed", "python3 other.py write x"):
            with self.subTest(command):
                self.assertPasses(self.run_hook(self.payload(command)))

    def test_a_non_bash_tool_passes_with_no_output(self):
        for tool in ("Read", "Write", "Grep"):
            with self.subTest(tool):
                self.assertPasses(self.run_hook(self.payload(self.write_command(), tool=tool)))

    def test_a_payload_without_a_tool_name_passes(self):
        self.assertPasses(self.run_hook({"hook_event_name": "PreToolUse"}))


class RunLogTest(HookCase):
    def log_lines(self, path):
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle.read().splitlines()]

    def test_every_ask_and_deny_is_one_line_in_the_log_and_a_pass_is_none(self):
        log = os.path.join(self.root, "hook.log")
        env = {"SETUP_DIFF_PROMPT_LOG": log}
        self.run_hook(self.payload(self.write_command()), env=env)
        self.run_hook(self.payload(self.write_command(digest="old")), env=env)
        self.run_hook(raw="not json", env=env)
        self.run_hook(self.payload("ls"), env=env)
        lines = self.log_lines(log)
        self.assertEqual([line["decision"] for line in lines], ["ask", "deny", "deny"])
        self.assertTrue(lines[0]["reason"].startswith("Diff to confirm:"))
        self.assertTrue(lines[1]["reason"].startswith("Setup write check:"))

    def test_a_log_path_that_cannot_be_written_does_not_change_the_decision(self):
        env = {"SETUP_DIFF_PROMPT_LOG": os.path.join(self.root, "no-such-folder", "hook.log")}
        output = self.run_hook(self.payload(self.write_command()), env=env)
        self.assertEqual(self.decision(output)[0], "ask")

    def test_nothing_is_written_when_the_variable_is_unset(self):
        self.run_hook(self.payload(self.write_command()), env={"SETUP_DIFF_PROMPT_LOG": ""})
        self.assertEqual(os.listdir(self.root).count("hook.log"), 0)


REPO = os.path.dirname(os.path.dirname(HERE))


class StructureTest(unittest.TestCase):
    def settings(self):
        with open(os.path.join(REPO, "settings.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def hook_commands(self):
        return [(group, entry) for group in self.settings()["hooks"]["PreToolUse"] for entry in group["hooks"]
                if "setup_diff_prompt.py" in entry["command"]]

    def test_settings_json_has_exactly_one_command_for_the_hook_in_the_bash_group_of_the_subagent_guard(self):
        found = self.hook_commands()
        self.assertEqual(len(found), 1, found)
        group, entry = found[0]
        self.assertEqual(group["matcher"], "Bash")
        self.assertTrue(any("block_subagent_writes.py" in other["command"] for other in group["hooks"]))
        self.assertEqual(entry["type"], "command")
        self.assertEqual(entry["command"], "python3 -I ~/.claude/hooks/setup-diff-prompt/setup_diff_prompt.py")
        self.assertEqual(entry["onFailure"], "block")

    def test_the_entry_timeout_is_above_the_plan_limit(self):
        self.assertGreater(self.hook_commands()[0][1]["timeout"], load_module().PLAN_SECONDS)

    def test_no_permission_ask_rule_names_the_setup_write_call_because_the_hook_replaces_it(self):
        # When a permission ask rule and the hook both ask, Claude Code shows the text of the rule and drops the hook reason,
        # so the diff never reaches the prompt (owner decision "1: hook replaces rule", ticket 520).
        ask = self.settings().get("permissions", {}).get("ask", [])
        self.assertEqual([rule for rule in ask if "setup_files.py" in rule], [])

    def test_the_declared_test_command_lists_the_hook_folder(self):
        with open(os.path.join(REPO, ".claude", "CLAUDE.md"), encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("'hooks/setup-diff-prompt'", text)

    def test_git_does_not_ignore_the_hook_files(self):
        for name in ("setup_diff_prompt.py", "test_setup_diff_prompt.py"):
            path = os.path.join("hooks", "setup-diff-prompt", name)
            done = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO, capture_output=True)
            self.assertEqual(done.returncode, 1, path + " is ignored by .gitignore")

    def test_the_root_readme_table_has_a_row_for_the_hook_folder(self):
        with open(os.path.join(REPO, "README.md"), encoding="utf-8") as handle:
            self.assertIn("| `hooks/setup-diff-prompt/*.py` |", handle.read())


if __name__ == "__main__":
    unittest.main()
