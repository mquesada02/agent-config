# Ticket 296: the write-time quote check of `audit ledger finding` (--quote, --raised), driven through the command line.
import json
import os
import unittest

from audit_support import EARLY, VERSION, AuditCase, finding_event, round_event, stamp, subagent_rows
from test_ledger import LedgerCase

PLAN = "plan-review-5.3"
QUOTE = "the quoted line"
REASON = f'rests on "{QUOTE}" and breaks the build'


def text_row(text, seconds=0):
    return {"type": "assistant", "timestamp": stamp(seconds), "version": VERSION,
            "message": {"model": "claude-sonnet-5-5", "content": [{"type": "text", "text": text}]}}


def tool_row(name, tool_input, seconds=0):
    return {"type": "assistant", "timestamp": stamp(seconds), "version": VERSION,
            "message": {"model": "claude-sonnet-5-5", "content": [{"type": "tool_use", "id": f"c{seconds}", "name": name, "input": tool_input}]}}


def result_text_row(text, seconds=0):
    return {"type": "user", "timestamp": stamp(seconds), "version": VERSION,
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"c{seconds}", "content": text}]}}


def user_text_row(text, seconds=0):
    return {"type": "user", "timestamp": stamp(seconds), "version": VERSION, "message": {"role": "user", "content": text}}


def reviewed(*rows):
    return [*subagent_rows()[:1], *rows]


def flags(finding_id="P1", loop=PLAN, kind="Blocking", reason=REASON, quote=QUOTE, raised=False, number="1"):
    result = ["--id", finding_id, "--loop", loop, "--phase", "correctness", "--round", number, "--loc", "a.py:1", "--type", kind,
              "--reason", reason]
    if quote is not None:
        result += ["--quote", quote]
    if raised:
        result.append("--raised")
    return result


class QuoteCase(LedgerCase):
    def round(self, loop=PLAN, reviewers=("rev1",), number="1"):
        self.ok("round", "--loop", loop, "--phase", "correctness", "--round", number, *[a for r in reviewers for a in ("--reviewer", r)])

    def reviewer(self, *rows, name="rev1", session="default-session"):
        return self.add_subagent(session, name, reviewed(*rows))

    def finding(self, **kwargs):
        return flags(**kwargs)


class RequiredQuoteTest(QuoteCase):
    def test_a_plan_review_blocking_finding_without_a_quote_is_refused_as_no_quote(self):
        for loop in ("plan-review-3", "plan-review-4.1", PLAN):
            with self.subTest(loop):
                self.round(loop)
                self.assertIn("no quote", self.refused("finding", *flags(loop=loop, quote=None)))

    def test_a_minor_plan_review_finding_needs_no_quote(self):
        self.round()
        self.ok("finding", *flags(kind="Minor", quote=None))

    def test_a_code_review_finding_that_is_not_raised_needs_no_quote(self):
        self.round("code-review")
        self.ok("finding", *flags(loop="code-review", quote=None))
        self.assertNotIn("quote", self.written()[-1])

    def test_an_empty_quote_is_refused_by_the_shape_rule(self):
        self.round()
        self.assertIn("quote", self.refused("finding", *flags(quote="")))


class CheckOrderTest(QuoteCase):
    def setUp(self):
        super().setUp()
        self.reviewer(text_row(f"I found {QUOTE} in the spec"))
        self.round()

    def test_a_quote_that_fails_every_check_is_refused_as_too_short_first(self):
        self.assertIn("quote too short", self.refused("finding", *flags(quote="abc", reason="no relation")))

    def test_a_long_enough_quote_that_is_not_in_the_reason_is_refused_as_not_in_reason(self):
        self.assertIn("quote not in reason", self.refused("finding", *flags(quote="some other line", reason="no relation")))

    def test_a_quote_that_is_in_the_reason_but_not_in_the_reviewer_text_is_refused(self):
        message = self.refused("finding", *flags(quote="never written", reason="it is never written anywhere"))
        self.assertIn("quote not in reviewer text", message)

    def test_a_quote_in_the_reason_and_the_reviewer_text_passes(self):
        self.ok("finding", *flags())
        self.assertEqual(self.written()[-1]["quote"], QUOTE)
        self.assertNotIn("raised", self.written()[-1])

    def test_a_quote_given_on_a_minor_finding_runs_every_check(self):
        self.assertIn("quote not in reviewer text", self.refused("finding", *flags(kind="Minor", quote="never written", reason="never written")))
        self.ok("finding", *flags(finding_id="P2", kind="Minor"))

    def test_a_quote_given_on_a_code_review_finding_runs_every_check(self):
        self.round("code-review")
        self.assertIn("quote not in reviewer text",
                      self.refused("finding", *flags(loop="code-review", quote="never written", reason="never written")))


class ReviewerTextTest(QuoteCase):
    def passes(self, *rows):
        self.reviewer(*rows)
        self.round()
        self.ok("finding", *flags())

    def refuses(self, *rows):
        self.reviewer(*rows)
        self.round()
        return self.refused("finding", *flags())

    def test_a_quote_in_the_assistant_text_passes(self):
        self.passes(text_row(f"the report says {QUOTE}."))

    def test_a_quote_only_in_a_subagent_handback_message_passes(self):
        self.passes(tool_row("SubagentHandback", {"message": f"final report: {QUOTE}"}))

    def test_a_quote_only_in_a_tool_result_is_refused(self):
        self.assertIn("quote not in reviewer text", self.refuses(result_text_row(f"the document holds {QUOTE}")))

    def test_a_quote_only_in_another_tool_call_input_is_refused(self):
        self.assertIn("quote not in reviewer text", self.refuses(tool_row("Bash", {"command": f"echo {QUOTE}"})))

    def test_a_quote_only_in_a_handback_input_other_than_message_is_refused(self):
        self.assertIn("quote not in reviewer text", self.refuses(tool_row("SubagentHandback", {"note": QUOTE})))

    def test_a_quote_only_in_a_user_row_is_refused(self):
        self.assertIn("quote not in reviewer text", self.refuses(user_text_row(f"please check {QUOTE}")))

    def test_a_quote_in_a_reviewer_of_another_round_is_refused(self):
        self.reviewer(text_row("nothing useful"), name="rev1")
        self.add_subagent("default-session", "rev2", reviewed(text_row(QUOTE)))
        self.round()
        self.round(reviewers=("rev2",), number="2")
        self.assertIn("quote not in reviewer text", self.refused("finding", *flags()))
        self.ok("finding", *flags(number="2"))

    def test_a_quote_in_any_one_reviewer_of_the_round_passes(self):
        self.reviewer(text_row("nothing useful"))
        self.add_subagent("default-session", "rev2", reviewed(text_row(QUOTE)))
        self.round(reviewers=("rev1", "rev2"))
        self.ok("finding", *flags())

    def test_a_reviewer_text_that_spans_a_line_break_matches_a_one_line_quote(self):
        self.passes(text_row("the report holds the quoted\n   line here"))

    def test_a_quote_split_by_a_backslash_newline_matches(self):
        self.reviewer(text_row("a long quo\\\nted statement"))
        self.round()
        self.ok("finding", *flags(quote="a long quoted statement", reason="the text a long quoted statement breaks"))

    def test_an_assistant_row_with_string_content_makes_the_reviewer_unreadable(self):
        row = text_row("x")
        row["message"]["content"] = QUOTE
        self.reviewer(row)
        self.round()
        self.assertIn("evidence unavailable", self.refused("finding", *flags()))

    def test_other_quote_marks_in_the_reviewer_text_are_ignored(self):
        self.reviewer(text_row("it says 'the quoted line' there"))
        self.round()
        self.ok("finding", *flags())


class NormalisingTest(QuoteCase):
    def test_a_quote_with_a_newline_is_refused_by_the_shape_rule(self):
        self.reviewer(text_row("the quoted\nline"))
        self.round()
        message = self.refused("finding", *flags(quote="the quoted\nline", reason="the quoted line"))
        self.assertIn("bad quote", message)

    def test_a_quote_of_eight_raw_characters_that_normalises_to_fewer_is_too_short(self):
        self.reviewer(text_row("abcd"))
        self.round()
        self.assertIn("quote too short", self.refused("finding", *flags(quote="'a'b'c'd", reason="abcd")))

    def test_a_quote_of_exactly_eight_normalised_characters_is_long_enough(self):
        self.reviewer(text_row("abcdefgh"))
        self.round()
        self.ok("finding", *flags(quote="abcdefgh", reason="the abcdefgh text"))
        self.assertIn("quote too short", self.refused("finding", *flags(finding_id="P2", quote="abcdefg", reason="the abcdefg text")))


class UnreadableReviewerTest(QuoteCase):
    def test_a_readable_reviewer_with_the_quote_passes_when_another_cannot_be_found(self):
        self.reviewer(text_row(QUOTE))
        self.write_ledger("feature", [round_event(1, PLAN, "correctness", ("rev1", "ghost"))])
        self.ok("finding", *flags())

    def test_no_readable_reviewer_with_the_quote_and_one_missing_is_evidence_unavailable(self):
        self.reviewer(text_row("nothing"))
        self.write_ledger("feature", [round_event(1, PLAN, "correctness", ("rev1", "ghost"))])
        self.assertIn("evidence unavailable", self.refused("finding", *flags()))

    def test_a_malformed_transcript_counts_as_unreadable(self):
        self.add_subagent("default-session", "bad", ["not json at all"])
        self.reviewer(text_row("nothing"))
        self.write_ledger("feature", [round_event(1, PLAN, "correctness", ("rev1", "bad"))])
        self.assertIn("evidence unavailable", self.refused("finding", *flags()))

    def test_a_malformed_transcript_does_not_stop_a_readable_reviewer_that_holds_the_quote(self):
        self.add_subagent("default-session", "bad", ["not json at all"])
        self.reviewer(text_row(QUOTE))
        self.write_ledger("feature", [round_event(1, PLAN, "correctness", ("rev1", "bad"))])
        self.ok("finding", *flags())

    def test_an_untested_version_counts_as_unreadable(self):
        self.reviewer(text_row("nothing"))
        rows = reviewed(text_row("nothing"))
        for row in rows:
            row["version"] = "9.9.9"
        self.add_subagent("default-session", "old", rows)
        self.write_ledger("feature", [round_event(1, PLAN, "correctness", ("rev1", "old"))])
        self.assertIn("evidence unavailable", self.refused("finding", *flags()))

    def test_every_reviewer_read_and_none_holding_the_quote_is_not_in_reviewer_text(self):
        self.reviewer(text_row("nothing"))
        self.round()
        self.assertIn("quote not in reviewer text", self.refused("finding", *flags()))

    def test_a_missing_registry_is_evidence_unavailable(self):
        self.write_ledger("feature", [round_event(1, PLAN, "correctness", ("rev1",))])
        os.unlink(os.path.join(self.runtime, "sessions.jsonl"))
        self.assertIn("evidence unavailable", self.refused("finding", *flags()))


class RegistryWideLookupTest(QuoteCase):
    def test_a_reviewer_of_another_registered_session_is_found(self):
        self.register_session("predecessor", [], subagents={"revB": reviewed(text_row(QUOTE))})
        self.write_ledger("feature", [round_event(1, PLAN, "correctness", ("revB",))])
        self.ok("finding", *flags())

    def test_the_first_readable_match_in_registry_order_is_used(self):
        self.register_session("first", [], subagents={"revB": ["not json"]})
        self.register_session("second", [], subagents={"revB": reviewed(text_row(QUOTE))})
        self.write_ledger("feature", [round_event(1, PLAN, "correctness", ("revB",))])
        self.ok("finding", *flags())


class RaisedTest(QuoteCase):
    def test_raised_on_a_minor_finding_is_refused(self):
        self.round()
        self.refused("finding", *flags(kind="Minor", raised=True))
        self.assertNotIn("raised", self.raw() or "")

    def test_a_raised_finding_without_a_quote_is_refused_also_in_code_review(self):
        self.round("code-review")
        self.assertIn("no quote", self.refused("finding", *flags(loop="code-review", quote=None, raised=True)))
        self.round()
        self.assertIn("no quote", self.refused("finding", *flags(quote=None, raised=True)))

    def test_a_raised_minor_finding_without_a_quote_is_refused_as_no_quote(self):
        self.round()
        self.assertIn("no quote", self.refused("finding", *flags(kind="Minor", quote=None, raised=True)))

    def test_a_raised_finding_still_needs_a_quote_in_its_reason_of_enough_length(self):
        self.round()
        self.assertIn("quote too short", self.refused("finding", *flags(quote="abc", raised=True)))
        self.assertIn("quote not in reason", self.refused("finding", *flags(quote="another long line", reason="elsewhere", raised=True)))

    def test_a_raised_finding_skips_the_reviewer_text_match_and_reads_no_transcript(self):
        self.write_ledger("feature", [round_event(1, PLAN, "correctness", ("ghost",))])
        os.unlink(os.path.join(self.runtime, "sessions.jsonl"))
        self.ok("finding", *flags(raised=True))
        written = self.written()[-1]
        self.assertIs(written["raised"], True)
        self.assertEqual(written["quote"], QUOTE)

    def test_a_raised_code_review_finding_passes_with_a_quote_that_no_reviewer_wrote(self):
        self.round("code-review")
        self.ok("finding", *flags(loop="code-review", raised=True))

    def test_raised_is_a_bare_flag(self):
        self.round()
        self.refused("finding", *flags(raised=True), "yes")

    def test_a_finding_without_a_round_is_refused_with_the_replay_text(self):
        message = self.refused("finding", *flags())
        self.assertIn("malformed event: no round event for round 1 of plan-review-5.3 correctness", message)


class FlagTest(QuoteCase):
    def test_quote_and_raised_are_refused_on_other_events(self):
        self.refused("round", "--loop", PLAN, "--phase", "correctness", "--round", "1", "--reviewer", "rev1", "--raised")
        self.refused("round", "--loop", PLAN, "--phase", "correctness", "--round", "1", "--reviewer", "rev1", "--quote", QUOTE)
        self.refused("status", "--finding", "P1", "--status", "fixed", "--quote", QUOTE)

    def test_the_refusal_keeps_needs_exactly_and_names_the_optional_flags(self):
        self.round()
        message = self.refused("finding", "--id", "P1")
        self.assertIn("needs exactly", message)
        self.assertIn("--quote", message)
        self.assertIn("--raised", message)

    def test_the_extension_quote_keeps_its_eight_character_minimum(self):
        self.refused("extension", "--loop", PLAN, "--phase", "correctness", "--rounds", "1", "--quote", "short")

    def test_the_help_lists_quote_and_raised_for_a_finding_and_the_raised_mark_of_show(self):
        text = self.audit("ledger", "--help").stdout.decode()
        self.assertRegex(text, r"finding\s+--id[^\n]*--reason[^\n]*--quote[^\n]*--raised")
        self.assertIn('"raised":true', text)
        self.assertIn("except the optional flags in [brackets]", text)

    def test_a_refused_quote_leaves_the_ledger_unchanged(self):
        self.round()
        before = self.raw()
        self.refused("finding", *flags(quote="never written", reason="never written"))
        self.assertEqual(self.raw(), before)

    def test_a_long_quote_that_makes_the_line_too_long_is_refused_as_event_too_long(self):
        self.reviewer(text_row("é" * 500))
        self.round()
        message = self.refused("finding", *flags(quote="é" * 500, reason="é" * 500))
        self.assertIn("event too long", message)


class ShapeAndReplayTest(QuoteCase):
    def test_an_old_finding_line_without_quote_and_raised_replays(self):
        self.write_ledger("feature", [round_event(1, PLAN, "correctness"), finding_event("P1", PLAN, kind="Blocking")])
        self.ok("status", "--finding", "P1", "--status", "fixed")

    def test_a_raised_key_with_any_value_but_true_is_refused(self):
        for value in (False, 1, "true", None, "yes"):
            with self.subTest(value=value):
                self.write_ledger("feature", [round_event(1, PLAN, "correctness"),
                                              finding_event("P1", PLAN, quote=QUOTE, raised=value)])
                self.assertIn("raised", self.refused("status", "--finding", "P1", "--status", "fixed"))

    def test_a_raised_key_on_a_minor_finding_line_is_a_ledger_error(self):
        self.write_ledger("feature", [round_event(1, PLAN, "correctness"),
                                      finding_event("P1", PLAN, kind="Minor", quote=QUOTE, raised=True)])
        self.assertIn("invalid line", self.refused("status", "--finding", "P1", "--status", "fixed"))

    def test_an_unknown_key_on_a_finding_line_is_still_refused(self):
        self.write_ledger("feature", [round_event(1, PLAN, "correctness"), finding_event("P1", PLAN, extra="x")])
        self.assertIn("invalid line", self.refused("status", "--finding", "P1", "--status", "fixed"))

    def test_a_quote_key_on_a_status_line_is_still_refused(self):
        self.write_ledger("feature", [round_event(1, PLAN, "correctness"), finding_event("P1", PLAN),
                                      {"kind": "status", "time": EARLY, "finding": "P1", "status": "fixed", "quote": QUOTE}])
        self.assertIn("invalid line", self.refused("status", "--finding", "P1", "--status", "fixed"))

    def test_a_ledger_replay_reads_no_transcript(self):
        self.write_ledger("feature", [round_event(1, PLAN, "correctness", ("ghost",)),
                                      {**finding_event("P1", PLAN, quote=QUOTE), "reason": REASON}])
        os.unlink(os.path.join(self.runtime, "sessions.jsonl"))
        self.ok("status", "--finding", "P1", "--status", "fixed")
        self.assertEqual(self.audit("ledger", "show", "--worktree", self.repo).returncode, 0)


class ShowTest(QuoteCase):
    def test_show_prints_the_quote_key_and_the_raised_mark_of_a_finding(self):
        self.round()
        self.reviewer(text_row(QUOTE))
        self.ok("finding", *flags())
        self.ok("finding", *flags(finding_id="P2", raised=True))
        lines = self.audit("ledger", "show", "--worktree", self.repo).stdout.decode().splitlines()
        findings = [json.loads(line) for line in lines if line.startswith('{"kind":"finding"')]
        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0]["quote"], QUOTE)
        self.assertNotIn("raised", findings[0])
        self.assertIs(findings[1]["raised"], True)
        self.assertIn('"raised":true', lines[-1])


if __name__ == "__main__":
    unittest.main()
