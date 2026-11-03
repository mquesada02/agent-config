# Ticket 297: `audit ledger finding-amend`, driven through the command line (one unit test calls `Ledger.in_force` on a replayed ledger).
import functools
import importlib.machinery
import importlib.util
import json
import os
import sys
import unittest

from audit_support import event, finding_event, link_event, round_event, status_event
from test_ledger import LinkCase
from test_ledger_quote import PLAN, QUOTE, REASON, QuoteCase, flags, reviewed, text_row, tool_row
from test_pre_dispatch import LOOP_3, LOOP_41, PreDispatchCase  # LOOP_3 and LOOP_41 are the two pre-dispatch loop names

AUDIT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit")
QUOTE2 = "the amended line"
REASON2 = f'rests on "{QUOTE2}" and still breaks the build'
REVIEWER = f"I found {QUOTE} and also {QUOTE2} in the spec"
LOOPS = ("code-review", "plan-review-3", "plan-review-4.1", PLAN)


@functools.cache
def load_audit():
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        loader = importlib.machinery.SourceFileLoader("audit_for_amend", AUDIT)
        module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = previous


def aflags(finding_id="P1", reason=REASON2, quote=QUOTE2, raised=False):
    result = ["--id", finding_id, "--reason", reason]
    if quote is not None:
        result += ["--quote", quote]
    if raised:
        result.append("--raised")
    return result


class AmendCase(QuoteCase):
    def setUp(self):
        super().setUp()
        self.rounds = set()
        self.reviewer(text_row(REVIEWER))

    def finding(self, loop=PLAN, kind="Blocking", raised=False, finding_id="P1", quote=QUOTE):
        """Write round 1 of the loop once, then a finding of that round whose reason holds the quote."""
        if loop not in self.rounds:
            self.rounds.add(loop)
            self.round(loop)
        reason = REASON if quote in (None, QUOTE) else f'rests on "{quote}" and breaks the build'
        self.ok("finding", *flags(finding_id, loop=loop, kind=kind, raised=raised, quote=quote, reason=reason))


class RefusalTest(AmendCase):
    def test_an_amendment_of_an_unknown_id_is_refused_and_creates_no_finding(self):
        self.round()
        message = self.refused("finding-amend", *aflags("ghost"))
        self.assertIn("malformed event", message)
        self.assertIn("no finding ghost", message)

    def test_raised_on_an_amendment_of_a_minor_finding_is_refused(self):
        self.finding(kind="Minor", quote=None)
        self.assertIn("only a Blocking finding is raised", self.refused("finding-amend", *aflags(raised=True)))

    def test_a_plan_review_blocking_amendment_without_a_quote_is_refused_as_no_quote(self):
        for loop in LOOPS[1:]:
            with self.subTest(loop):
                self.finding(loop, finding_id=loop)
                self.assertIn("no quote", self.refused("finding-amend", *aflags(loop, quote=None)))

    def test_a_raised_amendment_without_a_quote_is_refused_also_in_code_review(self):
        self.finding("code-review")
        self.assertIn("no quote", self.refused("finding-amend", *aflags(quote=None, raised=True)))

    def test_a_code_review_blocking_amendment_without_a_quote_passes(self):
        self.finding("code-review", quote=None)
        self.ok("finding-amend", *aflags(quote=None))
        self.assertNotIn("quote", self.written()[-1])

    def test_a_minor_plan_review_amendment_without_a_quote_passes(self):
        self.finding(kind="Minor", quote=None)
        self.ok("finding-amend", *aflags(quote=None))

    def test_the_other_flags_and_a_missing_reason_are_refused(self):
        self.finding()
        self.assertIn("not allowed", self.refused("finding-amend", *aflags(), "--loop", PLAN))
        self.assertIn("missing", self.refused("finding-amend", "--id", "P1", "--quote", QUOTE2))

    def test_the_help_lists_the_event_and_its_optional_flags(self):
        text = self.audit("ledger", "--help").stdout.decode()
        line = next(line for line in text.splitlines() if line.strip().startswith("finding-amend"))
        for word in ("--id", "--reason", "[--quote", "[--raised]"):
            self.assertIn(word, line)


class QuoteRuleTest(AmendCase):
    def setUp(self):
        super().setUp()
        self.finding()

    def test_a_quote_that_fails_every_check_is_refused_as_too_short_first(self):
        self.assertIn("quote too short", self.refused("finding-amend", *aflags(quote="abc", reason="no relation")))

    def test_a_quote_not_in_the_reason_is_refused(self):
        self.assertIn("quote not in reason", self.refused("finding-amend", *aflags(quote="some other line", reason="no relation")))

    def test_a_quote_not_in_the_reviewer_text_is_refused(self):
        message = self.refused("finding-amend", *aflags(quote="never written", reason="it is never written anywhere"))
        self.assertIn("finding P1: quote not in reviewer text", message)

    def test_a_missing_reviewer_makes_it_evidence_unavailable(self):
        self.write_ledger("feature", [round_event(1, PLAN, "correctness", ("ghost",)), {**finding_event("P1", PLAN), "reason": REASON}])
        self.assertIn("evidence unavailable", self.refused("finding-amend", *aflags()))

    def test_a_quote_only_in_a_handback_message_passes(self):
        self.reviewer(tool_row("SubagentHandback", {"message": "report: a handback line"}), name="rev2")
        self.write_ledger("feature", [round_event(1, PLAN, "correctness", ("rev2",)), {**finding_event("P1", PLAN), "reason": REASON}])
        self.ok("finding-amend", *aflags(quote="a handback line", reason="rests on a handback line"))

    def test_a_valid_amendment_is_written_with_the_keys_in_order(self):
        self.ok("finding-amend", *aflags())
        event = self.written()[-1]
        self.assertEqual(list(event), ["kind", "time", "id", "reason", "quote"])
        self.assertEqual((event["id"], event["reason"], event["quote"]), ("P1", REASON2, QUOTE2))

    def test_a_raised_amendment_is_written_with_the_raised_key_last(self):
        self.ok("finding-amend", *aflags(quote="a line no reviewer wrote", reason="the map says a line no reviewer wrote", raised=True))
        self.assertEqual(list(self.written()[-1])[-2:], ["quote", "raised"])
        self.assertIs(self.written()[-1]["raised"], True)

    def test_a_raised_amendment_still_needs_an_eight_character_quote_in_its_reason(self):
        self.assertIn("quote too short", self.refused("finding-amend", *aflags(quote="abc", raised=True)))
        self.assertIn("quote not in reason", self.refused("finding-amend", *aflags(quote="not in the reason", raised=True)))

    def test_the_raised_mark_is_never_inherited_so_the_reviewer_text_is_matched(self):
        self.finding(raised=True, finding_id="R1", quote="a map line no reviewer wrote")
        message = self.refused("finding-amend", *aflags("R1", quote="a map line no reviewer wrote", reason="a map line no reviewer wrote"))
        self.assertIn("quote not in reviewer text", message)

    def test_a_quote_given_on_a_code_review_amendment_runs_every_check(self):
        self.finding("code-review", quote=None, finding_id="C1")
        self.assertIn("quote not in reviewer text", self.refused("finding-amend", *aflags("C1", quote="never written", reason="never written")))
        self.ok("finding-amend", *aflags("C1"))

    def test_a_quote_with_a_newline_is_refused_by_the_shape_rule(self):
        self.assertIn("quote", self.refused("finding-amend", *aflags(quote="the amended\nline")))

    def test_a_reviewer_text_that_spans_a_line_break_matches_a_one_line_quote(self):
        self.reviewer(text_row("the broken\nline here"), name="rev3")
        self.write_ledger("feature", [round_event(1, PLAN, "correctness", ("rev3",)), {**finding_event("P1", PLAN), "reason": REASON}])
        self.ok("finding-amend", *aflags(quote="the broken line", reason="rests on the broken line"))

    def test_a_quote_of_eight_raw_characters_that_normalises_to_fewer_is_too_short(self):
        self.assertIn("quote too short", self.refused("finding-amend", *aflags(quote="a  b  c ", reason="a b c")))

    def test_a_quote_can_be_added_to_a_minor_finding(self):
        self.finding(kind="Minor", quote=None, finding_id="M1")
        self.ok("finding-amend", *aflags("M1"))
        self.assertEqual(self.written()[-1]["quote"], QUOTE2)


class AmendLoopsTest(AmendCase):
    def test_every_loop_can_amend_a_finding(self):
        for loop in LOOPS:
            with self.subTest(loop):
                self.finding(loop, finding_id=f"F-{loop}")
                self.ok("finding-amend", *aflags(f"F-{loop}"))

    def test_a_successor_session_can_amend_a_predecessor_finding(self):
        self.register_session("predecessor", [], subagents={"revB": reviewed(text_row(REVIEWER))})
        self.write_ledger("feature", [round_event(1, PLAN, "correctness", ("revB",)), {**finding_event("P1", PLAN), "reason": REASON}])
        self.ok("finding-amend", *aflags())


class InForceTest(AmendCase):
    def test_the_latest_amendment_is_in_force_and_status_and_type_stay(self):
        self.finding()
        self.ok("status", "--finding", "P1", "--status", "deferred")
        self.ok("finding-amend", *aflags())
        self.ok("finding-amend", *aflags(reason=f"{REASON} {QUOTE}", quote=QUOTE))
        ledger = load_audit()._replay(self.raw())
        entry = ledger.findings["P1"]
        self.assertEqual(len(entry["amendments"]), 2)
        self.assertEqual(ledger.in_force("P1"), {"reason": f"{REASON} {QUOTE}", "quote": QUOTE, "raised": False})
        self.assertEqual((entry["status"], entry["event"]["type"], entry["event"]["loc"]), ("deferred", "Blocking", "a.py:1"))

    def test_without_an_amendment_the_original_is_in_force(self):
        self.finding()
        self.assertEqual(load_audit()._replay(self.raw()).in_force("P1"), {"reason": REASON, "quote": QUOTE, "raised": False})

    def test_an_amendment_without_a_quote_leaves_no_quote_in_force(self):
        self.finding("code-review", quote=QUOTE)
        self.ok("finding-amend", *aflags(quote=None, reason="a plain reason"))
        self.assertEqual(load_audit()._replay(self.raw()).in_force("P1"), {"reason": "a plain reason", "quote": None, "raised": False})

    def test_the_raised_mark_in_force_is_the_amendments_own(self):
        self.finding(raised=True, quote="a map line")
        self.ok("finding-amend", *aflags(quote=QUOTE2))
        self.assertIs(load_audit()._replay(self.raw()).in_force("P1")["raised"], False)
        self.ok("finding-amend", *aflags(quote="a map line", reason="the map says a map line", raised=True))
        self.assertIs(load_audit()._replay(self.raw()).in_force("P1")["raised"], True)

    def test_a_finding_amend_line_is_never_a_phase_commit(self):
        self.finding()
        self.ok("finding-amend", *aflags())
        self.assertEqual(load_audit()._replay(self.raw()).commits, [])


class ReplayTest(AmendCase):
    def test_a_ledger_with_amendments_replays_and_reads_no_transcript(self):
        self.write_ledger("feature", [round_event(1, PLAN, "correctness", ("ghost",)), {**finding_event("P1", PLAN, quote=QUOTE), "reason": REASON},
                                      event("finding-amend", id="P1", reason=REASON2, quote=QUOTE2)])
        os.unlink(os.path.join(self.runtime, "sessions.jsonl"))
        self.ok("status", "--finding", "P1", "--status", "fixed")
        self.assertEqual(self.audit("ledger", "show", "--worktree", self.repo).returncode, 0)

    def bad(self, line):
        self.write_ledger("feature", [round_event(1, PLAN, "correctness"), finding_event("P1", PLAN), line])
        return self.refused("status", "--finding", "P1", "--status", "fixed")

    def amend_line(self, **extra):
        return event("finding-amend", **{"id": "P1", "reason": "r", **extra})

    def test_an_amend_line_of_an_unknown_id_is_a_ledger_error(self):
        self.assertIn("no finding ghost", self.bad(self.amend_line(id="ghost")))

    def test_a_raised_amend_line_of_a_minor_finding_is_a_ledger_error(self):
        self.write_ledger("feature", [round_event(1, PLAN, "correctness"), finding_event("P1", PLAN, kind="Minor"),
                                      self.amend_line(raised=True)])
        self.assertIn("only a Blocking finding is raised", self.refused("status", "--finding", "P1", "--status", "fixed"))

    def test_a_raised_key_with_any_value_but_true_is_refused(self):
        for value in (False, 1, "true", None):
            with self.subTest(value=value):
                self.assertIn("bad raised", self.bad(self.amend_line(raised=value)))

    def test_an_unknown_key_on_an_amend_line_is_refused(self):
        self.assertIn("finding-amend event needs exactly", self.bad(self.amend_line(loop=PLAN)))

    def test_an_amend_line_without_a_reason_is_refused(self):
        line = self.amend_line()
        del line["reason"]
        self.assertIn("finding-amend event needs exactly", self.bad(line))


class ShowTest(AmendCase):
    def test_show_prints_the_original_and_every_amendment_in_order_with_the_raised_mark(self):
        self.finding()
        self.ok("finding-amend", *aflags())
        self.ok("finding-amend", *aflags(quote="a map line", reason="the map says a map line", raised=True))
        lines = self.audit("ledger", "show", "--worktree", self.repo).stdout.decode().splitlines()
        events = [json.loads(line) for line in lines[1:]]
        self.assertEqual([event["kind"] for event in events], ["round", "finding", "finding-amend", "finding-amend"])
        self.assertEqual((events[2]["reason"], events[3]["reason"]), (REASON2, "the map says a map line"))
        self.assertNotIn("raised", events[2])
        self.assertIn('"raised":true', lines[-1])


class PreDispatchViewTest(PreDispatchCase):
    def test_the_view_holds_the_amendments_of_its_findings_only(self):
        events = self.plan_events(round_event(loop="code-review"), finding_event("P1", loop=LOOP_3, kind="Minor"),
                                  finding_event("C1"), status_event("P1", "deferred"))
        amend = event("finding-amend", reason="r")
        self.write_ledger("feature", [*events, {**amend, "id": "P1"}, {**amend, "id": "C1"}, {**amend, "id": "P1"}])
        self.assertEqual(self.pre_dispatch().returncode, 0)
        self.assertIn("6 events, 1 findings", self.pd_item("S3")["evidence"])

    def test_a_finding_amend_line_does_not_count_as_a_phase_commit(self):
        amend = event("finding-amend", id="P1", reason="r")
        self.write_ledger("feature", self.plan_events(finding_event("P1", loop=LOOP_41, kind="Minor"), status_event("P1", "fixed"), amend))
        self.assertEqual(self.pre_dispatch().returncode, 0)


class LinkedBlockTest(LinkCase):
    def test_the_linked_block_holds_the_amendments_of_its_linked_findings_only(self):
        amend = event("finding-amend", reason="the amended reason")
        self.source([round_event(loop=PLAN), finding_event("P1", loop=PLAN), round_event(), finding_event("C1"),
                     {**amend, "id": "P1"}, {**amend, "id": "C1"}, status_event("P1")])
        self.write_ledger("feature", [round_event(), link_event()], url=self.url)
        lines = self.audit("ledger", "show", "--worktree", self.repo).stdout.decode().splitlines()
        block = lines[lines.index(next(line for line in lines if line.startswith("linked from"))) + 1:]
        self.assertEqual([json.loads(line)["kind"] for line in block], ["round", "finding", "finding-amend", "status"])
        self.assertEqual(json.loads(block[2])["id"], "P1")


if __name__ == "__main__":
    unittest.main()
