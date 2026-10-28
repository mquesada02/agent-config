# The whole audit flow of ticket #98 against fixtures: check, a canned verdict file, record, then the PR gate.
import os
import shutil
import unittest

from audit_support import HERE, AuditCase

PR = "gh pr create --title t --body b"
VERDICT = os.path.join(HERE, "fixtures", "l-verdict.json")


class FlowTest(AuditCase):
    def setUp(self):
        super().setUp()
        shutil.copy(VERDICT, self.llm_path)

    def test_a_passing_audit_opens_the_gate(self):
        tip = self.start_branch("feature", "feat(audit): add a thing")
        self.assertTrue(self.denial(self.gate(PR)).startswith("no record"))
        checked = self.audit("check", "--worktree", self.repo, "--base", "main")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        lines = checked.stdout.decode().splitlines()
        self.assertEqual([line for line in lines if line.endswith(" fail")], [])
        self.assertIn("result pass", lines)
        self.assertEqual(self.record_files(), [])  # check wrote no record
        recorded = self.record()
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        self.assertEqual(self.read_record(tip)["result"], "pass")
        self.assertIsNone(self.denial(self.gate(PR)))

    def test_a_failed_audit_is_recorded_and_the_gate_denies_it(self):
        tip = self.start_branch("feature", "feat: a thing\n\nCo-Authored-By: Someone <someone@example.com>")
        checked = self.audit("check", "--worktree", self.repo, "--base", "main")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("S8 fail", checked.stdout.decode().splitlines())
        recorded = self.record()
        self.assertEqual(recorded.returncode, 1, recorded.stderr)
        self.assertEqual(self.read_record(tip)["result"], "fail")
        self.assertEqual(self.item(tip, "S8")["result"], "fail")
        self.assertTrue(self.denial(self.gate(PR)).startswith("failed record"))


if __name__ == "__main__":
    unittest.main()
