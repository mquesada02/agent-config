# Check 5 passes a branch whose work reached the base without a merged PR at its tip (#787):
# a merged PR whose head contains the tip (a squash-merged coordinator PR), or files already equal on the base.
import json
import os
import unittest

from cleanup_support import CleanupCase, git


class SquashTest(CleanupCase):
    def setUp(self):
        super().setUp()
        self.stub_gh_merged(prs=[])

    def search_key(self):
        return f"gh pr list --state merged --search {self.tip} --json number,headRefOid,baseRefName"

    def stub_search(self, prs):
        self.stub(self.search_key(), json.dumps(prs))

    def coordinator_head(self, number):
        """A coordinator commit on top of the tip, pushed as the pull ref of PR `number`; main gets a squash commit."""
        git("checkout", "-q", "-b", "coord", self.tip, cwd=self.main, env=self.env)
        self.commit(self.main, "coord.txt")
        head = self.git_out(self.main, "rev-parse", "HEAD")
        git("push", "-q", "origin", f"HEAD:refs/pull/{number}/head", cwd=self.main, env=self.env)
        git("checkout", "-q", "main", cwd=self.main, env=self.env)
        self.commit(self.main, "squash.txt")
        git("push", "-q", "origin", "main", cwd=self.main, env=self.env)
        return head

    def assert_refused(self, result, text):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(text, self.starts(result, "Merged")[0])
        self.assertTrue(os.path.isdir(self.wt))
        self.assertTrue(self.local_has(self.BRANCH))

    def test_a_tip_inside_a_merged_squashed_pr_is_removed(self):
        head = self.coordinator_head(9)
        self.stub_search([{"number": 9, "headRefOid": head, "baseRefName": "main"}])
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(os.path.isdir(self.wt))
        self.assertFalse(self.remote_has(self.BRANCH))
        self.assertEqual(self.git_out(self.main, "branch", "--show-current"), "main")

    def test_a_pr_whose_head_does_not_contain_the_tip_is_refused(self):
        self.coordinator_head(9)
        other = self.git_out(self.main, "rev-parse", "main")
        git("push", "-q", "-f", "origin", f"{other}:refs/pull/9/head", cwd=self.main, env=self.env)
        self.stub_search([{"number": 9, "headRefOid": other, "baseRefName": "main"}])
        self.assert_refused(self.run_cleanup(self.wt), "or contains it")

    def test_a_head_that_differs_from_the_pull_ref_is_refused(self):
        self.coordinator_head(9)
        self.stub_search([{"number": 9, "headRefOid": self.tip, "baseRefName": "main"}])
        self.assert_refused(self.run_cleanup(self.wt), "or contains it")

    def test_containing_prs_with_different_bases_are_refused(self):
        head = self.coordinator_head(9)
        git("push", "-q", "origin", f"{head}:refs/pull/10/head", cwd=self.main, env=self.env)
        self.stub_search([{"number": 9, "headRefOid": head, "baseRefName": "main"},
                          {"number": 10, "headRefOid": head, "baseRefName": "develop"}])
        self.assert_refused(self.run_cleanup(self.wt), "different base branches")

    def test_a_failed_search_is_named_in_the_refusal(self):
        self.stub(self.search_key(), "", rc=1, stderr="api down")
        self.assert_refused(self.run_cleanup(self.wt), "search for a merged PR that contains it failed")

    def test_a_branch_whose_files_are_equal_on_the_base_is_removed(self):
        self.commit(self.main, "earlier.txt")  # so the main commit of work.txt differs from the branch tip
        self.commit(self.main, "work.txt")
        self.assertNotEqual(self.git_out(self.main, "rev-parse", "HEAD"), self.tip)
        git("push", "-q", "origin", "main", cwd=self.main, env=self.env)
        self.stub_search([])
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(os.path.isdir(self.wt))

    def test_a_branch_with_no_net_change_is_removed(self):
        os.remove(os.path.join(self.wt, "work.txt"))
        git("commit", "-q", "-am", "revert work", cwd=self.wt, env=self.env)
        git("push", "-q", "origin", self.BRANCH, cwd=self.wt, env=self.env)
        self.tip = self.git_out(self.wt, "rev-parse", "HEAD")
        self.commit(self.main, "later.txt")
        git("push", "-q", "origin", "main", cwd=self.main, env=self.env)
        self.stub_search([])
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(os.path.isdir(self.wt))

    def test_a_branch_whose_files_differ_on_the_base_is_refused(self):
        with open(os.path.join(self.main, "work.txt"), "w") as f:
            f.write("other")
        git("add", "work.txt", cwd=self.main, env=self.env)
        git("commit", "-q", "-m", "other", cwd=self.main, env=self.env)
        git("push", "-q", "origin", "main", cwd=self.main, env=self.env)
        self.stub_search([])
        self.assert_refused(self.run_cleanup(self.wt), "not on origin/main")


if __name__ == "__main__":
    unittest.main()
