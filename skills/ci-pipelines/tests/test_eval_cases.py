import glob
import json
import os
import re
import unittest

from report_fixtures import make_report, row
from skill_files import EVALS, all_rules, frontmatter, level, read

NO_EDIT_GRADERS = {"no-edit.md": "Edit", "no-write.md": "Write", "no-shell-write.md": "Bash"}
SECTION_GRADERS = {"section-summary", "section-intake", "section-checks", "section-tools",
                   "section-graph", "section-approve"}


def row_pattern(rule_id):
    """The pattern of an expect or forbid grader: the id in the Rule cell of a table row."""
    return r"^\|\s*\d+\s*\|\s*" + rule_id + r"(?:\s*⚑)?\s*\|"


def case_names():
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(EVALS, "*")) if os.path.isdir(p))


def case_dir(name):
    return os.path.join(EVALS, name)


def expect_lists(name):
    with open(os.path.join(case_dir(name), "expect.json"), encoding="utf-8") as handle:
        data = json.load(handle)
    return data["expect"], data["forbid"]


def review_cases():
    return [n for n in case_names() if not n.startswith("trigger-")]


def grader_files(name):
    return {os.path.basename(p) for p in glob.glob(os.path.join(case_dir(name), "graders", "*.md"))}


class EveryCase(unittest.TestCase):
    def test_there_are_cases(self):
        self.assertTrue(case_names())

    def test_every_case_has_its_files(self):
        for name in case_names():
            base = case_dir(name)
            for part in ("prompt.md", "case.yaml", "expect.json", "scaffold.sh", "repo", "graders"):
                self.assertTrue(os.path.exists(os.path.join(base, part)), f"{name} has no {part}")
            self.assertRegex(read(os.path.join(base, "case.yaml")), r"(?m)^\s*scaffold_script:\s*scaffold\.sh\s*$")
            self.assertRegex(read(os.path.join(base, "case.yaml")), rf"(?m)^name:\s*{re.escape(name)}\s*$")

    def test_no_fixture_holds_a_test_file(self):
        for name in case_names():
            found = glob.glob(os.path.join(case_dir(name), "repo", "**", "test_*.py"), recursive=True)
            self.assertEqual(found, [], f"{name} holds a file that the coverage test would count")

    def test_every_case_holds_a_workflow_fixture(self):
        for name in case_names():
            found = glob.glob(os.path.join(case_dir(name), "repo", ".github", "workflows", "*.yml"))
            self.assertTrue(found, f"{name} has no workflow fixture")


class ReviewCases(unittest.TestCase):
    def test_there_is_one_bad_case_for_each_naming_rule(self):
        for number in range(1, 10):
            matches = [n for n in review_cases() if n.startswith(f"name-{number:02d}-")]
            self.assertEqual(len(matches), 1, f"name-{number:02d}")

    def test_each_naming_case_expects_its_own_id(self):
        for number in range(1, 9):
            (name,) = [n for n in review_cases() if n.startswith(f"name-{number:02d}-")]
            self.assertEqual(expect_lists(name), ([f"NAME-{number:02d}"], []))
        (name,) = [n for n in review_cases() if n.startswith("name-09-")]
        self.assertEqual(expect_lists(name), (["NAME-04", "NAME-09"], []))

    def test_the_multi_rule_cases_expect_their_naming_ids(self):
        self.assertEqual(expect_lists("fx-sequential-quality"), (["NAME-04", "NAME-06"], []))
        self.assertEqual(expect_lists("fx-suite-list"), (["NAME-07"], []))

    def test_each_rule_id_is_expected_by_a_review_case(self):
        expected = {rule for name in review_cases() for rule in expect_lists(name)[0]}
        for _, rule_id, _ in all_rules():
            self.assertIn(rule_id, expected, f"no review case expects {rule_id}")

    def test_the_clean_case_forbids_every_critical_and_required_id(self):
        expect, forbid = expect_lists("clean")
        self.assertEqual(expect, [])
        wanted = [rule_id for _, rule_id, fields in all_rules() if level(fields) in ("critical", "required")]
        self.assertEqual(sorted(forbid), sorted(wanted))

    def test_the_graders_match_the_expect_lists(self):
        for name in review_cases():
            expect, forbid = expect_lists(name)
            expected_files = ({f"expect-{r}.md" for r in expect} | {f"forbid-{r}.md" for r in forbid}
                              | set(NO_EDIT_GRADERS) | {f"{s}.md" for s in SECTION_GRADERS} | {"fix-quality.md"})
            self.assertEqual(grader_files(name), expected_files, name)
            for rule in expect:
                meta = frontmatter(os.path.join(case_dir(name), "graders", f"expect-{rule}.md"))
                self.assertEqual((meta["type"], meta["pattern"], meta["flags"]), ("regex", row_pattern(rule), "m"))
                self.assertNotIn("match", meta)
            for rule in forbid:
                meta = frontmatter(os.path.join(case_dir(name), "graders", f"forbid-{rule}.md"))
                self.assertEqual((meta["type"], meta["pattern"], meta["match"]),
                                 ("regex", row_pattern(rule), "not_contains"))

    def test_the_expect_pattern_finds_the_id_in_a_rule_cell_only(self):
        report = make_report(required=[row("NAME-04", flag=True)]).replace(
            "Defaults: none.", "NAME-06 was checked.")
        self.assertTrue(re.search(row_pattern("NAME-04"), report, re.M))
        self.assertFalse(re.search(row_pattern("NAME-06"), report, re.M))

    def test_the_no_edit_graders_allow_zero_calls(self):
        for name in review_cases():
            for file, tool in NO_EDIT_GRADERS.items():
                meta = frontmatter(os.path.join(case_dir(name), "graders", file))
                self.assertEqual((meta["type"], meta["tool"], meta["min"], meta["max"]), ("tool_used", tool, "0", "0"))
                self.assertTrue(meta["input_match"])

    def test_the_section_graders_are_regex_graders(self):
        for name in review_cases():
            for section in SECTION_GRADERS:
                meta = frontmatter(os.path.join(case_dir(name), "graders", f"{section}.md"))
                self.assertEqual((meta["type"], meta["flags"]), ("regex", "m"))

    def test_the_judge_is_reported_and_not_scored(self):
        for name in review_cases():
            meta = frontmatter(os.path.join(case_dir(name), "graders", "fix-quality.md"))
            self.assertEqual((meta["type"], meta["arm"]), ("llm", "with-only"))
            self.assertNotIn("weight", meta)

    def test_the_review_prompt_does_not_name_the_skill_or_a_rule(self):
        for name in review_cases():
            prompt = read(os.path.join(case_dir(name), "prompt.md")).lower()
            self.assertNotIn("ci-pipelines", prompt)
            self.assertNotIn("name-", prompt)


class TriggerCase(unittest.TestCase):
    def test_the_trigger_case_asks_for_a_workflow_edit_without_naming_the_skill(self):
        prompt = read(os.path.join(case_dir("trigger-edit-workflow"), "prompt.md"))
        self.assertIn(".github/workflows", prompt)
        self.assertNotIn("ci-pipelines", prompt)

    def test_the_skill_fired_grader_checks_the_skill_tool(self):
        meta = frontmatter(os.path.join(case_dir("trigger-edit-workflow"), "graders", "skill-fired.md"))
        self.assertEqual((meta["type"], meta["tool"], meta["arm"]), ("tool_used", "Skill", "with-only"))
        self.assertTrue(re.search(meta["input_match"], '{"skill": "ci-pipelines"}'))
        self.assertTrue(re.search(meta["input_match"], '{"skill": "plugin:ci-pipelines"}'))
        self.assertFalse(re.search(meta["input_match"], '{"skill": "other-skill"}'))


if __name__ == "__main__":
    unittest.main()
