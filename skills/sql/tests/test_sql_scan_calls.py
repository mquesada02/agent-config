import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import sql_guard  # noqa: E402


class ScanCallsTest(unittest.TestCase):
    """`scan_calls(text, mode)` reads the function calls of a plan string or an expression text."""

    def test_the_result_has_scan_calls_and_unreadable(self):
        result = sql_guard.scan_calls("lower(x)", "select")
        self.assertEqual(sorted(result), ["calls", "scan", "unreadable"])
        self.assertEqual(result["scan"], [])
        self.assertEqual(result["calls"], [[None, "lower"]])
        self.assertIs(result["unreadable"], False)

    def test_call_reading(self):
        for text, expected in (
            ("f(1)", [[None, "f"]]),
            ("F(1)", [[None, "f"]]),
            ("public.f(1)", [["public", "f"]]),
            ('"MyFn"(1)', [[None, "MyFn"]]),
            ('"My""Fn"(1)', [[None, 'My"Fn']]),
            ('"S".f(1)', [["S", "f"]]),
            ('s."F"(1)', [["s", "F"]]),
            ("f(g(1), g(2))", [[None, "f"], [None, "g"]]),
            ("x + 1", []),
            ("f", []),
        ):
            with self.subTest(text=text):
                self.assertEqual(sql_guard.scan_calls(text, "select")["calls"], sorted(expected, key=lambda c: (c[0] or "", c[1])))

    def test_blanks_and_comments_between_a_name_and_the_parenthesis_do_not_hide_a_call(self):
        for text in ("f (1)", "f\t(1)", "f\n(1)", "f/* c */(1)", "f -- c\n(1)"):
            with self.subTest(text=text):
                self.assertEqual(sql_guard.scan_calls(text, "select")["calls"], [[None, "f"]])

    def test_a_name_in_a_string_or_a_comment_is_no_call(self):
        for text in ("'query_to_xml(1)'", "x -- query_to_xml(1)", "/* query_to_xml(1) */ 1", "$$query_to_xml(1)$$"):
            with self.subTest(text=text):
                result = sql_guard.scan_calls(text, "select")
                self.assertEqual(result["scan"], [])
                self.assertEqual(result["calls"], [])

    def test_the_select_list(self):
        for name in (
            "query_to_xml", "query_to_xml_and_xmlschema", "cursor_to_xml", "ts_stat", "ts_rewrite", "crosstab2",
            "connectby", "set_config", "pg_notify", "lo_export", "dblink", "dblink_exec", "pg_advisory_lock",
            "pg_advisory_xact_lock", "pg_try_advisory_lock",
        ):
            with self.subTest(name=name):
                self.assertEqual(sql_guard.scan_calls(f"{name}('x')", "select")["scan"], [name])

    def test_select_mode_does_not_list_setval(self):
        self.assertEqual(sql_guard.scan_calls("setval('s', 1)", "select")["scan"], [])

    def test_the_write_list(self):
        for name in (
            "query_to_xml", "cursor_to_xml", "ts_stat", "ts_rewrite", "crosstab", "connectby", "lo_export", "setval",
            "dblink", "dblink_connect", "pg_advisory_lock", "pg_try_advisory_lock", "set_config",
        ):
            with self.subTest(name=name):
                self.assertEqual(sql_guard.scan_calls(f"{name}('x')", "write")["scan"], [name])

    def test_write_mode_does_not_list_pg_notify(self):
        self.assertEqual(sql_guard.scan_calls("pg_notify('c', 'p')", "write")["scan"], [])

    def test_the_xact_names_differ_between_the_modes(self):
        self.assertEqual(sql_guard.scan_calls("pg_advisory_xact_lock(1)", "select")["scan"], ["pg_advisory_xact_lock"])
        self.assertEqual(sql_guard.scan_calls("pg_advisory_xact_lock(1)", "write")["scan"], [])
        self.assertEqual(sql_guard.scan_calls("pg_try_advisory_xact_lock(1)", "write")["scan"], [])

    def test_case_rules_are_ascii_only(self):
        self.assertEqual(sql_guard.scan_calls("QUERY_TO_XML('x')", "select")["scan"], ["query_to_xml"])
        self.assertEqual(sql_guard.scan_calls('"Query_To_Xml"(\'x\')', "select")["scan"], ["query_to_xml"])
        self.assertEqual(sql_guard.scan_calls("Kquery_to_xml('x')", "select")["scan"], [])
        self.assertEqual(sql_guard.scan_calls("pg_adſisory_lock(1)", "select")["scan"], [])

    def test_scan_lists_a_listed_word_with_or_without_a_parenthesis(self):
        self.assertEqual(sql_guard.scan_calls("a.query_to_xml", "select")["scan"], ["query_to_xml"])
        self.assertEqual(sql_guard.scan_calls("a.query_to_xml", "select")["calls"], [])

    def test_a_listed_name_is_also_a_call_candidate(self):
        self.assertEqual(sql_guard.scan_calls("pg_catalog.query_to_xml('x')", "select")["calls"], [["pg_catalog", "query_to_xml"]])

    def test_an_unterminated_text_is_unreadable(self):
        for text in ("f('abc", 'f("abc', "f($$abc", "f(1) /* abc"):
            with self.subTest(text=text):
                self.assertIs(sql_guard.scan_calls(text, "select")["unreadable"], True)

    def test_a_readable_text_is_not_unreadable(self):
        self.assertIs(sql_guard.scan_calls("f('a''b')", "select")["unreadable"], False)

    def test_an_unknown_mode_is_a_value_error(self):
        with self.assertRaises(ValueError):
            sql_guard.scan_calls("f(1)", "diff")

    def test_scan_calls_reads_the_lists_at_call_time(self):
        original = sql_guard.STRING_SQL_NAMES
        sql_guard.STRING_SQL_NAMES = original | {"zz_probe_fn"}
        try:
            self.assertEqual(sql_guard.scan_calls("zz_probe_fn(1)", "select")["scan"], ["zz_probe_fn"])
        finally:
            sql_guard.STRING_SQL_NAMES = original
        self.assertEqual(sql_guard.scan_calls("zz_probe_fn(1)", "select")["scan"], [])


if __name__ == "__main__":
    unittest.main()
