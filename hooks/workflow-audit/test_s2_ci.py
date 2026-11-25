# S2 CI path: a declared `CI check: <name>` line, driven through `audit record` with a fake `gh`.
import json
import os
import stat
import sys
import unittest

from audit_support import result_row
from test_transcripts import TranscriptCase

CHECK = "test"
FAKE_GH = """\
#!{python}
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "gh-argv.jsonl"), "a") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
with open(os.path.join(here, "gh-out")) as handle:
    print(handle.read(), end="")
sys.exit(int(open(os.path.join(here, "gh-code")).read()))
"""


def run(name=CHECK, status="COMPLETED", conclusion="SUCCESS"):
    return {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion}


def section(*lines):
    """A CLAUDE.md whose test command section holds `lines` before the one fenced block."""
    return "# Project\n\n### Test command\n\n" + "".join(line + "\n\n" for line in lines) + "```\nmake test\n```\n"


class S2CiTest(TranscriptCase):
    def setUp(self):
        super().setUp()
        self.folder = os.path.join(self.root, "ci-gh")
        os.mkdir(self.folder)
        path = os.path.join(self.folder, "gh")
        with open(path, "w") as handle:
            handle.write(FAKE_GH.format(python=sys.executable))
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        self.env["PATH"] = self.folder + os.pathsep + os.environ["PATH"]
        self.answer([])
        self.register_session("s1", [self.own_edit("e1", 10)])

    def answer(self, out, code=0):
        """What the fake `gh` prints (a JSON value or raw text) and its exit status."""
        with open(os.path.join(self.folder, "gh-out"), "w") as handle:
            handle.write(out if isinstance(out, str) else json.dumps(out))
        with open(os.path.join(self.folder, "gh-code"), "w") as handle:
            handle.write(str(code))

    def calls(self):
        path = os.path.join(self.folder, "gh-argv.jsonl")
        if not os.path.exists(path):
            return []
        with open(path) as handle:
            return [json.loads(line) for line in handle]

    def s2(self, text, rollup=None, head=None, code=0, out=None):
        """The S2 item of a branch that declares `text`. The fake `gh` shows one open PR whose head is `head` (default: the audited
        HEAD) with the checks `rollup`, unless `out` gives the raw output."""
        tip = self.branch({"CLAUDE.md": text})
        self.git("remote", "set-url", "origin", "https://github.com/o/r.git")
        self.answer(out if out is not None else [{"headRefOid": head or tip, "statusCheckRollup": rollup or []}], code)
        result = self.record()
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return {item["id"]: item for item in self.read_record(tip)["items"]}["S2"]

    def assert_ci_fails(self, item, cause=None):
        self.assertEqual(item["result"], "fail", item["evidence"])
        self.assertIn("the CI path does not count", item["evidence"])
        self.assertIn("did not run", item["evidence"])  # the local result stays in the evidence
        if cause:
            self.assertIn(cause, item["evidence"])

    def test_a_green_check_on_the_audited_head_passes_and_says_so(self):
        item = self.s2(section(f"CI check: {CHECK}"), [run()])
        self.assertEqual(item["result"], "pass", item["evidence"])
        self.assertTrue(item["evidence"].startswith("CI check"), item["evidence"])
        self.assertEqual(len(self.calls()), 1)
        self.assertIn("o/r", self.calls()[0])

    def test_other_checks_of_the_rollup_do_not_matter(self):
        item = self.s2(section(f"CI check: {CHECK}"), [run("lint", conclusion="FAILURE"), run(), {"__typename": "StatusContext", "context": "x"}])
        self.assertEqual(item["result"], "pass", item["evidence"])

    def test_another_head_sha_does_not_count(self):
        self.assert_ci_fails(self.s2(section(f"CI check: {CHECK}"), [run()], head="0" * 40), "not the audited HEAD")

    def test_a_run_that_is_not_completed_with_success_does_not_count(self):
        for status, conclusion in (("IN_PROGRESS", ""), ("QUEUED", ""), ("COMPLETED", "FAILURE"), ("COMPLETED", "SKIPPED"),
                                   ("COMPLETED", "NEUTRAL"), ("COMPLETED", "CANCELLED"), ("COMPLETED", "STARTUP_FAILURE"),
                                   ("COMPLETED", ""), ("COMPLETED", "success"), ("", "SUCCESS")):
            with self.subTest(status=status, conclusion=conclusion):
                self.setUp()
                self.assert_ci_fails(self.s2(section(f"CI check: {CHECK}"), [run(status=status, conclusion=conclusion)]), "not completed with success")

    def test_every_run_of_the_check_must_succeed(self):
        self.assert_ci_fails(self.s2(section(f"CI check: {CHECK}"), [run(), run(conclusion="FAILURE")]), "not completed with success")

    def test_a_missing_check_does_not_count(self):
        for rollup in ([], [run("lint")], [run("Test")], [run("test2")], [run("tes")], [run(" test")], None):
            with self.subTest(rollup=rollup):
                self.setUp()
                self.assert_ci_fails(self.s2(section(f"CI check: {CHECK}"), rollup), "no check named")

    def test_a_gh_error_does_not_count(self):
        self.assert_ci_fails(self.s2(section(f"CI check: {CHECK}"), out="gh: boom", code=1), "exited with status 1")

    def test_a_green_answer_with_an_error_status_does_not_count(self):
        good = [{"headRefOid": "x", "statusCheckRollup": [run()]}]
        self.assert_ci_fails(self.s2(section(f"CI check: {CHECK}"), out=json.dumps(good), code=1), "exited with status 1")

    def test_output_that_is_not_one_open_pr_does_not_count(self):
        entry = {"headRefOid": "x", "statusCheckRollup": [run()]}
        for out in ("not json", "{}", "[]", "[1]", json.dumps([entry, entry]), "null", ""):
            with self.subTest(out=out):
                self.setUp()
                self.assert_ci_fails(self.s2(section(f"CI check: {CHECK}"), out=out), "exactly one open PR")

    def test_a_local_run_passes_without_asking_gh(self):
        text = section(f"CI check: {CHECK}")
        self.register_session("s2", [self.run_row("make test", "b1", 20), result_row("b1", 21)])
        item = self.s2(text, [])
        self.assertEqual(item["result"], "pass", item["evidence"])
        self.assertFalse(item["evidence"].startswith("CI check"))
        self.assertEqual(self.calls(), [])

    def test_no_ci_line_gives_the_local_result_and_never_asks_gh(self):
        item = self.s2(section(), [run()])
        self.assertEqual(item["result"], "fail")
        self.assertIn("did not run", item["evidence"])
        self.assertNotIn("CI", item["evidence"])
        self.assertEqual(self.calls(), [])

    def test_a_ci_line_outside_the_test_command_section_is_ignored(self):
        text = f"# Project\n\nCI check: {CHECK}\n\n" + section() + f"\n### Other\n\nCI check: {CHECK}\n"
        item = self.s2(text, [run()])
        self.assertEqual(item["result"], "fail")
        self.assertEqual(self.calls(), [])

    def test_a_ci_line_inside_the_fence_is_part_of_the_command(self):
        text = f"### Test command\n\n```\nmake test\nCI check: {CHECK}\n```\n"
        item = self.s2(text, [run()])
        self.assertEqual(item["result"], "fail")
        self.assertEqual(self.calls(), [])

    def test_two_ci_lines_or_an_empty_name_fail_the_declaration(self):
        for lines in ((f"CI check: {CHECK}", "CI check: other"), ("CI check: ",)):
            with self.subTest(lines=lines):
                self.setUp()
                item = self.s2(section(*lines), [run()])
                self.assertEqual(item["result"], "fail")
                self.assertIn("at most one", item["evidence"])
                self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
