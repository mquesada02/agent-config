# S5 with `extension` events: the quote must be found in real user input of the audited transcripts, through `audit record` and `audit check`.
import json
import os
import shutil
import stat
import subprocess
import unittest

from audit_support import (ABSENT, HERE, ask_rows, edit_row, extension_event, owner_row, phase_commit_event, queued_row, round_event, stamp,
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


class RebaseCase(ExtensionCase):
    FINAL = {"phase": "final"}

    def with_extension(self, events):
        """The S5 item of `events` and an extension of 4 final rounds (cap 7)."""
        return self.s5([owner_row(QUOTE, 100, HUMAN)],
                       events + [extension_event(phase="final", rounds=4, time=stamp(EXTENSION_AT), quote=QUOTE)])

    def past_the_cap(self, item, number):
        self.assertEqual(item["result"], "fail", item["evidence"])
        self.assertIn(f"code-review final: round {number} is past the cap of 7", item["evidence"])


class RebaseRoundTest(RebaseCase):
    """The one final round that follows a rebase (CLAUDE.md section 6 step 3) is not counted against the cap, but only with the proof of a rebase."""

    def setUp(self):
        super().setUp()
        self.original = self.commit("feat: phase", name="phase.txt")
        self.git("checkout", "-q", "main")
        self.commit("chore: main moves", name="main.txt")
        self.git("push", "-q", "origin", "main")
        self.git("checkout", "-q", "feature")
        self.git("rebase", "-q", "main")
        self.rebased = self.git("rev-parse", "HEAD")
        self.git("push", "-q", "--force", "origin", "feature")
        self.tip = self.rebased

    def change_the_patch(self):
        with open(os.path.join(self.repo, "phase.txt"), "w") as handle:
            handle.write("resolved differently")
        self.git("commit", "-q", "-a", "--amend", "--no-edit")
        self.tip = self.git("rev-parse", "HEAD")
        self.git("push", "-q", "--force", "origin", "feature")

    def run_s5(self, first, second, later=(8,)):
        """Final rounds 1 to 7 (cap 3 plus 4 extension rounds) after the phase commit `first`, then `second` and the final rounds `later`."""
        return self.with_extension([round_event(), phase_commit_event(first)] + [round_event(n, **self.FINAL) for n in range(1, 8)]
                                   + [phase_commit_event(second)] + [round_event(n, **self.FINAL) for n in later])

    def exempt(self, first, second, later=(8,)):
        item = self.run_s5(first, second, later)
        self.assertEqual(item["result"], "pass", item["evidence"])
        return item["evidence"]

    def not_exempt(self, first, second, later=(8,)):
        self.past_the_cap(self.run_s5(first, second, later), 8)

    def test_a_round_after_a_rebase_with_a_new_patch_id_passes_and_is_named(self):
        self.change_the_patch()
        evidence = self.exempt(self.original, self.tip)
        self.assertIn(f"round 8 after phase-commit {self.tip[:7]}", evidence)

    def test_a_second_extra_round_after_the_same_phase_commit_fails(self):
        self.change_the_patch()
        item = self.run_s5(self.original, self.tip, (8, 9))
        self.past_the_cap(item, 9)
        self.assertIn(f"round 8 after phase-commit {self.tip[:7]}", item["evidence"])

    def test_the_exemption_goes_to_the_first_round_after_the_phase_commit_not_to_a_later_one(self):
        self.change_the_patch()
        item = self.with_extension([round_event(), phase_commit_event(self.original)] + [round_event(n, **self.FINAL) for n in range(1, 9)]
                                   + [phase_commit_event(self.tip)] + [round_event(9, **self.FINAL)])
        self.past_the_cap(item, 9)

    def test_the_same_patch_id_gives_no_exemption(self):
        self.not_exempt(self.original, self.rebased)

    def test_the_same_parent_gives_no_exemption(self):
        self.change_the_patch()
        self.not_exempt(self.rebased, self.tip)

    def test_a_missing_phase_commit_gives_no_exemption(self):
        self.not_exempt(self.original, "b" * 40)

    def test_a_missing_earlier_phase_commit_gives_no_exemption(self):
        self.change_the_patch()
        self.not_exempt("b" * 40, self.tip)

    def test_a_phase_commit_that_is_not_an_ancestor_of_head_gives_no_exemption(self):
        self.git("checkout", "-q", "-b", "side", "main")
        side = self.commit("feat: side", name="side.txt")
        self.git("checkout", "-q", "feature")
        self.not_exempt(self.original, side)

    def test_the_first_phase_commit_alone_gives_no_exemption(self):
        item = self.with_extension([round_event(), phase_commit_event(self.rebased)] + [round_event(n, **self.FINAL) for n in range(1, 9)])
        self.past_the_cap(item, 8)

    def test_a_round_within_the_cap_needs_no_proof(self):
        events = ([round_event(), phase_commit_event("b" * 40), phase_commit_event("c" * 40)]
                  + [round_event(n, **self.FINAL) for n in range(1, 4)])
        item = self.s5([], events)
        self.assertEqual(item["result"], "pass", item["evidence"])
        self.assertNotIn("exempt", item["evidence"])


FAILING_ANCESTOR_SHIM = """#!/bin/sh
case " $* " in
  *" merge-base --is-ancestor "*) echo "fatal: simulated failure" >&2; exit 5 ;;
esac
exec "$REAL_GIT" "$@"
"""


class TwoRebasesTest(RebaseCase):
    """Two rebases in one task: each phase commit is proven by its base (the merge base with the PR base branch), not by its parent."""

    def move_main(self, name):
        """A pushed commit on main; leaves main checked out. Returns it."""
        self.git("checkout", "-q", "main")
        sha = self.commit("chore: main moves again", name=name)
        self.git("push", "-q", "origin", "main")
        return sha

    def moved_main_and_rebased(self, name, text):
        """Main moves, `feature` is rebased onto it and the phase commit is amended with a new patch. Returns the rewritten phase commit."""
        self.move_main(name)
        self.git("checkout", "-q", "feature")
        self.git("rebase", "-q", "main")
        with open(os.path.join(self.repo, "phase.txt"), "w") as handle:
            handle.write(text)
        self.git("commit", "-q", "-a", "--amend", "--no-edit")
        self.git("push", "-q", "--force", "origin", "feature")
        return self.git("rev-parse", "HEAD")

    def setUp(self):
        """Three phase commits on top of an implementation commit: `first`, then `second` and `third` after two rebases (only `third` is on
        HEAD's history, and the parent of each is rewritten by the rebase after it)."""
        super().setUp()
        self.base = self.move_main("main.txt")
        self.git("checkout", "-q", "feature")
        self.git("reset", "-q", "--hard", "main")
        self.commit("feat: implementation", name="impl.txt")
        self.first = self.commit("feat: phase", name="phase.txt")
        self.second = self.moved_main_and_rebased("main2.txt", "resolved differently")
        self.third = self.moved_main_and_rebased("main3.txt", "resolved again")
        self.tip = self.third

    def three(self, first, second, third):
        """The S5 item: final rounds 1 to 7 after `first`, round 8 after `second` and round 9 after `third` (cap 3 plus 4 extension rounds)."""
        return self.with_extension([round_event(), phase_commit_event(first)] + [round_event(n, **self.FINAL) for n in range(1, 8)]
                                   + [phase_commit_event(second), round_event(8, **self.FINAL),
                                      phase_commit_event(third), round_event(9, **self.FINAL)])

    def only_the_last_is_exempt(self, second):
        item = self.three(self.first, second, self.third)
        self.past_the_cap(item, 9)
        self.assertIn(f"round 9 after phase-commit {self.third[:7]}", item["evidence"])
        self.assertNotIn("round 8 after", item["evidence"])

    def side_branch(self, start, *names):
        """One commit per name on a new branch at `start` (each with a patch unlike the first phase commit); back on `feature`."""
        self.git("checkout", "-q", "-b", f"side-{start[:7]}", start)
        sha = None
        for name in names:
            sha = self.commit(f"side {name}", name=name)
        self.git("checkout", "-q", "feature")
        return sha

    def test_two_real_rebases_exempt_both_rounds(self):
        item = self.three(self.first, self.second, self.third)
        self.assertEqual(item["result"], "pass", item["evidence"])
        self.assertIn(f"round 8 after phase-commit {self.second[:7]}", item["evidence"])
        self.assertIn(f"round 9 after phase-commit {self.third[:7]}", item["evidence"])

    def test_the_earlier_phase_commit_is_not_an_ancestor_of_head(self):
        self.assertFalse(self.is_ancestor(self.second))

    def test_a_missing_second_phase_commit_gives_no_exemption(self):
        self.past_the_cap(self.three(self.first, "b" * 40, self.third), 9)

    def test_a_second_phase_commit_whose_base_is_not_an_ancestor_of_head_gives_no_exemption(self):
        side = self.side_branch(self.move_main("main4.txt"), "s1.txt")
        item = self.three(self.first, side, self.third)
        self.past_the_cap(item, 9)
        self.assertNotIn("after phase-commit", item["evidence"])

    def test_a_second_phase_commit_on_the_base_of_the_earlier_one_gives_no_exemption(self):
        self.only_the_last_is_exempt(self.side_branch(self.base, "s1.txt"))

    def test_a_second_phase_commit_on_an_older_base_gives_no_exemption(self):
        self.only_the_last_is_exempt(self.side_branch(self.git("rev-parse", f"{self.base}^"), "s1.txt"))

    def test_a_rewrite_without_a_base_move_gives_no_exemption_for_the_last_phase_commit_too(self):
        self.git("reset", "-q", "--hard", self.first)
        with open(os.path.join(self.repo, "phase.txt"), "w") as handle:
            handle.write("rewritten in place")
        self.git("commit", "-q", "-a", "--amend", "--no-edit")
        self.git("push", "-q", "--force", "origin", "feature")
        self.tip = self.git("rev-parse", "HEAD")
        item = self.with_extension([round_event(), phase_commit_event(self.first)] + [round_event(n, **self.FINAL) for n in range(1, 8)]
                                   + [phase_commit_event(self.tip), round_event(8, **self.FINAL)])
        self.past_the_cap(item, 8)
        self.assertNotIn("after phase-commit", item["evidence"])

    def test_a_second_phase_commit_with_the_same_patch_gives_no_exemption(self):
        self.git("checkout", "-q", "-b", "same", f"{self.second}^")
        self.git("cherry-pick", self.first)
        same = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "feature")
        self.only_the_last_is_exempt(same)

    def test_a_git_failure_fails_closed_and_names_the_problem(self):
        folder = os.path.join(self.root, "shim")
        os.makedirs(folder)
        path = os.path.join(folder, "git")
        with open(path, "w") as handle:
            handle.write(FAILING_ANCESTOR_SHIM)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        self.env.update(PATH=folder + os.pathsep + os.environ["PATH"], REAL_GIT=shutil.which("git"))
        item = self.three(self.first, self.second, self.third)
        self.past_the_cap(item, 9)
        self.assertIn("rebase proof unavailable: evidence unavailable: git merge-base exited with status 5: fatal: simulated failure", item["evidence"])
        self.assertNotIn("not counting", item["evidence"])

    def test_a_missing_base_ref_fails_closed_and_names_the_problem(self):
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        item = self.three(self.first, self.second, self.third)
        self.past_the_cap(item, 9)
        self.assertIn("rebase proof unavailable: evidence unavailable: no such ref origin/main", item["evidence"])
        self.assertNotIn("not counting", item["evidence"])

    def is_ancestor(self, sha):
        return subprocess.run(["git", "-C", self.repo, "merge-base", "--is-ancestor", sha, "HEAD"]).returncode == 0


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
