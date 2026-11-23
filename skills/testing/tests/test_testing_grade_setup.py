import json
import os
import subprocess
import sys
import tempfile
import unittest

import helper_testing_rules as helper

GRADER = os.path.join(helper.SKILL, "scripts", "grade_testing_setup.py")
NEEDS_TOMLLIB = unittest.skipUnless(sys.version_info >= (3, 11), "intake.py needs Python 3.11 (tomllib)")
NO_LANGUAGE = "languages = []\ngroups = []\n\n[commands]\n[runner]\n[layout]\n[libraries]\n"
PROSE = "## Conventions\n\n- Keep tests small.\n\n## Disabled rules\n\n- RUN-05: slow CI hardware.\n"


class GradeSetupCase(unittest.TestCase):
    def setUp(self):
        self.repo = helper.Repo()
        self.addCleanup(self.repo.close)
        self._scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self._scratch.cleanup)

    def scratch_file(self, name, text):
        path = os.path.join(self._scratch.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def run_grader(self, expect=None, before_text=None, repo=None, extra=()):
        args = [sys.executable, "-I", GRADER, "--repo", repo or self.repo.root,
                "--expect", self.scratch_file("expect.json", json.dumps(expect or {}))]
        if before_text is not None:
            args += ["--before", self.scratch_file("before.md", before_text)]
        return subprocess.run(args + list(extra), capture_output=True, text=True, encoding="utf-8")

    def assert_pass(self, **kwargs):
        done = self.run_grader(**kwargs)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(done.stdout.strip(), "PASS")

    def assert_fail(self, check, **kwargs):
        done = self.run_grader(**kwargs)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn(f"FAIL {check}:", done.stdout)
        self.assertEqual(done.stdout.strip().splitlines()[-1], "FAIL")
        return done.stdout

    def assert_usage_error(self, done):
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertNotIn("PASS", done.stdout)
        self.assertNotIn("FAIL", done.stdout)
        self.assertTrue(done.stderr.strip())


@NEEDS_TOMLLIB
class IntakeCheckTest(GradeSetupCase):
    def test_a_complete_file_passes(self):
        self.repo.write(helper.doc(helper.FULL_BLOCK))
        self.assert_pass()

    def test_a_missing_section_fails_intake(self):
        self.repo.write(helper.doc(helper.block(drop=("commands.rust",))))
        out = self.assert_fail("intake")
        self.assertIn("commands.rust", out)

    def test_no_rules_file_fails_intake(self):
        self.assert_fail("intake")

    def test_an_unknown_id_fails_intake(self):
        self.repo.write(helper.doc(helper.block(replace={"rules": '[rules]\ndisabled = ["ZZZ-99"]\n'})))
        out = self.assert_fail("intake")
        self.assertIn("ZZZ-99", out)

    def test_a_disabled_id_without_a_reason_fails_intake(self):
        self.repo.write(helper.doc(helper.block(replace={"rules": '[rules]\ndisabled = ["RUN-05"]\n'})))
        self.assert_fail("intake")

    def test_a_disabled_id_with_a_reason_passes(self):
        self.repo.write(helper.doc(
            helper.block(replace={"rules": '[rules]\ndisabled = ["RUN-05"]\n'}), prose_after=PROSE))
        self.assert_pass()

    def test_an_empty_array_at_the_top_is_not_reported_missing(self):
        self.repo.write(helper.doc(helper.block(drop=("groups",), top="groups = []\n")))
        self.assert_pass()

    def test_a_missing_commands_entry_passes_only_with_allow_missing(self):
        self.repo.write(helper.doc(helper.block(replace={"commands.typescript": "[commands.typescript]\n"})))
        self.assert_fail("intake")
        self.assert_pass(expect={"allow_missing": ["commands.typescript"]})

    def test_a_no_language_file_passes(self):
        self.repo.write(helper.doc(NO_LANGUAGE))
        self.assert_pass()

    def test_an_unclosed_fence_fails_intake_and_skips_the_later_checks(self):
        self.repo.put("docs/agents/testing.md", "# T\n```toml\n" + helper.FULL_BLOCK)
        out = self.assert_fail("intake", expect={"set": {"limits.small_ms": 1}, "contains": ["x"]})
        self.assertNotIn("FAIL set", out)
        self.assertNotIn("FAIL contains", out)

    def test_a_second_toml_block_fails_intake(self):
        text = helper.doc(helper.FULL_BLOCK) + "\n```toml\n[x]\n```\n"
        self.repo.write(text)
        self.assert_fail("intake")

    def test_an_info_string_after_the_fence_is_read_as_intake_reads_it(self):
        text = "# T\n\n```toml title\n" + helper.FULL_BLOCK + "```\n\n- Keep tests small.\n"
        self.repo.write(text)
        self.assert_pass(expect={"contains": ["- Keep tests small."]})


@NEEDS_TOMLLIB
class ExpectationTest(GradeSetupCase):
    def setUp(self):
        super().setUp()
        self.repo.write(helper.doc(helper.FULL_BLOCK, prose_after=PROSE))

    def test_set_passes_on_a_match_and_fails_on_a_mismatch(self):
        self.assert_pass(expect={"set": {"limits.small_ms": 100}})
        self.assert_fail("set", expect={"set": {"limits.small_ms": 5}})
        self.assert_fail("set", expect={"set": {"limits.nothing": 1}})

    def test_set_compares_a_list_as_one_value(self):
        self.assert_pass(expect={"set": {"rules.disabled": []}})
        self.assert_fail("set", expect={"set": {"rules.disabled": ["RUN-05"]}})

    def test_set_does_not_match_a_boolean_with_a_number(self):
        self.repo.write(helper.doc(helper.block(replace={"limits": "[limits]\nsmall_ms = true\n"}), prose_after=PROSE))
        self.assert_pass(expect={"set": {"limits.small_ms": True}})
        self.assert_fail("set", expect={"set": {"limits.small_ms": 1}})

    def test_set_does_not_match_a_boolean_inside_a_list_with_a_number(self):
        self.repo.write(helper.doc(helper.block(replace={"limits": "[limits]\nsmall_ms = [true]\n"}), prose_after=PROSE))
        self.assert_pass(expect={"set": {"limits.small_ms": [True]}})
        self.assert_fail("set", expect={"set": {"limits.small_ms": [1]}})

    def test_unset_fails_on_a_present_path(self):
        self.assert_pass(expect={"unset": ["limits.medium_ms"]})
        self.assert_fail("unset", expect={"unset": ["limits.small_ms"]})

    def test_contains_needs_a_whole_line_of_the_prose(self):
        self.assert_pass(expect={"contains": ["- RUN-05: slow CI hardware."]})
        self.assert_fail("contains", expect={"contains": ["- RUN-05: slow"]})

    def test_contains_does_not_read_the_toml_block(self):
        self.assert_fail("contains", expect={"contains": ['small_ms = 100']})

    def test_absent_fails_on_a_string_anywhere_in_the_file(self):
        self.assert_pass(expect={"absent": ["FOO-99"]})
        self.assert_fail("absent", expect={"absent": ["small_ms"]})

    def test_invalid_utf8_gives_a_fail_line_and_a_failing_exit_code(self):
        self.repo.put("docs/agents/testing.md", b"\xff\xfe not utf-8")
        done = self.run_grader()
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("FAIL intake:", done.stdout)
        self.assertEqual(done.stdout.strip().splitlines()[-1], "FAIL")
        self.assertNotIn("Traceback", done.stderr)

    def test_a_missing_repo_folder_gives_a_fail_line_and_a_failing_exit_code(self):
        done = self.run_grader(repo=os.path.join(self.repo.root, "missing"))
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("FAIL intake:", done.stdout)
        self.assertNotIn("Traceback", done.stderr)

    def test_a_file_with_a_bom_and_crlf_lines_is_read(self):
        text = helper.doc(helper.FULL_BLOCK, prose_after=PROSE).replace("\n", "\r\n")
        self.repo.put("docs/agents/testing.md", b"\xef\xbb\xbf" + text.encode("utf-8"))
        self.assert_pass(expect={"contains": ["- Keep tests small."]})


@NEEDS_TOMLLIB
class BeforeTest(GradeSetupCase):
    BEFORE = helper.doc(helper.FULL_BLOCK, prose_after=PROSE)

    def after(self, block=None, prose=PROSE):
        self.repo.write(helper.doc(block or helper.FULL_BLOCK, prose_after=prose))

    def test_an_unchanged_file_passes(self):
        self.after()
        self.assert_pass(before_text=self.BEFORE)

    def test_a_changed_value_that_is_not_approved_fails_settings(self):
        self.after(helper.block(replace={"limits": "[limits]\nsmall_ms = 50\n"}))
        out = self.assert_fail("settings", before_text=self.BEFORE)
        self.assertIn("limits.small_ms", out)

    def test_a_changed_value_that_is_approved_passes(self):
        self.after(helper.block(replace={"limits": "[limits]\nsmall_ms = 50\n"}))
        self.assert_pass(before_text=self.BEFORE, expect={"set": {"limits.small_ms": 50}})

    def test_a_nested_set_path_does_not_approve_a_changed_sibling(self):
        two = helper.block(replace={"limits": "[limits]\nsmall_ms = 100\nmedium_ms = 500\n"})
        before = helper.doc(two, prose_after=PROSE)
        after = helper.block(replace={"limits": "[limits]\nsmall_ms = 50\nmedium_ms = 900\n"})
        self.repo.write(helper.doc(after, prose_after=PROSE))
        out = self.assert_fail("settings", before_text=before, expect={"set": {"limits.small_ms": 50}})
        self.assertIn("limits.medium_ms", out)
        self.assertNotIn("limits.small_ms was", out)

    def test_a_before_boolean_does_not_match_a_number_in_the_new_file(self):
        before = helper.doc(helper.block(replace={"limits": "[limits]\nsmall_ms = true\n"}), prose_after=PROSE)
        self.after(helper.block(replace={"limits": "[limits]\nsmall_ms = 1\n"}))
        self.assert_fail("settings", before_text=before)

    def test_a_lost_value_fails_settings(self):
        self.after(helper.block(drop=("limits",)))
        self.assert_fail("settings", before_text=self.BEFORE)

    def test_a_lost_prose_line_fails_prose(self):
        self.after(prose="## Conventions\n\n- Keep tests small.\n")
        out = self.assert_fail("prose", before_text=self.BEFORE)
        self.assertIn("RUN-05", out)

    def test_a_lost_reason_line_fails_prose(self):
        self.after(prose=PROSE.replace("- RUN-05: slow CI hardware.\n", ""))
        self.assert_fail("prose", before_text=self.BEFORE)

    def test_a_new_prose_line_and_a_changed_approved_value_pass(self):
        self.after(helper.block(replace={"limits": "[limits]\nsmall_ms = 50\n"}), prose=PROSE + "- New line.\n")
        self.assert_pass(before_text=self.BEFORE, expect={"set": {"limits.small_ms": 50}})


class UsageTest(GradeSetupCase):
    def test_a_missing_option_is_a_usage_error(self):
        done = subprocess.run([sys.executable, "-I", GRADER, "--repo", self.repo.root],
                              capture_output=True, text=True)
        self.assert_usage_error(done)

    def test_an_unreadable_expect_file_is_a_usage_error(self):
        done = subprocess.run([sys.executable, "-I", GRADER, "--repo", self.repo.root,
                               "--expect", os.path.join(self._scratch.name, "missing.json")],
                              capture_output=True, text=True)
        self.assert_usage_error(done)

    def test_invalid_json_and_an_unknown_key_are_usage_errors(self):
        for text in ("{not json", "[]", '{"nothing": 1}', '{"set": []}', '{"contains": "x"}'):
            with self.subTest(text=text):
                path = self.scratch_file("bad.json", text)
                done = subprocess.run([sys.executable, "-I", GRADER, "--repo", self.repo.root, "--expect", path],
                                      capture_output=True, text=True)
                self.assert_usage_error(done)

    @NEEDS_TOMLLIB
    def test_a_before_file_that_is_missing_or_malformed_is_a_usage_error(self):
        self.repo.write(helper.doc(helper.FULL_BLOCK))
        done = self.run_grader(extra=["--before", os.path.join(self._scratch.name, "missing.md")])
        self.assert_usage_error(done)
        self.assert_usage_error(self.run_grader(before_text="# T\n```toml\n[a\n```\n"))

    @NEEDS_TOMLLIB
    def test_a_before_file_without_a_toml_block_is_a_usage_error(self):
        self.repo.write(helper.doc(helper.FULL_BLOCK))
        self.assert_usage_error(self.run_grader(before_text="# Only prose\n"))


if __name__ == "__main__":
    unittest.main()
