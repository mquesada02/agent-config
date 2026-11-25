# Issue 1026: the `round-retire` ledger event. It writes through the command line and lets XC accept an out-of-order round
# that a later round of the same phase, in the correct order, replaces.
import json
import unittest

from audit_support import EARLY, LATE, event, finding_event, round_event, subagent_rows, verdict_event
import test_pre_dispatch
from test_ledger import LedgerCase
from test_ledger_checks import LedgerChecksCase

ROUND = ("--loop", "code-review", "--phase", "correctness")


def retire(n, by, **extra):
    return event("round-retire", loop="code-review", phase="correctness", round=n, by=by, **extra)


class RoundRetireWriteTest(LedgerCase):
    def setUp(self):
        super().setUp()
        for number in (1, 2, 3):
            self.ok("round", *ROUND, "--round", str(number), "--reviewer", "rev1")

    def test_a_retire_of_an_earlier_round_by_a_later_round_is_written_with_a_number_for_by(self):
        self.ok("round-retire", *ROUND, "--round", "1", "--by", "3")
        written = self.written()[-1]
        self.assertEqual({key: written[key] for key in ("kind", "loop", "phase", "round", "by")},
                         {"kind": "round-retire", "loop": "code-review", "phase": "correctness", "round": 1, "by": 3})
        shown = self.audit("ledger", "show", "--worktree", self.repo).stdout.decode().splitlines()
        self.assertEqual(json.loads(shown[-1])["by"], 3)

    def test_a_missing_round_n_is_refused(self):
        self.assertIn("no round event for round 5", self.refused("round-retire", *ROUND, "--round", "4", "--by", "5"))

    def test_a_missing_round_m_is_refused(self):
        self.assertIn("no round event for round 4", self.refused("round-retire", *ROUND, "--round", "1", "--by", "4"))

    def test_a_round_of_another_phase_is_missing(self):
        self.assertIn("no round event", self.refused("round-retire", "--loop", "code-review", "--phase", "final", "--round", "1", "--by", "2"))

    def test_m_must_be_after_n(self):
        self.assertIn("not after round 2", self.refused("round-retire", *ROUND, "--round", "2", "--by", "2"))
        self.assertIn("not after round 3", self.refused("round-retire", *ROUND, "--round", "3", "--by", "2"))

    def test_a_round_is_retired_once(self):
        self.ok("round-retire", *ROUND, "--round", "1", "--by", "2")
        self.assertIn("retired already", self.refused("round-retire", *ROUND, "--round", "1", "--by", "3"))

    def test_by_must_be_a_whole_round_number(self):
        for value in ("x", "0", "-1", "2.0", "02"):
            with self.subTest(value=value):
                self.assertIn("bad by", self.refused("round-retire", *ROUND, "--round", "1", "--by", value))

    def test_a_missing_flag_and_a_foreign_flag_are_refused(self):
        self.refused("round-retire", *ROUND, "--round", "1")
        self.refused("round-retire", *ROUND, "--round", "1", "--by", "2", "--reviewer", "rev1")

    def test_the_retire_does_not_change_the_round_numbering(self):
        self.ok("round-retire", *ROUND, "--round", "1", "--by", "2")
        self.refused("round", *ROUND, "--round", "3", "--reviewer", "rev1")
        self.ok("round", *ROUND, "--round", "4", "--reviewer", "rev1")


class RoundRetireXcTest(LedgerChecksCase):
    """Round 1 is stamped EARLY. A reviewer that starts at EARLY is out of order for round 2 or later; one that starts at LATE is in order."""

    def setUp(self):
        super().setUp()
        self.agents(late=subagent_rows(start=LATE), late2=subagent_rows(start=LATE), early=subagent_rows(start=EARLY),
                    early2=subagent_rows(start=EARLY), opus=subagent_rows(model="claude-opus-5-5", start=LATE))

    def xc(self, events):
        return self.items(events)["XC"]

    def test_an_out_of_order_round_fails_without_a_retire(self):
        item = self.xc([round_event(1), round_event(2, reviewers=["early"]), round_event(3, reviewers=["late"])])
        self.assertEqual(item["result"], "fail")
        self.assertIn("reviewer early of code-review correctness round 2: started before the previous round", item["evidence"])

    def test_an_in_order_replacement_retires_it(self):
        events = [round_event(1), round_event(2, reviewers=["early"]), round_event(3, reviewers=["late"]), retire(2, 3)]
        self.check(self.items(events), "XC", "pass", "3 reviewers and verifiers checked")

    def test_a_replacement_that_is_also_out_of_order_still_fails(self):
        events = [round_event(1), round_event(2, reviewers=["early"]), round_event(3, reviewers=["early2"]), retire(2, 3)]
        item = self.xc(events)
        self.assertEqual(item["result"], "fail")
        self.assertIn("reviewer early of code-review correctness round 2: started before the previous round", item["evidence"])
        self.assertIn("reviewer early2 of code-review correctness round 3: started before the previous round", item["evidence"])

    def test_one_out_of_order_reviewer_of_the_replacement_is_enough_to_fail(self):
        events = [round_event(1), round_event(2, reviewers=["early"]), round_event(3, reviewers=["late", "early2"]), retire(2, 3)]
        self.assertEqual(self.xc(events)["result"], "fail")

    def test_a_chain_of_retires_cannot_pass_an_out_of_order_round(self):
        # round 4 is in order and retires round 3, but round 3 is out of order itself, so it cannot replace round 2
        events = [round_event(1), round_event(2, reviewers=["early"]), round_event(3, reviewers=["early2"]), round_event(4, reviewers=["late"]),
                  retire(2, 3), retire(3, 4)]
        item = self.xc(events)
        self.assertEqual(item["result"], "fail")
        self.assertIn("reviewer early of code-review correctness round 2: started before the previous round", item["evidence"])
        self.assertNotIn("reviewer early2", item["evidence"])

    def test_a_retire_by_a_round_that_is_not_the_next_one_works_when_that_round_is_in_order(self):
        events = [round_event(1), round_event(2, reviewers=["early"]), round_event(3, reviewers=["late"]),
                  round_event(4, reviewers=["late2"]), retire(2, 4)]
        self.check(self.items(events), "XC", "pass")

    def test_every_other_check_of_the_retired_round_still_runs(self):
        events = [round_event(1), round_event(2, reviewers=["opus", "ghost"]), round_event(3, reviewers=["late"]), retire(2, 3)]
        item = self.xc(events)
        self.assertEqual(item["result"], "fail")
        self.assertIn("reviewer opus of code-review correctness round 2: not a Sonnet subagent", item["evidence"])
        self.assertIn("reviewer ghost of code-review correctness round 2: not a subagent of an audited transcript", item["evidence"])

    def test_a_replacement_reviewer_that_is_not_a_subagent_does_not_replace(self):
        events = [round_event(1), round_event(2, reviewers=["early"]), round_event(3, reviewers=["ghost"]), retire(2, 3)]
        item = self.xc(events)
        self.assertEqual(item["result"], "fail")
        self.assertIn("reviewer early of code-review correctness round 2: started before the previous round", item["evidence"])

    def test_a_retire_does_not_reach_another_phase_or_loop(self):
        events = [round_event(1), round_event(2, reviewers=["early"]), round_event(3, reviewers=["late"]),
                  round_event(1, phase="final", reviewers=["early2"]), round_event(1, loop="plan-review-3", reviewers=["early2"]), retire(2, 3)]
        item = self.xc(events)
        self.assertEqual(item["result"], "fail")
        self.assertIn("round 1: started before the previous round", item["evidence"])
        self.assertNotIn("round 2", item["evidence"])

    def test_a_verifier_of_a_finding_of_the_retired_round_follows_the_retire(self):
        events = [round_event(1), round_event(2, reviewers=["late"]), finding_event("I1", n=2), verdict_event("I1", "early"),
                  round_event(3, reviewers=["late2"])]
        self.assertIn("verifier early of I1: started before the previous round", self.xc(events)["evidence"])
        self.check(self.items(events + [retire(2, 3)]), "XC", "pass")

    def test_a_retire_naming_a_round_that_is_missing_makes_the_ledger_invalid_and_xc_fails_closed(self):
        events = [round_event(1), round_event(2, reviewers=["early"]), retire(2, 3)]
        item = self.xc(events)
        self.assertEqual(item["result"], "fail")
        self.assertIn("evidence unavailable: ledger is invalid", item["evidence"])

    def test_a_replacement_with_an_unreadable_start_time_does_not_replace(self):
        rows = subagent_rows(start=LATE)
        del rows[0]["timestamp"]
        self.agents(nostart=rows)
        events = [round_event(1), round_event(2, reviewers=["early"]), round_event(3, reviewers=["nostart"]), retire(2, 3)]
        item = self.xc(events)
        self.assertEqual(item["result"], "fail")
        self.assertIn("reviewer early of code-review correctness round 2: started before the previous round", item["evidence"])


class RoundRetirePreDispatchTest(test_pre_dispatch.PreDispatchCase):
    def test_the_pre_dispatch_view_keeps_the_retire(self):
        loop = test_pre_dispatch.LOOP_3
        self.register_session("s2", [], subagents={"early": subagent_rows(start=EARLY), "late": subagent_rows(start=LATE)})
        self.write_ledger("feature", [round_event(1, loop=loop), round_event(2, loop=loop, reviewers=("early",)),
                                       round_event(3, loop=loop, reviewers=("late",)), round_event(loop=test_pre_dispatch.LOOP_41),
                                       event("round-retire", loop=loop, phase="correctness", round=2, by=3)])
        self.pre_dispatch()
        self.assertEqual(self.pd_item("XC")["result"], "pass", self.pd_item("XC")["evidence"])


if __name__ == "__main__":
    unittest.main()
