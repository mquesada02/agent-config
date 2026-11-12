import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import sql_guard  # noqa: E402

LISTED = (
    "query_to_xml", "query_to_xml_and_xmlschema", "query_to_xmlschema", "cursor_to_xml", "cursor_to_xmlschema",
    "ts_stat", "ts_rewrite", "crosstab", "crosstab2", "crosstab4", "connectby",
)


class SelectScanTest(unittest.TestCase):
    """`check_select_scan` names the string-SQL functions of a statement that `check_select` accepts."""

    def scan(self, text):
        result, refusal = sql_guard.check_select_scan(text)
        self.assertIsNone(refusal, text)
        return result["scan"]

    def test_each_listed_function_is_found(self):
        for name in LISTED:
            with self.subTest(name=name):
                self.assertEqual(self.scan(f"SELECT {name}('select 1')"), [name])

    def test_the_result_has_the_checked_sql_and_the_scan(self):
        result, refusal = sql_guard.check_select_scan("SELECT query_to_xml('select 1', true, true, ''); ")
        self.assertIsNone(refusal)
        self.assertEqual(sorted(result), ["scan", "sql"])
        self.assertEqual(result["sql"], "SELECT query_to_xml('select 1', true, true, '')")

    def test_the_shapes_of_a_name(self):
        for text, expected in (
            ("SELECT QUERY_TO_XML('x', true, true, '')", ["query_to_xml"]),
            ('SELECT "Query_To_Xml"(\'x\')', ["query_to_xml"]),
            ("SELECT pg_catalog.ts_stat('x')", ["ts_stat"]),
            ("WITH q AS (SELECT connectby('t', 'a', 'b', 'c', 1)) SELECT * FROM q", ["connectby"]),
            ("SELECT * FROM crosstab('select 1') AS ct(a int)", ["crosstab"]),
        ):
            with self.subTest(text=text):
                self.assertEqual(self.scan(text), expected)

    def test_the_scan_is_sorted_and_has_no_duplicates(self):
        text = "SELECT ts_stat('a'), query_to_xml('b', true, true, ''), ts_stat('c'), TS_STAT('d')"
        self.assertEqual(self.scan(text), ["query_to_xml", "ts_stat"])

    def test_a_name_in_a_string_a_comment_or_a_dollar_quote_is_not_found(self):
        for text in (
            "SELECT 'query_to_xml'",
            "SELECT 1 -- ts_stat('x')",
            "SELECT 1 /* crosstab('x') */",
            "SELECT $q$connectby$q$",
            "SELECT E'cursor_to_xml'",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.scan(text), [])

    def test_a_statement_with_no_listed_function_has_an_empty_scan(self):
        for text in ("SELECT 1", "SELECT lower(a) FROM t", "SELECT xcrosstab"):
            with self.subTest(text=text):
                self.assertEqual(self.scan(text), [])

    def test_a_name_that_starts_with_a_listed_prefix_is_found(self):
        self.assertEqual(self.scan("SELECT query_to_xmlx"), ["query_to_xmlx"])

    def test_a_refusal_of_check_select_passes_through_unchanged(self):
        for text in (
            "", "SELECT 'x", "SELECT 1; SELECT 2", "UPDATE t SET a = 1", "VACUUM t", "SELECT 1 INTO t2",
            "SELECT dblink_exec(1)", "SELECT 1 AS U&\"x\"",
        ):
            with self.subTest(text=text):
                result, refusal = sql_guard.check_select_scan(text)
                self.assertIsNone(result)
                self.assertEqual((None, refusal), sql_guard.check_select(text))

    def test_a_direct_forbidden_call_next_to_a_listed_function_is_still_refused(self):
        for forbidden in ("dblink_exec(1)", "set_config('a', 'b', false)", "pg_notify('c', 'p')", "lo_export(1, 'f')",
                          "pg_advisory_lock(1)", "pg_try_advisory_lock(1)"):
            text = f"SELECT query_to_xml('select 1', true, true, ''), {forbidden}"
            with self.subTest(text=text):
                result, refusal = sql_guard.check_select_scan(text)
                self.assertIsNone(result)
                self.assertEqual(refusal["reason"], "forbidden_function")

    def test_a_forbidden_name_in_the_text_argument_is_accepted_and_downgraded(self):
        text = "SELECT query_to_xml('SELECT dblink_exec(1)', true, true, '')"
        self.assertEqual(self.scan(text), ["query_to_xml"])
        self.assertEqual(sql_guard.check_select(text)[1], None)


class ScanListsTest(unittest.TestCase):
    """The split of the scan lists keeps the members of write mode and `diff`."""

    def test_the_scan_sets_hold_the_listed_names(self):
        self.assertEqual(sql_guard.SCAN_NAMES, frozenset(["lo_export", "setval", "ts_stat", "ts_rewrite", "connectby"]))
        self.assertEqual(set(sql_guard.SCAN_PREFIXES), {"dblink", "query_to_xml", "cursor_to_xml", "crosstab"})

    def test_the_string_sql_lists_are_a_subset_without_the_effect_names(self):
        self.assertEqual(sql_guard.STRING_SQL_NAMES, frozenset(["ts_stat", "ts_rewrite", "connectby"]))
        self.assertEqual(set(sql_guard.STRING_SQL_PREFIXES), {"query_to_xml", "cursor_to_xml", "crosstab"})

    def test_write_mode_and_diff_keep_their_results(self):
        result, refusal = sql_guard.check_write("UPDATE t SET a = query_to_xml('x', true, true, '') IS NULL")
        self.assertIsNone(refusal)
        self.assertEqual(result["scan"], ["query_to_xml"])
        result, refusal = sql_guard.check_write("UPDATE t SET a = 1 WHERE lo_export(1, 'f') > 0 AND setval('s', 1) > 0")
        self.assertEqual(result["scan"], ["lo_export", "setval"])
        for name in ("ts_stat", "ts_rewrite", "crosstab", "connectby", "query_to_xml", "cursor_to_xml"):
            with self.subTest(name=name):
                result, refusal = sql_guard.check_diff(f"SELECT {name}('x')")
                self.assertIsNone(result)
                self.assertEqual(refusal["reason"], "forbidden_function")

    def test_ts_rewrite_in_both_forms_is_found_in_select_mode_and_write_mode_and_refused_by_diff(self):
        for call in ("ts_rewrite('a'::tsquery, 'SELECT dblink_exec(1)')",
                     "ts_rewrite('a'::tsquery, 'b'::tsquery, 'c'::tsquery)"):
            with self.subTest(call=call):
                result, refusal = sql_guard.check_select_scan(f"SELECT {call}")
                self.assertIsNone(refusal)
                self.assertEqual(result["scan"], ["ts_rewrite"])
                result, refusal = sql_guard.check_write(f"UPDATE t SET q = {call}")
                self.assertIsNone(refusal)
                self.assertEqual(result["scan"], ["ts_rewrite"])
                result, refusal = sql_guard.check_diff(f"SELECT {call}")
                self.assertIsNone(result)
                self.assertEqual(refusal["reason"], "forbidden_function")


if __name__ == "__main__":
    unittest.main()
