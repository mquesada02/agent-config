# The main checkout returns to the development branch, not to the PR base (#869).
import os
import shutil
import unittest

from cleanup_support import CleanupCase, git


class SwitchTargetTest(CleanupCase):
    def add_branch(self, name):
        git("checkout", "-q", "-b", name, cwd=self.main, env=self.env)
        self.commit(self.main, f"{name.replace('/', '-')}.txt")
        git("push", "-q", "-u", "origin", name, cwd=self.main, env=self.env)
        git("checkout", "-q", "main", cwd=self.main, env=self.env)

    def stub_stacked(self):
        self.stub_gh_merged(prs=[{"number": 7, "headRefOid": self.tip, "baseRefName": "feature/a"}])

    def test_a_stacked_pr_returns_the_main_checkout_to_develop(self):
        self.add_branch("develop")
        self.add_branch("feature/a")
        self.stub_stacked()
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git_out(self.main, "branch", "--show-current"), "develop")
        self.assertIn("Switch and pull: develop pulled with --ff-only", result.stdout)
        self.assertFalse(os.path.isdir(self.wt))

    def test_a_stacked_pr_in_a_repo_without_develop_returns_to_the_default_branch(self):
        self.add_branch("feature/a")
        self.stub_stacked()
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git_out(self.main, "branch", "--show-current"), "main")
        self.assertIn("Switch and pull: main pulled with --ff-only", result.stdout)

    def test_a_pr_into_main_in_a_repo_with_develop_returns_to_develop(self):
        self.add_branch("develop")
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git_out(self.main, "branch", "--show-current"), "develop")

    def test_a_develop_that_the_main_checkout_never_fetched_is_fetched_before_any_action(self):
        other = os.path.join(self.root, "other")
        git("clone", "-q", self.remote, other, env=self.env)
        git("push", "-q", "origin", "HEAD:refs/heads/develop", cwd=other, env=self.env)
        self.assertFalse(self.git_out(self.main, "branch", "--list", "-a", "*develop"))
        self.stub_stacked()
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git_out(self.main, "branch", "--show-current"), "develop")
        self.assertFalse(os.path.isdir(self.wt))

    def assert_refused_and_untouched(self, result, text):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(text, self.starts(result, "Main checkout")[0])
        self.assertTrue(self.remote_has(self.BRANCH))
        self.assertTrue(os.path.isdir(self.wt))
        self.assertTrue(self.local_has(self.BRANCH))
        self.assertEqual(self.rm_calls(), [])

    def test_a_develop_checked_out_in_another_worktree_is_refused_before_any_delete(self):
        self.add_branch("develop")
        git("worktree", "add", "-q", os.path.join(self.root, "dev"), "develop", cwd=self.main, env=self.env)
        self.assert_refused_and_untouched(self.run_cleanup(self.wt), "develop is checked out in another worktree")

    def test_a_local_develop_that_diverged_from_origin_is_refused_before_any_delete(self):
        self.add_branch("develop")
        git("checkout", "-q", "develop", cwd=self.main, env=self.env)
        self.commit(self.main, "local-only.txt")
        other = os.path.join(self.root, "other")
        git("clone", "-q", "-b", "develop", self.remote, other, env=self.env)
        self.commit(other, "remote-only.txt")
        git("push", "-q", "origin", "develop", cwd=other, env=self.env)
        git("checkout", "-q", "main", cwd=self.main, env=self.env)
        self.assert_refused_and_untouched(self.run_cleanup(self.wt), "local develop and origin/develop have diverged")

    def test_a_local_develop_that_is_ahead_of_origin_is_not_refused(self):
        self.add_branch("develop")
        git("checkout", "-q", "develop", cwd=self.main, env=self.env)
        self.commit(self.main, "local-only.txt")
        git("checkout", "-q", "main", cwd=self.main, env=self.env)
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git_out(self.main, "branch", "--show-current"), "develop")

    def test_a_local_develop_without_an_upstream_is_pulled(self):
        git("push", "-q", "origin", "main:refs/heads/develop", cwd=self.main, env=self.env)
        git("branch", "develop", "main", cwd=self.main, env=self.env)
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git_out(self.main, "branch", "--show-current"), "develop")

    def test_a_local_develop_that_is_behind_origin_is_fast_forwarded(self):
        self.add_branch("develop")
        other = os.path.join(self.root, "other")
        git("clone", "-q", "-b", "develop", self.remote, other, env=self.env)
        self.commit(other, "remote-only.txt")
        git("push", "-q", "origin", "develop", cwd=other, env=self.env)
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git_out(self.main, "branch", "--show-current"), "develop")
        self.assertTrue(os.path.exists(os.path.join(self.main, "remote-only.txt")))

    def test_an_unreadable_origin_refuses_and_removes_nothing(self):
        self.add_branch("develop")
        git("remote", "set-url", "origin", os.path.join(self.root, "missing.git"), cwd=self.wt, env=self.env)
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue(os.path.isdir(self.wt))
        self.assertEqual(self.rm_calls(), [])


class LocalTipRefusalTest(CleanupCase):
    def test_the_refusal_says_how_to_go_on(self):
        self.commit(self.wt, "ahead.txt")
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        line = self.starts(result, "Pushed")[0]
        self.assertIn("not the local tip", line)
        self.assertIn("The local branch is ahead of or differs from origin: push it (or ask the owner), then run cleanup again", line)
        self.assertNotIn("reset", line)
        self.assertTrue(os.path.isdir(self.wt))


class WorktreeListFailureTest(CleanupCase):
    def test_a_failed_worktree_list_of_the_main_checkout_refuses_before_any_action(self):
        wrapper = os.path.join(self.bin, "git")
        with open(wrapper, "w") as f:
            f.write(f'#!/bin/sh\nif [ "$1 $2 $3 $4" = "-C {self.main} worktree list" ]; then\n'
                    '  echo "fatal: list failed" >&2\n  exit 128\nfi\n'
                    f'exec {shutil.which("git")} "$@"\n')
        os.chmod(wrapper, 0o755)
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("git worktree list failed: fatal: list failed", self.starts(result, "Main checkout")[0])
        self.assertTrue(self.remote_has(self.BRANCH))
        self.assertTrue(self.local_has(self.BRANCH))
        self.assertTrue(os.path.isdir(self.wt))
        self.assertEqual(self.rm_calls(), [])


class UsageTextTest(CleanupCase):
    def test_the_usage_says_what_base_affects_and_where_the_switch_goes(self):
        result = self.run_cleanup()
        self.assertIn("--base affects only the merged check (check 5). The main checkout returns to develop when origin has it, "
                      "else to the default branch.", result.stdout)


if __name__ == "__main__":
    unittest.main()
