# A git problem or a git timeout in the helpers of the S5 rebase proof and of S6 is `Unavailable`: no exemption, no S6 pass, a named note.
import importlib.machinery
import importlib.util
import os
import shutil
import stat
import subprocess
import sys
import types
import unittest
from unittest import mock

from audit_support import AUDIT, phase_commit_event, round_event
from test_ledger_checks import FINAL, LedgerChecksCase

SHIM = """#!/bin/sh
case " $* " in
  %s) : > "%s"; echo "fatal: simulated failure" >&2; exit %d ;;
esac
exec "$REAL_GIT" "$@"
"""
REV_PARSE_OF_THE_BASE = '*" rev-parse --verify -q refs/remotes/origin/main"*'  # not origin/feature: the audit reads that one itself
REV_PARSE_OF_A_SHA = '*" rev-parse --verify -q "[0-9a-f]*'
MERGE_BASE_OF_A_COMMIT = '*" merge-base "*"refs/remotes/origin/"*'
DIFF = '*" diff --no-color "*'


def _load_audit():
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        loader = importlib.machinery.SourceFileLoader("audit_for_git_unavailable", AUDIT)
        module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = previous


audit = _load_audit()


class RebasedCase(LedgerChecksCase):
    """`feature` is rebased onto a moved `main` and its phase commit is amended with a new patch: a real rebase proof for S5."""

    def setUp(self):
        super().setUp()
        self.original = self.commit("feat: phase", name="phase.txt")
        self.git("checkout", "-q", "main")
        self.commit("chore: main moves", name="main.txt")
        self.git("push", "-q", "origin", "main")
        self.git("checkout", "-q", "feature")
        self.git("rebase", "-q", "main")
        with open(os.path.join(self.repo, "phase.txt"), "w") as handle:
            handle.write("resolved differently")
        self.git("commit", "-q", "-a", "--amend", "--no-edit")
        self.tip = self.git("rev-parse", "HEAD")
        self.git("push", "-q", "--force", "origin", "feature")

    def shim(self, pattern, status):
        """A `git` in front of the real one that fails with `status` for the calls that match the shell `pattern`.
        It creates a marker file when it fails a call: `assert_shim_fired` checks it."""
        folder = os.path.join(self.root, "shim")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "git")
        self.marker = os.path.join(folder, "fired")
        with open(path, "w") as handle:
            handle.write(SHIM % (pattern, self.marker, status))
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        self.env.update(PATH=folder + os.pathsep + os.environ["PATH"], REAL_GIT=shutil.which("git"))

    def assert_shim_fired(self):
        self.assertTrue(os.path.exists(self.marker), "the shim pattern matched no git call: real git ran")


class S5Test(RebasedCase):
    def s5(self):
        """Final rounds 1 to 3 after the original phase commit, round 4 after the rebased one (cap 3)."""
        events = ([round_event(), phase_commit_event(self.original)] + [round_event(n, **FINAL) for n in range(1, 4)]
                  + [phase_commit_event(self.tip), round_event(4, **FINAL)])
        return self.items(events)["S5"]

    def unavailable(self, text):
        item = self.s5()
        self.assertEqual(item["result"], "fail", item["evidence"])
        self.assertIn("code-review final: round 4 is past the cap of 3", item["evidence"])
        self.assertIn(f"rebase proof unavailable: evidence unavailable: {text}", item["evidence"])
        self.assertNotIn("not counting", item["evidence"])

    def test_the_proof_exempts_the_round_without_a_git_problem(self):
        item = self.s5()
        self.assertEqual(item["result"], "pass", item["evidence"])

    def test_status_128_from_rev_parse_gives_no_exemption_and_names_git(self):
        self.shim(REV_PARSE_OF_THE_BASE, 128)
        self.unavailable("git rev-parse exited with status 128: fatal: simulated failure")
        self.assert_shim_fired()

    def test_status_128_from_merge_base_gives_no_exemption_and_names_git(self):
        self.shim(MERGE_BASE_OF_A_COMMIT, 128)
        self.unavailable("git merge-base exited with status 128: fatal: simulated failure")
        self.assert_shim_fired()

    def test_status_1_from_merge_base_is_no_merge_base_and_gives_no_exemption_without_a_note(self):
        self.shim(MERGE_BASE_OF_A_COMMIT, 1)
        item = self.s5()
        self.assert_shim_fired()
        self.assertEqual(item["result"], "fail", item["evidence"])
        self.assertNotIn("unavailable", item["evidence"])

    def test_a_missing_commit_gives_no_exemption_without_a_note(self):
        events = ([round_event(), phase_commit_event(self.original)] + [round_event(n, **FINAL) for n in range(1, 4)]
                  + [phase_commit_event("b" * 40), round_event(4, **FINAL)])
        item = self.items(events)["S5"]
        self.assertEqual(item["result"], "fail", item["evidence"])
        self.assertNotIn("unavailable", item["evidence"])


class S6Test(RebasedCase):
    def s6(self):
        """The final round follows the original phase commit, which the rebase removed from HEAD history; the new phase commit has no final round after it, so S6 compares their patch-ids."""
        return self.items([round_event(), phase_commit_event(self.original), round_event(1, **FINAL), phase_commit_event(self.tip)])["S6"]

    def test_the_changed_patch_fails_on_its_own_without_a_git_problem(self):
        item = self.s6()
        self.assertEqual(item["result"], "fail", item["evidence"])
        self.assertIn("has a different patch-id", item["evidence"])
        self.assertNotIn("unavailable", item["evidence"])

    def test_status_128_from_rev_parse_fails_with_the_git_message(self):
        self.shim(REV_PARSE_OF_A_SHA, 128)
        item = self.s6()
        self.assert_shim_fired()
        self.assertEqual(item["result"], "fail", item["evidence"])
        self.assertIn("evidence unavailable: git rev-parse exited with status 128: fatal: simulated failure", item["evidence"])
        self.assertNotIn("unknown commit", item["evidence"])

    def test_status_128_from_diff_fails_with_the_git_message(self):
        self.shim(DIFF, 128)
        item = self.s6()
        self.assert_shim_fired()
        self.assertEqual(item["result"], "fail", item["evidence"])
        self.assertIn("evidence unavailable: git diff exited with status 128: fatal: simulated failure", item["evidence"])

    def test_a_missing_commit_still_reads_as_unknown(self):
        item = self.items([round_event(), phase_commit_event("b" * 40), round_event(1, **FINAL)])["S6"]
        self.assertEqual(item["result"], "fail", item["evidence"])
        self.assertIn("unknown commit bbbbbbb", item["evidence"])


class TimeoutThroughTheChecksTest(unittest.TestCase):
    """A git timeout fails S5 with the note and S6 with the git message; the audit goes on (no exception reaches the caller)."""

    LEDGER = types.SimpleNamespace(
        rounds={audit.FINAL_REVIEW: 4}, effective_cap=lambda loop, phase: 3, events=[],
        commits=[(1, {"sha": "a" * 40}), (3, {"sha": "b" * 40})],
        round_events=[(2, {"loop": "code-review", "phase": "final", "round": 1}), (4, {"loop": "code-review", "phase": "final", "round": 4})])

    def test_s5_names_the_timeout_and_gives_no_exemption(self):
        with mock.patch.object(audit, "_git", side_effect=subprocess.TimeoutExpired(["git"], audit.GIT_TIMEOUT_SECONDS)):
            passed, evidence = audit.check_s5(self.LEDGER, None, "", "/w", "main")
        self.assertFalse(passed)
        self.assertIn("rebase proof unavailable: evidence unavailable: git rev-parse timed out", evidence)
        self.assertNotIn("not counting", evidence)

    def test_s6_fails_with_the_timeout_message(self):
        with mock.patch.object(audit, "_git", side_effect=subprocess.TimeoutExpired(["git"], audit.GIT_TIMEOUT_SECONDS)):
            item = audit._check_item("S6", audit.check_s6, "/w", self.LEDGER, "main")
        self.assertEqual(item["result"], "fail")
        self.assertIn("evidence unavailable: git rev-parse timed out", item["evidence"])


class HelperTest(unittest.TestCase):
    """A timeout or an OS error of git becomes `Unavailable` in each of the four helpers; the message names the git command."""

    TIMEOUT = subprocess.TimeoutExpired(["git"], audit.GIT_TIMEOUT_SECONDS)

    def calls(self):
        return {
            "_is_known_commit": ("rev-parse", lambda: audit._is_known_commit("/w", "abc")),
            "_is_ancestor": ("merge-base", lambda: audit._is_ancestor("/w", "a", "b")),
            "_branch_patch_id": ("merge-base", lambda: audit._branch_patch_id("/w", "refs/remotes/origin/main", "abc")),
            "_base_of": ("merge-base", lambda: audit._base_of("/w", "abc", "refs/remotes/origin/main")),
        }

    def test_a_timeout_is_unavailable_and_names_the_command(self):
        for name, (command, call) in self.calls().items():
            with self.subTest(name=name), mock.patch.object(audit, "_git", side_effect=self.TIMEOUT):
                with self.assertRaisesRegex(audit.Unavailable, f"git {command} timed out after {audit.GIT_TIMEOUT_SECONDS} seconds"):
                    call()

    def test_an_os_error_is_unavailable_and_names_the_command(self):
        for name, (command, call) in self.calls().items():
            with self.subTest(name=name), mock.patch.object(audit, "_git", side_effect=FileNotFoundError("no git")):
                with self.assertRaisesRegex(audit.Unavailable, f"git {command} failed: no git"):
                    call()

    def test_a_patch_id_timeout_in_git_patch_id_is_unavailable(self):
        shown = subprocess.CompletedProcess(["git"], 0, stdout="diff", stderr="")
        with mock.patch.object(audit, "_git", return_value=shown), mock.patch("subprocess.run", side_effect=self.TIMEOUT):
            with self.assertRaisesRegex(audit.Unavailable, "git patch-id timed out"):
                audit._branch_patch_id("/w", "refs/remotes/origin/main", "abc")

    def test_a_patch_id_os_error_in_git_patch_id_is_unavailable(self):
        shown = subprocess.CompletedProcess(["git"], 0, stdout="diff", stderr="")
        with mock.patch.object(audit, "_git", return_value=shown), mock.patch("subprocess.run", side_effect=OSError("gone")):
            with self.assertRaisesRegex(audit.Unavailable, "git patch-id failed: gone"):
                audit._branch_patch_id("/w", "refs/remotes/origin/main", "abc")


if __name__ == "__main__":
    unittest.main()
