"""Tests of ticket 347 (ticket spec 349, general spec 334): the same-line masking of an unquoted YAML key follows
the position rule. A key counts only at a line start position (prefix grammar) or at a flow-mapping position.

Seam 1 is `redact(text)` through the test kit. Seam 2 is the Monitor filter script on stdin. One cases mixin is run
by a rules-seam class and a filter-seam class. Story numbers refer to the general spec 334. In the fixtures `@K`
is a matched key name, `@TK` a second one, `@NK` a prose name that holds a key word, `@V` a secret value and `@P`
a prose value; `@B` and `@E` are the PEM markers. The names are joined from parts, so this file holds no
secret-shaped text of its own. The docs checks read the hook files as text: they are the one exception to
"tests do not call helpers".
"""
import os
import unittest

from redact_testkit import HERE, redact, run_filter

K = "pass" + "word"
TK = "to" + "ken"
NK = "redact-" + "sec" + "rets"
V = "hunter2"
P = "keepme"
BEGIN = "-----BEGIN PRIVATE " + "KEY-----"
END = "-----END PRIVATE " + "KEY-----"
AWS = "AK" + "IA" + "IOSFODNN7EXAMPLE"
JWT = "ey" + "Jhbgci.ey" + "Jzdwi.c2ln"
VENDOR = "gh" + "p_abc123DEF456"


def T(text):
    """A fixture text with its @-names replaced."""
    for name, value in (("@NK", NK), ("@TK", TK), ("@K", K), ("@V", V), ("@P", P), ("@B", BEGIN), ("@E", END)):
        text = text.replace(name, value)
    return text


def filt(text):
    """The text that the Monitor filter writes for a text on stdin."""
    result = run_filter(text.encode("utf-8", "surrogateescape"))
    assert result.returncode == 0, result.stderr
    return result.stdout.decode("utf-8", "surrogateescape")


def lines(*parts):
    return "\n".join(parts) + "\n"


def body_lines(count):
    return ["MIIE%03d" % number for number in range(count)]


# Inputs of the behavior stories; the seams-agree test runs every one of them through both seams.
PROSE = [
    "title:\t@NK: hide lines",
    "abc1234 @NK: hide lines",
    "2026-11-04 INFO @NK: retry in 5s",
    "The @NK: we never log it.",
    "Fixed two bugs, @NK: handled",
    'msg: "{", @NK: @P',
    "title:\t@K: @P",
    "+\t@K: @P",
    "config.yml:3:#\t@K: @P",
    "a, @K: @P",
]
MASKED = [
    "@K: @V",
    "  @K: @V",
    "\t@K: @V",
    " \t@K: @V",
    "- @K: @V",
    "- - @K: @V",
    "{@K: @V}",
    "{a: 1, @K: @V}",
    "{a: {b: 1}, @K: @V}",
    '{a: "x}", @K: @V}',
    "{a: 'x}', @K: @V}",
    "don't {a: 1, @K: @V}",
    'echo "{@K: @V"',
    'x "\\\\" {a: 1, @K: @V}',
    "+  @K: @V",
    "-  @K: @V",
    "-@K: @V",
    " @K: @V",
    "    12\t@K: @V",
    "config.yml:12:  @K: @V",
    "config.yml:@K: @V",
    "# @K: @V",
    "#@K: @V",
    "#\t@K: @V",
    "# \t@K: @V",
    "config.yml:12:+  # - @K: @V",
    "title: @K: @V",
    "{ \t@K: @V}",
    "{a: 1,\t@K: @V}",
    'use "@K": "@V"',
    "use @K=@V",
    "use '@K': @V",
]


class ProseCases:
    """Cases that both seams must satisfy with the same text. A subclass defines `seam`."""

    def seam(self, text):
        raise NotImplementedError

    def prose(self, text):
        text = T(text)
        self.assertEqual(self.seam(text), text)

    def masked(self, text):
        text = T(text)
        out = self.seam(text)
        self.assertNotIn(V, out)
        self.assertIn("***", out)
        self.assertTrue(out.startswith(text[: text.index(V)]), "text before the value is kept")

    def exact(self, text, expected):
        self.assertEqual(self.seam(T(text)), T(expected))

    # R1, stories 1 to 5: prose stays whole
    def test_347_story_1_gh_issue_title_line_stays_whole(self):
        self.prose(PROSE[0])

    def test_347_story_2_commit_list_line_stays_whole(self):
        self.prose(PROSE[1])

    def test_347_story_3_log_line_stays_whole(self):
        self.prose(PROSE[2])

    def test_347_story_4_sentence_stays_whole(self):
        self.prose(PROSE[3])

    def test_347_story_5_comma_in_a_sentence_stays_whole(self):
        self.prose(PROSE[4])

    # R2, stories 7 to 16: the prefix grammar
    def test_347_story_7_true_line_start_is_masked(self):
        self.exact("@K: @V", "@K: ***")

    def test_347_story_8_indent_spaces_is_masked(self):
        self.masked("  @K: @V")

    def test_347_story_8_indent_tab_is_masked(self):
        self.masked("\t@K: @V")

    def test_347_story_8_space_then_tab_is_masked(self):
        self.masked(" \t@K: @V")

    def test_347_story_9_list_marker_is_masked(self):
        self.masked("- @K: @V")

    def test_347_story_9_two_list_markers_are_masked(self):
        self.masked("- - @K: @V")

    def test_347_story_11_diff_markers_are_masked(self):
        for text in ("+  @K: @V", "-  @K: @V", "-@K: @V", " @K: @V"):
            self.masked(text)

    def test_347_story_12_line_number_prefix_is_masked(self):
        self.masked("    12\t@K: @V")

    def test_347_story_13_grep_prefix_with_a_line_number_is_masked(self):
        self.masked("config.yml:12:  @K: @V")

    def test_347_story_13_grep_prefix_without_a_line_number_is_masked(self):
        self.masked("config.yml:@K: @V")

    def test_347_story_14_comment_marker_is_masked(self):
        for text in ("# @K: @V", "#@K: @V"):
            self.masked(text)

    def test_347_story_14_comment_marker_with_a_tab_at_the_true_line_start_is_masked(self):
        for text in ("#\t@K: @V", "# \t@K: @V"):
            self.masked(text)

    def test_347_story_14_comment_marker_with_a_tab_after_a_tool_prefix_is_prose(self):
        self.prose("config.yml:3:#\t@K: @P")

    def test_347_story_15_prefixes_combine_in_grammar_order(self):
        self.masked("config.yml:12:+  # - @K: @V")

    def test_347_story_16_tab_after_a_grep_prefix_is_prose(self):
        self.prose("title:\t@K: @P")

    def test_347_story_16_tab_after_a_diff_marker_is_prose(self):
        self.prose("+\t@K: @P")

    def test_347_story_16_space_after_a_grep_prefix_is_masked(self):
        self.masked("title: @K: @V")

    def test_347_prefix_grammar_text_before_the_key_that_is_no_prefix_is_prose(self):
        self.prose("a, @K: @P")

    # R3, story 10: the flow-mapping rule
    def test_347_story_10_key_directly_after_an_open_brace(self):
        self.masked("{@K: @V}")

    def test_347_story_10_key_after_a_comma_in_a_flow_mapping(self):
        self.masked("{a: 1, @K: @V}")

    def test_347_story_10_nested_close_brace_before_the_comma(self):
        self.masked("{a: {b: 1}, @K: @V}")

    def test_347_story_10_close_brace_in_a_double_quoted_string(self):
        self.masked('{a: "x}", @K: @V}')

    def test_347_story_10_close_brace_in_a_single_quoted_string(self):
        self.masked("{a: 'x}', @K: @V}")

    def test_347_story_10_apostrophe_is_a_plain_character(self):
        self.masked("don't {a: 1, @K: @V}")

    def test_347_story_10_open_brace_inside_a_string_counts_directly_before_the_key(self):
        self.masked('echo "{@K: @V"')

    def test_347_story_10_escaped_backslash_closes_the_string_at_the_next_quote(self):
        self.masked('x "\\\\" {a: 1, @K: @V}')

    def test_347_story_10_only_open_brace_is_in_a_string_is_prose(self):
        self.prose('msg: "{", @NK: @P')

    def test_347_story_10_spaces_and_tabs_between_brace_and_key(self):
        self.masked("{ \t@K: @V}")

    def test_347_story_10_spaces_and_tabs_between_comma_and_key(self):
        self.masked("{a: 1,\t@K: @V}")

    def test_347_story_10_comma_after_a_closed_mapping_still_counts_accepted_cost(self):
        out = self.seam(T("{a: 1} done, @NK: @P"))
        self.assertNotIn(P, out)

    # R4: a skipped prose key does not hide a later key
    def test_347_prose_key_then_a_json_key_on_the_same_line(self):
        self.exact('abc @NK: x "@K": "@V"', 'abc @NK: x "@K": "***"')

    def test_347_prose_key_then_a_key_at_a_flow_mapping_position(self):
        self.exact("abc @NK: x {a: 1, @K: @V}", "abc @NK: x {a: 1, @K: ***")

    # R1, story 17: the empty-key rule and the block scalar rule keep today's behavior
    def test_347_story_17_empty_key_at_the_line_start_hides_the_lines_after_it(self):
        self.exact(lines("@K:", "  @V"), lines("@K: ***"))

    def test_347_story_17_block_scalar_at_the_line_start_is_one_mask(self):
        self.exact(lines("@K: |", "  @V"), lines("@K: ***"))

    def test_347_story_17_block_scalar_on_a_prose_position_key_still_fires_until_ticket_348(self):
        self.exact(lines("see @NK: |", "      @V"), lines("see @NK: ***"))

    def test_347_story_17_empty_key_on_a_prose_position_key_still_fires_until_ticket_348(self):
        self.exact(lines("The @NK:", "      @V"), lines("The @NK: ***"))

    # R1, story 18: the other key forms keep their behavior anywhere in a line
    def test_347_story_18_json_key_anywhere_in_a_line(self):
        self.exact('use "@K": "@V"', 'use "@K": "***"')

    def test_347_story_18_env_pair_anywhere_in_a_line(self):
        self.exact("use @K=@V", "use @K=***")

    def test_347_story_18_single_quoted_key_anywhere_in_a_line(self):
        self.exact("use '@K': @V", "use '@K': ***")

    def test_347_story_18_single_quoted_empty_key_anywhere_in_a_line(self):
        out = self.seam(T(lines("abc '@K':", "      @V")))
        self.assertNotIn(V, out)

    # R5, story 19: the shape rules still mask a secret after a prose key
    def test_347_story_19_aws_key_id_after_a_prose_key(self):
        self.exact("The @NK: " + AWS, "The @NK: ***")

    def test_347_story_19_jwt_after_a_prose_key(self):
        self.exact("The @NK: " + JWT, "The @NK: ***")

    def test_347_story_19_url_password_after_a_prose_key(self):
        self.exact("The @NK: https://user:@V@example.com", "The @NK: https://user:***@example.com")

    def test_347_story_19_vendor_token_after_a_prose_key(self):
        self.exact("The @NK: " + VENDOR, "The @NK: ***")

    def test_347_story_19_pem_block_after_a_prose_key(self):
        self.exact(lines("The @NK: @B", "MIIE", "@E"), lines("The @NK: ***"))

    # R6, story 20: a key in a rest counts only where it counts in the full line
    def test_347_story_20_pem_rest_in_a_flow_mapping_is_masked(self):
        self.exact(lines("{a: 1, c: @B", "MIIE", "@E, @K: @V}"), lines("{a: 1, c: ***, @K: ***"))

    def test_347_story_20_pem_rest_is_never_a_line_start(self):
        self.exact(lines("@B", "MIIE", "@E@K: @P"), lines("***@K: @P"))

    def test_347_story_20_two_pem_blocks_keep_the_prefix_of_the_first(self):
        text = lines("{a: 1, c: @B", "MIIE", "@E mid @B", "MIIE", "@E, @K: @V}")
        self.exact(text, lines("{a: 1, c: *** mid ***, @K: ***"))

    def test_347_story_20_pem_rest_in_a_flow_mapping_past_the_held_line_cap(self):
        out = self.seam(T(lines("{a: 1, c: @B", *body_lines(250), "@E, @K: @V}")))
        self.assertNotIn(V, out)

    def test_347_story_20_pem_rest_is_prose_past_the_held_line_cap(self):
        out = self.seam(T(lines("@B", *body_lines(250), "@E@K: @P")))
        self.assertIn(P, out)

    def test_347_story_20_dropped_json_object_rest_with_no_brace_in_the_closing_line_is_prose(self):
        out = self.seam(T(lines('"@K": {', '"a": 1', "}, @NK: @P")))
        self.assertIn(P, out)

    def test_347_story_20_dropped_json_object_rest_with_a_brace_in_the_closing_line_is_masked(self):
        out = self.seam(T(lines('"@K": {', '"a": 1', '{"z": 1}}, @K: @V')))
        self.assertNotIn(V, out)

    def test_347_story_20_next_line_json_value_rest_holding_a_brace_is_masked(self):
        self.exact(lines('"@K":', '{"a": 1}, @K: @V'), lines('"@K":', '"***", @K: ***'))

    def test_347_story_20_next_line_json_value_rest_without_a_brace_is_prose(self):
        self.exact(lines('"@K":', '"x", @NK: @P'), lines('"@K":', '"***", @NK: @P'))

    def test_347_story_20_next_line_json_value_that_stays_is_a_full_line(self):
        self.exact(lines('"@K":', "5, @NK: @P"), lines('"@K":', "5, @NK: @P"))

    def test_347_story_20_held_empty_key_line_in_a_rest_keeps_the_line_prefix(self):
        text = lines("@B", "MIIE", '@E  @TK: "@P" @K:', " " * 40 + "deep")  # deeper than the key in the full line
        self.exact(text, lines('***  @TK: "@P" @K: ***'))

    def test_347_story_20_held_empty_key_line_at_the_end_of_the_input_keeps_the_line_prefix(self):
        text = lines("@B", "MIIE", '@E  @TK: "@P" @K:')
        self.exact(text, lines('***  @TK: "@P" @K:'))

    def test_347_story_20_held_pending_json_key_line_in_a_rest_keeps_the_line_prefix(self):
        text = lines("@B", "MIIE", '@E  @TK: "@P" "@K":', '"x"')
        self.exact(text, lines('***  @TK: "@P" "@K":', '"***"'))


class RulesSeam(ProseCases, unittest.TestCase):
    def seam(self, text):
        return redact(text)


class FilterSeam(ProseCases, unittest.TestCase):
    def seam(self, text):
        return filt(text)


class SeamsAgree(unittest.TestCase):
    def test_347_story_21_both_seams_agree_on_every_story_input(self):
        for text in map(T, PROSE + MASKED):
            self.assertEqual(redact(text), filt(text), text)


class DocsChecks(unittest.TestCase):
    def read(self, name):
        with open(os.path.join(HERE, name), encoding="utf-8") as handle:
            return handle.read()

    def test_347_story_22_rules_docstring_names_the_position_rule(self):
        docstring = self.read("redact_rules.py").split('"""')[1]
        for phrase in ("line start position", "prefix grammar", "flow-mapping position"):
            self.assertIn(phrase, docstring)

    def test_347_story_22_filter_docstring_says_a_rest_is_judged_with_the_line_prefix(self):
        docstring = self.read("redact_filter.py").split('"""')[1]
        self.assertIn("judged with the line prefix", docstring)

    def test_347_story_23_residual_risk_list_names_the_accepted_cost(self):
        text = self.read("redact_post.py")
        for phrase in ("mid-line prose", "tab after a tool prefix", "grep context lines", "looks like a grep prefix"):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
