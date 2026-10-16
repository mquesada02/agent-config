# S3 to S6 and the agent-id cross-check XC, through `audit record` with ledgers written straight into the runtime folder.
import os
import unittest

from audit_support import (EARLY, LATE, AuditCase, edit_row, finding_event, phase_commit_event, round_event, status_event,
                           subagent_rows, verdict_event)

FINAL = {"phase": "final"}


class LedgerChecksCase(AuditCase):
    default_ledger = False

    def setUp(self):
        super().setUp()
        self.tip = self.start_branch("feature", "feat: a")
        self.sessions = 0

    def agents(self, **agents):
        """Register one more audited session whose subagents are `agents`: id -> rows."""
        self.sessions += 1
        path = os.path.join(self.repo, f"b{self.sessions}.txt")
        self.register_session(f"more-{self.sessions}", [edit_row(path, "t9", 3)], subagents=agents)

    def items(self, events=None, raw=None):
        if events is not None or raw is not None:
            self.write_ledger("feature", events if events is not None else raw)
        result = self.record()
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return {item["id"]: item for item in self.read_record(self.tip)["items"]}

    def check(self, items, name, result, text=None):
        self.assertEqual(items[name]["result"], result, items[name]["evidence"])
        if text is not None:
            self.assertIn(text, items[name]["evidence"])


class S3Test(LedgerChecksCase):
    def test_a_valid_ledger_with_every_finding_closed_passes(self):
        items = self.items([round_event(), finding_event(kind="Minor"), status_event(status="deferred")])
        self.check(items, "S3", "pass", "3 events, 1 findings, none open")

    def test_no_ledger_is_evidence_unavailable(self):
        self.check(self.items(), "S3", "fail", "evidence unavailable: no ledger for feature")

    def test_an_empty_ledger_fails(self):
        self.check(self.items(raw=[]), "S3", "fail", "ledger has no events")

    def test_an_invalid_line_fails_with_its_number(self):
        items = self.items(raw=[round_event(), "{not json"])
        self.check(items, "S3", "fail", "invalid ledger: line 2")
        for name in ("S4", "S5", "S6", "XC"):
            self.check(items, name, "fail", "evidence unavailable")

    def test_an_event_that_breaks_a_rule_fails(self):
        self.check(self.items(raw=[finding_event()]), "S3", "fail", "line 1")

    def test_an_unreadable_ledger_is_evidence_unavailable(self):
        os.makedirs(self.runtime, exist_ok=True)
        os.mkdir(self.ledger_file())  # a directory in place of the file
        self.check(self.items(), "S3", "fail", "evidence unavailable: unreadable ledger")

    def test_a_finding_without_a_status_fails_and_is_listed(self):
        items = self.items([round_event(), finding_event("I1", kind="Minor"), finding_event("I2", kind="Minor"), status_event("I2")])
        self.check(items, "S3", "fail", "1 findings have no status")
        self.assertIn("I1 a.py:1", items["S3"]["evidence"])
        self.assertNotIn("I2", items["S3"]["evidence"])

    def test_the_latest_status_stands_and_a_status_closes_the_finding(self):
        events = [round_event(), finding_event(kind="Minor"), status_event(status="deferred"), status_event(status="fixed")]
        self.check(self.items(events), "S3", "pass")

    def test_a_correctness_round_at_the_cap_lets_findings_stay_open_with_a_note(self):
        events = [round_event(n) for n in range(1, 6)] + [finding_event("I1", n=5), finding_event("I2", n=5, kind="Minor")]
        items = self.items(events)
        self.check(items, "S3", "pass", "stopped at cap: 2 open findings")
        self.assertIn("I1 a.py:1", items["S3"]["evidence"])

    def test_a_final_round_at_the_cap_lets_findings_of_any_phase_of_that_loop_stay_open(self):
        events = ([round_event(1), finding_event("I1", kind="Minor")]
                  + [round_event(n, **FINAL) for n in range(1, 4)])
        self.check(self.items(events), "S3", "pass", "stopped at cap: 1 open findings")

    def test_a_cap_in_one_loop_does_not_let_another_loop_leave_findings_open(self):
        events = ([round_event(n) for n in range(1, 6)] + [round_event(1, loop="plan-review-3"),
                  finding_event("P1", loop="plan-review-3", kind="Minor")])
        items = self.items(events)
        self.check(items, "S3", "fail", "1 findings have no status")

    def test_rounds_below_the_cap_do_not_exempt(self):
        events = [round_event(n) for n in range(1, 5)] + [finding_event("I1", n=4, kind="Minor")]
        self.check(self.items(events), "S3", "fail")

    def test_events_written_under_two_session_ids_are_read_back_as_one_ledger(self):
        loop = ("--loop", "code-review", "--phase", "correctness")
        self.assertEqual(self.ledger("round", *loop, "--round", "1", "--reviewer", "rev1",
                                     env={"CLAUDE_CODE_SESSION_ID": "session-a"}, cwd=self.main).returncode, 0)
        self.assertEqual(self.ledger("finding", "--id", "I1", *loop, "--round", "1", "--loc", "a.py:1", "--type", "Minor",
                                     "--reason", "r", env={"CLAUDE_CODE_SESSION_ID": "session-b"}).returncode, 0)
        self.assertEqual(self.ledger("status", "--finding", "I1", "--status", "fixed",
                                     env={"CLAUDE_CODE_SESSION_ID": "session-c"}, cwd=self.root).returncode, 0)
        self.check(self.items(), "S3", "pass", "3 events, 1 findings, none open")


class S4Test(LedgerChecksCase):
    def blocking(self, verifier="ver1", result="confirmed"):
        return [round_event(), finding_event(), verdict_event(verifier=verifier, result=result)]

    def test_a_blocking_finding_with_a_sonnet_verifier_passes(self):
        self.agents(ver1=subagent_rows())
        self.check(self.items(self.blocking()), "S4", "pass", "1 Blocking findings")

    def test_a_rejected_verdict_counts(self):
        self.agents(ver1=subagent_rows())
        self.check(self.items(self.blocking(result="rejected")), "S4", "pass")

    def test_a_blocking_finding_without_a_verdict_fails(self):
        self.check(self.items([round_event(), finding_event()]), "S4", "fail", "I1: no verdict")

    def test_a_verifier_that_is_not_in_a_transcript_fails(self):
        self.check(self.items(self.blocking(verifier="ghost")), "S4", "fail", "I1: no verdict by a Sonnet subagent")

    def test_a_verifier_that_is_not_sonnet_fails(self):
        for model in ("claude-opus-5-5", "claude-haiku-5-5", None):
            with self.subTest(model=model):
                self.agents(ver1=subagent_rows(model=model))
                self.check(self.items(self.blocking()), "S4", "fail", "I1: no verdict by a Sonnet subagent")

    def test_one_non_sonnet_row_makes_the_agent_not_sonnet(self):
        self.agents(ver1=subagent_rows(extra_models=("claude-opus-5-5",)))
        self.check(self.items(self.blocking()), "S4", "fail")

    def test_a_synthetic_row_among_sonnet_rows_is_ignored(self):
        self.agents(ver1=subagent_rows(extra_models=("<synthetic>",)))
        self.check(self.items(self.blocking()), "S4", "pass")

    def test_only_synthetic_rows_are_not_sonnet(self):
        self.agents(ver1=subagent_rows(model="<synthetic>"))
        self.check(self.items(self.blocking()), "S4", "fail")

    def test_a_subagent_without_assistant_rows_is_not_sonnet(self):
        self.agents(ver1=subagent_rows()[:1])
        self.check(self.items(self.blocking()), "S4", "fail")

    def test_a_second_verdict_by_a_sonnet_verifier_is_enough(self):
        self.agents(ver2=subagent_rows())
        events = self.blocking(verifier="ghost") + [verdict_event(verifier="ver2")]
        self.check(self.items(events), "S4", "pass")

    def test_a_blocking_finding_of_a_plan_review_loop_needs_no_verdict(self):
        events = [round_event(loop="plan-review-3"), finding_event("P1", loop="plan-review-3")]
        self.check(self.items(events), "S4", "pass", "no Blocking finding")

    def test_a_minor_finding_needs_no_verdict(self):
        self.check(self.items([round_event(), finding_event(kind="Minor")]), "S4", "pass")

    def test_without_a_blocking_finding_no_transcript_is_needed(self):
        os.unlink(os.path.join(self.runtime, "sessions.jsonl"))
        items = self.items([round_event(), finding_event(kind="Minor")])
        self.check(items, "S4", "pass")
        self.check(items, "XC", "fail", "evidence unavailable")

    def test_unreadable_transcripts_fail_with_a_blocking_finding(self):
        os.unlink(os.path.join(self.runtime, "sessions.jsonl"))
        self.check(self.items(self.blocking()), "S4", "fail", "evidence unavailable")


class S5Test(LedgerChecksCase):
    def test_rounds_up_to_the_caps_pass(self):
        events = [round_event(n) for n in range(1, 6)] + [round_event(n, **FINAL) for n in range(1, 4)]
        events += [round_event(n, loop="plan-review-4.1") for n in range(1, 6)]
        self.check(self.items(events), "S5", "pass")

    def test_a_sixth_correctness_round_fails(self):
        self.check(self.items([round_event(n) for n in range(1, 7)]), "S5", "fail", "code-review correctness: round 6 is past the cap of 5")

    def test_a_fourth_final_round_fails(self):
        events = [round_event(n, **FINAL) for n in range(1, 5)]
        self.check(self.items(events), "S5", "fail", "code-review final: round 4 is past the cap of 3")

    def test_the_plan_review_loops_have_the_same_caps(self):
        for loop in ("plan-review-3", "plan-review-4.1", "plan-review-5.3"):
            with self.subTest(loop=loop):
                self.check(self.items([round_event(n, loop=loop) for n in range(1, 7)]), "S5", "fail", f"{loop} correctness: round 6")
                self.check(self.items([round_event(n, loop=loop, **FINAL) for n in range(1, 5)]), "S5", "fail", f"{loop} final: round 4")


class S6Test(LedgerChecksCase):
    def events(self, *commits):
        return [round_event(), *commits, round_event(1, **FINAL)]

    def test_an_ancestor_commit_before_the_first_final_round_passes(self):
        parent = self.git("rev-parse", "HEAD~1")
        self.check(self.items(self.events(phase_commit_event(parent))), "S6", "pass", f"{parent[:7]} is an ancestor of HEAD")

    def test_the_head_commit_itself_is_an_ancestor(self):
        self.check(self.items(self.events(phase_commit_event(self.tip))), "S6", "pass")

    def test_no_phase_commit_fails(self):
        self.check(self.items(self.events()), "S6", "fail", "no phase-commit before the first final round")

    def test_a_phase_commit_after_the_first_final_round_fails(self):
        events = [round_event(), round_event(1, **FINAL), phase_commit_event(self.tip)]
        self.check(self.items(events), "S6", "fail", "no phase-commit before")

    def test_a_commit_that_is_not_an_ancestor_of_head_fails(self):
        self.git("checkout", "-q", "-b", "side")
        side = self.commit("feat: side")
        self.git("checkout", "-q", "feature")
        self.check(self.items(self.events(phase_commit_event(side))), "S6", "fail", f"{side[:7]} is not an ancestor of HEAD")

    def test_an_unknown_commit_fails(self):
        self.check(self.items(self.events(phase_commit_event("b" * 40))), "S6", "fail", "unknown commit bbbbbbb")

    def test_the_last_phase_commit_before_the_first_final_round_decides(self):
        parent = self.git("rev-parse", "HEAD~1")
        self.check(self.items(self.events(phase_commit_event("b" * 40), phase_commit_event(parent))), "S6", "pass")
        self.check(self.items(self.events(phase_commit_event(parent), phase_commit_event("b" * 40))), "S6", "fail", "unknown commit")

    def test_the_first_final_round_of_the_code_review_loop_is_the_one_that_counts(self):
        events = [round_event(), round_event(1, loop="plan-review-3", **FINAL), phase_commit_event(self.tip), round_event(1, **FINAL)]
        self.check(self.items(events), "S6", "pass")

    def test_without_a_final_round_of_the_code_review_loop_it_passes_with_a_note(self):
        self.check(self.items([round_event()]), "S6", "pass", "no section 6 final round")
        self.check(self.items([round_event(1, loop="plan-review-3", **FINAL)]), "S6", "pass", "no section 6 final round")


class CrossCheckTest(LedgerChecksCase):
    def test_reviewers_that_are_sonnet_subagents_in_order_pass(self):
        self.agents(rev2=subagent_rows(start=LATE))
        events = [round_event(), round_event(2, reviewers=["rev2"])]
        # a round event's time is the time of the write; here it is EARLY, so a subagent that starts at LATE follows round 1
        self.check(self.items(events), "XC", "pass", "2 reviewers and verifiers checked")

    def test_an_id_that_is_not_in_a_transcript_fails(self):
        self.check(self.items([round_event(reviewers=["rev1", "ghost"])]), "XC", "fail", "reviewer ghost of code-review correctness round 1: not a subagent")

    def test_a_reviewer_that_is_not_sonnet_fails(self):
        self.agents(rev2=subagent_rows(model="claude-opus-5-5"))
        self.check(self.items([round_event(reviewers=["rev2"])]), "XC", "fail", "not a Sonnet subagent")

    def test_a_reviewer_that_started_before_the_previous_round_fails(self):
        self.agents(rev2=subagent_rows(start=EARLY))
        events = [round_event(), round_event(2, reviewers=["rev2"])]
        self.check(self.items(events), "XC", "fail", "reviewer rev2 of code-review correctness round 2: started before the previous round")

    def test_starting_at_the_time_of_the_previous_round_is_too_early(self):
        self.agents(rev2=subagent_rows(start=LATE))
        events = [round_event(time=LATE), round_event(2, reviewers=["rev2"])]
        self.check(self.items(events), "XC", "fail", "started before the previous round")

    def test_the_first_round_of_a_loop_has_no_lower_bound(self):
        self.agents(rev2=subagent_rows(start=EARLY))
        events = [round_event(time=LATE, reviewers=["rev1"]), round_event(1, loop="plan-review-3", reviewers=["rev2"])]
        self.check(self.items(events), "XC", "pass")

    def test_the_bound_is_the_previous_round_of_the_same_loop_in_any_phase(self):
        self.agents(rev2=subagent_rows(start=EARLY), rev3=subagent_rows(start=LATE))
        events = [round_event(), round_event(1, reviewers=["rev2"], **FINAL)]
        self.check(self.items(events), "XC", "fail", "reviewer rev2 of code-review final round 1")
        events = [round_event(), round_event(1, reviewers=["rev3"], **FINAL)]
        self.check(self.items(events), "XC", "pass")

    def test_another_loop_does_not_set_the_bound(self):
        self.agents(rev2=subagent_rows(start=EARLY))
        events = [round_event(loop="plan-review-3", reviewers=["rev1"], time=LATE), round_event(reviewers=["rev2"])]
        self.check(self.items(events), "XC", "pass")

    def test_a_verifier_must_start_after_the_round_before_its_findings_round(self):
        self.agents(ver1=subagent_rows(start=EARLY), ver2=subagent_rows(start=LATE), rev3=subagent_rows(start=LATE))
        base = [round_event(), round_event(2, reviewers=["rev3"], time=LATE), finding_event("I1", n=2)]
        self.check(self.items(base + [verdict_event("I1", "ver1")]), "XC", "fail", "verifier ver1 of I1: started before")
        self.check(self.items(base + [verdict_event("I1", "ver2")]), "XC", "pass")

    def test_a_verifier_of_a_first_round_finding_has_no_lower_bound(self):
        self.agents(ver1=subagent_rows(start=EARLY))
        self.check(self.items([round_event(), finding_event("I1"), verdict_event("I1", "ver1")]), "XC", "pass")

    def test_a_start_time_that_cannot_be_read_is_unavailable_when_a_bound_applies(self):
        rows = subagent_rows(start=LATE)
        del rows[0]["timestamp"]
        self.agents(rev2=rows)
        events = [round_event(), round_event(2, reviewers=["rev2"])]
        self.check(self.items(events), "XC", "fail", "evidence unavailable: no readable start time")
        self.check(self.items([round_event(reviewers=["rev2"])]), "XC", "pass")

    def test_unreadable_transcripts_fail(self):
        os.unlink(os.path.join(self.runtime, "sessions.jsonl"))
        self.check(self.items([round_event()]), "XC", "fail", "evidence unavailable")


class RecordItemsTest(LedgerChecksCase):
    def test_the_record_lists_the_new_items_in_order_and_a_passing_ledger_passes(self):
        result = self.record_with([round_event()])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([item["id"] for item in self.read_record(self.tip)["items"]],
                         ["S1", "S2", "S3", "S4", "S5", "S6", "XC", "S8", "L1", "L2", "L3", "L4", "L5", "L6"])
        self.assertEqual(result.stdout.decode().splitlines()[:8], ["S1 pass", "S2 pass", "S3 pass", "S4 pass", "S5 pass", "S6 pass", "XC pass", "S8 pass"])

    def test_a_failed_ledger_item_fails_the_record(self):
        result = self.record_with([round_event(n) for n in range(1, 7)])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.read_record(self.tip)["result"], "fail")

    def record_with(self, events):
        self.write_ledger("feature", events)
        return self.record()


if __name__ == "__main__":
    unittest.main()
