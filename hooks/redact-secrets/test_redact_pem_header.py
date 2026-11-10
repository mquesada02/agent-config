"""Tests of ticket 416 (ticket spec 418, general spec 413 leak A): a block scalar header line with a BEGIN marker.

When the header line of a YAML block scalar of a secret key holds a BEGIN marker (`SK: | BEGIN`), the block state that
the text before the marker opens goes on after the END line of the held PEM block. The block lines after the END line
that are empty or deeper than the key column are hidden, as `redact(text)` hides them.

Seam 1 is `redact(text)` through the test kit. Seam 2 is the Monitor filter script on stdin. One cases class is run by
a rules-seam class and a filter-seam class. `redact(text)` does not change in this ticket, so the rules-seam class
pins the literal output of `redact(text)` as the reference for the filter. Fixtures are built from parts, so this file
holds no secret-shaped text of its own. The docs check reads the filter file as text: it is the one exception to "tests
go through a public seam". "Story" numbers in a test name are the stories of ticket spec 418. Test names carry the
rule they prove: R1 the block state goes on after a held END line; R2 the key column of the carried state; R3 empty
lines after END stay hidden and a shallow line ends the state; R4 node properties and `>`; R5 a key that is not a
secret key opens no state; R6 past the cap the block state goes on and the text after END is dropped; R7 a second BEGIN
marker in the text after END keeps the state; R8 the docstring phrase; R9 the block state has priority over a state
that the text after END opens; R10 the held-line count of a second hold starts again; R11 the cap boundary.
"""
import unittest

from redact_testkit import filt, lines, normalized, read_module, redact

K = "pass" + "word"  # a matched key name
V = "hunter2"
BEGIN = "-----BEGIN PRIVATE " + "KEY-----"
END = "-----END PRIVATE " + "KEY-----"
HEADER = K + ": | " + BEGIN


class HeaderCases:
    """Cases that both seams must satisfy. A subclass defines `seam` and `is_rules`."""

    is_rules = False

    def check(self, text, expected):
        out = self.seam(text)
        self.assertNotIn(V, out)
        self.assertNotIn("MIIE", out)
        self.assertEqual(out, expected)

    def check_own(self, text, rules_expected, filter_expected):
        """A story that states one output for `redact(text)` and another for the filter."""
        self.check(text, rules_expected if self.is_rules else filter_expected)

    # stories 1 to 5: the block state goes on after the END line
    def test_416_r1_story_1_a_block_line_after_end_is_hidden(self):
        self.check(lines(HEADER, "  MIIE", "  " + END, "  " + V, "keep: 1"), lines(K + ": ***", "keep: 1"))

    def test_416_r4_story_2_a_folded_header(self):
        text = lines(K + ": > " + BEGIN, "  MIIE", "  " + END, "  " + V, "keep: 1")
        self.check(text, lines(K + ": ***", "keep: 1"))

    def test_416_r2_story_3_a_deeper_key_uses_its_own_column(self):
        text = lines("a:", "  " + HEADER, "    MIIE", "    " + END, "    " + V, "  next: 1")
        self.check(text, lines("a:", "  " + K + ": ***", "  next: 1"))

    def test_416_r3_story_4_an_empty_line_after_end_does_not_end_the_state(self):
        self.check(lines(HEADER, "  MIIE", "  " + END, "", "  " + V, "keep: 1"), lines(K + ": ***", "keep: 1"))

    def test_416_r3_story_5_a_line_not_deeper_than_the_key_ends_the_state(self):
        self.check(lines(HEADER, "  MIIE", "  " + END, "keep: 1"), lines(K + ": ***", "keep: 1"))

    # stories 6 to 6d: the text on the END line and the cases that keep today's output
    def test_416_r1_story_6_text_after_end_on_the_end_line_stays_hidden(self):
        self.check(lines(HEADER, "  MIIE", "  " + END + " " + V, "keep: 1"), lines(K + ": ***", "keep: 1"))

    def test_416_r1_story_6a_a_begin_marker_on_its_own_block_line(self):
        text = lines(K + ": |", "  " + BEGIN, "  MIIE", "  " + END, "  " + V, "keep: 1")
        self.check(text, lines(K + ": ***", "keep: 1"))

    def test_416_r2_story_6b_text_after_end_of_a_deeper_key_stays_hidden_at_any_indent(self):
        text = lines("a:", "  " + HEADER, "    MIIE", END + " " + V, "  next: 1")
        self.check(text, lines("a:", "  " + K + ": ***", "  next: 1"))

    def test_416_r9_story_6c_the_block_state_has_priority_over_an_object_that_the_text_after_end_opens(self):
        text = lines(HEADER, "  MIIE", "  " + END + ' "' + K + '": {', '  "a": "' + V + '"', "keep: 1")
        self.check(text, lines(K + ": ***", "keep: 1"))

    def test_416_r9_story_6d_a_line_that_is_not_deeper_than_the_key_stays(self):
        text = lines(HEADER, "  MIIE", "  " + END + ' "' + K + '": {', '  "a": "' + V + '"', "}", "keep: 1")
        self.check(text, lines(K + ": ***", "}", "keep: 1"))

    # story 7: node properties
    def test_416_r4_story_7_a_header_with_node_properties(self):
        text = lines(K + ": !!str | " + BEGIN, "  MIIE", "  " + END, "  " + V, "keep: 1")
        self.check(text, lines(K + ": ***", "keep: 1"))

    # story 8: a key that is not a secret key opens no state
    def test_416_r5_story_8_a_key_that_is_not_a_secret_key_keeps_the_text_after_end(self):
        text = lines("name: | " + BEGIN, "  MIIE", "  " + END, "  text", "keep: 1")
        out = self.seam(text)  # not `check`: this story hides no V, and `  text` stays
        self.assertEqual(out, lines("name: | ***", "  text", "keep: 1"))

    # stories 9, 9a, 9b: the held-line cap (the BEGIN line is line 1)
    def test_416_r6_story_9_past_the_cap_the_block_lines_after_end_are_dropped(self):
        text = lines(HEADER, *["  MIIE"] * 250, "  " + END, "  " + V, "keep: 1")
        self.check_own(text, lines(K + ": ***", "keep: 1"), lines("***", "keep: 1"))

    def test_416_r6_story_9_text_on_the_end_line_past_the_cap_is_dropped(self):
        text = lines(HEADER, *["  MIIE"] * 250, "  " + END + " " + V, "  " + V, "keep: 1")
        self.check_own(text, lines(K + ": ***", "keep: 1"), lines("***", "keep: 1"))

    def test_416_r11_story_9a_an_end_line_on_line_200_is_held(self):
        text = lines(HEADER, *["  MIIE"] * 198, "  " + END, "  " + V, "keep: 1")
        self.check(text, lines(K + ": ***", "keep: 1"))

    def test_416_r11_story_9b_an_end_line_on_line_201_is_past_the_cap(self):
        text = lines(HEADER, *["  MIIE"] * 199, "  " + END, "  " + V, "keep: 1")
        self.check_own(text, lines(K + ": ***", "keep: 1"), lines("***", "keep: 1"))

    # story 10: no END line before the end of the input
    def test_416_r1_story_10_a_held_block_with_no_end_line_writes_nothing_in_the_filter(self):
        out = self.seam(lines(HEADER, "  MIIE", "keep: 1"))
        self.assertNotIn("MIIE", out)
        self.assertNotIn("keep", out)
        self.assertEqual(out, K + ": ***" if self.is_rules else "")

    # stories 10a to 10c: a second BEGIN marker in the text after END
    def test_416_r7_story_10a_a_second_begin_marker_on_the_end_line_keeps_the_state(self):
        text = lines(HEADER, "  MIIE", "  " + END + " x " + BEGIN, "  MIIE", "  " + END, "  " + V, "keep: 1")
        self.check(text, lines(K + ": ***", "keep: 1"))

    def test_416_r7_story_10b_a_second_begin_marker_past_the_cap_keeps_the_state(self):
        text = lines(HEADER, *["  MIIE"] * 250, "  " + END + " x " + BEGIN, "  MIIE", "  " + END, "  " + V, "keep: 1")
        self.check_own(text, lines(K + ": ***", "keep: 1"), lines("***", "keep: 1"))

    def test_416_r10_story_10c_the_held_line_count_of_a_second_hold_starts_again(self):
        text = lines(HEADER, "  MIIE", "  " + END + " x " + BEGIN, *["  MIIE"] * 250, "  " + END, "  " + V, "keep: 1")
        self.check_own(text, lines(K + ": ***", "keep: 1"), lines("***", "keep: 1"))

    def test_416_r10_story_10c_variant_a_second_hold_under_its_own_cap_is_held(self):
        # 150 lines in the first block and 100 in the second: 250 in all, but each count stays under the cap
        text = lines(
            HEADER, *["  MIIE"] * 150, "  " + END + " x " + BEGIN, *["  MIIE"] * 100, "  " + END, "  " + V, "keep: 1"
        )
        self.check(text, lines(K + ": ***", "keep: 1"))


class RulesSeamTest(HeaderCases, unittest.TestCase):
    is_rules = True

    def seam(self, text):
        return redact(text)


class FilterSeamTest(HeaderCases, unittest.TestCase):
    def seam(self, text):
        return filt(text)


class SeamAgreementTest(unittest.TestCase):
    """For the stories that state one output for both seams, the filter output equals the `redact(text)` output."""

    def test_416_both_seams_agree_on_the_equal_output_stories(self):
        for text in (
            lines(HEADER, "  MIIE", "  " + END, "  " + V, "keep: 1"),
            lines(K + ": > " + BEGIN, "  MIIE", "  " + END, "  " + V, "keep: 1"),
            lines("a:", "  " + HEADER, "    MIIE", "    " + END, "    " + V, "  next: 1"),
            lines(HEADER, "  MIIE", "  " + END, "", "  " + V, "keep: 1"),
            lines(HEADER, "  MIIE", "  " + END, "keep: 1"),
            lines(HEADER, "  MIIE", "  " + END + " " + V, "keep: 1"),
            lines(K + ": |", "  " + BEGIN, "  MIIE", "  " + END, "  " + V, "keep: 1"),
            lines("a:", "  " + HEADER, "    MIIE", END + " " + V, "  next: 1"),
            lines(HEADER, "  MIIE", "  " + END + ' "' + K + '": {', '  "a": "' + V + '"', "keep: 1"),
            lines(HEADER, "  MIIE", "  " + END + ' "' + K + '": {', '  "a": "' + V + '"', "}", "keep: 1"),
            lines(K + ": !!str | " + BEGIN, "  MIIE", "  " + END, "  " + V, "keep: 1"),
            lines("name: | " + BEGIN, "  MIIE", "  " + END, "  text", "keep: 1"),
            lines(HEADER, *["  MIIE"] * 198, "  " + END, "  " + V, "keep: 1"),
            lines(HEADER, "  MIIE", "  " + END + " x " + BEGIN, "  MIIE", "  " + END, "  " + V, "keep: 1"),
        ):
            with self.subTest(text=text):
                self.assertEqual(filt(text), redact(text))


class DocsChecks(unittest.TestCase):
    def test_416_r8_the_yaml_block_scalar_bullet_names_the_block_scalar_header_line_with_a_begin_marker(self):
        docstring = read_module("redact_filter.py").split('"""')[1]
        bullets = [normalized(item) for item in docstring.split("\n- ")]
        bullet = [item for item in bullets if item.startswith("A YAML block scalar under a matched key")]
        self.assertEqual(len(bullet), 1)
        self.assertIn("a block scalar header line that holds a BEGIN marker", bullet[0])


if __name__ == "__main__":
    unittest.main()
