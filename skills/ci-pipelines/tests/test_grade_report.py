import os
import unittest

from report_fixtures import (APPROVE_FINDINGS, APPROVE_ZERO, TOOLS_OK, TempReport, make_report,
                             row, run_script)

SCRIPT = "grade_report.py"


class GradeReport(unittest.TestCase):
    def grade(self, text):
        report = TempReport(text)
        self.addCleanup(report.cleanup)
        return run_script(SCRIPT, [report.path])

    def assertPasses(self, text):
        code, out, _ = self.grade(text)
        self.assertEqual((code, out.strip().splitlines()[-1]), (0, "PASS"), out)

    def assertFailsCheck(self, text, check):
        code, out, _ = self.grade(text)
        self.assertEqual(code, 1, out)
        self.assertIn(f"FAIL {check}:", out)
        self.assertEqual(out.strip().splitlines()[-1], "FAIL")

    def full(self, **kwargs):
        return make_report(critical=[row("SEC-04")],
                           required=[row("NAME-04", flag=True), row("NAME-06")],
                           suggestion=[row("NAME-09")], **kwargs)

    # ----- the valid reports
    def test_a_full_report_passes(self):
        self.assertPasses(self.full())

    def test_a_zero_findings_report_passes(self):
        self.assertPasses(make_report())

    def test_one_severity_only_passes(self):
        self.assertPasses(make_report(required=[row("NAME-06")]))

    def test_a_singular_suggestion_count_is_accepted(self):
        text = make_report(suggestion=[row("NAME-09")],
                           summary="**Result: 0 critical, 0 required, 1 suggestion.**")
        self.assertPasses(text)

    # ----- summary
    def test_a_missing_summary_fails(self):
        self.assertFailsCheck(self.full(summary="Result: some findings."), "summary")

    # ----- sections
    def test_a_missing_title_fails(self):
        self.assertFailsCheck(self.full().replace("# ci-pipelines review: all workflows\n", ""), "sections")

    def test_a_missing_intake_fails(self):
        self.assertFailsCheck(self.full(intake=False), "sections")

    def test_a_missing_required_checks_line_fails(self):
        self.assertFailsCheck(self.full(checks=False), "sections")

    def test_a_missing_job_graph_fails(self):
        self.assertFailsCheck(self.full(graph=False), "sections")

    def test_a_job_graph_without_a_fence_fails(self):
        text = self.full().replace("```", "")
        self.assertFailsCheck(text, "sections")

    def test_sections_out_of_order_fail(self):
        text = self.full()
        intake = next(l for l in text.splitlines() if l.startswith("Intake:"))
        moved = text.replace(intake + "\n", "", 1).replace("## Approve", intake + "\n\n## Approve")
        self.assertFailsCheck(moved, "sections")

    # ----- tables
    def test_a_table_for_an_empty_severity_fails(self):
        text = make_report(required=[row("NAME-06")]).replace(
            "## Approve", "## Critical\n\n| # | Rule | Where | Problem | Fix |\n|---|---|---|---|---|\n\n## Approve")
        self.assertFailsCheck(text, "tables")

    def test_a_missing_table_fails(self):
        text = self.full().replace("## Critical", "## Notes")
        self.assertFailsCheck(text, "tables")

    def test_tables_in_the_wrong_order_fail(self):
        text = self.full()
        crit = text.index("## Critical")
        req = text.index("## Required")
        sug = text.index("## Suggestions")
        swapped = text[:crit] + text[req:sug] + text[crit:req] + text[sug:]
        self.assertFailsCheck(swapped, "tables")

    def test_a_wrong_column_name_fails(self):
        text = self.full().replace("| Problem |", "| Issue |", 1)
        self.assertFailsCheck(text, "tables")

    # ----- numbering
    def test_a_gap_in_the_numbers_fails(self):
        text = self.full().replace("| 3 | NAME-06 |", "| 4 | NAME-06 |")
        self.assertFailsCheck(text, "numbering")

    def test_a_non_ascii_digit_in_the_number_cell_fails_without_a_crash(self):
        # An Arabic-Indic digit is read by int() as 3. A superscript three passes isdigit() but int() rejects it.
        for digit in ("٣", "³"):
            self.assertFailsCheck(self.full().replace("| 3 | NAME-06 |", f"| {digit} | NAME-06 |"), "numbering")

    def test_a_huge_number_cell_fails_without_a_crash(self):
        text = self.full().replace("| 3 | NAME-06 |", f"| {'9' * 5000} | NAME-06 |")
        self.assertFailsCheck(text, "numbering")

    def test_a_huge_summary_count_fails_without_a_crash(self):
        text = self.full(summary=f"**Result: 1 critical, {'9' * 5000} required, 1 suggestions.**")
        self.assertFailsCheck(text, "summary")

    def test_numbers_that_do_not_follow_severity_order_fail(self):
        text = self.full().replace("| 1 | SEC-04 |", "| 4 | SEC-04 |").replace("| 4 | NAME-09 |", "| 1 | NAME-09 |")
        self.assertFailsCheck(text, "numbering")

    # ----- counts
    def test_a_count_that_differs_from_the_rows_fails(self):
        text = self.full(summary="**Result: 1 critical, 3 required, 1 suggestions.**")
        self.assertFailsCheck(text, "counts")

    # ----- unique
    def test_the_same_rule_twice_at_one_severity_fails(self):
        text = make_report(required=[row("NAME-06"), row("NAME-06", where="ci.yml:9")])
        self.assertFailsCheck(text, "unique")

    def test_the_same_rule_at_two_severities_passes(self):
        self.assertPasses(make_report(critical=[row("SEC-04")], required=[row("SEC-04")]))

    def test_a_rule_cell_with_two_ids_fails(self):
        text = make_report(required=[row("NAME-04, GRAPH-01")])
        self.assertFailsCheck(text, "unique")

    # ----- flag section
    def test_a_flag_without_the_section_fails(self):
        self.assertFailsCheck(self.full(flag_section=False), "flag-section")

    def test_the_section_without_a_flag_fails(self):
        text = make_report(required=[row("NAME-06")], flag_section=True)
        self.assertFailsCheck(text, "flag-section")

    # ----- approve
    def test_the_approve_section_must_be_last(self):
        text = self.full() + "\n## Extra\n\nMore text.\n"
        self.assertFailsCheck(text, "approve")

    def test_findings_need_the_reply_grammar(self):
        self.assertFailsCheck(self.full(approve="Tell me what to fix."), "approve")

    def test_zero_findings_need_the_nothing_to_approve_line(self):
        self.assertFailsCheck(make_report(approve=APPROVE_FINDINGS), "approve")

    def test_the_zero_line_with_findings_fails(self):
        self.assertFailsCheck(self.full(approve=APPROVE_ZERO), "approve")

    # ----- tools
    def test_a_missing_tool_bullet_fails(self):
        self.assertFailsCheck(self.full(tools=[TOOLS_OK[0]]), "tools")

    def test_a_missing_tool_without_an_install_hint_fails(self):
        self.assertFailsCheck(self.full(tools=[TOOLS_OK[0], "- zizmor: not on PATH."]), "tools")

    def test_both_tools_on_path_pass(self):
        self.assertPasses(self.full(tools=["- actionlint: on PATH (1.7.0)", "- zizmor: on PATH (1.5.0)"]))

    def test_a_merged_finding_appears_once_and_passes(self):
        self.assertPasses(make_report(required=[row("SEC-01", where="ci.yml:7, ci.yml:12")]))

    def test_a_merged_finding_written_twice_at_one_severity_fails(self):
        self.assertFailsCheck(make_report(required=[row("SEC-01"), row("SEC-01")]), "unique")

    def test_the_missing_tool_report_with_an_install_hint_passes(self):
        tools = ["- actionlint: not on PATH. Install it with `brew install actionlint`.", TOOLS_OK[1]]
        self.assertPasses(make_report(required=[row("SEC-01"), row("SEC-03")], tools=tools))

    def test_a_tool_on_path_without_its_version_fails(self):
        self.assertFailsCheck(self.full(tools=["- actionlint: on PATH", TOOLS_OK[1]]), "tools")

    def test_a_tool_bullet_that_says_nothing_about_path_fails(self):
        self.assertFailsCheck(self.full(tools=[TOOLS_OK[0], "- zizmor: ran."]), "tools")

    def test_a_blank_line_between_the_tool_bullets_passes(self):
        self.assertPasses(self.full(tools=[TOOLS_OK[0], "", TOOLS_OK[1]]))

    def test_the_tools_block_ends_at_a_line_that_is_not_a_bullet(self):
        # The zizmor bullet is after a paragraph, so it is not part of the Tools block.
        self.assertFailsCheck(self.full(tools=[TOOLS_OK[0], "", "Some text.", TOOLS_OK[1]]), "tools")

    def test_blank_lines_between_tools_and_its_bullets_pass(self):
        self.assertPasses(self.full().replace("Tools:\n", "Tools:\n\n"))

    # ----- command line
    def test_an_unreadable_report_is_a_usage_error(self):
        code, _, err = run_script(SCRIPT, [os.path.join("no", "such", "report.md")])
        self.assertEqual(code, 2)
        self.assertTrue(err.strip())


if __name__ == "__main__":
    unittest.main()
