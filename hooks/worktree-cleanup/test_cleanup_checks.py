import os
import subprocess
import tempfile
import unittest

from cleanup_support import CLEANUP, CleanupCase, HANDLE, git


class UsageTest(CleanupCase):
    def assert_usage_error(self, result):
        self.assertEqual(result.returncode, 1)
        self.assertTrue(self.starts(result, "Usage"))
        self.assertEqual(self.calls(), [])

    def test_no_path(self):
        self.assert_usage_error(self.run_cleanup())

    def test_two_paths(self):
        self.assert_usage_error(self.run_cleanup(self.wt, self.wt))

    def test_unknown_flag(self):
        self.assert_usage_error(self.run_cleanup("--force", self.wt))

    def test_invalid_wait_variables(self):
        for value in ("abc", "0", "-1"):
            with self.subTest(value):
                self.assert_usage_error(self.run_cleanup(self.wt, wait_interval=value))
                self.assert_usage_error(self.run_cleanup(self.wt, wait_limit=value))


class TargetTest(CleanupCase):
    def assert_target_only(self, result):
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(self.starts(result, "Target")), 1)
        for other in ("Ownership", "Clean", "Merged"):
            self.assertFalse(self.starts(result, other), other)
        self.assert_unchanged()

    def test_a_path_that_is_not_a_repo(self):
        plain = tempfile.mkdtemp(dir=self.root)
        result = self.run_cleanup(plain)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(self.starts(result, "Target"))

    def test_a_missing_path(self):
        result = self.run_cleanup(os.path.join(self.root, "missing"))
        self.assertEqual(result.returncode, 1)
        self.assertTrue(self.starts(result, "Target"))

    def test_the_main_checkout(self):
        self.assert_target_only(self.run_cleanup(self.main))

    def test_a_subfolder_of_a_worktree(self):
        os.mkdir(os.path.join(self.wt, "sub"))
        self.assert_target_only(self.run_cleanup(os.path.join(self.wt, "sub")))

    def test_a_detached_head(self):
        git("checkout", "-q", "--detach", cwd=self.wt, env=self.env)
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(self.starts(result, "Target")), 1)
        self.assertFalse(self.starts(result, "Clean"))

    def test_orca_does_not_know_the_worktree(self):
        self.stub_show(ok=False, rc=1)
        self.assert_target_only(self.run_cleanup(self.wt))

    def test_orca_answers_ok_false(self):
        self.stub_show(ok=False, rc=0)
        self.assert_target_only(self.run_cleanup(self.wt))

    def test_skip_ownership_does_not_skip_the_target_check(self):
        self.assert_target_only(self.run_cleanup("--skip-ownership", self.main))


class OwnershipTest(CleanupCase):
    def assert_refused(self, result):
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(self.starts(result, "Ownership")), 1)
        self.assertIn(f"! ~/.claude/hooks/worktree-cleanup/cleanup --skip-ownership {self.wt}", self.lines(result))
        self.assert_unchanged()

    def test_the_target_is_the_anchor_worktree(self):
        self.stub_terminal(self.wt_id)
        self.assertEqual(self.run_cleanup(self.wt).returncode, 0)

    def test_the_parent_is_the_anchor_worktree(self):
        self.stub_show(parent=self.anchor_id)
        self.assertEqual(self.run_cleanup(self.wt).returncode, 0)

    def test_the_caller_terminal_created_it(self):
        self.stub_show(caller=HANDLE)
        self.assertEqual(self.run_cleanup(self.wt).returncode, 0)

    def test_no_proof(self):
        self.stub_show(parent="other-id", caller="term_other")
        self.assert_refused(self.run_cleanup(self.wt))

    def test_absent_parent_and_provenance_give_no_proof(self):
        self.stub_show()
        self.assert_refused(self.run_cleanup(self.wt))

    def test_a_failed_terminal_show_is_no_proof_even_for_a_matching_parent(self):
        self.stub_show(parent=self.anchor_id)
        self.stub_terminal(self.anchor_id, rc=1)
        self.assert_refused(self.run_cleanup(self.wt))

    def test_an_empty_handle_is_no_proof_even_for_an_empty_caller(self):
        self.stub_show(parent=self.anchor_id, caller="")
        self.assert_refused(self.run_cleanup(self.wt, handle=""))

    def test_a_missing_handle_is_no_proof(self):
        self.assert_refused(self.run_cleanup(self.wt, handle=None))

    def test_the_cwd_is_never_a_proof(self):
        self.stub_show(parent="other-id")
        env = dict(self.env, PATH=self.bin + os.pathsep + os.environ["PATH"], STUB_DIR=self.stub_dir,
                   ORCA_TERMINAL_HANDLE=HANDLE)
        result = subprocess.run([CLEANUP, self.wt], cwd=self.wt, capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(self.starts(result, "Ownership"))

    def test_skip_ownership_skips_only_that_check(self):
        self.stub_show()
        with open(os.path.join(self.wt, "dirty.txt"), "w") as f:
            f.write("x")
        result = self.run_cleanup("--skip-ownership", self.wt)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.starts(result, "Ownership"))
        self.assertEqual(len(self.starts(result, "Clean")), 1)

    def test_skip_ownership_lets_a_clean_merged_worktree_through(self):
        self.stub_show()
        self.assertEqual(self.run_cleanup("--skip-ownership", self.wt).returncode, 0)


class CleanTest(CleanupCase):
    def test_a_clean_worktree_passes(self):
        self.assertEqual(self.run_cleanup(self.wt).returncode, 0)

    def test_an_untracked_file_refuses(self):
        with open(os.path.join(self.wt, "new.txt"), "w") as f:
            f.write("x")
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(self.starts(result, "Clean")), 1)
        self.assert_unchanged()

    def test_a_modified_file_refuses(self):
        with open(os.path.join(self.wt, "work.txt"), "w") as f:
            f.write("changed")
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(self.starts(result, "Clean")), 1)

    def test_an_ignored_file_passes(self):
        with open(os.path.join(self.main, ".git", "info", "exclude"), "a") as f:
            f.write("ignored.txt\n")
        with open(os.path.join(self.wt, "ignored.txt"), "w") as f:
            f.write("x")
        self.assertEqual(self.run_cleanup(self.wt).returncode, 0)


class MergedTest(CleanupCase):
    def assert_merged_refusal(self, result):
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(self.starts(result, "Merged")), 1)
        self.assert_unchanged()

    def test_a_merged_pr_at_the_tip_passes(self):
        self.assertEqual(self.run_cleanup(self.wt).returncode, 0)

    def test_no_merged_pr(self):
        self.stub_gh_merged(prs=[])
        self.assert_merged_refusal(self.run_cleanup(self.wt))

    def test_a_merged_pr_at_another_commit(self):
        self.stub_gh_merged(prs=[{"number": 7, "headRefOid": "0" * 40, "baseRefName": "main"}])
        self.assert_merged_refusal(self.run_cleanup(self.wt))

    def test_a_failed_gh_call(self):
        self.stub_gh_merged(rc=1)
        self.assert_merged_refusal(self.run_cleanup(self.wt))

    def test_garbage_from_gh(self):
        self.stub("gh pr list", "not json")
        self.assert_merged_refusal(self.run_cleanup(self.wt))

    def test_a_failed_default_branch_lookup(self):
        self.stub("gh repo view", rc=1)
        self.assert_merged_refusal(self.run_cleanup(self.wt))

    def test_matching_prs_with_different_bases(self):
        self.stub_gh_merged(prs=[{"number": 7, "headRefOid": self.tip, "baseRefName": "main"},
                                 {"number": 8, "headRefOid": self.tip, "baseRefName": "develop"}])
        self.assert_merged_refusal(self.run_cleanup(self.wt))

    def test_matching_prs_with_one_base_pass(self):
        self.stub_gh_merged(prs=[{"number": 7, "headRefOid": self.tip, "baseRefName": "main"},
                                 {"number": 8, "headRefOid": self.tip, "baseRefName": "main"},
                                 {"number": 9, "headRefOid": "0" * 40, "baseRefName": "develop"}])
        self.assertEqual(self.run_cleanup(self.wt).returncode, 0)


class RefusalTest(CleanupCase):
    def test_a_refusal_lists_every_failed_check_and_changes_nothing(self):
        with open(os.path.join(self.wt, "new.txt"), "w") as f:
            f.write("x")
        self.stub_show()
        self.stub_gh_merged(prs=[])
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 1)
        for marker in ("Ownership", "Clean", "Merged"):
            self.assertEqual(len(self.starts(result, marker)), 1, marker)
        self.assertFalse(self.starts(result, "Target"))
        self.assert_unchanged()
        self.assertEqual(os.listdir(self.wt).count("new.txt"), 1)


if __name__ == "__main__":
    unittest.main()
