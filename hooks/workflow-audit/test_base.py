# The --base flag of `audit check` and `audit record` (spec #171): the PR target decides the commits that S8 and the digest read.
import os
import shutil
import stat
import unittest

from audit_support import AuditCase

DIGEST_MARKER = "--- digest ---"
GIT_SHIM = """#!/bin/sh
# A git wrapper for the tests: it logs its arguments and can fail the merge-base calls that are not --is-ancestor.
[ -n "$GIT_SHIM_LOG" ] && echo "$@" >> "$GIT_SHIM_LOG"
case " $* " in
  *" merge-base "*)
    case " $* " in
      *" --is-ancestor "*) ;;
      *) if [ -n "$GIT_SHIM_FAIL" ]; then echo "fatal: simulated failure" >&2; exit 5; fi ;;
    esac ;;
esac
exec "$REAL_GIT" "$@"
"""


class BaseCase(AuditCase):
    def develop_fixture(self):
        """origin/develop holds one non-conventional commit; the branch `work` is off develop with one conventional commit."""
        self.git("checkout", "-b", "develop")
        self.commit("bad develop commit")
        self.git("push", "-u", "origin", "develop")
        self.start_branch("work", "feat: on work")
        return self.git("merge-base", "origin/develop", "HEAD")

    def record_with(self, *flags):
        return self.audit("record", "--worktree", self.repo, *flags, "--llm", self.llm_path)

    def s8(self, base):
        """(passed, evidence) of the S8 item that `record --base <base>` writes for the current tip."""
        result = self.record_with("--base", base)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        item = self.item(self.git("rev-parse", "HEAD"), "S8")
        return item["result"] == "pass", item["evidence"]

    def check_with(self, *flags, env=None):
        """(the lines before the digest marker, the digest text) of `check`."""
        result = self.audit("check", "--worktree", self.repo, *flags, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        head, marker, digest = result.stdout.decode().partition("\n" + DIGEST_MARKER + "\n")
        self.assertTrue(marker)
        return head.splitlines(), digest

    def shim_env(self, fail=False):
        folder = os.path.join(self.root, "shim")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "git")
        with open(path, "w") as handle:
            handle.write(GIT_SHIM)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        self.shim_log = os.path.join(self.root, "shim.log")
        env = {"PATH": folder + os.pathsep + os.environ["PATH"], "REAL_GIT": shutil.which("git"), "GIT_SHIM_LOG": self.shim_log}
        if fail:
            env["GIT_SHIM_FAIL"] = "1"
        return env

    def merge_base_calls(self):
        """The logged git calls that compute a merge base for the range (a merge-base call without --is-ancestor)."""
        with open(self.shim_log) as handle:
            return [line for line in handle if " merge-base " in " " + line and "--is-ancestor" not in line]


class SelectionTest(BaseCase):
    def test_s8_follows_the_pr_target(self):  # (a)
        base = self.develop_fixture()
        passed, evidence = self.s8("develop")
        self.assertTrue(passed, evidence)
        self.assertIn(f"1 commits since {base[:7]}", evidence)
        passed, evidence = self.s8("main")
        self.assertFalse(passed)
        self.assertIn("bad develop commit", evidence)

    def test_an_unknown_base_branch_is_evidence_unavailable_and_named(self):  # (d)
        self.start_branch("work", "feat: a")
        passed, evidence = self.s8("nope")
        self.assertFalse(passed)
        self.assertEqual(evidence, "evidence unavailable: no such ref origin/nope")

    def test_a_base_without_a_merge_base_is_evidence_unavailable(self):  # (g)
        self.git("checkout", "--orphan", "island")
        self.commit("feat: unrelated history")
        self.git("push", "-u", "origin", "island")
        passed, evidence = self.s8("main")
        self.assertFalse(passed)
        self.assertEqual(evidence, "evidence unavailable: no merge base of origin/main and HEAD")

    def test_a_name_that_is_not_a_branch_name_is_evidence_unavailable(self):  # (l)
        self.start_branch("work", "feat: a")
        for name in ("main~1", "a..b", "main^", "a b"):
            with self.subTest(name=name):
                passed, evidence = self.s8(name)
                self.assertFalse(passed)
                self.assertEqual(evidence, f"evidence unavailable: {name} is not a branch name")


class EmptyRangeTest(BaseCase):
    def test_head_on_the_base_tip_is_not_a_pass(self):  # (k)
        self.start_branch("work")
        passed, evidence = self.s8("main")
        self.assertFalse(passed)
        self.assertEqual(evidence, "evidence unavailable: HEAD is already in origin/main: no commits to check")
        self.assertEqual(self.record_with("--base", "main").returncode, 1)
        self.assertEqual(len(self.record_files()), 1)
        _, digest = self.check_with("--base", "main")
        self.assertIn("commits unavailable: evidence unavailable: HEAD is already in origin/main: no commits to check", digest)

    def test_head_behind_a_newer_base_is_not_a_pass(self):  # (k)
        self.start_branch("work")
        self.git("checkout", "main")
        self.commit("feat: main moves on")
        self.git("push", "origin", "main")
        self.git("checkout", "work")
        passed, evidence = self.s8("main")
        self.assertFalse(passed)
        self.assertIn("no commits to check", evidence)


class DigestTest(BaseCase):
    def test_the_digest_commits_follow_the_pr_target(self):  # (e)
        base = self.develop_fixture()
        lines, digest = self.check_with("--base", "develop")
        self.assertIn(f"commits since {base[:7]}", digest)
        self.assertIn("feat: on work", digest)
        self.assertNotIn("bad develop commit", digest)
        self.assertIn(f"1 commits since {base[:7]}", " ".join(lines))

    def test_an_unknown_base_gives_commits_unavailable_naming_it(self):  # (e)
        self.start_branch("work", "feat: a")
        _, digest = self.check_with("--base", "nope")
        self.assertIn("commits unavailable: evidence unavailable: no such ref origin/nope", digest)

    def test_the_shortstat_follows_the_pr_target(self):  # (j)
        self.develop_fixture()
        _, digest = self.check_with("--base", "develop")
        self.assertIn("1 file changed", digest)
        _, digest = self.check_with("--base", "main")
        self.assertIn("2 files changed", digest)


class ArgumentTest(BaseCase):
    def refused(self, result):
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"--base", result.stderr)
        self.assertEqual(self.record_files(), [])

    def test_a_missing_base_is_a_usage_error(self):  # (b)
        self.start_branch("work", "feat: a")
        self.refused(self.audit("check", "--worktree", self.repo))
        self.refused(self.record_with())

    def test_a_repeated_or_valueless_base_is_refused(self):  # (c)
        self.start_branch("work", "feat: a")
        for flags in (("--base", "main", "--base", "main"), ("--base", "--worktree", self.repo), ("--base", "")):
            with self.subTest(flags=flags):
                self.refused(self.audit("check", "--worktree", self.repo, *flags))
                self.refused(self.record_with(*flags))
        self.refused(self.audit("check", "--worktree", self.repo, "--base"))
        self.refused(self.audit("record", "--worktree", self.repo, "--llm", self.llm_path, "--base"))

    def test_the_base_may_come_before_or_after_the_other_flags(self):  # (i)
        self.start_branch("work", "feat: a")
        for args in (("--base", "main", "--worktree", self.repo), ("--worktree", self.repo, "--base", "main")):
            with self.subTest(args=args):
                self.assertEqual(self.audit("check", *args).returncode, 0)
        for args in (("--base", "main", "--llm", self.llm_path, "--worktree", self.repo),
                     ("--llm", self.llm_path, "--worktree", self.repo, "--base", "main")):
            with self.subTest(args=args):
                result = self.audit("record", *args)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_pre_dispatch_refuses_the_base(self):  # (h)
        self.start_branch("work", "feat: a")
        result = self.audit("record", "--pre-dispatch", "--worktree", self.repo, "--map", "82", "--llm", self.llm_path, "--base", "main",
                            env={"CLAUDE_CODE_SESSION_ID": "main-1"})
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"usage:", result.stderr)
        self.assertEqual(self.record_files(), [])


class OnePerAuditTest(BaseCase):
    def test_a_git_failure_in_the_base_does_not_abort(self):  # (m)
        self.start_branch("work", "feat: a")
        env = self.shim_env(fail=True)
        lines, digest = self.check_with("--base", "main", env=env)
        self.assertIn("S8 fail", lines)
        self.assertIn("  evidence unavailable: git failed: git merge-base exited with status 5: fatal: simulated failure", lines)
        self.assertIn("commits unavailable: evidence unavailable: git failed", digest)
        result = self.audit("record", "--worktree", self.repo, "--base", "main", "--llm", self.llm_path, env=env)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.item(self.git("rev-parse", "HEAD"), "S8")["result"], "fail")

    def test_the_base_is_computed_once_and_shared(self):  # (n)
        base = self.develop_fixture()
        env = self.shim_env()
        lines, digest = self.check_with("--base", "develop", env=env)
        self.assertEqual(len(self.merge_base_calls()), 1)
        self.assertIn(f"1 commits since {base[:7]}", " ".join(lines))
        self.assertIn(f"commits since {base[:7]}", digest)
        os.remove(self.shim_log)
        result = self.audit("record", "--worktree", self.repo, "--base", "develop", "--llm", self.llm_path, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.merge_base_calls()), 1)


if __name__ == "__main__":
    unittest.main()
