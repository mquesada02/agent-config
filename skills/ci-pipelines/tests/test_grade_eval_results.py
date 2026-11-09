import json
import os
import tempfile
import unittest

from report_fixtures import make_report, row, run_script

SCRIPT = "grade_eval_results.py"


class GradeEvalResults(unittest.TestCase):
    """The result layout follows a real `claude plugin eval --json` result (schemaVersion 1) of a run with
    --keep-temp: cases[].arms.with[].tracePath is a trace.jsonl whose last line holds the final message in `result`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.evals = os.path.join(self.tmp.name, "evals")
        self.cases = []

    def add_case(self, name, expect, forbid, reports, review=True, without=None):
        """Write expect.json and one trace for each report. `reports` is a list of texts (None: no trace file)."""
        case_dir = os.path.join(self.evals, name)
        os.makedirs(case_dir)
        with open(os.path.join(case_dir, "expect.json"), "w", encoding="utf-8") as handle:
            json.dump({"expect": expect, "forbid": forbid}, handle)
        names = ["section-summary", "no-edit"] if review else ["skill-fired"]
        case = {"name": name, "graders": [{"name": n} for n in names],
                "arms": {"with": self.runs(name, "with", reports), "without": self.runs(name, "without", without or [])}}
        self.cases.append(case)

    def runs(self, name, arm, reports):
        runs = []
        for index, text in enumerate(reports):
            path = os.path.join(self.tmp.name, f"{name}-{arm}-{index}", "trace.jsonl")
            if text is not None:
                os.makedirs(os.path.dirname(path))
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(json.dumps({"type": "assistant"}) + "\n")
                    handle.write(json.dumps({"type": "result", "result": text}) + "\n")
            runs.append({"score": 1, "tracePath": path})
        return runs

    def grade(self):
        result = os.path.join(self.tmp.name, "result.json")
        with open(result, "w", encoding="utf-8") as handle:
            json.dump({"schemaVersion": 1, "cases": self.cases}, handle)
        return run_script(SCRIPT, [result, "--evals", self.evals])

    def test_valid_runs_pass(self):
        self.add_case("name-04-x", ["NAME-04"], [], [make_report(required=[row("NAME-04")])] * 2)
        code, out, _ = self.grade()
        self.assertEqual((code, out.strip().splitlines()[-1]), (0, "PASS"), out)
        self.assertIn("name-04-x", out)

    def test_a_report_that_breaks_the_contract_fails_with_the_case_and_the_check(self):
        bad = make_report(required=[row("NAME-04")], intake=False)
        self.add_case("name-04-x", ["NAME-04"], [], [bad])
        code, out, _ = self.grade()
        self.assertEqual(code, 1)
        self.assertIn("FAIL name-04-x#1 sections:", out)
        self.assertEqual(out.strip().splitlines()[-1], "FAIL")

    def test_a_missing_expected_id_fails(self):
        self.add_case("name-06-x", ["NAME-06"], [], [make_report(required=[row("NAME-04")])])
        code, out, _ = self.grade()
        self.assertEqual(code, 1)
        self.assertIn("FAIL name-06-x#1 expect:NAME-06:", out)

    def test_a_forbidden_id_fails(self):
        self.add_case("clean", [], ["NAME-04"], [make_report(required=[row("NAME-04")])])
        code, out, _ = self.grade()
        self.assertEqual(code, 1)
        self.assertIn("FAIL clean#1 forbid:NAME-04:", out)

    def test_each_run_is_graded(self):
        good = make_report(required=[row("NAME-04")])
        self.add_case("name-04-x", ["NAME-04"], [], [good, make_report(), good])
        code, out, _ = self.grade()
        self.assertEqual(code, 1)
        self.assertIn("FAIL name-04-x#2 expect:NAME-04", out)
        self.assertIn("name-04-x#1: PASS", out)
        self.assertIn("name-04-x#2: FAIL", out)
        self.assertIn("name-04-x#3: PASS", out)

    def test_a_missing_trace_fails_and_says_to_use_keep_temp(self):
        self.add_case("name-04-x", ["NAME-04"], [], [None])
        code, out, _ = self.grade()
        self.assertEqual(code, 1)
        self.assertIn("FAIL name-04-x#1 trace:", out)
        self.assertIn("--keep-temp", out)

    def test_a_case_without_the_section_graders_is_skipped(self):
        self.add_case("trigger-x", [], [], ["not a report"], review=False)
        self.add_case("name-04-x", ["NAME-04"], [], [make_report(required=[row("NAME-04")])])
        code, out, _ = self.grade()
        self.assertEqual(code, 0, out)
        self.assertNotIn("trigger-x", out)

    def test_the_baseline_arm_is_not_graded(self):
        good = make_report(required=[row("NAME-04")])
        self.add_case("name-04-x", ["NAME-04"], [], [good], without=["no report at all"])
        code, _, _ = self.grade()
        self.assertEqual(code, 0)

    def test_a_missing_expect_file_is_a_usage_error(self):
        self.add_case("name-04-x", ["NAME-04"], [], [make_report(required=[row("NAME-04")])])
        os.remove(os.path.join(self.evals, "name-04-x", "expect.json"))
        code, _, err = self.grade()
        self.assertEqual(code, 2)
        self.assertIn("expect.json", err)

    def test_an_invalid_expect_file_is_a_usage_error(self):
        self.add_case("name-04-x", ["NAME-04"], [], [make_report(required=[row("NAME-04")])])
        with open(os.path.join(self.evals, "name-04-x", "expect.json"), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        code, _, err = self.grade()
        self.assertEqual(code, 2)
        self.assertIn("expect.json", err)

    def test_an_expect_file_without_the_forbid_list_is_a_usage_error(self):
        self.add_case("name-04-x", ["NAME-04"], [], [make_report(required=[row("NAME-04")])])
        with open(os.path.join(self.evals, "name-04-x", "expect.json"), "w", encoding="utf-8") as handle:
            json.dump({"expect": ["NAME-04"]}, handle)
        code, _, err = self.grade()
        self.assertEqual(code, 2)
        self.assertIn("expect.json", err)

    def test_a_result_with_a_malformed_shape_is_a_usage_error(self):
        review = '"name": "x", "graders": [{"name": "section-summary"}]'
        shapes = [
            "[]", '{"cases": 5}', '{"cases": [5]}',
            '{"cases": [{"graders": []}]}',                                   # no name
            '{"cases": [{"name": 5, "graders": []}]}',                        # name is not a string
            '{"cases": [{"name": "x", "graders": [1]}]}',                     # grader is not an object
            '{"cases": [{"name": "x", "graders": 5}]}',                       # graders is not a list
            '{"cases": [{%s, "arms": []}]}' % review,                         # arms is not an object
            '{"cases": [{%s, "arms": {"with": 5}}]}' % review,                # with is not a list
            '{"cases": [{%s, "arms": {"with": [1]}}]}' % review,              # a run is not an object
            '{"cases": [{%s, "arms": {"with": [{"tracePath": null}]}}]}' % review,   # tracePath is not a string
        ]
        os.makedirs(os.path.join(self.evals, "x"))
        with open(os.path.join(self.evals, "x", "expect.json"), "w", encoding="utf-8") as handle:
            json.dump({"expect": [], "forbid": []}, handle)
        for text in shapes:
            path = os.path.join(self.tmp.name, "odd.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            code, out, err = run_script(SCRIPT, [path, "--evals", self.evals])
            self.assertEqual(code, 2, f"{text}: {out}{err}")
            self.assertTrue(err.strip(), text)

    def test_a_trace_whose_last_line_is_not_an_object_is_a_failed_run(self):
        for line in ("[]", "1", '"x"'):
            self.add_case(f"case-{len(self.cases)}", [], [], [None])
            trace = self.cases[-1]["arms"]["with"][0]["tracePath"]
            os.makedirs(os.path.dirname(trace))
            with open(trace, "w", encoding="utf-8") as handle:
                handle.write(line + "\n")
        code, out, _ = self.grade()
        self.assertEqual(code, 1)
        for number in range(3):
            self.assertIn(f"FAIL case-{number}#1 trace:", out)
            self.assertIn(f"case-{number}#1: FAIL", out)
        self.assertEqual(out.strip().splitlines()[-1], "FAIL")

    def test_an_unreadable_result_is_a_usage_error(self):
        code, _, err = run_script(SCRIPT, [os.path.join(self.tmp.name, "missing.json")])
        self.assertEqual(code, 2)
        self.assertTrue(err.strip())


if __name__ == "__main__":
    unittest.main()
