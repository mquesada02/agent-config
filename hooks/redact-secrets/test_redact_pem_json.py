"""Tests of ticket 315 (spec 329): PEM then JSON in the Monitor filter, and the pr-22 input of ticket 313.

Seam 1 is `redact(text)` through the test kit. Seam 2 is the Monitor filter script on stdin.
`redact(text)` already masks every input of this file; the shared cases pin that reference result and the
filter has to give the same text. The cases that differ by design say so. "Shape" and "story" numbers in a
test name refer to the general spec 311, except where the name says "329 story". Fixtures are built from
parts, so this file holds no secret-shaped text of its own. The docs checks read the hook files as text:
they are the one exception to "tests do not call helpers".
"""
import os
import unittest

from redact_testkit import FILTER, HERE, redact, run_filter

K = "pass" + "word"  # a matched key name
TK = "to" + "ken"  # a second matched key name
V = "hunter2"
BEGIN = "-----BEGIN PRIVATE " + "KEY-----"
END = "-----END PRIVATE " + "KEY-----"


def filt(text):
    """The text that the Monitor filter writes for a text on stdin."""
    result = run_filter(text.encode("utf-8", "surrogateescape"))
    assert result.returncode == 0, result.stderr
    return result.stdout.decode("utf-8", "surrogateescape")


def lines(*parts):
    return "\n".join(parts) + "\n"


def body_lines(count):
    return ["MIIE%03d" % number for number in range(count)]


class PemJsonCases:
    """Cases that both seams must satisfy with the same text. A subclass defines `seam`."""

    def seam(self, text):
        raise NotImplementedError

    def check(self, text, expected):
        out = self.seam(text)
        self.assertEqual(out, expected)
        self.assertNotIn(V, out)

    # shape 3: a BEGIN line opens a PEM block inside an object under a secret key
    def test_311_shape_3_object_stays_open_after_the_end_line(self):
        text = lines('{"%s": {"k": "%s' % (K, BEGIN), "MIIE", END + '",', '"n": "%s"' % V, "}", "after: 1")
        self.check(text, lines('{"%s": "***"' % K, "after: 1"))

    def test_311_shape_3_end_line_closes_the_object(self):
        text = lines('{"%s": {"k": "%s' % (K, BEGIN), "MIIE", END + '"}}', "next: 1")
        self.check(text, lines('{"%s": "***"}' % K, "next: 1"))

    def test_329_story_3_end_line_closes_the_object_and_nothing_follows(self):
        text = lines('{"%s": {"k": "%s' % (K, BEGIN), "MIIE", END + '"}', "next: 1")
        self.check(text, lines('{"%s": "***"' % K, "next: 1"))

    def test_311_shape_3_array_under_the_secret_key(self):
        text = lines('{"%s": ["a", "%s' % (K, BEGIN), "MIIE", END + '",', '"%s"]' % V, "after: 1")
        self.check(text, lines('{"%s": "***"' % K, "after: 1"))

    def test_311_shape_3_text_before_the_secret_key_is_kept(self):
        text = lines('x {"%s": {"k": "%s' % (K, BEGIN), "MIIE", END + '",', '"n": "%s"' % V, "}", "after: 1")
        self.check(text, lines('x {"%s": "***"' % K, "after: 1"))

    def test_311_shape_3_closed_object_before_the_begin_line_starts_no_json_state(self):
        text = lines('{"%s": {"a": 1}, "t": "%s' % (K, BEGIN), "MIIE", END + '",', "next: 1")
        self.check(text, lines('{"%s": "***", "t": "***",' % K, "next: 1"))

    def test_329_story_1_text_after_the_closing_bracket_is_a_normal_line(self):
        text = lines('{"%s": {"k": "%s' % (K, BEGIN), "MIIE", END + '",', '"n": "x"', '}, "%s": "%s"' % (K, V), "after: 1")
        out = self.seam(text)
        self.assertNotIn(V, out)
        self.assertTrue(out.endswith("after: 1\n"))

    # the bracket scan never counts a bracket inside a PEM pair
    def test_329_rule_r1_bracket_inside_a_complete_pair_on_a_normal_line(self):
        text = lines('"%s": {"x": 1 %s } %s "k": "v"' % (K, BEGIN, END), '"n": "%s"' % V, "}", "after: 1")
        self.check(text, lines('"%s": "***"' % K, "after: 1"))

    def test_329_rule_r1_bracket_inside_a_complete_pair_before_an_unclosed_begin_line(self):
        text = lines(
            '"%s": {"x": 1 %s } %s "k": "%s' % (K, BEGIN, END, BEGIN), "MIIE", END + '",', '"n": "%s"' % V, "}", "after: 1"
        )
        self.check(text, lines('"%s": "***"' % K, "after: 1"))

    def test_329_rule_r1_two_begin_lines_on_one_line_with_a_bracket_between_them(self):
        text = lines('{"%s": {"x": 1 %s } %s' % (K, BEGIN, BEGIN), "MIIE", END + ', "n": "%s"}}' % V, "after: 1")
        self.check(text, lines('{"%s": "***"}' % K, "after: 1"))

    # pr-22 (ticket 313): a BEGIN line inside a dropped object
    def test_329_rule_r4_bracket_inside_a_pair_in_a_dropped_object(self):
        text = lines('"%s": {' % TK, '"x": 1 %s } %s' % (BEGIN, END), '"n": "%s"' % V, "}", "after: 1")
        self.check(text, lines('"%s": "***"' % TK, "after: 1"))

    def test_329_rule_r5_begin_and_end_on_different_lines_in_a_dropped_object(self):
        text = lines('"%s": {' % TK, '"x": 1 %s } ' % BEGIN, "MIIE", END, '"n": "%s"' % V, "}", "after: 1")
        self.check(text, lines('"%s": "***"' % TK, "after: 1"))

    def test_329_rule_r5_brackets_in_the_pem_body_do_not_close_a_dropped_object(self):
        text = lines('"%s": {' % TK, '"x": 1 %s' % BEGIN, "}", "]", END, '"n": "%s"' % V, "}", "after: 1")
        self.check(text, lines('"%s": "***"' % TK, "after: 1"))

    def test_329_rule_r5_two_begin_lines_in_a_dropped_object(self):
        text = lines('"%s": {' % TK, '"x": 1 %s } %s' % (BEGIN, BEGIN), "MIIE", END + ', "n": "%s"' % V, "}", "after: 1")
        self.check(text, lines('"%s": "***"' % TK, "after: 1"))

    # the pending JSON value state of ticket 314 meets a BEGIN line
    def test_329_rule_r6_next_line_object_with_an_unclosed_begin_line(self):
        text = lines('"%s":' % K, '{"a": "%s' % BEGIN, "MIIE", END + '",', '"n": "%s"}' % V, "after")
        self.check(text, lines('"%s":' % K, '"***"', "after"))

    def test_329_rule_r6_indented_next_line_object_with_an_unclosed_begin_line(self):
        text = lines('"%s":' % K, '  {"a": "%s' % BEGIN, "  MIIE", "  " + END + '",', '  "n": "%s"}' % V, "after")
        self.check(text, lines('"%s":' % K, '  "***"', "after"))

    def test_329_rule_r6_closing_bracket_on_its_own_line(self):
        text = lines('"%s":' % K, '{"a": "%s' % BEGIN, "MIIE", END + '",', '"n": "%s"' % V, "}", "after")
        self.check(text, lines('"%s":' % K, '"***"', "after"))

    def test_329_rule_r6_blank_lines_before_the_object_are_kept(self):
        text = lines('"%s":' % K, "", '{"a": "%s' % BEGIN, "MIIE", END + '",', '"n": "%s"}' % V, "after")
        self.check(text, lines('"%s":' % K, "", '"***"', "after"))

    def test_329_rule_r6_long_pem_body_in_a_next_line_object(self):
        text = lines('"%s":' % K, '{"a": "%s' % BEGIN, *body_lines(250), END + '",', '"n": "%s"}' % V, "after")
        self.check(text, lines('"%s":' % K, '"***"', "after"))

    def test_311_story_13_the_empty_key_hidden_lines_rule_is_unchanged(self):
        text = lines("%s:" % K, "  %s" % BEGIN, "MIIE", END, "after: 1")
        self.assertNotIn("MIIE", self.seam(text))


class RedactSeamTest(PemJsonCases, unittest.TestCase):
    def seam(self, text):
        return redact(text)


class FilterSeamTest(PemJsonCases, unittest.TestCase):
    def seam(self, text):
        return filt(text)

    # the held-line cap (200 lines): the held path keeps the head, the past-cap path writes one *** line
    def test_311_shape_3_cap_boundary_held_path_writes_the_masked_head(self):
        text = lines('{"%s": {"k": "%s' % (K, BEGIN), *body_lines(198), END + '",', '"n": "%s"' % V, "}", "after: 1")
        self.assertEqual(filt(text), lines('{"%s": "***"' % K, "after: 1"))

    def test_311_shape_3_cap_boundary_past_the_cap_object_stays_open(self):
        text = lines('{"%s": {"k": "%s' % (K, BEGIN), *body_lines(199), END + '",', '"n": "%s"' % V, "}", "after: 1")
        self.assertEqual(filt(text), lines("***", "after: 1"))

    def test_329_story_2_past_the_cap_end_line_closes_the_object_with_an_empty_rest(self):
        text = lines('{"%s": {"k": "%s' % (K, BEGIN), *body_lines(250), END + '"}', "after: 1")
        self.assertEqual(filt(text), lines("***", "after: 1"))

    def test_329_story_3_past_the_cap_text_after_the_closing_bracket_is_a_normal_line(self):
        # ticket 347: a key after `}` and a space is prose; after a comma, with a `{` in the line prefix, it counts
        text = lines('{"%s": {"k": "%s' % (K, BEGIN), *body_lines(250), END + '"}, %s: %s' % (K, V), "after: 1")
        self.assertEqual(filt(text), lines("***", ", %s: ***" % K, "after: 1"))

    def test_329_story_2_past_the_cap_shape_3_array(self):
        text = lines('{"%s": ["a", "%s' % (K, BEGIN), *body_lines(250), END + '",', '"%s"]' % V, "after: 1")
        self.assertEqual(filt(text), lines("***", "after: 1"))

    def test_329_story_4_pr_22_exact_input_of_ticket_315(self):
        text = lines('"%s": {' % TK, '"x": 1 %s } %s %s:' % (BEGIN, END, K), "      " + V)
        out = filt(text)
        self.assertNotIn(V, out)
        self.assertEqual(out, lines('"%s": "***"' % TK))

    def test_329_story_4_pr_22_exact_input_is_masked_by_redact(self):
        text = lines('"%s": {' % TK, '"x": 1 %s } %s %s:' % (BEGIN, END, K), "      " + V)
        self.assertNotIn(V, redact(text))

    def test_311_shape_3_second_begin_line_in_the_rest_of_the_end_line(self):
        text = lines(
            '{"%s": {"k": "%s' % (K, BEGIN), "MIIE", END + '", "j": "%s } ' % BEGIN, "MIIE2", END + ', "n": "%s"}}' % V, "after: 1"
        )
        self.assertNotIn(V, filt(text))
        self.assertNotIn(V, redact(text))

    # redact(text) keeps a JSON string open across lines, so a string open at the END line hides the rest
    def test_329_rule_r8_string_open_at_the_end_line_hides_the_following_lines(self):
        text = lines('{"%s": {"k": "%s' % (K, BEGIN), "MIIE", END, "}", V, "after: 1")
        out = filt(text)
        self.assertNotIn(V, out)
        self.assertEqual(out, lines('{"%s": "***"' % K))
        self.assertNotIn(V, redact(text))

    def test_329_rule_r8_string_open_at_the_end_line_hides_the_following_lines_after_a_pending_key(self):
        text = lines('"%s":' % K, '{"a": "%s' % BEGIN, "MIIE", END, "}", V, "after: 1")
        out = filt(text)
        self.assertNotIn(V, out)
        self.assertEqual(out, lines('"%s":' % K, '"***"'))
        self.assertNotIn(V, redact(text))

    def test_329_rule_r8_a_later_quote_closes_the_open_string(self):
        text = lines('{"%s": {"k": "%s' % (K, BEGIN), "MIIE", END, 'x", "n": "%s"' % V, "}", "after: 1")
        out = filt(text)
        self.assertNotIn(V, out)
        self.assertEqual(out, lines('{"%s": "***"' % K, "after: 1"))

    def test_329_rule_r6_a_string_value_line_with_an_unclosed_begin_line_keeps_the_314_behavior(self):
        text = lines('"%s":' % K, '"abc %s' % BEGIN, "MIIE", END + '"', "after: 1")
        out = filt(text)
        self.assertNotIn("MIIE", out)
        self.assertEqual(out, lines('"%s": ***' % K, "after: 1"))


class DocsTest(unittest.TestCase):
    def read(self, name):
        with open(os.path.join(HERE, name), encoding="utf-8") as handle:
            return handle.read()

    def test_329_story_6_residual_risk_list_names_none_of_the_closed_forms(self):
        text = self.read("redact_post.py")
        self.assertNotIn("a YAML sequence under a matched key", text)
        self.assertNotIn("a JSON value on the line after its key", text)
        self.assertNotIn("a YAML block scalar with a tag, an anchor or a quoted key", text)
        self.assertNotIn("One input leaks", text)

    def test_329_story_6_residual_risk_pem_bullet_says_the_json_state_goes_on(self):
        self.assertIn("the JSON state goes on after a PEM block", self.read("redact_post.py"))

    def test_329_story_6_filter_docstring_lists_the_pem_then_json_rules(self):
        text = self.read(os.path.basename(FILTER))
        self.assertIn("the JSON state goes on after the END line", text)
        self.assertIn("a bracket inside a PEM block", text)


if __name__ == "__main__":
    unittest.main()
