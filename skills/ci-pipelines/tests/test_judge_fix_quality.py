import json
import os
import subprocess
import sys
import tempfile
import unittest

from report_fixtures import HEADER, SEPARATOR, SCRIPTS, make_report
from skill_files import read

SCRIPT = os.path.join(SCRIPTS, "judge_fix_quality.py")
WORKFLOW = "name: CI\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
FAKE_JUDGE = (
    "import os, sys\n"
    "prompt = sys.stdin.read()\n"
    "with open(os.environ['FAKE_LOG'], 'a', encoding='utf-8') as log:\n"
    "    log.write(prompt + '\\n=====\\n')\n"
    "row = prompt.split('Row:')[-1]\n"
    "print('FAIL: the fix is vague' if 'VAGUE' in row else 'PASS: the edit is concrete')\n"
)


def report(*fixes, flag_rows=()):
    """A review report with one required row for each Fix text. The rules in flag_rows carry the ⚑ mark."""
    rows = []
    for index, fix in enumerate(fixes, start=1):
        rule = f"NAME-0{index}"
        cell = f"{rule} ⚑" if rule in flag_rows else rule
        rows.append(f"| {index} | {cell} | ci.yml:{index} | Problem {index}. | {fix} |")
    lines = ["# ci-pipelines review: all workflows", "", "## Required", "", HEADER, SEPARATOR] + rows + [""]
    if flag_rows:
        lines += ["## ⚑ Branch protection change needed", "", "Admin step: add the required check `CI passed`.", ""]
    return "\n".join(lines + ["## Approve", "", "Reply with `all`.", ""])


class JudgeFixQuality(unittest.TestCase):
    """The result layout follows a real `claude plugin eval --json` result run with --keep-temp."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.evals = os.path.join(self.tmp.name, "evals")
        self.log = os.path.join(self.tmp.name, "prompts.log")
        self.judge = os.path.join(self.tmp.name, "fake_judge.py")
        with open(self.judge, "w", encoding="utf-8") as handle:
            handle.write(FAKE_JUDGE)
        self.cases = []

    def add_case(self, name, messages, judged=True, workflow=WORKFLOW):
        workflows = os.path.join(self.evals, name, "repo", ".github", "workflows")
        os.makedirs(workflows)
        with open(os.path.join(workflows, "ci.yml"), "w", encoding="utf-8") as handle:
            handle.write(workflow)
        runs = []
        for index, text in enumerate(messages):
            path = os.path.join(self.tmp.name, f"{name}-{index}", "trace.jsonl")
            if text is not None:
                os.makedirs(os.path.dirname(path))
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(json.dumps({"type": "result", "result": text}) + "\n")
            runs.append({"tracePath": path})
        graders = [{"name": "fix-quality"}] if judged else [{"name": "section-summary"}]
        self.cases.append({"name": name, "graders": graders, "arms": {"with": runs, "without": runs}})

    def run_script(self, *extra, result=True):
        path = os.path.join(self.tmp.name, "result.json")
        if result:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"schemaVersion": 1, "cases": self.cases}, handle)
        args = [sys.executable, "-I", SCRIPT, path, "--evals", self.evals,
                "--judge-cmd", f"{sys.executable} {self.judge}", *extra]
        proc = subprocess.run(args, capture_output=True, text=True, env={**os.environ, "FAKE_LOG": self.log})
        return proc.returncode, proc.stdout, proc.stderr

    def prompts(self):
        with open(self.log, encoding="utf-8") as handle:
            return handle.read().split("\n=====\n")[:-1]

    def test_it_judges_each_row_alone_and_prints_the_reason(self):
        self.add_case("name-01-x", [report("Rename the job to `test`.", "VAGUE improve it", "Add `timeout-minutes: 10`.")])
        code, out, _ = self.run_script()
        self.assertEqual(code, 0, out)
        self.assertIn("name-01-x#1 row 1 NAME-01: PASS the edit is concrete", out)
        self.assertIn("name-01-x#1 row 2 NAME-02: FAIL the fix is vague", out)
        self.assertIn("name-01-x#1 row 3 NAME-03: PASS the edit is concrete", out)
        self.assertIn("name-01-x#1: FAIL", out)
        self.assertIn("rows: 2 of 3 PASS", out)
        self.assertIn("runs: 0 of 1 PASS", out)
        self.assertEqual(len(self.prompts()), 3)

    def test_a_prompt_holds_its_row_and_the_workflow_text_and_no_other_row(self):
        self.add_case("name-01-x", [report("Rename the job to `test`.", "Add `timeout-minutes: 10`.")])
        self.run_script()
        first, second = self.prompts()
        self.assertIn("runs-on: ubuntu-latest", first)
        self.assertIn("ci.yml", first)
        self.assertIn("Rename the job to `test`.", first)
        self.assertNotIn("timeout-minutes: 10", first)
        self.assertIn("Add `timeout-minutes: 10`.", second)
        self.assertNotIn("Rename the job", second)

    def test_a_flag_row_gets_the_flag_section_and_the_flag_rule(self):
        self.add_case("name-01-x", [report("Add the job `ci-passed`.", "Rename the job.", flag_rows=("NAME-01",))])
        self.run_script()
        first, second = self.prompts()
        self.assertIn("Admin step: add the required check", first)
        self.assertIn("admin steps", first)
        self.assertNotIn("Admin step: add the required check", second)

    def test_a_name_09_row_gets_the_flag_section_even_without_the_flag_mark(self):
        text = report("Add the job `ci-passed`.", "Rename the job.", "Tell the user the check names.")
        text = text.replace("| NAME-03 |", "| NAME-09 |")
        flag_section = "## ⚑ Branch protection change needed\n\nRemove `test`, add `CI passed`.\n\n"
        self.assertIn("\n## Approve", text)
        self.add_case("name-09-x", [text.replace("## Approve", flag_section + "## Approve")])
        self.run_script()
        first, second, third = self.prompts()
        self.assertNotIn("Remove `test`, add `CI passed`.", second)
        self.assertIn("Remove `test`, add `CI passed`.", third)

    def test_the_criterion_passes_a_name_09_row_when_the_flag_section_names_the_old_and_new_check_names(self):
        self.add_case("name-09-x", [report("Tell the user.")])
        self.run_script()
        prompt = self.prompts()[0]
        self.assertIn("A NAME-09 row", prompt)
        self.assertIn("the flag section below names the exact old and new check names", prompt)

    def test_the_criterion_says_a_name_09_fix_never_needs_a_workflow_edit(self):
        self.add_case("name-09-x", [report("Tell the user.")])
        self.run_script()
        prompt = self.prompts()[0]
        self.assertIn("A NAME-09 Fix never needs a workflow edit, because the rename or split comes from "
                      "another finding, so a NAME-09 row is exempt from the workflow edit rule for flag rows "
                      "below.", prompt)

    def test_an_escaped_pipe_stays_inside_its_cell(self):
        self.add_case("name-01-x", [report("Set `if: a \\|\\| b`.")])
        code, out, _ = self.run_script()
        self.assertEqual(code, 0, out)
        self.assertIn("rows: 1 of 1 PASS", out)
        self.assertIn("Set `if: a || b`.", self.prompts()[0])

    def test_a_row_with_a_bare_pipe_in_a_cell_is_an_error_not_a_dropped_row(self):
        self.add_case("name-01-x", [report("Set `if: a || b`.", "Rename the job.")])
        code, out, _ = self.run_script()
        self.assertEqual(code, 1)
        self.assertIn("FAIL name-01-x#1 row 1 table:", out)
        self.assertIn("name-01-x#1: FAIL", out)

    def test_a_run_with_all_rows_passing_passes(self):
        self.add_case("name-01-x", [report("Rename the job to `test`.")])
        code, out, _ = self.run_script()
        self.assertEqual(code, 0)
        self.assertIn("name-01-x#1: PASS", out)
        self.assertIn("runs: 1 of 1 PASS", out)

    def test_a_case_without_the_judge_is_skipped(self):
        self.add_case("create-x", [report("Rename the job.")], judged=False)
        self.add_case("name-01-x", [report("Rename the job.")])
        code, out, _ = self.run_script()
        self.assertEqual(code, 0)
        self.assertNotIn("create-x", out)

    def test_a_run_without_a_table_row_says_so_and_is_not_counted_in_the_run_rate(self):
        self.add_case("clean", [make_report()])
        self.add_case("name-01-x", [report("Rename the job.")])
        code, out, _ = self.run_script()
        self.assertEqual(code, 0)
        self.assertIn("clean#1: no rows", out)
        self.assertIn("runs: 1 of 1 PASS", out)

    def test_a_row_with_an_empty_first_cell_is_judged(self):
        text = report("Rename the job.").replace("| 1 | NAME-01", "|  | NAME-01")
        self.add_case("name-01-x", [text])
        code, out, _ = self.run_script()
        self.assertEqual(code, 0, out)
        self.assertIn("name-01-x#1 row 1 NAME-01: PASS", out)

    def test_a_last_cell_that_ends_in_an_escaped_pipe_keeps_it(self):
        self.add_case("name-01-x", [report("Use a \\|").replace("\\| |", "\\||")])
        self.run_script()
        self.assertIn("fix Use a |\n", self.prompts()[0] + "\n")

    def test_a_missing_trace_is_an_error_and_exit_1(self):
        self.add_case("name-01-x", [None])
        code, out, _ = self.run_script()
        self.assertEqual(code, 1)
        self.assertIn("FAIL name-01-x#1 trace:", out)

    def test_an_unreadable_judge_reply_is_an_error_and_exit_1(self):
        self.add_case("name-01-x", [report("Rename the job.")])
        with open(self.judge, "w", encoding="utf-8") as handle:
            handle.write("print('maybe')\n")
        code, out, _ = self.run_script()
        self.assertEqual(code, 1)
        self.assertIn("FAIL name-01-x#1 row 1 judge:", out)
        self.assertNotIn("rows: 1 of 1", out)

    def test_the_case_filter_limits_the_cases(self):
        self.add_case("name-01-x", [report("Rename the job.")])
        self.add_case("cost-01-y", [report("Rename the job.")])
        code, out, _ = self.run_script("--case", "cost-*")
        self.assertEqual(code, 0)
        self.assertIn("cost-01-y#1", out)
        self.assertNotIn("name-01-x", out)

    def test_an_unreadable_result_is_exit_2(self):
        code, _, err = self.run_script(result=False)
        self.assertEqual(code, 2)
        self.assertIn("cannot read the result", err)

    def test_a_fixture_without_workflow_files_is_exit_2_and_judges_nothing(self):
        self.add_case("name-01-x", [report("Rename the job.")])
        code, out, err = self.run_script("--evals", os.path.join(self.tmp.name, "no-such-evals"))
        self.assertEqual(code, 2)
        self.assertIn("cannot read the fixture of name-01-x", err)
        self.assertFalse(os.path.exists(self.log))

    def test_a_result_with_nothing_to_judge_is_exit_2(self):
        self.add_case("create-x", [report("Rename the job.")], judged=False)
        code, _, err = self.run_script()
        self.assertEqual(code, 2)
        self.assertIn("nothing to judge", err)

    def test_the_default_judge_runs_haiku_without_tools(self):
        text = read(SCRIPT)
        self.assertIn('"--model", "haiku"', text)
        self.assertIn('"--tools", ""', text)


if __name__ == "__main__":
    unittest.main()
