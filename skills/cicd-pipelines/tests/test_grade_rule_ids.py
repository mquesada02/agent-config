import os
import unittest

from report_fixtures import TempReport, make_report, row, run_script

SCRIPT = "grade_rule_ids.py"


class GradeRuleIds(unittest.TestCase):
    def grade(self, text, *args):
        report = TempReport(text)
        self.addCleanup(report.cleanup)
        return run_script(SCRIPT, [report.path, *args])

    def last_line(self, out):
        return out.strip().splitlines()[-1]

    def test_every_expected_id_found_passes(self):
        text = make_report(required=[row("NAME-04"), row("NAME-06")])
        code, out, _ = self.grade(text, "--expect", "NAME-04", "NAME-06")
        self.assertEqual(code, 0)
        self.assertEqual(self.last_line(out), "PASS")

    def test_a_missing_expected_id_fails_and_names_the_check(self):
        text = make_report(required=[row("NAME-04")])
        code, out, _ = self.grade(text, "--expect", "NAME-04", "NAME-06")
        self.assertEqual(code, 1)
        self.assertIn("FAIL expect:NAME-06:", out)
        self.assertEqual(self.last_line(out), "FAIL")

    def test_a_forbidden_id_that_appears_fails(self):
        text = make_report(required=[row("NAME-04")])
        code, out, _ = self.grade(text, "--forbid", "NAME-04")
        self.assertEqual(code, 1)
        self.assertIn("FAIL forbid:NAME-04:", out)

    def test_a_forbidden_id_that_is_absent_passes(self):
        text = make_report(required=[row("NAME-04")])
        code, _, _ = self.grade(text, "--forbid", "NAME-06", "SEC-01")
        self.assertEqual(code, 0)

    def test_an_id_in_prose_is_not_a_finding(self):
        text = make_report(required=[row("NAME-04")]).replace(
            "Defaults: none.", "NAME-06 was checked and is fine.")
        code, out, _ = self.grade(text, "--expect", "NAME-06")
        self.assertEqual(code, 1)
        self.assertIn("FAIL expect:NAME-06:", out)

    def test_the_flag_mark_is_not_part_of_the_token(self):
        text = make_report(required=[row("NAME-08", flag=True)])
        code, _, _ = self.grade(text, "--expect", "NAME-08")
        self.assertEqual(code, 0)

    def test_a_bare_tool_id_is_matched_exactly(self):
        text = make_report(suggestion=[row("unpinned-uses")])
        code, _, _ = self.grade(text, "--forbid", "unpinned-uses")
        self.assertEqual(code, 1)
        code, _, _ = self.grade(text, "--forbid", "unpinned")
        self.assertEqual(code, 0)

    def test_no_findings_and_no_lists_passes(self):
        code, out, _ = self.grade(make_report())
        self.assertEqual(code, 0)
        self.assertEqual(self.last_line(out), "PASS")

    def test_the_header_row_is_not_a_finding(self):
        code, _, _ = self.grade(make_report(), "--forbid", "Rule", "#")
        self.assertEqual(code, 0)

    def test_the_report_can_come_from_stdin(self):
        text = make_report(required=[row("NAME-04")])
        code, _, _ = run_script(SCRIPT, ["-", "--expect", "NAME-04"], stdin=text)
        self.assertEqual(code, 0)

    def test_a_merged_report_passes_the_merge_case_lists(self):
        text = make_report(required=[row("SEC-01", where="ci.yml:7")])
        code, _, _ = self.grade(text, "--expect", "SEC-01", "--forbid", "unpinned-uses")
        self.assertEqual(code, 0)

    def test_a_report_that_lists_the_bare_zizmor_id_fails_the_merge_case_lists(self):
        text = make_report(required=[row("SEC-01"), row("unpinned-uses")])
        code, out, _ = self.grade(text, "--expect", "SEC-01", "--forbid", "unpinned-uses")
        self.assertEqual(code, 1)
        self.assertIn("FAIL forbid:unpinned-uses:", out)

    def test_an_unmapped_audit_id_in_a_rule_cell_is_found(self):
        text = make_report(suggestion=[row("obfuscation")])
        code, _, _ = self.grade(text, "--expect", "obfuscation")
        self.assertEqual(code, 0)

    def test_an_unreadable_report_is_a_usage_error(self):
        code, _, err = run_script(SCRIPT, [os.path.join("no", "such", "report.md")])
        self.assertEqual(code, 2)
        self.assertTrue(err.strip())


if __name__ == "__main__":
    unittest.main()
