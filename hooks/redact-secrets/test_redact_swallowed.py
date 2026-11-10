"""Tests of ticket 381 (ticket spec 403, general spec 367 leak 1): a secret key that an earlier value swallows.

When a keyed value is masked to the line end, the keyed rules scan the masked text again (the rescan rule). The key
at which the rescan opens a later-line state is the swallowed key, and its state runs with its own column.
Seam 1 is `redact(text)` through the test kit. Seam 2 is the Monitor filter script on stdin.
"Story" numbers (T1 to T9) in a test name are the local stories of ticket spec 403. Fixtures are built from parts,
so this file holds no secret-shaped text of its own. Placeholders in the comments: SK a secret key, V a secret value.
"""
import unittest

from redact_testkit import filt, read_module, redact

K = "pass" + "word"  # a matched key name
V = "hunter2"
V2 = "tail2"
DEEP = " " * 40  # deeper than every key column in these tests


class SwallowedCases:
    """Cases that both seams must satisfy. A subclass defines `seam`."""

    def seam(self, text):
        raise NotImplementedError

    def check(self, text, expected):
        out = self.seam(text)
        self.assertEqual(out, expected)
        self.assertNotIn(V, out)
        self.assertNotIn(V2, out)

    # T1: a next-line JSON string after a swallowed plain double-quoted key
    def test_381_r1_t1_a_json_first_key_swallows_a_key_whose_next_line_string_is_masked(self):
        self.check('"%s": abc "%s":\n"%s"\n' % (K, K, V), '"%s": ***\n"***"\n' % K)

    def test_381_r1_t1_a_yaml_first_key_swallows_a_key_whose_next_line_string_is_masked(self):
        self.check('%s: abc "%s":\n"%s"\n' % (K, K, V), '%s: ***\n"***"\n' % K)

    def test_381_r1_t1_an_env_first_key_swallows_a_key_whose_next_line_string_is_masked(self):
        self.check('%s=abc "%s":\n"%s"\n' % (K, K, V), '%s=***\n"***"\n' % K)

    def test_381_r1_t1_node_properties_after_the_swallowed_key_are_hidden_with_the_key_line(self):
        self.check('"%s": abc "%s": !!str\n"%s"\n' % (K, K, V), '"%s": ***\n"***"\n' % K)

    # T2: a next-line object or array
    def test_381_r1_t2_a_next_line_object_is_masked_as_one_value(self):
        self.check('"%s": abc "%s":\n  {"a": "%s"}\nnext: 1\n' % (K, K, V), '"%s": ***\n  "***"\nnext: 1\n' % K)

    def test_381_r1_t2_a_next_line_array_is_masked_as_one_value(self):
        self.check('"%s": abc "%s":\n  ["%s", "%s"]\nnext: 1\n' % (K, K, V, V2), '"%s": ***\n  "***"\nnext: 1\n' % K)

    def test_381_r1_t2_a_next_line_object_that_spans_lines_is_masked_to_its_close(self):
        self.check(
            '"%s": abc "%s":\n  {\n    "a": "%s"\n  }\nnext: 1\n' % (K, K, V), '"%s": ***\n  "***"\nnext: 1\n' % K
        )

    # T3 and T4: the empty-key rule with the key column of the swallowed key
    def test_381_r3_t3_a_line_deeper_than_the_swallowed_key_is_hidden(self):
        self.check('"%s": abc "%s":\n%sa: %s\nnext: 1\n' % (K, K, " " * 20, V), '"%s": ***\nnext: 1\n' % K)

    def test_381_r3_t3_a_line_not_deeper_than_the_swallowed_key_stays(self):
        # the swallowed key is at column 16, so a line indented by 2 is not hidden
        text = '"%s": abc "%s":\n  keep\nnext: 1\n' % (K, K)
        self.assertEqual(self.seam(text), '"%s": ***\n  keep\nnext: 1\n' % K)

    def test_381_r3_t4_a_single_quoted_swallowed_key_takes_the_empty_key_rule_only(self):
        self.check("%s: abc '%s':\n%sa: %s\nnext: 1\n" % (K, K, " " * 20, V), "%s: ***\nnext: 1\n" % K)

    def test_381_r3_t4_a_single_quoted_swallowed_key_does_not_mask_a_next_line_string(self):
        # no next-line JSON value rule for a single-quoted key: the line is at column 0, not deeper than the key
        text = "%s: abc '%s':\n\"%s\"\nnext: 1\n" % (K, K, V)
        self.assertEqual(self.seam(text), "%s: ***\n\"%s\"\nnext: 1\n" % (K, V))

    def test_381_r3_t4_a_counting_yaml_swallowed_key_takes_the_empty_key_rule_only(self):
        # the second key is at a flow-mapping position, so it counts
        self.check("%s: abc {a: 1, %s:\n%skeep %s\nnext: 1\n" % (K, K, " " * 30, V), "%s: ***\nnext: 1\n" % K)

    # T5: a block scalar header and an open object after the swallowed key
    def test_381_r5_t5_a_block_header_after_a_swallowed_key_hides_the_deeper_lines(self):
        self.check('"%s": abc "%s": |\n%s%s\nnext: 1\n' % (K, K, DEEP, V), '"%s": ***\nnext: 1\n' % K)

    def test_381_r5_t5_a_block_line_not_deeper_than_the_swallowed_key_stays(self):
        text = '"%s": abc "%s": |\n  keep\nnext: 1\n' % (K, K)
        self.assertEqual(self.seam(text), '"%s": ***\n  keep\nnext: 1\n' % K)

    def test_381_r5_t5_a_block_header_with_node_properties_after_a_swallowed_key(self):
        self.check('"%s": abc "%s": !!str |\n%s%s\nnext: 1\n' % (K, K, DEEP, V), '"%s": ***\nnext: 1\n' % K)

    def test_381_r5_t5_an_open_object_after_a_swallowed_key_hides_the_lines_to_its_close(self):
        self.check('"%s": abc "%s": {\n  "a": "%s"\n}\nnext: 1\n' % (K, K, V), '"%s": ***\nnext: 1\n' % K)

    def test_381_r5_t5_an_open_array_after_a_swallowed_key_hides_the_lines_to_its_close(self):
        self.check('"%s": abc "%s": [\n  "%s"\n]\nnext: 1\n' % (K, K, V), '"%s": ***\nnext: 1\n' % K)

    # T6: no state opens where the rescan opens none
    def test_381_r4_t6_an_unquoted_yaml_key_in_a_masked_value_opens_no_state(self):
        text = "%s: abc %s:\n    keep\n" % (K, K)
        self.assertEqual(self.seam(text), "%s: ***\n    keep\n" % K)

    def test_381_r4_t6_an_unquoted_yaml_key_in_a_masked_value_hides_no_deeper_line(self):
        text = "%s: abc %s:\n%skeep\n" % (K, K, " " * 20)
        self.assertEqual(self.seam(text), "%s: ***\n%skeep\n" % (K, " " * 20))

    def test_381_r4_t6_an_env_key_in_a_masked_value_opens_no_state(self):
        text = "%s: abc %s=\n  keep\n" % (K, K)
        self.assertEqual(self.seam(text), "%s: ***\n  keep\n" % K)

    def test_381_r5_t6_an_env_key_in_a_masked_value_hides_no_deeper_line(self):
        text = "%s: abc %s=\n%skeep\n" % (K, K, " " * 20)
        self.assertEqual(self.seam(text), "%s: ***\n%skeep\n" % (K, " " * 20))

    def test_381_r4_t6_a_value_masked_to_the_line_end_that_holds_no_secret_key_opens_no_state(self):
        text = '"%s": abc "%s": x "n":\n  keep\n' % (K, K)
        self.assertEqual(self.seam(text), '"%s": ***\n  keep\n' % K)

    def test_381_r6_t6_the_rescan_goes_on_into_a_value_that_it_masks_to_the_line_end(self):
        self.check('"%s": abc "%s": x "%s":\n"%s"\n' % (K, K, K, V), '"%s": ***\n"***"\n' % K)

    # T7: values that do not reach the line end keep today's behavior (the base)
    def test_381_r7_t7_a_closed_string_value_keeps_the_scan_going_after_it(self):
        self.check('"%s": "abc" "%s":\n"%s"\n' % (K, K, V), '"%s": "***" "%s":\n"***"\n' % (K, K))

    def test_381_r7_t7_a_one_word_json_value_keeps_the_base_output(self):
        text = '"%s": abc"%s":\n"%s"\n' % (K, K, V)
        self.assertEqual(self.seam(text), '"%s": "***"\n"%s"\n' % (K, V))

    # T7: the end of the input
    def test_381_r8_t7_a_swallowed_key_at_the_end_of_the_input_adds_no_mask(self):
        self.assertEqual(self.seam('"%s": abc "%s":\n' % (K, K)), '"%s": ***\n' % K)

    def test_381_r8_t7_a_swallowed_key_as_the_last_line_with_no_line_ending(self):
        self.assertEqual(self.seam('"%s": abc "%s":' % (K, K)), '"%s": ***' % K)


class RulesSeamTest(SwallowedCases, unittest.TestCase):
    def seam(self, text):
        return redact(text)

    def test_381_r5_t5_an_open_object_with_no_closing_bracket_hides_the_rest_of_the_input(self):
        out = redact('"%s": abc "%s": {\n  "a": "%s"\n' % (K, K, V))
        self.assertEqual(out, '"%s": ***' % K)

    def test_381_r9_t8_a_swallowed_key_in_a_rest_after_a_closed_object(self):
        # the object `{` and `}` is empty, so the value guard keeps it; the swallowed key still masks its next line
        out = redact('"%s": {\n} "%s": abc "%s":\n"%s"\n' % (K, K, K, V))
        self.assertEqual(out, '"%s": {\n} "%s": ***\n"***"\n' % (K, K))

    def test_381_r9_t8_a_swallowed_key_in_a_rest_after_an_object_with_content(self):
        out = redact('"%s": {\n"a": 1\n} "%s": abc "%s":\n"%s"\n' % (K, K, K, V))
        self.assertEqual(out, '"%s": "***" "%s": ***\n"***"\n' % (K, K))


class FilterSeamTest(SwallowedCases, unittest.TestCase):
    def seam(self, text):
        return filt(text)

    def test_381_r5_t5_an_open_object_with_no_closing_bracket_hides_the_rest_of_the_input(self):
        out = filt('"%s": abc "%s": {\n  "a": "%s"\n' % (K, K, V))
        self.assertEqual(out, '"%s": ***\n' % K)

    def test_381_r9_t8_a_swallowed_key_in_a_rest_after_a_closed_object(self):
        # the key is in the rest ` "SK": abc "SK":` of the closing line: a normal line, its own line in the filter
        out = filt('"%s": {\n} "%s": abc "%s":\n"%s"\n' % (K, K, K, V))
        self.assertEqual(out, '"%s": "***"\n "%s": ***\n"***"\n' % (K, K))

    def test_381_r9_t8_a_swallowed_key_in_a_rest_after_an_object_with_content(self):
        out = filt('"%s": {\n"a": 1\n} "%s": abc "%s":\n"%s"\n' % (K, K, K, V))
        self.assertEqual(out, '"%s": "***"\n "%s": ***\n"***"\n' % (K, K))

    def test_381_r9_t8_the_key_column_of_a_swallowed_key_in_a_rest_is_measured_on_the_rest_only(self):
        # the swallowed key is at column 26 in the closing line and at column 17 in the rest: a line indented by 20
        # stays in redact(text) and is hidden by the filter (fail-closed, owner decision 5)
        text = '"%s": {\n"a": 1\n{"z": 1}} "%s": abc "%s":\n%skeep\nnext: 1\n' % (K, K, K, " " * 20)
        self.assertEqual(redact(text), '"%s": "***" "%s": ***\n%skeep\nnext: 1\n' % (K, K, " " * 20))
        self.assertEqual(filt(text), '"%s": "***"\n "%s": ***\nnext: 1\n' % (K, K))


class SeamAgreementTest(unittest.TestCase):
    """For LF text the two seams give the same output on a swallowed key (T1 to T7)."""

    def test_381_both_seams_agree_on_the_swallowed_key_forms(self):
        for text in (
            '"%s": abc "%s":\n"%s"\n' % (K, K, V),
            '%s: abc "%s":\n"%s"\n' % (K, K, V),
            '%s=abc "%s":\n"%s"\n' % (K, K, V),
            '"%s": abc "%s":\n  {"a": "%s"}\nnext: 1\n' % (K, K, V),
            '"%s": abc "%s":\n  {\n    "a": "%s"\n  }\nnext: 1\n' % (K, K, V),
            '"%s": abc "%s":\n%sa: %s\nnext: 1\n' % (K, K, " " * 20, V),
            '"%s": abc "%s":\n  keep\nnext: 1\n' % (K, K),
            "%s: abc '%s':\n%sa: %s\nnext: 1\n" % (K, K, " " * 20, V),
            "%s: abc {a: 1, %s:\n%skeep\nnext: 1\n" % (K, K, " " * 30),
            '"%s": abc "%s": |\n%s%s\nnext: 1\n' % (K, K, DEEP, V),
            '"%s": abc "%s": |\n  keep\nnext: 1\n' % (K, K),
            '"%s": abc "%s": {\n  "a": "%s"\n}\nnext: 1\n' % (K, K, V),
            "%s: abc %s:\n    keep\n" % (K, K),
            "%s: abc %s=\n  keep\n" % (K, K),
            '"%s": abc "%s": x "n":\n  keep\n' % (K, K),
            '"%s": abc "%s": x "%s":\n"%s"\n' % (K, K, K, V),
            '"%s": "abc" "%s":\n"%s"\n' % (K, K, V),
            '"%s": abc"%s":\n"%s"\n' % (K, K, V),
            '"%s": abc "%s":\n' % (K, K),
            '"%s": abc "%s":' % (K, K),
        ):
            with self.subTest(text=text):
                self.assertEqual(filt(text), redact(text))


class SourceAndDocsTest(unittest.TestCase):
    def read(self, name):
        return read_module(name)

    def test_381_r10_the_filter_no_longer_defines_key_is_live(self):
        self.assertTrue("key_is_live" not in self.read("redact_filter.py"))

    def test_381_r10_the_filter_calls_the_shared_rules_function(self):
        self.assertTrue("redact_rules.later_line_state(" in self.read("redact_filter.py"))

    def test_381_r11_the_rules_docstring_names_the_rescan_rule(self):
        doc = " ".join(self.read("redact_rules.py").split('"""')[1].split())
        self.assertTrue("The rescan rule (spec 367, ticket 381)" in doc)
        self.assertTrue("value swallows (see the rescan rule below) takes this rule too" in doc)
        self.assertTrue("takes this rule too (the rescan rule below)" in doc)

    def test_381_r11_the_filter_docstring_bullets_name_the_swallowed_key(self):
        doc = self.read("redact_filter.py").split('"""')[1]
        for bullet in ("- A YAML block scalar under a matched key", "- A matched key with an empty value",
                       "- A plain double-quoted matched key with an empty value"):
            start = doc.index(bullet)
            end = doc.find("\n- ", start + 1)
            self.assertTrue("swallowed key" in doc[start : end if end >= 0 else len(doc)], bullet)

    def test_381_r11_the_residual_risk_list_has_the_bullet_of_the_accepted_costs(self):
        text = self.read("redact_post.py")
        self.assertTrue("swallows (the rescan rule" in text)
        self.assertTrue("By the position rule, an unquoted YAML key in a masked value" in text)
        self.assertTrue("The key\n  column of a swallowed key is its column in its line" in text)

    def test_381_r11_the_new_residual_risk_bullet_does_not_repeat_the_rest_only_wording(self):
        text = self.read("redact_post.py")
        self.assertEqual(text.count("column of the rest only"), 1)


if __name__ == "__main__":
    unittest.main()
