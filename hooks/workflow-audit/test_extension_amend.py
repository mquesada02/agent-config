# `extension-amend`: a new owner answer backs an earlier extension; S5 judges that extension by its latest amendment.
import json
import unittest

import test_extension_s5 as s5
import test_ledger
import test_pre_dispatch
from audit_support import event, owner_row, round_event, stamp

NEW = "approve one more round now"
LATER = "yes, go on for round seven"
HUMAN = s5.HUMAN
TWO = s5.rounds(5) + [round_event(6, time=stamp(60)), s5.extension(), s5.extension(at=210)]
SECOND_NOT_FOUND = "extension 2 (code-review correctness +1): quote not found in real user input"


def amend(number=2, quote=NEW, at=300):
    return event("extension-amend", extension=number, quote=quote, time=stamp(at))


class AmendS5Test(s5.ExtensionCase):
    def test_a_new_answer_after_the_extension_backs_it(self):
        self.passes([owner_row(s5.QUOTE, 100, HUMAN), owner_row(NEW, 250, HUMAN)], TWO + [amend()])

    def test_the_same_ledger_without_the_amendment_fails_the_second_extension(self):
        self.fails([owner_row(s5.QUOTE, 100, HUMAN), owner_row(NEW, 250, HUMAN)], SECOND_NOT_FOUND, TWO)

    def test_an_amendment_whose_quote_is_in_no_real_input_fails(self):
        self.fails([owner_row(s5.QUOTE, 100, HUMAN)], SECOND_NOT_FOUND, TWO + [amend()])

    def test_the_new_quote_in_a_peer_message_does_not_back_it(self):
        self.fails([owner_row(s5.QUOTE, 100, HUMAN), owner_row(NEW, 250, s5.PEER)], SECOND_NOT_FOUND, TWO + [amend()])

    def test_the_answer_must_not_be_after_the_amendment(self):
        for seconds, counts in ((299, True), (300, True), (301, False)):
            with self.subTest(seconds=seconds):
                self.setUp()
                rows = [owner_row(s5.QUOTE, 100, HUMAN), owner_row(NEW, seconds, HUMAN)]
                if counts:
                    self.passes(rows, TWO + [amend()])
                else:
                    self.fails(rows, SECOND_NOT_FOUND, TWO + [amend()])

    def test_the_answer_must_be_after_the_capped_round(self):
        # the second extension follows round 6, stamped 60: an answer at 60 or before does not count
        for seconds, counts in ((60, False), (61, True)):
            with self.subTest(seconds=seconds):
                self.setUp()
                rows = [owner_row(s5.QUOTE, 100, HUMAN), owner_row(NEW, seconds, HUMAN)]
                if counts:
                    self.passes(rows, TWO + [amend()])
                else:
                    self.fails(rows, SECOND_NOT_FOUND, TWO + [amend()])

    def test_an_answer_between_the_extension_and_the_amendment_counts(self):
        self.passes([owner_row(s5.QUOTE, 100, HUMAN), owner_row(NEW, 215, HUMAN)], TWO + [amend()])

    def test_one_answer_does_not_back_an_extension_and_the_amendment_of_another(self):
        self.fails([owner_row(s5.QUOTE, 100, HUMAN)], SECOND_NOT_FOUND, TWO + [amend(quote=s5.QUOTE)])

    def test_two_answers_back_an_extension_and_the_amendment_of_another(self):
        self.passes([owner_row(s5.QUOTE, 100, HUMAN), owner_row(s5.QUOTE, 250, HUMAN)], TWO + [amend(quote=s5.QUOTE)])

    def test_the_amendment_replaces_the_own_quote_of_the_extension(self):
        # the original quote is backed, the amendment quote is not: the amendment is in force, so the extension fails
        self.fails([owner_row(s5.QUOTE, 100, HUMAN)], "extension 1 (code-review correctness +1): quote not found in real user input",
                   s5.rounds(5) + [s5.extension(), amend(1)])

    def test_the_latest_amendment_is_in_force(self):
        rows = [owner_row(NEW, 250, HUMAN)]
        events = s5.rounds(5) + [s5.extension(), amend(1, NEW, 260), amend(1, LATER, 270)]
        self.fails(rows, "extension 1 (code-review correctness +1): quote not found in real user input", events)
        self.setUp()
        self.passes(rows + [owner_row(LATER, 255, HUMAN)], events)

    def test_the_amendment_does_not_change_the_cap(self):
        events = s5.rounds(5) + [s5.extension(), amend(1), round_event(6, time=stamp(310)), round_event(7, time=stamp(320))]
        self.fails([owner_row(NEW, 250, HUMAN)], "code-review correctness: round 7 is past the cap of 6", events)

    def test_an_amendment_of_an_unbacked_first_extension_backs_it(self):
        self.passes([owner_row(NEW, 250, HUMAN)], s5.rounds(5) + [s5.extension(), amend(1)])


class AmendLedgerTest(test_ledger.LedgerCase):
    QUOTE = "allow one more round"

    def at_cap_with_extension(self):
        for number in range(1, 6):
            self.ok("round", "--loop", "code-review", "--phase", "correctness", "--round", str(number), "--reviewer", "rev1")
        self.ok("extension", "--loop", "code-review", "--phase", "correctness", "--rounds", "1", "--quote", self.QUOTE)

    def test_an_amendment_of_an_earlier_extension_is_written_and_shown(self):
        self.at_cap_with_extension()
        self.ok("extension-amend", "--extension", "1", "--quote", NEW)
        written = self.written()[-1]
        written.pop("time")
        self.assertEqual(written, {"kind": "extension-amend", "extension": 1, "quote": NEW})
        shown = self.audit("ledger", "show", "--worktree", self.repo).stdout.decode().splitlines()
        self.assertEqual(json.loads(shown[-1])["extension"], 1)

    def test_an_amendment_of_a_missing_extension_is_refused(self):
        self.refused("extension-amend", "--extension", "1", "--quote", NEW)
        self.at_cap_with_extension()
        self.refused("extension-amend", "--extension", "2", "--quote", NEW)
        self.refused("extension-amend", "--extension", "0", "--quote", NEW)
        self.refused("extension-amend", "--extension", "-1", "--quote", NEW)
        self.refused("extension-amend", "--extension", "x", "--quote", NEW)

    def test_a_short_quote_is_refused(self):
        self.at_cap_with_extension()
        for quote in ("1234567", "x" * 501, "abcd\nefgh", "''''''''", ""):
            with self.subTest(quote=quote):
                self.refused("extension-amend", "--extension", "1", "--quote", quote)

    def test_an_amendment_cannot_change_the_loop_the_phase_or_the_rounds(self):
        self.at_cap_with_extension()
        for flags in (("--loop", "code-review"), ("--phase", "final"), ("--rounds", "2"), ("--round", "1")):
            with self.subTest(flags=flags):
                self.refused("extension-amend", "--extension", "1", "--quote", NEW, *flags)

    def test_a_missing_flag_is_refused(self):
        self.at_cap_with_extension()
        self.refused("extension-amend", "--extension", "1")
        self.refused("extension-amend", "--quote", NEW)

    def test_the_extension_flag_is_refused_for_other_events(self):
        self.refused("round", *test_ledger.ROUND, "--extension", "1")

    def test_an_amendment_does_not_raise_the_cap(self):
        self.at_cap_with_extension()
        self.ok("extension-amend", "--extension", "1", "--quote", NEW)
        self.refused("extension", "--loop", "code-review", "--phase", "correctness", "--rounds", "1", "--quote", self.QUOTE)


class AmendPreDispatchTest(test_pre_dispatch.PreDispatchCase):
    """The pre-dispatch view keeps the extensions of the plan-review loops: an amendment names its extension by the place in the whole ledger."""

    def test_an_amendment_of_a_later_extension_counts_after_an_extension_of_another_loop(self):
        loop_3, loop_4 = test_pre_dispatch.LOOP_3, test_pre_dispatch.LOOP_41
        events = [*test_pre_dispatch.rounds(loop_3, "final", 4), round_event(loop=loop_4),
                  *test_pre_dispatch.rounds("code-review", "correctness", 5),
                  event("extension", loop="code-review", phase="correctness", rounds=1, quote=s5.QUOTE, time=stamp(200)),
                  event("extension", loop=loop_3, phase="final", rounds=1, quote=s5.QUOTE, time=stamp(210)),
                  amend(1, "words that no one typed", 290), amend(2, NEW, 300)]
        self.write_ledger("feature", events)
        self.register_session("coordinator", [test_pre_dispatch.bash_row(test_pre_dispatch.write_command(self.repo), "w1", 150),
                                              test_pre_dispatch.queued_row(NEW, 100, HUMAN)])
        result = self.pre_dispatch()
        self.assertEqual(self.pd_item("S5")["result"], "pass", self.pd_item("S5")["evidence"])
        self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
