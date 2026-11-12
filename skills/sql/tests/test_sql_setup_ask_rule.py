import importlib.util
import json
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
REPO_DIR = os.path.dirname(os.path.dirname(SKILL_DIR))
SETUP_MD = os.path.join(SKILL_DIR, "setup.md")
README = os.path.join(SKILL_DIR, "evals", "README.md")

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


def repo_settings():
    with open(os.path.join(REPO_DIR, "settings.json"), encoding="utf-8") as handle:
        return json.load(handle)


def write_rule():
    ask = repo_settings().get("permissions", {}).get("ask", [])
    return [rule for rule in ask if "setup_files.py write" in rule]


def matches(rule, command):
    """A restatement of the Claude Code wildcard rule for a Bash rule: `*` is any text, the whole specifier must match.
    A compound command is split at `&&`, `||`, `;` and `|`, and the command is matched when one part matches.
    The real prompt behavior is proven by the prototype with a real `claude`, not by this test."""
    specifier = re.fullmatch(r"Bash\((.*)\)", rule, re.DOTALL).group(1)
    pattern = re.compile(".*".join(re.escape(piece) for piece in specifier.split("*")), re.DOTALL)
    return any(pattern.fullmatch(part.strip()) for part in re.split(r"&&|\|\||;|\|", command))


class AskRuleTest(unittest.TestCase):
    def test_settings_json_has_exactly_one_ask_rule_for_the_setup_write_call(self):
        self.assertEqual(len(write_rule()), 1, repo_settings().get("permissions"))

    def test_the_rule_matches_every_form_of_the_write_call(self):
        rule = write_rule()[0]
        for command in WRITE_CALLS:
            with self.subTest(command):
                self.assertTrue(matches(rule, command))

    def test_the_rule_does_not_match_plan_or_the_other_setup_calls(self):
        rule = write_rule()[0]
        for command in OTHER_CALLS:
            with self.subTest(command):
                self.assertFalse(matches(rule, command))

    def test_the_commands_of_setup_md_are_the_forms_that_the_tests_use(self):
        with open(SETUP_MD, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("python3 <skill folder>/scripts/setup_files.py write <repo root>", text)
        self.assertIn("python3 <skill folder>/scripts/setup_files.py plan <repo root>", text)
        rule = write_rule()[0]
        self.assertTrue(matches(rule, "python3 <skill folder>/scripts/setup_files.py write <repo root> --proposal <proposal file> --confirm <digest>"))
        self.assertFalse(matches(rule, "python3 <skill folder>/scripts/setup_files.py plan <repo root> --proposal <proposal file>"))


class RuleAndGraderAgreeTest(unittest.TestCase):
    """The ask rule of settings.json, the runner constant WRITE_SCRIPT (how the runner finds that rule) and grader D's
    WRITE_CALL (how a trace call is named a write call) are three spellings of one call: they must agree."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("run_setup_turns", os.path.join(SKILL_DIR, "evals", "turns", "run_setup_turns.py"))
        cls.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.runner)

    def test_the_rule_holds_the_script_text_that_the_runner_searches_for(self):
        self.assertIn(self.runner.WRITE_SCRIPT, write_rule()[0])

    def test_all_three_name_the_write_calls_and_none_of_the_other_calls(self):
        rule = write_rule()[0]
        for command in WRITE_CALLS:
            with self.subTest(command):
                self.assertIn(self.runner.WRITE_SCRIPT, command)
                self.assertTrue(self.runner.grade_setup.WRITE_CALL.search(command))
                self.assertTrue(matches(rule, command))
        for command in OTHER_CALLS:
            with self.subTest(command):
                self.assertNotIn(self.runner.WRITE_SCRIPT, command)
                self.assertFalse(self.runner.grade_setup.WRITE_CALL.search(command))
                self.assertFalse(matches(rule, command))


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

    def test_a_denial_that_starts_with_setup_write_check_is_not_a_decline(self):
        step = self.step_six()
        self.assertIn("Setup write check:", step)
        self.assertRegex(step, r"is not a decline")

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
    def test_the_two_turn_runner_section_names_the_ask_rule(self):
        with open(README, encoding="utf-8") as handle:
            text = handle.read()
        section = text.split("### Two-turn runner", 1)[1]
        section = re.split(r"\n#{2,3} ", section, maxsplit=1)[0]
        self.assertIn("permissions.ask", section)
        self.assertRegex(section, r"turn 1.*ask rule|ask rule.*turn 1")


if __name__ == "__main__":
    unittest.main()
