import os
import subprocess
import sys
import unittest

import helper_testing_rules as helper

GRADER = os.path.join(helper.SKILL, "scripts", "grade_testing_report.py")
APPROVE = "Reply with the findings to fix: `all`, `none`, a list such as `1,3,5`, or a range such as `1-12`."
HEADER = "| # | Rule | Where | Problem | Fix |\n|---|---|---|---|---|\n"


def report(title="# testing review: tests/a.test.ts", result="**Result: 1 critical, 1 required, 1 suggestions.**",
           notes="", critical="| 1 | ASSERT-01 | tests/a.test.ts:3 | No assertion. | Add one. |\n",
           required="| 2 | RUN-02 | tests/a.test.ts:9 | Real sleep. | Use fake time. |\n",
           suggestion="| 3 | RUN-05 | tests/a.test.ts:12 | No reason. | Add a reason. |\n",
           tail="## Approve\n\n" + APPROVE + "\n"):
    parts = [title, "", result, ""]
    if notes:
        parts += [notes.rstrip("\n"), ""]
    for heading, rows in (("## Critical", critical), ("## Required", required), ("## Suggestions", suggestion)):
        if rows:
            parts += [heading, "", HEADER + rows.rstrip("\n"), ""]
    parts.append(tail.rstrip("\n"))
    return "\n".join(parts) + "\n"


ZERO = "# testing review: tests\n\n**Result: 0 critical, 0 required, 0 suggestions.**\n"


def grade(text):
    args = [sys.executable, "-I", GRADER, "-"]
    return subprocess.run(args, input=text, capture_output=True, text=True)


class GradeCase(unittest.TestCase):
    def assert_pass(self, text):
        result = grade(text)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stdout.strip(), "PASS")

    def assert_fail(self, text, check):
        result = grade(text)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(f"FAIL {check}:", result.stdout)
        self.assertEqual(result.stdout.strip().splitlines()[-1], "FAIL")
        return result.stdout


class ValidReportTest(GradeCase):
    def test_report_with_all_three_tables_passes(self):
        self.assert_pass(report())

    def test_zero_findings_report_with_no_approve_passes(self):
        self.assert_pass(ZERO)

    def test_report_with_every_note_line_in_order_passes(self):
        notes = (
            "Disabled (reason recorded, not checked): RUN-02.\n"
            "No reason line, checked anyway: ASSERT-01.\n"
            "Unknown ids in rules.disabled, ignored: FOO-01.\n"
            "Detected for this run: commands.rust. Run /testing setup to record them.\n"
        )
        self.assert_pass(report(notes=notes, required="", suggestion="", result="**Result: 1 critical, 0 required, 0 suggestions.**"))

    def test_zero_findings_report_with_notes_passes(self):
        notes = "Rules file error: expected a value (line 4). Every setting is detected for this run. Run /testing setup.\n"
        self.assert_pass(ZERO + "\n" + notes)

    def test_where_cell_may_hold_several_places_and_a_range(self):
        rows = "| 1 | ASSERT-01 | a.test.ts:3, b.test.ts:4-6 | No assertion. | Add one. |\n"
        self.assert_pass(report(critical=rows, required="", suggestion="", result="**Result: 1 critical, 0 required, 0 suggestions.**"))

    def test_singular_suggestion_word_is_accepted(self):
        text = report().replace("1 suggestions.", "1 suggestion.")
        self.assert_pass(text)


class BrokenReportTest(GradeCase):
    def test_wrong_title(self):
        self.assert_fail(report(title="# cicd-pipelines review: x"), "title")

    def test_no_result_line(self):
        self.assert_fail(report(result="Result: none"), "summary")

    def test_count_mismatch(self):
        self.assert_fail(report(result="**Result: 2 critical, 1 required, 1 suggestions.**"), "counts")

    def test_table_present_but_count_zero(self):
        self.assert_fail(report(result="**Result: 1 critical, 0 required, 1 suggestions.**"), "tables")

    def test_table_missing_but_count_positive(self):
        self.assert_fail(report(required="", result="**Result: 1 critical, 1 required, 1 suggestions.**"), "tables")

    def test_number_gap_across_tables(self):
        text = report(suggestion="| 4 | RUN-05 | a.test.ts:12 | No reason. | Add. |\n")
        self.assert_fail(text, "numbering")

    def test_wrong_header(self):
        text = report().replace("| # | Rule | Where | Problem | Fix |", "| # | Rule | Place | Problem | Fix |", 1)
        self.assert_fail(text, "tables")

    def test_tables_in_the_wrong_order(self):
        text = report()
        crit = text.index("## Critical")
        req = text.index("## Required")
        sug = text.index("## Suggestions")
        approve = text.index("## Approve")
        swapped = text[:crit] + text[req:sug] + text[crit:req] + text[sug:approve] + text[approve:]
        self.assert_fail(swapped, "sections")

    def test_unknown_id(self):
        text = report(critical="| 1 | FOO-01 | a.test.ts:3 | x | y |\n")
        self.assert_fail(text, "ids")

    def test_rule_cell_with_two_ids(self):
        text = report(critical="| 1 | ASSERT-01, ASSERT-02 | a.test.ts:3 | x | y |\n")
        self.assert_fail(text, "ids")

    def test_id_twice(self):
        text = report(required="| 2 | ASSERT-01 | a.test.ts:9 | x | y |\n")
        out = self.assert_fail(text, "ids")
        self.assertIn("ASSERT-01 appears twice", out)

    def test_id_in_the_wrong_severity_table(self):
        text = report(critical="| 1 | RUN-02 | a.test.ts:3 | x | y |\n", required="")
        text = text.replace("1 required", "0 required")
        self.assert_fail(text, "severities")

    def test_flag_mark(self):
        text = report(critical="| 1 | ASSERT-01 ⚑ | a.test.ts:3 | x | y |\n")
        self.assert_fail(text, "sections")

    def test_lock_mark(self):
        self.assert_fail(report().replace("No assertion.", "No assertion 🔒."), "sections")

    def test_missing_approve(self):
        self.assert_fail(report(tail=""), "approve")

    def test_wrong_approve_text(self):
        self.assert_fail(report(tail="## Approve\n\nReply with the findings to fix: all."), "approve")

    def test_approve_in_a_zero_findings_report(self):
        self.assert_fail(ZERO + "\n## Approve\n\nThere is nothing to approve.\n", "approve")

    def test_unknown_section(self):
        self.assert_fail(report() + "\n## Notes\n\nx\n", "sections")

    def test_where_cell_without_a_place(self):
        self.assert_fail(report(critical="| 1 | ASSERT-01 | a.test.ts | x | y |\n"), "where")

    def test_note_line_twice(self):
        notes = "Disabled (reason recorded, not checked): RUN-02.\nDisabled (reason recorded, not checked): RUN-03.\n"
        self.assert_fail(report(notes=notes), "notes")

    def test_note_lines_out_of_order(self):
        notes = (
            "No reason line, checked anyway: ASSERT-01.\n"
            "Disabled (reason recorded, not checked): RUN-02.\n"
        )
        self.assert_fail(report(notes=notes), "notes")

    def test_id_in_two_note_lines(self):
        notes = (
            "Disabled (reason recorded, not checked): RUN-02.\n"
            "No reason line, checked anyway: RUN-02, ASSERT-01.\n"
        )
        self.assert_fail(report(notes=notes), "notes")

    def test_id_in_lines_a_and_c(self):
        notes = (
            "Disabled (reason recorded, not checked): RUN-02.\n"
            "Unknown ids in rules.disabled, ignored: RUN-02.\n"
        )
        self.assert_fail(report(notes=notes), "notes")

    def test_id_in_lines_b_and_c(self):
        notes = (
            "No reason line, checked anyway: ASSERT-01.\n"
            "Unknown ids in rules.disabled, ignored: ASSERT-01.\n"
        )
        self.assert_fail(report(notes=notes), "notes")

    def test_empty_input_fails_title_and_summary(self):
        out = self.assert_fail("", "title")
        self.assertIn("FAIL summary:", out)

    def test_checked_id_may_be_in_a_table_and_in_line_b(self):
        notes = "No reason line, checked anyway: ASSERT-01.\n"
        self.assert_pass(report(notes=notes))


class CliTest(unittest.TestCase):
    def test_unreadable_report_is_exit_2(self):
        result = subprocess.run([sys.executable, "-I", GRADER, "/nonexistent/report.md"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)

    def test_no_argument_is_a_usage_error(self):
        result = subprocess.run([sys.executable, "-I", GRADER], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)

    def test_report_from_a_path(self):
        repo = helper.Repo()
        self.addCleanup(repo.close)
        path = os.path.join(repo.root, "report.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(report())
        result = subprocess.run([sys.executable, "-I", GRADER, path], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
