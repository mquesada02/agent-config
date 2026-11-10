"""Tests of ticket 348 (ticket spec 351, general spec 334): the empty-key rule and the block scalar rule follow the
position rule. They apply to an unquoted YAML key only where the key counts (line start position or flow-mapping
position), in `redact(text)` and in the Monitor filter, also for every rest of a line.

Seam 1 is `redact(text)` through the test kit. Seam 2 is the Monitor filter script on stdin. One cases mixin is run
by a rules-seam class and a filter-seam class. Story numbers refer to the general spec 334 unless a test says
"list" (a story of the ticket spec 351). In the fixtures `@K` is a matched key name, `@NK` a prose name that holds
a key word, `@V` a secret value and `@P` a prose value; `@B` and `@E` are the PEM markers. The names are joined from
parts, so this file holds no secret-shaped text of its own. The docs checks read the hook files as text: they are
the one exception to "tests go through a public seam".
"""
import unittest

from redact_testkit import filt, lines, normalized, read_module, redact

K = "pass" + "word"
NK = "redact-" + "sec" + "rets"
V = "hunter2"
P = "keepme"
BEGIN = "-----BEGIN PRIVATE " + "KEY-----"
END = "-----END PRIVATE " + "KEY-----"
DEEP = " " * 60  # deeper than the key column of every fixture, a tool prefix included


def T(text):
    """A fixture text with its @-names replaced."""
    for name, value in (("@NK", NK), ("@K", K), ("@V", V), ("@P", P), ("@B", BEGIN), ("@E", END)):
        text = text.replace(name, value)
    return text


def body_lines(count):
    return ["MIIE%03d" % number for number in range(count)]


# Every prefix after which a key counts: tool prefixes, comment marker, list markers, flow-mapping positions and the
# true line start (spaces and tabs).
PREFIXES = [
    "",
    "  ",
    "\t",
    "config.yml:",
    "config.yml:12:",
    "    12\t",
    "+",
    "-",
    " ",
    "# ",
    "#",
    "- ",
    "- - ",
    "{",
    "{a: 1, ",
    "config.yml:12:+  # - ",
]

# Inputs for the seams-agree test (story 21): none of them depends on the key column in a rest.
AGREE = [
    lines("The @NK:", DEEP + "@P"),
    lines("see @NK: |", DEEP + "@P"),
    lines("@K:", "  @V"),
    lines("@K: |", "  @V"),
    lines("@B", "MIIE", "@E The @NK:", DEEP + "@P"),
    lines("{a: 1, c: @B", "MIIE", "@E, @K:", DEEP + "@V"),
    lines("{a: 1, c: @B", "MIIE", "@E, @K: |", DEEP + "@V"),
    lines("@B", "MIIE", "@E see @NK: |", DEEP + "@P"),
    lines('"@K": {', '"a": 1', "}, @NK:", DEEP + "@P"),
    lines('"@K": {', '"a": 1', '{"z": 1}}, @K:', DEEP + "@V"),
    lines('"@K":', '{"a": 1}, @K:', DEEP + "@V"),
    lines('"@K":', '"x", @NK:', DEEP + "@P"),
    lines("{a: 1, c: @B", *body_lines(250), "@E, @K:", DEEP + "@V"),
    lines("@B", *body_lines(250), "@E see @NK: |", DEEP + "@P"),
    lines("{a: 1, c: @B x", "MIIE", "@E, @K: |", DEEP + "@V"),
]


class StateCases:
    """Cases that both seams must satisfy with the same text. A subclass defines `seam`."""

    def seam(self, text):
        raise NotImplementedError

    def kept(self, text):
        text = T(text)
        self.assertEqual(self.seam(text), text)

    def hidden(self, text):
        text = T(text)
        out = self.seam(text)
        self.assertNotIn(V, out)
        self.assertIn("***", out)
        return out

    # story 6: prose opens no state
    def test_348_story_6_a_line_that_ends_in_a_prose_key_hides_nothing(self):
        self.kept(lines("The @NK:", DEEP + "@P", "", "- item"))

    def test_348_story_6_a_prose_key_with_a_block_header_opens_no_block(self):
        self.kept(lines("see @NK: |", DEEP + "@P", "next: 1"))

    def test_348_story_6_a_prose_key_with_a_folded_block_header_opens_no_block(self):
        self.kept(lines("see @NK: >", DEEP + "@P", "next: 1"))

    def test_348_story_6_a_prose_key_after_a_tab_after_a_tool_prefix_hides_nothing(self):
        self.kept(lines("title:\t@NK:", DEEP + "@P"))

    def test_348_story_6_a_prose_key_with_node_properties_hides_nothing(self):
        self.kept(lines("see @NK: !!str", DEEP + "@P"))

    # story 17: a key that counts keeps both rules
    def test_348_story_17_empty_key_at_the_line_start_hides_the_lines_after_it(self):
        self.assertEqual(self.seam(T(lines("@K:", "  @V"))), T(lines("@K: ***")))

    def test_348_story_17_block_scalar_at_the_line_start_is_one_mask(self):
        self.assertEqual(self.seam(T(lines("@K: |", "  @V"))), T(lines("@K: ***")))

    def test_348_story_17_empty_key_after_each_prefix_and_flow_mapping_position(self):
        for prefix in PREFIXES:
            out = self.hidden(lines(prefix + "@K:", DEEP + "@V", "next: 1"))
            self.assertTrue(out.endswith("next: 1\n"), (prefix, out))

    def test_348_story_17_block_scalar_after_each_prefix_and_flow_mapping_position(self):
        for prefix in PREFIXES:
            out = self.hidden(lines(prefix + "@K: |", DEEP + "@V", "next: 1"))
            self.assertTrue(out.endswith("next: 1\n"), (prefix, out))

    def test_348_story_17_two_space_value_line_after_a_prefix_is_not_hidden_as_today(self):
        out = self.seam(T(lines("config.yml:12:@K:", "  @P")))
        self.assertIn(P, out)

    # story 18: the other key forms keep their behavior, with no position check
    def test_348_story_18_double_quoted_empty_key_in_mid_line_prose_still_hides(self):
        self.hidden(lines('use "@K":', DEEP + "@V"))

    def test_348_story_18_single_quoted_empty_key_in_mid_line_prose_still_hides(self):
        self.hidden(lines("use '@K':", DEEP + "@V"))

    def test_348_story_18_double_quoted_block_header_in_mid_line_prose_still_opens_a_block(self):
        self.hidden(lines('use "@K": |', DEEP + "@V"))

    def test_348_story_18_single_quoted_block_header_in_mid_line_prose_still_opens_a_block(self):
        self.hidden(lines("use '@K': |", DEEP + "@V"))

    # story 20: a key in a rest of a line counts only where it counts in the full line
    def test_348_story_20_pem_rest_prose_key_hides_nothing(self):
        out = self.seam(T(lines("@B", "MIIE", "@E The @NK:", DEEP + "@P")))
        self.assertIn(P, out)

    def test_348_story_20_pem_rest_prose_block_header_opens_no_block(self):
        out = self.seam(T(lines("@B", "MIIE", "@E see @NK: |", DEEP + "@P")))
        self.assertIn(P, out)

    def test_348_story_20_pem_rest_in_a_flow_mapping_hides_the_lines_after_an_empty_key(self):
        self.hidden(lines("{a: 1, c: @B", "MIIE", "@E, @K:", DEEP + "@V"))

    def test_348_story_20_pem_rest_in_a_flow_mapping_opens_a_block(self):
        self.hidden(lines("{a: 1, c: @B", "MIIE", "@E, @K: |", DEEP + "@V"))

    def test_348_story_20_held_key_line_that_is_not_hidden_is_written_as_a_normal_line(self):
        text = lines("{a: 1, c: @B", "MIIE", "@E, @K:", "plain")
        self.assertEqual(self.seam(T(text)), T(lines("{a: 1, c: ***, @K:", "plain")))

    def test_348_story_20_held_key_line_at_the_end_of_the_input_is_written(self):
        text = lines("{a: 1, c: @B", "MIIE", "@E, @K:")
        self.assertEqual(self.seam(T(text)), T(lines("{a: 1, c: ***, @K:")))

    def test_348_story_20_pem_rest_in_a_flow_mapping_past_the_held_line_cap_hides_the_lines(self):
        self.hidden(lines("{a: 1, c: @B", *body_lines(250), "@E, @K:", DEEP + "@V"))

    def test_348_story_20_pem_rest_past_the_held_line_cap_prose_block_header_opens_no_block(self):
        out = self.seam(T(lines("@B", *body_lines(250), "@E see @NK: |", DEEP + "@P")))
        self.assertIn(P, out)

    def test_348_story_20_pem_rest_past_the_held_line_cap_prose_empty_key_hides_nothing(self):
        out = self.seam(T(lines("@B", *body_lines(250), "@E The @NK:", DEEP + "@P")))
        self.assertIn(P, out)

    def test_348_story_20_dropped_json_object_rest_prose_key_hides_nothing(self):
        out = self.seam(T(lines('"@K": {', '"a": 1', "}, @NK:", DEEP + "@P")))
        self.assertIn(P, out)

    def test_348_story_20_dropped_json_object_rest_with_a_brace_hides_the_lines_after_an_empty_key(self):
        self.hidden(lines('"@K": {', '"a": 1', '{"z": 1}}, @K:', DEEP + "@V"))

    def test_348_story_20_dropped_json_object_rest_prose_block_header_opens_no_block(self):
        out = self.seam(T(lines('"@K": {', '"a": 1', "}, see @NK: |", DEEP + "@P")))
        self.assertIn(P, out)

    def test_348_story_20_dropped_json_object_rest_with_a_brace_opens_a_block(self):
        self.hidden(lines('"@K": {', '"a": 1', '{"z": 1}}, @K: |', DEEP + "@V"))

    def test_348_story_20_next_line_json_value_rest_with_a_brace_hides_the_lines_after_an_empty_key(self):
        self.hidden(lines('"@K":', '{"a": 1}, @K:', DEEP + "@V"))

    def test_348_story_20_next_line_json_value_rest_prose_key_hides_nothing(self):
        out = self.seam(T(lines('"@K":', '"x", @NK:', DEEP + "@P")))
        self.assertIn(P, out)

    def test_348_story_20_next_line_json_value_rest_prose_block_header_opens_no_block(self):
        out = self.seam(T(lines('"@K":', '"x", see @NK: |', DEEP + "@P")))
        self.assertIn(P, out)

    def test_348_story_20_block_header_after_a_pem_pair_with_a_brace_is_judged_on_the_masked_line(self):
        # the pair holds a brace before a prose key: the masked line has none, so the key is prose in both seams
        text = lines("x @B {a: 1} @E , @NK: |", DEEP + "@P")
        out = self.seam(T(text))
        self.assertIn(P, out)

    def test_348_story_20_block_header_after_a_pem_pair_in_a_flow_mapping_opens_a_block(self):
        self.hidden(lines("{a: 1, c: @B x @E, @K: |", DEEP + "@V"))


class RulesSeam(StateCases, unittest.TestCase):
    def seam(self, text):
        return redact(text)


class FilterSeam(StateCases, unittest.TestCase):
    def seam(self, text):
        return filt(text)


class SeamsAgree(unittest.TestCase):
    def test_348_story_21_both_seams_agree_on_every_story_input(self):
        # The line breaks of a dropped state differ between the seams (as before), so compare what stays visible.
        for text in map(T, AGREE):
            rules, filtered = redact(text), filt(text)
            self.assertEqual((V in rules, P in rules), (V in filtered, P in filtered), text)
            self.assertNotIn(V, rules, text)

    def test_348_story_21_both_seams_agree_after_each_prefix(self):
        for prefix in PREFIXES:
            for rule in ("@K:", "@K: |"):
                text = T(lines(prefix + rule, DEEP + "@V", "next: 1"))
                self.assertEqual(redact(text), filt(text), text)


class DocsChecks(unittest.TestCase):
    def read(self, name):
        return normalized(read_module(name))

    def test_348_story_22_rules_docstring_says_the_state_rules_follow_the_position_rule(self):
        docstring = self.read("redact_rules.py").split('"""')[1]
        self.assertIn("empty-key rule and the block scalar rule follow the position rule", docstring)

    def test_348_story_22_rules_docstring_no_longer_says_they_still_fire_on_any_key(self):
        docstring = self.read("redact_rules.py").split('"""')[1]
        self.assertNotIn("still fire on any unquoted YAML key", docstring)

    def test_348_story_22_rules_docstring_has_no_ticket_348_remark(self):
        docstring = self.read("redact_rules.py").split('"""')[1]
        self.assertNotIn("ticket 348", docstring)

    def test_348_story_22_filter_docstring_says_the_state_detection_of_a_rest_uses_the_line_prefix(self):
        docstring = self.read("redact_filter.py").split('"""')[1]
        self.assertIn("empty-key and block scalar detection", docstring)

    def test_348_story_23_residual_risk_list_names_the_column_with_a_tool_prefix(self):
        self.assertIn("measure the key column with the prefix", self.read("redact_post.py"))

    def test_348_story_23_false_positive_bullet_keeps_the_phrase_with_a_line_start_example(self):
        text = self.read("redact_post.py")
        self.assertIn("false positive", text)
        self.assertNotIn("see <key>: |", text)

    def test_348_story_23_rest_column_bullet_names_both_rules(self):
        bullets = [bullet for bullet in self.read("redact_post.py").split(" - ") if "column of the rest only" in bullet]
        self.assertEqual(len(bullets), 1)
        self.assertIn("empty-key rule and the block scalar rule", bullets[0])


if __name__ == "__main__":
    unittest.main()
