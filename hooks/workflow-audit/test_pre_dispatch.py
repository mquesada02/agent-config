import json
import os
import unittest

from audit_support import (AuditCase, PASSING_LLM, bash_row, edit_row, extension_event, finding_event, phase_commit_event, queued_row,
                           round_event, stamp, status_event, subagent_rows)

SID = "main-session-1"
LOOP_3, LOOP_41 = "plan-review-3", "plan-review-4.1"
QUOTE = "please allow one more final round"
HUMAN, PEER = {"kind": "human"}, {"kind": "peer"}
ALL_PASS = {"S3": "pass", "S5": "pass", "S7": "pass", "XC": "pass"}
S5_FAILS = {**ALL_PASS, "S5": "fail"}
NOT_FOUND ="extension 1 (plan-review-3 final +1): quote not found in real user input"
L1_ONLY = {"L1": PASSING_LLM["L1"]}


def at(second):
    """A ledger time before every subagent start (EARLY), so that a later round of a loop is not blocked by the cross-check."""
    return "1990-01-01T00:00:%02d.000Z" % second


class PreDispatchCase(AuditCase):
    def setUp(self):
        super().setUp()
        self.git("checkout", "-b", "feature")  # not pushed: a pre-dispatch audit needs no push
        self.commit("feat: a")
        self.write_ledger("feature", self.plan_events())
        self.write_llm(L1_ONLY)

    @staticmethod
    def plan_events(*extra):
        return [round_event(loop=LOOP_3), round_event(loop=LOOP_41), *extra]

    def pre_dispatch(self, sid=SID, map_issue="82", worktree=None, llm=None, flags=None):
        args = flags if flags is not None else ["--worktree", worktree or self.repo, "--map", map_issue, "--llm", llm or self.llm_path]
        return self.audit("record", "--pre-dispatch", *args, env={"CLAUDE_CODE_SESSION_ID": sid})

    def record_path(self, sid=SID):
        return os.path.join(self.runtime, f"pre-dispatch-{sid}.json")

    def read_pre_dispatch(self, sid=SID):
        with open(self.record_path(sid)) as handle:
            return json.load(handle)

    def pd_item(self, name, sid=SID):
        return next(item for item in self.read_pre_dispatch(sid)["items"] if item["id"] == name)

    def assert_nothing_written(self, result):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self.record_files(), [])


class RecordTest(PreDispatchCase):
    def test_a_passing_audit_writes_the_record_without_a_push(self):
        result = self.pre_dispatch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.decode().split("\n"), ["S3 pass", "S5 pass", "S7 pass", "XC pass", "L1 pass", "result pass", ""])
        self.assertEqual(self.record_files(), [f"pre-dispatch-{SID}.json"])
        record = self.read_pre_dispatch()
        self.assertEqual(set(record), {"session_id", "map", "remote_url", "branch", "time", "items", "result"})
        self.assertEqual((record["session_id"], record["map"], record["branch"], record["result"]), (SID, 82, "feature", "pass"))
        self.assertEqual(record["remote_url"], self.origin)
        self.assertRegex(record["time"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")
        self.assertEqual([(item["id"], item["kind"], item["result"]) for item in record["items"]],
                         [("S3", "S", "pass"), ("S5", "S", "pass"), ("S7", "S", "pass"), ("XC", "S", "pass"), ("L1", "L", "pass")])
        for item in record["items"]:
            self.assertEqual(set(item), {"id", "kind", "result", "evidence"})

    def test_a_failed_audit_is_recorded_and_exits_1(self):
        self.write_llm({"L1": {"result": "fail", "evidence": "a Blocking finding has no quoted line"}})
        result = self.pre_dispatch()
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"L1 fail", result.stdout)
        self.assertEqual(self.read_pre_dispatch()["result"], "fail")

    def test_a_second_run_of_the_same_session_replaces_the_record(self):
        self.write_ledger("feature", self.plan_events(finding_event("P1", loop=LOOP_3, kind="Blocking")))
        self.assertEqual(self.pre_dispatch().returncode, 1)
        self.assertEqual(self.read_pre_dispatch()["result"], "fail")
        self.write_ledger("feature", self.plan_events(finding_event("P1", loop=LOOP_3, kind="Blocking"), status_event("P1")))
        self.assertEqual(self.pre_dispatch().returncode, 0)
        self.assertEqual(self.read_pre_dispatch()["result"], "pass")
        self.assertEqual(self.record_files(), [f"pre-dispatch-{SID}.json"])

    def test_each_session_has_its_own_record(self):
        self.assertEqual(self.pre_dispatch("one").returncode, 0)
        self.assertEqual(self.pre_dispatch("two", map_issue="83").returncode, 0)
        self.assertEqual(self.record_files(), ["pre-dispatch-one.json", "pre-dispatch-two.json"])
        self.assertEqual(self.read_pre_dispatch("two")["map"], 83)

    def test_the_pr_gate_ignores_the_pre_dispatch_record(self):
        self.assertEqual(self.pre_dispatch().returncode, 0)
        self.git("push", "-u", "origin", "feature")
        reason = self.denial(self.gate("gh pr create --fill"))
        self.assertTrue(reason.startswith("no record"), reason)


class LedgerViewTest(PreDispatchCase):
    def test_code_review_events_do_not_decide(self):
        events = self.plan_events(round_event(loop="code-review"), finding_event("I1", kind="Blocking"), phase_commit_event("a" * 40))
        self.write_ledger("feature", events)
        result = self.pre_dispatch()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("2 events, 0 findings", self.pd_item("S3")["evidence"])

    def test_the_plan_review_5_3_loop_is_not_read(self):
        self.write_ledger("feature", self.plan_events(round_event(loop="plan-review-5.3"), finding_event("T1", loop="plan-review-5.3")))
        self.assertEqual(self.pre_dispatch().returncode, 0)

    def test_an_open_plan_review_finding_fails_s3(self):
        for loop in (LOOP_3, LOOP_41):
            with self.subTest(loop=loop):
                self.write_ledger("feature", self.plan_events(finding_event("P1", loop=loop, kind="Minor")))
                result = self.pre_dispatch()
                self.assertEqual(result.returncode, 1)
                self.assertEqual(self.pd_item("S3")["result"], "fail")
                self.assertIn("P1", self.pd_item("S3")["evidence"])

    def test_a_closed_plan_review_finding_passes(self):
        self.write_ledger("feature", self.plan_events(finding_event("P1", loop=LOOP_3), status_event("P1", "deferred")))
        self.assertEqual(self.pre_dispatch().returncode, 0)

    def test_a_loop_stopped_at_its_cap_may_leave_findings_open(self):
        rounds = [round_event(n, loop=LOOP_3, time=at(n)) for n in range(1, 6)]
        self.write_ledger("feature", [*rounds, finding_event("P1", loop=LOOP_3, n=5), round_event(loop=LOOP_41)])
        result = self.pre_dispatch()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("stopped at cap: 1 open findings", self.pd_item("S3")["evidence"])

    def test_a_missing_plan_review_loop_fails_s3(self):
        for loop, other in ((LOOP_3, LOOP_41), (LOOP_41, LOOP_3)):
            with self.subTest(missing=loop):
                self.write_ledger("feature", [round_event(loop=other)])
                self.assertEqual(self.pre_dispatch().returncode, 1)
                item = self.pd_item("S3")
                self.assertEqual(item["result"], "fail")
                self.assertIn(f"evidence unavailable: no round event for {loop}", item["evidence"])

    def test_a_ledger_of_code_review_events_only_fails_s3(self):
        self.write_ledger("feature", [round_event(loop="code-review")])
        self.assertEqual(self.pre_dispatch().returncode, 1)
        self.assertIn("no round event for plan-review-3, plan-review-4.1", self.pd_item("S3")["evidence"])

    def test_a_round_past_the_cap_fails_s5(self):
        rounds = [round_event(n, loop=LOOP_3, time=at(n)) for n in range(1, 7)]
        self.write_ledger("feature", [*rounds, round_event(loop=LOOP_41)])
        self.assertEqual(self.pre_dispatch().returncode, 1)
        self.assertEqual(self.pd_item("S5")["result"], "fail")
        self.assertIn("past the cap of 5", self.pd_item("S5")["evidence"])

    def test_a_round_past_the_cap_of_the_code_review_loop_does_not_fail_s5(self):
        rounds = [round_event(n, loop="code-review", time=at(n)) for n in range(1, 7)]
        self.write_ledger("feature", [*self.plan_events(), *rounds])
        self.assertEqual(self.pre_dispatch().returncode, 0)

    def test_an_invalid_line_anywhere_fails_s3_s5_and_xc(self):
        self.write_ledger("feature", [*self.plan_events(), "{not json"])
        self.assertEqual(self.pre_dispatch().returncode, 1)
        self.assertIn("invalid ledger", self.pd_item("S3")["evidence"])
        for name in ("S5", "XC"):
            self.assertEqual(self.pd_item(name)["result"], "fail")
            self.assertIn("evidence unavailable", self.pd_item(name)["evidence"])

    def test_a_missing_ledger_fails(self):
        os.remove(self.ledger_file("feature"))
        self.assertEqual(self.pre_dispatch().returncode, 1)
        self.assertIn("no ledger", self.pd_item("S3")["evidence"])
        self.assertEqual(self.pd_item("S7")["result"], "pass")


class CrossCheckAndModelTest(PreDispatchCase):
    def test_a_reviewer_that_is_not_a_subagent_fails_xc(self):
        self.write_ledger("feature", [round_event(loop=LOOP_3, reviewers=("ghost",)), round_event(loop=LOOP_41)])
        self.assertEqual(self.pre_dispatch().returncode, 1)
        self.assertEqual(self.pd_item("XC")["result"], "fail")
        self.assertIn("ghost", self.pd_item("XC")["evidence"])

    def test_a_reviewer_that_started_before_the_previous_round_fails_xc(self):
        self.write_ledger("feature", [round_event(1, loop=LOOP_3, time="9999-01-01T00:00:00.000Z"), round_event(2, loop=LOOP_3),
                                       round_event(loop=LOOP_41)])
        self.assertEqual(self.pre_dispatch().returncode, 1)
        self.assertIn("started before the previous round", self.pd_item("XC")["evidence"])

    def test_a_subagent_that_is_not_sonnet_fails_s7_and_xc(self):
        self.register_session("s2", [edit_row(os.path.join(self.repo, "other.txt"), "t2", 2)],
                              subagents={"opus1": subagent_rows(model="claude-opus-5-5")})
        self.write_ledger("feature", [round_event(loop=LOOP_3, reviewers=("opus1",)), round_event(loop=LOOP_41)])
        self.assertEqual(self.pre_dispatch().returncode, 1)
        self.assertEqual(self.pd_item("S7")["result"], "fail")
        self.assertEqual(self.pd_item("XC")["result"], "fail")


class NoSessionTest(PreDispatchCase):
    default_session = False

    def test_no_session_that_touches_the_worktree_fails_s7_and_xc(self):
        self.register_session("elsewhere", [edit_row(os.path.join(self.root, "not-the-worktree.txt"), "t1", 1)])
        self.assertEqual(self.pre_dispatch().returncode, 1)
        for name in ("S7", "XC"):
            self.assertEqual(self.pd_item(name)["result"], "fail")
            self.assertIn("evidence unavailable", self.pd_item(name)["evidence"])
        self.assertEqual(self.pd_item("S3")["result"], "pass")

    def test_an_empty_registry_fails_s7_and_xc(self):
        self.assertEqual(self.pre_dispatch().returncode, 1)
        self.assertIn("evidence unavailable", self.pd_item("S7")["evidence"])


class UnreadableTranscriptTest(PreDispatchCase):
    def test_a_registered_transcript_that_cannot_be_read_fails_s7_and_xc(self):
        os.makedirs(os.path.join(self.root, "projects", "missing.jsonl"))  # EISDIR, not ENOENT
        self.register_path("gone", os.path.join(self.root, "projects", "missing.jsonl"))
        result = self.pre_dispatch()
        self.assertEqual(result.returncode, 1)
        for name in ("S7", "XC"):
            self.assertEqual(self.pd_item(name)["result"], "fail")
            self.assertIn("evidence unavailable: cannot read transcript missing.jsonl", self.pd_item(name)["evidence"])
        self.assertEqual(self.pd_item("S3")["result"], "pass")
        self.assertEqual(self.pd_item("S5")["result"], "pass")


def rounds(loop, phase, count):
    """Rounds 1 to `count` with explicit times, so that each reviewer starts after the previous round (XC)."""
    return [round_event(n, loop=loop, phase=phase, time=at(n)) for n in range(1, count + 1)]


def write_command(worktree, loop=LOOP_3):
    """The coordinator's Bash command that writes the extension; `worktree` is typed as given."""
    return (f"python3 -I ~/.claude/hooks/workflow-audit/audit ledger extension --worktree {worktree} --loop {loop} "
            f"--phase final --rounds 1 --quote '{QUOTE}'")


class ExtensionOfAnotherWorktreeTest(PreDispatchCase):
    """The ledger is A's (self.repo). The coordinator session of another worktree wrote the extension and holds the owner's words."""

    def coordinator(self, human, command=None, loop=LOOP_3):
        rows = [bash_row(command or write_command(self.repo, loop), "w1", 150)]
        rows.append(human)
        self.register_session("coordinator", rows)

    def ledger_of(self, loop, count=4, extension=True):
        extension_events = [extension_event(loop=loop, phase="final", rounds=1, quote=QUOTE, time=stamp(200))] if extension else []
        other = LOOP_41 if loop == LOOP_3 else LOOP_3
        self.write_ledger("feature", [*rounds(loop, "final", count), round_event(loop=other), *extension_events])

    def assert_items(self, expected):
        result = self.pre_dispatch()
        for name, outcome in expected.items():
            self.assertEqual(self.pd_item(name)["result"], outcome, (name, self.pd_item(name)["evidence"]))
        return result

    def test_the_driving_case_passes(self):
        self.ledger_of(LOOP_3)
        self.coordinator(queued_row(QUOTE, 100, HUMAN))
        result = self.assert_items(ALL_PASS)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_the_same_ledger_without_the_extension_fails_s5(self):
        self.ledger_of(LOOP_3, extension=False)
        self.coordinator(queued_row(QUOTE, 100, HUMAN))
        self.assert_items(S5_FAILS)
        self.assertEqual(self.pd_item("S5")["evidence"], "plan-review-3 final: round 4 is past the cap of 3")

    def test_a_quote_only_in_a_peer_message_fails_s5(self):
        self.ledger_of(LOOP_3)
        self.coordinator(queued_row(QUOTE, 100, PEER))
        self.assert_items({"S5": "fail"})
        self.assertEqual(self.pd_item("S5")["evidence"], NOT_FOUND)

    def test_a_write_command_typed_with_a_tilde_does_not_put_the_session_in_the_audit(self):
        self.ledger_of(LOOP_3)
        self.coordinator(queued_row(QUOTE, 100, HUMAN), command=write_command("~/../repo"))
        self.assert_items({"S5": "fail"})
        self.assertEqual(self.pd_item("S5")["evidence"], NOT_FOUND)

    def test_a_plan_review_4_1_extension_counts(self):
        self.ledger_of(LOOP_41)
        self.coordinator(queued_row(QUOTE, 100, HUMAN), loop=LOOP_41)
        self.assert_items(ALL_PASS)
        self.ledger_of(LOOP_41, extension=False)
        self.assert_items(S5_FAILS)
        self.assertEqual(self.pd_item("S5")["evidence"], "plan-review-4.1 final: round 4 is past the cap of 3")

    def test_an_extension_of_another_loop_stays_out_of_the_view(self):
        for loop, phase, count in (("code-review", "correctness", 5), ("plan-review-5.3", "final", 3)):
            with self.subTest(loop=loop):
                extension = extension_event(loop=loop, phase=phase, rounds=1, quote=QUOTE, time=stamp(200))
                self.write_ledger("feature", [*self.plan_events(), *rounds(loop, phase, count), extension])
                result = self.assert_items(ALL_PASS)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_s3_uses_the_extended_cap(self):
        events = [*rounds(LOOP_3, "final", 3), round_event(loop=LOOP_41), finding_event("P1", loop=LOOP_3, phase="final", n=3)]
        self.write_ledger("feature", events)
        self.assert_items({"S3": "pass"})
        self.write_ledger("feature", [*events, extension_event(loop=LOOP_3, phase="final", rounds=1, quote=QUOTE, time=stamp(200))])
        self.assert_items({"S3": "fail"})
        self.assertIn("P1", self.pd_item("S3")["evidence"])


class ExtensionWithoutSessionTest(PreDispatchCase):
    default_session = False

    def test_a_tilde_write_command_with_no_session_in_the_audit_is_evidence_unavailable(self):
        events = [*rounds(LOOP_3, "final", 4), round_event(loop=LOOP_41),
                  extension_event(loop=LOOP_3, phase="final", rounds=1, quote=QUOTE, time=stamp(200))]
        self.write_ledger("feature", events)
        self.register_session("coordinator", [bash_row(write_command("~/../repo"), "w1", 150), queued_row(QUOTE, 100, HUMAN)])
        self.pre_dispatch()
        self.assertEqual(self.pd_item("S5")["result"], "fail")
        self.assertEqual(self.pd_item("S5")["evidence"], "evidence unavailable: no registered session touches the worktree")

    def test_a_ledger_without_an_extension_needs_no_transcript(self):
        self.pre_dispatch()
        self.assertEqual(self.pd_item("S5")["result"], "pass")
        self.assertEqual(self.pd_item("S5")["evidence"], "2 rounds in 2 loop phases, none past a cap")


class RefusalTest(PreDispatchCase):
    def test_a_missing_or_invalid_session_id(self):
        for sid in (None, "", "a/b", "a b", "x" * 129):
            with self.subTest(sid=sid):
                result = self.audit("record", "--pre-dispatch", "--worktree", self.repo, "--map", "82", "--llm", self.llm_path,
                                    env={"CLAUDE_CODE_SESSION_ID": sid})
                self.assert_nothing_written(result)
                self.assertIn(b"no session id", result.stderr)

    def test_a_bad_map_value(self):
        for value in ("0", "007", "abc", "", "1234567890", "-1", "#82", "8 2", "８２"):
            with self.subTest(value=value):
                self.assert_nothing_written(self.pre_dispatch(map_issue=value))

    def test_the_largest_map_value_is_accepted(self):
        self.assertEqual(self.pre_dispatch(map_issue="999999999").returncode, 0)
        self.assertEqual(self.read_pre_dispatch()["map"], 999999999)

    def test_a_bad_command_line(self):
        base = ["--worktree", self.repo, "--map", "82", "--llm", self.llm_path]
        for name, flags in (("no map", base[:2] + base[4:]), ("no llm", base[:4]), ("no worktree", base[2:]), ("no flags", []),
                            ("repeated map", base + ["--map", "83"]), ("repeated llm", base + ["--llm", self.llm_path]),
                            ("repeated worktree", base + ["--worktree", self.repo]), ("unknown flag", base + ["--extra", "1"]),
                            ("flag without value", base + ["--map"]), ("worktree only", base[:2])):
            with self.subTest(name):
                self.assert_nothing_written(self.pre_dispatch(flags=flags))
        result = self.audit("record", "--pre-dispatch", "--pre-dispatch", *base, env={"CLAUDE_CODE_SESSION_ID": SID})
        self.assert_nothing_written(result)
        self.assertIn(b"usage:", result.stderr)

    def test_the_flags_may_come_in_any_order(self):
        result = self.pre_dispatch(flags=["--llm", self.llm_path, "--map", "82", "--worktree", self.repo])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_map_without_pre_dispatch_is_refused_by_the_plain_record(self):
        result = self.audit("record", "--worktree", self.repo, "--map", "82", "--llm", self.llm_path, env={"CLAUDE_CODE_SESSION_ID": SID})
        self.assert_nothing_written(result)
        self.assertIn(b"usage:", result.stderr)
        self.assertIn(b"--pre-dispatch", result.stderr)

    def test_malformed_l_input(self):
        good = L1_ONLY["L1"]
        for name, content in (("all six keys", PASSING_LLM), ("L1 and L2", {"L1": good, "L2": good}), ("an S key", {"L1": good, "S3": good}),
                              ("no L1", {}), ("only L2", {"L2": good}), ("bad result", {"L1": {"result": "maybe", "evidence": "x"}}),
                              ("no evidence", {"L1": {"result": "pass", "evidence": ""}}),
                              ("long evidence", {"L1": {"result": "pass", "evidence": "x" * 4001}}),
                              ("extra key in L1", {"L1": dict(good, extra=1)}), ("not an object", [1]), ("not JSON", "{broken")):
            with self.subTest(name):
                self.write_llm(content)
                self.assert_nothing_written(self.pre_dispatch())
        os.remove(self.llm_path)
        self.assert_nothing_written(self.pre_dispatch())

    def test_the_plain_record_still_needs_all_six_keys(self):
        self.git("push", "-u", "origin", "feature")
        self.write_llm(L1_ONLY)
        self.assertEqual(self.record().returncode, 2)

    def test_a_detached_head_is_refused(self):
        self.git("checkout", "--detach")
        result = self.pre_dispatch()
        self.assert_nothing_written(result)
        self.assertIn(b"no branch to record", result.stderr)

    def test_a_worktree_outside_git_is_refused(self):
        self.assert_nothing_written(self.pre_dispatch(worktree=self.root))

    def test_no_origin_url_is_refused(self):
        self.git("remote", "remove", "origin")
        result = self.pre_dispatch()
        self.assert_nothing_written(result)
        self.assertIn(b"no remote URL for origin", result.stderr)

    def test_an_unsafe_runtime_folder_is_refused(self):
        os.chmod(self.runtime, 0o755)
        result = self.pre_dispatch()
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"unsafe runtime folder", result.stderr)
        self.assertEqual(self.record_files(), [])

    def test_a_record_over_the_read_limit_is_refused(self):
        wide = "\U0001F600" * 200  # 12 bytes each once the record is written as ASCII JSON
        findings = [{**finding_event(f"P{n}", loop=LOOP_3, kind="Minor"), "loc": wide} for n in range(10)]
        self.write_ledger("feature", self.plan_events(*findings))
        self.write_llm({"L1": {"result": "pass", "evidence": "\U0001F600" * 4000}})
        result = self.pre_dispatch()
        self.assert_nothing_written(result)
        self.assertIn(b"record too large", result.stderr)


if __name__ == "__main__":
    unittest.main()
