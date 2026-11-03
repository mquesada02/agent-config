# Ticket #319: the `size-approval` ledger event, its S5 check against real user input, and the about-150-line small-task limit.
import json
import os
import re
import unittest

from audit_support import HERE, event, owner_row, stamp
from test_brief import read_brief
from test_claude_md import ROOT_CLAUDE_MD, read, section
from test_extension_s5 import HUMAN, ExtensionCase, rounds
from test_ledger import LedgerCase

QUOTE = "yes, about 300 lines is fine"
APPROVED_AT = 200
NOT_FOUND = "size-approval 1 (300 lines): quote not found in real user input"


def size_approval(at=APPROVED_AT, quote=QUOTE, lines=300):
    return event("size-approval", lines=lines, quote=quote, time=stamp(at))


class SizeApprovalLedgerTest(LedgerCase):
    def test_a_valid_size_approval_is_written_and_shown(self):
        self.ok("size-approval", "--lines", "300", "--quote", QUOTE)
        written = self.written()[-1]
        written.pop("time")
        self.assertEqual(written, {"kind": "size-approval", "lines": 300, "quote": QUOTE})
        shown = self.audit("ledger", "show", "--worktree", self.repo).stdout.decode().splitlines()
        self.assertEqual(json.loads(shown[-1])["kind"], "size-approval")

    def test_a_size_approval_needs_both_flags_and_no_other(self):
        self.refused("size-approval", "--lines", "300")
        self.refused("size-approval", "--quote", QUOTE)
        self.refused("size-approval", "--lines", "300", "--quote", QUOTE, "--rounds", "1")
        self.refused("extension", "--loop", "code-review", "--phase", "correctness", "--rounds", "1", "--quote", QUOTE,
                     "--lines", "300")

    def test_the_lines_value_must_be_a_positive_integer(self):
        for value in ("0", "-1", "abc", "2.5", "100001"):
            with self.subTest(value):
                self.refused("size-approval", "--lines", value, "--quote", QUOTE)

    def test_the_quote_must_hold_8_characters_after_normalising(self):
        for quote in ("1234567", "'" * 8, " " * 8, "x" * 501, "abcd\nefgh"):
            with self.subTest(quote=quote):
                self.refused("size-approval", "--lines", "300", "--quote", quote)

    def test_the_help_lists_the_size_approval_event(self):
        text = self.audit("ledger", "--help").stdout.decode()
        self.assertRegex(text, r"size-approval\s+--lines[^\n]*--quote")


class SizeApprovalS5Test(ExtensionCase):
    def test_a_quote_in_real_user_input_before_the_event_passes(self):
        self.passes([owner_row(f"Sure, {QUOTE}.", 100, HUMAN)], events=[size_approval()])

    def test_a_quote_at_the_event_time_passes(self):
        self.passes([owner_row(QUOTE, APPROVED_AT, HUMAN)], events=[size_approval()])

    def test_a_quote_after_the_event_fails(self):
        self.fails([owner_row(QUOTE, APPROVED_AT + 1, HUMAN)], NOT_FOUND, events=[size_approval()])

    def test_a_quote_that_is_not_in_real_user_input_fails(self):
        self.fails([owner_row("something else", 100, HUMAN)], NOT_FOUND, events=[size_approval()])

    def test_a_ledger_without_a_size_approval_keeps_its_s5_result(self):
        self.passes([], events=rounds(1))


class LimitTextTest(unittest.TestCase):
    def test_claude_md_names_about_150_lines_tests_included_for_the_small_path(self):
        exception = re.search(r"^\*\*Exception:\*\*.*$", section(read(ROOT_CLAUDE_MD), 7), re.MULTILINE).group(0)
        self.assertIn("estimated under ~150 changed lines, tests included", exception)
        self.assertIn("`size-approval`", exception)

    def test_claude_md_lists_the_size_approval_event_after_the_extension_event(self):
        text = section(read(ROOT_CLAUDE_MD), 6)
        bullet = re.search(r"^- `size-approval`:.*$", text, re.MULTILINE).group(0)
        for phrase in ("`--lines`", "`--quote`", "the user's own words"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, bullet)
        self.assertGreater(text.index("- `size-approval`:"), text.index("- `extension`:"))

    def test_the_brief_l5_names_150_lines_and_the_size_approval_exception(self):
        full = read_brief().partition("## Pre-dispatch variant")[0]
        l5 = full.split("- **L5.**", 1)[1].split("- **L6.**", 1)[0]
        for phrase in ("under about 150 changed lines, tests included", "`size-approval`", "`lines`"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, l5)
        self.assertNotRegex(l5, r"\b50 changed lines")
        self.assertIn('"The diff is under about 150 lines, as estimated."', full)

    def test_the_brief_says_size_approval_lines_are_data_that_s5_verifies(self):
        reading = read_brief().split("## Reading the ledger", 1)[1].split("## Reading the sessions", 1)[0]
        self.assertIn("`size-approval` lines of `ledger show`", reading)
        self.assertIn("quote is verified by S5", reading)


if __name__ == "__main__":
    unittest.main()
