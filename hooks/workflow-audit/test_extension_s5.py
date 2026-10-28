# S5 with `extension` events: the quote must be found in real user input of the audited transcripts, through `audit record` and `audit check`.
import json
import os
import unittest

from audit_support import (ABSENT, HERE, ask_rows, edit_row, extension_event, owner_row, queued_row, round_event, stamp,
                           subagent_rows)
from test_ledger_checks import LedgerChecksCase

HUMAN = {"kind": "human"}
PEER = {"kind": "peer"}
NOTICE = {"kind": "task-notification"}
QUOTE = "please allow one more round"
NOT_FOUND = "extension 1 (code-review correctness +1): quote not found in real user input"
PREAMBLE = ("You are working inside Orca, a multi-agent IDE. You are a dispatched worker.\n"
            "orca orchestration send --type worker_done --task-id task_x --dispatch-id ctx_0000 --outcome succeeded")
ROUND_5 = 50  # rounds n of a phase are stamped 10 * n seconds; the extension is stamped EXTENSION_AT
EXTENSION_AT = 200


def rounds(count, **extra):
    return [round_event(n, time=stamp(10 * n), **extra) for n in range(1, count + 1)]


def extension(at=EXTENSION_AT, quote=QUOTE, **extra):
    return extension_event(time=stamp(at), quote=quote, **extra)


class ExtensionCase(LedgerChecksCase):
    def s5(self, rows, events=None, **session):
        """The S5 item for a ledger (default: rounds 1 to 5 and one extension) and one registered session that holds `rows`."""
        self.register_session(
            "owner", [edit_row(os.path.join(self.repo, "b.txt"), "e1", 1)] + list(rows), **session)
        return self.items(events if events is not None else rounds(5) + [extension()])["S5"]

    def passes(self, rows, events=None, **session):
        item = self.s5(rows, events, **session)
        self.assertEqual(item["result"], "pass", item["evidence"])

    def fails(self, rows, text=NOT_FOUND, events=None, **session):
        item = self.s5(rows, events, **session)
        self.assertEqual(item["result"], "fail", item["evidence"])
        self.assertEqual(item["evidence"], text)


class SourceTest(ExtensionCase):
    def test_a_human_prompt_counts(self):
        self.passes([owner_row(QUOTE, 100, HUMAN)])

    def test_the_quote_may_be_part_of_a_longer_prompt(self):
        self.passes([owner_row(f"Yes, {QUOTE}, then stop.", 100, HUMAN)])

    def test_a_normalised_match_counts(self):
        self.passes([owner_row('please   allow "one" more\n round', 100, HUMAN)])

    def test_a_human_text_block_in_a_list_content_counts(self):
        row = owner_row([{"type": "text", "text": QUOTE}], 100, HUMAN)
        self.passes([row])

    def test_a_queued_command_with_a_human_origin_counts(self):
        self.passes([queued_row(QUOTE, 100, HUMAN)])

    def test_an_ask_user_question_answer_counts(self):
        self.passes(ask_rows("ask1", {"Which?": QUOTE}, 100))

    def test_sources_that_do_not_count(self):
        sources = {
            "peer message": [owner_row(QUOTE, 100, PEER)],
            "task notification": [owner_row(QUOTE, 100, NOTICE)],
            "orca reply relayed as a peer message": [owner_row(f"[reply] {QUOTE}", 100, PEER)],
            "row without origin": [owner_row(QUOTE, 100)],
            "bash row without origin": [owner_row(f"<bash-input>{QUOTE}</bash-input>", 100)],
            "compaction summary": [owner_row(QUOTE, 100, HUMAN, isCompactSummary=True)],
            "queued_command with a peer origin": [queued_row(QUOTE, 100, PEER)],
            "queued_command without origin": [queued_row(QUOTE, 100)],
            "question text": ask_rows("ask1", {"Which?": "unrelated"}, 100, question=QUOTE),
            "answer key": ask_rows("ask1", {QUOTE: "unrelated"}, 100),
            "assistant text": [{**owner_row("x", 100), "type": "assistant", "message": {"model": "claude-opus-5-5", "content": [{"type": "text", "text": QUOTE}]}}],
            "answers of a result that answers another call": ask_rows("ask1", {"Which?": "unrelated"}, 100)
            + [{**ask_rows("other", {"Which?": QUOTE}, 105)[1]}],
        }
        for name, rows in sources.items():
            with self.subTest(name):
                self.setUp()
                self.fails(rows)

    def test_a_worker_session_does_not_count(self):
        self.fails([owner_row(PREAMBLE, 90, HUMAN), owner_row(QUOTE, 100, HUMAN)])

    def test_a_subagent_transcript_does_not_count(self):
        sub = subagent_rows()
        sub[0]["message"]["content"] = QUOTE
        sub[0]["origin"] = HUMAN
        sub[0]["timestamp"] = stamp(100)
        self.fails([], subagents={"a1": sub})

    def test_a_tool_use_result_that_is_not_an_object_is_read_as_absent(self):
        rows = ask_rows("ask1", ABSENT, 100)
        rows[1]["toolUseResult"] = "invented error text"
        self.fails(rows)


class TimeTest(ExtensionCase):
    def test_the_row_must_be_after_the_round_and_not_after_the_extension(self):
        for seconds, counts in ((ROUND_5 - 1, False), (ROUND_5, False), (ROUND_5 + 1, True), (EXTENSION_AT, True), (EXTENSION_AT + 1, False)):
            with self.subTest(seconds=seconds):
                self.setUp()
                if counts:
                    self.passes([owner_row(QUOTE, seconds, HUMAN)])
                else:
                    self.fails([owner_row(QUOTE, seconds, HUMAN)])

    def test_a_row_without_a_readable_timestamp_does_not_count(self):
        for name, value in (("missing", ABSENT), ("bad", "not a time"), ("not a string", 12345)):
            with self.subTest(name):
                self.setUp()
                row = owner_row(QUOTE, 100, HUMAN)
                if value is ABSENT:
                    del row["timestamp"]
                else:
                    row["timestamp"] = value
                self.fails([row])

    def test_the_round_of_the_second_extension_is_the_one_at_its_own_cap(self):
        events = rounds(5) + [extension(), round_event(6, time=stamp(210)), extension(at=300)]
        self.fails([owner_row(QUOTE, 100, HUMAN)], "extension 2 (code-review correctness +1): quote not found in real user input", events)

    def test_a_row_after_the_second_round_backs_the_second_extension(self):
        events = rounds(5) + [extension(), round_event(6, time=stamp(210)), extension(at=300)]
        self.passes([owner_row(QUOTE, 100, HUMAN), owner_row(QUOTE, 250, HUMAN)], events)

    def test_an_extension_written_after_the_extra_round_takes_a_row_after_the_capped_round(self):
        events = rounds(6) + [extension()]
        self.passes([owner_row(QUOTE, 55, HUMAN)], events)


class OneUseTest(ExtensionCase):
    two = rounds(5) + [round_event(6, time=stamp(60)), extension(), extension(at=210)]

    def test_one_block_for_two_extensions_fails_the_second(self):
        self.fails([owner_row(QUOTE, 100, HUMAN)], "extension 2 (code-review correctness +1): quote not found in real user input", self.two)

    def test_two_blocks_back_two_extensions(self):
        self.passes([owner_row(QUOTE, 100, HUMAN), queued_row(QUOTE, 110, HUMAN)], self.two)

    def test_two_answer_values_of_one_row_back_two_extensions(self):
        self.passes(ask_rows("ask1", {"A?": QUOTE, "B?": QUOTE}, 100), self.two)

    def test_each_extension_takes_the_earliest_unused_block(self):
        rows = [owner_row(f"{QUOTE}, thanks", 100, HUMAN), owner_row(QUOTE, 110, HUMAN)]
        events = rounds(5) + [round_event(6, time=stamp(60)), extension(), extension(at=210, quote="round, thanks")]
        self.fails(rows, "extension 2 (code-review correctness +1): quote not found in real user input", events)

    def test_a_later_block_backs_the_second_when_the_first_is_taken(self):
        rows = [owner_row(f"{QUOTE}, thanks", 100, HUMAN), owner_row("yes, a round, thanks again", 110, HUMAN)]
        events = rounds(5) + [round_event(6, time=stamp(60)), extension(), extension(at=210, quote="round, thanks")]
        self.passes(rows, events)


class EvidenceTest(ExtensionCase):
    def test_the_evidence_names_the_extension_loop_phase_and_rounds(self):
        events = [round_event(n, loop="plan-review-3", phase="final", time=stamp(10 * n)) for n in range(1, 4)]
        events += [extension_event(loop="plan-review-3", phase="final", rounds=2, time=stamp(200), quote=QUOTE)]
        self.fails([], "extension 1 (plan-review-3 final +2): quote not found in real user input", events)

    def test_every_unbacked_extension_is_listed_by_its_position(self):
        events = rounds(5) + [round_event(6, time=stamp(60)), extension(), extension(at=210)]
        item = self.s5([], events=events)
        self.assertEqual(item["evidence"].splitlines(), [
            "extension 1 (code-review correctness +1): quote not found in real user input",
            "extension 2 (code-review correctness +1): quote not found in real user input"])

    def test_a_round_past_the_extended_cap_names_the_extended_cap(self):
        events = rounds(5) + [extension(), round_event(6, time=stamp(210)), round_event(7, time=stamp(220))]
        self.fails([owner_row(QUOTE, 100, HUMAN)], "code-review correctness: round 7 is past the cap of 6", events)

    def test_a_round_within_the_extended_cap_passes(self):
        events = rounds(5) + [extension(), round_event(6, time=stamp(210))]
        self.passes([owner_row(QUOTE, 100, HUMAN)], events)

    def test_a_correctness_extension_does_not_raise_the_final_cap(self):
        events = rounds(5) + [extension()] + [round_event(n, phase="final", time=stamp(300 + n)) for n in range(1, 5)]
        self.fails([owner_row(QUOTE, 100, HUMAN)], "code-review final: round 4 is past the cap of 3", events)

    def test_a_past_cap_round_and_an_unbacked_quote_are_both_listed(self):
        events = rounds(5) + [extension(), round_event(6, time=stamp(210)), round_event(7, time=stamp(220))]
        item = self.s5([], events=events)
        self.assertEqual(item["evidence"].splitlines(), ["code-review correctness: round 7 is past the cap of 6", NOT_FOUND])


class NoExtensionTest(LedgerChecksCase):
    default_session = False

    def test_a_round_past_the_base_cap_keeps_the_past_cap_text(self):
        item = self.items(rounds(6))["S5"]
        self.assertEqual(item["result"], "fail")
        self.assertEqual(item["evidence"], "code-review correctness: round 6 is past the cap of 5")

    def test_an_empty_registry_gives_todays_result(self):
        item = self.items(rounds(5))["S5"]
        self.assertEqual(item["result"], "pass")
        self.assertEqual(item["evidence"], "5 rounds in 1 loop phases, none past a cap")

    def test_an_unreadable_transcript_is_not_read_without_an_extension(self):
        os.mkdir(os.path.join(self.root, "dir.jsonl"))
        self.register_path("bad", os.path.join(self.root, "dir.jsonl"))
        item = self.items(rounds(5))["S5"]
        self.assertEqual(item["result"], "pass")


class UnavailableTest(ExtensionCase):
    default_session = False

    def unavailable(self, text, events=None):
        item = self.items(events if events is not None else rounds(5) + [extension()])["S5"]
        self.assertEqual(item["result"], "fail")
        self.assertEqual(item["evidence"], text)

    def test_no_registered_session(self):
        self.unavailable("evidence unavailable: no registered session (empty or wiped registry)")

    def test_no_session_touches_the_worktree(self):
        self.register_session("elsewhere", [edit_row(os.path.join(self.root, "elsewhere.txt"), "e1", 1)])
        self.unavailable("evidence unavailable: no registered session touches the worktree")

    def test_an_unreadable_transcript(self):
        os.mkdir(os.path.join(self.root, "dir.jsonl"))
        self.register_path("bad", os.path.join(self.root, "dir.jsonl"))
        item = self.items(rounds(5) + [extension()])["S5"]
        self.assertEqual(item["result"], "fail")
        self.assertTrue(item["evidence"].startswith("evidence unavailable: cannot read transcript dir.jsonl"), item["evidence"])

    def test_an_unreadable_registry(self):
        os.makedirs(self.runtime, exist_ok=True)
        os.chmod(self.runtime, 0o700)
        with open(os.path.join(self.runtime, "sessions.jsonl"), "w") as handle:
            handle.write("not json\n")
        self.unavailable("evidence unavailable: unreadable registry line 1")

    def test_the_unavailable_text_wins_over_a_past_cap_round(self):
        events = rounds(5) + [extension(), round_event(6, time=stamp(210)), round_event(7, time=stamp(220))]
        self.unavailable("evidence unavailable: no registered session (empty or wiped registry)", events)

    def test_a_hand_written_short_quote_does_not_pass(self):
        self.register_session("owner", [edit_row(os.path.join(self.repo, "b.txt"), "e1", 1), owner_row("anything", 100, HUMAN)])
        item = self.items(rounds(5) + [extension(quote="''''''''")])["S5"]
        self.assertEqual(item["result"], "fail")
        self.assertIn("evidence unavailable", item["evidence"])


class MalformedTest(ExtensionCase):
    BAD = ("human", None, 5, ["human"], {}, {"kind": 5}, {"kind": None})

    def test_a_malformed_origin_is_unavailable(self):
        for bad in self.BAD:
            with self.subTest(bad=bad):
                self.setUp()
                rows = [owner_row("x", 90, bad)]
                self.fails(rows, "evidence unavailable: malformed origin in owner.jsonl row 2")

    def test_a_malformed_attachment_origin_is_unavailable(self):
        for bad in self.BAD:
            with self.subTest(bad=bad):
                self.setUp()
                self.fails([owner_row("x", 90, HUMAN), queued_row("x", 95, bad)], "evidence unavailable: malformed attachment.origin in owner.jsonl row 3")

    def test_malformed_answers_are_unavailable(self):
        for bad in (None, ["x"], "x", 5, {"q": 1}, {"q": ["a"]}, {"q": None}):
            with self.subTest(bad=bad):
                self.setUp()
                self.fails(ask_rows("ask1", bad, 90), "evidence unavailable: malformed answers in owner.jsonl row 3")

    def test_the_malformed_origin_of_a_row_that_is_not_checked_is_ignored(self):
        cases = {
            "compaction summary": dict(rows=[owner_row("x", 90, "bad", isCompactSummary=True)]),
            "answers of another call": dict(rows=ask_rows("ask1", {"q": "x"}, 90) + [ask_rows("other", [1], 95)[1]]),
            "assistant row": dict(rows=[{**owner_row("x", 90), "type": "assistant", "origin": "bad",
                                         "message": {"model": "claude-opus-5-5", "content": [{"type": "text", "text": "x"}]}}]),
        }
        for name, case in cases.items():
            with self.subTest(name):
                self.setUp()
                self.fails(case["rows"])

    def test_a_malformed_origin_in_a_subagent_or_a_worker_session_is_ignored(self):
        sub = subagent_rows()
        sub[0]["origin"] = "bad"
        self.fails([], subagents={"a1": sub})
        self.setUp()
        self.fails([owner_row(PREAMBLE, 80, HUMAN), owner_row("x", 90, "bad")])

    def test_a_malformed_shape_is_not_read_without_an_extension(self):
        self.register_session("owner", [edit_row(os.path.join(self.repo, "b.txt"), "e1", 1), owner_row("x", 90, "bad")])
        self.assertEqual(self.items(rounds(5))["S5"]["result"], "pass")

    def test_s1_s2_s7_and_s9_do_not_read_the_malformed_shape(self):
        good = [owner_row("x", 90, HUMAN), queued_row("x", 95, HUMAN)] + ask_rows("ask1", {"q": "x"}, 100)
        bad = [owner_row("x", 90, "bad"), queued_row("x", 95, 5)] + ask_rows("ask1", None, 100)
        self.register_session("owner", [edit_row(os.path.join(self.repo, "b.txt"), "e1", 1)] + good)
        events = rounds(5) + [extension()]
        before = self.items(events)
        self.write_rows(self.owner_path_of("owner"), [edit_row(os.path.join(self.repo, "b.txt"), "e1", 1)] + bad)
        after = self.items(events)
        self.assertEqual(after["S5"]["evidence"], "evidence unavailable: malformed origin in owner.jsonl row 2")
        for name in ("S1", "S2", "S7", "S9"):
            self.assertEqual(before[name], after[name], name)

    def owner_path_of(self, session_id):
        return os.path.join(self.root, "projects", f"{session_id}.jsonl")


class FixtureTest(LedgerChecksCase):
    """The invented rows of fixtures/session-2.1.301.jsonl, read through the whole flow."""
    FIXTURE_ROUND = "2026-10-15T12:00:50.000Z"
    FIXTURE_EXTENSION = "2026-10-15T12:02:00.000Z"

    def setUp(self):
        super().setUp()
        with open(os.path.join(HERE, "fixtures", "session-2.1.301.jsonl")) as handle:
            text = handle.read().replace("{WORKTREE}", self.repo)
        path = os.path.join(self.root, "fixture.jsonl")
        with open(path, "w") as handle:
            handle.write(text)
        self.register_path("fixture", path)

    def events(self, quote):
        return ([round_event(n, time="2026-10-15T12:00:%02d.000Z" % (10 * n)) for n in range(1, 6)]
                + [extension_event(time=self.FIXTURE_EXTENSION, quote=quote)])

    def test_each_source_of_the_fixture(self):
        for quote, counts in (("fixture approve alpha", True), ("fixture approve delta", True), ("fixture answer eta", True),
                              ("fixture relay beta", False), ("fixture notice gamma", False), ("fixture relay epsilon", False),
                              ("fixture question zeta", False)):
            with self.subTest(quote=quote):
                item = self.items(self.events(quote))["S5"]
                self.assertEqual(item["result"], "pass" if counts else "fail", item["evidence"])

    def test_the_fixture_still_passes_s1_and_s2_and_stays_synthetic(self):
        items = self.items(self.events("fixture approve alpha"))
        self.assertEqual((items["S1"]["result"], items["S2"]["result"]), ("pass", "pass"))
        with open(os.path.join(HERE, "fixtures", "session-2.1.301.jsonl")) as handle:
            text = handle.read()
        self.assertNotIn("/home/", text)
        rows = [json.loads(line) for line in text.splitlines()]
        self.assertEqual({row["version"] for row in rows if "version" in row}, {"2.1.301"})


class CommandTest(ExtensionCase):
    def check_lines(self):
        result = self.audit("check", "--worktree", self.repo, "--base", "main")
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.decode().splitlines()

    def test_check_and_record_pass_s5_with_a_backed_extension(self):
        self.passes([owner_row(QUOTE, 100, HUMAN)])
        self.assertIn("S5 pass", self.check_lines())

    def test_check_and_record_fail_s5_with_an_unbacked_extension(self):
        self.fails([owner_row("something else", 100, HUMAN)])
        lines = self.check_lines()
        self.assertIn("S5 fail", lines)
        self.assertIn("  " + NOT_FOUND, lines)


if __name__ == "__main__":
    unittest.main()
