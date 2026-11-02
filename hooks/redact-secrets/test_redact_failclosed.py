import time
import unittest

from redact_testkit import bash_event, run_post, updated_output

NOTICE = "[output hidden: redaction hook failed: {}]"
BASH_SHAPE = {"stderr": "", "interrupted": False, "isImage": False, "noOutputExpected": False}


def bash_notice(error_class):
    return dict(BASH_SHAPE, stdout=NOTICE.format(error_class))


def read_notice(error_class):
    return {
        "type": "text",
        "file": {"filePath": "", "content": NOTICE.format(error_class), "numLines": 1, "startLine": 1, "totalLines": 1},
    }


def grep_notice(mode, error_class):
    notice = NOTICE.format(error_class)
    if mode == "files_with_matches":
        return {"mode": mode, "filenames": [notice], "numFiles": 1, "totalFiles": 1}
    if mode == "count":
        return {"mode": mode, "numFiles": 0, "filenames": [], "content": notice, "numMatches": 0}
    return {"mode": "content", "numFiles": 0, "filenames": [], "content": notice, "numLines": 1, "totalLines": 1}


class FailClosedTest(unittest.TestCase):
    def test_stdin_that_is_not_json_gives_malformed_event_in_the_bash_shape(self):
        result = run_post("{not json at all")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(updated_output(result), bash_notice("MalformedEvent"))

    def test_stdin_that_is_json_but_not_an_object_gives_malformed_event(self):
        for raw in ("[1, 2]", '"text"', "7", ""):
            with self.subTest(raw=raw):
                result = run_post(raw)
                self.assertEqual(updated_output(result), bash_notice("MalformedEvent"))

    def test_known_tool_name_picks_the_shape(self):
        event = {"tool_name": "Read", "tool_response": {"type": "text", "file": {"content": "FAKE_SECRET_123"}}}
        result = run_post(event, sleep="abc")
        self.assertEqual(updated_output(result), read_notice("ValueError"))
        event = {"tool_name": "Grep", "tool_response": {"mode": "count", "content": "x"}}
        self.assertEqual(updated_output(run_post(event, sleep="abc")), grep_notice("count", "ValueError"))
        event = {"tool_name": "Grep", "tool_response": {"mode": "files_with_matches", "filenames": ["x"]}}
        self.assertEqual(
            updated_output(run_post(event, sleep="abc")), grep_notice("files_with_matches", "ValueError")
        )
        event = {"tool_name": "Bash", "tool_response": {"stdout": "FAKE_SECRET_123"}}
        self.assertEqual(updated_output(run_post(event, sleep="abc")), bash_notice("ValueError"))

    def test_only_tool_response_keys_pick_the_shape(self):
        cases = (
            ({"stdout": "FAKE_SECRET_123"}, bash_notice("ValueError")),
            ({"file": {"content": "FAKE_SECRET_123"}}, read_notice("ValueError")),
            ({"mode": "content", "content": "FAKE_SECRET_123"}, grep_notice("content", "ValueError")),
        )
        for response, expected in cases:
            with self.subTest(response=response):
                result = run_post({"tool_response": response}, sleep="abc")
                self.assertEqual(updated_output(result), expected)

    def test_unknown_grep_mode_and_unreadable_event_fall_back(self):
        event = {"tool_name": "Grep", "tool_response": {"mode": "weird"}}
        self.assertEqual(updated_output(run_post(event, sleep="abc")), grep_notice("content", "ValueError"))
        self.assertEqual(updated_output(run_post({"tool_response": 5}, sleep="abc")), bash_notice("ValueError"))
        self.assertEqual(updated_output(run_post({}, sleep="abc")), bash_notice("ValueError"))

    def test_the_notice_never_holds_a_part_of_the_original_output(self):
        event = bash_event("PASSWORD=FAKE_SECRET_123")
        result = run_post(event, sleep="abc")
        self.assertNotIn("FAKE_SECRET_123", result.stdout)

    def test_sleep_switch_gives_timeout_within_six_seconds(self):
        start = time.monotonic()
        result = run_post(bash_event("PASSWORD=FAKE_SECRET_123"), sleep="8")
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 6)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(updated_output(result), bash_notice("Timeout"))

    def test_sleep_switch_with_zero_or_negative_sleeps_nothing(self):
        for value in ("0", "-3"):
            with self.subTest(value=value):
                start = time.monotonic()
                result = run_post(bash_event("PASSWORD=FAKE_SECRET_123"), sleep=value)
                self.assertLess(time.monotonic() - start, 4)
                self.assertEqual(updated_output(result)["stdout"], "PASSWORD=***")

    def test_sleep_switch_with_a_non_number_gives_value_error(self):
        result = run_post(bash_event("x"), sleep="abc")
        self.assertEqual(updated_output(result), bash_notice("ValueError"))

    def test_unset_switch_has_no_effect(self):
        result = run_post(bash_event("PASSWORD=FAKE_SECRET_123"))
        self.assertEqual(updated_output(result)["stdout"], "PASSWORD=***")

    def test_input_that_is_not_utf8_fails_closed(self):
        import subprocess
        import sys
        from redact_testkit import POST

        result = subprocess.run([sys.executable, "-I", POST], input=b"\xff\xfe{}", capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"UnicodeDecodeError", result.stdout)


if __name__ == "__main__":
    unittest.main()
