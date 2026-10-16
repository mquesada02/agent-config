import os
import re
import unittest

from audit_support import HERE, AuditCase

SKILL = os.path.join(HERE, "..", "..", "skills", "smart-commits", "SKILL.md")


def skill_types():
    with open(SKILL, encoding="utf-8") as handle:
        text = handle.read()
    table = text.split("**Types:**", 1)[1].split("**Scope:**", 1)[0]
    return re.findall(r"^\| `(\w+)` \|", table, re.MULTILINE)


class S8Test(AuditCase):
    def s8(self):
        """Run record on the current branch and return (passed, evidence) of its S8 item."""
        result = self.record()
        self.assertIn(result.returncode, (0, 1), result.stderr)
        tip = self.git("rev-parse", "HEAD")
        item = self.item(tip, "S8")
        self.assertEqual(item["id"], "S8")
        return item["result"] == "pass", item["evidence"]

    def assert_s8(self, message, expected):
        self.git("checkout", "-B", "work", "main")
        self.commit(message)
        self.git("push", "-f", "-u", "origin", "work")
        passed, evidence = self.s8()
        self.assertEqual(passed, expected, f"{message!r}: {evidence}")

    def test_every_type_in_the_smart_commits_skill_passes(self):
        types = skill_types()
        self.assertEqual(len(types), 10)
        for kind in types:
            with self.subTest(kind):
                self.assert_s8(f"{kind}: do a thing", True)

    def test_header_forms(self):
        for message in ("feat: a", "feat(audit): a", "feat!: a", "feat(audit)!: a", "fix(claude-md): a", "chore(a.b_c/d-e): a",
                        "feat: a\n\nbody text that mentions claude in running text\nand a scope claude-md"):
            with self.subTest(message=message):
                self.assert_s8(message, True)

    def test_bad_headers_fail(self):
        for message in ("wip: a", "revert: a", "Feat: a", "feat a", "feat:a", "feat: ", "feat(): a", "feat(a b): a", "feat(a)(b): a",
                        "no type at all", "Merge branch 'x'", "feat !: a", "feat(a)!!: a"):
            with self.subTest(message=message):
                self.assert_s8(message, False)

    def test_attribution_fails(self):
        for message in (
            "feat: a\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
            "feat: a\n\nco-authored-by: Someone Human <h@example.com>",
            "feat: a\n\nSigned-off-by: Claude",
            "feat: a\n\nGenerated-By: anthropic tools",
            "feat: a\n\nAssisted-by: Claude Code",
            "feat: a\n\nbody\n\n\U0001F916 Generated with [Claude Code](https://claude.com/claude-code)",
            "feat: a\n\nGenerated with Claude Code",
            "feat: a\n\n  \U0001F916 done",
            "feat: a\n\nMade-by: noreply@anthropic.com",
        ):
            with self.subTest(message=message):
                self.assert_s8(message, False)

    def test_a_human_signoff_is_not_attribution(self):
        self.assert_s8("feat: a\n\nSigned-off-by: A Human <h@example.com>", True)

    def test_the_failing_commit_is_named_in_the_evidence(self):
        self.git("checkout", "-b", "work")
        good = self.commit("feat: good")
        bad = self.commit("oops")
        self.git("push", "-u", "origin", "work")
        passed, evidence = self.s8()
        self.assertFalse(passed)
        self.assertIn(bad[:7], evidence)
        self.assertNotIn(good[:7], evidence)

    def test_many_failures_are_cut_to_ten_lines(self):
        self.git("checkout", "-b", "work")
        for number in range(12):
            self.commit(f"bad {number}")
        self.git("push", "-u", "origin", "work")
        passed, evidence = self.s8()
        self.assertFalse(passed)
        self.assertEqual(len(evidence.splitlines()), 11)
        self.assertIn("and 2 more", evidence)

    def test_a_merge_commit_in_the_range_is_checked_like_any_other(self):
        self.git("checkout", "-b", "work")
        self.commit("feat: on work", name="work.txt")
        self.git("checkout", "main")
        self.commit("feat: on main", name="main.txt")
        self.git("push", "origin", "main")
        self.git("checkout", "work")
        self.git("merge", "--no-ff", "-m", "Merge branch 'main' into work", "main")
        self.git("push", "-u", "origin", "work")
        passed, evidence = self.s8()
        self.assertFalse(passed)
        self.assertIn("Merge branch", evidence)

    def test_head_on_the_default_branch_has_zero_commits_and_passes(self):
        self.commit("old bad commit")
        self.git("push", "origin", "main")
        passed, evidence = self.s8()
        self.assertTrue(passed, evidence)
        self.assertIn("0 commits", evidence)

    def test_origin_head_wins_over_origin_main(self):
        # develop holds a bad commit. Against origin/main the range would hold it; against origin/HEAD (develop) it does not.
        self.git("checkout", "-b", "develop")
        self.commit("bad develop commit")
        self.git("push", "-u", "origin", "develop")
        self.git("remote", "set-head", "origin", "develop")
        self.start_branch("work", "feat: fine")
        passed, evidence = self.s8()
        self.assertTrue(passed, evidence)
        self.assertIn("1 commits", evidence)

    def test_origin_main_is_used_when_there_is_no_origin_head(self):
        self.git("checkout", "-b", "develop")
        self.commit("bad develop commit")
        self.git("push", "-u", "origin", "develop")
        self.start_branch("work", "feat: fine")
        passed, evidence = self.s8()
        self.assertFalse(passed)
        self.assertIn("bad develop commit", evidence)

    def test_origin_master_is_the_last_resort(self):
        self.git("branch", "-m", "main", "master")
        self.git("push", "origin", "master")
        self.git("symbolic-ref", "HEAD", "refs/heads/master", cwd=self.origin)
        self.git("push", "origin", "--delete", "main")
        self.git("fetch", "--prune", "origin")
        self.assertEqual(self.git("branch", "-r", "--list", "origin/main"), "")
        self.start_branch("work", "oops")
        passed, evidence = self.s8()
        self.assertFalse(passed)
        self.assertIn("oops", evidence)

    def test_no_default_branch_is_evidence_unavailable(self):
        self.start_branch("work", "feat: fine")
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        passed, evidence = self.s8()
        self.assertFalse(passed)
        self.assertTrue(evidence.startswith("evidence unavailable"), evidence)

    def test_no_merge_base_is_evidence_unavailable(self):
        self.git("checkout", "--orphan", "island")
        self.commit("feat: unrelated history")
        self.git("push", "-u", "origin", "island")
        passed, evidence = self.s8()
        self.assertFalse(passed)
        self.assertTrue(evidence.startswith("evidence unavailable"), evidence)


if __name__ == "__main__":
    unittest.main()
