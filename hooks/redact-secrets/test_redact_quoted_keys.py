"""Tests of ticket 312 (spec 316): quoted keys and node properties on one line, in both seams.

Seam 1 is `redact(text)` through the test kit. Seam 2 is the Monitor filter script on stdin.
"Shape" and "story" numbers in a test name refer to the general spec 311 (prefix 311), except where the
name says "316 story". Fixtures are built from parts, so this file holds no secret-shaped text of its own.
"""
import unittest

from redact_testkit import filt, redact

KEY = "pass" + "word"  # a matched key name
V = "hunter2"
V2 = "tail2"


class QuotedKeyCases:
    """Cases that both seams must satisfy. A subclass defines `seam`."""

    def seam(self, text):
        raise NotImplementedError

    def check(self, text, expected):
        out = self.seam(text)
        self.assertEqual(out, expected)
        if expected != text:
            self.assertNotIn(V, out)
            self.assertNotIn(V2, out)

    # shape 1: a single-quoted key with every same-line YAML value form
    def test_311_shape_1_single_quoted_key_plain_value(self):
        self.check("'%s': %s\n" % (KEY, V), "'%s': ***\n" % KEY)

    def test_311_shape_1_single_quoted_key_double_quoted_value(self):
        self.check("'%s': \"%s\"\n" % (KEY, V), "'%s': \"***\"\n" % KEY)

    def test_311_shape_1_single_quoted_key_single_quoted_value(self):
        self.check("'%s': '%s' # note\n" % (KEY, V), "'%s': '***' # note\n" % KEY)

    def test_311_shape_1_single_quoted_key_flow_value_is_masked_to_the_end_of_the_line(self):
        self.check("'%s': {a: %s, b: 1}\nnext: 1\n" % (KEY, V), "'%s': ***\nnext: 1\n" % KEY)
        self.check("'%s': [%s, %s]\n" % (KEY, V, V2), "'%s': ***\n" % KEY)

    def test_311_shape_1_single_quoted_key_value_guard_keeps_a_harmless_value(self):
        for value in ("42", "true", "null"):
            with self.subTest(value=value):
                text = "'%s': %s\n" % (KEY, value)
                self.check(text, text)

    def test_311_shape_1_single_quoted_key_that_is_not_matched_is_kept(self):
        text = "'other': %s\n" % V
        self.assertEqual(self.seam(text), text)

    def test_311_shape_1_single_quoted_key_in_a_list_item(self):
        self.check("- '%s': %s\n" % (KEY, V), "- '%s': ***\n" % KEY)

    def test_311_shape_1_a_colon_with_no_space_is_not_a_single_quoted_key(self):
        text = "'%s':%s\n" % (KEY, V)
        self.assertEqual(self.seam(text), text)

    # shape 4c: a block scalar with a quoted key
    def test_311_shape_4c_single_quoted_key_block_scalar(self):
        self.check("'%s': |\n  line1 %s\n\n  line2 %s\nnext: 1\n" % (KEY, V, V2), "'%s': ***\nnext: 1\n" % KEY)

    def test_311_shape_4c_double_quoted_key_block_scalar(self):
        self.check('"%s": |\n  line1 %s\n\n  line2 %s\nnext: 1\n' % (KEY, V, V2), '"%s": ***\nnext: 1\n' % KEY)

    def test_311_shape_4c_double_quoted_key_folded_scalar_with_modifier(self):
        self.check('"%s": >-\n  line1 %s\nnext: 1\n' % (KEY, V), '"%s": ***\nnext: 1\n' % KEY)

    def test_311_shape_4c_quoted_key_in_a_list_item_uses_the_column_of_the_quote(self):
        self.check("- '%s': |\n    a %s\n  sibling: 1\n" % (KEY, V), "- '%s': ***\n  sibling: 1\n" % KEY)

    def test_311_shape_4c_block_ends_at_a_line_back_at_the_key_indent(self):
        self.check("  '%s': |\n    a %s\n  b: 1\n" % (KEY, V), "  '%s': ***\n  b: 1\n" % KEY)

    def test_311_shape_4c_block_that_ends_the_input(self):
        out = self.seam("'%s': |\n  a %s" % (KEY, V))
        self.assertNotIn(V, out)
        self.assertTrue(out.startswith("'%s': ***" % KEY), out)

    # shape 4c: node properties before the block scalar indicator (story 12)
    def test_311_story_12_tag_alone_before_a_block_scalar(self):
        for header in ("!!str |", "!x |", "!<tag:y> |", "! |"):
            with self.subTest(header=header):
                self.check("%s: %s\n  line %s\nnext: 1\n" % (KEY, header, V), "%s: ***\nnext: 1\n" % KEY)

    def test_311_story_12_anchor_alone_before_a_block_scalar(self):
        self.check("%s: &a |\n  line %s\nnext: 1\n" % (KEY, V), "%s: ***\nnext: 1\n" % KEY)

    def test_311_story_12_tag_then_anchor_before_a_block_scalar(self):
        self.check("%s: !!str &a |\n  line %s\nnext: 1\n" % (KEY, V), "%s: ***\nnext: 1\n" % KEY)

    def test_311_story_12_anchor_then_tag_before_a_block_scalar(self):
        self.check("%s: &a !!str >-\n  line %s\nnext: 1\n" % (KEY, V), "%s: ***\nnext: 1\n" % KEY)

    def test_311_story_12_properties_after_a_single_quoted_key(self):
        self.check("'%s': !!str |\n  line %s\nnext: 1\n" % (KEY, V), "'%s': ***\nnext: 1\n" % KEY)
        self.check("'%s': &a |\n  line %s\nnext: 1\n" % (KEY, V), "'%s': ***\nnext: 1\n" % KEY)

    def test_311_story_12_properties_after_a_double_quoted_key(self):
        self.check('"%s": !!str |\n  line %s\nnext: 1\n' % (KEY, V), '"%s": ***\nnext: 1\n' % KEY)
        self.check('"%s": &a !!str |\n  line %s\nnext: 1\n' % (KEY, V), '"%s": ***\nnext: 1\n' % KEY)

    def test_311_story_12_two_tags_are_masked_as_a_plain_value(self):
        self.assertEqual(self.seam("%s: !a !b |\n" % KEY), "%s: ***\n" % KEY)
        self.assertEqual(self.seam("'%s': !a !b |\n" % KEY), "'%s': ***\n" % KEY)
        self.assertEqual(self.seam('"%s": !a !b |\n' % KEY), '"%s": ***\n' % KEY)

    def test_311_story_12_two_anchors_are_masked_as_a_plain_value(self):
        self.assertEqual(self.seam("%s: &a &b |\n" % KEY), "%s: ***\n" % KEY)
        self.assertEqual(self.seam('"%s": &a &b |\n' % KEY), '"%s": ***\n' % KEY)

    def test_311_story_12_two_tags_or_two_anchors_open_no_block(self):
        # as today: the header is a plain value, so the indented line below it is a normal line
        self.assertEqual(self.seam("%s: !a !b |\n  keep me\n" % KEY), "%s: ***\n  keep me\n" % KEY)
        self.assertEqual(self.seam("%s: &a &b |\n  keep me\n" % KEY), "%s: ***\n  keep me\n" % KEY)

    def test_311_story_14_an_alias_is_masked_as_today(self):
        self.assertEqual(self.seam("%s: *x\n" % KEY), "%s: ***\n" % KEY)
        self.assertEqual(self.seam("'%s': *x\n" % KEY), "'%s': ***\n" % KEY)

    def test_311_story_14_a_quoted_value_after_properties_is_masked_to_the_end_of_the_line(self):
        self.assertEqual(self.seam('%s: !!str "%s" tail\n' % (KEY, V)), "%s: ***\n" % KEY)

    def test_316_an_env_pair_with_a_block_indicator_opens_no_block(self):
        out = self.seam("%s=|\n  keep me\n" % KEY)
        self.assertEqual(out, "%s=***\n  keep me\n" % KEY)

    def test_311_shape_4c_double_quoted_key_with_no_space_before_the_indicator(self):
        out = self.seam('"%s":|\n  line %s\nnext: 1\n' % (KEY, V))
        self.assertNotIn(V, out)
        self.assertTrue(out.endswith("next: 1\n"), out)

    # story 16: an unquoted value of more than one word after a double-quoted key
    def test_311_story_16_two_words_after_a_double_quoted_key(self):
        self.check('"%s": %s %s\n' % (KEY, V, V2), '"%s": ***\n' % KEY)

    def test_311_story_16_a_number_then_a_word_after_a_double_quoted_key(self):
        self.check('"%s": 42 %s\n' % (KEY, V2), '"%s": ***\n' % KEY)

    def test_311_story_16_the_mask_reaches_the_end_of_the_line_only(self):
        self.check('{"%s": %s %s, "x": 1}\nnext: 1\n' % (KEY, V, V2), '{"%s": ***\nnext: 1\n' % KEY)

    def test_316_story_13_one_bare_word_keeps_the_json_mask(self):
        self.check('{"%s": %s, "x": 1}\n' % (KEY, V), '{"%s": "***", "x": 1}\n' % KEY)
        self.check('"%s": %s\r\n' % (KEY, V), '"%s": "***"\r\n' % KEY)
        self.check('"%s": %s }\n' % (KEY, V), '"%s": "***" }\n' % KEY)

    def test_316_story_14_json_values_after_a_double_quoted_key_keep_their_output(self):
        self.check('{"%s": "%s"}\n' % (KEY, V), '{"%s": "***"}\n' % KEY)
        for text in ('{"%s": 42, "x": 1}\n' % KEY, '"%s": true \n' % KEY, '{"%s": null}\n' % KEY):
            with self.subTest(text=text):
                self.assertEqual(self.seam(text), text)


class RulesSeamTest(QuotedKeyCases, unittest.TestCase):
    def seam(self, text):
        return redact(text)


class FilterSeamTest(QuotedKeyCases, unittest.TestCase):
    def seam(self, text):
        return filt(text)

    def test_316_a_crlf_block_scalar_with_a_quoted_key_keeps_the_endings(self):
        text = "'%s': !!str |\r\n  a %s\r\nnext: 1\r\n" % (KEY, V)
        self.assertEqual(filt(text), "'%s': ***\r\nnext: 1\r\n" % KEY)

    def test_316_the_next_line_after_a_block_is_a_normal_line(self):
        text = "'%s': |\n  a\n%s=%s\n" % (KEY, KEY, V)
        self.assertEqual(filt(text), "'%s': ***\n%s=***\n" % (KEY, KEY))


class SeamAgreementTest(unittest.TestCase):
    """316 story 16 and 311 story 17: for LF text the two seams give the same output."""

    def test_311_story_17_both_seams_agree_on_every_new_header(self):
        headers = (
            "%s: !!str |", "%s: &a |", "%s: !!str &a |", "%s: &a !!str |",
            "'%s': |", '"%s": |', "'%s': !!str |", '"%s": &a |', "%s: !a !b |",
        )
        for header in headers:
            with self.subTest(header=header):
                text = (header % KEY) + "\n  line %s\n\nnext: 1\n" % V
                self.assertEqual(filt(text), redact(text))

    def test_311_story_17_both_seams_agree_on_the_one_line_forms(self):
        for text in (
            "'%s': %s\n" % (KEY, V), '"%s": %s %s\n' % (KEY, V, V2), '"%s": 42 %s\n' % (KEY, V2),
            "'%s': {a: %s}\n" % (KEY, V), "%s: *x\n" % KEY,
        ):
            with self.subTest(text=text):
                self.assertEqual(filt(text), redact(text))


if __name__ == "__main__":
    unittest.main()
