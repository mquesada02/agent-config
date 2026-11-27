# Issue 1113: the S11 audit item (section 6 step 2 ran /simplify), driven through `audit record` with synthetic transcripts.
import os
import unittest

from audit_support import HERE, AuditCase, call_row, edit_row, owner_row, phase_commit_event, round_event, stamp

SHA = "a" * 40
SLASH = "<command-message>simplify</command-message>\n<command-name>/simplify</command-name>"


def at(seconds):
    return stamp(seconds).replace(".000Z", ".000+00:00")


def final_loop(commit_seconds=10, final_seconds=30):
    """A section 6 ledger: a phase-commit event, then the first final round."""
    return [round_event(), phase_commit_event(SHA, time=at(commit_seconds)),
            round_event(1, phase="final", time=at(final_seconds))]


def skill_row(seconds, skill="simplify", call_id="s1"):
    return call_row("Skill", {"skill": skill}, call_id, seconds)


def slash_row(seconds, content=SLASH):
    return owner_row(content, seconds)


class S11Case(AuditCase):
    default_ledger = False

    def s11(self, rows, events):
        self.register_session("s1", [edit_row(os.path.join(self.repo, "a.txt"), "e1", 1), *rows])
        tip = self.start_branch("feature", "feat: a")
        self.write_ledger("feature", events)
        self.assertIn(self.record().returncode, (0, 1))
        return self.item(tip, "S11")

    def assert_item(self, item, result, text):
        self.assertEqual(item["result"], result, item["evidence"])
        self.assertIn(text, item["evidence"])


class S11PassTest(S11Case):
    def test_a_skill_call_in_the_window_passes(self):
        self.assert_item(self.s11([skill_row(20)], final_loop()), "pass", "1 /simplify calls")

    def test_a_slash_command_in_the_window_passes(self):
        self.assert_item(self.s11([slash_row(20)], final_loop()), "pass", "1 /simplify calls")

    def test_a_ledger_with_no_section_6_final_round_passes(self):
        self.assert_item(self.s11([], [round_event(loop="plan-review-3")]), "pass", "no section 6 final round")

    def test_a_call_in_the_window_of_a_later_phase_commit_passes(self):
        events = final_loop() + [phase_commit_event(SHA, time=at(40)), round_event(2, phase="final", time=at(60))]
        item = self.s11([skill_row(50)], events)
        self.assert_item(item, "pass", "1 /simplify calls after the phase-commit at 2026-10-15T12:00:40")

    def test_a_rebase_ledger_with_a_call_only_in_the_first_window_passes(self):
        events = final_loop() + [phase_commit_event(SHA, time=at(40)), round_event(2, phase="final", time=at(60))]
        self.assert_item(self.s11([skill_row(20)], events), "pass", "1 /simplify calls after the phase-commit at 2026-10-15T12:00:10")


class S11FailTest(S11Case):
    def test_no_call_fails_and_names_the_window(self):
        item = self.s11([], final_loop())
        self.assert_item(item, "fail", "no /simplify call after the phase-commit at 2026-10-15T12:00:10")
        self.assertIn("before the final round at 2026-10-15T12:00:30", item["evidence"])

    def test_no_call_names_every_window(self):
        events = final_loop() + [phase_commit_event(SHA, time=at(40)), round_event(2, phase="final", time=at(60))]
        item = self.s11([], events)
        self.assert_item(item, "fail", "after the phase-commit at 2026-10-15T12:00:10")
        self.assertIn("after the phase-commit at 2026-10-15T12:00:40", item["evidence"])

    def test_a_call_after_a_later_phase_commit_with_no_final_round_fails(self):
        events = final_loop() + [phase_commit_event(SHA, time=at(40))]
        self.assert_item(self.s11([skill_row(50)], events), "fail", "no /simplify call")

    def test_a_call_after_the_last_final_round_fails(self):
        events = final_loop() + [phase_commit_event(SHA, time=at(40)), round_event(2, phase="final", time=at(60))]
        self.assert_item(self.s11([skill_row(70)], events), "fail", "no /simplify call")

    def test_a_call_before_the_phase_commit_fails(self):
        self.assert_item(self.s11([skill_row(5), slash_row(6)], final_loop()), "fail", "no /simplify call")

    def test_a_call_after_the_first_final_round_fails(self):
        self.assert_item(self.s11([skill_row(40), slash_row(41)], final_loop()), "fail", "no /simplify call")

    def test_another_skill_and_another_command_do_not_count(self):
        rows = [skill_row(20, skill="smart-commits"), slash_row(21, "<command-name>/simplify-other</command-name>")]
        self.assert_item(self.s11(rows, final_loop()), "fail", "no /simplify call")

    def test_a_final_round_with_no_phase_commit_fails(self):
        self.assert_item(self.s11([skill_row(20)], [round_event(), round_event(1, phase="final", time=at(30))]), "fail", "no phase-commit event")

    def test_unreadable_transcripts_fail_with_evidence_unavailable(self):
        self.assert_item(self.s11(["not json"], final_loop()), "fail", "evidence unavailable")


class S11DocsTest(unittest.TestCase):
    def test_the_adr_names_s11(self):  # the brief is pinned by test_brief
        with open(os.path.join(os.path.dirname(os.path.dirname(HERE)), "docs/adr/0001-audit-checks-guard-against-mistakes.md"), encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("S1 to S11", text)
        self.assertNotIn("S1 to S10", text)


if __name__ == "__main__":
    unittest.main()
