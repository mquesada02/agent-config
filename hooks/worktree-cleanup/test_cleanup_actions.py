import json
import os
import unittest

from cleanup_support import CleanupCase, git


class OtherTargetTest(CleanupCase):
    def test_full_success_runs_every_step_in_order(self):
        self.stub_rm_effect(delete_branch=False)
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        names = [line.split(":")[0] for line in self.lines(result) if line.split(":")[0] in
                 ("Remote branch", "Switch and pull", "Worktree", "Local branch")]
        self.assertEqual(names, ["Remote branch", "Switch and pull", "Worktree", "Local branch"])
        self.assertFalse(self.remote_has(self.BRANCH))
        self.assertFalse(self.local_has(self.BRANCH))
        self.assertFalse(os.path.exists(self.wt))
        self.assertEqual(self.git_out(self.main, "branch", "--show-current"), "main")
        self.assertFalse(self.starts(result, "Terminal closes"))

    def test_the_rm_call_forces_and_names_the_path(self):
        self.run_cleanup(self.wt)
        rm = [c for c in self.calls() if c.startswith("orca worktree rm")]
        self.assertEqual(len(rm), 1)
        self.assertIn(f"--worktree path:{self.wt}", rm[0])
        self.assertIn("--force", rm[0])

    def test_a_branch_that_orca_already_deleted_counts_as_done(self):
        self.stub_rm_effect(delete_branch=True)
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(self.starts(result, "Local branch"))
        self.assertIn("already gone", self.starts(result, "Local branch")[0])

    def test_it_waits_for_the_asynchronous_removal_before_the_branch_delete(self):
        self.stub_rm_effect(delay=0.4)
        result = self.run_cleanup(self.wt, wait_limit="5")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(os.path.exists(self.wt))
        self.assertFalse(self.local_has(self.BRANCH))

    def test_a_removal_that_never_finishes_times_out_with_exit_2(self):
        del self.config["rm_effect"]
        self.stub("orca worktree rm", json.dumps({"ok": True}))
        result = self.run_cleanup(self.wt, wait_limit="0.3")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(len(self.starts(result, "Worktree")), 1)
        self.assertTrue(self.local_has(self.BRANCH))
        self.assertTrue(self.starts(result, "Remote branch"))

    def test_a_failing_rm_exits_2_with_the_done_steps(self):
        self.stub("orca worktree rm", rc=1, stderr="boom")
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 2)
        self.assertTrue(self.starts(result, "Worktree"))
        self.assertTrue(self.starts(result, "Done steps"))
        self.assertIn("Remote branch", self.starts(result, "Done steps")[0])
        self.assertIn("Switch and pull", self.starts(result, "Done steps")[0])


class OwnWorktreeTest(CleanupCase):
    def setUp(self):
        super().setUp()
        self.stub_terminal(self.wt_id)
        del self.config["rm_effect"]
        self.stub("orca worktree rm", json.dumps({"ok": True}))

    def test_rm_is_the_last_call_and_the_close_notice_comes_first(self):
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.calls()[-1].startswith("orca worktree rm"))
        lines = self.lines(result)
        closes = [i for i, line in enumerate(lines) if line.startswith("Terminal closes")]
        self.assertEqual(len(closes), 1)
        self.assertTrue(any(line.startswith("Remote branch") for line in lines[:closes[0]]))
        self.assertTrue(any(line.startswith("Switch and pull") for line in lines[:closes[0]]))
        self.assertFalse(self.remote_has(self.BRANCH))

    def test_no_wait_and_no_branch_delete_after_rm(self):
        self.run_cleanup(self.wt)
        self.assertTrue(self.local_has(self.BRANCH))
        self.assertTrue(os.path.isdir(self.wt))

    def test_an_unknown_anchor_under_skip_ownership_is_the_own_case(self):
        self.stub_terminal(self.anchor_id, rc=1)
        result = self.run_cleanup("--skip-ownership", self.wt)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(self.starts(result, "Terminal closes"))
        self.assertTrue(self.calls()[-1].startswith("orca worktree rm"))

    def test_a_rm_error_that_returns_exits_2(self):
        self.stub("orca worktree rm", rc=1, stderr="boom")
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 2)
        self.assertTrue(self.starts(result, "Done steps"))


class RemoteBranchTest(CleanupCase):
    def test_a_protected_branch_skips_only_the_remote_delete(self):
        self.stub("gh repo view", json.dumps({"defaultBranchRef": {"name": self.BRANCH}}))
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("skipped", self.starts(result, "Remote branch")[0])
        self.assertTrue(self.remote_has(self.BRANCH))
        self.assertFalse(os.path.exists(self.wt))
        self.assertEqual(len([c for c in self.calls() if c.startswith("orca worktree rm")]), 1)

    def test_an_absent_remote_ref_skips_the_delete(self):
        git("push", "-q", "origin", "--delete", self.BRANCH, cwd=self.main, env=self.env)
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("skipped", self.starts(result, "Remote branch")[0])
        self.assertFalse(os.path.exists(self.wt))

    def write_hook(self, body):
        path = os.path.join(self.remote, "hooks", "pre-receive")
        with open(path, "w") as f:
            f.write("#!/bin/sh\n" + body)
        os.chmod(path, 0o755)

    def test_a_rejected_delete_exits_2_and_reports_the_done_steps(self):
        self.write_hook("exit 1\n")
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 2)
        self.assertTrue(self.starts(result, "Remote branch"))
        self.assertIn("none", self.starts(result, "Done steps")[0])
        self.assertTrue(os.path.isdir(self.wt))
        self.assertFalse([c for c in self.calls() if c.startswith("orca worktree rm")])

    def test_a_failed_delete_with_the_ref_gone_afterwards_counts_as_done(self):
        self.write_hook(f"git update-ref -d refs/heads/{self.BRANCH}\nexit 1\n")
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("already gone", self.starts(result, "Remote branch")[0])
        self.assertFalse(os.path.exists(self.wt))


class SwitchAndPullTest(CleanupCase):
    def test_a_pull_that_cannot_fast_forward_exits_2(self):
        other = os.path.join(self.root, "other")
        git("clone", "-q", self.remote, other, env=self.env)
        self.commit(other, "remote-only.txt")
        git("push", "-q", "origin", "main", cwd=other, env=self.env)
        self.commit(self.main, "local-only.txt")
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 2)
        self.assertTrue(self.starts(result, "Switch and pull"))
        self.assertIn("Remote branch", self.starts(result, "Done steps")[0])
        self.assertTrue(os.path.isdir(self.wt))
        self.assertFalse([c for c in self.calls() if c.startswith("orca worktree rm")])

    def test_the_main_checkout_ends_on_the_base_branch_and_is_pulled(self):
        git("checkout", "-q", "-b", "elsewhere", cwd=self.main, env=self.env)
        other = os.path.join(self.root, "other")
        git("clone", "-q", self.remote, other, env=self.env)
        self.commit(other, "remote-only.txt")
        git("push", "-q", "origin", "main", cwd=other, env=self.env)
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git_out(self.main, "branch", "--show-current"), "main")
        self.assertTrue(os.path.exists(os.path.join(self.main, "remote-only.txt")))


if __name__ == "__main__":
    unittest.main()
