import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
GRADERS = os.path.join(SKILL_DIR, "graders")
FALLBACK = ("General guidance: this repo uses MySQL, which the skill does not cover. "
            "The advice is general, with no database and no rule script.")
LAST = "The skill edits no file in general mode."
TABLE_HEAD = ["| # | Rule | Where | Problem | Fix |", "|---|---|---|---|---|"]


def run(script, args=(), stdin=None):
    proc = subprocess.run([sys.executable, "-I", os.path.join(GRADERS, script), *args],
                          input=stdin, capture_output=True, text=True)
    return proc.returncode, proc.stdout.splitlines(), proc.stderr


def general_part(rows=None, title="# sql optimize (general): src/reports.ts", extra=()):
    rows = rows if rows is not None else [
        ["1", "GEN-08 (SQLFluff)", "src/reports.ts:4", "SELECT * in a query.", "List the columns."],
        ["2", "GEN-03 (skill rule)", "src/reports.ts:9, src/reports.ts:12-13", "Cast.", "Cast the value."],
    ]
    lines = [FALLBACK, title, "**Result: 0 critical, %d required, 0 suggestions.**" % len(rows), *extra]
    if rows:
        lines += ["", "## Required", *TABLE_HEAD, *[f"| {' | '.join(row)} |" for row in rows]]
    lines += ["", LAST, ""]
    return "\n".join(lines)


PG_REPORT = "\n".join([
    "# sql optimize: src/profile.ts",
    "**Result: 0 critical, 0 required, 1 suggestion.**",
    "",
    "## Suggestions",
    *TABLE_HEAD,
    "| 1 | PG-08 | src/profile.ts:6 | SELECT * in a template. | List the columns. |",
    "",
    "## Approve",
    "Reply with the findings to fix: `all`, `none`, a list such as `1,3,5`, or a range such as `1-12`.",
    "",
])


class GeneralReportGraderTest(unittest.TestCase):
    def grade(self, text, *args):
        return run("grade_report.py", ["-", "--general", *args], text)

    def assert_fails(self, text, check, *args):
        code, out, _ = self.grade(text, *args)
        self.assertEqual(code, 1, out)
        self.assertTrue(any(line.startswith(f"FAIL {check}:") for line in out), out)

    def test_a_good_general_part_passes(self):
        self.assertEqual(self.grade(general_part())[:2], (0, ["PASS"]))

    def test_a_general_part_with_no_finding_passes(self):
        self.assertEqual(self.grade(general_part(rows=[]))[:2], (0, ["PASS"]))

    def test_no_fallback_sentence_fails(self):
        self.assert_fails(general_part().replace(FALLBACK, "Hello."), "fallback")

    def test_the_postgresql_title_fails(self):
        self.assert_fails(general_part(title="# sql optimize: src/reports.ts"), "title")

    def test_a_rule_cell_with_no_source_fails(self):
        rows = [["1", "GEN-08", "a.ts:1", "p", "f"]]
        self.assert_fails(general_part(rows=rows), "unique")

    def test_a_rule_cell_with_an_unknown_source_fails(self):
        rows = [["1", "GEN-08 (Some Blog)", "a.ts:1", "p", "f"]]
        self.assert_fails(general_part(rows=rows), "unique")

    def test_an_approve_section_fails(self):
        text = general_part().replace(LAST, "## Approve\nThere is nothing to approve.\n" + LAST)
        self.assert_fails(text, "sections")

    def test_a_rewrite_fix_cell_fails(self):
        rows = [["1", "GEN-08 (SQLFluff)", "a.ts:1", "p", "Rewrite (unproven: no database): SELECT 1 database diff"]]
        self.assert_fails(general_part(rows=rows), "rewrite")

    def test_a_missing_last_line_fails(self):
        self.assert_fails(general_part().replace(LAST, ""), "last")

    def test_the_same_rule_in_two_rows_fails(self):
        rows = [["1", "GEN-08 (SQLFluff)", "a.ts:1", "p", "f"], ["2", "GEN-08 (SQLFluff)", "a.ts:2", "p", "f"]]
        self.assert_fails(general_part(rows=rows), "unique")

    def test_a_bad_place_fails(self):
        rows = [["1", "GEN-08 (SQLFluff)", "a.ts", "p", "f"]]
        self.assert_fails(general_part(rows=rows), "where")

    def test_the_disabled_line_is_checked_against_the_flag(self):
        text = general_part(extra=["Disabled rules: GEN-10."])
        self.assertEqual(self.grade(text, "--disabled", "GEN-10")[:2], (0, ["PASS"]))
        self.assert_fails(text, "disabled", "--disabled", "GEN-11")

    def test_a_disabled_id_with_a_row_fails(self):
        text = general_part(extra=["Disabled rules: GEN-08."])
        self.assert_fails(text, "disabled", "--disabled", "GEN-08")

    def test_every_source_of_the_module_is_accepted(self):
        for source in ("SQLFluff", "Use The Index, Luke", "OWASP SQL Injection Prevention Cheat Sheet", "skill rule"):
            rows = [["1", f"GEN-08 ({source})", "a.ts:1", "p", "f"]]
            self.assertEqual(self.grade(general_part(rows=rows))[:2], (0, ["PASS"]), source)


class MixedReportGraderTest(unittest.TestCase):
    def grade(self, text, *args):
        return run("grade_report.py", ["-", "--mixed", *args], text)

    def test_a_good_mixed_report_passes(self):
        self.assertEqual(self.grade(general_part() + PG_REPORT)[:2], (0, ["PASS"]))

    def test_a_mixed_report_with_no_postgresql_title_fails(self):
        code, out, _ = self.grade(general_part())
        self.assertEqual(code, 1)
        self.assertTrue(out[0].startswith("FAIL mixed:"), out)

    def test_a_broken_postgresql_part_fails_with_the_existing_checks(self):
        text = general_part() + PG_REPORT.replace("## Approve", "## Done")
        code, out, _ = self.grade(text)
        self.assertEqual(code, 1)
        self.assertTrue(any(line.startswith("FAIL approve:") for line in out), out)

    def test_a_broken_general_part_fails(self):
        text = general_part().replace(LAST, "") + PG_REPORT
        code, out, _ = self.grade(text)
        self.assertEqual(code, 1)
        self.assertTrue(any(line.startswith("FAIL last:") for line in out), out)

    def test_disabled_ids_split_by_family(self):
        text = general_part(extra=["Disabled rules: GEN-10."]) + PG_REPORT.replace(
            "**Result: 0 critical, 0 required, 1 suggestion.**",
            "**Result: 0 critical, 0 required, 1 suggestion.**\nDisabled rules: PG-10.")
        self.assertEqual(self.grade(text, "--disabled", "GEN-10", "PG-10")[:2], (0, ["PASS"]))
        code, out, _ = self.grade(text, "--disabled", "GEN-10", "PG-06")
        self.assertEqual(code, 1)

    def test_a_part_with_no_disabled_id_gets_no_disabled_check(self):
        text = general_part(extra=["Disabled rules: GEN-10."]) + PG_REPORT
        self.assertEqual(self.grade(text, "--disabled", "GEN-10")[:2], (0, ["PASS"]))


class PostgresqlReportUnchangedTest(unittest.TestCase):
    def test_a_postgresql_report_passes_with_no_flag(self):
        self.assertEqual(run("grade_report.py", ["-"], PG_REPORT)[:2], (0, ["PASS"]))

    def test_a_general_part_fails_with_no_flag(self):
        code, out, _ = run("grade_report.py", ["-"], general_part())
        self.assertEqual(code, 1)

    def test_the_two_flags_exclude_each_other(self):
        code, _, _ = run("grade_report.py", ["-", "--general", "--mixed"], PG_REPORT)
        self.assertEqual(code, 2)


class RuleIdGraderGeneralRowTest(unittest.TestCase):
    def test_the_id_of_a_general_row_is_the_text_before_the_first_space(self):
        code, out, _ = run("grade_rule_ids.py", ["-", "--expect", "GEN-08", "GEN-03", "--forbid", "PG-08"],
                           general_part())
        self.assertEqual((code, out), (0, ["PASS"]))

    def test_a_forbidden_general_id_is_found(self):
        code, out, _ = run("grade_rule_ids.py", ["-", "--forbid", "GEN-08"], general_part())
        self.assertEqual(code, 1)

    def test_a_mixed_report_holds_both_families(self):
        code, out, _ = run("grade_rule_ids.py", ["-", "--expect", "GEN-08", "PG-08"], general_part() + PG_REPORT)
        self.assertEqual((code, out), (0, ["PASS"]))


class EvalResultsReportKeyTest(unittest.TestCase):
    def make_case(self, root, name, expect, report_text):
        folder = os.path.join(root, "evals", name)
        os.makedirs(folder)
        with open(os.path.join(folder, "expect.json"), "w", encoding="utf-8") as handle:
            json.dump(expect, handle)
        trace = os.path.join(root, f"{name}.jsonl")
        with open(trace, "w", encoding="utf-8") as handle:
            assistant = {"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}}
            handle.write(json.dumps(assistant) + "\n")
            handle.write(json.dumps({"type": "result", "result": report_text}) + "\n")
        return trace

    def grade(self, name, expect, report_text):
        with tempfile.TemporaryDirectory() as root:
            trace = self.make_case(root, name, expect, report_text)
            result = os.path.join(root, "result.json")
            with open(result, "w", encoding="utf-8") as handle:
                json.dump({"cases": [{"name": name, "arms": {"with": [{"tracePath": trace}]}}]}, handle)
            return run("grade_eval_results.py", [result, "--evals", os.path.join(root, "evals")])

    def test_a_general_report_passes_with_the_general_key(self):
        code, out, _ = self.grade("c", {"expect": ["GEN-08"], "forbid": ["PG-08"], "report": "general"}, general_part())
        self.assertEqual((code, out[-1]), (0, "PASS"), out)

    def test_a_mixed_report_passes_with_the_mixed_key(self):
        code, out, _ = self.grade("c", {"expect": ["GEN-08", "PG-08"], "forbid": [], "report": "mixed"},
                                  general_part() + PG_REPORT)
        self.assertEqual((code, out[-1]), (0, "PASS"), out)

    def test_a_general_report_fails_with_no_key(self):
        code, out, _ = self.grade("c", {"expect": ["GEN-08"], "forbid": []}, general_part())
        self.assertEqual(code, 1)

    def test_an_unknown_report_value_gives_exit_code_2(self):
        code, _, err = self.grade("c", {"expect": [], "forbid": [], "report": "gneral"}, general_part())
        self.assertEqual(code, 2)
        self.assertIn("report", err)


if __name__ == "__main__":
    unittest.main()
