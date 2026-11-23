import json
import os
import subprocess
import sys
import tempfile
import unittest

import helper_testing_rules as helper

GRADER = os.path.join(helper.SKILL, "scripts", "grade_testing_write.py")
NEEDS_TOMLLIB = unittest.skipUnless(sys.version_info >= (3, 11), "the grouped check needs Python 3.11 (tomllib)")
HEADER = "| Test | Point | Kind | Size | Group | Reason |\n|---|---|---|---|---|---|\n"
SCOPE_NOTE = "No group: typescript. Tests are placed at the named or derived path.\n"


def file_section(path="tests/a.test.js", rows=None, command="node --test --test-concurrency=2 tests/a.test.js",
                 result="pass", group="none"):
    rows = rows if rows is not None else [("adds two numbers", "add()", "unit", "small", group, "pure; wanted small")]
    body = "".join(f"| {' | '.join(row)} |\n" for row in rows)
    tail = f"Command: {command}\nRun result: {result}\n" if command is not None else ""
    return f"## File: {path}\n\n{HEADER}{body}\n{tail}\n"


def report(sections=None, scope="src/a.js", counts="1 files, 1 pass, 0 fail, 0 not run, 0 bugs", notes=SCOPE_NOTE):
    sections = file_section() if sections is None else sections
    return f"# testing write: {scope}\n\n**Result: {counts}.**\n\n{notes}\n{sections}"


BUG_SECTION = (
    "## Found bugs\n\n| File | Test | Where | Expected | Source |\n|---|---|---|---|---|\n"
    "| tests/a.test.js | adds two numbers | tests/a.test.js:5 | 3 | README line 4 |\n\n"
)
KEPT_SECTION = (
    "## Kept failing\n\n| File | Test | Reason |\n|---|---|---|\n"
    "| tests/a.test.js | adds two numbers | still fails after 2 tries |\n\n"
)
FAILED = file_section(result="fail (adds two numbers)")


class WriteGraderCase(unittest.TestCase):
    def setUp(self):
        self._scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self._scratch.cleanup)
        self.counter = 0

    def scratch_file(self, text, name=None):
        self.counter += 1
        path = os.path.join(self._scratch.name, name or f"f{self.counter}.txt")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def run_grader(self, text, extra=()):
        args = [sys.executable, "-I", GRADER, self.scratch_file(text)] + list(extra)
        return subprocess.run(args, capture_output=True, text=True, encoding="utf-8")

    def assert_pass(self, text, extra=()):
        done = self.run_grader(text, extra)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(done.stdout.strip(), "PASS")

    def assert_fail(self, check, text, extra=()):
        done = self.run_grader(text, extra)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn(f"FAIL {check}:", done.stdout)
        self.assertEqual(done.stdout.strip().splitlines()[-1], "FAIL")
        return done.stdout

    def assert_usage_error(self, done):
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertNotIn("PASS", done.stdout)
        self.assertTrue(done.stderr.strip())


class ReportCheckTest(WriteGraderCase):
    def test_a_valid_report_passes(self):
        self.assert_pass(report())

    def test_report_from_stdin_passes(self):
        done = subprocess.run([sys.executable, "-I", GRADER, "-"], input=report(), capture_output=True,
                              text=True, encoding="utf-8")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_a_missing_or_late_title_fails(self):
        self.assert_fail("title", report().replace("# testing write: src/a.js", "# testing review: src/a.js"))
        self.assert_fail("title", "intro\n" + report())

    def test_a_missing_result_line_fails(self):
        self.assert_fail("result", report().replace("**Result:", "Result:"))

    def test_a_count_mismatch_fails(self):
        out = self.assert_fail("counts", report(counts="1 files, 0 pass, 1 fail, 0 not run, 0 bugs"))
        self.assertIn("pass", out)
        self.assert_fail("counts", report(counts="2 files, 1 pass, 0 fail, 0 not run, 0 bugs"))
        self.assert_fail("counts", report(counts="1 files, 1 pass, 0 fail, 0 not run, 1 bugs"))

    def test_a_bad_kind_or_size_fails(self):
        bad_kind = file_section(rows=[("t", "p", "e2e", "small", "none", "r")])
        self.assert_fail("tables", report(bad_kind))
        bad_size = file_section(rows=[("t", "p", "unit", "tiny", "none", "r")])
        self.assert_fail("tables", report(bad_size))

    def test_a_wrong_table_header_or_an_empty_table_fails(self):
        self.assert_fail("tables", report(file_section().replace("| Test | Point |", "| Name | Point |")))
        self.assert_fail("tables", report(file_section(rows=[])))

    def test_a_missing_or_double_command_or_run_result_fails(self):
        self.assert_fail("command", report(file_section(command=None)))
        self.assert_fail("command", report(file_section().replace("Run result: pass", "Command: x\nRun result: pass")))
        self.assert_fail("run result", report(file_section(command=None)))
        self.assert_fail("run result", report(file_section().replace("Run result: pass", "Run result: pass\nRun result: pass")))

    def test_a_run_result_with_no_valid_form_fails(self):
        self.assert_fail("run result", report(file_section(result="ok")))
        self.assert_fail("run result", report(file_section(result="not run")))

    def test_command_none_needs_not_run(self):
        ok = file_section(command="none", result="not run (no test command is known)", group="none")
        self.assert_pass(report(ok, counts="1 files, 0 pass, 0 fail, 1 not run, 0 bugs"))
        self.assert_fail("command", report(file_section(command="none", result="pass")))
        self.assert_fail("command", report(file_section(command="none", result="fail (adds two numbers)"),
                                           counts="1 files, 0 pass, 1 fail, 0 not run, 0 bugs"))

    def test_an_unknown_or_misordered_section_fails(self):
        self.assert_fail("sections", report(file_section() + "## Summary\n\nx\n"))
        text = report(FAILED + KEPT_SECTION + BUG_SECTION, counts="1 files, 0 pass, 1 fail, 0 not run, 1 bugs")
        self.assert_fail("sections", text)

    def test_a_found_bug_must_be_in_a_file_table_and_in_the_fail_result(self):
        counts = "1 files, 0 pass, 1 fail, 0 not run, 1 bugs"
        self.assert_pass(report(FAILED + BUG_SECTION, counts=counts))
        elsewhere = BUG_SECTION.replace("| adds two numbers |", "| other test |")
        self.assert_fail("found bugs", report(FAILED + elsewhere, counts=counts))
        not_failed = file_section(result="fail (another)")
        self.assert_fail("found bugs", report(not_failed + BUG_SECTION, counts=counts))
        no_file = BUG_SECTION.replace("| tests/a.test.js |", "| tests/zzz.test.js |")
        self.assert_fail("found bugs", report(FAILED + no_file, counts=counts))

    def test_a_found_bug_needs_a_place_and_a_source(self):
        counts = "1 files, 0 pass, 1 fail, 0 not run, 1 bugs"
        self.assert_fail("found bugs", report(FAILED + BUG_SECTION.replace("tests/a.test.js:5", "nowhere"), counts=counts))
        self.assert_fail("found bugs", report(FAILED + BUG_SECTION.replace("README line 4", ""), counts=counts))

    def test_kept_failing_rows_and_the_file_row(self):
        counts = "1 files, 0 pass, 1 fail, 0 not run, 0 bugs"
        self.assert_pass(report(FAILED + KEPT_SECTION, counts=counts))
        self.assert_fail("kept failing", report(file_section(result="fail (another)") + KEPT_SECTION, counts=counts))
        file_row = KEPT_SECTION.replace("| adds two numbers |", "| (file) |")
        named_by_path = file_section(result="fail (tests/a.test.js)")
        self.assert_pass(report(named_by_path + file_row, counts=counts))
        self.assert_fail("kept failing", report(FAILED + file_row, counts=counts))

    def test_the_existing_suffix_is_allowed_for_a_failing_existing_test(self):
        text = file_section(result="fail (old case (existing), adds two numbers)")
        self.assert_pass(report(text, counts="1 files, 0 pass, 1 fail, 0 not run, 0 bugs"))

    def test_the_existing_suffix_on_a_new_test_fails(self):
        text = file_section(result="fail (adds two numbers (existing))")
        self.assert_fail("run result", report(text, counts="1 files, 0 pass, 1 fail, 0 not run, 0 bugs"))

    def test_the_empty_scope_and_failed_intake_forms(self):
        zero = "0 files, 0 pass, 0 fail, 0 not run, 0 bugs"
        self.assert_pass(report("", scope="none", counts=zero, notes="No product file in scope. Name the files to test.\n"))
        self.assert_pass(report("", scope="none", counts=zero, notes="Intake failed: the repo root is missing.\n"))
        self.assert_fail("forms", report("", scope="none", counts=zero, notes=""))
        self.assert_fail("forms", report("", scope="none", counts=zero,
                                          notes="No product file in scope. Name the files to test.\n" + SCOPE_NOTE))
        self.assert_fail("forms", report(file_section(), scope="none", counts=zero,
                                          notes="No product file in scope. Name the files to test.\n"))
        self.assert_fail("forms", report("", scope="none", counts="0 files, 0 pass, 0 fail, 0 not run, 1 bugs",
                                          notes="No product file in scope. Name the files to test.\n"))
        self.assert_fail("forms", report("", scope="src/a.js", counts=zero,
                                          notes="No product file in scope. Name the files to test.\n"))

    def test_notes_each_at_most_once_in_order(self):
        detected = "Detected for this run: the rules file is missing. Run /testing setup to record these.\n"
        self.assert_pass(report(notes=detected + SCOPE_NOTE))
        self.assert_fail("notes", report(notes=detected + detected + SCOPE_NOTE))
        self.assert_fail("notes", report(notes=SCOPE_NOTE + detected))
        self.assert_fail("notes", report(notes=SCOPE_NOTE + SCOPE_NOTE))

    def test_the_setup_command_is_named_only_in_the_fallback_line_and_once(self):
        self.assert_fail("notes", report(notes=SCOPE_NOTE.replace("derived path.", "derived path. Run /testing setup.")))
        twice = "Detected for this run: x. Run /testing setup. Run /testing setup.\n"
        self.assert_fail("notes", report(notes=twice + SCOPE_NOTE))

    def test_the_no_group_line_names_the_named_or_derived_path(self):
        self.assert_pass(report(notes="No group: typescript. Tests are placed at the named or derived path.\n"))
        self.assert_fail("notes", report(notes="No group: typescript. Tests are placed at the named path.\n"))
        self.assert_fail("notes", report(notes=SCOPE_NOTE.replace("derived path.", "derived path. Extra text.")))

    def test_the_no_group_line_matches_the_none_cells(self):
        self.assert_fail("notes", report(notes=""))
        self.assert_fail("notes", report(file_section(group="unit"), notes=SCOPE_NOTE))

    def test_not_written_once_for_each_product_file(self):
        written = "Not written: src/b.js (no test point).\n"
        self.assert_pass(report(scope="src/a.js, src/b.js", notes=SCOPE_NOTE + written))
        self.assert_fail("notes", report(scope="src/a.js, src/b.js", notes=SCOPE_NOTE + written + written))
        self.assert_fail("notes", report(scope="src/a.js", notes=SCOPE_NOTE + written))
        self.assert_fail("notes", report(scope="src/a.js, src/b.js",
                                          notes=SCOPE_NOTE + "Not written: src/b.js (bad reason).\n"))

    def test_a_report_with_every_file_not_written_has_no_file_section(self):
        zero = "0 files, 0 pass, 0 fail, 0 not run, 0 bugs"
        note = "Not written: src/a.js (no test location is known).\n"
        self.assert_pass(report("", counts=zero, notes=note))
        self.assert_fail("notes", report(file_section(), counts="1 files, 1 pass, 0 fail, 0 not run, 0 bugs", notes=note))


@NEEDS_TOMLLIB
class RepoCheckTest(WriteGraderCase):
    RULES = (
        "# Testing rules\n\n```toml\n[[groups]]\nname = \"unit\"\nlanguage = \"typescript\"\n"
        "size = \"small\"\ncommand = \"node --test tests/\"\n\n[[groups]]\nname = \"named\"\nlanguage = \"typescript\"\n"
        "size = \"small\"\ncommand = \"node --test -t foo\"\n```\n"
    )

    def setUp(self):
        super().setUp()
        self.repo = os.path.join(self._scratch.name, "repo")
        self.before = os.path.join(self._scratch.name, "before")
        for folder in (self.repo, self.before):
            os.makedirs(os.path.join(folder, "tests"))
            os.makedirs(os.path.join(folder, "src"))
            os.makedirs(os.path.join(folder, "docs", "agents"))
            self.put(folder, "src/a.js", "export const add = (a, b) => a + b;\n")
        self.put(self.repo, "tests/a.test.js", "assert.equal(add(1, 2), 3);\n")
        self.put(self.repo, "docs/agents/testing.md", self.RULES)

    def put(self, folder, name, text):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
            handle.write(text)

    def run_repo(self, text, expect, use_before=False, extra=()):
        args = ["--repo", self.repo, "--expect", self.scratch_file(json.dumps(expect), "expect.json")]
        if use_before:
            args += ["--before", self.before]
        return self.run_grader(text, args + list(extra))

    def grouped_report(self, group="unit"):
        return report(file_section(group=group), notes="")

    def test_a_written_test_file_with_an_assertion_passes(self):
        done = self.run_repo(report(), {"tests": ["tests/a.test.js"]})
        self.assertEqual(done.returncode, 0, done.stdout)

    def test_a_missing_test_file_fails(self):
        done = self.run_repo(report(), {"tests": ["tests/zzz.test.js"]})
        self.assertIn("FAIL tests:", done.stdout)

    def test_a_go_test_that_fails_through_t_fatalf_holds_an_assertion(self):
        self.put(self.repo, "tests/a.test.js", "if got != 3 {\n\tt.Fatalf(\"got %d\", got)\n}\n")
        done = self.run_repo(report(), {"tests": ["tests/a.test.js"]})
        self.assertEqual(done.returncode, 0, done.stdout)

    def test_a_test_file_with_no_assertion_fails(self):
        self.put(self.repo, "tests/a.test.js", "console.log(add(1, 2));\n")
        done = self.run_repo(report(), {"tests": ["tests/a.test.js"]})
        self.assertIn("FAIL tests:", done.stdout)

    def test_grouped_true_needs_a_selecting_group_and_its_name_in_the_cells(self):
        done = self.run_repo(self.grouped_report("unit"), {"tests": ["tests/a.test.js"], "grouped": {"tests/a.test.js": True}})
        self.assertEqual(done.returncode, 0, done.stdout)
        done = self.run_repo(self.grouped_report("none"), {"tests": ["tests/a.test.js"], "grouped": {"tests/a.test.js": True}})
        self.assertIn("FAIL grouped:", done.stdout)

    def test_grouped_true_with_no_selecting_group_fails(self):
        self.put(self.repo, "docs/agents/testing.md", self.RULES.replace("node --test tests/", "node --test other/"))
        done = self.run_repo(self.grouped_report("unit"), {"tests": ["tests/a.test.js"], "grouped": {"tests/a.test.js": True}})
        self.assertIn("FAIL grouped:", done.stdout)

    def test_a_group_with_a_name_filter_is_skipped(self):
        done = self.run_repo(self.grouped_report("named"), {"tests": ["tests/a.test.js"], "grouped": {"tests/a.test.js": True}})
        self.assertIn("FAIL grouped:", done.stdout)

    def test_a_group_command_with_no_operand_selects_every_file(self):
        self.put(self.repo, "docs/agents/testing.md", self.RULES.replace("node --test tests/", "node --test"))
        done = self.run_repo(self.grouped_report("unit"), {"tests": ["tests/a.test.js"], "grouped": {"tests/a.test.js": True}})
        self.assertEqual(done.returncode, 0, done.stdout)

    def test_grouped_false_needs_group_none(self):
        done = self.run_repo(report(), {"tests": ["tests/a.test.js"], "grouped": {"tests/a.test.js": False}})
        self.assertEqual(done.returncode, 0, done.stdout)
        done = self.run_repo(self.grouped_report("unit"), {"tests": ["tests/a.test.js"], "grouped": {"tests/a.test.js": False}})
        self.assertIn("FAIL grouped:", done.stdout)

    def test_a_changed_product_file_fails(self):
        done = self.run_repo(report(), {"tests": ["tests/a.test.js"], "product": ["src/a.js"]}, use_before=True)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.put(self.repo, "src/a.js", "export const add = (a, b) => a - b;\n")
        done = self.run_repo(report(), {"tests": ["tests/a.test.js"], "product": ["src/a.js"]}, use_before=True)
        self.assertIn("FAIL product:", done.stdout)

    def test_an_existing_test_line_removed_or_moved_fails(self):
        self.put(self.before, "tests/a.test.js", "line one\nline two\n")
        expect = {"tests": ["tests/a.test.js"], "existing": ["tests/a.test.js"]}
        self.put(self.repo, "tests/a.test.js", "line one\nassert 1\nline two\n")
        self.assertEqual(self.run_repo(report(), expect, use_before=True).returncode, 0)
        self.put(self.repo, "tests/a.test.js", "line one\nassert 1\n")
        self.assertIn("FAIL existing:", self.run_repo(report(), expect, use_before=True).stdout)
        self.put(self.repo, "tests/a.test.js", "line two\nline one\nassert 1\n")
        self.assertIn("FAIL existing:", self.run_repo(report(), expect, use_before=True).stdout)

    def test_result_words_per_file(self):
        self.assertEqual(self.run_repo(report(), {"tests": ["tests/a.test.js"], "result": {"tests/a.test.js": "pass"}}).returncode, 0)
        done = self.run_repo(report(), {"tests": ["tests/a.test.js"], "result": {"tests/a.test.js": "fail"}})
        self.assertIn("FAIL result:", done.stdout)

    def test_bugs_need_a_row_with_a_source_and_an_empty_list_means_none(self):
        counts = "1 files, 0 pass, 1 fail, 0 not run, 1 bugs"
        text = report(FAILED + BUG_SECTION, counts=counts)
        base = {"tests": ["tests/a.test.js"]}
        self.assertEqual(self.run_repo(text, dict(base, bugs=["adds two numbers"])).returncode, 0)
        self.assertIn("FAIL bugs:", self.run_repo(report(), dict(base, bugs=["adds two numbers"])).stdout)
        self.assertIn("FAIL bugs:", self.run_repo(text, dict(base, bugs=[])).stdout)
        self.assertEqual(self.run_repo(report(), dict(base, bugs=[])).returncode, 0)

    def test_command_contains_every_command_line(self):
        base = {"tests": ["tests/a.test.js"]}
        self.assertEqual(self.run_repo(report(), dict(base, command_contains="--test-concurrency=2")).returncode, 0)
        self.assertIn("FAIL command_contains:", self.run_repo(report(), dict(base, command_contains="--workers=2")).stdout)

    def test_each_fallback_value(self):
        base = {"tests": ["tests/a.test.js"]}
        detected = "Detected for this run: the rules file is missing. Run /testing setup to record these.\n"
        error = "Rules file error: invalid value (line 4). Every setting is detected for this run. Run /testing setup.\n"
        self.assertEqual(self.run_repo(report(), dict(base, fallback="none")).returncode, 0)
        self.assertEqual(self.run_repo(report(notes=detected + SCOPE_NOTE), dict(base, fallback="detected")).returncode, 0)
        self.assertEqual(self.run_repo(report(notes=error + SCOPE_NOTE), dict(base, fallback="error", error_line=4)).returncode, 0)
        self.assertIn("FAIL fallback:", self.run_repo(report(notes=detected + SCOPE_NOTE), dict(base, fallback="none")).stdout)
        self.assertIn("FAIL fallback:", self.run_repo(report(), dict(base, fallback="detected")).stdout)
        self.assertIn("FAIL fallback:", self.run_repo(report(notes=error + SCOPE_NOTE), dict(base, fallback="detected")).stdout)
        self.assertIn("FAIL fallback:", self.run_repo(report(notes=error + SCOPE_NOTE), dict(base, fallback="error", error_line=7)).stdout)
        self.assertIn("FAIL fallback:", self.run_repo(report(notes=detected + SCOPE_NOTE), dict(base, fallback="error", error_line=4)).stdout)


class UsageErrorTest(WriteGraderCase):
    def test_a_missing_report_is_a_usage_error(self):
        done = subprocess.run([sys.executable, "-I", GRADER, os.path.join(self._scratch.name, "none.txt")],
                              capture_output=True, text=True, encoding="utf-8")
        self.assert_usage_error(done)

    def test_repo_without_expect_and_expect_without_repo(self):
        folder = self.scratch_file("x", "repo/x.txt")
        self.assert_usage_error(self.run_grader(report(), ["--repo", os.path.dirname(folder)]))
        expect = self.scratch_file(json.dumps({"tests": ["a"]}), "expect.json")
        self.assert_usage_error(self.run_grader(report(), ["--expect", expect]))

    def test_before_without_repo_is_a_usage_error(self):
        self.assert_usage_error(self.run_grader(report(), ["--before", self._scratch.name]))

    def test_product_or_existing_without_before(self):
        folder = os.path.dirname(self.scratch_file("x", "repo/x.txt"))
        for key in ("product", "existing"):
            with self.subTest(key):
                expect = self.scratch_file(json.dumps({"tests": ["a"], key: ["a"]}), "expect.json")
                self.assert_usage_error(self.run_grader(report(), ["--repo", folder, "--expect", expect]))

    def test_a_bad_expect_file_is_a_usage_error(self):
        folder = os.path.dirname(self.scratch_file("x", "repo/x.txt"))
        cases = {
            "not json": "{",
            "not an object": "[]",
            "unknown key": json.dumps({"tests": ["a"], "zzz": 1}),
            "no tests": json.dumps({"bugs": []}),
            "bad fallback": json.dumps({"tests": ["a"], "fallback": "x"}),
            "error without a line": json.dumps({"tests": ["a"], "fallback": "error"}),
            "bad result word": json.dumps({"tests": ["a"], "result": {"a": "ok"}}),
        }
        for name, text in cases.items():
            with self.subTest(name):
                expect = self.scratch_file(text, "expect.json")
                self.assert_usage_error(self.run_grader(report(), ["--repo", folder, "--expect", expect]))


@NEEDS_TOMLLIB
class RustGroupModelTest(WriteGraderCase):
    """The grouped check for `.rs` files: `--test <target>` selects files, other selectors skip a group."""
    FILES = ("tests/foo.rs", "tests/it.rs", "tests/it/main.rs", "tests/it/a.rs")

    def setUp(self):
        super().setUp()
        self.repo = os.path.join(self._scratch.name, "repo")
        for name in self.FILES:
            path = os.path.join(self.repo, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("assert_eq!(1, 1);\n")
        os.makedirs(os.path.join(self.repo, "docs", "agents"))

    def selects(self, command, path):
        rules = f"# Rules\n\n```toml\n[[groups]]\nname = \"g\"\nlanguage = \"rust\"\nsize = \"small\"\ncommand = {json.dumps(command)}\n```\n"
        with open(os.path.join(self.repo, "docs", "agents", "testing.md"), "w", encoding="utf-8") as handle:
            handle.write(rules)
        text = report(file_section(path=path, group="g"), scope="src/foo.rs", notes="")
        expect = self.scratch_file(json.dumps({"tests": [path], "grouped": {path: True}}), "expect.json")
        done = self.run_grader(text, ["--repo", self.repo, "--expect", expect])
        self.assertIn(done.returncode, (0, 1), done.stdout + done.stderr)
        return done.returncode == 0

    def test_a_group_with_no_selector_selects_the_derived_path(self):
        self.assertTrue(self.selects("cargo nextest run", "tests/foo.rs"))

    def test_a_test_flag_selects_the_files_of_its_target(self):
        for command in ("cargo nextest run --test it", "cargo nextest run --test=it"):
            for path in ("tests/it.rs", "tests/it/main.rs", "tests/it/a.rs"):
                with self.subTest(command=command, path=path):
                    self.assertTrue(self.selects(command, path))
            with self.subTest(command=command, path="tests/foo.rs"):
                self.assertFalse(self.selects(command, "tests/foo.rs"))

    def test_the_value_of_a_flag_is_not_a_name_filter(self):
        self.assertTrue(self.selects("cargo nextest run --profile ci -j 2", "tests/foo.rs"))
        self.assertTrue(self.selects("CI=true cargo test --no-fail-fast -- --test-threads=2", "tests/foo.rs"))

    def test_a_group_with_a_selector_that_is_not_a_test_target_selects_no_file(self):
        for command in (
            "cargo nextest run slow_", "cargo test -- --skip slow_", "cargo nextest run -p other",
            "cargo nextest run --package other", "cargo nextest run --lib", "cargo test --doc",
            "cargo nextest run -E 'test(x)'", "cargo nextest run --test it slow_",
        ):
            with self.subTest(command):
                self.assertFalse(self.selects(command, "tests/it.rs"))


@NEEDS_TOMLLIB
class GroupModelBase(WriteGraderCase):
    """Scratch repo and the `selects` helper for the TypeScript group reader tests (no test of its own)."""
    FILES = ("src/price.test.ts", "tests/a.test.ts", "tests/unit/b.test.ts", "src/deep/c.test.ts")

    def setUp(self):
        super().setUp()
        self.repo = os.path.join(self._scratch.name, "repo")
        for name in self.FILES:
            path = os.path.join(self.repo, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("expect(1).toBe(1);\n")
        os.makedirs(os.path.join(self.repo, "docs", "agents"))

    def selects(self, command, path):
        rules = f"# Rules\n\n```toml\n[[groups]]\nname = \"g\"\nlanguage = \"typescript\"\nsize = \"small\"\ncommand = {json.dumps(command)}\n```\n"
        with open(os.path.join(self.repo, "docs", "agents", "testing.md"), "w", encoding="utf-8") as handle:
            handle.write(rules)
        text = report(file_section(path=path, group="g"), scope="src/price.ts", notes="")
        expect = self.scratch_file(json.dumps({"tests": [path], "grouped": {path: True}}), "expect.json")
        done = self.run_grader(text, ["--repo", self.repo, "--expect", expect])
        self.assertIn(done.returncode, (0, 1), done.stdout + done.stderr)
        return done.returncode == 0


@NEEDS_TOMLLIB
class VitestGroupModelTest(GroupModelBase):
    """The grouped check for TypeScript groups that are an exec form of Vitest (Table 2, write column)."""

    def test_a_group_with_no_selector_selects_every_file(self):
        for command in ("npx vitest run", "pnpm exec vitest run", "yarn vitest run", "bunx vitest run", "npx vitest --run"):
            with self.subTest(command):
                self.assertTrue(self.selects(command, "tests/a.test.ts"))

    def test_a_path_operand_selects_a_file_whose_path_contains_it(self):
        self.assertTrue(self.selects("npx vitest run src/price", "src/price.test.ts"))
        self.assertTrue(self.selects("npx vitest run src tests", "tests/a.test.ts"))

    def test_an_operand_that_is_not_a_substring_selects_no_file(self):
        self.assertFalse(self.selects("npx vitest run src/other", "src/price.test.ts"))

    def test_a_fixed_flag_with_a_value_is_not_an_operand(self):
        self.assertTrue(self.selects("CI=true npx vitest run --maxWorkers 2 --reporter=verbose", "tests/a.test.ts"))
        self.assertTrue(self.selects("npx vitest run --maxWorkers=2", "tests/a.test.ts"))

    def test_a_project_token_narrows_nothing_because_the_grader_cannot_read_the_config(self):
        for command in ("npx vitest run --project unit", "npx vitest run -p unit", "npx vitest run --project=unit"):
            with self.subTest(command):
                self.assertTrue(self.selects(command, "src/price.test.ts"))
        self.assertFalse(self.selects("npx vitest run --project unit src/other", "src/price.test.ts"))

    def test_the_subcommand_is_only_the_first_word_after_the_exec_form(self):
        for command in ("npx vitest --project list --run src", "npx vitest --reporter list --run src"):
            with self.subTest(command):
                self.assertTrue(self.selects(command, "src/price.test.ts"))
        self.assertFalse(self.selects("npx vitest list --run src", "src/price.test.ts"))

    def test_a_later_word_equal_to_a_subcommand_is_an_operand(self):
        self.assertFalse(self.selects("npx vitest --run run", "src/deep/c.test.ts"))

    def test_a_bare_double_dash_is_dropped(self):
        self.assertTrue(self.selects("npx vitest run -- src/price", "src/price.test.ts"))
        self.assertTrue(self.selects("npx vitest run --", "src/price.test.ts"))

    def test_a_leading_dot_slash_of_an_operand_is_dropped(self):
        self.assertTrue(self.selects("npx vitest run ./src/price", "src/price.test.ts"))
        self.assertFalse(self.selects("npx vitest run ./src/other", "src/price.test.ts"))

    def test_a_boolean_flag_with_an_inline_value_is_not_an_operand(self):
        for command in ("npx vitest run --silent=false", "npx vitest run --coverage=false src"):
            with self.subTest(command):
                self.assertTrue(self.selects(command, "src/price.test.ts"))

    def test_a_launcher_form_that_is_not_an_exec_form_is_a_wrapper(self):
        for command in (
            "npx -y vitest run", "npx --no-install vitest run", "pnpm vitest run", "CI=true npm exec vitest run",
        ):
            with self.subTest(command):
                self.assertFalse(self.selects(command, "src/price.test.ts"))

    def test_every_exec_form_of_the_entry_narrows_by_path(self):
        for prefix in ("npx vitest", "pnpm exec vitest", "yarn vitest", "bunx vitest"):
            command = prefix + " run src/price"
            with self.subTest(command):
                self.assertTrue(self.selects(command, "src/price.test.ts"))
                self.assertFalse(self.selects(command, "tests/a.test.ts"))

    def test_a_shell_marker_in_an_exec_form_makes_a_wrapper(self):
        for command in (
            "npx vitest run src/price && tsc", "npx vitest run src/price | tee out", "npx vitest run src/price > out.txt",
            "npx vitest run && tsc", "npx vitest run; true",
        ):
            with self.subTest(command):
                self.assertFalse(self.selects(command, "src/price.test.ts"))

    def test_the_flag_name_tuples_do_not_overlap(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("grade_testing_write", GRADER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        groups = [
            module.VITEST_FIXED_FLAGS, module.VITEST_FIXED_VALUE_FLAGS, module.VITEST_UPDATE_FLAGS,
            module.VITEST_NAME_FLAGS, module.VITEST_PROJECT_FLAGS,
        ]
        every = [flag for group in groups for flag in group]
        self.assertEqual(len(every), len(set(every)))

    def test_a_name_filter_or_unreadable_token_selects_no_file(self):
        for command in (
            "npx vitest run -t slow",
            "npx vitest run --testNamePattern slow", "npx vitest run --changed",
            "npx vitest run --exclude x", "npx vitest run src/price.test.ts:12",
        ):
            with self.subTest(command):
                self.assertFalse(self.selects(command, "src/price.test.ts"))

    def test_a_directory_selects_the_files_below_it_and_is_an_intersection_with_an_operand(self):
        for command in ("npx vitest run --dir src", "npx vitest run --dir=./src/", "npx vitest run --dir src price"):
            with self.subTest(command):
                self.assertTrue(self.selects(command, "src/price.test.ts"))
                self.assertFalse(self.selects(command, "tests/a.test.ts"))
        self.assertFalse(self.selects("npx vitest run --dir src other", "src/price.test.ts"))

    def test_a_command_that_table_1_does_not_run_selects_no_file(self):
        for command in (
            "npx vitest", "npx vitest watch", "npx vitest --watch", "npx vitest run -u", "npx vitest run --update=all",
            "npx vitest list --filesOnly", "npx vitest bench", "npx vitest related src/price.ts",
        ):
            with self.subTest(command):
                self.assertFalse(self.selects(command, "src/price.test.ts"))

    def test_an_update_value_of_none_is_not_an_update_mode(self):
        self.assertTrue(self.selects("npx vitest run --update=none", "tests/a.test.ts"))

    def test_a_wrapper_keeps_the_old_result(self):
        self.assertTrue(self.selects("npm test", "tests/a.test.ts"))
        self.assertTrue(self.selects("jest", "tests/a.test.ts"))


@NEEDS_TOMLLIB
class JestGroupModelTest(GroupModelBase):
    """The grouped check for TypeScript groups that are an exec form of Jest (Table J2, write column)."""

    def test_a_group_with_no_selector_selects_every_file(self):
        for command in ("npx jest --ci", "pnpm exec jest", "yarn jest", "bunx jest", "CI=true npx jest --ci --json"):
            with self.subTest(command):
                self.assertTrue(self.selects(command, "tests/a.test.ts"))

    def test_a_path_operand_is_a_regular_expression_on_the_path(self):
        self.assertTrue(self.selects("npx jest src/price", "src/price.test.ts"))
        self.assertTrue(self.selects("npx jest src tests", "tests/a.test.ts"))
        self.assertTrue(self.selects("npx jest 'src/.*\\.test\\.ts'", "src/price.test.ts"))
        self.assertFalse(self.selects("npx jest src/other", "src/price.test.ts"))

    def test_test_path_patterns_always_reads_as_a_regular_expression(self):
        self.assertTrue(self.selects("npx jest --testPathPatterns tests/a", "tests/a.test.ts"))
        self.assertTrue(self.selects("npx jest --testPathPatterns=tests/a", "tests/a.test.ts"))
        self.assertFalse(self.selects("npx jest --runTestsByPath --testPathPatterns src/other", "src/price.test.ts"))

    def test_an_operand_that_starts_with_a_caret_or_slash_selects_no_file(self):
        for command in ("npx jest ^src/price", "npx jest /src/price", "npx jest src/price ^tests"):
            with self.subTest(command):
                self.assertFalse(self.selects(command, "src/price.test.ts"))

    def test_run_tests_by_path_reads_an_operand_as_an_equal_path_with_a_dropped_dot_slash(self):
        self.assertTrue(self.selects("npx jest --runTestsByPath ./src/price.test.ts", "src/price.test.ts"))
        self.assertTrue(self.selects("npx jest --runTestsByPath src/price.test.ts tests/a.test.ts", "tests/a.test.ts"))
        self.assertFalse(self.selects("npx jest --runTestsByPath src/price", "src/price.test.ts"))

    def test_a_fixed_flag_with_a_value_is_not_an_operand(self):
        self.assertTrue(self.selects("npx jest --maxWorkers 2 -w 2 --ci", "tests/a.test.ts"))
        self.assertTrue(self.selects("npx jest --maxWorkers=2 --outputFile out.json", "tests/a.test.ts"))

    def test_a_project_name_filter_or_unreadable_token_selects_no_file(self):
        for command in (
            "npx jest --selectProjects unit", "npx jest -t slow", "npx jest --testNamePattern slow",
            "npx jest --onlyChanged", "npx jest --shard 1/2", "npx jest --testPathIgnorePatterns tests/slow",
        ):
            with self.subTest(command):
                self.assertFalse(self.selects(command, "src/price.test.ts"))

    def test_an_update_mode_or_a_watch_marker_selects_no_file(self):
        for command in (
            "npx jest -u", "npx jest --updateSnapshot", "npx jest --updateSnapshot=true", "npx jest --watch",
            "npx jest --watchAll", "npx jest --listTests",
        ):
            with self.subTest(command):
                self.assertFalse(self.selects(command, "src/price.test.ts"))

    def test_an_update_snapshot_value_of_false_is_not_an_update_mode(self):
        self.assertTrue(self.selects("npx jest --updateSnapshot=false", "tests/a.test.ts"))

    def test_a_bare_update_snapshot_token_is_an_update_mode_whatever_follows_it(self):
        for command in ("npx jest --updateSnapshot false", "npx jest --updateSnapshot tests/a"):
            with self.subTest(command):
                self.assertFalse(self.selects(command, "tests/a.test.ts"))

    def test_a_wrapper_and_jest_alone_keep_the_old_result(self):
        self.assertTrue(self.selects("npm test", "tests/a.test.ts"))
        self.assertTrue(self.selects("jest --ci", "tests/a.test.ts"))
        self.assertFalse(self.selects("jest -t slow", "tests/a.test.ts"))

    def test_a_wrapper_selects_no_file_even_when_an_operand_matches(self):
        for command in ("npx jest tests/a && tsc", "npx jest --ci; tsc", "npx jest tests/a | cat", "npx jest tests/a > out.txt"):
            with self.subTest(command):
                self.assertFalse(self.selects(command, "tests/a.test.ts"))
        self.assertTrue(self.selects("npx jest 'tests/(a|b)'", "tests/a.test.ts"))

    def test_a_boolean_flag_with_an_inline_value_is_not_an_operand(self):
        self.assertTrue(self.selects("npx jest --ci=true --runInBand=true", "tests/a.test.ts"))
        self.assertFalse(self.selects("npx jest --ci=true tests/a", "src/price.test.ts"))

    def test_several_operands_and_combined_selectors_select_the_union(self):
        self.assertTrue(self.selects("npx jest src/price tests/unit", "tests/unit/b.test.ts"))
        self.assertTrue(self.selects("npx jest --testPathPatterns src/price tests/unit", "tests/unit/b.test.ts"))
        self.assertTrue(self.selects("npx jest --testPathPatterns src/price --runTestsByPath tests/a.test.ts", "tests/a.test.ts"))
        self.assertFalse(self.selects("npx jest --testPathPatterns src/price tests/unit", "tests/a.test.ts"))

    def test_a_caret_value_of_test_path_patterns_selects_no_file(self):
        self.assertFalse(self.selects("npx jest --testPathPatterns ^tests/a", "tests/a.test.ts"))

    def test_run_tests_by_path_does_not_read_a_caret_or_slash_operand_as_a_regular_expression(self):
        self.assertFalse(self.selects("npx jest --runTestsByPath /tests/a.test.ts", "tests/a.test.ts"))
        self.assertTrue(self.selects("npx jest --runTestsByPath ^x tests/a.test.ts", "tests/a.test.ts"))

    def test_an_invalid_regular_expression_selects_no_file_whatever_its_place(self):
        for command in ("npx jest tests/a '('", "npx jest '(' tests/a"):
            with self.subTest(command):
                self.assertFalse(self.selects(command, "tests/a.test.ts"))


@NEEDS_TOMLLIB
class NodeTestGroupModelTest(GroupModelBase):
    """The grouped check for TypeScript groups that are `node --test` commands (Table N2, write column)."""

    def test_a_group_with_no_operand_selects_every_file(self):
        for command in ("node --test", "node --import tsx --test", "CI=true node --test --test-concurrency=2"):
            with self.subTest(command):
                self.assertTrue(self.selects(command, "tests/a.test.ts"))

    def test_a_file_a_folder_or_a_glob_operand_selects_the_files_it_names(self):
        self.assertTrue(self.selects("node --test tests/a.test.ts", "tests/a.test.ts"))
        self.assertTrue(self.selects("node --test ./tests/unit/", "tests/unit/b.test.ts"))
        self.assertTrue(self.selects("node --test tests", "tests/unit/b.test.ts"))
        self.assertTrue(self.selects("node --test 'tests/**/*.test.ts'", "tests/unit/b.test.ts"))
        self.assertTrue(self.selects("node --test 'tests/**/*.test.ts'", "tests/a.test.ts"))
        self.assertTrue(self.selects("node --test src/other tests/a.test.ts", "tests/a.test.ts"))

    def test_a_star_does_not_cross_a_folder(self):
        self.assertFalse(self.selects("node --test 'tests/*.test.ts'", "tests/unit/b.test.ts"))
        self.assertTrue(self.selects("node --test 'tests/*.test.ts'", "tests/a.test.ts"))

    def test_an_operand_that_names_no_file_selects_no_file(self):
        self.assertFalse(self.selects("node --test tests/unit", "tests/a.test.ts"))
        self.assertFalse(self.selects("node --test src/other.test.ts", "src/price.test.ts"))

    def test_a_fixed_flag_with_a_value_is_not_an_operand(self):
        self.assertTrue(self.selects("node --import tsx --test --test-concurrency 2 --test-reporter spec", "tests/a.test.ts"))
        self.assertTrue(self.selects("node --test --test-reporter=spec --test-timeout=5000", "tests/a.test.ts"))

    def test_a_name_filter_unreadable_token_watch_marker_or_update_mode_selects_no_file(self):
        for command in (
            "node --test -t slow", "node --test --test-name-pattern slow", "node --test --test-skip-pattern slow",
            "node --test --test-shard=1/2", "node --test --watch", "node --test --watch-path src",
            "node --test --test-update-snapshots",
        ):
            with self.subTest(command):
                self.assertFalse(self.selects(command, "src/price.test.ts"))

    def test_a_command_with_no_test_token_keeps_the_old_result(self):
        self.assertTrue(self.selects("npm test", "tests/a.test.ts"))

    def test_a_wrapper_selects_no_file_even_when_an_operand_matches(self):
        for command in ("node --test tests/a.test.ts && tsc", "node --test; tsc", "node --test tests | cat"):
            with self.subTest(command):
                self.assertFalse(self.selects(command, "tests/a.test.ts"))
        self.assertTrue(self.selects("node --test 'tests/*.test.ts'", "tests/a.test.ts"))

    def test_a_dot_or_dot_slash_folder_selects_every_file(self):
        for command in ("node --test .", "node --test ./"):
            with self.subTest(command):
                self.assertTrue(self.selects(command, "tests/unit/b.test.ts"))

    def test_several_operands_and_combined_selectors_select_the_union(self):
        self.assertTrue(self.selects("node --test src tests/unit", "tests/unit/b.test.ts"))
        self.assertTrue(self.selects("node --test tests/a.test.ts 'tests/**/*.test.ts'", "tests/unit/b.test.ts"))
        self.assertFalse(self.selects("node --test src tests/unit", "tests/a.test.ts"))


if __name__ == "__main__":
    unittest.main()
