import json
import os
import unittest

from cleanup_support import HANDLE, MISSING, RUN_ID
from test_cleanup_run_proof import RunProofCase

SKIP_FLAG = "--skip-ownership"
ACTIVE = "ready"
SETTLED = ("succeeded", "failed", "abandoned")
TERMINALS = ("released", "retained")
BAD_LIST_SHAPES = ("ok_false", "non_json", "no_page_object", "has_more_without_cursor", "failed_second_page")
PROOFS = ("none", "149", "skip")


class ActiveCase(RunProofCase):
    def active_row(self, **kwargs):
        return self.own_row(state=ACTIVE, **kwargs)

    def run_under(self, proof):
        """Run the cleanup with no #149 proof ("none"), with a #149 proof, or with the ownership skip flag."""
        if proof == "skip":
            return self.run_cleanup(SKIP_FLAG, self.wt)
        if proof == "149":
            self.stub_show(parent=self.anchor_id)
        return self.run_cleanup(self.wt)

    def assert_refused(self, result, marker):
        """One refusal line with the marker, no skip command anywhere, and nothing changed."""
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(len(self.starts(result, marker)), 1, result.stdout)
        self.assertNotIn(SKIP_FLAG, result.stdout)
        self.assert_unchanged()

    def assert_active_refusal(self, result, *dispatches):
        self.assert_refused(result, "Active worker:")
        line = self.starts(result, "Active worker:")[0]
        self.assertIn("release the worker first", line)
        for dispatch in dispatches:
            self.assertIn(dispatch, line)

    def assert_bound_run_refusal(self, result):
        self.assert_refused(result, "Bound Run:")
        line = self.starts(result, "Bound Run:")[0]
        self.assertIn(RUN_ID, line)
        self.assertIn("not read in full", line)


class ActiveRefusalTest(ActiveCase):
    def test_it_holds_under_the_run_proof(self):
        self.stub_worker_pages(self.worker_page([self.active_row(dispatch="ctx_live")]))
        result = self.run_cleanup(self.wt)
        self.assert_active_refusal(result, "ctx_live")
        self.assertEqual(self.starts(result, "Ownership"), [])
        for call in self.worker_calls():
            self.assertIn(f"--run {RUN_ID} --limit 100 --json", call)

    def test_it_holds_under_a_149_proof(self):
        self.stub_show(parent=self.anchor_id)
        self.stub_worker_pages(self.worker_page([self.active_row(dispatch="ctx_live")]))
        result = self.run_cleanup(self.wt)
        self.assert_active_refusal(result, "ctx_live")
        self.assertEqual(self.starts(result, "Ownership"), [])

    def test_it_holds_under_skip_ownership(self):
        self.stub_worker_pages(self.worker_page([self.active_row(dispatch="ctx_live")]))
        result = self.run_cleanup(SKIP_FLAG, self.wt)
        self.assert_active_refusal(result, "ctx_live")
        self.assertEqual(self.starts(result, "Ownership"), [])

    def test_a_worker_terminal_keeps_the_ownership_line_and_gets_no_skip_command(self):
        self.stub_worker_pages(self.worker_page([self.active_row(handle=HANDLE)]))
        result = self.run_cleanup(self.wt)
        self.assert_active_refusal(result, "ctx_one")
        self.assertEqual(len(self.starts(result, "Ownership")), 1)

    def test_an_active_dispatch_on_page_two_refuses(self):
        self.stub_worker_pages(self.worker_page([self.worker_row(worktree="other-id")], next_cursor="cur1"),
                               self.worker_page([self.active_row(dispatch="ctx_late")]))
        self.assert_active_refusal(self.run_cleanup(self.wt), "ctx_late")

    def test_every_active_dispatch_on_the_target_is_named_in_list_order(self):
        self.stub_worker_pages(self.worker_page([self.active_row(dispatch="ctx_a"), self.own_row(dispatch="ctx_done"),
                                                 self.active_row(dispatch="ctx_b")]))
        result = self.run_cleanup(self.wt)
        self.assert_active_refusal(result)
        self.assertIn("Dispatch ctx_a, ctx_b ", self.starts(result, "Active worker:")[0])

    def test_an_active_row_without_a_dispatch_id_is_named_no_id(self):
        row = self.active_row()
        del row["dispatchId"]
        self.stub_worker_pages(self.worker_page([row]))
        self.assert_active_refusal(self.run_cleanup(self.wt), "(no id)")

    def test_an_unknown_state_counts_as_active(self):
        self.stub_worker_pages(self.worker_page([self.own_row(state="frozen")]))
        self.assert_active_refusal(self.run_cleanup(self.wt))

    def test_a_missing_state_counts_as_active(self):
        self.stub_worker_pages(self.worker_page([self.own_row(state=MISSING)]))
        self.assert_active_refusal(self.run_cleanup(self.wt))

    def test_an_active_state_with_a_released_terminal_still_refuses(self):
        self.stub_worker_pages(self.worker_page([self.active_row(terminal="released")]))
        self.assert_active_refusal(self.run_cleanup(self.wt))

    def test_a_settled_state_with_an_active_terminal_lets_the_removal_through(self):
        self.stub_worker_pages(self.worker_page([self.own_row(terminal="active")]))
        self.assert_run_proof_passes(self.run_cleanup(self.wt))

    def test_an_active_row_on_another_worktree_does_not_block_the_target(self):
        self.stub_worker_pages(self.worker_page([self.worker_row(worktree="other-id", state=ACTIVE), self.own_row()]))
        self.assert_run_proof_passes(self.run_cleanup(self.wt))

    def test_an_active_row_with_neither_worktree_field_gives_no_refusal(self):
        self.stub_worker_pages(self.worker_page([self.worker_row(state=ACTIVE), self.own_row()]))
        self.assert_run_proof_passes(self.run_cleanup(self.wt))

    def test_an_entry_of_workers_that_is_not_an_object_is_skipped(self):
        self.stub_worker_pages(self.worker_page(["junk", None, self.own_row()]))
        self.assert_run_proof_passes(self.run_cleanup(self.wt))

    def test_the_other_checks_still_report_beside_the_refusal(self):
        with open(os.path.join(self.wt, "dirty.txt"), "w") as f:
            f.write("x")
        self.stub_gh_merged(prs=[])
        self.stub_worker_pages(self.worker_page([self.active_row()]))
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 1)
        for marker in ("Active worker:", "Clean", "Merged"):
            self.assertEqual(len(self.starts(result, marker)), 1, marker)
        self.assertEqual(self.rm_calls(), [])


class SettledStatesTest(ActiveCase):
    """Each settled workerState, with each terminalState, lets the Run proof remove the worktree."""


class EmptyHandleTest(ActiveCase):
    def test_an_empty_handle_with_a_bound_run_still_runs_the_active_check(self):
        self.stub_worker_pages(self.worker_page([self.active_row(dispatch="ctx_live")]))
        result = self.run_cleanup(self.wt, handle="")
        self.assert_active_refusal(result, "ctx_live")
        self.assertEqual(len(self.starts(result, "Ownership")), 1)

    def test_an_empty_handle_with_an_unreadable_list_refuses(self):
        self.stub_worker_raw({"stdout": "not json"})
        result = self.run_cleanup(self.wt, handle="")
        self.assert_bound_run_refusal(result)
        self.assertEqual(len(self.starts(result, "Ownership")), 1)


class NoBoundRunTest(ActiveCase):
    """run-current fails or returns no Run: nothing changes from ticket 1."""

    def test_skip_ownership_passes_when_run_current_fails(self):
        self.stub_run_current(rc=1)
        self.assertEqual(self.run_cleanup(SKIP_FLAG, self.wt).returncode, 0)

    def test_skip_ownership_passes_when_run_current_has_ok_false(self):
        self.stub_run_current(ok=False)
        self.assertEqual(self.run_cleanup(SKIP_FLAG, self.wt).returncode, 0)
        self.assertEqual(self.worker_calls(), [])

    def test_skip_ownership_passes_when_there_is_no_bound_run(self):
        self.stub_run_current(run_id=None)
        self.assertEqual(self.run_cleanup(SKIP_FLAG, self.wt).returncode, 0)
        self.assertEqual(self.worker_calls(), [])

    def test_a_run_with_an_empty_id_is_no_bound_run(self):
        self.stub("orca orchestration run-current", json.dumps({"ok": True, "result": {"run": {"id": ""}}}))
        self.assertEqual(self.run_cleanup(SKIP_FLAG, self.wt).returncode, 0)
        self.assertEqual(self.worker_calls(), [])

    def test_a_149_proof_passes_when_run_current_has_ok_false(self):
        self.stub_show(parent=self.anchor_id)
        self.stub_run_current(ok=False)
        self.assertEqual(self.run_cleanup(self.wt).returncode, 0)

    def test_a_149_proof_passes_when_there_is_no_bound_run(self):
        self.stub_show(parent=self.anchor_id)
        self.stub_run_current(run_id=None)
        self.assertEqual(self.run_cleanup(self.wt).returncode, 0)

    def test_no_proof_still_refuses_with_the_skip_command_when_run_current_fails(self):
        self.stub_run_current(rc=1)
        self.assert_no_proof(self.run_cleanup(self.wt))


class CallsTest(ActiveCase):
    def test_every_orca_call_is_one_the_spec_allows(self):
        self.stub_worker_pages(self.worker_page([self.worker_row(worktree="other-id")], next_cursor="cur1"),
                               self.worker_page([self.active_row()]))
        self.run_cleanup(self.wt)
        allowed = ("orca orchestration run-current --json",
                   f"orca orchestration worker-list --run {RUN_ID} --limit 100 --json",
                   "orca worktree show", "orca terminal show", "orca worktree rm")
        for call in self.calls():
            if call.startswith("orca"):
                self.assertTrue(call.startswith(allowed), call)
        self.assertEqual(len(self.worker_calls()), 2)


class UnreadableListTest(ActiveCase):
    def stub_bad_list(self, shape):
        if shape == "ok_false":
            self.stub_worker_raw({"stdout": json.dumps({"ok": False, "error": {"code": "run_not_found"}})})
        elif shape == "non_json":
            self.stub_worker_raw({"stdout": "not json"})
        elif shape == "no_page_object":
            self.stub_worker_raw({"stdout": json.dumps({"ok": True, "result": {"workers": [self.own_row()]}})})
        elif shape == "has_more_without_cursor":
            page = {"ok": True, "result": {"workers": [self.own_row()], "page": {"hasMore": True}}}
            self.stub_worker_raw({"stdout": json.dumps(page)})
        else:
            self.stub_worker_raw({"stdout": json.dumps(self.worker_page([self.own_row()], next_cursor="cur1"))},
                                 {"stdout": "", "rc": 1})


def add_settled_tests():
    for state in SETTLED:
        for terminal in TERMINALS:
            def test(self, state=state, terminal=terminal):
                self.stub_worker_pages(self.worker_page([self.own_row(state=state, terminal=terminal)]))
                self.assert_run_proof_passes(self.run_cleanup(self.wt))
            setattr(SettledStatesTest, f"test_{state}_with_a_{terminal}_terminal_lets_the_run_proof_through", test)


def add_unreadable_tests():
    for shape in BAD_LIST_SHAPES:
        for proof in PROOFS:
            def test(self, shape=shape, proof=proof):
                self.stub_bad_list(shape)
                result = self.run_under(proof)
                self.assert_bound_run_refusal(result)
                self.assertEqual(len(self.starts(result, "Ownership")), 1 if proof == "none" else 0)
            setattr(UnreadableListTest, f"test_{shape}_refuses_under_proof_{proof}", test)


add_settled_tests()
add_unreadable_tests()

if __name__ == "__main__":
    unittest.main()
