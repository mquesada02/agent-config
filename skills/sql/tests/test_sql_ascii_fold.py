import ast
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SKILL, "scripts"))

import sql_guard  # noqa: E402

GUARD_PATH = os.path.join(SKILL, "scripts", "sql_guard.py")
DB_ACCESS_PATH = os.path.join(SKILL, "db-access.md")

LONG_S = "ſ"
DOTLESS_I = "ı"
KELVIN = "K"
NBSP = " "
WRITE_INSERT = "INSERT INTO t VALUES (1) RETURNING 1 AS a"


def _reason(result):
    """The refusal reason of `(result, refusal)`, or None when the text is accepted."""
    _, refusal = result
    return refusal["reason"] if refusal else None


class CaseFoldTest(unittest.TestCase):
    """The guard folds case with ASCII rules only, as the PostgreSQL scanner does."""

    def test_a_long_s_first_word_is_not_select_in_select_mode_and_diff(self):
        text = f"{LONG_S}elect 1"
        self.assertEqual(_reason(sql_guard.check_select(text)), "not_select")
        self.assertEqual(_reason(sql_guard.check_select_scan(text)), "not_select")
        self.assertEqual(_reason(sql_guard.check_diff(text)), "not_select")

    def test_a_long_s_first_word_is_not_write_in_write_mode(self):
        self.assertEqual(_reason(sql_guard.check_write(f"{LONG_S}elect 1")), "not_write")

    def test_a_long_s_name_is_an_ordinary_identifier(self):
        for text in (f"SELECT 1 AS {LONG_S}elect", f"SELECT {LONG_S}et_config('a', 'b', false)"):
            for check in (sql_guard.check_select, sql_guard.check_diff):
                with self.subTest(text=text, check=check.__name__):
                    self.assertIsNone(_reason(check(text)))
        self.assertIsNone(_reason(sql_guard.check_write(f"INSERT INTO t VALUES ({LONG_S}et_config('a', 'b', false))")))

    def test_a_dotless_i_first_word_is_not_write_in_select_mode_and_diff(self):
        text = f"{DOTLESS_I}nsert into t values (1)"
        self.assertEqual(_reason(sql_guard.check_select(text)), "not_select")
        self.assertEqual(_reason(sql_guard.check_diff(text)), "not_select")

    def test_a_dotless_i_first_word_is_not_write_in_write_mode(self):
        self.assertEqual(_reason(sql_guard.check_write(f"{DOTLESS_I}nsert into t values (1)")), "not_write")

    def test_a_dotless_i_main_word_after_a_with_list(self):
        text = f"WITH x AS (SELECT 1) {DOTLESS_I}nsert INTO t SELECT 1"
        self.assertEqual(_reason(sql_guard.check_write(text)), "not_write")
        self.assertEqual(_reason(sql_guard.check_select(text)), "data_modifying")
        self.assertEqual(_reason(sql_guard.check_diff(text)), "data_modifying")

    def test_a_kelvin_sign_name_is_not_dblink(self):
        text = f"SELECT dblin{KELVIN}('x')"
        self.assertIsNone(_reason(sql_guard.check_select(text)))
        result, refusal = sql_guard.check_select_scan(text)
        self.assertIsNone(refusal)
        self.assertEqual(result["scan"], [])
        self.assertIsNone(_reason(sql_guard.check_diff(text)))
        result, refusal = sql_guard.check_write(f"INSERT INTO t VALUES (dblin{KELVIN}('x'))")
        self.assertIsNone(refusal)
        self.assertEqual(result["scan"], [])

    def test_the_ascii_dblink_is_still_refused(self):
        self.assertEqual(_reason(sql_guard.check_select("SELECT dblink('x')")), "forbidden_function")
        self.assertEqual(_reason(sql_guard.check_diff("SELECT dblink('x')")), "forbidden_function")
        self.assertEqual(_reason(sql_guard.check_select("SELECT DBLINK('x')")), "forbidden_function")


class BlankCutTest(unittest.TestCase):
    """The cut of the sent text strips only the blanks of every supported PostgreSQL scanner."""

    def sent(self, check, text):
        result, refusal = check(text)
        self.assertIsNone(refusal, text)
        return result if isinstance(result, str) else result["sql"]

    def test_blanks_is_the_set_that_is_blank_on_every_supported_version(self):
        self.assertEqual(sql_guard.BLANKS, " \t\n\r\f")

    def test_a_trailing_no_break_space_is_kept_in_select_mode_and_diff(self):
        text = f"SELECT 1 AS a{NBSP}"
        self.assertEqual(self.sent(sql_guard.check_select, text), text)
        self.assertEqual(self.sent(sql_guard.check_diff, text), text)
        self.assertEqual(self.sent(sql_guard.check_select_scan, text), text)

    def test_a_trailing_no_break_space_is_kept_in_write_mode(self):
        text = f"{WRITE_INSERT}{NBSP}"
        self.assertEqual(self.sent(sql_guard.check_write, text), text)

    def test_the_blanks_of_the_scanner_are_stripped_at_both_ends(self):
        for blank in (" ", "\t", "\n", "\r", "\f"):
            with self.subTest(blank=repr(blank)):
                self.assertEqual(self.sent(sql_guard.check_select, f"{blank}SELECT 1{blank};"), "SELECT 1")
                self.assertEqual(self.sent(sql_guard.check_diff, f"{blank}SELECT 1{blank}"), "SELECT 1")
                self.assertEqual(self.sent(sql_guard.check_write, f"{blank}{WRITE_INSERT}{blank}"), WRITE_INSERT)

    def test_a_vertical_tab_at_the_edge_is_kept_in_every_mode(self):
        for text, check in (
            ("SELECT 1 AS a\v", sql_guard.check_select),
            ("SELECT 1 AS a\v", sql_guard.check_diff),
            ("\vSELECT 1", sql_guard.check_select),
            (f"{WRITE_INSERT}\v", sql_guard.check_write),
        ):
            with self.subTest(text=text, check=check.__name__):
                self.assertEqual(self.sent(check, text), text)

    def test_a_leading_no_break_space_makes_the_first_word_not_a_keyword(self):
        text = f"{NBSP}SELECT 1"
        self.assertEqual(_reason(sql_guard.check_select(text)), "not_select")
        self.assertEqual(_reason(sql_guard.check_diff(text)), "not_select")
        self.assertEqual(_reason(sql_guard.check_write(text)), "not_write")

    def test_the_tokenizer_still_skips_the_vertical_tab_between_tokens(self):
        self.assertEqual(self.sent(sql_guard.check_select, "SELECT 1\f,\v2"), "SELECT 1\f,\v2")


class SourceRuleTest(unittest.TestCase):
    """The file has no Unicode-aware string call: one `ast` walk over it."""

    BANNED = {"upper", "lower", "casefold", "strip", "lstrip", "rstrip", "isspace", "isalpha", "isalnum", "isidentifier", "isdigit"}
    HELPERS = {"_ascii_upper", "_ascii_lower"}

    def test_no_unicode_aware_call_remains_outside_the_two_helpers(self):
        with open(GUARD_PATH, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        found = []

        def visit(node, function):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function = node.name
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in self.BANNED:
                is_helper = function in self.HELPERS and node.func.attr in ("upper", "lower")
                is_cut = (
                    node.func.attr == "strip" and len(node.args) == 1 and not node.keywords
                    and isinstance(node.args[0], ast.Name) and node.args[0].id == "BLANKS"
                )
                if not (is_helper or is_cut):
                    found.append((node.lineno, node.func.attr))
            if isinstance(node, ast.Name) and node.id == "IGNORECASE":
                found.append((node.lineno, "IGNORECASE"))
            if isinstance(node, ast.Attribute) and node.attr == "IGNORECASE":
                found.append((node.lineno, "IGNORECASE"))
            for child in ast.iter_child_nodes(node):
                visit(child, function)

        visit(tree, None)
        self.assertEqual(found, [])

    def test_the_comment_above_blanks_quotes_the_versions(self):
        with open(GUARD_PATH, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        index = next(i for i, line in enumerate(lines) if line.startswith("BLANKS = "))
        comment = []
        for line in reversed(lines[:index]):
            if not line.startswith("#"):
                break
            comment.append(line)
        text = "\n".join(comment)
        for phrase in ("scan.l", "13 to 16", "17 and 18"):
            self.assertIn(phrase, text)


class DocumentRuleTest(unittest.TestCase):
    """`db-access.md` states the closed divergences as closed and keeps the open risks."""

    def setUp(self):
        with open(DB_ACCESS_PATH, encoding="utf-8") as handle:
            self.text = handle.read()

    def test_the_closed_divergences_are_gone(self):
        for phrase in ("Unicode case fold, Unicode blanks", "a Unicode blank that", "the case fold of a letter"):
            self.assertNotIn(phrase, self.text)

    def test_the_open_risks_are_named(self):
        for phrase in ("vertical tab", "single-byte", "Unicode"):
            self.assertIn(phrase, self.text)

    def test_the_case_bullet_names_the_three_modes(self):
        bullet = re.search(r"^- the guard reads the case of a word[^\n]*$", self.text, re.M)
        self.assertIsNotNone(bullet)
        for phrase in ("select mode", "write mode", "diff"):
            self.assertIn(phrase, bullet.group())


if __name__ == "__main__":
    unittest.main()
