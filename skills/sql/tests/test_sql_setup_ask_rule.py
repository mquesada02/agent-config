import importlib.util
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
REPO_DIR = os.path.dirname(os.path.dirname(SKILL_DIR))
SETUP_MD = os.path.join(SKILL_DIR, "setup.md")
README = os.path.join(SKILL_DIR, "evals", "README.md")
HOOK = os.path.join(REPO_DIR, "hooks", "setup-diff-prompt", "setup_diff_prompt.py")

SCRIPT = "/home/dev/.claude/skills/sql/scripts/setup_files.py"
WRITE_CALLS = [
    f"python3 {SCRIPT} write /repo --proposal /tmp/p.json --confirm abc123",
    f"python3 -I {SCRIPT} write /repo --proposal /tmp/p.json --confirm abc123",
    f"PGSERVICEFILE=/tmp/pg.conf python3 {SCRIPT} write /repo --proposal /tmp/p.json --confirm abc123",
    f"cd /repo && python3 {SCRIPT} plan /repo --proposal /tmp/p.json && python3 {SCRIPT} write /repo --proposal /tmp/p.json --confirm abc123",
]
OTHER_CALLS = [
    f"python3 {SCRIPT} plan /repo --proposal /tmp/p.json",
    f"python3 {SCRIPT} services app-dev",
    f"python3 {SCRIPT} plan /repo --proposal /tmp/p.json | head -5",
    "python3 /home/dev/.claude/skills/sql/scripts/formatter_install.py offer /repo",
    "python3 /home/dev/.claude/skills/sql/scripts/formatter_install.py apply /repo --confirm abc123",
    "python3 /home/dev/.claude/skills/sql/scripts/rules_file.py /repo",
]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HookCoversTheWriteCallTest(unittest.TestCase):
    """The setup diff hook replaced the permission ask rule of ticket 509 (a rule and a hook that both ask show only the rule
    text in the prompt, never the diff). Its raw text pattern RAW_WRITE is the old rule glob, so it must match every form of
    the write call and none of the other setup calls; grader D's WRITE_CALL names the same calls in a trace."""

    @classmethod
    def setUpClass(cls):
        cls.hook = load("setup_diff_prompt", HOOK)
        cls.runner = load("run_setup_turns", os.path.join(SKILL_DIR, "evals", "turns", "run_setup_turns.py"))

    def test_the_hook_text_pattern_matches_every_form_of_the_write_call(self):
        for command in WRITE_CALLS:
            with self.subTest(command):
                self.assertTrue(self.hook.RAW_WRITE.search(command))

    def test_the_hook_text_pattern_does_not_match_plan_or_the_other_setup_calls(self):
        for command in OTHER_CALLS:
            with self.subTest(command):
                self.assertFalse(self.hook.RAW_WRITE.search(command))

    def test_the_hook_text_pattern_and_grader_d_name_the_same_calls(self):
        for command in WRITE_CALLS:
            with self.subTest(command):
                self.assertTrue(self.runner.grade_setup.WRITE_CALL.search(command))
        for command in OTHER_CALLS:
            with self.subTest(command):
                self.assertFalse(self.runner.grade_setup.WRITE_CALL.search(command))

    def test_the_commands_of_setup_md_are_the_forms_that_the_tests_use(self):
        with open(SETUP_MD, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("python3 <skill folder>/scripts/setup_files.py write <repo root>", text)
        self.assertIn("python3 <skill folder>/scripts/setup_files.py plan <repo root>", text)
        self.assertTrue(self.hook.RAW_WRITE.search(
            "python3 <skill folder>/scripts/setup_files.py write <repo root> --proposal <proposal file> --confirm <digest>"))
        self.assertFalse(self.hook.RAW_WRITE.search(
            "python3 <skill folder>/scripts/setup_files.py plan <repo root> --proposal <proposal file>"))


class SetupMdStepSixTest(unittest.TestCase):
    def step_six(self):
        with open(SETUP_MD, encoding="utf-8") as handle:
            text = handle.read()
        return text.split("## Step 6: Write", 1)[1].split("## Step 7", 1)[0]

    def test_the_permission_prompt_is_the_confirmation(self):
        self.assertRegex(self.step_six(), r"permission prompt is the confirmation")

    def test_the_digest_rule_stays(self):
        step = self.step_six()
        self.assertIn("stale_digest", step)
        self.assertIn("--confirm <digest>", step)

    def test_no_diff_message_is_asked_of_the_model_anywhere_in_the_file(self):
        with open(SETUP_MD, encoding="utf-8") as handle:
            self.assertNotIn("Diff to confirm", handle.read())

    def test_the_hook_shows_the_diff_in_the_permission_prompt(self):
        step = self.step_six()
        self.assertRegex(step, r"(?s)hook.*permission prompt.*diff|diff.*permission prompt")
        self.assertRegex(step, r"you do not print the diff")

    def test_the_prompt_starts_with_a_summary_and_the_full_diff_file_path(self):
        step = self.step_six()
        self.assertRegex(step, r"(?s)starts with a summary.*Full diff")

    def test_a_denial_that_starts_with_setup_write_check_is_not_a_decline(self):
        step = self.step_six()
        self.assertIn("Setup write check:", step)
        self.assertRegex(step, r"is not a decline")

    def test_no_other_command_may_hold_the_script_name_followed_by_write(self):
        # the hook denies every command whose text holds them, not only a wrong write call (it replaced the ask rule)
        self.assertRegex(self.step_six(), r"(?s)script name followed by `write` in any other command.*hook denies it too")

    def test_the_repo_and_the_proposal_paths_are_absolute(self):
        self.assertRegex(self.step_six(), r"absolute path")

    def test_a_denied_write_call_stops_the_turn_with_no_other_route(self):
        step = self.step_six()
        self.assertRegex(step, r"(?i)denied or declined")
        self.assertIn("Do not write the files by any other route", step)
        self.assertRegex(step, r"later user message that confirms")

    def test_the_write_failed_fallback_does_not_apply_to_a_denied_call(self):
        self.assertRegex(self.step_six(), r"does not apply to a denied")

    def test_the_old_separate_confirmation_question_is_gone(self):
        self.assertNotIn("Then ask for the confirmation, once.", self.step_six())


class ReadmeTest(unittest.TestCase):
    def test_the_two_turn_runner_section_names_the_hook_as_the_only_gate_of_turn_1(self):
        with open(README, encoding="utf-8") as handle:
            text = handle.read()
        section = text.split("### Two-turn runner", 1)[1]
        section = re.split(r"\n#{2,3} ", section, maxsplit=1)[0]
        self.assertRegex(section, r"(?i)only gate")
        self.assertRegex(section, r"turn 1.*hook|hook.*turn 1")


if __name__ == "__main__":
    unittest.main()
