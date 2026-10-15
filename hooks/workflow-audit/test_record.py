import datetime
import json
import os
import stat
import unittest

from audit_support import PASSING_LLM, AuditCase


class RecordTest(AuditCase):
    def test_writes_the_record_for_the_pushed_tip(self):
        tip = self.start_branch("feature", "feat(audit): add a thing")
        result = self.record()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.record_files(), [f"{tip}.json"])
        record = self.read_record(tip)
        self.assertEqual(record["sha"], tip)
        self.assertEqual(record["remote_url"], self.origin)
        self.assertEqual(record["branch"], "feature")
        self.assertEqual(record["result"], "pass")
        datetime.datetime.fromisoformat(record["time"])
        self.assertEqual([(item["id"], item["kind"], item["result"]) for item in record["items"]],
                         [("S8", "S", "pass")] + [(f"L{n}", "L", "pass") for n in range(1, 7)])
        self.assertTrue(all(isinstance(item["evidence"], str) and item["evidence"] for item in record["items"]))
        self.assertEqual(result.stdout.decode().splitlines()[-1], "result pass")

    def test_record_file_and_runtime_folder_are_private(self):
        tip = self.start_branch("feature", "feat: a")
        self.record()
        self.assertEqual(stat.S_IMODE(os.stat(self.runtime).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.runtime, f"{tip}.json")).st_mode), 0o600)

    def test_s8_is_run_again_and_a_failed_audit_is_recorded(self):
        tip = self.start_branch("feature", "bad message")
        result = self.record()
        self.assertEqual(result.returncode, 1)
        record = self.read_record(tip)
        self.assertEqual(record["result"], "fail")
        s8 = record["items"][0]
        self.assertEqual((s8["id"], s8["result"]), ("S8", "fail"))
        self.assertIn("bad message", s8["evidence"])
        self.assertEqual(result.stdout.decode().splitlines()[0], "S8 fail")

    def test_a_failed_l_verdict_gives_a_failed_record(self):
        tip = self.start_branch("feature", "feat: a")
        self.write_llm(dict(PASSING_LLM, L4={"result": "fail", "evidence": "the report contradicts the ledger"}))
        self.assertEqual(self.record().returncode, 1)
        record = self.read_record(tip)
        self.assertEqual(record["result"], "fail")
        self.assertEqual([item["id"] for item in record["items"] if item["result"] == "fail"], ["L4"])

    def test_a_second_record_for_the_same_sha_replaces_the_first(self):
        tip = self.start_branch("feature", "feat: a")
        self.record()
        self.write_llm(dict(PASSING_LLM, L2={"result": "fail", "evidence": "second run"}))
        self.assertEqual(self.record().returncode, 1)
        self.assertEqual(self.record_files(), [f"{tip}.json"])
        self.assertEqual(self.read_record(tip)["result"], "fail")
        self.assertEqual(os.listdir(self.runtime), [f"{tip}.json"])  # no temp file is left behind

    def test_malformed_l_input_writes_nothing(self):
        self.start_branch("feature", "feat: a")
        good = lambda: {key: dict(value) for key, value in PASSING_LLM.items()}
        cases = {
            "not json": "{nope",
            "not an object": "[]",
            "missing key": {key: value for key, value in PASSING_LLM.items() if key != "L3"},
            "extra key": dict(PASSING_LLM, L7={"result": "pass", "evidence": "x"}),
            "an S result as input": dict(PASSING_LLM, S8={"result": "pass", "evidence": "x"}),
            "bad result": dict(good(), L1={"result": "maybe", "evidence": "x"}),
            "empty evidence": dict(good(), L1={"result": "pass", "evidence": ""}),
            "evidence not a string": dict(good(), L1={"result": "pass", "evidence": 5}),
            "evidence too long": dict(good(), L1={"result": "pass", "evidence": "x" * 4001}),
            "verdict with extra field": dict(good(), L1={"result": "pass", "evidence": "x", "note": "y"}),
            "verdict not an object": dict(good(), L1="pass"),
        }
        for name, content in cases.items():
            with self.subTest(name):
                self.write_llm(content)
                result = self.record()
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("malformed L input", result.stderr.decode())
                self.assertEqual(self.record_files(), [])
        with self.subTest("missing file"):
            os.unlink(self.llm_path)
            self.assertEqual(self.record().returncode, 2)
            self.assertEqual(self.record_files(), [])

    def test_a_long_l_evidence_is_accepted_at_the_limit(self):
        tip = self.start_branch("feature", "feat: a")
        self.write_llm(dict(PASSING_LLM, L1={"result": "pass", "evidence": "x" * 4000}))
        self.assertEqual(self.record().returncode, 0)
        self.assertEqual(len(self.read_record(tip)["items"][1]["evidence"]), 4000)

    def test_a_record_that_the_gate_could_not_read_is_refused(self):
        self.start_branch("feature", "feat: a")
        evidence = "é" * 4000  # escapes to 6 bytes each in ASCII JSON, so 6 items pass 64 KB
        self.write_llm({key: {"result": "pass", "evidence": evidence} for key in PASSING_LLM})
        result = self.record()
        self.assertEqual(result.returncode, 2)
        self.assertIn("record too large", result.stderr.decode())
        self.assertEqual(self.record_files(), [])

    def test_nothing_to_bind_to_writes_nothing(self):
        self.git("checkout", "-b", "unpushed")
        self.commit("feat: a")
        with self.subTest("no origin branch"):
            result = self.record()
            self.assertEqual(result.returncode, 2)
            self.assertIn("push first", result.stderr.decode())
        self.git("push", "-u", "origin", "unpushed")
        self.commit("feat: b")
        with self.subTest("HEAD ahead of the tip"):
            result = self.record()
            self.assertEqual(result.returncode, 2)
            self.assertIn("push first", result.stderr.decode())
        self.git("checkout", "--detach")
        with self.subTest("detached HEAD"):
            self.assertEqual(self.record().returncode, 2)
        with self.subTest("not a git directory"):
            self.assertEqual(self.record(worktree=self.root).returncode, 2)
        self.assertEqual(self.record_files(), [])

    def test_an_unsafe_runtime_folder_writes_nothing(self):
        self.start_branch("feature", "feat: a")
        os.mkdir(self.runtime, 0o755)
        os.chmod(self.runtime, 0o755)
        result = self.record()
        self.assertEqual(result.returncode, 2)
        self.assertIn("unsafe runtime folder", result.stderr.decode())
        self.assertEqual(os.listdir(self.runtime), [])

    def test_the_command_line_is_strict(self):
        self.start_branch("feature", "feat: a")
        cases = [
            ["record"],
            ["record", "--worktree", self.repo],
            ["record", "--llm", self.llm_path],
            ["record", "--worktree", self.repo, "--llm", self.llm_path, "extra"],
            ["record", "--worktree", self.repo, "--worktree", self.repo, "--llm", self.llm_path],
            ["record", "--worktree", self.repo, "--llm"],
            ["ledger"],
            ["hook"],
            ["hook", "nope"],
            [],
        ]
        for args in cases:
            with self.subTest(args=args):
                result = self.audit(*args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertIn("usage:", result.stderr.decode())
        self.assertEqual(self.record_files(), [])

    def test_the_executable_has_an_execute_bit(self):
        from audit_support import AUDIT

        self.assertTrue(os.access(AUDIT, os.X_OK))


if __name__ == "__main__":
    unittest.main()
