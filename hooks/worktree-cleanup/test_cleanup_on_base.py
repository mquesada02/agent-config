# Check 5 passes a clean branch whose tip is already on origin/<base>, with no merged PR (#300).
import os
import unittest

from cleanup_support import CleanupCase, git


class OnBaseTest(CleanupCase):
    def setUp(self):
        super().setUp()
        self.stub_gh_merged(prs=[])

    def move_branch_to(self, sha, keep_remote=False):
        """Point the worktree branch at `sha`, then drop its remote branch unless `keep_remote`."""
        git("reset", "-q", "--hard", sha, cwd=self.wt, env=self.env)
        self.tip = sha
        if keep_remote:
            git("push", "-q", "-f", "origin", f"HEAD:refs/heads/{self.BRANCH}", cwd=self.wt, env=self.env)
        else:
            git("push", "-q", "origin", "--delete", self.BRANCH, cwd=self.main, env=self.env)

    def main_tip(self):
        return self.git_out(self.main, "rev-parse", "origin/main")

    def assert_removed(self, result, base="main"):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(os.path.isdir(self.wt))
        self.assertFalse(self.local_has(self.BRANCH))
        self.assertFalse(self.remote_has(self.BRANCH))
        self.assertEqual(self.git_out(self.main, "branch", "--show-current"), base)

    def test_a_tip_equal_to_the_base_tip_with_no_pr_and_no_remote_branch_is_removed(self):
        self.move_branch_to(self.main_tip())
        result = self.run_cleanup(self.wt)
        self.assert_removed(result)
        self.assertFalse(self.starts(result, "Merged"))
        self.assertFalse(self.starts(result, "Pushed"))

    def test_a_tip_that_is_an_older_base_commit_is_removed(self):
        old = self.main_tip()
        self.commit(self.main, "later.txt")
        git("push", "-q", "origin", "main", cwd=self.main, env=self.env)
        self.move_branch_to(old)
        self.assert_removed(self.run_cleanup(self.wt))

    def test_a_branch_with_one_commit_beyond_the_base_is_refused(self):
        git("push", "-q", "origin", "--delete", self.BRANCH, cwd=self.main, env=self.env)
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not on origin/main", self.starts(result, "Merged")[0])
        self.assertTrue(os.path.isdir(self.wt))
        self.assertTrue(self.local_has(self.BRANCH))
        self.assertEqual(self.rm_calls(), [])

    def test_the_base_is_fetched_before_the_comparison(self):
        other = os.path.join(self.root, "other")
        git("clone", "-q", self.remote, other, env=self.env)
        self.commit(other, "remote-only.txt")
        git("push", "-q", "origin", "main", cwd=other, env=self.env)
        new_tip = self.git_out(other, "rev-parse", "HEAD")
        git("fetch", "-q", self.remote, "main", cwd=self.wt, env=self.env)
        self.assertNotEqual(self.main_tip(), new_tip)
        self.move_branch_to(new_tip)
        self.assert_removed(self.run_cleanup(self.wt))

    def test_a_remote_branch_at_the_tip_is_deleted(self):
        self.move_branch_to(self.main_tip(), keep_remote=True)
        self.assert_removed(self.run_cleanup(self.wt))

    def test_a_remote_branch_at_another_sha_is_refused(self):
        self.move_branch_to(self.main_tip(), keep_remote=True)
        git("checkout", "-q", "-b", "side", cwd=self.main, env=self.env)
        self.commit(self.main, "side.txt")
        git("push", "-q", "-f", "origin", f"HEAD:refs/heads/{self.BRANCH}", cwd=self.main, env=self.env)
        git("checkout", "-q", "main", cwd=self.main, env=self.env)
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(self.starts(result, "Pushed")), 1)
        self.assertTrue(os.path.isdir(self.wt))

    def test_an_unclean_worktree_on_the_base_is_still_refused(self):
        self.move_branch_to(self.main_tip())
        with open(os.path.join(self.wt, "new.txt"), "w") as f:
            f.write("x")
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(self.starts(result, "Clean")), 1)
        self.assertTrue(os.path.isdir(self.wt))

    def test_a_named_base_is_used_for_the_comparison_and_the_switch(self):
        git("checkout", "-q", "-b", "develop", cwd=self.main, env=self.env)
        self.commit(self.main, "develop.txt")
        git("push", "-q", "-u", "origin", "develop", cwd=self.main, env=self.env)
        git("checkout", "-q", "main", cwd=self.main, env=self.env)
        self.move_branch_to(self.git_out(self.main, "rev-parse", "develop"))
        refused = self.run_cleanup(self.wt)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("not on origin/main", self.starts(refused, "Merged")[0])
        self.assert_removed(self.run_cleanup("--base", "develop", self.wt), base="develop")

    def test_a_named_base_that_is_absent_on_origin_is_refused(self):
        self.move_branch_to(self.main_tip())
        result = self.run_cleanup("--base", "missing", self.wt)
        self.assertEqual(result.returncode, 1)
        self.assertIn("origin/missing", self.starts(result, "Merged")[0])
        self.assertTrue(os.path.isdir(self.wt))

    def test_a_merged_pr_wins_over_a_named_base(self):
        self.stub_gh_merged()
        result = self.run_cleanup("--base", "develop", self.wt)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git_out(self.main, "branch", "--show-current"), "main")

    def test_a_base_flag_without_a_value_is_a_usage_error(self):
        for args in (("--base",), (self.wt, "--base"), ("--base", "--skip-ownership", self.wt)):
            with self.subTest(args=args):
                result = self.run_cleanup(*args)
                self.assertEqual(result.returncode, 1)
                self.assertTrue(self.starts(result, "Usage"))
                self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
