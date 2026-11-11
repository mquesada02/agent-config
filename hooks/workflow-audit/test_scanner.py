import importlib.machinery
import importlib.util
import os
import sys
import unittest

AUDIT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit")


def _audit():
    """The audit script as a module: it has no `.py` extension, and its `__main__` guard makes the load safe. No `.pyc` is written."""
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        loader = importlib.machinery.SourceFileLoader("audit_for_scanner", AUDIT)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = previous


audit = _audit()


class UnitsTest(unittest.TestCase):
    def kinds(self, text, **options):
        return [(kind, text[start:end], closed) for kind, start, end, closed in audit._units(text, **options)]

    def test_each_unit_kind(self):
        self.assertEqual(self.kinds("a \\b 'c' \"d\" `e` $(f) #g"), [
            ("char", "a", True), ("char", " ", True), ("escape", "\\b", True), ("char", " ", True), ("single", "'c'", True),
            ("char", " ", True), ("double", '"d"', True), ("char", " ", True), ("backtick", "`e`", True), ("char", " ", True),
            ("paren", "$(f)", True), ("char", " ", True), ("comment", "#g", True)])

    def test_a_hash_inside_a_word_is_no_comment(self):
        self.assertEqual([kind for kind, _, _ in self.kinds("a#b")], ["char", "char", "char"])

    def test_a_hash_after_a_parenthesis_or_a_separator_is_a_comment(self):
        for text in ("(#a", ";#a", "|#a", "&#a"):
            with self.subTest(text=text):
                self.assertEqual(self.kinds(text)[1][0], "comment")

    def test_a_hash_after_a_substitution_is_no_comment(self):
        self.assertEqual(self.kinds("$(a)#b")[-1][0], "char")

    def test_a_unit_that_is_not_closed_raises_or_runs_to_the_end_when_tolerant(self):
        for text, kind in (("'a", "single"), ('"a', "double"), ("`a", "backtick"), ("$(a", "paren")):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    list(audit._units(text))
                self.assertEqual(self.kinds(text, tolerant=True), [(kind, text, False)])


class JoinAsBashTest(unittest.TestCase):
    def test_a_continued_line_is_joined_outside_single_quotes_and_comments(self):
        self.assertEqual(audit._join_as_bash("echo 'a\\\nb' \"c\\\nd\" e\\\nf # g\\\nh"), "echo 'a\\\nb' \"cd\" ef # g\\\nh")

    def test_an_escaped_backslash_does_not_join(self):
        self.assertEqual(audit._join_as_bash("a\\\\\nb"), "a\\\\\nb")

    def test_a_unit_that_is_not_closed_runs_to_the_end(self):
        self.assertEqual(audit._join_as_bash('echo "a\\\nb'), 'echo "ab')
        self.assertEqual(audit._join_as_bash("$(a\\\nb"), "$(ab")
        self.assertEqual(audit._join_as_bash("'a\\\nb"), "'a\\\nb")

    def test_a_continued_line_leaves_the_start_of_a_word_as_it_was(self):
        self.assertEqual(audit._join_as_bash("a \\\n#b\\\nc"), "a #b\\\nc")

    def test_a_comment_in_a_backtick_body_ends_at_the_closing_backtick(self):
        self.assertEqual(audit._join_as_bash("`a #b\\\nc`d\\\ne"), "`a #b\\\nc`de")

    def test_case_b_a_quote_in_a_backtick_body_does_not_reach_past_the_closing_backtick(self):
        # Changed by #209 (owner decision): the old join scanned flat, so the quote ran past the backtick and kept the continued line.
        self.assertEqual(audit._join_as_bash("`'`\\\n"), "`'`")


    def test_case_c_a_hash_after_a_parenthesis_in_a_backtick_body_in_a_substitution_is_a_comment(self):
        # Changed by #209 (owner decision): the old join scanned flat, so the `)` closed the `$(` and the `#` was plain text.
        self.assertEqual(audit._join_as_bash("$(`)#a\\\nb`)"), "$(`)#a\\\nb`)")


class ParenEndTest(unittest.TestCase):
    def test_the_end_follows_parentheses_quotes_substitutions_and_comments(self):
        self.assertEqual(audit._paren_end("a (b) ')' \")\" $(c)) d", 0), 19)
        self.assertEqual(audit._paren_end("a #)\n)", 0), 6)

    def test_a_missing_close_raises(self):
        with self.assertRaises(ValueError):
            audit._paren_end("a (b)", 0)

    def test_case_a_a_continued_line_before_a_hash_leaves_it_a_comment(self):
        # Changed by #209 (owner decision): the old scan took the `#` after a backslash-newline for plain text, so the `)` ended the body.
        self.assertEqual(audit._paren_end("a \\\n#)\n)", 0), 8)


class MaskSubstitutionsTest(unittest.TestCase):
    def test_substitutions_are_masked_and_comments_dropped(self):
        masked, marker, substitutions = audit._mask_substitutions("a $(b) 'c' # d\n`e\\`f`")
        self.assertEqual(masked, f"a {marker}0{marker} 'c' \n{marker}1{marker}")
        self.assertEqual(substitutions, [("$(b)", "b"), ("`e\\`f`", "e`f")])

    def test_case_a_a_continued_line_before_a_hash_leaves_it_a_comment(self):
        # Changed by #209 (owner decision): the old scan kept `#c` as plain text.
        self.assertEqual(audit._mask_substitutions("x \\\n#c")[0], "x \\\n")
        self.assertEqual(audit.split_command("x \\\n#c"), [["x"], "\n"])


if __name__ == "__main__":
    unittest.main()
