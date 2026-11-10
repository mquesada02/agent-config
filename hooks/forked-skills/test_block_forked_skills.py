import json
import os
import subprocess
import sys
import unittest

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "block_forked_skills.py")
sys.path.insert(0, os.path.dirname(HOOK))
from block_forked_skills import FORKED_BUILTIN_SKILLS  # noqa: E402


def run(stdin_text):
    return subprocess.run([sys.executable, "-I", HOOK], input=stdin_text, capture_output=True, text=True)


def skill_call(name):
    return json.dumps({"tool_name": "Skill", "tool_input": {"skill": name}})


class BlockForkedSkillsTest(unittest.TestCase):
    def test_each_listed_forked_skill_is_denied_with_the_message(self):
        self.assertTrue(FORKED_BUILTIN_SKILLS)
        for name in FORKED_BUILTIN_SKILLS:
            with self.subTest(skill=name):
                result = run(skill_call(name))
                self.assertEqual(result.returncode, 2)
                self.assertIn(f"'{name}'", result.stderr)
                self.assertIn("parent session's model", result.stderr)
                self.assertIn("S7", result.stderr)
                self.assertIn("every worktree that this session touches", result.stderr)
                self.assertIn("separate session", result.stderr)

    def test_a_leading_slash_or_spacing_is_still_denied(self):
        for variant in ("/{}", " {}", "{} ", " /{} ", "/ {}"):
            with self.subTest(variant=variant):
                self.assertEqual(run(skill_call(variant.format(FORKED_BUILTIN_SKILLS[0]))).returncode, 2)

    def test_the_plugin_skill_with_the_same_base_name_is_allowed(self):
        self.assertEqual(run(skill_call("mattpocock-skills:code-review")).returncode, 0)

    def test_other_skills_are_allowed(self):
        for name in ("smart-commits", "simplify", "plan-review", "ci-pipelines"):
            with self.subTest(skill=name):
                result = run(skill_call(name))
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stderr, "")

    def test_a_skill_call_whose_name_cannot_be_read_is_denied(self):
        for stdin_text in ("", "not json", "[]", "{}", json.dumps({"tool_name": "Skill"}),
                           json.dumps({"tool_name": "Skill", "tool_input": {}}),
                           json.dumps({"tool_name": "Skill", "tool_input": {"skill": None}}),
                           json.dumps({"tool_name": "Skill", "tool_input": {"skill": 5}})):
            with self.subTest(stdin=stdin_text):
                result = run(stdin_text)
                self.assertEqual(result.returncode, 2)
                self.assertIn("cannot read the skill name", result.stderr)


if __name__ == "__main__":
    unittest.main()
