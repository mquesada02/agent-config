# Ticket 298: the S10 quote audit item, driven through `audit check`, `audit record` and `audit record --pre-dispatch`.
import os
import unittest

from audit_support import AuditCase, PASSING_LLM, event, finding_event, link_event, round_event, status_event
from test_ledger_quote import reviewed, text_row
from test_pre_dispatch import SID, LOOP_3, LOOP_41, PreDispatchCase, L1_ONLY

PLAN = "plan-review-5.3"
QUOTE = "the quoted line"
REASON = f'rests on "{QUOTE}" and breaks the build'
REVIEWER_TEXT = f"I found {QUOTE} in the spec"
WS = "orca-ide orchestration worker-start --task t1 --agent claude"


def fe(finding_id="P1", loop=PLAN, kind="Blocking", n=1, quote=None, reason=None, raised=False):
    """A finding line as a hand edit or an old session leaves it: it holds a quote only when given."""
    result = finding_event(finding_id, loop=loop, kind=kind, n=n)
    if reason is not None:
        result["reason"] = reason
    if quote is not None:
        result["quote"] = quote
    if raised:
        result["raised"] = True
    return result


def good(finding_id="P1", **kwargs):
    return fe(finding_id, quote=QUOTE, reason=REASON, **kwargs)


def amend(finding_id="P1", reason=REASON, quote=QUOTE, raised=False):
    result = event("finding-amend", id=finding_id, reason=reason)
    if quote is not None:
        result["quote"] = quote
    if raised:
        result["raised"] = True
    return result


class S10Case(AuditCase):
    default_ledger = False

    def setUp(self):
        super().setUp()
        self.start_branch("feature", "feat: a")
        self.add_subagent("default-session", "rev1", reviewed(text_row(REVIEWER_TEXT)))

    def put(self, *events, branch="feature"):
        self.write_ledger(branch, [*events])

    def check_lines(self):
        result = self.audit("check", "--worktree", self.repo, "--base", "main")
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.decode().splitlines()

    def check_item(self, name="S10"):
        """(result word, evidence text) of an item in the `check` output."""
        lines = self.check_lines()
        start = next(index for index, line in enumerate(lines) if line.startswith(name + " "))
        evidence = []
        for line in lines[start + 1:]:
            if not line.startswith("  "):
                break
            evidence.append(line[2:])
        return lines[start].split()[1], "\n".join(evidence)

    def passes(self):
        status, evidence = self.check_item()
        self.assertEqual(status, "pass", evidence)
        return evidence

    def fails(self):
        status, evidence = self.check_item()
        self.assertEqual(status, "fail", evidence)
        return evidence


class S10PassTest(S10Case):
    def test_valid_quotes_pass_and_the_evidence_counts_findings_and_quotes(self):
        self.put(round_event(loop=PLAN), good("P1"), fe("P2", kind="Minor"))
        self.assertEqual(self.passes(), "2 findings judged, 1 with a quote checked")

    def test_minor_and_code_review_findings_without_quotes_pass_and_read_no_transcript(self):
        os.remove(os.path.join(self.root, "projects", "default-session", "subagents", "agent-rev1.jsonl"))
        self.put(round_event(loop=PLAN), round_event(loop="code-review"), fe("P1", kind="Minor"), fe("I1", loop="code-review"))
        self.assertEqual(self.passes(), "2 findings judged, 0 with a quote checked")


class S10FailTest(S10Case):
    def test_a_plan_review_blocking_finding_without_a_quote_fails_also_on_an_old_line(self):
        for loop in ("plan-review-3", "plan-review-4.1", PLAN):
            with self.subTest(loop):
                self.put(round_event(loop=loop), fe("P1", loop=loop))
                self.assertEqual(self.fails(), "P1: no quote")

    def test_a_raised_finding_without_a_quote_fails(self):
        for loop in ("code-review", PLAN):
            with self.subTest(loop):
                self.put(round_event(loop=loop), fe("R1", loop=loop, raised=True))
                self.assertEqual(self.fails(), "R1: no quote")

    def test_each_hand_edit_names_its_cause(self):
        for cause, quote, reason in (("quote too short", "abc", REASON), ("quote not in reason", "some other line", REASON),
                                     ("quote not in reviewer text", "never written", "it is never written anywhere")):
            with self.subTest(cause):
                self.put(round_event(loop=PLAN), fe("P1", quote=quote, reason=reason))
                self.assertEqual(self.fails(), f"P1: {cause}")

    def test_a_quote_that_fails_several_checks_names_the_first_cause(self):
        self.put(round_event(loop=PLAN), fe("P1", quote="abc", reason="no relation"))
        self.assertEqual(self.fails(), "P1: quote too short")

    def test_a_finding_without_a_round_event_makes_the_ledger_unavailable(self):
        self.put(round_event(loop="code-review"), good("P1"))
        status, s3 = self.check_item("S3")
        self.assertEqual(status, "fail")
        self.assertTrue(s3.startswith("invalid ledger:"), s3)
        self.assertEqual(self.fails(), s3)


class S10EvidenceTest(S10Case):
    def test_a_missing_reviewer_transcript_is_evidence_unavailable_per_finding(self):
        self.put(round_event(loop=PLAN, reviewers=("gone",)), good("P1"), round_event(2, loop=PLAN),
                 fe("P2", n=2, quote="never written", reason="it is never written anywhere"))
        self.assertEqual(self.fails().splitlines(), ["P1: evidence unavailable: a reviewer transcript of the round cannot be read",
                                                     "P2: quote not in reviewer text"])

    def test_a_raised_finding_passes_with_its_transcripts_missing(self):
        self.put(round_event(loop=PLAN, reviewers=("gone",)), good("R1", raised=True))
        self.assertEqual(self.passes(), "1 findings judged, 1 with a quote checked")

    def test_a_reviewer_of_another_registered_session_is_found(self):
        self.register_session("other-session", [], subagents={"rev9": reviewed(text_row(REVIEWER_TEXT))})
        self.put(round_event(loop=PLAN, reviewers=("rev9",)), good("P1"))
        self.passes()


class S10AmendTest(S10Case):
    def test_an_amendment_repairs_the_finding(self):
        self.put(round_event(loop=PLAN), fe("P1"))
        self.fails()
        self.put(round_event(loop=PLAN), fe("P1"), amend())
        self.passes()

    def test_a_bad_latest_amendment_fails_though_the_original_was_good(self):
        self.put(round_event(loop=PLAN), good("P1"), amend(reason="it is never written anywhere", quote="never written"))
        self.assertEqual(self.fails(), "P1: quote not in reviewer text")

    def test_the_latest_of_two_amendments_decides(self):
        self.put(round_event(loop=PLAN), fe("P1"), amend(reason="it is never written anywhere", quote="never written"), amend())
        self.passes()


class S10LinkedTest(S10Case):
    def setUp(self):
        super().setUp()
        self.add_subagent("default-session", "rev7", reviewed(text_row(REVIEWER_TEXT)))

    def linked(self, *source_events):
        self.put(round_event(loop="code-review"), link_event(source="src", ticket="T-1"))
        if source_events:
            self.put(*source_events, branch="src")

    def test_linked_findings_are_checked_on_the_values_in_force(self):
        self.linked(round_event(loop=PLAN, reviewers=("rev7",)), fe("P1"), amend())
        self.assertEqual(self.passes(), "1 findings judged, 1 with a quote checked")

    def test_a_quote_deleted_in_the_source_ledger_fails(self):
        self.linked(round_event(loop=PLAN, reviewers=("rev7",)), fe("P1"))
        self.assertEqual(self.fails(), "P1 (linked): no quote")

    def test_a_missing_linked_ledger_is_evidence_unavailable(self):
        self.linked()
        self.assertIn("evidence unavailable: linked ledger unavailable", self.fails())

    def test_a_linked_finding_without_a_round_event_makes_the_linked_ledger_unavailable(self):
        self.linked(round_event(loop="code-review"), good("P1"))
        self.assertIn("evidence unavailable: linked ledger unavailable (ledger of src is invalid", self.fails())


class S10OrderTest(S10Case):
    def test_check_and_record_list_s10_after_s9(self):
        self.put(round_event(loop="code-review"))
        names = [line.split()[0] for line in self.check_lines() if line[:1] in "SX" and len(line.split()) == 2]
        self.assertEqual(names, ["S1", "S2", "S3", "S4", "S5", "S6", "XC", "S7", "S8", "S9", "S10"])
        self.record()
        ids = [item["id"] for item in self.read_record(self.git("rev-parse", "HEAD"))["items"]]
        self.assertEqual(ids, ["S1", "S2", "S3", "S4", "S5", "S6", "XC", "S7", "S8", "S9", "S10", "L1", "L2", "L3", "L4", "L5", "L6"])

    def test_an_unusable_ledger_fails_s10_in_check_and_record(self):
        self.put(round_event(loop="code-review"), "{not json")
        _, s3 = self.check_item("S3")
        self.assertEqual(self.fails(), s3)
        self.record()
        tip = self.git("rev-parse", "HEAD")
        self.assertEqual((self.item(tip, "S10")["result"], self.item(tip, "S10")["evidence"]), ("fail", self.item(tip, "S3")["evidence"]))

    def test_the_header_comments_name_s10(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit"), encoding="utf-8") as handle:
            header = handle.read().split("import json", 1)[0]
        self.assertEqual(header.count("S1-S10"), 2)
        self.assertNotIn("S1-S9", header)


class S10PreDispatchTest(PreDispatchCase):
    def test_the_pre_dispatch_record_lists_s10_after_xc(self):
        self.assertEqual(self.pre_dispatch().returncode, 0)
        self.assertEqual([item["id"] for item in self.read_pre_dispatch()["items"]], ["S3", "S5", "S7", "XC", "S10", "L1"])

    def test_it_judges_the_pre_dispatch_view_only(self):
        outside = [round_event(loop="code-review"), fe("I1", loop="code-review", raised=True), round_event(loop=PLAN), fe("T1")]
        self.write_ledger("feature", self.plan_events(*outside))
        self.pre_dispatch()
        self.assertEqual(self.pd_item("S10")["result"], "pass", self.pd_item("S10")["evidence"])
        self.assertEqual(self.pd_item("S10")["evidence"], "0 findings judged, 0 with a quote checked")
        self.write_ledger("feature", self.plan_events(fe("P1", loop=LOOP_3), status_event("P1")))
        self.assertEqual(self.pre_dispatch().returncode, 1)
        self.assertEqual(self.pd_item("S10")["result"], "fail")
        self.assertEqual(self.pd_item("S10")["evidence"], "P1: no quote")

    def test_an_unusable_ledger_fails_s10_in_the_pre_dispatch_record(self):
        self.write_ledger("feature", [*self.plan_events(), "{not json"])
        self.pre_dispatch()
        self.assertEqual(self.pd_item("S10")["result"], "fail")
        self.assertEqual(self.pd_item("S10")["evidence"], self.pd_item("S3")["evidence"])


class S10GateFlowTest(PreDispatchCase):
    def test_a_failed_pre_dispatch_record_passes_after_the_findings_are_amended(self):
        self.add_subagent("default-session", "rev1", reviewed(text_row(REVIEWER_TEXT)))
        self.write_ledger("feature", self.plan_events(fe("P1", loop=LOOP_3), status_event("P1")))
        self.write_llm({"L1": {"result": "fail", "evidence": "P1 has no quoted line"}})
        self.assertEqual(self.pre_dispatch().returncode, 1)
        self.assertIn("failed pre-dispatch record", self.denial(self.gate(WS, session_id=SID)))
        amended = self.ledger("finding-amend", "--id", "P1", "--reason", REASON, "--quote", QUOTE)
        self.assertEqual(amended.returncode, 0, amended.stderr)
        self.write_llm(L1_ONLY)
        rerun = self.pre_dispatch()
        self.assertEqual(rerun.returncode, 0, rerun.stdout)
        self.assertIsNone(self.denial(self.gate(WS, session_id=SID)))


if __name__ == "__main__":
    unittest.main()
