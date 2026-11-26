import os
import re
import unittest

from report_fixtures import TempReport, general_row, make_general_report, make_report, row, run_script
from skill_files import RULES, SKILL, frontmatter

SCRIPT = "grade_rule_ids.py"
GENERAL_RULES = os.path.join(RULES, "general.md")
STAGE_GRADER = os.path.join(SKILL, "evals", "general-create-python-empty", "graders", "general-stage.md")
PLAN = ("General guidance: this repo uses Python with no CI system yet.\n\n"
        "1. Checkout: get the code. Follows GEN-05.\n"
        "2. Test: run pytest. Follows GEN-05, GEN-17.\n\n"
        "The skill edits no file in general mode.\n")


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

    def test_the_lock_mark_and_both_marks_are_not_part_of_the_token(self):
        text = make_report(required=[row("PROTECT-02", lock=True), row("PROTECT-01", flag=True, lock=True)])
        code, _, _ = self.grade(text, "--expect", "PROTECT-01", "PROTECT-02")
        self.assertEqual(code, 0)
        code, _, _ = self.grade(text, "--forbid", "PROTECT-02")
        self.assertEqual(code, 1)

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

    def test_a_general_reply_finds_its_ids_in_the_first_cell(self):
        text = make_general_report(required=[general_row("GEN-02"), general_row("GEN-03")])
        code, out, _ = self.grade(text, "--expect", "GEN-02", "GEN-03")
        self.assertEqual((code, self.last_line(out)), (0, "PASS"), out)

    def test_a_general_reply_gives_no_token_for_its_header_or_its_other_cells(self):
        text = make_general_report(required=[general_row("GEN-02", "ci.yml:3")])
        code, out, _ = self.grade(text, "--forbid", "Rule", "Where", "repo", "ci.yml:3", "A problem.")
        self.assertEqual((code, self.last_line(out)), (0, "PASS"), out)

    def test_a_forbidden_gen_id_fails(self):
        text = make_general_report(required=[general_row("GEN-02")])
        code, out, _ = self.grade(text, "--forbid", "GEN-02")
        self.assertEqual(code, 1)
        self.assertIn("FAIL forbid:GEN-02:", out)

    def test_a_mixed_reply_finds_both_kinds_of_id(self):
        normal = make_report(required=[row("NAME-04")])
        text = make_general_report(required=[general_row("GEN-02")], normal=normal)
        code, out, _ = self.grade(text, "--expect", "GEN-02", "NAME-04", "--forbid", "Rule", "Where")
        self.assertEqual((code, self.last_line(out)), (0, "PASS"), out)

    def test_a_normal_table_still_reads_the_second_cell(self):
        text = make_report(required=[row("NAME-04")])
        code, out, _ = self.grade(text, "--forbid", "1", "Rule")
        self.assertEqual((code, self.last_line(out)), (0, "PASS"), out)

    def test_a_row_with_too_few_cells_gives_no_token(self):
        text = "| # | Rule | Where |\n|---|---|---|\n| 1 |\n"
        code, out, _ = self.grade(text, "--forbid", "1")
        self.assertEqual((code, self.last_line(out)), (0, "PASS"), out)

    def plan(self, text):
        return self.grade(text, "--plan", GENERAL_RULES)

    def test_a_good_create_plan_passes(self):
        code, out, _ = self.plan(PLAN)
        self.assertEqual((code, self.last_line(out)), (0, "PASS"), out)

    def test_a_plan_with_a_stage_that_has_no_id_fails(self):
        code, out, _ = self.plan(PLAN.replace("2. Test: run pytest. Follows GEN-05, GEN-17.", "2. Test: run pytest."))
        self.assertEqual((code, self.last_line(out)), (1, "FAIL"), out)
        self.assertIn("FAIL plan:stage 2:", out)

    def test_a_plan_with_an_unknown_id_fails(self):
        code, out, _ = self.plan(PLAN.replace("GEN-17", "GEN-99"))
        self.assertEqual((code, self.last_line(out)), (1, "FAIL"), out)
        self.assertIn("FAIL plan:GEN-99:", out)

    def test_a_plan_with_an_id_outside_follows_fails(self):
        code, out, _ = self.plan(PLAN.replace("Follows GEN-05.", "See GEN-05."))
        self.assertEqual((code, self.last_line(out)), (1, "FAIL"), out)

    def test_a_plan_with_no_numbered_line_fails(self):
        code, out, _ = self.plan("General guidance: x\n")
        self.assertEqual((code, self.last_line(out)), (1, "FAIL"), out)

    def test_a_rules_file_with_no_entry_fails_closed(self):
        rules = TempReport("no entries here\n")
        self.addCleanup(rules.cleanup)
        code, out, _ = self.grade(PLAN, "--plan", rules.path)
        self.assertEqual((code, self.last_line(out)), (1, "FAIL"), out)

    def test_an_unreadable_rules_file_is_a_usage_error(self):
        code, _, err = self.grade(PLAN, "--plan", os.path.join("no", "such", "rules.md"))
        self.assertEqual(code, 2)
        self.assertIn("rules file", err)

    def test_the_regex_grader_and_the_script_agree_on_the_format(self):
        stage = re.compile(frontmatter(STAGE_GRADER)["pattern"])
        bad = PLAN.replace("2. Test: run pytest. Follows GEN-05, GEN-17.", "2. Test: run pytest.")
        for text, passes in ((PLAN, True), (bad, False), (PLAN.replace("Follows GEN-05.", "See GEN-05."), False),
                             (PLAN.replace("GEN-05, GEN-17", "GEN-05 and GEN-17"), True)):
            code, _, _ = self.plan(text)
            self.assertEqual((bool(stage.search(text)), code == 0), (passes, passes), text)

    def test_an_unreadable_report_is_a_usage_error(self):
        code, _, err = run_script(SCRIPT, [os.path.join("no", "such", "report.md")])
        self.assertEqual(code, 2)
        self.assertTrue(err.strip())


if __name__ == "__main__":
    unittest.main()
