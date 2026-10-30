import json
import os
import unittest

from cleanup_support import CleanupCase, HANDLE, RUN_ID

SUCCESS_LINES = ["Remote branch: deleted", "Switch and pull: main pulled with --ff-only",
                 "Worktree: removed", "Local branch: deleted"]
ORCA_CALLS = ("orca orchestration run-current", "orca orchestration worker-list", "orca worktree show",
              "orca terminal show", "orca worktree rm")


class RunProofCase(CleanupCase):
    """No #149 proof holds: the anchor is another worktree, the target has no parent and no provenance."""

    def setUp(self):
        super().setUp()
        self.stub_show()
        self.stub_run_current()

    def worker_calls(self):
        return [call for call in self.calls() if call.startswith("orca orchestration worker-list")]

    def orchestration_calls(self):
        return [call for call in self.calls() if call.startswith("orca orchestration")]

    def own_row(self, **kwargs):
        return self.worker_row(worktree=self.wt_id, **kwargs)

    def assert_run_proof_passes(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(os.path.exists(self.wt))

    def assert_no_proof(self, result):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(len(self.starts(result, "Ownership")), 1)
        self.assertIn(f"! ~/.claude/hooks/worktree-cleanup/cleanup --skip-ownership {self.wt}", self.lines(result))
        self.assert_unchanged()


class StubTest(RunProofCase):
    def test_the_full_argument_list_wins_over_the_two_argument_key(self):
        self.stub("orca orchestration worker-list", json.dumps(self.worker_page([])))
        self.stub(f"orca orchestration worker-list --run {RUN_ID} --limit 100 --json",
                  json.dumps(self.worker_page([self.own_row()])))
        self.assert_run_proof_passes(self.run_cleanup(self.wt))

    def test_a_sequence_answers_the_calls_of_one_key_in_order(self):
        self.stub_worker_pages(self.worker_page([self.worker_row(worktree="other-id")], next_cursor="cur1"),
                               self.worker_page([self.own_row()]))
        self.assert_run_proof_passes(self.run_cleanup(self.wt))
        self.assertEqual(len(self.worker_calls()), 2)


class RunProofTest(RunProofCase):
    def test_the_run_proof_alone_lets_a_merged_worktree_through_with_a_stale_coordinator(self):
        # The anchor is another worktree and the handle created nothing: a successor in another repo (stories 2, 3).
        self.stub_run_current(coordinator="term_other")
        self.stub_worker_pages(self.worker_page([self.own_row()]))
        self.assert_run_proof_passes(self.run_cleanup(self.wt))

    def test_a_match_on_page_two(self):
        self.stub_worker_pages(self.worker_page([self.worker_row(worktree="other-id")], next_cursor="cur1"),
                               self.worker_page([self.own_row()]))
        self.assert_run_proof_passes(self.run_cleanup(self.wt))
        self.assertIn("--cursor cur1", self.worker_calls()[1])

    def test_a_match_through_the_projection_when_resource_is_null(self):
        self.stub_worker_pages(self.worker_page([self.own_row(via="projection")]))
        self.assert_run_proof_passes(self.run_cleanup(self.wt))

    def test_two_rows_on_the_same_worktree_one_a_retry_of_the_other(self):
        self.stub_worker_pages(self.worker_page([self.own_row(dispatch="ctx_retry"), self.own_row(dispatch="ctx_one")]))
        self.assert_run_proof_passes(self.run_cleanup(self.wt))

    def test_a_row_with_a_null_handle_does_not_exclude_the_caller(self):
        self.stub_worker_pages(self.worker_page([self.own_row(handle=None), self.worker_row(worktree="other-id")]))
        self.assert_run_proof_passes(self.run_cleanup(self.wt))

    def test_a_parent_only_match_gives_no_proof(self):
        self.stub_show(parent="parent-id")
        self.stub_worker_pages(self.worker_page([self.worker_row(worktree="parent-id")]))
        self.assert_no_proof(self.run_cleanup(self.wt))

    def test_a_worker_terminal_gets_no_proof(self):
        self.stub_worker_pages(self.worker_page([self.own_row(handle="term_worker"),
                                                 self.worker_row(worktree="other-id", handle=HANDLE)]))
        self.assert_no_proof(self.run_cleanup(self.wt))

    def test_a_row_with_neither_worktree_field_matches_nothing(self):
        self.stub_worker_pages(self.worker_page([self.worker_row()]))
        self.assert_no_proof(self.run_cleanup(self.wt))

    def test_a_resource_without_a_worktree_id_matches_nothing(self):
        row = self.worker_row(via="projection", worktree=self.wt_id)
        row["resource"] = {"ownershipState": "owned"}
        self.stub_worker_pages(self.worker_page([row]))
        self.assert_no_proof(self.run_cleanup(self.wt))

    def test_a_run_with_no_row_on_the_target_gives_no_proof(self):
        self.stub_worker_pages(self.worker_page([self.worker_row(worktree="other-id")]))
        self.assert_no_proof(self.run_cleanup(self.wt))

    def test_a_run_with_no_dispatch_keeps_todays_rules(self):
        self.stub_worker_pages(self.worker_page([]))
        self.assert_no_proof(self.run_cleanup(self.wt))

    def test_run_current_with_ok_false_gives_no_proof(self):
        self.stub_run_current(ok=False)
        self.assert_no_proof(self.run_cleanup(self.wt))
        self.assertEqual(self.worker_calls(), [])

    def test_a_failed_run_current_gives_no_proof(self):
        self.stub_run_current(rc=1)
        self.assert_no_proof(self.run_cleanup(self.wt))

    def test_no_bound_run_gives_no_proof(self):
        self.stub_run_current(run_id=None)
        self.assert_no_proof(self.run_cleanup(self.wt))
        self.assertEqual(self.worker_calls(), [])

    def test_an_empty_handle_gives_no_proof_and_makes_no_run_call(self):
        self.stub_worker_pages(self.worker_page([self.own_row()]))
        self.assert_no_proof(self.run_cleanup(self.wt, handle=""))
        self.assertEqual(self.orchestration_calls(), [])

    def test_a_149_proof_passes_when_run_current_fails(self):
        self.stub_show(parent=self.anchor_id)
        self.stub_run_current(rc=1)
        self.assertEqual(self.run_cleanup(self.wt).returncode, 0)

    def test_a_149_proof_makes_no_run_call(self):
        self.stub_show(parent=self.anchor_id)
        self.assertEqual(self.run_cleanup(self.wt).returncode, 0)
        self.assertEqual(self.orchestration_calls(), [])

    def test_skip_ownership_makes_no_run_call(self):
        self.assertEqual(self.run_cleanup("--skip-ownership", self.wt).returncode, 0)
        self.assertEqual(self.orchestration_calls(), [])

    def test_worker_list_is_always_scoped_to_the_bound_run(self):
        self.stub_worker_pages(self.worker_page([self.worker_row(worktree="other-id")], next_cursor="cur1"),
                               self.worker_page([self.own_row()]))
        self.run_cleanup(self.wt)
        calls = self.worker_calls()
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertIn(f"--run {RUN_ID} --limit 100 --json", call)

    def test_every_orca_call_is_one_the_spec_allows(self):
        self.stub_worker_pages(self.worker_page([self.own_row()]))
        self.run_cleanup(self.wt)
        for call in self.calls():
            if call.startswith("orca"):
                self.assertTrue(call.startswith(ORCA_CALLS), call)


class RunProofOnlyRemovalTest(RunProofCase):
    def setUp(self):
        super().setUp()
        self.stub_worker_pages(self.worker_page([self.own_row()]))
        # A failed terminal show makes the anchor unknown: the old rule would call the worktree the session's own.
        self.stub_terminal(self.anchor_id, rc=1)

    def test_it_waits_deletes_the_local_branch_and_prints_no_close_notice(self):
        self.stub_rm_effect(delay=0.4)
        result = self.run_cleanup(self.wt, wait_limit="5")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(os.path.exists(self.wt))
        self.assertFalse(self.local_has(self.BRANCH))
        self.assertFalse(self.starts(result, "Terminal closes"))
        self.assertEqual(self.lines(result), SUCCESS_LINES)

    def test_the_output_is_that_of_a_149_removal_on_the_other_session_path(self):
        self.stub_show(parent=self.anchor_id)
        self.stub_terminal(self.anchor_id)
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.lines(result), SUCCESS_LINES)

    def test_the_other_checks_still_run(self):
        with open(os.path.join(self.wt, "dirty.txt"), "w") as f:
            f.write("x")
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(self.starts(result, "Clean"))
        self.assertFalse(self.starts(result, "Ownership"))
        self.assertEqual(self.rm_calls(), [])

    def test_an_unmerged_branch_still_refuses(self):
        self.stub_gh_merged(prs=[])
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(self.starts(result, "Merged"))
        self.assertEqual(self.rm_calls(), [])

    def test_an_unpushed_tip_still_refuses(self):
        self.commit(self.wt, "late.txt")
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(self.starts(result, "Pushed"))
        self.assertEqual(self.rm_calls(), [])


if __name__ == "__main__":
    unittest.main()
