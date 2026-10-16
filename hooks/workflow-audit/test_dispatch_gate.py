import json
import os
import unittest

from test_gate import PR, GateTestCase

WS = "orca-ide orchestration worker-start --task t1 --agent claude"


class DispatchGateCase(GateTestCase):
    def pd_record(self, sid="s1", result="pass", **override):
        record = {"session_id": sid, "map": 82, "remote_url": self.origin, "branch": "feature", "time": "2026-10-16T00:00:00+00:00",
                  "items": [], "result": result}
        record.update(override)
        self.write_pd_text(sid, json.dumps(record))

    def write_pd_text(self, sid, text):
        os.makedirs(self.runtime, 0o700, exist_ok=True)
        with open(os.path.join(self.runtime, f"pre-dispatch-{sid}.json"), "w") as handle:
            handle.write(text)

    def hook(self, **data):
        return self.audit("hook", "pre-tool-use", stdin=json.dumps(data))


class AllowTest(DispatchGateCase):
    def test_a_passing_record_of_the_session_allows_every_orca_name(self):
        self.pd_record()
        for command in (
            WS,
            "orca orchestration worker-start --task t1",
            "orca-dev orchestration worker-start --task t1",
            "/usr/bin/orca-ide orchestration worker-start --task t1",
            "FOO=1 orca-ide orchestration worker-start --task t1",
            "env orca-ide orchestration worker-start --task t1",
            f"cd {self.repo} && {WS}",
            f"echo hi; {WS}",
            f"({WS})",
            f"true | {WS}",
            f"if true; then {WS}; fi",
            "orca-ide  orchestration \t worker-start --task t1",
        ):
            with self.subTest(command=command):
                result = self.gate(command)
                self.assert_allowed(result)
                self.assertEqual(result.stderr, b"")

    def test_a_command_with_neither_gated_text_is_allowed(self):
        for command in ("ls", "", "orca-ide orchestration send --to x", "orca-ide orchestration list", "orca-ide worktree create",
                        "orca-other orchestration worker-start --task t1", "ocra orchestration worker-start", "orca orchestration worker-stop",
                        "orca worker-start", "orchestration worker-start", "echo orca-ide orchestration worker-start", "git commit -m worker-start",
                        "# orca-ide orchestration worker-start", "ls worker-start"):
            with self.subTest(command=command):
                self.assert_allowed(self.gate(command))

    def test_the_pr_gate_tests_are_not_affected_by_a_record_of_the_session(self):
        self.pd_record()
        self.assert_denied(self.gate(PR), "no record")


class DenialTest(DispatchGateCase):
    def test_no_record(self):
        reason = self.assert_denied(self.gate(WS), "no pre-dispatch record")
        self.assertIn("pre-dispatch", reason)

    def test_a_failed_record(self):
        self.pd_record(result="fail")
        self.assert_denied(self.gate(WS), "failed pre-dispatch record")

    def test_the_record_of_another_session_does_not_count(self):
        self.pd_record(sid="other")
        self.assert_denied(self.gate(WS), "no pre-dispatch record")
        self.assert_allowed(self.gate(WS, session_id="other"))

    def test_an_invalid_record_is_a_hook_error(self):
        for name, text in (("not JSON", "{broken"), ("not an object", "[1]"), ("empty", ""),
                           ("wrong session", json.dumps({"session_id": "other", "result": "pass"})),
                           ("no session", json.dumps({"result": "pass"})),
                           ("bad result", json.dumps({"session_id": "s1", "result": "maybe"})),
                           ("no result", json.dumps({"session_id": "s1"}))):
            with self.subTest(name):
                self.write_pd_text("s1", text)
                self.assert_denied(self.gate(WS), "hook error")

    def test_a_record_that_is_not_a_regular_file_is_a_hook_error(self):
        os.makedirs(os.path.join(self.runtime, "pre-dispatch-s1.json"), 0o700)
        self.assert_denied(self.gate(WS), "hook error")

    def test_a_missing_or_invalid_session_id_is_denied(self):
        self.pd_record()
        base = {"tool_input": {"command": WS}, "cwd": self.repo}
        for name, data in (("missing", base), ("none", dict(base, session_id=None)), ("empty", dict(base, session_id="")),
                           ("number", dict(base, session_id=5)), ("slash", dict(base, session_id="../s1")),
                           ("too long", dict(base, session_id="s" * 129))):
            with self.subTest(name):
                self.assert_denied(self.hook(**data), "hook input unreadable: no session id")

    def test_the_session_id_reason_wins_over_an_unsafe_runtime_folder(self):
        self.pd_record()
        os.chmod(self.runtime, 0o755)
        self.assert_denied(self.hook(tool_input={"command": WS}, cwd=self.repo), "hook input unreadable: no session id")

    def test_an_unsafe_runtime_folder_denies_a_dispatch_and_allows_the_rest(self):
        self.pd_record()
        os.chmod(self.runtime, 0o755)
        self.assert_denied(self.gate(WS), "unsafe runtime folder")
        self.assert_allowed(self.gate("ls"))

    def test_a_dispatch_needs_no_working_directory(self):
        self.pd_record()
        self.assert_allowed(self.hook(session_id="s1", tool_input={"command": WS}))

    def test_every_dispatch_of_a_command_is_checked(self):
        self.assert_denied(self.gate(f"{WS} && {WS}"), "no pre-dispatch record")
        self.pd_record()
        self.assert_allowed(self.gate(f"{WS} && {WS}"))

    def test_a_denied_gate_creates_no_record(self):
        self.gate(WS)
        self.assertEqual(self.record_files(), [])


class RetryOfTest(DispatchGateCase):
    def test_retry_of_is_allowed_without_a_record(self):
        for command in (f"{WS} --retry-of t1", f"{WS} --retry-of=t1", f"orca orchestration worker-start --retry-of t1 --task t2",
                        f"cd {self.repo} && {WS} --retry-of t1", f"{WS} --task --retry-of", "orca-dev orchestration worker-start --retry-of x"):
            with self.subTest(command=command):
                result = self.gate(command)
                self.assert_allowed(result)
                self.assertEqual(result.stderr, b"")

    def test_retry_of_is_allowed_in_an_unsafe_runtime_folder_and_with_no_session_id(self):
        os.makedirs(self.runtime, 0o700, exist_ok=True)
        os.chmod(self.runtime, 0o755)
        self.assert_allowed(self.gate(f"{WS} --retry-of t1"))
        self.assert_allowed(self.hook(tool_input={"command": f"{WS} --retry-of t1"}, cwd=self.repo))

    def test_a_flag_that_only_looks_like_retry_of_does_not_exempt(self):
        for flag in ("--retry-of-x", "--retry", "-retry-of", "retry-of"):
            with self.subTest(flag=flag):
                self.assert_denied(self.gate(f"{WS} {flag} t1"), "no pre-dispatch record")

    def test_a_retry_of_next_to_a_dispatch_without_it_is_denied(self):
        self.assert_denied(self.gate(f"{WS} --retry-of t1 && {WS}"), "no pre-dispatch record")
        self.assert_denied(self.gate(f"{WS} ; {WS} --retry-of t1"), "no pre-dispatch record")


class ParseFailureTest(DispatchGateCase):
    def test_an_unparsable_command_with_worker_start_is_denied_on_the_raw_text(self):
        self.pd_record()  # even a passing record does not open the gate: nothing can be resolved
        for command in ('orca-ide orchestration worker-start --task "unbalanced', "orca-ide  orchestration \t worker-start --task 'x",
                        'echo "a" && orca  orchestration  worker-start "b', 'echo "unbalanced worker-start', 'x "worker-start'):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), "no pre-dispatch record: the command cannot be parsed")

    def test_the_denial_holds_with_retry_of_in_the_text(self):
        for command in ('orca-ide orchestration worker-start --retry-of t1 --task "unbalanced', "orca orchestration worker-start --retry-of=t1 'x"):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), "no pre-dispatch record: the command cannot be parsed")

    def test_a_parse_failure_is_decided_before_the_session_id_and_the_runtime_folder(self):
        command = 'orca-ide orchestration worker-start --task "unbalanced'
        self.assert_denied(self.hook(tool_input={"command": command}, cwd=self.repo), "no pre-dispatch record: the command cannot be parsed")
        self.pd_record()
        os.chmod(self.runtime, 0o755)
        self.assert_denied(self.gate(command), "no pre-dispatch record: the command cannot be parsed")

    def test_an_unparsable_command_without_worker_start_is_allowed(self):
        self.assert_allowed(self.gate('echo "unbalanced'))
        self.assert_allowed(self.gate("orca-ide orchestration send 'x"))

    def test_the_pr_reason_wins_when_both_texts_are_in_an_unparsable_command(self):
        self.assert_denied(self.gate('gh pr create "x; orca-ide orchestration worker-start'), "no branch to check")


class RawInputTest(DispatchGateCase):
    def raw(self, text):
        return self.audit("hook", "pre-tool-use", stdin=text)

    def test_a_hook_input_that_is_not_json_is_matched_on_its_raw_text(self):
        self.assert_denied(self.raw("not json: orca-ide orchestration  worker-start"), "hook input unreadable")
        self.assert_denied(self.raw('["orca orchestration worker-start"]'), "hook input unreadable")
        self.assert_denied(self.raw("not json: gh  pr create"), "hook input unreadable")
        self.assert_allowed(self.raw("not json at all"))
        self.assert_allowed(self.raw("[]"))

    def test_a_missing_field_allows_a_command_that_does_not_match(self):
        for data in ({}, {"session_id": "s1"}, {"tool_input": {"command": 5}}, {"tool_input": {"command": ["orca", "worker-start"]}}):
            with self.subTest(data=data):
                self.assert_allowed(self.hook(**data))

    def test_another_tool_is_ignored(self):
        self.assert_allowed(self.hook(session_id="s1", tool_name="Edit", tool_input={"command": WS}))


class BothGatesTest(DispatchGateCase):
    def test_a_command_with_both_is_allowed_only_when_both_gates_allow(self):
        self.start_branch("feature", "feat: a")
        self.assertEqual(self.record().returncode, 0)
        command = f"{WS}; {PR}"
        self.assert_denied(self.gate(command), "no pre-dispatch record")
        self.pd_record()
        self.assert_allowed(self.gate(command))
        self.assert_allowed(self.gate(f"{PR}; {WS}"))
        os.remove(os.path.join(self.runtime, "pre-dispatch-s1.json"))
        self.assert_denied(self.gate(f"{PR}; {WS}"), "no pre-dispatch record")

    def test_the_first_denial_in_command_order_wins(self):
        self.start_branch("feature", "feat: a")  # no PR record
        self.assert_denied(self.gate(f"{PR}; {WS}"), "no record")
        self.assert_denied(self.gate(f"{WS}; {PR}"), "no pre-dispatch record")


if __name__ == "__main__":
    unittest.main()
