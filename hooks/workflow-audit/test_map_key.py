# Issue #138: `record --pre-dispatch --map` takes a GitHub issue number or a Linear key, and the brief and CLAUDE.md say so.
import unittest

from test_brief import read_brief
from test_claude_md import ROOT_CLAUDE_MD, read
from test_pre_dispatch import PreDispatchCase


class LinearKeyTest(PreDispatchCase):
    def test_a_linear_key_is_accepted_and_recorded_as_text(self):
        for key in ("ENG-42", "A-1", "ENG2-123", "ABCDEFGHIJ-999999999"):
            with self.subTest(key=key):
                self.setUp()
                result = self.pre_dispatch(map_issue=key)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.read_pre_dispatch()["map"], key)

    def test_a_github_number_is_still_recorded_as_an_integer(self):
        self.assertEqual(self.pre_dispatch(map_issue="82").returncode, 0)
        self.assertEqual(self.read_pre_dispatch()["map"], 82)

    def test_a_bad_linear_key_is_refused(self):
        for key in ("eng-42", "ENG-0", "ENG-042", "ENG42", "-42", "ENG-", "1ENG-42", "ENG_42", "ENG-42 ", "ABCDEFGHIJK-1",
                    "ENG-1234567890", "ＥＮＧ-42"):
            with self.subTest(key=key):
                result = self.pre_dispatch(map_issue=key)
                self.assert_nothing_written(result)
                self.assertIn(b"bad --map", result.stderr)

    def test_the_refusal_names_both_forms(self):
        result = self.pre_dispatch(map_issue="abc")
        self.assertIn(b"GitHub issue number", result.stderr)
        self.assertIn(b"Linear key", result.stderr)


class MapTextTest(unittest.TestCase):
    def test_the_brief_says_which_form_to_pass(self):
        variant = read_brief().partition("## Pre-dispatch variant")[2]
        for phrase in ("GitHub issue number (for example `309`)", "Linear key (for example `ENG-42`)"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, variant)

    def test_claude_md_says_the_map_is_an_issue_number_or_a_linear_key(self):
        self.assertIn("`--map` takes the map's GitHub issue number or its Linear key", read(ROOT_CLAUDE_MD))


if __name__ == "__main__":
    unittest.main()
