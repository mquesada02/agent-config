"""Tests of ticket 417 (ticket spec 422, general spec 413 leaks B and C): a JSON key written with escaped quotes.

A JSON key written with escaped quotes (`{\\"SK\\": {`, JSON inside a string) whose object or array value does not close
on its line opens the JSON open-object state in both seams, as a plain double-quoted key does. The same holds for such
a key that an earlier value swallows (leak C): `redact(text)` and the filter hide the object value.

Seam 1 is `redact(text)` through the test kit. Seam 2 is the Monitor filter script on stdin. One cases class is run by
a rules-seam class and a filter-seam class. Fixtures are built from parts, so this file holds no secret-shaped text of
its own. The docs checks read the hook files as text: they are the one exception to "tests go through a public seam".
"Story" numbers in a test name are the stories of ticket spec 422. Test names carry the rule they prove: R1 an
escaped-quote object key opens the state; R2 an array value; R3 nested brackets balance; R4 the text after the closing
bracket; R5 no closing bracket fails closed; R6 the state has no held-line cap; R7 a swallowed escaped-quote key opens
the state; R8 the docstring phrase of the filter; R9 an escaped-quote key opens no block or empty-key state; R10 the
docs of the shared decision. Placeholders in the comments: SK a secret key, V a secret value.
"""
import ast
import re
import unittest

from redact_testkit import filt, lines, read_module, redact

K = "pass" + "word"  # a matched key name
V = "hunter2"
BEGIN = "-----BEGIN PRIVATE " + "KEY-----"
END = "-----END PRIVATE " + "KEY-----"
Q = "\\" + '"'  # an escaped quote
EK = "{" + Q + K + Q + ": "  # the head of an escaped-quote key line
MASKED = EK + Q + "***" + Q  # an escaped-quote key whose value is masked
PLAIN_MASKED = '{"' + K + '": "***"'
PHRASE = "opens the JSON open-object state but never a block or an empty-key state"


def member(name, value):
    """An escaped-quote JSON member."""
    return Q + name + Q + ": " + value


class EscapedJsonCases:
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

    # stories 1 to 3: the state opens and the brackets balance
    def test_417_r1_story_1_an_object_value_over_lines_is_hidden(self):
        text = lines(EK + "{", "  " + member("a", Q + V + Q), "}", "keep: 1")
        self.check(text, lines(MASKED, "keep: 1"))

    def test_417_r2_story_2_an_array_value_over_lines_is_hidden(self):
        text = lines(EK + "[", "  " + Q + V + Q, "]", "keep: 1")
        self.check(text, lines(MASKED, "keep: 1"))

    def test_417_r3_story_3_a_nested_object_is_dropped_up_to_the_balancing_bracket(self):
        text = lines(EK + "{", "  " + member("a", "{"), "    " + member("b", Q + V + Q), "  }", "}", "keep: 1")
        self.check(text, lines(MASKED, "keep: 1"))

    # stories 4 and 5: the end of the state
    def test_417_r4_story_4_the_text_after_the_closing_bracket_is_written(self):
        tail = ", " + member("n", "1") + "}"
        text = lines(EK + "{", "  " + member("a", Q + V + Q) + "}" + tail, "keep: 1")
        self.check_own(text, lines(MASKED + tail, "keep: 1"), lines(MASKED, tail, "keep: 1"))

    def test_417_r5_story_5_no_closing_bracket_hides_the_rest_of_the_input(self):
        text = lines(EK + "{", "  " + member("a", Q + V + Q), "keep: 1")
        out = self.seam(text)
        self.assertNotIn(V, out)
        self.assertNotIn("keep", out)
        self.assertEqual(out, MASKED if self.is_rules else MASKED + "\n")

    def test_417_r6_story_6_an_array_over_the_held_line_cap_is_hidden(self):
        filler = ["  " + Q + "x%d" % number + Q + "," for number in range(250)]
        text = lines(EK + "[", *filler, "  " + Q + V + Q, "]", "keep: 1")
        self.check(text, lines(MASKED, "keep: 1"))

    # stories 7 to 9: the output stays as on main
    def test_417_story_7_an_object_that_closes_on_its_line_keeps_its_output(self):
        text = lines(EK + "{" + member("a", Q + V + Q) + "}}", "keep: 1")
        self.check(text, lines(MASKED + "}", "keep: 1"))

    def test_417_story_8_a_begin_marker_inside_an_object_value_keeps_its_output(self):
        text = lines(EK + "{" + member("a", Q + BEGIN), "MIIE", END + Q + ", " + member("b", Q + V + Q) + "}}", "keep: 1")
        self.check(text, lines(MASKED + "}", "keep: 1"))

    def test_417_story_9_a_plain_double_quoted_key_object_keeps_its_output(self):
        text = lines('{"' + K + '": {', '  "a": "' + V + '"', "}", "keep: 1")
        self.check(text, lines(PLAIN_MASKED, "keep: 1"))

    # story 10: no block or empty-key state for an escaped-quote key
    def test_417_r9_story_10_a_next_line_value_of_an_escaped_quote_key_is_shown(self):
        text = lines("{" + Q + K + Q + ":", "  " + Q + V + Q, "keep: 1")
        self.assertEqual(self.seam(text), text)

    # stories 11 and 12: the swallowed key
    def test_417_r7_story_11_a_swallowed_escaped_quote_key_hides_its_object_value(self):
        text = lines(K + ": x " + EK + "{", "  " + member("a", Q + V + Q), "}", "keep: 1")
        self.check(text, lines(K + ": ***", "keep: 1"))

    def test_417_r7_story_11_a_swallowed_escaped_quote_key_hides_its_array_value(self):
        text = lines(K + ": x " + EK + "[", "  " + Q + V + Q, "]", "keep: 1")
        self.check(text, lines(K + ": ***", "keep: 1"))

    def test_417_story_12_a_swallowed_plain_double_quoted_key_keeps_its_output(self):
        text = lines(K + ': x {"' + K + '": {', '  "a": "' + V + '"', "}", "keep: 1")
        self.check(text, lines(K + ": ***", "keep: 1"))


class RulesSeamTest(EscapedJsonCases, unittest.TestCase):
    is_rules = True

    def seam(self, text):
        return redact(text)


class FilterSeamTest(EscapedJsonCases, unittest.TestCase):
    def seam(self, text):
        return filt(text)


class SeamAgreementTest(unittest.TestCase):
    """For the stories that state one output for both seams, the filter output equals the `redact(text)` output."""

    def test_417_both_seams_agree_on_the_equal_output_stories(self):
        for text in (
            lines(EK + "{", "  " + member("a", Q + V + Q), "}", "keep: 1"),
            lines(EK + "[", "  " + Q + V + Q, "]", "keep: 1"),
            lines(EK + "{", "  " + member("a", "{"), "    " + member("b", Q + V + Q), "  }", "}", "keep: 1"),
            lines(EK + "[", *["  " + Q + "x%d" % number + Q + "," for number in range(250)], "  " + Q + V + Q, "]", "keep: 1"),
            lines(EK + "{" + member("a", Q + V + Q) + "}}", "keep: 1"),
            lines(EK + "{" + member("a", Q + BEGIN), "MIIE", END + Q + ", " + member("b", Q + V + Q) + "}}", "keep: 1"),
            lines('{"' + K + '": {', '  "a": "' + V + '"', "}", "keep: 1"),
            lines("{" + Q + K + Q + ":", "  " + Q + V + Q, "keep: 1"),
            lines(K + ": x " + EK + "{", "  " + member("a", Q + V + Q), "}", "keep: 1"),
            lines(K + ": x " + EK + "[", "  " + Q + V + Q, "]", "keep: 1"),
            lines(K + ': x {"' + K + '": {', '  "a": "' + V + '"', "}", "keep: 1"),
        ):
            with self.subTest(text=text):
                self.assertEqual(filt(text), redact(text))


def normalized_without_comments(text):
    """The text with comment markers removed and white space collapsed."""
    return re.sub(r"\s+", " ", text.replace("#", " "))


class DocsChecks(unittest.TestCase):
    def read(self, name):
        return read_module(name)

    def between(self, source, start, stop):
        """The text of `source` from the line `start` up to the line `stop` (both must exist once)."""
        self.assertEqual(source.count(start), 1, start)
        begin = source.index(start)
        return source[begin : source.index(stop, begin)]

    def function_docstring(self, name):
        for node in ast.parse(self.read("redact_rules.py")).body:
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return normalized_without_comments(ast.get_docstring(node))
        self.fail(name)

    def test_417_r8_the_json_open_object_bullet_names_a_key_written_with_escaped_quotes(self):
        docstring = self.read("redact_filter.py").split('"""')[1]
        bullets = [normalized_without_comments(item) for item in docstring.split("\n- ")]
        bullet = [item for item in bullets if item.startswith("A JSON object or array under a matched key")]
        self.assertEqual(len(bullet), 1)
        self.assertIn("a key written with escaped quotes", bullet[0])

    def test_417_r10_the_block_key_docstring_names_the_json_open_object_state(self):
        self.assertIn(PHRASE, self.function_docstring("block_key"))

    def test_417_r10_the_key_step_docstring_names_the_json_open_object_state(self):
        docstring = self.function_docstring("key_step")
        self.assertIn(PHRASE, docstring)
        self.assertNotIn("for a plain double-quoted key", docstring)

    def test_417_r10_the_state_effect_comment_names_the_json_open_object_state(self):
        source = self.read("redact_rules.py")
        comment = self.between(source, '    if state.rule == "json_open":', "end = matching_bracket(text, start)")
        self.assertIn(PHRASE, normalized_without_comments(comment))

    def test_417_r10_the_key_step_comment_names_the_json_open_object_state(self):
        source = self.read("redact_rules.py")
        comment = self.between(source, '    if kind == "json" and text[start : start + 1] in ("{", "["):', 'rule = "json_open"')
        self.assertIn(PHRASE, normalized_without_comments(comment))


if __name__ == "__main__":
    unittest.main()
