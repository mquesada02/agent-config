"""Tests of the PreToolUse rewrite hook. They run redact_pre.py as a subprocess, as Claude Code does."""
import json
import os
import subprocess
import unittest

from redact_testkit import HERE, bash_pre_event, monitor_pre_event, run_pre

ROOT = os.path.dirname(os.path.dirname(HERE))
SUFFIX = " || echo command-failed"
PIPE = " 2>&1 | python3 -I -u ~/.claude/hooks/redact-secrets/redact_filter.py"
PREFIX = "redact_pre.py: "


def rewritten(result):
    """The updatedInput of a rewrite result."""
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    hook_output = payload["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "PreToolUse"
    assert "permissionDecision" not in hook_output
    assert set(hook_output) == {"hookEventName", "updatedInput"}
    return hook_output["updatedInput"]


def denied(result):
    """The reason of a deny result."""
    assert result.returncode == 0, result.stderr
    hook_output = json.loads(result.stdout)["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "PreToolUse"
    assert hook_output["permissionDecision"] == "deny"
    assert set(hook_output) == {"hookEventName", "permissionDecision", "permissionDecisionReason"}
    return hook_output["permissionDecisionReason"]


class RewriteTest(unittest.TestCase):
    def command_after(self, command):
        return rewritten(run_pre(bash_pre_event(command)))["command"]

    def test_plain_command_gets_the_exact_suffix(self):
        self.assertEqual(self.command_after("ls"), "ls" + SUFFIX)

    def test_multi_line_command_gets_the_suffix_on_the_last_line(self):
        self.assertEqual(self.command_after("a\nb"), "a\nb" + SUFFIX)

    def test_trailing_newlines_are_stripped_before_the_suffix(self):
        self.assertEqual(self.command_after("ls\n"), "ls" + SUFFIX)
        self.assertEqual(self.command_after("ls\n\n\n"), "ls" + SUFFIX)

    def test_trailing_spaces_tabs_and_crlf_are_stripped_before_the_suffix(self):
        self.assertEqual(self.command_after("ls  \t \n"), "ls" + SUFFIX)
        self.assertEqual(self.command_after("ls\r\n"), "ls" + SUFFIX)

    def test_every_other_input_field_is_unchanged(self):
        extra = {"description": "d", "timeout": 5000, "run_in_background": True, "other": {"a": [1, None]}}
        updated = rewritten(run_pre(bash_pre_event("ls", **extra)))
        self.assertEqual(updated, {"command": "ls" + SUFFIX, **extra})
        self.assertIs(type(updated["timeout"]), int)
        self.assertIs(updated["run_in_background"], True)

    def test_a_rewrite_never_sets_a_permission_decision(self):
        result = run_pre(bash_pre_event("ls"))
        self.assertNotIn("permissionDecision", result.stdout)

    def test_a_here_string_is_safe(self):
        self.assertEqual(self.command_after("cat <<< hi"), "cat <<< hi" + SUFFIX)
        self.assertEqual(self.command_after("cat <<<< hi"), "cat <<<< hi" + SUFFIX)

    def test_a_hash_without_a_space_before_it_is_safe(self):
        self.assertEqual(self.command_after("echo a#b"), "echo a#b" + SUFFIX)
        self.assertEqual(self.command_after("echo ${#x}"), "echo ${#x}" + SUFFIX)

    def test_a_comment_on_an_earlier_line_is_safe(self):
        self.assertEqual(self.command_after("# note\nls"), "# note\nls" + SUFFIX)

    def test_an_empty_command_passes_unchanged(self):
        for command in ("", "   ", "\n\t\n"):
            with self.subTest(command=command):
                result = run_pre(bash_pre_event(command))
                self.assertEqual((result.returncode, result.stdout), (0, ""))


class DenyTest(unittest.TestCase):
    def assert_denied(self, command, cause):
        reason = denied(run_pre(bash_pre_event(command)))
        self.assertTrue(reason.startswith(PREFIX), reason)
        self.assertTrue(reason[len(PREFIX):].startswith(cause), reason)
        self.assertIn("Rephrase the command", reason)

    def test_a_heredoc_is_denied(self):
        self.assert_denied("cat <<EOF\nx\nEOF", "heredoc")

    def test_a_dash_heredoc_is_denied(self):
        self.assert_denied("cat <<-EOF\nx\nEOF", "heredoc")

    def test_a_heredoc_in_the_middle_of_the_command_is_denied(self):
        self.assert_denied("cat <<EOF\nx\nEOF\nls", "heredoc")

    def test_an_arithmetic_shift_is_a_deliberate_false_deny(self):
        self.assert_denied("echo $((1<<3))", "heredoc")

    def test_last_line_endings_are_denied_with_their_own_cause(self):
        endings = {"&&": "&&", "||": "||", ";": ";", "&": "&", "\\": "\\", "|": "|"}
        for ending, name in endings.items():
            with self.subTest(ending=ending):
                self.assert_denied("ls " + ending, "last line ends with `%s`" % name)

    def test_a_trailing_ending_is_found_after_trailing_whitespace(self):
        self.assert_denied("ls ;  \n\n", "last line ends with `;`")

    def test_an_ending_on_an_earlier_line_is_safe(self):
        result = run_pre(bash_pre_event("ls ;\nls"))
        self.assertEqual(rewritten(result)["command"], "ls ;\nls" + SUFFIX)

    def test_a_comment_line_is_denied(self):
        self.assert_denied("ls\n# done", "comment on the last line")
        self.assert_denied("ls\n   # done", "comment on the last line")

    def test_a_quoted_hash_after_a_space_is_a_deliberate_false_deny(self):
        self.assert_denied("echo \"a #b\"", "comment on the last line")

    def test_a_trailing_comment_is_denied(self):
        self.assert_denied("ls # done", "comment on the last line")
        self.assert_denied("ls\t# done", "comment on the last line")

    def test_a_deny_reason_does_not_echo_the_command(self):
        reason = denied(run_pre(bash_pre_event("echo FAKE_SECRET_123 &")))
        self.assertNotIn("FAKE_SECRET_123", reason)


class MonitorRewriteTest(unittest.TestCase):
    def command_after(self, command):
        return rewritten(run_pre(monitor_pre_event(command)))["command"]

    def test_a_plain_command_gets_the_exact_pipe(self):
        self.assertEqual(self.command_after("tail -f x"), "tail -f x" + PIPE)

    def test_a_multi_line_command_gets_the_pipe_on_the_last_line(self):
        self.assertEqual(self.command_after("a\nb"), "a\nb" + PIPE)

    def test_trailing_whitespace_is_stripped_before_the_pipe(self):
        self.assertEqual(self.command_after("tail -f x\n\n"), "tail -f x" + PIPE)
        self.assertEqual(self.command_after("tail -f x  \t\r\n"), "tail -f x" + PIPE)

    def test_a_monitor_command_does_not_get_the_bash_suffix(self):
        self.assertNotIn(SUFFIX, self.command_after("tail -f x"))

    def test_every_other_input_field_is_unchanged(self):
        extra = {"description": "d", "timeout_ms": 5000, "persistent": True, "other": {"a": [1, None]}}
        updated = rewritten(run_pre(monitor_pre_event("tail -f x", **extra)))
        self.assertEqual(updated, {"command": "tail -f x" + PIPE, **extra})
        self.assertIs(type(updated["timeout_ms"]), int)
        self.assertIs(updated["persistent"], True)

    def test_a_rewrite_never_sets_a_permission_decision(self):
        self.assertNotIn("permissionDecision", run_pre(monitor_pre_event("tail -f x")).stdout)

    def test_a_here_string_and_an_earlier_comment_are_safe(self):
        self.assertEqual(self.command_after("cat <<< hi"), "cat <<< hi" + PIPE)
        self.assertEqual(self.command_after("# note\nls"), "# note\nls" + PIPE)

    def test_the_fail_switch_exits_1_for_a_monitor_call(self):
        result = run_pre(monitor_pre_event("ls"), switch="fail")
        self.assertEqual((result.returncode, result.stdout), (1, ""))

    def test_the_rewritten_command_filters_a_secret_end_to_end(self):
        # the pipe names ~/.claude/hooks/...; point it at this repo, which is the ~/.claude repo
        command = self.command_after("printf '%s\\n' '" + "TOKEN" + "=abc123' plain").replace("~/.claude", ROOT)
        result = subprocess.run(["bash", "-c", command], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.stdout, "TOKEN=***\nplain\n")


class MonitorDenyTest(unittest.TestCase):
    def assert_denied(self, command, cause):
        reason = denied(run_pre(monitor_pre_event(command)))
        self.assertTrue(reason.startswith(PREFIX), reason)
        self.assertTrue(reason[len(PREFIX):].startswith(cause), reason)
        self.assertIn("Rephrase the command", reason)

    def test_a_heredoc_is_denied(self):
        self.assert_denied("cat <<EOF\nx\nEOF", "heredoc")
        self.assert_denied("cat <<-EOF\nx\nEOF", "heredoc")

    def test_last_line_endings_are_denied_with_their_own_cause(self):
        for ending in ("&&", "||", ";", "&", "\\", "|"):
            with self.subTest(ending=ending):
                self.assert_denied("tail -f x " + ending, "last line ends with `%s`" % ending)

    def test_a_trailing_ending_is_found_after_trailing_whitespace(self):
        self.assert_denied("tail -f x ;  \n\n", "last line ends with `;`")

    def test_comments_on_the_last_line_are_denied(self):
        self.assert_denied("ls\n# done", "comment on the last line")
        self.assert_denied("ls\n   # done", "comment on the last line")
        self.assert_denied("#", "comment on the last line")
        self.assert_denied("ls # done", "comment on the last line")
        self.assert_denied("ls\t# done", "comment on the last line")

    def test_a_deny_reason_does_not_echo_the_command(self):
        reason = denied(run_pre(monitor_pre_event("echo FAKE_SECRET_123 &")))
        self.assertNotIn("FAKE_SECRET_123", reason)

    def test_a_deny_has_no_updated_input(self):
        self.assertNotIn("updatedInput", run_pre(monitor_pre_event("ls ;")).stdout)


class PassThroughTest(unittest.TestCase):
    def assert_silent(self, event):
        result = run_pre(event)
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_an_empty_monitor_command_passes_unchanged(self):
        for command in ("", "   ", "\n\t\n"):
            with self.subTest(command=command):
                self.assert_silent(monitor_pre_event(command))

    def test_a_non_string_monitor_command_passes_unchanged(self):
        self.assert_silent({"tool_name": "Monitor", "tool_input": {"command": 5}})
        self.assert_silent({"tool_name": "Monitor", "tool_input": {}})

    def test_an_unknown_tool_passes_unchanged(self):
        self.assert_silent({"tool_name": "Read", "tool_input": {"command": "ls"}})

    def test_a_tool_name_that_is_not_a_string_passes_unchanged(self):
        for name in (["x"], {"a": 1}, 5, None):
            with self.subTest(name=name):
                self.assert_silent({"tool_name": name, "tool_input": {"command": "ls"}})

    def test_a_non_string_command_passes_unchanged(self):
        self.assert_silent({"tool_name": "Bash", "tool_input": {"command": 5}})

    def test_a_missing_command_passes_unchanged(self):
        self.assert_silent({"tool_name": "Bash", "tool_input": {}})

    def test_a_tool_input_that_is_not_an_object_passes_unchanged(self):
        self.assert_silent({"tool_name": "Bash", "tool_input": "ls"})
        self.assert_silent({"tool_name": "Bash"})


class FailClosedTest(unittest.TestCase):
    def test_the_fail_switch_exits_1_with_nothing_on_stdout(self):
        result = run_pre(bash_pre_event("ls"), switch="fail")
        self.assertEqual((result.returncode, result.stdout), (1, ""))

    def test_other_switch_values_have_no_effect(self):
        for value in ("2", "", "FAIL"):
            with self.subTest(value=value):
                self.assertEqual(rewritten(run_pre(bash_pre_event("ls"), switch=value))["command"], "ls" + SUFFIX)

    def test_stdin_that_is_not_json_exits_1(self):
        result = run_pre("not json")
        self.assertEqual((result.returncode, result.stdout), (1, ""))

    def test_json_that_is_not_an_object_exits_1(self):
        for text in ("[]", "5", "null", '"x"'):
            with self.subTest(text=text):
                result = run_pre(text)
                self.assertEqual((result.returncode, result.stdout), (1, ""))


class HeaderCommentTest(unittest.TestCase):
    def test_the_post_hook_header_lists_the_rewrite_hook_residual_risks(self):
        with open(os.path.join(HERE, "redact_post.py"), encoding="utf-8") as handle:
            header = handle.read().split('"""')[1]
        self.assertIn("exit N", header)
        self.assertIn("PostToolUseFailure", header)
        self.assertIn("command-failed", header)
        self.assertIn("native error flag", header)
        self.assertIn("refused once", header)

    def test_the_post_hook_header_lists_the_monitor_residual_risks(self):
        with open(os.path.join(HERE, "redact_post.py"), encoding="utf-8") as handle:
            header = handle.read().split('"""')[1]
        for phrase in ("last pipeline", "Monitor commands are not checked", "hide the rest of the stream", "false positive"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, header)

    def test_the_pre_hook_header_describes_the_monitor_pipe(self):
        with open(os.path.join(HERE, "redact_pre.py"), encoding="utf-8") as handle:
            header = handle.read().split('"""')[1]
        self.assertIn("redact_filter.py", header)
        self.assertNotIn("not part of this hook yet", header)


if __name__ == "__main__":
    unittest.main()
