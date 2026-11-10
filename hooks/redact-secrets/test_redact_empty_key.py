"""Tests of ticket 313 (spec 318): the fail-closed rule for a secret key with an empty value, in both seams.

Seam 1 is `redact(text)` through the test kit. Seam 2 is the Monitor filter script on stdin.
"Shape" and "story" numbers in a test name refer to the general spec 311, except where the name says
"318 story". Fixtures are built from parts, so this file holds no secret-shaped text of its own.
"""
import os
import unittest

from redact_testkit import HERE, filt, redact

K = "pass" + "word"  # a matched key name
V = "hunter2"
V2 = "tail2"
BEGIN = "-----BEGIN PRIVATE " + "KEY-----"
END = "-----END PRIVATE " + "KEY-----"
AWS = "AKIA" + "IOSFODNN7EXAMPLE"


class EmptyKeyCases:
    """Cases that both seams must satisfy. A subclass defines `seam`."""

    def seam(self, text):
        raise NotImplementedError

    def check(self, text, expected):
        out = self.seam(text)
        self.assertEqual(out, expected)
        if expected != text:
            self.assertNotIn(V, out)
            self.assertNotIn(V2, out)

    # shape 2: a value on the line after an empty secret key
    def test_311_shape_2_indented_value_after_an_empty_key(self):
        self.check("%s:\n  %s\nnext: 1\n" % (K, V), "%s: ***\nnext: 1\n" % K)

    def test_311_shape_2_value_deeper_by_a_tab(self):
        self.check("%s:\n\t%s\nnext: 1\n" % (K, V), "%s: ***\nnext: 1\n" % K)

    # shape 4a: a sequence under an empty secret key
    def test_311_shape_4a_sequence_deeper_than_the_key(self):
        self.check("%s:\n  - %s\n  - %s\nnext: 1\n" % (K, V, V2), "%s: ***\nnext: 1\n" % K)

    def test_311_shape_4a_sequence_at_the_key_indent(self):
        self.check("%s:\n- %s\n- %s\nnext: 1\n" % (K, V, V2), "%s: ***\nnext: 1\n" % K)

    def test_311_shape_4a_sequence_at_the_key_indent_of_a_nested_key(self):
        self.check("top:\n  %s:\n  - %s\n  other: 1\n" % (K, V), "top:\n  %s: ***\n  other: 1\n" % K)

    # stories 5 and 8: the fail-closed rule hides a nested map, and the first line back at the key indent is shown
    def test_311_story_8_nested_map_is_hidden_and_the_line_back_at_the_key_indent_is_shown(self):
        self.check("%s:\n  a: %s\n  b:\n    c: %s\nnext: 1\n" % (K, V, V2), "%s: ***\nnext: 1\n" % K)

    def test_311_story_8_nested_key_with_a_nested_key_indent(self):
        self.check("top:\n  %s:\n    a: %s\n  other: 1\n" % (K, V), "top:\n  %s: ***\n  other: 1\n" % K)

    def test_311_story_8_double_quoted_key_with_a_quoted_first_nested_key(self):
        self.check('"%s":\n  "a": %s\nnext: 1\n' % (K, V), '"%s": ***\nnext: 1\n' % K)

    # story 7: the form of the key line
    def test_311_story_7_single_quoted_key(self):
        self.check("'%s':\n  %s\nnext: 1\n" % (K, V), "'%s': ***\nnext: 1\n" % K)

    def test_311_story_7_double_quoted_key(self):
        self.check('"%s":\n  %s\nnext: 1\n' % (K, V), '"%s": ***\nnext: 1\n' % K)

    def test_311_story_7_key_in_a_list_item_uses_the_column_of_the_key(self):
        self.check("- %s:\n    %s\n  sibling: 1\n" % (K, V), "- %s: ***\n  sibling: 1\n" % K)

    # story 6 and the boundaries
    def test_311_story_6_a_line_at_the_key_indent_leaves_the_text_unchanged(self):
        for text in ("%s:\nnext: 1\n" % K, "  %s:\n  next: 1\n" % K, "%s:\n-x\n" % K):
            with self.subTest(text=text):
                self.assertEqual(self.seam(text), text)

    def test_311_story_5_a_blank_line_then_a_line_at_the_key_indent(self):
        self.check("%s:\n\nnext: 1\n" % K, "%s: ***\nnext: 1\n" % K)

    def test_311_story_5_blank_lines_with_spaces_and_tabs_are_removed(self):
        self.check("%s:\n \t \n\nnext: 1\n" % K, "%s: ***\nnext: 1\n" % K)

    def test_311_story_6_the_key_as_the_last_line_stays_unchanged(self):
        for text in ("%s:" % K, "%s:\n" % K, "x: 1\n%s:" % K, "x: 1\n%s: \n" % K):
            with self.subTest(text=text):
                self.assertEqual(self.seam(text), text)

    def test_311_story_18_a_double_quoted_key_and_blank_lines_to_the_end_of_the_input(self):
        self.check('"%s":\n\n\n' % K, '"%s": ***\n' % K)

    def test_311_story_3_an_empty_key_hides_lines_to_the_end_of_the_input(self):
        out = self.seam("%s:\n  %s" % (K, V))
        self.assertNotIn(V, out)
        self.assertTrue(out.startswith("%s: ***" % K), out)

    # story 13: node properties and an empty value
    def test_311_story_13_a_tag_alone_with_a_hidden_line(self):
        self.check("%s: !!str\n  %s\nnext: 1\n" % (K, V), "%s: ***\nnext: 1\n" % K)

    def test_311_story_13_an_anchor_alone_with_a_hidden_line(self):
        self.check("%s: &a\n  %s\nnext: 1\n" % (K, V), "%s: ***\nnext: 1\n" % K)

    def test_311_story_13_a_tag_then_an_anchor_with_a_hidden_line(self):
        self.check("%s: !!str &a\n  %s\nnext: 1\n" % (K, V), "%s: ***\nnext: 1\n" % K)

    def test_311_story_13_an_anchor_then_a_tag_with_a_hidden_line(self):
        self.check("%s: &a !x\n  %s\nnext: 1\n" % (K, V), "%s: ***\nnext: 1\n" % K)

    def test_311_story_13_properties_after_a_quoted_key_with_a_hidden_line(self):
        self.check("'%s': !!str\n  %s\nnext: 1\n" % (K, V), "'%s': ***\nnext: 1\n" % K)
        self.check('"%s": &a\n  %s\nnext: 1\n' % (K, V), '"%s": ***\nnext: 1\n' % K)

    def test_311_story_13_properties_with_trailing_spaces_and_a_hidden_line(self):
        self.check("%s: !!str \t\n  %s\nnext: 1\n" % (K, V), "%s: ***\nnext: 1\n" % K)

    def test_311_story_13_properties_with_no_hidden_line_stay_unchanged(self):
        for text in (
            "%s: !!str\nnext: 1\n" % K, "%s: &a\nnext: 1\n" % K, "%s: !!str &a \nnext: 1\n" % K,
            "'%s': !!str\nnext: 1\n" % K, '"%s": &a\nnext: 1\n' % K, "%s: !!str" % K,
        ):
            with self.subTest(text=text):
                self.assertEqual(self.seam(text), text)

    # not an empty-key line
    def test_318_an_env_pair_with_an_empty_value_opens_no_rule(self):
        text = "%s=\n  keep\n" % K
        self.assertEqual(self.seam(text), text)

    def test_318_a_key_that_is_not_matched_hides_nothing(self):
        text = "other:\n  keep\n"
        self.assertEqual(self.seam(text), text)

    def test_318_a_comment_after_the_colon_is_not_an_empty_value(self):
        out = self.seam("%s: # note\n  keep\n" % K)
        self.assertIn("  keep\n", out)

    def test_318_a_value_on_the_key_line_keeps_the_old_rules(self):
        self.check("%s: %s\n  keep\n" % (K, V), "%s: ***\n  keep\n" % K)

    def test_318_a_key_swallowed_by_an_earlier_value_hides_nothing_when_the_line_is_not_deeper(self):
        # the second key is at a flow-mapping position, so it counts (ticket 348) and the first value swallows it;
        # it opens the empty-key rule (ticket 381) with its own column, and the line is not deeper than that column
        text = "%s: abc {a: 1, %s:\n  keep\n" % (K, K)
        self.assertEqual(self.seam(text), "%s: ***\n  keep\n" % K)

    def test_381_a_swallowed_key_hides_a_line_that_is_deeper_than_it(self):
        # redact masks the key line, and the swallowed key opens the empty-key rule with its own column (21)
        text = "%s: abc {a: 1, %s:\n%skeep\nnext: 1\n" % (K, K, " " * 30)
        self.assertEqual(self.seam(text), "%s: ***\nnext: 1\n" % K)

    # line endings
    def test_318_crlf_endings_are_kept_on_the_key_line(self):
        self.check("%s:\r\n  %s\r\nnext: 1\r\n" % (K, V), "%s: ***\r\nnext: 1\r\n" % K)

    def test_318_crlf_blank_line_after_the_key(self):
        self.check("%s:\r\n\r\nnext: 1\r\n" % K, "%s: ***\r\nnext: 1\r\n" % K)

    def test_318_crlf_key_with_no_hidden_line_stays_unchanged(self):
        text = "%s:\r\nnext: 1\r\n" % K
        self.assertEqual(self.seam(text), text)

    # another secret on the key line
    def test_318_another_secret_on_the_key_line_is_still_masked(self):
        # the key column is measured before the shape masks, so the value line is indented past it
        # the key is at a flow-mapping position, so it counts (ticket 348)
        text = "{a: %s, %s:\n%s%s\nb: 1\n" % (AWS, K, " " * 40, V)
        self.assertEqual(self.seam(text), "{a: ***, %s: ***\nb: 1\n" % K)

    def test_318_another_secret_on_an_unhidden_key_line_is_still_masked(self):
        self.assertEqual(self.seam("{a: %s, %s:\nb: 1\n" % (AWS, K)), "{a: ***, %s:\nb: 1\n" % K)

    # PEM blocks around the rule
    def test_318_a_pem_block_under_the_key_is_hidden_with_its_unindented_body(self):
        text = "%s:\n  %s\nMIIEbody\n%s\nnext: 1\n" % (K, BEGIN, END)
        self.assertEqual(self.seam(text), "%s: ***\nnext: 1\n" % K)

    def test_318_a_pem_block_with_no_end_line_under_the_key_hides_the_rest(self):
        text = "%s:\n  %s\nMIIEbody\nnext: 1\n" % (K, BEGIN)
        self.assertEqual(self.seam(text), "%s: ***\n" % K)

    def test_318_a_pem_block_in_a_sequence_at_the_key_indent(self):
        text = "%s:\n- %s\nMIIEbody\n%s\n- %s\nnext: 1\n" % (K, BEGIN, END, V)
        self.assertEqual(self.seam(text), "%s: ***\nnext: 1\n" % K)

    def test_318_a_complete_pem_block_before_the_key_shortens_its_column(self):
        # the key is at a flow-mapping position (ticket 348); its masked column is 7, its raw column is much larger
        text = "{ %s x %s, %s:\n%skeep\nnext: 1\n" % (BEGIN, END, K, " " * 10)
        self.assertEqual(self.seam(text), "{ ***, %s: ***\nnext: 1\n" % K)


class RulesSeamTest(EmptyKeyCases, unittest.TestCase):
    def seam(self, text):
        return redact(text)

    def test_318_rest_line_after_an_end_line_uses_the_column_of_the_masked_text(self):
        # the key is at a flow-mapping position (ticket 348): its column in the full line is 15
        text = "{a: 1, c: %s\nbody\n%s, %s:\n     keep\n" % (BEGIN, END, K)
        self.assertEqual(redact(text), "{a: 1, c: ***, %s:\n     keep\n" % K)

    def test_318_rest_line_after_a_json_close_uses_the_column_of_the_whole_line(self):
        text = '"%s": {\n"a": 1\n{"z": 1}}, %s:\n    keep\nnext: 1\n' % (K, K)
        self.assertEqual(redact(text), '"%s": "***", %s:\n    keep\nnext: 1\n' % (K, K))


class FilterSeamTest(EmptyKeyCases, unittest.TestCase):
    def seam(self, text):
        return filt(text)

    def test_318_rest_line_after_an_end_line_uses_the_column_of_the_rest_only(self):
        # fail-closed difference (spec 318): the filter hides a line that redact(text) shows
        text = "{a: 1, c: %s\nbody\n%s, %s:\n     keep\n" % (BEGIN, END, K)
        self.assertEqual(filt(text), "{a: 1, c: ***, %s: ***\n" % K)

    def test_318_rest_line_after_a_json_close_uses_the_column_of_the_rest_only(self):
        text = '"%s": {\n"a": 1\n{"z": 1}}, %s:\n    keep\nnext: 1\n' % (K, K)
        out = filt(text)
        self.assertIn("%s: ***\n" % K, out)
        self.assertNotIn("keep", out)
        self.assertTrue(out.endswith("next: 1\n"), out)

    def test_318_the_line_after_a_hidden_state_is_a_normal_line(self):
        out = filt("%s:\n  %s\n%s=%s\n" % (K, V, K, V))
        self.assertEqual(out, "%s: ***\n%s=***\n" % (K, K))

    def test_318_a_held_key_line_is_followed_by_a_normal_line(self):
        out = filt("%s:\n%s=%s\n" % (K, K, V))
        self.assertEqual(out, "%s:\n%s=***\n" % (K, K))

    def test_318_two_empty_keys_in_a_row(self):
        out = filt("%s:\n%s:\n  %s\nnext: 1\n" % (K, K, V))
        self.assertEqual(out, "%s:\n%s: ***\nnext: 1\n" % (K, K))


class DocsTest(unittest.TestCase):
    def test_311_story_20_the_residual_risk_list_no_longer_names_the_closed_sequence_form(self):
        with open(os.path.join(HERE, "redact_post.py"), encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn("a YAML sequence under a matched", text)
        self.assertNotIn("a JSON value on the line after", text)  # ticket 314 closed this form


class SeamAgreementTest(unittest.TestCase):
    """311 story 17: for LF text the two seams give the same output."""

    def test_311_story_17_both_seams_agree_on_the_empty_key_forms(self):
        for text in (
            "%s:\n  %s\nnext: 1\n" % (K, V),
            "%s:\n- %s\nnext: 1\n" % (K, V),
            "%s:\n  a:\n    b: %s\nnext: 1\n" % (K, V),
            "'%s':\n  %s\nnext: 1\n" % (K, V),
            '"%s":\n  "a": %s\nnext: 1\n' % (K, V),
            "%s:\n\nnext: 1\n" % K,
            "%s:\nnext: 1\n" % K,
            "%s: !!str\n  %s\n" % (K, V),
            "%s: !!str\nnext: 1\n" % K,
            "%s: !!str \nnext: 1\n" % K,
            "- %s:\n    %s\n  sibling: 1\n" % (K, V),
            "%s:\n  %s\nMIIEbody\n%s\nnext: 1\n" % (K, BEGIN, END),
            "%s:\n  %s\nMIIEbody\n" % (K, BEGIN),
            "a: %s %s:\n%s%s\nb: 1\n" % (AWS, K, " " * 40, V),
            "%s: abc %s:\n  keep\n" % (K, K),
            "%s:\n" % K,
            "x: 1\n%s:" % K,
            '"%s":\n\n' % K,
            "%s x %s %s:\n      keep\nnext: 1\n" % (BEGIN, END, K),
        ):
            with self.subTest(text=text):
                self.assertEqual(filt(text), redact(text))


if __name__ == "__main__":
    unittest.main()
