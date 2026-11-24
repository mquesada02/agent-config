# Issue 890: the `superseded` status of `audit ledger status --by`, driven through the command line, and its S3 and brief text.
import json
import os
import unittest

from audit_support import finding_event, round_event, status_event
from test_brief import read_brief
from test_ledger import LedgerCase
from test_ledger_checks import LedgerChecksCase

FLAGS = ("--loop", "code-review", "--phase", "correctness", "--round", "1", "--loc", "a.py:3", "--reason", "it breaks")


class SupersededWriteTest(LedgerCase):
    def setUp(self):
        super().setUp()
        self.ok("round", "--loop", "code-review", "--phase", "correctness", "--round", "1", "--reviewer", "rev1")
        self.ok("finding", "--id", "A", "--type", "Minor", *FLAGS)
        self.ok("finding", "--id", "B", "--type", "Blocking", *FLAGS)

    def supersede(self, finding="A", by="B"):
        return ("--finding", finding, "--status", "superseded", "--by", by)

    def test_a_superseded_status_names_a_blocking_finding_and_both_stay_on_the_ledger(self):
        self.ok("status", "--finding", "B", "--status", "fixed")
        self.ok("status", *self.supersede())
        events = self.written()
        self.assertEqual({key: events[-1][key] for key in ("kind", "finding", "status", "by")},
                         {"kind": "status", "finding": "A", "status": "superseded", "by": "B"})
        self.assertEqual([event["id"] for event in events if event["kind"] == "finding"], ["A", "B"])
        shown = self.audit("ledger", "show", "--worktree", self.repo).stdout.decode().splitlines()
        self.assertEqual(json.loads(shown[-1])["by"], "B")

    def test_a_missing_replacement_is_refused(self):
        self.assertIn("no finding C", self.refused("status", *self.supersede(by="C")))

    def test_a_minor_replacement_is_refused(self):
        self.ok("finding", "--id", "M", "--type", "Minor", *FLAGS)
        self.assertIn("not Blocking", self.refused("status", *self.supersede(by="M")))

    def test_a_blocking_finding_is_never_superseded_not_even_by_itself(self):
        self.ok("finding", "--id", "C", "--type", "Blocking", *FLAGS)
        self.assertIn("not Minor", self.refused("status", *self.supersede(finding="B", by="C")))
        self.assertIn("not Minor", self.refused("status", *self.supersede(finding="B", by="B")))

    def test_a_replacement_of_another_loop_is_refused(self):
        self.ok("round", "--loop", "plan-review-3", "--phase", "correctness", "--round", "1", "--reviewer", "rev1")
        self.ok("finding", "--id", "P", "--type", "Minor", "--loop", "plan-review-3", "--phase", "correctness", "--round", "1",
                "--loc", "a.py:3", "--reason", "it breaks")
        self.assertIn("another loop", self.refused("status", *self.supersede(finding="P")))

    def test_by_without_superseded_and_superseded_without_by_are_refused(self):
        self.assertIn("by if and only if", self.refused("status", "--finding", "A", "--status", "deferred", "--by", "B"))
        self.assertIn("by if and only if", self.refused("status", "--finding", "A", "--status", "superseded"))

    def test_a_later_status_clears_the_replacement(self):
        self.ok("status", *self.supersede())
        self.ok("status", "--finding", "A", "--status", "deferred")
        self.assertNotIn("by", self.written()[-1])


class SupersededS3Test(LedgerChecksCase):
    def events(self, b_status, extra=()):
        return [round_event(), finding_event("A", kind="Minor"), finding_event("B"), status_event("B", b_status),
                status_event("A", "superseded", by="B"), *extra]

    def test_a_replacement_closed_as_fixed_passes(self):
        self.check(self.items(self.events("fixed")), "S3", "pass")

    def test_a_replacement_that_is_not_fixed_fails_closed(self):
        for status in ("rejected", "deferred"):
            with self.subTest(status):
                self.check(self.items(self.events(status)), "S3", "fail", "1 superseded findings have no Blocking finding closed as fixed")

    def test_a_replacement_without_a_status_fails_closed(self):
        events = self.events("fixed")
        del events[3]
        self.check(self.items(events), "S3", "fail", "superseded by B")

    def test_a_chain_or_a_cycle_is_refused_when_the_ledger_is_replayed(self):
        """Only a Minor finding is superseded and only a Blocking one supersedes, so the replacement is never itself superseded."""
        chain = self.events("fixed") + [finding_event("C"), status_event("B", "superseded", by="C")]
        cycle = self.events("fixed")[:3] + [status_event("A", "superseded", by="B"), status_event("B", "superseded", by="A")]
        for raw in (chain, cycle):
            self.check(self.items(raw=raw), "S3", "fail", "not Minor")


class SupersededTextTest(unittest.TestCase):
    def test_the_brief_names_the_l1_and_l3_rules(self):
        for phrase in ("A superseded finding A", "`\"by\":\"<B>\"`", "closed as fixed", "A passes only when B describes the same defect as A (the same location or the same quoted line, and a reason that covers the evidence of A)", "a chain or a cycle", "is in another loop",
                       "A superseded finding is closed, not deferred", "separate \"superseded\" list"):
            with self.subTest(phrase):
                self.assertIn(phrase, read_brief())

    def test_section_six_names_the_status_and_its_rule(self):
        from test_claude_md import ROOT_CLAUDE_MD, read, section

        bullet = [line for line in section(read(ROOT_CLAUDE_MD), 6).splitlines() if line.startswith("- `status`:")][0]
        for phrase in ("superseded", "--by <B>", "refuses it unless A is Minor, B exists, B is Blocking and B is not A", "of the same loop", "closed as fixed",
                       "lists A as superseded, not as deferred"):
            with self.subTest(phrase):
                self.assertIn(phrase, bullet)


if __name__ == "__main__":
    unittest.main()
