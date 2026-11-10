"""Tests of ticket 380 (ticket spec 388, general spec 367 stories 13 to 18b, 24 and 25): the joined line of a held PEM
block in a keyed line value, and the held-line cap gate.

Seam 1 is `redact(text)` through the test kit. Seam 2 is the Monitor filter script on stdin. `redact(text)` does not
change in this ticket, so the rules-seam class pins the literal output of `redact(text)` as the reference for the
filter. Story numbers in test names are the numbers of the ticket spec (1 to 11). Fixtures are built from parts, so this
file holds no secret-shaped text of its own. The docs checks read the hook files as text: they are the one exception to
"tests go through a public seam". Test names carry the rule they prove: R1 the joined line is written as redact(text)
writes it; R2 a state that the rest after the END marker opens works as on a normal line; R3 a block with an open JSON
depth keeps its path; R4 past the cap the rest is dropped when the BEGIN marker stands in a masked keyed value; R5 the
drop stops at the next BEGIN marker; R6 no masked value keeps the rest as a normal line; R7 no END line writes nothing
of the held lines; R8 the docs changes.
"""
import unittest

from redact_testkit import filt, lines, normalized, read_module, redact

K = "pass" + "word"  # a matched key name
V = "hunter2"
BEGIN = "-----BEGIN PRIVATE " + "KEY-----"
END = "-----END PRIVATE " + "KEY-----"


def body_lines(count):
    return ["MIIE%03d" % number for number in range(count)]


class JoinedCases:
    """Cases that both seams must satisfy with the same literal text. A subclass defines `seam`."""

    def check(self, text, expected):
        out = self.seam(text)
        self.assertNotIn(V, out)
        self.assertNotIn("MIIE", out)
        self.assertEqual(out, expected)

    # R1: the joined line (spec stories 1 to 3)
    def test_380_r1_yaml_plain_value_hides_the_text_after_the_end_marker(self):
        self.check(lines(K + ": " + BEGIN, "MIIE", END + " " + V), lines(K + ": ***"))

    def test_380_r1_json_string_value_hides_the_text_after_the_end_marker(self):
        text = lines('{"%s": "%s' % (K, BEGIN), "MIIE", END + " " + V + '"}')
        self.check(text, lines('{"%s": "***"}' % K))

    def test_380_r1_env_value_hides_the_text_after_the_end_marker(self):
        self.check(lines(K + "=" + BEGIN, "MIIE", END + " " + V), lines(K + "=***"))

    def test_380_r1_yaml_single_quoted_value(self):
        text = lines(K + ": '" + BEGIN, "MIIE", END + " " + V + "'")
        self.check(text, lines(K + ": '***'"))

    def test_380_r1_yaml_double_quoted_value(self):
        text = lines(K + ': "' + BEGIN, "MIIE", END + " " + V + '"')
        self.check(text, lines(K + ': "***"'))

    def test_380_r1_the_extra_quote_is_gone(self):
        text = lines('{"%s": "%s' % (K, BEGIN), "MIIE", END + '", "%s": "%s"}' % (K, V))
        self.check(text, lines('{"%s": "***", "%s": "***"}' % (K, K)))

    def test_380_r1_text_before_the_begin_marker_and_a_complete_pair_are_kept_as_the_rules_write_them(self):
        text = lines("x " + BEGIN + " a " + END + ' "' + K + '": "' + BEGIN, "MIIE", END + " " + V + '"', "next: 1")
        self.check(text, lines('x *** "' + K + '": "***"', "next: 1"))

    # R3: a block that is inside an object under a secret key keeps its path (spec story 4)
    def test_380_r3_block_inside_an_object_under_a_secret_key_keeps_the_json_state(self):
        text = lines('{"%s": {"k": "%s' % (K, BEGIN), "MIIE", END + '",', '"n": "%s"' % V, "}", "after: 1")
        self.check(text, lines('{"%s": "***"' % K, "after: 1"))

    # R2: a later state that the rest opens (spec story 5)
    def test_380_r2_a_begin_marker_in_the_rest_opens_a_second_held_block(self):
        text = lines(K + ": " + BEGIN, "MIIE", END + " x " + BEGIN, "MIIE", END + " " + V)
        self.check(text, lines(K + ": ***"))

    def test_380_r2_a_pending_json_value_in_the_rest(self):
        text = lines('{"%s": "%s' % (K, BEGIN), "MIIE", END + '", "%s":' % K, '"%s"' % V)
        self.check(text, lines('{"%s": "***", "%s":' % (K, K), '"***"'))

    # R7 (the redact seam of spec story 9) and R6 (the redact seam of spec story 8) are in the subclasses


class RulesSeamTest(JoinedCases, unittest.TestCase):
    def seam(self, text):
        return redact(text)

    def test_380_r2_an_empty_key_in_the_rest_with_a_deeper_line_shows_the_line(self):
        # the rules measure the key column on the whole line, so `keep` stays (the filter hides it, fail-closed)
        text = lines("x " + BEGIN, "MIIE", END + ' "%s":' % K, "  keep")
        self.assertEqual(redact(text), lines('x *** "%s":' % K, "  keep"))

    def test_380_r4_past_the_cap_redact_masks_the_whole_value(self):
        text = lines(K + ": " + BEGIN, *body_lines(200), END + " " + V)
        self.assertEqual(redact(text), lines(K + ": ***"))
        text = lines('{"%s": "%s' % (K, BEGIN), *body_lines(200), END + " " + V + '"}')
        self.assertEqual(redact(text), lines('{"%s": "***"}' % K))

    def test_380_r6_a_string_that_closes_before_the_marker_keeps_the_rest(self):
        text = lines('"%s": "x" "%s' % (K, BEGIN), *body_lines(200), END + " " + V)
        self.assertEqual(redact(text), lines('"%s": "***" "*** %s' % (K, V)))

    def test_380_r7_no_end_line_masks_to_the_end_of_the_input(self):
        self.assertEqual(redact(lines(K + ": " + BEGIN, "MIIE")), K + ": ***")


class FilterSeamTest(JoinedCases, unittest.TestCase):
    def seam(self, text):
        return filt(text)

    def test_380_r2_an_empty_key_in_the_rest_hides_a_deeper_line_by_the_column_of_the_rest_only(self):
        # spec 367 story 17, owner decision 5: fail-closed, the filter hides more than redact(text)
        out = filt(lines("x " + BEGIN, "MIIE", END + ' "%s":' % K, "  keep", "next: 1"))
        self.assertEqual(out, lines('x *** "%s": ***' % K, "next: 1"))

    def test_380_r2_an_empty_key_in_the_rest_with_a_line_that_is_not_deeper_shows_the_line(self):
        out = filt(lines("x " + BEGIN, "MIIE", END + ' "%s":' % K, "keep"))
        self.assertEqual(out, lines('x *** "%s":' % K, "keep"))

    # R4: past the held-line cap (spec stories 6 and 7)
    def test_380_r4_past_the_cap_yaml_value_drops_the_text_after_the_end_marker(self):
        out = filt(lines(K + ": " + BEGIN, *body_lines(200), END + " " + V))
        self.assertEqual(out, lines("***"))

    def test_380_r4_past_the_cap_json_string_value_drops_the_text_after_the_end_marker(self):
        out = filt(lines('{"%s": "%s' % (K, BEGIN), *body_lines(200), END + " " + V + '"}'))
        self.assertEqual(out, lines("***"))

    def test_380_r4_past_the_cap_env_value_drops_the_text_after_the_end_marker(self):
        out = filt(lines(K + "=" + BEGIN, *body_lines(200), END + " " + V))
        self.assertEqual(out, lines("***"))

    def test_380_r4_past_the_cap_plain_double_quoted_key_value_drops_the_text_after_the_end_marker(self):
        out = filt(lines('"%s": %s' % (K, BEGIN), *body_lines(200), END + " " + V))
        self.assertEqual(out, lines("***"))

    def test_380_r4_past_the_cap_the_drop_holds_after_a_complete_pair_before_the_marker(self):
        out = filt(lines("a " + BEGIN + " x " + END + ' "' + K + '": ' + BEGIN, *body_lines(200), END + " " + V))
        self.assertEqual(out, lines("***"))

    def test_380_r5_the_drop_stops_at_the_next_begin_marker_and_a_second_block_is_held(self):
        text = lines(K + ": " + BEGIN, *body_lines(200), END + " " + BEGIN, "MIIE", END, "next: 1")
        self.assertEqual(filt(text), lines("***", "***", "next: 1"))

    def test_380_r5_a_complete_pair_after_the_end_marker_is_a_normal_line(self):
        text = lines(K + ": " + BEGIN, *body_lines(200), END + " " + V + " " + BEGIN + " a " + END + " b", "next: 1")
        self.assertEqual(filt(text), lines("***", "*** b", "next: 1"))

    def test_380_r5_with_no_begin_marker_the_next_line_is_a_normal_line(self):
        text = lines(K + ": " + BEGIN, *body_lines(200), END + " " + V, K + ": " + V)
        self.assertEqual(filt(text), lines("***", K + ": ***"))

    def test_380_r6_a_string_that_closes_before_the_marker_keeps_the_rest_as_a_normal_line(self):
        out = filt(lines('"%s": "x" "%s' % (K, BEGIN), *body_lines(200), END + " " + V))
        self.assertEqual(out, lines("***", " " + V))

    def test_380_r6_no_key_keeps_the_rest_as_a_normal_line(self):
        out = filt(lines("a: " + BEGIN, *body_lines(200), END + " keep"))
        self.assertEqual(out, lines("***", " keep"))

    # R7: no END line (spec story 9)
    def test_380_r7_no_end_line_writes_nothing_of_the_held_lines(self):
        self.assertEqual(filt(lines(K + ": " + BEGIN, "MIIE")), "")


class DocsChecks(unittest.TestCase):
    def read(self, name):
        return read_module(name)

    def test_380_r8_the_pem_hold_bullet_describes_the_joined_line_and_the_cap_gate(self):
        docstring = self.read("redact_filter.py").split('"""')[1]
        bullets = [
            normalized(item) for item in docstring.split("\n- ") if item.startswith("A PEM private-key block is held")
        ]
        self.assertEqual(len(bullets), 1)
        for phrase in ("the joined line", "the held-line cap", "masked keyed value", "up to the next BEGIN marker"):
            self.assertIn(phrase, bullets[0])
        self.assertIn("the JSON state goes on after the END line", normalized(docstring))
        self.assertIn("a bracket inside a PEM block", normalized(docstring))

    def test_380_r8_residual_risk_list_no_longer_names_the_pem_then_text_leak(self):
        text = normalized(self.read("redact_post.py"))
        self.assertNotIn("is not tracked past its END line", text)
        self.assertNotIn("a secret in the text after the END line can be written", text)

    def test_380_r8_residual_risk_list_keeps_the_cr_m10_sentence_as_its_own_bullet(self):
        text = self.read("redact_post.py")
        sentence = "A next-line JSON string with a BEGIN line and no END line differs between the two seams (fail-closed)."
        self.assertIn("\n- " + sentence, text)
        self.assertIn("uses the column of the rest only", normalized(text))


if __name__ == "__main__":
    unittest.main()
