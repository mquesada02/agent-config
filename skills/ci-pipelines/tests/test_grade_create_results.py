import json
import os
import subprocess
import sys
import tempfile
import unittest

from skill_files import SKILL

SCRIPT = os.path.join(SKILL, "scripts", "grade_create_results.py")
CI = ".github/workflows/ci.yml"
DEPENDABOT = ".github/dependabot.yml"

FAKE_ACTIONLINT = """#!{python}
import sys
with open({log!r}, "a") as handle:
    handle.write(" ".join(sys.argv[1:]) + "\\n")
if {fail}:
    print("ci.yml:1:1: fake error [syntax-check]")
    sys.exit(1)
"""

DEPENDABOT_TEXT = 'version: 2\nupdates:\n  - package-ecosystem: "github-actions"\n    directory: "/"\n    schedule:\n      interval: "weekly"\n'


def created(*blocks):
    """A final message: a `## Created` section with one `### path` block for each (path, text), then a report."""
    lines = ["## Created", ""]
    for path, text in blocks:
        lines += [f"- `{path}` written"]
    for path, text in blocks:
        lines += ["", f"### {path}", "", "```yaml", text.rstrip("\n"), "```"]
    lines += ["", "# ci-pipelines review: .github/workflows/ci.yml (created)", "", "**Result: clean**"]
    return "\n".join(lines) + "\n"


class GradeCreateResults(unittest.TestCase):
    """The result layout follows a `claude plugin eval --json` result with --keep-temp, as in grade_eval_results."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.evals = os.path.join(self.tmp.name, "evals")
        self.bin = os.path.join(self.tmp.name, "bin")
        os.mkdir(self.bin)
        self.log = os.path.join(self.tmp.name, "actionlint.log")
        self.cases = []

    def fake_actionlint(self, fail=False):
        path = os.path.join(self.bin, "actionlint")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(FAKE_ACTIONLINT.format(python=sys.executable, log=self.log, fail=fail))
        os.chmod(path, 0o755)

    def add_case(self, name, asserts, messages, grader="wrote-ci"):
        case_dir = os.path.join(self.evals, name)
        os.makedirs(case_dir)
        with open(os.path.join(case_dir, "expect.json"), "w", encoding="utf-8") as handle:
            json.dump({"expect": [], "forbid": [], "asserts": asserts}, handle)
        runs = []
        for index, text in enumerate(messages):
            path = os.path.join(self.tmp.name, f"{name}-{index}", "trace.jsonl")
            if text is not None:
                os.makedirs(os.path.dirname(path))
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(json.dumps({"type": "assistant"}) + "\n")
                    handle.write(json.dumps({"type": "result", "result": text}) + "\n")
            runs.append({"score": 1, "tracePath": path})
        self.cases.append({"name": name, "graders": [{"name": grader}], "arms": {"with": runs, "without": []}})

    def grade(self):
        result = os.path.join(self.tmp.name, "result.json")
        with open(result, "w", encoding="utf-8") as handle:
            json.dump({"schemaVersion": 1, "cases": self.cases}, handle)
        proc = subprocess.run([sys.executable, "-I", SCRIPT, result, "--evals", self.evals],
                              env={"PATH": self.bin}, capture_output=True, text=True)
        return proc.returncode, proc.stdout, proc.stderr

    def test_a_run_whose_blocks_pass_their_assertions_passes(self):
        self.add_case("create-x", {CI: ["name=CI"], DEPENDABOT: ["dependabot"]},
                      [created((CI, "name: CI\non: push"), (DEPENDABOT, DEPENDABOT_TEXT))])
        code, out, _ = self.grade()
        self.assertEqual((code, out.strip().splitlines()[-1]), (0, "PASS"), out)
        self.assertIn("create-x#1: PASS", out)

    def test_a_failed_assertion_fails_with_the_case_and_the_check(self):
        self.add_case("create-x", {CI: ["name=CI"]}, [created((CI, "name: Build"))])
        code, out, _ = self.grade()
        self.assertEqual(code, 1)
        self.assertIn("FAIL create-x#1 name:", out)
        self.assertIn("create-x#1: FAIL", out)
        self.assertEqual(out.strip().splitlines()[-1], "FAIL")

    def test_the_check_script_failure_names_the_path(self):
        self.add_case("create-x", {CI: ["name=CI"]}, [created((CI, "name: Build"))])
        _, out, _ = self.grade()
        self.assertIn(CI, [line for line in out.splitlines() if line.startswith("FAIL create-x#1 name:")][0])

    def test_a_path_that_is_asserted_and_not_shown_fails(self):
        self.add_case("create-x", {CI: ["name=CI"], DEPENDABOT: ["dependabot"]}, [created((CI, "name: CI"))])
        code, out, _ = self.grade()
        self.assertEqual(code, 1)
        self.assertIn(f"FAIL create-x#1 written: {DEPENDABOT}", out)

    def test_a_path_that_is_not_asserted_is_not_checked(self):
        self.add_case("create-x", {CI: ["name=CI"]}, [created((CI, "name: CI"), (DEPENDABOT, "garbage"))])
        code, out, _ = self.grade()
        self.assertEqual(code, 0, out)

    def test_an_assertion_with_spaces_is_one_assertion(self):
        self.add_case("create-x", {CI: ["text=playwright install"]},
                      [created((CI, "- run: npx playwright install chromium"))])
        code, out, _ = self.grade()
        self.assertEqual(code, 0, out)

    def test_a_yaml_comment_line_does_not_end_the_created_section(self):
        self.add_case("create-x", {CI: ["text=# note"]}, [created((CI, "name: CI\n# note\n## not a heading"))])
        code, out, _ = self.grade()
        self.assertEqual(code, 0, out)

    def test_a_message_with_no_created_section_fails(self):
        self.add_case("create-x", {CI: ["name=CI"]}, ["# ci-pipelines review: x\n"])
        code, out, _ = self.grade()
        self.assertEqual(code, 1)
        self.assertIn(f"FAIL create-x#1 written: {CI}", out)

    def test_a_missing_trace_fails(self):
        self.add_case("create-x", {CI: ["name=CI"]}, [None])
        code, out, _ = self.grade()
        self.assertEqual(code, 1)
        self.assertIn("FAIL create-x#1 trace:", out)

    def test_each_run_is_graded(self):
        good = created((CI, "name: CI"))
        self.add_case("create-x", {CI: ["name=CI"]}, [good, created((CI, "name: Other")), good])
        code, out, _ = self.grade()
        self.assertEqual(code, 1)
        self.assertIn("create-x#1: PASS", out)
        self.assertIn("create-x#2: FAIL", out)
        self.assertIn("create-x#3: PASS", out)

    def test_a_case_without_the_wrote_ci_grader_is_skipped(self):
        self.add_case("create-no-lockfile", {}, [None], grader="no-write-github")
        self.add_case("create-x", {CI: ["name=CI"]}, [created((CI, "name: CI"))])
        code, out, _ = self.grade()
        self.assertEqual(code, 0, out)
        self.assertNotIn("create-no-lockfile", out)

    def test_a_result_with_no_create_case_is_a_usage_error(self):
        self.add_case("clean", {}, [None], grader="section-summary")
        code, _, err = self.grade()
        self.assertEqual(code, 2)
        self.assertIn("nothing to grade", err)

    def test_an_unreadable_result_is_a_usage_error(self):
        proc = subprocess.run([sys.executable, "-I", SCRIPT, os.path.join(self.tmp.name, "none.json")],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot read the result", proc.stderr)

    def test_an_unreadable_expect_file_is_a_usage_error(self):
        self.add_case("create-x", {CI: ["name=CI"]}, [created((CI, "name: CI"))])
        os.remove(os.path.join(self.evals, "create-x", "expect.json"))
        code, _, err = self.grade()
        self.assertEqual(code, 2)
        self.assertIn("expect.json", err)

    def test_an_unknown_assertion_fails_the_run(self):
        self.add_case("create-x", {CI: ["no-such-assertion"]}, [created((CI, "name: CI"))])
        code, out, _ = self.grade()
        self.assertEqual(code, 1)
        self.assertIn("FAIL create-x#1 check_workflow:", out)
        self.assertIn("no-such-assertion", out)

    def test_a_missing_actionlint_is_reported_and_does_not_fail(self):
        self.add_case("create-x", {CI: ["name=CI"]}, [created((CI, "name: CI"))])
        code, out, _ = self.grade()
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count("NOT RUN actionlint: not on PATH"), 1)

    def test_actionlint_that_passes_is_run_on_each_written_workflow(self):
        self.fake_actionlint()
        self.add_case("create-x", {CI: ["name=CI"], DEPENDABOT: ["dependabot"]},
                      [created((CI, "name: CI"), (DEPENDABOT, DEPENDABOT_TEXT))])
        code, out, _ = self.grade()
        self.assertEqual(code, 0, out)
        self.assertNotIn("NOT RUN", out)
        with open(self.log, encoding="utf-8") as handle:
            calls = handle.read().splitlines()
        self.assertEqual(len(calls), 1, calls)
        self.assertTrue(calls[0].endswith("ci.yml"), calls)

    def test_actionlint_that_fails_fails_the_run(self):
        self.fake_actionlint(fail=True)
        self.add_case("create-x", {CI: ["name=CI"]}, [created((CI, "name: CI"))])
        code, out, _ = self.grade()
        self.assertEqual(code, 1)
        self.assertIn("FAIL create-x#1 actionlint:", out)
        self.assertIn("fake error", out)


if __name__ == "__main__":
    unittest.main()
