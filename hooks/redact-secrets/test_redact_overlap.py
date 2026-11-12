"""Tests of issue 534: overlapping secret values and values that hold the mask text.

The rules are key based and run in one pass, so no replacement reads the output of another one.
These tests pin that behavior for three cases: one value that contains another, a value that equals
or contains the mask text, and two keyed values next to each other. Each case runs in JSON, in YAML,
on separate lines and as plain pairs on one line. Some formats add a case about the text around the values.

JSON, YAML and separate lines: every value becomes `***` once and the rest of the text is unchanged.
Plain pairs on one line: `plain_line_value` masks from the first value to the line end (a plain value
can hold spaces), so the line becomes `<key>=***`. This is the fail-closed design, pinned on purpose.
Fixtures are built from parts, so this file holds no secret-shaped text of its own.
"""
import json
import unittest

from redact_testkit import redact

K1 = "pass" + "word"  # a matched key name
K2 = "to" + "ken"  # a second matched key name
MASK = "***"
LONG = "abc123"
SHORT = "abc"


class OverlapJson(unittest.TestCase):
    def check(self, v1, v2):
        text = '{"%s": "%s", "%s": "%s"}\n' % (K1, v1, K2, v2)
        out = redact(text)
        self.assertEqual(out, '{"%s": "%s", "%s": "%s"}\n' % (K1, MASK, K2, MASK))
        self.assertEqual(json.loads(out), {K1: MASK, K2: MASK})

    def test_534_json_a_value_that_contains_the_next_value(self):
        self.check(LONG, SHORT)

    def test_534_json_a_value_that_is_inside_the_next_value(self):
        self.check(SHORT, LONG)

    def test_534_json_two_equal_values(self):
        self.check(SHORT, SHORT)

    def test_534_json_two_values_next_to_each_other(self):
        text = '{"%s":"%s","%s":"%s"}\n' % (K1, "a", K2, "b")
        self.assertEqual(redact(text), '{"%s":"%s","%s":"%s"}\n' % (K1, MASK, K2, MASK))

    def test_534_json_a_value_equal_to_the_mask(self):
        self.check(MASK, MASK)

    def test_534_json_a_value_with_a_star(self):
        self.check("*", "*")

    def test_534_json_a_value_that_holds_the_mask(self):
        self.check("a" + MASK + "b", "x" + MASK)

    def test_534_json_a_mask_value_next_to_a_long_value(self):
        self.check(MASK, LONG)

    def test_534_json_text_around_the_values_is_unchanged(self):
        text = 'before {"%s": "%s", "n": 1, "%s": "%s"} after\n' % (K1, LONG, K2, SHORT)
        self.assertEqual(redact(text), 'before {"%s": "%s", "n": 1, "%s": "%s"} after\n' % (K1, MASK, K2, MASK))


class OverlapYaml(unittest.TestCase):
    def check(self, v1, v2, quote_char=""):
        q = quote_char
        text = "%s: %s%s%s\n%s: %s%s%s\n" % (K1, q, v1, q, K2, q, v2, q)
        expected = "%s: %s%s%s\n%s: %s%s%s\n" % (K1, q, MASK, q, K2, q, MASK, q)
        self.assertEqual(redact(text), expected)

    def test_534_yaml_a_value_that_contains_the_next_value(self):
        self.check(LONG, SHORT)

    def test_534_yaml_a_value_that_is_inside_the_next_value(self):
        self.check(SHORT, LONG)

    def test_534_yaml_quoted_values_where_one_contains_the_other(self):
        self.check(LONG, SHORT, "'")

    def test_534_yaml_a_single_quoted_value_equal_to_the_mask(self):
        self.check(MASK, MASK, "'")

    def test_534_yaml_a_single_quoted_value_with_a_star(self):
        self.check("*", "*", "'")

    def test_534_yaml_a_double_quoted_value_equal_to_the_mask(self):
        self.check(MASK, MASK, '"')

    def test_534_yaml_a_plain_value_equal_to_the_mask(self):
        self.check(MASK, MASK)

    def test_534_yaml_a_value_that_holds_the_mask(self):
        self.check("a" + MASK + "b", "x" + MASK, "'")

    def test_534_yaml_a_line_between_the_values_is_unchanged(self):
        text = "%s: %s\nname: demo\n%s: %s\n" % (K1, LONG, K2, SHORT)
        self.assertEqual(redact(text), "%s: %s\nname: demo\n%s: %s\n" % (K1, MASK, K2, MASK))


class OverlapSeparateLines(unittest.TestCase):
    def check(self, v1, v2):
        text = "%s=%s\n%s=%s\n" % (K1, v1, K2, v2)
        self.assertEqual(redact(text), "%s=%s\n%s=%s\n" % (K1, MASK, K2, MASK))

    def test_534_lines_a_value_that_contains_the_next_value(self):
        self.check(LONG, SHORT)

    def test_534_lines_a_value_that_is_inside_the_next_value(self):
        self.check(SHORT, LONG)

    def test_534_lines_two_equal_values(self):
        self.check(SHORT, SHORT)

    def test_534_lines_a_value_equal_to_the_mask(self):
        self.check(MASK, MASK)

    def test_534_lines_a_value_with_a_star(self):
        self.check("*", "*")

    def test_534_lines_a_value_that_holds_the_mask(self):
        self.check("a" + MASK + "b", "x" + MASK)

    def test_534_lines_a_line_between_the_values_is_unchanged(self):
        text = "%s=%s\nname=demo\n%s=%s\n" % (K1, LONG, K2, SHORT)
        self.assertEqual(redact(text), "%s=%s\nname=demo\n%s=%s\n" % (K1, MASK, K2, MASK))


class OverlapPlainPairsOnOneLine(unittest.TestCase):
    """The first value masks to the line end, so the second value is gone with it."""

    def check(self, v1, v2):
        text = "%s=%s %s=%s\n" % (K1, v1, K2, v2)
        self.assertEqual(redact(text), "%s=%s\n" % (K1, MASK))

    def test_534_one_line_a_value_that_contains_the_next_value(self):
        self.check(LONG, SHORT)

    def test_534_one_line_a_value_that_is_inside_the_next_value(self):
        self.check(SHORT, LONG)

    def test_534_one_line_two_values_next_to_each_other(self):
        self.check("x", "y")

    def test_534_one_line_a_value_equal_to_the_mask(self):
        self.check(MASK, MASK)

    def test_534_one_line_a_value_with_a_star(self):
        self.check("*", "*")

    def test_534_one_line_a_value_that_holds_the_mask(self):
        self.check("a" + MASK + "b", "x" + MASK)

    def test_534_one_line_text_before_the_first_key_is_unchanged(self):
        text = "run %s=%s %s=%s\n" % (K1, LONG, K2, SHORT)
        self.assertEqual(redact(text), "run %s=%s\n" % (K1, MASK))


if __name__ == "__main__":
    unittest.main()
