import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import sql_guard  # noqa: E402


def key(operand, value, descending=False, nulls=None):
    return {"operand": operand, "value": value, "descending": descending, "nulls": nulls}


class DiffGuardRefusalTest(unittest.TestCase):
    """`check_diff` refuses with its own messages and keeps the select-mode reasons."""

    def refusal(self, text):
        result, refusal = sql_guard.check_diff(text)
        self.assertIsNone(result, text)
        self.assertIsNotNone(refusal, text)
        return refusal

    def test_the_select_reasons_pass_through(self):
        for text, reason in (
            ("", "empty"), ("SELECT 'x", "unterminated"), ("SELECT 1; SELECT 2", "multiple_statements"),
            ("SELECT 1 INTO t2", "data_modifying"), ("VACUUM t", "not_select"), ("SELECT 1 AS U&\"x\"", "unicode_identifier"),
            ("SELECT pg_advisory_lock(1)", "forbidden_function"), ("SELECT set_config('a', 'b', false)", "forbidden_function"),
        ):
            self.assertEqual(self.refusal(text)["reason"], reason, text)

    def test_a_write_statement_is_write_statement_with_the_diff_message_and_no_static_review(self):
        refusal = self.refusal("UPDATE t SET a = 1")
        self.assertEqual(refusal["reason"], "write_statement")
        self.assertEqual(refusal["message"], "diff takes a SELECT only. A rewrite of a write statement is unproven (story 61).")
        self.assertFalse(refusal["static_review_only"])

    def test_the_messages_name_diff_and_not_select_mode(self):
        self.assertEqual(self.refusal("SELECT 1; SELECT 2")["message"], "diff accepts one statement for each of --a and --b.")
        self.assertEqual(self.refusal("VACUUM t")["message"], "diff accepts only SELECT or WITH ... SELECT.")
        self.assertTrue(self.refusal("VACUUM t")["static_review_only"])
        for text in ("SELECT pg_notify('a', 'b')", "SELECT 1 FROM ts_stat('select 1')"):
            self.assertNotIn("select mode", self.refusal(text)["message"].lower())

    def test_the_string_sql_functions_are_forbidden(self):
        for name in ("query_to_xml", "cursor_to_xml", "query_to_xml_and_xmlschema", "ts_stat", "crosstab", "crosstab2",
                     "connectby", "setval", "QUERY_TO_XML", '"ts_stat"'):
            refusal = self.refusal(f"SELECT {name}('select 1', true, false, '')")
            self.assertEqual(refusal["reason"], "forbidden_function", name)
            self.assertFalse(refusal["static_review_only"])

    def test_a_scan_name_in_a_string_or_a_comment_is_not_a_function(self):
        result, refusal = sql_guard.check_diff("SELECT 'ts_stat' AS a -- crosstab")
        self.assertIsNone(refusal)
        self.assertEqual(result["sql"], "SELECT 'ts_stat' AS a -- crosstab")

    def test_unbalanced_parentheses_are_refused(self):
        for text in ("SELECT (1", "SELECT 1)", "SELECT ) 1 (", "SELECT ((1)", "SELECT 1 FROM (SELECT 2"):
            refusal = self.refusal(text)
            self.assertEqual(refusal["reason"], "unbalanced_parentheses", text)
            self.assertEqual(refusal["message"], "The parentheses of the statement are not balanced.")
            self.assertFalse(refusal["static_review_only"])

    def test_parentheses_in_a_string_or_a_quoted_name_do_not_count(self):
        for text in ("SELECT ')' AS a", "SELECT '(' AS a", 'SELECT 1 AS "a)"', "SELECT $$(($$"):
            self.assertIsNotNone(sql_guard.check_diff(text)[0], text)

    def test_the_text_is_cut_at_its_final_semicolon(self):
        result, _ = sql_guard.check_diff("SELECT 1 ; -- c")
        self.assertEqual(result["sql"], "SELECT 1")

    def test_check_select_and_check_write_are_unchanged_for_a_string_sql_name(self):
        self.assertIsNone(sql_guard.check_select("SELECT ts_stat('select 1')")[1])
        self.assertIsNone(sql_guard.check_select("SELECT (1")[1])


class DiffGuardOrderTest(unittest.TestCase):
    def order(self, text):
        result, refusal = sql_guard.check_diff(text)
        self.assertIsNone(refusal, text)
        return result["order"]

    def test_no_top_level_order_by_is_none(self):
        for text in (
            "SELECT a FROM t",
            "SELECT a FROM (SELECT a FROM t ORDER BY a) AS s",
            "WITH c AS (SELECT a FROM t ORDER BY a) SELECT a FROM c",
            "SELECT a, rank() OVER w FROM t WINDOW w AS (ORDER BY a)",
            "SELECT a, row_number() OVER (ORDER BY a) FROM t",
            "SELECT string_agg(a, ',' ORDER BY a) FROM t",
            "SELECT a FROM t UNION ALL (SELECT a FROM u ORDER BY a LIMIT 1)",
            "SELECT 'order by 1' AS a",
            'SELECT 1 AS "order", 2 AS "by"',
        ):
            self.assertIsNone(self.order(text), text)

    def test_one_key(self):
        self.assertEqual(self.order("SELECT a FROM t ORDER BY a"), {"keys": [key("name", "a")]})

    def test_two_keys_with_desc_and_nulls_last(self):
        self.assertEqual(
            self.order("SELECT a, b FROM t ORDER BY a DESC NULLS LAST, b ASC NULLS FIRST"),
            {"keys": [key("name", "a", True, "last"), key("name", "b", False, "first")]},
        )

    def test_a_position_a_quoted_name_and_a_case_folded_word(self):
        self.assertEqual(
            self.order('SELECT a, "B c" FROM t ORDER BY 2, "B c" DESC, ABC'),
            {"keys": [key("position", 2), key("name", "B c", True), key("name", "abc")]},
        )

    def test_a_limit_offset_or_fetch_after_the_keys_ends_them(self):
        for tail in ("LIMIT 3", "OFFSET 2", "FETCH FIRST 2 ROWS ONLY", "LIMIT 3 OFFSET 1"):
            self.assertEqual(self.order(f"SELECT a FROM t ORDER BY a {tail}"), {"keys": [key("name", "a")]}, tail)

    def test_an_order_by_after_a_union_at_depth_zero_counts(self):
        self.assertEqual(self.order("SELECT a FROM t UNION SELECT a FROM u ORDER BY 1"), {"keys": [key("position", 1)]})

    def test_a_key_that_is_not_one_operand_is_unextractable(self):
        for text in (
            "SELECT a FROM t ORDER BY a + 1",
            "SELECT a FROM t ORDER BY lower(a)",
            "SELECT a FROM t ORDER BY t.a",
            "SELECT a FROM t ORDER BY a USING <",
            "SELECT a FROM t ORDER BY a COLLATE \"C\"",
            "SELECT a FROM t ORDER BY a, b + 1",
            "SELECT a FROM t ORDER BY 'x'",
            "SELECT a FROM t ORDER BY $1",
            "SELECT a FROM t ORDER BY a DESC DESC",
            "SELECT a FROM t ORDER BY a NULLS",
            "SELECT a FROM t ORDER BY 1.5",
        ):
            order = self.order(text)
            self.assertEqual(list(order), ["unextractable"], text)
            self.assertIsInstance(order["unextractable"], str, text)

    def test_a_second_top_level_order_by_is_unextractable(self):
        order = self.order("SELECT a FROM t ORDER BY a UNION SELECT a FROM u ORDER BY a")
        self.assertEqual(list(order), ["unextractable"])


if __name__ == "__main__":
    unittest.main()
