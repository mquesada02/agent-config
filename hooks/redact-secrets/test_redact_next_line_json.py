"""Tests of ticket 314 (spec 325): the next-line JSON value after a double-quoted secret key, in both seams.

Seam 1 is `redact(text)` through the test kit. Seam 2 is the Monitor filter script on stdin.
"Shape" and "story" numbers in a test name refer to the general spec 311, except where the name says
"325 story". Fixtures are built from parts, so this file holds no secret-shaped text of its own.
"""
import json
import unittest

from redact_testkit import redact, run_filter

K = "pass" + "word"  # a matched key name
V = "hunter2"
V2 = "tail2"
BEGIN = "-----BEGIN PRIVATE " + "KEY-----"
END = "-----END PRIVATE " + "KEY-----"


def filt(text):
    """The text that the Monitor filter writes for a text on stdin."""
    result = run_filter(text.encode("utf-8", "surrogateescape"))
    assert result.returncode == 0, result.stderr
    return result.stdout.decode("utf-8", "surrogateescape")


class NextLineJsonCases:
    """Cases that both seams must satisfy. A subclass defines `seam`."""

    def seam(self, text):
        raise NotImplementedError

    def check(self, text, expected):
        out = self.seam(text)
        self.assertEqual(out, expected)
        if expected != text:
            self.assertNotIn(V, out)
            self.assertNotIn(V2, out)

    # shape 4b and story 9: a string on the next line is masked as one value
    def test_311_shape_4b_next_line_string_keeps_the_json_well_formed(self):
        text = '{"%s":\n"%s"}\n' % (K, V)
        out = self.seam(text)
        self.assertEqual(out, '{"%s":\n"***"}\n' % K)
        self.assertEqual(json.loads(out), {K: "***"})

    def test_311_story_9_next_line_string_is_masked_as_one_value(self):
        self.check('"%s":\n  "%s"\nnext: 1\n' % (K, V), '"%s":\n  "***"\nnext: 1\n' % K)

    def test_311_story_9_next_line_string_with_spaces_inside_is_one_value(self):
        self.check('"%s":\n  "%s %s"\nnext: 1\n' % (K, V, V2), '"%s":\n  "***"\nnext: 1\n' % K)

    def test_311_story_9_the_rest_of_the_value_line_is_a_normal_line(self):
        self.check('{"%s":\n  "%s", "%s": "%s"}\n' % (K, V, K, V2), '{"%s":\n  "***", "%s": "***"}\n' % (K, K))

    def test_325_story_6_blank_lines_and_indent_are_kept_before_a_string(self):
        self.check('"%s":\n\n   "%s"\n' % (K, V), '"%s":\n\n   "***"\n' % K)

    def test_325_story_6_blank_lines_with_spaces_and_tabs_are_kept_before_a_string(self):
        self.check('"%s":\n \t \n\n\t"%s"\n' % (K, V), '"%s":\n \t \n\n\t"***"\n' % K)

    # story 10: a next-line object or array
    def test_311_story_10_next_line_object_is_masked(self):
        self.check('"%s":\n  {"a": "%s"}\nnext: 1\n' % (K, V), '"%s":\n  "***"\nnext: 1\n' % K)

    def test_311_story_10_next_line_array_is_masked(self):
        self.check('"%s":\n  ["%s", "%s"]\nnext: 1\n' % (K, V, V2), '"%s":\n  "***"\nnext: 1\n' % K)

    def test_311_story_10_next_line_object_that_spans_lines_is_masked_to_its_close(self):
        self.check(
            '"%s":\n  {\n    "a": "%s"\n  }\nnext: 1\n' % (K, V), '"%s":\n  "***"\nnext: 1\n' % K
        )

    def test_311_story_10_text_after_the_close_of_a_next_line_object_is_a_normal_line(self):
        self.check('{"%s":\n  {"a": "%s"}, "%s": "%s"}\n' % (K, V, K, V2), '{"%s":\n  "***", "%s": "***"}\n' % (K, K))

    # story 11: the value guard
    def test_311_story_11_next_line_empty_object_stays(self):
        for text in ('"%s":\n  {}\nnext: 1\n' % K, '"%s":\n  { }\nnext: 1\n' % K):
            with self.subTest(text=text):
                self.assertEqual(self.seam(text), text)

    def test_311_story_11_next_line_empty_array_stays(self):
        for text in ('"%s":\n  []\nnext: 1\n' % K, '"%s":\n  [ ]\nnext: 1\n' % K):
            with self.subTest(text=text):
                self.assertEqual(self.seam(text), text)

    def test_311_story_11_next_line_number_stays(self):
        for text in ('"%s":\n  42\nnext: 1\n' % K, '"%s":\n  -1.5\nnext: 1\n' % K):
            with self.subTest(text=text):
                self.assertEqual(self.seam(text), text)

    def test_311_story_11_next_line_true_false_null_stay(self):
        for token in ("true", "false", "null", "TRUE"):
            text = '"%s":\n  %s\nnext: 1\n' % (K, token)
            with self.subTest(text=text):
                self.assertEqual(self.seam(text), text)

    def test_311_story_11_next_line_token_followed_by_a_comma_or_a_bracket_stays(self):
        for text in ('{"%s":\n  42, "b": 1}\n' % K, '{"%s":\n  true}\n' % K, '["x", {"%s":\n  null }]\n' % K):
            with self.subTest(text=text):
                self.assertEqual(self.seam(text), text)

    def test_311_story_11_next_line_string_kept_by_the_value_guard_stays(self):
        for text in ('"%s":\n  "42"\nnext: 1\n' % K, '"%s":\n  ""\nnext: 1\n' % K, '"%s":\n  "true"\n' % K):
            with self.subTest(text=text):
                self.assertEqual(self.seam(text), text)

    # not a JSON value: the empty-key rule of ticket 313
    def test_311_story_8_a_nested_map_with_a_quoted_first_key_is_hidden(self):
        self.check('"%s":\n  "a": %s\nnext: 1\n' % (K, V), '"%s": ***\nnext: 1\n' % K)

    def test_325_story_7_a_next_line_string_followed_by_a_colon_after_spaces_is_a_key(self):
        self.check('"%s":\n  "a" : %s\nnext: 1\n' % (K, V), '"%s": ***\nnext: 1\n' % K)

    def test_325_story_8_a_bare_word_on_the_next_line_takes_the_empty_key_rule(self):
        self.check('"%s":\n  %s\nnext: 1\n' % (K, V), '"%s": ***\nnext: 1\n' % K)

    def test_325_story_8_a_token_followed_by_a_bare_word_takes_the_empty_key_rule(self):
        self.check('"%s":\n  42 %s\nnext: 1\n' % (K, V), '"%s": ***\nnext: 1\n' % K)

    def test_325_story_8_a_string_with_no_closing_quote_takes_the_empty_key_rule(self):
        self.check('"%s":\n  "%s\nnext: 1\n' % (K, V), '"%s": ***\nnext: 1\n' % K)

    def test_325_story_8_a_blank_line_then_a_bare_word_takes_the_empty_key_rule(self):
        self.check('"%s":\n\n  %s\nnext: 1\n' % (K, V), '"%s": ***\nnext: 1\n' % K)

    def test_325_story_8_a_blank_line_then_a_line_at_the_key_indent_hides_the_blank_line(self):
        self.check('"%s":\n\nnext: 1\n' % K, '"%s": ***\nnext: 1\n' % K)

    def test_325_story_8_a_line_back_at_the_key_indent_is_shown(self):
        text = '"%s":\nnext: 1\n' % K
        self.assertEqual(self.seam(text), text)

    # story 18 and the boundaries
    def test_311_story_18_blank_lines_to_the_end_of_the_input(self):
        self.check('"%s":\n\n\n' % K, '"%s": ***\n' % K)

    def test_311_story_18_one_blank_line_to_the_end_of_the_input(self):
        self.check('"%s":\n \n' % K, '"%s": ***\n' % K)

    def test_325_story_9_the_key_as_the_last_line_stays_unchanged(self):
        for text in ('"%s":' % K, '"%s":\n' % K, 'x: 1\n"%s":' % K):
            with self.subTest(text=text):
                self.assertEqual(self.seam(text), text)

    # the scope of the rule
    def test_325_scope_a_single_quoted_key_keeps_the_empty_key_rule(self):
        self.check("'%s':\n  \"%s\"\nnext: 1\n" % (K, V), "'%s': ***\nnext: 1\n" % K)

    def test_325_scope_an_unquoted_yaml_key_keeps_the_empty_key_rule(self):
        self.check('%s:\n  "%s"\nnext: 1\n' % (K, V), "%s: ***\nnext: 1\n" % K)

    def test_325_scope_node_properties_after_the_key_keep_the_key_line(self):
        self.check('"%s": !!str\n  "%s"\nnext: 1\n' % (K, V), '"%s": !!str\n  "***"\nnext: 1\n' % K)

    # a key that an earlier value swallows
    def test_325_a_swallowed_key_leaves_the_next_line_string_as_redact_does(self):
        self.assertEqual(self.seam('"%s": abc "%s":\n"%s"\n' % (K, K, V)), '"%s": ***\n"%s"\n' % (K, V))

    # line endings
    def test_325_crlf_endings_are_kept(self):
        self.check('"%s":\r\n  "%s"\r\nnext: 1\r\n' % (K, V), '"%s":\r\n  "***"\r\nnext: 1\r\n' % K)

    def test_325_crlf_blank_line_before_a_string_is_kept(self):
        self.check('"%s":\r\n\r\n  "%s"\r\n' % (K, V), '"%s":\r\n\r\n  "***"\r\n' % K)


class RulesSeamTest(NextLineJsonCases, unittest.TestCase):
    def seam(self, text):
        return redact(text)


class FilterSeamTest(NextLineJsonCases, unittest.TestCase):
    def seam(self, text):
        return filt(text)

    def test_311_story_10_an_unclosed_next_line_object_drops_its_following_lines(self):
        out = filt('"%s":\n  {\n    "a": "%s",\n    "b": "%s"\n  }\nnext: 1\n' % (K, V, V2))
        self.assertEqual(out, '"%s":\n  "***"\nnext: 1\n' % K)

    def test_311_story_10_an_unclosed_next_line_array_drops_its_following_lines(self):
        out = filt('"%s":\n  [\n    "%s",\n    "%s"\n  ]\nnext: 1\n' % (K, V, V2))
        self.assertEqual(out, '"%s":\n  "***"\nnext: 1\n' % K)

    def test_311_story_18_held_blank_lines_are_never_written_at_the_end_of_the_input(self):
        # the key is swallowed by an earlier value, so only the held blank line decides: it is not written
        self.assertEqual(filt('"%s": abc "%s":\n\n' % (K, K)), '"%s": ***\n' % K)

    def test_311_story_18_a_key_line_with_no_line_ending_is_written_with_none(self):
        self.assertEqual(filt('x: 1\n"%s":' % K), 'x: 1\n"%s":' % K)

    def test_325_story_8_a_value_line_with_a_begin_line_and_no_end_line_takes_the_empty_key_rule(self):
        text = '"%s":\n  %s\nMIIEbody\n%s\nnext: 1\n' % (K, BEGIN, END)
        self.assertEqual(filt(text), '"%s": ***\nnext: 1\n' % K)

    def test_325_story_8_a_value_with_a_begin_line_after_it_takes_the_empty_key_rule(self):
        # without the rule the object is masked on its line and the PEM body lines after it are written
        text = '"%s":\n  {"a": "x"} %s\nMIIEbody\n%s\nnext: 1\n' % (K, BEGIN, END)
        out = filt(text)
        self.assertEqual(out, '"%s": ***\nnext: 1\n' % K)
        self.assertNotIn("MIIEbody", out)

    def test_325_story_8_a_value_at_the_key_indent_with_a_begin_line_after_it_is_hidden(self):
        # the line is at the key indent and no blank line is held, yet its value must not be written
        for value in ('{"a": "%s"}' % V, '"%s"' % V):
            text = '"%s":\n%s %s\nMIIEbody\n%s\nafter\n' % (K, value, BEGIN, END)
            with self.subTest(value=value):
                out = filt(text)
                self.assertEqual(out, '"%s": ***\nafter\n' % K)
                self.assertNotIn(V, out)

    def test_325_story_8_a_begin_line_with_no_end_line_hides_the_rest(self):
        text = '"%s":\n  %s\nMIIEbody\nnext: 1\n' % (K, BEGIN)
        self.assertEqual(filt(text), '"%s": ***\n' % K)


class SeamAgreementTest(unittest.TestCase):
    """311 story 17: for LF text the two seams give the same output."""

    def test_311_story_17_both_seams_agree_on_the_next_line_json_forms(self):
        for text in (
            '{"%s":\n"%s"}\n' % (K, V),
            '"%s":\n  "%s"\nnext: 1\n' % (K, V),
            '"%s":\n\n   "%s"\n' % (K, V),
            '"%s":\n  {"a": "%s"}\nnext: 1\n' % (K, V),
            '"%s":\n  {\n    "a": "%s"\n  }\nnext: 1\n' % (K, V),
            '"%s":\n  ["%s", "%s"]\nnext: 1\n' % (K, V, V2),
            '"%s":\n  {}\nnext: 1\n' % K,
            '"%s":\n  []\nnext: 1\n' % K,
            '"%s":\n  42\nnext: 1\n' % K,
            '{"%s":\n  42, "b": 1}\n' % K,
            '"%s":\n  "42"\n' % K,
            '"%s":\n  "a": %s\nnext: 1\n' % (K, V),
            '"%s":\n  42 %s\nnext: 1\n' % (K, V),
            '"%s":\n  "%s\nnext: 1\n' % (K, V),
            '"%s":\n  %s\nnext: 1\n' % (K, V),
            '"%s":\n\n  %s\nnext: 1\n' % (K, V),
            '"%s":\nnext: 1\n' % K,
            '"%s":\n\n\n' % K,
            '"%s":' % K,
            '"%s": abc "%s":\n"%s"\n' % (K, K, V),
            "'%s':\n  \"%s\"\nnext: 1\n" % (K, V),
            '%s:\n  "%s"\nnext: 1\n' % (K, V),
            '"%s": !!str\n  "%s"\nnext: 1\n' % (K, V),
            '"%s":\n  %s\nMIIEbody\n%s\nnext: 1\n' % (K, BEGIN, END),
        ):
            with self.subTest(text=text):
                self.assertEqual(filt(text), redact(text))


if __name__ == "__main__":
    unittest.main()
