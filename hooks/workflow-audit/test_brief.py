import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from audit_support import HERE, AuditCase

BRIEF = os.path.join(HERE, "auditor-brief.md")
GITIGNORE = os.path.join(HERE, "..", "..", ".gitignore")
AUDIT_PATH = "~/.claude/hooks/workflow-audit/audit"


def read_brief():
    with open(BRIEF, encoding="utf-8") as handle:
        return handle.read()


class BriefTextTest(unittest.TestCase):
    def setUp(self):
        self.text = read_brief()

    def test_defines_the_six_items(self):
        for name in ("L1", "L2", "L3", "L4", "L5", "L6"):
            with self.subTest(name):
                self.assertRegex(self.text, rf"\*\*{name}\.\*\* ")

    def test_l1_quotes_the_section_6_evidence_rules(self):
        for phrase in ("section 6 of `~/.claude/CLAUDE.md`", "A spec mismatch needs the quoted spec line", "always Blocking",
                       "the quoted code and the section 0 rule", "an input or state and the wrong result", "A finding without its evidence is Minor"):
            with self.subTest(phrase):
                self.assertIn(phrase, self.text)

    def test_names_the_three_inputs_including_the_done_report(self):
        self.assertIn("The path of the session's draft done report", self.text)
        self.assertIn("The worktree path", self.text)
        self.assertIn("The path where you write the verdict file", self.text)

    def test_gives_the_literal_command_lines(self):
        self.assertIn(f"python3 -I {AUDIT_PATH} check --worktree <worktree>", self.text)
        self.assertIn(f"python3 -I {AUDIT_PATH} record --worktree <worktree> --llm <verdict file>", self.text)

    def test_the_first_step_is_the_push_check(self):
        steps = self.text.split("## Steps", 1)[1].split("## The six items", 1)[0]
        first = steps.strip().splitlines()[0]
        self.assertIn("pushed", first)
        self.assertIn("push first", first)

    def test_bans_fixing_and_s_input(self):
        self.assertIn("You never fix anything", self.text)
        self.assertIn("you do not write S results", self.text)
        self.assertIn("It never takes S results from you", self.text)

    def test_describes_the_format_and_missing_evidence(self):
        for phrase in ("exactly the keys `L1` to `L6`", "`result` (`pass` or `fail`)", "at most 4000 characters", "evidence unavailable"):
            with self.subTest(phrase):
                self.assertIn(phrase, self.text)

    def test_is_not_ignored_by_the_allow_list(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        shutil.copy(GITIGNORE, os.path.join(root, ".gitignore"))
        env = {"PATH": os.environ["PATH"], "HOME": root}
        subprocess.run(["git", "init", "-q", root], check=True, env=env)
        result = subprocess.run(["git", "-C", root, "check-ignore", "-q", "hooks/workflow-audit/auditor-brief.md"], env=env)
        self.assertEqual(result.returncode, 1)


class BriefExampleTest(AuditCase):
    def test_the_example_verdict_is_accepted_by_record(self):
        blocks = re.findall(r"```json\n(.*?)\n```", read_brief(), re.DOTALL)
        self.assertTrue(blocks)
        json.loads(blocks[0])
        self.write_llm(blocks[0])
        self.start_branch("feature", "feat: a")
        result = self.record()
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
