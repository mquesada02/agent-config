"""Tests of ticket 379 (ticket spec 384, general spec 367 stories 19 to 25): the PEM rule of the drop states.

A dropped line of the YAML block scalar drop state or of the empty-key drop state that holds a BEGIN marker with no
END marker after it drops every line up to and including its END line, and the text after the END marker with it;
another unclosed BEGIN marker in that text goes on to the next END line; then the state goes on.

Seam 1 is `redact(text)` through the test kit. Seam 2 is the Monitor filter script on stdin. One cases class is run by
a rules-seam class and a filter-seam class. `redact(text)` does not change in this ticket, so the rules-seam class
pins the literal output of `redact(text)` as the reference for the filter. Fixtures are built from parts, so this file holds no
secret-shaped text of its own. The docs checks read the hook files as text: they are the one exception to "tests go
through a public seam". Test names carry the rule they prove: R1 the block scalar state drops a line with an unclosed
BEGIN marker up to its END line; R2 the block scalar state goes on after that END line; R3 the text after the END
marker is dropped and a second unclosed BEGIN marker goes on to its END line; R4 an unclosed BEGIN marker with no END
line drops to the end of the input; R5 a complete pair stays; R6 the docs changes.
"""
import unittest

from redact_testkit import filt, lines, normalized, read_module, redact

K = "pass" + "word"  # a matched key name
V = "hunter2"
BEGIN = "-----BEGIN PRIVATE " + "KEY-----"
END = "-----END PRIVATE " + "KEY-----"


class DropCases:
    """Cases that both seams must satisfy with the same text. A subclass defines `seam`.

    Both seams are checked against the same literal text, so the filter output equals the `redact(text)` output."""

    def check(self, text, expected):
        out = self.seam(text)
        self.assertNotIn(V, out)
        self.assertNotIn("MIIE", out)
        self.assertEqual(out, expected)

    # the YAML block scalar state: R1 and R2
    def test_379_r1_r2_block_scalar_drops_a_pem_body_that_is_not_indented_and_goes_on(self):
        text = lines(K + ": |", "  " + BEGIN, "MIIE", END, "  " + V, "next: 1")
        self.check(text, lines(K + ": ***", "next: 1"))

    def test_379_r1_r2_block_scalar_with_a_folded_header(self):
        text = lines(K + ": >", "  " + BEGIN, "MIIE", END, "  " + V, "next: 1")
        self.check(text, lines(K + ": ***", "next: 1"))

    def test_379_r1_r2_block_scalar_with_node_properties(self):
        text = lines(K + ": !!str |", "  " + BEGIN, "MIIE", END, "  " + V, "next: 1")
        self.check(text, lines(K + ": ***", "next: 1"))

    def test_379_r1_r2_block_scalar_with_a_single_quoted_key(self):
        text = lines("'" + K + "': |", "  " + BEGIN, "MIIE", END, "  " + V, "next: 1")
        self.check(text, lines("'" + K + "': ***", "next: 1"))

    def test_379_r1_r2_block_scalar_with_a_double_quoted_key(self):
        text = lines('"' + K + '": |', "  " + BEGIN, "MIIE", END, "  " + V, "next: 1")
        self.check(text, lines('"' + K + '": ***', "next: 1"))

    def test_379_r1_r2_block_scalar_under_a_parent_key(self):
        text = lines("a:", "  " + K + ": |", "    " + BEGIN, "MIIE", END, "    " + V, "  next: 1")
        self.check(text, lines("a:", "  " + K + ": ***", "  next: 1"))

    # the text after the END marker: R3
    def test_379_r3_block_scalar_drops_the_text_after_the_end_marker_with_a_second_begin_marker(self):
        text = lines(K + ": |", "  " + BEGIN, "MIIE", END + " " + BEGIN, "  " + V)
        self.check(text, lines(K + ": ***"))

    def test_379_r3_block_scalar_goes_on_after_the_end_line_of_the_second_block(self):
        text = lines(K + ": |", "  " + BEGIN, "MIIE", END + " " + BEGIN, "x", END, "  " + V, "next: 1")
        self.check(text, lines(K + ": ***", "next: 1"))

    def test_379_r3_empty_key_drops_the_text_after_the_end_marker_with_a_second_begin_marker(self):
        # the related leak of spec 367 (the empty-key drop state)
        text = lines(K + ":", "  " + BEGIN, "MIIE", END + " " + BEGIN, V)
        self.check(text, lines(K + ": ***"))

    def test_379_r3_empty_key_goes_on_after_the_end_line_of_the_second_block(self):
        text = lines(K + ":", "  " + BEGIN, "MIIE", END + " " + BEGIN, "  " + V, END, "  " + V, "next: 1")
        self.check(text, lines(K + ": ***", "next: 1"))

    # no END line: R4 (fail-closed, also the literal output of redact(text))
    def test_379_r4_block_scalar_with_no_end_line_drops_to_the_end_of_the_input(self):
        text = lines(K + ": |", "  " + BEGIN, "MIIE", "  " + V)
        self.check(text, lines(K + ": ***"))

    def test_379_r4_block_scalar_with_no_end_line_drops_a_dedented_line_too(self):
        text = lines(K + ": |", "  " + BEGIN, "MIIE", "next: 1")
        self.check(text, lines(K + ": ***"))

    def test_379_r4_empty_key_with_no_end_line_drops_to_the_end_of_the_input(self):
        text = lines(K + ":", "  " + BEGIN, "MIIE", "  " + V)
        self.check(text, lines(K + ": ***"))

    # a complete pair and the plain empty-key shape: R5 (regression pins)
    def test_379_r5_block_scalar_complete_pair_on_a_block_line_keeps_the_behavior(self):
        text = lines(K + ": |", "  a " + BEGIN + " MIIE " + END + " b", "  " + V, "next: 1")
        self.check(text, lines(K + ": ***", "next: 1"))

    def test_379_r5_empty_key_complete_pair_on_a_hidden_line_keeps_the_behavior(self):
        text = lines(K + ":", "  a " + BEGIN + " MIIE " + END + " b", "  " + V, "next: 1")
        self.check(text, lines(K + ": ***", "next: 1"))

    def test_379_r5_empty_key_pem_block_keeps_the_behavior(self):
        text = lines(K + ":", "  " + BEGIN, "MIIE", END, "  " + V, "next: 1")
        self.check(text, lines(K + ": ***", "next: 1"))

    def test_379_r5_block_scalar_pair_then_an_unclosed_begin_marker_starts_the_drop(self):
        text = lines(K + ": |", "  a " + BEGIN + " MIIE " + END + " b " + BEGIN, "MIIE", END, "  " + V, "next: 1")
        self.check(text, lines(K + ": ***", "next: 1"))


class RulesSeamTest(DropCases, unittest.TestCase):
    def seam(self, text):
        return redact(text)


class FilterSeamTest(DropCases, unittest.TestCase):
    def seam(self, text):
        return filt(text)


class DocsChecks(unittest.TestCase):
    def bullet(self, first_words):
        docstring = read_module("redact_filter.py").split('"""')[1]
        for item in docstring.split("\n- "):
            if normalized(item).startswith(first_words):
                return normalized(item)
        self.fail("no bullet starts with " + first_words)

    def check_pem_rule(self, first_words):
        bullet = self.bullet(first_words)
        self.assertIn("the PEM rule of the drop states", bullet)
        self.assertIn("drops up to its END line and the text after it", bullet)
        self.assertIn("goes on to the next END line", bullet)

    def test_379_r6_block_scalar_bullet_names_the_pem_rule_of_the_drop_states(self):
        self.check_pem_rule("A YAML block scalar under a matched key")

    def test_379_r6_empty_key_bullet_names_the_pem_rule_of_the_drop_states(self):
        self.check_pem_rule("A matched key with an empty value")

    def test_379_r6_residual_risk_list_no_longer_names_the_block_scalar_leak(self):
        text = normalized(read_module("redact_post.py"))
        self.assertNotIn("A BEGIN line inside a YAML block scalar with an unindented PEM body leaks too.", text)

    def test_379_r6_residual_risk_list_keeps_the_cr_m10_sentence_and_the_rest_only_bullet(self):
        text = normalized(read_module("redact_post.py"))
        self.assertIn(
            "A next-line JSON string with a BEGIN line and no END line differs between the two seams (fail-closed).",
            text,
        )
        self.assertIn("uses the column of the rest only", text)


if __name__ == "__main__":
    unittest.main()
