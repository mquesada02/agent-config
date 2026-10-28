import json
import os
import unittest

from test_gate import PR, GateTestCase

UNCHECKED_DISPATCH = "unchecked command form: run orchestration worker-start as a plain command"

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
                        "orca orchestration worker-stop",
                        "orca worker-start", "git commit -m worker-start",
                        "ls worker-start"):
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

    def test_a_retry_of_in_a_comment_is_not_read(self):
        self.assert_denied(self.gate(f"{WS} # --retry-of t1"), "no pre-dispatch record")
        self.assert_allowed(self.gate(f"{WS} --retry-of t1 # c"))

    def test_a_retry_of_next_to_a_dispatch_without_it_is_denied(self):
        self.assert_denied(self.gate(f"{WS} --retry-of t1 && {WS}"), "no pre-dispatch record")
        self.assert_denied(self.gate(f"{WS} ; {WS} --retry-of t1"), "no pre-dispatch record")


class HelpTest(DispatchGateCase):
    HELP = "orca-ide orchestration worker-start --help"

    def test_a_help_only_worker_start_is_allowed_without_a_record(self):
        for command in (self.HELP, "orca orchestration worker-start -h", f"cd {self.repo} && {self.HELP}"):
            with self.subTest(command=command):
                result = self.gate(command)
                self.assert_allowed(result)
                self.assertEqual(result.stderr, b"")

    def test_a_help_only_worker_start_needs_no_session_id_or_safe_runtime_folder(self):
        os.makedirs(self.runtime, 0o700, exist_ok=True)
        os.chmod(self.runtime, 0o755)
        self.assert_allowed(self.gate(self.HELP))
        self.assert_allowed(self.hook(tool_input={"command": self.HELP}, cwd=self.repo))

    def test_help_with_another_option_is_denied(self):
        for command in (f"{WS} --help", f"{self.HELP} --task t1", "orca-ide orchestration worker-start --help=x"):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), "no pre-dispatch record")

    def test_a_help_next_to_a_dispatch_is_denied(self):
        self.assert_denied(self.gate(f"{self.HELP} && {WS}"), "no pre-dispatch record")

    def test_a_wrapped_help_is_denied(self):
        self.assert_denied(self.gate(f'bash -c "{self.HELP}"'), UNCHECKED_DISPATCH)
        self.assert_denied(self.gate(f'echo "$({self.HELP})"'), UNCHECKED_DISPATCH)


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


class UncheckedFormTest(DispatchGateCase):
    FORMS = ('bash -c "%s"', "sh -c '%s'", "eval %s", "sudo %s", "nohup %s", "timeout 60 %s", "nice %s", "echo x | xargs %s")

    def forms(self, command):
        return [form % command for form in self.FORMS]

    def test_a_form_that_the_parser_cannot_resolve_is_denied_even_with_a_passing_record(self):
        self.pd_record()
        for command in self.forms(WS):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), UNCHECKED_DISPATCH)

    def test_the_denial_holds_with_retry_of(self):
        self.pd_record()
        for command in self.forms(f"{WS} --retry-of t1"):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), UNCHECKED_DISPATCH)

    def test_a_parsed_match_does_not_hide_a_second_unresolved_occurrence(self):
        self.pd_record()
        for command in (f'{WS}; bash -c "{WS}"', f'{WS} --retry-of t1; bash -c "{WS}"', f'bash -c "{WS}"; {WS} --retry-of t1'):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), UNCHECKED_DISPATCH)

    def test_a_command_that_only_mentions_the_text_is_denied(self):
        # An accepted false positive: the gate cannot tell a mention from a run.
        for command in ("orca-other orchestration worker-start --task t1", "ocra orchestration worker-start", "orchestration worker-start",
                        "echo orca-ide orchestration worker-start", "# orca-ide orchestration worker-start"):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), UNCHECKED_DISPATCH)

    def test_the_text_inside_a_matched_command_is_an_unresolved_occurrence(self):
        self.pd_record()
        self.assert_denied(self.gate(f"{WS} --note 'orchestration worker-start'"), UNCHECKED_DISPATCH)

    def test_a_plain_retry_of_is_still_allowed_with_no_record(self):
        self.assert_allowed(self.gate(f"{WS} --retry-of t1"))
        self.assert_allowed(self.gate(f"{WS} --retry-of t1; {WS} --retry-of t2"))

    def test_the_forms_are_denied_without_a_record_or_a_session_id(self):
        self.assert_denied(self.gate(f'bash -c "{WS}"'), UNCHECKED_DISPATCH)
        self.assert_denied(self.hook(tool_input={"command": f'bash -c "{WS}"'}, cwd=self.repo), UNCHECKED_DISPATCH)

    def test_an_unsafe_runtime_folder_keeps_its_reason_only_for_a_command_with_a_record_check(self):
        self.pd_record()
        os.chmod(self.runtime, 0o755)
        self.assert_denied(self.gate(f'{WS}; bash -c "{WS}"'), "unsafe runtime folder")
        self.assert_denied(self.gate(f'bash -c "{WS}"'), UNCHECKED_DISPATCH)

    def test_a_newline_inside_the_text_is_denied(self):
        self.pd_record()
        self.assert_denied(self.gate("orca-ide orchestration\nworker-start --task t1"), UNCHECKED_DISPATCH)

    def test_a_retry_of_segment_with_a_hidden_second_occurrence_is_denied_in_an_unsafe_runtime_folder(self):
        os.makedirs(self.runtime, 0o700, exist_ok=True)
        os.chmod(self.runtime, 0o755)
        self.assert_denied(self.gate(f'{WS} --retry-of t1; bash -c "{WS}"'), UNCHECKED_DISPATCH)

    def test_a_substitution_is_denied_as_an_unchecked_form(self):
        self.assert_denied(self.gate(f'echo "$({WS})"'), UNCHECKED_DISPATCH)

    def test_the_pr_reason_wins_when_both_gates_have_an_unchecked_form(self):
        self.pd_record()
        self.assert_denied(self.gate(f'bash -c "{WS}"; bash -c "gh pr create"'), "unchecked command form: run gh pr create as a plain command")
        self.assert_denied(self.gate(f'bash -c "gh pr create"; bash -c "{WS}"'), "unchecked command form: run gh pr create as a plain command")

    def test_a_continued_line_is_seen_when_the_command_cannot_be_parsed(self):
        self.assert_denied(self.gate('orca-ide orchestration \\\nworker-start --task "unbalanced'), "no pre-dispatch record: the command cannot be parsed")


class ContinuedLineTest(DispatchGateCase):
    def test_a_retry_of_on_a_continued_line_is_read(self):
        self.assert_allowed(self.gate(f"{WS} \\\n --retry-of t1"))
        self.assert_allowed(self.gate("orca-ide orchestration worker-start \\\n --task t1 \\\n --retry-of=t1"))

    def test_a_continued_dispatch_without_retry_of_is_checked_as_a_plain_command(self):
        self.assert_denied(self.gate(f"{WS} \\\n --task t2"), "no pre-dispatch record")
        self.pd_record()
        self.assert_allowed(self.gate(f"{WS} \\\n --task t2"))

    def test_a_continued_gated_text_is_checked_as_the_plain_command(self):
        command = "orca-ide orchestration \\\nworker-start --task t1"
        self.assert_denied(self.gate(command), "no pre-dispatch record")
        self.pd_record()
        self.assert_allowed(self.gate(command))


class QuotedTextTest(DispatchGateCase):
    def test_a_quoted_gated_command_does_not_offset_an_unresolved_one(self):
        self.pd_record()
        for command in (f'orca-ide orchestration "worker-start" --task t1; bash -c "{WS}"', f"orca-ide 'orchestration' worker-start; bash -c '{WS}'"):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), UNCHECKED_DISPATCH)

    def test_a_lone_quoted_gated_command_is_checked_as_a_plain_command(self):
        self.assert_denied(self.gate('orca-ide orchestration "worker-start" --task t1'), "no pre-dispatch record")
        self.pd_record()
        self.assert_allowed(self.gate('orca-ide orchestration "worker-start" --task t1'))


class SubstitutionTest(DispatchGateCase):
    def test_a_retry_of_after_a_substitution_is_read(self):
        for command in ("orca-ide orchestration worker-start $(true) --retry-of x", "orca-ide orchestration worker-start `true` --retry-of=x",
                        "orca-ide orchestration worker-start --task $((1+2)) --retry-of x"):
            with self.subTest(command=command):
                self.assert_allowed(self.gate(command))

    def test_a_dispatch_after_a_substitution_is_still_checked(self):
        for command in ("orca-ide orchestration worker-start $(true) --task t1", "orca-ide orchestration worker-start `true` --task t1",
                        "echo $(orca-ide orchestration worker-start --task t1)", "echo `orca-ide orchestration worker-start --task t1`"):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), "no pre-dispatch record")


class VariableRuleTest(DispatchGateCase):
    """A segment whose leading words can become `orchestration worker-start` after variable expansion is denied."""

    def test_a_segment_that_can_become_the_gated_command_is_denied_with_a_passing_record(self):
        self.pd_record()
        for command in ("orca-ide orchestration $W", "$O orchestration worker-start", "$O worker-start", "echo $(orca orchestration $W)",
                        f"{WS} && orca-ide orchestration $W"):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), UNCHECKED_DISPATCH)

    def test_a_segment_that_cannot_become_the_gated_command_is_allowed(self):
        for command in ("echo $X", "orca-ide orchestration", "orca-ide orchestration list $N", "orca-ide worktree list $N",
                        "orca-ide orchestration worker-start --task $T --retry-of t1"):
            with self.subTest(command=command):
                self.assert_allowed(self.gate(command))

    def test_the_pr_form_gets_its_own_reason_in_a_dispatch_command(self):
        self.pd_record()
        self.assert_denied(self.gate("$TERRAFORM create"), "unchecked command form: run gh pr create as a plain command")

    def test_an_existing_check_keeps_its_reason(self):
        self.assert_denied(self.gate(f"{WS} && orca-ide orchestration $W"), "no pre-dispatch record")


if __name__ == "__main__":
    unittest.main()
