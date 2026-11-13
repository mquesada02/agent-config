# A malformed Edit, Write, NotebookEdit or Bash call is skipped only when its result is an is_error InputValidationError (#576).
import os
import re
import unittest

from audit_support import bash_row, call_row, edit_row, result_row
import test_check
import test_transcripts

VALIDATION = "<tool_use_error>InputValidationError: Write failed due to the following issues:\nThe required parameter `file_path` is missing</tool_use_error>"
BLOCKED = "<tool_use_error>Blocked by a hook</tool_use_error>"


def error_row(call_id, seconds, text=VALIDATION, is_error=True, as_list=False):
    row = result_row(call_id, seconds, is_error=is_error, stdout=None)
    row["message"]["content"][0]["content"] = [{"type": "text", "text": text}] if as_list else text
    return row


def malformed_rows(call_id="m1", seconds=5):
    """A Write, an Edit, a Bash and a NotebookEdit call, each without its path or command."""
    return [call_row("Write", {"command": "x"}, call_id + "w", seconds), call_row("Edit", {"old_string": "a"}, call_id + "e", seconds),
            call_row("Bash", {"cmd": "ls"}, call_id + "b", seconds), call_row("NotebookEdit", {}, call_id + "n", seconds)]


class RejectedCallsTest(test_transcripts.TranscriptCase):
    def rows(self, extra):
        return [self.own_edit(), self.run_row("make test", "t1", 20), result_row("t1", 21, is_error=False)] + extra

    def rejected(self, as_list=False):
        rows = malformed_rows()
        return rows + [error_row(row["message"]["content"][0]["id"], 6, as_list=as_list) for row in rows]

    def results(self, extra):
        self.register_session("s1", self.rows(extra))
        return {key: (item["result"], re.sub(r"[0-9a-f]{7,40}", "SHA", item["evidence"])) for key, item in self.items().items()}

    def test_rejected_calls_give_the_results_of_a_transcript_without_them(self):
        with_rows = self.results(self.rejected())
        self.setUp()
        self.assertEqual(with_rows, self.results([]))

    def test_the_result_text_can_be_a_list_of_text_blocks(self):
        with_rows = self.results(self.rejected(as_list=True))
        self.setUp()
        self.assertEqual(with_rows, self.results([]))

    def test_a_malformed_call_with_no_result_is_unavailable(self):
        self.register_session("s1", self.rows(malformed_rows()))
        self.unavailable(self.items())

    def test_a_malformed_call_with_another_error_result_is_unavailable(self):
        for text in (BLOCKED, "InputValidationError: no tag", "x<tool_use_error>InputValidationError"):
            with self.subTest(text=text):
                self.setUp()
                self.register_session("s1", self.rows([call_row("Write", {}, "m1", 5), error_row("m1", 6, text=text)]))
                self.unavailable(self.items())

    def test_a_malformed_call_with_a_result_that_is_not_an_error_is_unavailable(self):
        self.register_session("s1", self.rows([call_row("Write", {}, "m1", 5), error_row("m1", 6, is_error=False)]))
        self.unavailable(self.items())
        self.setUp()
        self.register_session("s1", self.rows([call_row("Write", {}, "m1", 5), error_row("m1", 6, is_error=None)]))
        self.unavailable(self.items())

    def test_one_proven_and_one_unproven_result_is_unavailable(self):
        self.register_session("s1", self.rows([call_row("Write", {}, "m1", 5), error_row("m1", 6), error_row("m1", 7, text=BLOCKED)]))
        self.unavailable(self.items())

    def test_two_malformed_calls_with_one_id_are_unavailable(self):
        self.register_session("s1", self.rows([call_row("Write", {}, "m1", 5), call_row("Write", {}, "m1", 6), error_row("m1", 7)]))
        self.unavailable(self.items())

    def test_a_malformed_call_that_shares_its_id_with_a_read_call_is_unavailable(self):
        self.register_session("s1", self.rows([call_row("Write", {}, "e1", 5), error_row("e1", 6)]))
        self.unavailable(self.items())

    def test_a_well_formed_call_with_a_blocked_result_counts_as_before(self):
        blocked = [bash_row("make test", "b1", 30, cwd=self.wt), error_row("b1", 31, text=BLOCKED)]
        self.register_session("s1", self.rows([]) + blocked)
        with_blocked = {key: item["result"] for key, item in self.items().items()}
        self.setUp()
        self.register_session("s1", self.rows([]) + [bash_row("make test", "b1", 30, cwd=self.wt), result_row("b1", 31, is_error=True)])
        self.assertEqual(with_blocked, {key: item["result"] for key, item in self.items().items()})

    def test_a_well_formed_call_with_an_input_validation_error_result_counts_as_before(self):
        self.register_session("s1", self.rows([edit_row(os.path.join(self.wt, "b.txt"), "e2", 8), error_row("e2", 9)]))
        self.assertEqual(self.items()["S1"]["result"], "pass")

    def test_a_call_to_an_unknown_tool_is_ignored(self):
        self.register_session("s1", self.rows([call_row("Frobnicate", {}, "u1", 5)]))
        self.assertEqual({key: item["result"] for key, item in self.items().items()}["S1"], "pass")


class RejectedDigestTest(test_check.SessionCase):
    def test_sessions_show_notes_each_skipped_call_with_its_file_and_row(self):
        rows = malformed_rows()
        rows += [error_row(row["message"]["content"][0]["id"], 6) for row in rows]
        subagent = [{"type": "user", "timestamp": "2026-10-15T12:00:00.000Z", "version": malformed_rows()[0]["version"],
                     "message": {"role": "user", "content": "prompt"}}, call_row("Write", {"command": "x"}, "s1w", 1), error_row("s1w", 2)]
        self.start_branch("feature", "feat: a")
        self.session(rows, subagents={"rev1": subagent})
        result = self.show()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.decode().count("rejected by the harness, not run:"), 5)
        self.assertIn("rejected by the harness, not run: Write in main-session.jsonl row 2", result.stdout.decode())
        self.assertIn("rejected by the harness, not run: Write in agent-rev1.jsonl row 2", result.stdout.decode())


if __name__ == "__main__":
    unittest.main()
