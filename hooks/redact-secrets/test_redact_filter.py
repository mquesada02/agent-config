"""Tests of the Monitor line filter. They run redact_filter.py as a subprocess with bytes on stdin, as the pipe does.

Fixtures are built from parts at run time, so that this file holds no secret-shaped text of its own.
"""
import os
import select
import subprocess
import sys
import unittest

from redact_testkit import FILTER, filter_env, run_filter

KEY = "pass" + "word"  # a matched key name
TOK = "to" + "ken"  # a second matched key name
SECRET = "hunter2"
BEGIN = "-----BEGIN " + "PRIVATE KEY-----"
END = "-----END " + "PRIVATE KEY-----"
BEGIN_ENC = "-----BEGIN " + "ENCRYPTED PRIVATE KEY-----"
END_ENC = "-----END " + "ENCRYPTED PRIVATE KEY-----"


def filt(text, switch=None):
    """The text that the filter writes for a text on stdin."""
    result = run_filter(text.encode("utf-8", "surrogateescape"), switch)
    assert result.returncode == 0, result.stderr
    return result.stdout.decode("utf-8", "surrogateescape")


def body_lines(count, prefix="body"):
    return ["%s%d %s\n" % (prefix, number, SECRET) for number in range(count)]


class NormalLineTest(unittest.TestCase):
    def test_an_env_line_is_redacted(self):
        self.assertEqual(filt("%s=%s\n" % (KEY, SECRET)), "%s=***\n" % KEY)

    def test_a_json_line_is_redacted(self):
        self.assertEqual(filt('{"%s": "%s"}\n' % (TOK, SECRET)), '{"%s": "***"}\n' % TOK)

    def test_a_line_with_no_secret_comes_out_byte_for_byte(self):
        for text in ("plain line\n", "plain\r\nline\r\n", "no final newline", "", "\n\n"):
            with self.subTest(text=text):
                self.assertEqual(filt(text), text)

    def test_each_line_keeps_its_own_ending(self):
        self.assertEqual(filt("a\r\n%s=%s\r\nb\n" % (KEY, SECRET)), "a\r\n%s=***\r\nb\n" % KEY)

    def test_the_last_line_without_a_newline_is_redacted_without_one(self):
        self.assertEqual(filt("%s=%s" % (KEY, SECRET)), "%s=***" % KEY)

    def test_invalid_utf8_bytes_pass_through_unchanged(self):
        data = b"\xff\xfe ok\n"
        self.assertEqual(run_filter(data).stdout, data)

    def test_a_carriage_return_inside_a_line_is_kept(self):
        data = b"progress 10%\rprogress 20%\n"
        self.assertEqual(run_filter(data).stdout, data)

    def test_the_exit_code_is_0_at_the_end_of_the_input(self):
        self.assertEqual(run_filter(b"x\n").returncode, 0)


class FlushTest(unittest.TestCase):
    def test_a_line_comes_out_before_the_input_is_closed(self):
        # no -u here: the explicit flush of the filter is what makes the line come out
        process = subprocess.Popen(
            [sys.executable, "-I", FILTER], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=filter_env()
        )
        try:
            process.stdin.write(("%s=%s\n" % (KEY, SECRET)).encode())
            process.stdin.flush()
            ready, _, _ = select.select([process.stdout], [], [], 10)
            self.assertTrue(ready, "no output while stdin is still open")
            self.assertEqual(os.read(process.stdout.fileno(), 100), ("%s=***\n" % KEY).encode())
        finally:
            process.stdin.close()
            process.wait(timeout=10)
            process.stdout.close()


class PemTest(unittest.TestCase):
    def test_a_block_is_held_and_replaced_by_one_line(self):
        text = "a\n" + BEGIN + "\n" + "".join(body_lines(3)) + END + "\nb\n"
        self.assertEqual(filt(text), "a\n***\nb\n")

    def test_the_text_before_begin_and_after_end_is_kept(self):
        text = "pre " + BEGIN + "\n" + "".join(body_lines(2)) + END + " post\n"
        self.assertEqual(filt(text), "pre *** post\n")

    def test_crlf_endings_are_kept(self):
        text = BEGIN + "\r\nbody\r\n" + END + "\r\nafter\r\n"
        self.assertEqual(filt(text), "***\r\nafter\r\n")

    def test_a_block_of_exactly_200_lines_is_replaced_normally(self):
        text = BEGIN + "\n" + "".join(body_lines(198)) + END + "\nafter\n"
        self.assertEqual(text.count("\n"), 201)
        self.assertEqual(filt(text), "***\nafter\n")

    def test_the_cap_drops_the_held_lines_and_the_rest_up_to_end(self):
        text = BEGIN + "\n" + "".join(body_lines(250)) + END + "\nafter\n"
        out = filt(text)
        self.assertEqual(out, "***\nafter\n")
        self.assertNotIn(SECRET, out)

    def test_the_cap_line_is_written_when_the_input_then_ends(self):
        self.assertEqual(filt(BEGIN + "\n" + "".join(body_lines(250))), "***\n")

    def test_a_cap_boundary_with_200_held_lines_and_no_end_writes_the_line(self):
        self.assertEqual(filt(BEGIN + "\n" + "".join(body_lines(199))), "***\n")

    def test_199_held_lines_and_no_end_write_nothing(self):
        self.assertEqual(filt(BEGIN + "\n" + "".join(body_lines(198))), "")

    def test_a_begin_line_with_no_end_before_the_end_of_the_input_writes_nothing(self):
        self.assertEqual(filt("a\n" + BEGIN + "\n" + "".join(body_lines(3))), "a\n")

    def test_a_block_on_one_line_is_a_normal_line(self):
        self.assertEqual(filt("x " + BEGIN + "AAA" + END + " y\n"), "x *** y\n")

    def test_an_encrypted_key_block_is_replaced(self):
        text = BEGIN_ENC + "\nbody\n" + END_ENC + "\nafter\n"
        self.assertEqual(filt(text), "***\nafter\n")

    def test_a_closed_block_followed_by_a_second_begin_holds_the_line(self):
        text = "x " + BEGIN + "a" + END + " y " + BEGIN + "\nSECRETB\n" + END + "\nafter\n"
        out = filt(text)
        self.assertNotIn("SECRETB", out)
        self.assertTrue(out.endswith("after\n"), out)

    def test_an_end_before_the_begin_on_the_begin_line_does_not_end_the_block(self):
        text = END + BEGIN + "\nSECRETB\n" + END + "\nafter\n"
        out = filt(text)
        self.assertNotIn("SECRETB", out)
        self.assertTrue(out.endswith("after\n"), out)

    def test_an_end_line_that_carries_a_second_begin_starts_a_new_block(self):
        text = BEGIN + "\nbody\n" + END + " " + BEGIN + "\nSECRETB\n" + END + "\nafter\n"
        out = filt(text)
        self.assertNotIn("SECRETB", out)
        self.assertTrue(out.endswith("after\n"), out)

    def test_a_cap_end_line_that_carries_a_begin_starts_a_new_block(self):
        text = BEGIN + "\n" + "".join(body_lines(250)) + END + " " + BEGIN + "\nSECRETB\n" + END + "\nafter\n"
        out = filt(text)
        self.assertNotIn("SECRETB", out)
        self.assertNotIn(SECRET, out)
        self.assertTrue(out.endswith("after\n"), out)

    def test_a_key_inside_the_held_block_is_not_written(self):
        text = BEGIN + "\n%s=%s\n" % (KEY, SECRET) + END + "\n"
        self.assertEqual(filt(text), "***\n")


class JsonStateTest(unittest.TestCase):
    def test_a_multi_line_object_under_a_matched_key_is_dropped(self):
        text = (
            '{\n  "%s": {\n    "a": "%s",\n    "b": [1, {"c": 2}],\n    "s": "}",\n  },\n  "ok": 1\n}\n' % (TOK, SECRET)
        )
        out = filt(text)
        self.assertEqual(out, '{\n  "%s": "***"\n,\n  "ok": 1\n}\n' % TOK)

    def test_an_array_under_a_matched_key_is_dropped(self):
        text = '"%s": [\n  "%s",\n  "x"\n]\nafter\n' % (TOK, SECRET)
        self.assertEqual(filt(text), '"%s": "***"\nafter\n' % TOK)

    def test_an_object_of_more_than_200_lines_is_still_dropped_until_it_balances(self):
        text = '"%s": {\n' % TOK + "".join(body_lines(300)) + "}\nafter\n"
        out = filt(text)
        self.assertEqual(out, '"%s": "***"\nafter\n' % TOK)

    def test_an_object_with_no_closing_bracket_writes_only_the_first_line(self):
        text = '"%s": {\n' % TOK + "".join(body_lines(5))
        self.assertEqual(filt(text), '"%s": "***"\n' % TOK)

    def test_an_object_that_closes_on_its_line_is_a_normal_line(self):
        self.assertEqual(filt('{"%s": {"a": 1}}\nafter\n' % TOK), '{"%s": "***"}\nafter\n' % TOK)

    def test_an_object_under_a_key_that_is_not_matched_is_kept(self):
        text = '"other": {\n  "a": 1\n}\n'
        self.assertEqual(filt(text), text)

    def test_a_bracket_inside_a_string_is_ignored(self):
        text = '"%s": {\n  "s": "}}}",\n  "t": "{"\n}\nafter\n' % TOK
        self.assertEqual(filt(text), '"%s": "***"\nafter\n' % TOK)

    def test_only_the_bracket_of_the_value_counts(self):
        text = '{"a": {"%s": {\n  "x": "%s"\n}\n"y": "keep"\n' % (TOK, SECRET)
        self.assertEqual(filt(text), '{"a": {"%s": "***"\n"y": "keep"\n' % TOK)

    def test_a_closed_matched_key_before_an_unclosed_one_does_not_start_the_state(self):
        text = '{"%s": {}, "%s": {\n  "x": "%s"\n}\nafter\n' % (TOK, KEY, SECRET)
        out = filt(text)
        self.assertNotIn(SECRET, out)
        self.assertTrue(out.endswith("after\n"), out)

    def test_an_escaped_key_starts_the_state(self):
        text = '{\\"%s\\": {\nhidden line\n' % TOK
        self.assertEqual(filt(text), '{\\"%s\\": \\"***\\"\n' % TOK)

    def test_a_closing_line_that_opens_a_new_matched_object_starts_a_new_state(self):
        text = '"%s": {\n"a": "S1"\n}, "%s": {\n"b": "S2"\n}\nafter\n' % (TOK, KEY)
        out = filt(text)
        self.assertEqual(out, '"%s": "***"\n, "%s": "***"\nafter\n' % (TOK, KEY))

    def test_the_rest_after_the_closing_bracket_is_written_with_the_line_ending(self):
        text = '"%s": {\r\n"a": 1\r\n}, "ok": 2\r\nafter\r\n' % TOK
        self.assertEqual(filt(text), '"%s": "***"\r\n, "ok": 2\r\nafter\r\n' % TOK)

    def test_a_pem_begin_inside_a_dropped_object_is_dropped_with_it(self):
        text = '"%s": {\n%s\nBODY\n%s\n}\nafter\n' % (TOK, BEGIN, END)
        self.assertEqual(filt(text), '"%s": "***"\nafter\n' % TOK)


class YamlStateTest(unittest.TestCase):
    def test_a_block_scalar_under_a_matched_key_is_dropped(self):
        text = "%s: |\n  line1 %s\n\n  line2\nnext: 1\n" % (KEY, SECRET)
        self.assertEqual(filt(text), "%s: ***\nnext: 1\n" % KEY)

    def test_a_folded_scalar_with_a_modifier_is_dropped(self):
        text = "%s: >-\n  line1 %s\nnext: 1\n" % (KEY, SECRET)
        self.assertEqual(filt(text), "%s: ***\nnext: 1\n" % KEY)

    def test_a_list_item_key_uses_the_column_of_the_key(self):
        text = "- %s: |\n    line1 %s\n  sibling: 1\n" % (KEY, SECRET)
        self.assertEqual(filt(text), "- %s: ***\n  sibling: 1\n" % KEY)

    def test_a_tab_indented_block_is_dropped(self):
        text = "%s: |\n\tline1 %s\nnext: 1\n" % (KEY, SECRET)
        self.assertEqual(filt(text), "%s: ***\nnext: 1\n" % KEY)

    def test_the_block_ends_at_a_line_that_is_not_indented_more(self):
        text = "  %s: |\n    a\n  b: 1\n" % KEY
        self.assertEqual(filt(text), "  %s: ***\n  b: 1\n" % KEY)

    def test_the_first_line_after_the_block_is_a_normal_line(self):
        text = "%s: |\n  a\n%s=%s\n" % (KEY, TOK, SECRET)
        self.assertEqual(filt(text), "%s: ***\n%s=***\n" % (KEY, TOK))

    def test_a_block_scalar_under_a_key_that_is_not_matched_is_kept(self):
        text = "other: |\n  keep\n"
        self.assertEqual(filt(text), text)

    def test_the_end_of_the_input_inside_the_block_writes_only_the_first_line(self):
        self.assertEqual(filt("%s: |\n  a\n  b" % KEY), "%s: ***\n" % KEY)

    def test_crlf_endings_are_kept(self):
        text = "%s: |\r\n  a\r\nnext: 1\r\n" % KEY
        self.assertEqual(filt(text), "%s: ***\r\nnext: 1\r\n" % KEY)


class PriorityTest(unittest.TestCase):
    def test_pem_wins_over_json_on_one_line(self):
        text = '"%s": { %s\nbodyline\n%s }\nafter\n' % (TOK, BEGIN, END)
        out = filt(text)
        self.assertNotIn("bodyline", out)
        self.assertTrue(out.endswith("after\n"), out)

    def test_json_wins_over_yaml_on_one_line(self):
        text = '"%s": { %s: |\n  deep\n}\nafter\n' % (TOK, KEY)
        out = filt(text)
        self.assertEqual(out.splitlines()[-1], "after")
        self.assertNotIn("deep", out)


class FailClosedTest(unittest.TestCase):
    def test_the_fail_switch_writes_nothing_and_exits_non_zero(self):
        result = run_filter(("%s=%s\n" % (KEY, SECRET)).encode(), switch="fail")
        self.assertEqual(result.stdout, b"")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(SECRET.encode(), result.stderr)

    def test_other_switch_values_have_no_effect(self):
        for value in ("2", "", "FAIL"):
            with self.subTest(value=value):
                result = run_filter(b"x\n", switch=value)
                self.assertEqual((result.returncode, result.stdout), (0, b"x\n"))


if __name__ == "__main__":
    unittest.main()
