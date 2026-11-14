import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import sql_guard  # noqa: E402


def key(operand, value, descending=False, nulls=None, collation=None, using=None):
    return {
        "operand": operand, "value": value, "descending": descending, "nulls": nulls,
        "collation": collation, "using": using,
    }


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
        for name in ("query_to_xml", "cursor_to_xml", "query_to_xml_and_xmlschema", "ts_stat", "ts_rewrite", "crosstab", "crosstab2",
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

    def test_collate_reads_a_word_folded_or_a_quoted_name_exact_and_makes_the_key_a_reference(self):
        self.assertEqual(
            self.order('SELECT a FROM t ORDER BY a COLLATE "C"'), {"keys": [key("ref", ["a"], collation="C")]}
        )
        self.assertEqual(
            self.order("SELECT a FROM t ORDER BY a COLLATE Und"), {"keys": [key("ref", ["a"], collation="und")]}
        )
        self.assertEqual(
            self.order('SELECT a FROM t ORDER BY a COLLATE "a ""b"""'), {"keys": [key("ref", ["a"], collation='a "b"')]}
        )

    def test_using_less_and_greater_are_read_and_default_nulls_follow_them_in_the_key(self):
        self.assertEqual(self.order("SELECT a FROM t ORDER BY a USING >"), {"keys": [key("name", "a", True, None, None, ">")]})
        self.assertEqual(self.order("SELECT a FROM t ORDER BY 1 USING <"), {"keys": [key("position", 1, False, None, None, "<")]})
        self.assertEqual(
            self.order("SELECT a FROM t ORDER BY a USING > NULLS LAST"), {"keys": [key("name", "a", True, "last", None, ">")]}
        )

    def test_a_qualified_name_is_a_reference_with_its_parts_folded_or_exact(self):
        self.assertEqual(self.order("SELECT u.a FROM u ORDER BY u.a"), {"keys": [key("ref", ["u", "a"])]})
        self.assertEqual(
            self.order('SELECT 1 FROM u ORDER BY S.U.A DESC, "S"."u"."A b"'),
            {"keys": [key("ref", ["s", "u", "a"], True), key("ref", ["S", "u", "A b"])]},
        )

    def test_the_combined_form(self):
        self.assertEqual(
            self.order('SELECT u.name FROM u ORDER BY u.name COLLATE "C" DESC NULLS LAST'),
            {"keys": [key("ref", ["u", "name"], True, "last", "C")]},
        )

    def test_forms_that_stay_unextractable(self):
        for text in (
            'SELECT a FROM t ORDER BY a COLLATE pg_catalog."C"',
            'SELECT a FROM t ORDER BY 1 COLLATE "C"',
            "SELECT a FROM t ORDER BY a COLLATE",
            "SELECT a FROM t ORDER BY a USING <=",
            "SELECT a FROM t ORDER BY a USING <>",
            "SELECT a FROM t ORDER BY a USING OPERATOR(pg_catalog.<)",
            "SELECT a FROM t ORDER BY a USING",
            "SELECT a FROM t ORDER BY a USING < DESC",
            "SELECT a FROM t ORDER BY a DESC USING <",
            "SELECT a FROM t ORDER BY d.s.t.a",
            "SELECT a FROM t ORDER BY t.",
            "SELECT a FROM t ORDER BY t..a",
            "SELECT a FROM t ORDER BY t.*",
            "SELECT a FROM t ORDER BY a COLLATE \"C\" COLLATE \"C\"",
            "SELECT a FROM t ORDER BY NULLS FIRST",
        ):
            self.assertEqual(list(self.order(text)), ["unextractable"], text)


class DiffGuardItemsTest(unittest.TestCase):
    def items(self, text):
        result, refusal = sql_guard.check_diff(text)
        self.assertIsNone(refusal, text)
        return result["items"]

    def test_there_are_no_items_when_there_is_no_order_by_or_it_is_unextractable(self):
        self.assertIsNone(self.items("SELECT a FROM t"))
        self.assertIsNone(self.items("SELECT a FROM t ORDER BY a + 1"))

    def test_plain_references_with_and_without_an_alias(self):
        self.assertEqual(
            self.items('SELECT u.a, u.b AS B2, u.c d, "X".y AS "Z z", e FROM u ORDER BY 1'),
            [
                {"ref": ["u", "a"], "name": "a"}, {"ref": ["u", "b"], "name": "b2"}, {"ref": ["u", "c"], "name": "d"},
                {"ref": ["X", "y"], "name": "Z z"}, {"ref": ["e"], "name": "e"},
            ],
        )

    def test_an_item_that_is_not_a_plain_reference_has_no_ref_and_no_name(self):
        expression = {"ref": None, "name": None}
        self.assertEqual(
            self.items('SELECT a + 1, lower(a) AS l, a COLLATE "C", a::text, d.s.t.a FROM t ORDER BY 1'),
            [expression, expression, expression, expression, expression],
        )

    def test_distinct_distinct_on_all_and_with_are_skipped_or_ignored(self):
        want = [{"ref": ["a"], "name": "a"}, {"ref": ["b"], "name": "b"}]
        for text in (
            "SELECT DISTINCT a, b FROM t ORDER BY 1",
            "SELECT ALL a, b FROM t ORDER BY 1",
            "SELECT DISTINCT ON (a, b) a, b FROM t ORDER BY 1",
            "WITH c AS (SELECT x, y, z FROM t) SELECT a, b FROM c ORDER BY 1",
            "SELECT a, b ORDER BY 1",
        ):
            self.assertEqual(self.items(text), want, text)

    def test_star_forms_and_set_operations_and_a_missing_select_give_no_items(self):
        for text in (
            "SELECT * FROM t ORDER BY 1", "SELECT t.* FROM t ORDER BY 1", "SELECT a, (t).* FROM t ORDER BY 1",
            "SELECT a FROM t UNION SELECT a FROM u ORDER BY 1", "SELECT a FROM t EXCEPT SELECT a FROM u ORDER BY 1",
            "WITH c AS (SELECT 1) SELECT * FROM c ORDER BY 1", "WITH c AS (SELECT 1) SELECT a FROM c UNION ALL SELECT 2 ORDER BY 1",
        ):
            self.assertIsNone(self.items(text), text)

    def test_commas_in_brackets_and_in_parentheses_do_not_split_items(self):
        got = self.items('SELECT ARRAY[a, b], c, d IS DISTINCT FROM e AS c, f(a, b) AS g FROM t ORDER BY c COLLATE "C"')
        self.assertEqual(
            got,
            [{"ref": None, "name": None}, {"ref": ["c"], "name": "c"}, {"ref": None, "name": None}, {"ref": None, "name": None}],
        )

    def test_within_group_and_is_distinct_from_do_not_end_the_list(self):
        got = self.items("SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY x) AS m, a FROM t GROUP BY a ORDER BY 1")
        self.assertEqual(got, [{"ref": None, "name": None}, {"ref": ["a"], "name": "a"}])

    def test_a_label_that_is_an_end_word_only_drops_or_corrupts_the_tail(self):
        early = self.items("SELECT a, b AS order, c FROM t ORDER BY 1")
        self.assertEqual(early, [{"ref": ["a"], "name": "a"}, {"ref": None, "name": None}])
        late = self.items("SELECT a, c AS distinct FROM t ORDER BY 1")
        self.assertEqual(late[0], {"ref": ["a"], "name": "a"})
        self.assertEqual(self.items("SELECT DISTINCT FROM t ORDER BY 1"), [])

    def test_a_postfix_keyword_is_read_as_an_alias(self):
        self.assertEqual(self.items("SELECT u.a ISNULL FROM u ORDER BY 1"), [{"ref": ["u", "a"], "name": "isnull"}])


if __name__ == "__main__":
    unittest.main()
