# `audit ledger`: the CLI that appends validated events, run as a subprocess.
import datetime
import json
import os
import stat
import unittest

from audit_support import AuditCase, finding_event, round_event, verdict_event

SHA = "a" * 40
ROUND = ("--loop", "code-review", "--phase", "correctness", "--round", "1", "--reviewer", "rev1")
FINDING = ("--id", "I1", "--loop", "code-review", "--phase", "correctness", "--round", "1", "--loc", "a.py:3",
           "--type", "Blocking", "--reason", "it breaks")
VERDICT = ("--finding", "I1", "--verifier", "ver1", "--result", "confirmed")
STATUS = ("--finding", "I1", "--status", "fixed")


def finding_flags(finding_id, loop="code-review", number="1", kind="Blocking"):
    return ("--id", finding_id, "--loop", loop, "--phase", "correctness", "--round", number, "--loc", "a.py:9",
            "--type", kind, "--reason", "r")


class LedgerCase(AuditCase):
    default_ledger = False

    def setUp(self):
        super().setUp()
        self.start_branch("feature", "feat: a")

    def raw(self):
        """The text of the ledger file, None when it does not exist."""
        if not os.path.exists(self.ledger_file()):
            return None
        with open(self.ledger_file()) as handle:
            return handle.read()

    def written(self):
        return [json.loads(line) for line in self.raw().splitlines()]

    def ok(self, kind, *flags, **kwargs):
        result = self.ledger(kind, *flags, **kwargs)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.decode().strip(), f"ok {kind}")
        return result

    def refused(self, kind, *flags, **kwargs):
        before = self.raw()
        result = self.ledger(kind, *flags, **kwargs)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertEqual(result.stdout, b"")
        self.assertTrue(result.stderr)
        self.assertEqual(before, self.raw(), "a refused event must write nothing")
        return result.stderr.decode()

    def first_round_and_finding(self):
        self.ok("round", *ROUND)
        self.ok("finding", *FINDING)


class AppendTest(LedgerCase):
    def test_each_event_is_appended_as_one_json_line_with_its_keys(self):
        self.ok("round", *ROUND, "--reviewer", "rev2")
        self.ok("finding", *FINDING)
        self.ok("verdict", *VERDICT)
        self.ok("status", *STATUS)
        self.ok("phase-commit", "--sha", SHA)
        events = self.written()
        self.assertEqual([event["kind"] for event in events], ["round", "finding", "verdict", "status", "phase-commit"])
        for event in events:
            moment = datetime.datetime.fromisoformat(event.pop("time"))
            self.assertIsNotNone(moment.tzinfo)
        self.assertEqual(events[0], {"kind": "round", "loop": "code-review", "phase": "correctness", "round": 1,
                                     "reviewers": ["rev1", "rev2"]})
        self.assertEqual(events[1], {"kind": "finding", "id": "I1", "loop": "code-review", "phase": "correctness", "round": 1,
                                     "loc": "a.py:3", "type": "Blocking", "reason": "it breaks"})
        self.assertEqual(events[2], {"kind": "verdict", "finding": "I1", "verifier": "ver1", "result": "confirmed"})
        self.assertEqual(events[3], {"kind": "status", "finding": "I1", "status": "fixed"})
        self.assertEqual(events[4], {"kind": "phase-commit", "sha": SHA})

    def test_the_time_has_millisecond_precision(self):
        self.ok("round", *ROUND)
        self.assertRegex(self.written()[0]["time"], r"T\d\d:\d\d:\d\d\.\d{3}\+00:00$")

    def test_the_ledger_file_and_its_lock_are_private(self):
        self.ok("round", *ROUND)
        self.assertEqual(stat.S_IMODE(os.stat(self.ledger_file()).st_mode), 0o600)
        locks = [name for name in os.listdir(self.runtime) if name.endswith(".lock")]
        self.assertEqual(len(locks), 1)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.runtime, locks[0])).st_mode), 0o600)

    def test_the_help_lists_every_loop_and_phase_value(self):
        for args in (("ledger", "--help"), ("ledger", "round", "--help")):
            result = self.audit(*args)
            self.assertEqual(result.returncode, 0)
            text = result.stdout.decode()
            for value in ("code-review", "plan-review-3", "plan-review-4.1", "plan-review-5.3", "correctness", "final"):
                self.assertIn(value, text)

    def test_the_ledger_is_the_same_for_any_cwd_and_any_session_id(self):
        self.ok("round", *ROUND, env={"CLAUDE_CODE_SESSION_ID": "session-a"}, cwd=self.root)
        self.ok("finding", *FINDING, env={"CLAUDE_CODE_SESSION_ID": "session-b"}, cwd=self.repo)
        self.ok("status", *STATUS, env={"CLAUDE_CODE_SESSION_ID": None}, cwd=self.main)
        self.assertEqual([event["kind"] for event in self.written()], ["round", "finding", "status"])
        self.assertEqual(len([name for name in os.listdir(self.runtime) if name.startswith("ledger-") and name.endswith(".jsonl")]), 1)

    def test_a_branch_has_its_own_ledger(self):
        self.ok("round", *ROUND)
        self.git("checkout", "-b", "other")
        self.ok("round", *ROUND)
        self.assertEqual(len(self.written()), 1)
        with open(self.ledger_file("other")) as handle:
            self.assertEqual(len(handle.read().splitlines()), 1)

    def test_a_repo_with_another_remote_has_its_own_ledger(self):
        self.ok("round", *ROUND)
        self.git("remote", "set-url", "origin", os.path.join(self.root, "elsewhere.git"))
        self.ok("round", *ROUND)
        self.assertEqual(len(self.written()), 1)


class MalformedEventTest(LedgerCase):
    def test_a_malformed_event_is_refused_at_once(self):
        long_text = "x" * 201
        cases = {
            "unknown event": ("nope", *ROUND),
            "no flags": ("round",),
            "missing flag": ("round", "--loop", "code-review", "--phase", "correctness", "--round", "1"),
            "extra flag": ("round", *ROUND, "--sha", SHA),
            "flag of another event": ("status", *STATUS, "--reviewer", "rev1"),
            "repeated single flag": ("round", *ROUND, "--round", "2"),
            "abbreviated flag": ("round", "--loop", "code-review", "--phase", "correctness", "--round", "1", "--review", "rev1"),
            "bad loop": ("round", "--loop", "section-6", "--phase", "correctness", "--round", "1", "--reviewer", "rev1"),
            "bad phase": ("round", "--loop", "code-review", "--phase", "quality", "--round", "1", "--reviewer", "rev1"),
            "round zero": ("round", "--loop", "code-review", "--phase", "correctness", "--round", "0", "--reviewer", "rev1"),
            "round not a number": ("round", "--loop", "code-review", "--phase", "correctness", "--round", "x", "--reviewer", "rev1"),
            "bad agent id": ("round", "--loop", "code-review", "--phase", "correctness", "--round", "1", "--reviewer", "a b"),
            "empty agent id": ("round", "--loop", "code-review", "--phase", "correctness", "--round", "1", "--reviewer", ""),
            "agent id too long": ("round", "--loop", "code-review", "--phase", "correctness", "--round", "1", "--reviewer", "a" * 65),
            "same reviewer twice": ("round", *ROUND, "--reviewer", "rev1"),
            "21 reviewers": ("round", "--loop", "code-review", "--phase", "correctness", "--round", "1",
                             *[arg for n in range(21) for arg in ("--reviewer", f"r{n}")]),
            "bad finding id": ("finding", *FINDING[2:], "--id", "bad id"),
            "bad type": ("finding", *FINDING[:10], "--type", "Major", *FINDING[12:]),
            "loc too long": ("finding", *FINDING[:8], "--loc", long_text, *FINDING[10:]),
            "empty loc": ("finding", *FINDING[:8], "--loc", "", *FINDING[10:]),
            "reason too long": ("finding", *FINDING[:12], "--reason", "x" * 501),
            "reason with a newline": ("finding", *FINDING[:12], "--reason", "a\nb"),
            "reason with a control character": ("finding", *FINDING[:12], "--reason", "a\x07b"),
            "bad verdict result": ("verdict", "--finding", "I1", "--verifier", "ver1", "--result", "maybe"),
            "bad status": ("status", "--finding", "I1", "--status", "open"),
            "short sha": ("phase-commit", "--sha", "abc"),
            "upper case sha": ("phase-commit", "--sha", "A" * 40),
            "no worktree flag": None,
        }
        for name, args in cases.items():
            with self.subTest(name):
                if args is None:
                    result = self.audit("ledger", "round", *ROUND)
                    self.assertEqual(result.returncode, 2)
                    continue
                self.refused(*args)
        self.assertFalse(os.path.exists(self.ledger_file()))

    def test_a_line_over_4096_bytes_is_refused_and_one_just_under_is_accepted(self):
        self.ok("round", *ROUND)
        # "é" is escaped to 6 ASCII bytes. 200 in the loc and 500 in the reason is 4200 bytes of text.
        flags = list(FINDING[:8]) + ["--loc", "é" * 200] + list(FINDING[10:12]) + ["--reason", "é" * 500]
        self.assertIn("event too long", self.refused("finding", *flags))
        flags = list(FINDING[:8]) + ["--loc", "é" * 200] + list(FINDING[10:12]) + ["--reason", "é" * 453]
        self.ok("finding", *flags)
        self.assertEqual(len(self.raw().splitlines()[-1].encode()) + 1, 4095)

    def test_no_origin_a_detached_head_and_a_non_git_path_are_refused(self):
        self.refused("round", *ROUND, worktree=self.root)
        self.git("checkout", "--detach")
        self.refused("round", *ROUND)
        self.git("checkout", "feature")
        self.git("remote", "remove", "origin")
        self.refused("round", *ROUND)
        self.assertFalse(os.path.exists(self.ledger_file()))

    def test_an_unsafe_runtime_folder_writes_nothing(self):
        os.makedirs(self.runtime, exist_ok=True)
        os.chmod(self.runtime, 0o755)
        self.assertIn("unsafe runtime folder", self.refused("round", *ROUND))
        self.assertEqual([name for name in os.listdir(self.runtime) if name.startswith("ledger-")], [])


class ReplayRuleTest(LedgerCase):
    def test_rounds_are_numbered_one_after_the_other_in_each_loop_and_phase(self):
        self.refused("round", "--loop", "code-review", "--phase", "correctness", "--round", "2", "--reviewer", "rev1")
        self.ok("round", *ROUND)
        self.refused("round", *ROUND)  # a repeat of round 1
        self.refused("round", "--loop", "code-review", "--phase", "correctness", "--round", "3", "--reviewer", "rev1")
        self.ok("round", "--loop", "code-review", "--phase", "correctness", "--round", "2", "--reviewer", "rev1")
        # another phase and another loop each start at 1
        self.ok("round", "--loop", "code-review", "--phase", "final", "--round", "1", "--reviewer", "rev1")
        self.ok("round", "--loop", "plan-review-3", "--phase", "correctness", "--round", "1", "--reviewer", "rev1")

    def test_a_round_past_the_cap_is_accepted_so_that_s5_can_fail_it(self):
        for number in range(1, 7):
            self.ok("round", "--loop", "code-review", "--phase", "correctness", "--round", str(number), "--reviewer", "rev1")

    def test_a_finding_needs_its_round_event_and_a_new_id(self):
        self.refused("finding", *FINDING)  # no round event yet
        self.ok("round", *ROUND)
        self.ok("finding", *FINDING)
        self.refused("finding", *FINDING)  # the id exists
        self.refused("finding", *finding_flags("I2", number="2"))  # round 2 has no event
        self.refused("finding", *finding_flags("I3", loop="plan-review-3"))  # that loop has no round event

    def test_a_verdict_needs_a_blocking_finding_of_the_code_review_loop(self):
        self.refused("verdict", *VERDICT)  # no finding
        self.ok("round", *ROUND)
        self.ok("round", "--loop", "plan-review-3", "--phase", "correctness", "--round", "1", "--reviewer", "rev1")
        self.ok("finding", *finding_flags("I1", kind="Minor"))
        self.refused("verdict", *VERDICT)  # a Minor finding
        self.ok("finding", *finding_flags("P1", loop="plan-review-3"))
        self.refused("verdict", "--finding", "P1", "--verifier", "ver1", "--result", "confirmed")  # a plan-review finding
        self.ok("finding", *finding_flags("I2"))
        self.ok("verdict", "--finding", "I2", "--verifier", "ver1", "--result", "confirmed")
        self.ok("verdict", "--finding", "I2", "--verifier", "ver2", "--result", "rejected")  # more than one verdict is allowed

    def test_a_status_needs_an_existing_finding_and_the_latest_status_stands(self):
        self.refused("status", *STATUS)
        self.first_round_and_finding()
        self.ok("status", *STATUS)
        self.ok("status", "--finding", "I1", "--status", "deferred")

    def test_an_invalid_line_in_the_ledger_refuses_every_append(self):
        self.write_ledger("feature", [round_event(), "{not json"])
        message = self.refused("round", "--loop", "code-review", "--phase", "correctness", "--round", "2", "--reviewer", "rev1")
        self.assertIn("line 2", message)

    def test_a_ledger_that_breaks_a_rule_refuses_an_append(self):
        self.write_ledger("feature", [finding_event()])  # a finding before its round event
        self.assertIn("line 1", self.refused("round", *ROUND))
        self.write_ledger("feature", [round_event(), verdict_event()])  # a verdict without a finding
        self.assertIn("line 2", self.refused("round", "--loop", "code-review", "--phase", "correctness", "--round", "2",
                                             "--reviewer", "rev1"))
        self.write_ledger("feature", [dict(round_event(), extra=1)])  # an extra key
        self.assertIn("line 1", self.refused("round", *ROUND))

    def test_a_ledger_that_does_not_end_with_a_newline_refuses_an_append(self):
        with open(self.ledger_file(), "w") as handle:
            handle.write(json.dumps(round_event()))
        self.refused("round", "--loop", "code-review", "--phase", "correctness", "--round", "2", "--reviewer", "rev1")


if __name__ == "__main__":
    unittest.main()
