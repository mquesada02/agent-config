import importlib.machinery
import importlib.util
import os
import sys
import unittest

AUDIT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit")


def _audit():
    """The audit script as a module, read as data (no `.pyc` is written)."""
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        loader = importlib.machinery.SourceFileLoader("audit_for_api_options", AUDIT)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = previous


audit = _audit()


def values(arguments, short, long):
    return list(audit._api_option_values(arguments.split(), short, long))


class OptionValuesTest(unittest.TestCase):
    def test_every_spelling_of_an_option_gives_its_value(self):
        self.assertEqual(values("-H a:b", "-H", "--header"), ["a:b"])
        self.assertEqual(values("--header a:b", "-H", "--header"), ["a:b"])
        self.assertEqual(values("--header=a:b", "-H", "--header"), ["a:b"])
        self.assertEqual(values("-Ha:b", "-H", "--header"), ["a:b"])
        self.assertEqual(values("-H=a:b", "-H", "--header"), ["a:b"])
        self.assertEqual(values("-XPOST", "-X", "--method"), ["POST"])

    def test_the_values_come_in_order_and_a_missing_value_is_empty(self):
        self.assertEqual(values("-X GET --method=POST -X", "-X", "--method"), ["GET", "POST", ""])

    def test_the_reading_is_flat_a_value_of_another_option_is_still_seen(self):
        self.assertEqual(values("-q -H $x:y", "-H", "--header"), ["$x:y"])
        self.assertEqual(values("-X -X POST", "-X", "--method"), ["-X", "POST"])

    def test_the_value_after_a_method_option_may_be_the_dashes_and_the_dashes_end_the_options(self):
        self.assertEqual(values("-X -- -H a:b", "-X", "--method"), ["--"])
        self.assertEqual(values("-- -H a:b", "-H", "--header"), [])

    def test_the_other_options_are_not_read(self):
        self.assertEqual(values("--hostname h --input f -f a=b", "-H", "--header"), [])


class MethodTest(unittest.TestCase):
    def method(self, arguments):
        return audit._api_method(arguments.split())

    def test_the_last_method_wins_and_is_upper_case(self):
        self.assertEqual(self.method("-X get --method=post"), "POST")
        self.assertEqual(self.method("-XPATCH user"), "PATCH")

    def test_a_field_or_an_input_implies_post_and_a_method_wins(self):
        self.assertEqual(self.method("user -f a=b"), "POST")
        self.assertEqual(self.method("user --input f"), "POST")
        self.assertEqual(self.method("user -X GET -f a=b"), "GET")

    def test_no_option_is_a_get_and_the_dashes_end_the_options(self):
        self.assertEqual(self.method("user"), "GET")
        self.assertEqual(self.method("-- -X POST"), "GET")
        self.assertEqual(self.method("-X"), "GET")
        self.assertEqual(self.method("-X -- user"), "--")


class OverrideTest(unittest.TestCase):
    def denied(self, text):
        segment = ["gh", "api", *text.split()]
        return audit._denies_api_override(segment)

    def test_a_header_name_that_a_variable_or_a_substitution_builds_is_denied_in_every_spelling(self):
        for text in ("-H $h:v user", "--header $h:v user", "--header=$h:v user", "-H$h:v user", "-q -H $h:v user", "-f -H $h:v user"):
            with self.subTest(text=text):
                self.assertTrue(self.denied(text))

    def test_the_override_name_is_denied_in_any_case(self):
        self.assertTrue(self.denied("-H X-Http-Method-Override:PUT user"))

    def test_another_header_is_allowed(self):
        self.assertFalse(self.denied("-H Accept:json user"))


class ShapeTest(unittest.TestCase):
    """An unparsable text is denied when its `gh api` form can reach the gated word within the reach (`API_TEXT_REACH`), and not otherwise."""

    def gate(self, command):
        return audit.gate_reason(command, os.getcwd())

    def test_an_unparsable_gh_api_call_that_names_pulls_within_the_reach_is_denied(self):
        # The last filler is the longest one that still leaves the gated word and the closing quote inside the reach.
        for filler in (0, 1, audit.API_TEXT_REACH - len(" pulls") - len(" '")):
            with self.subTest(filler=filler):
                self.assertEqual(self.gate(f"gh api {'x' * filler} pulls '"), audit.API_FORM.unparsable_reason)

    def test_an_unparsable_gh_api_call_that_reaches_the_limit_is_denied_even_with_no_gated_word(self):
        self.assertEqual(self.gate(f"gh api {'x' * audit.API_TEXT_REACH}'"), audit.API_FORM.unparsable_reason)

    def test_an_unparsable_gh_api_call_that_names_no_gated_word_within_the_reach_is_allowed(self):
        self.assertIsNone(self.gate("gh api user '"))
        self.assertIsNone(self.gate(f"gh api {'x' * (audit.API_TEXT_REACH - 2)}'"))

    def test_an_unparsable_gh_api_call_with_the_override_header_within_the_reach_is_denied(self):
        for filler in (0, 1, audit.API_TEXT_REACH - len(" x-http-method-override") - len(" '")):
            with self.subTest(filler=filler):
                self.assertEqual(self.gate(f"gh api {'x' * filler} x-http-method-override '"), audit.API_OVERRIDE_FORM.unparsable_reason)

    def test_an_unparsable_gh_api_call_with_the_override_header_beyond_the_reach_is_denied_by_the_pulls_form_only(self):
        """The override form reads no further than the reach; the pulls form denies the call because it reaches its own limit."""
        self.assertEqual(self.gate(f"gh api {'x' * audit.API_TEXT_REACH} x-http-method-override '"), audit.API_FORM.unparsable_reason)

    def test_the_head_is_all_the_words_of_a_plain_call_and_none_for_another_command(self):
        self.assertEqual(audit._api_whole_head(["gh", "api", "user"]), ["gh", "api", "user"])
        self.assertIsNone(audit._api_whole_head(["gh", "pr", "view"]))
        self.assertIsNone(audit._api_whole_head(["bash", "-c", "gh api user"]))


if __name__ == "__main__":
    unittest.main()
