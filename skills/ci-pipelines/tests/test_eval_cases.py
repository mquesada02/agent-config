import glob
import json
import math
import os
import re
import unittest

from report_fixtures import make_report, row
from skill_files import EVALS, all_rules, frontmatter, level, read

NO_EDIT_GRADERS = {"no-edit.md": "Edit", "no-write.md": "Write", "no-shell-write.md": "Bash"}
COST_MONO_CASES = {
    "cost-01-push-no-branches": (["COST-01"], []),
    "cost-02-no-concurrency": (["COST-02"], []),
    "cost-03-workflow-paths": (["COST-03"], []),
    "cost-04-missing-timeout": (["COST-04"], []),
    "cost-04-timeout-too-high-with-history": (["COST-04"], []),
    "cost-04-timeout-too-high-no-history": ([], ["COST-04"]),
    "cost-05-install-not-frozen": (["COST-05"], []),
    "cost-06-too-many-workers": (["COST-06"], []),
    "cost-07-latest-runner": (["COST-07"], []),
    "cost-08-full-history-checkout": (["COST-08"], []),
    "mono-01-no-affected-run": (["MONO-01"], ["COST-08"]),
    "mono-02-no-tool": (["MONO-02"], []),
}
SECTION_GRADERS = {"section-summary", "section-intake", "section-checks", "section-tools",
                   "section-graph", "section-approve"}


def row_pattern(rule_id):
    """The pattern of an expect or forbid grader: the id in the Rule cell of a table row."""
    return r"^\|\s*\d+\s*\|\s*" + rule_id + r"(?:\s*⚑)?\s*\|"


def job_ids(workflow_text):
    """The job ids of a workflow text: the keys at two spaces of indent under `jobs:`."""
    return re.findall(r"(?m)^  [a-z][\w-]*:\n", workflow_text.split("\njobs:\n")[1])


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
            case_yaml = read(os.path.join(base, "case.yaml"))
            self.assertRegex(case_yaml, r"(?m)^\s*scaffold_script:\s*scaffold\.sh\s*$")
            self.assertRegex(case_yaml, rf"(?m)^name:\s*{re.escape(name)}\s*$")

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

    def test_there_is_one_bad_case_for_each_job_graph_and_maintainability_rule(self):
        measured = {rule_id for _, rule_id, fields in all_rules() if "measured" in fields["Severity"]}
        for prefix, count in (("graph", 7), ("maint", 3)):
            for number in range(1, count + 1):
                matches = [n for n in review_cases() if n.startswith(f"{prefix}-{number:02d}-")]
                rule = f"{prefix.upper()}-{number:02d}"
                if rule in measured:
                    self.assertEqual(sorted(expect_lists(n) for n in matches), [([], [rule]), ([rule], [])], rule)
                else:
                    self.assertEqual([expect_lists(n) for n in matches], [([rule], [])], rule)

    def test_the_multi_rule_cases_expect_their_ids(self):
        self.assertEqual(expect_lists("fx-sequential-quality"), (["GRAPH-01", "NAME-04", "NAME-06"], []))
        self.assertEqual(expect_lists("fx-suite-list"), (["GRAPH-07", "NAME-07"], []))
        self.assertEqual(expect_lists("fx-duplicate-build"), (["GRAPH-06"], []))
        self.assertEqual(expect_lists("fx-inline-tests"), (["MAINT-01"], []))
        self.assertEqual(expect_lists("fx-no-limits"), (["COST-02", "COST-04"], []))
        self.assertEqual(expect_lists("fx-paths-required"), (["COST-03"], []))

    def test_the_cost_and_monorepo_cases_are_exactly_these_with_their_lists(self):
        found = {n for n in review_cases() if n.startswith(("cost-", "mono-"))}
        self.assertEqual(found, set(COST_MONO_CASES))
        for name, lists in COST_MONO_CASES.items():
            self.assertEqual(expect_lists(name), lists, name)

    def test_cost_04_has_a_case_for_each_part_and_one_that_forbids_it(self):
        expects = [n for n in COST_MONO_CASES if n.startswith("cost-04-") and COST_MONO_CASES[n][0]]
        forbids = [n for n in COST_MONO_CASES if n.startswith("cost-04-") and COST_MONO_CASES[n][1]]
        self.assertEqual(len(expects), 2)
        self.assertEqual(len(forbids), 1)

    def test_each_rule_id_is_expected_by_a_review_case(self):
        expected = {rule for name in review_cases() for rule in expect_lists(name)[0]}
        forbidden = {rule for name in review_cases() for rule in expect_lists(name)[1]}
        for _, rule_id, fields in all_rules():
            self.assertIn(rule_id, expected, f"no review case expects {rule_id}")
            if "measured" in fields["Severity"]:
                self.assertIn(rule_id, forbidden, f"no review case forbids the measured rule {rule_id}")

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
            self.assertIsNone(re.search(r"\b(name|graph|maint|cost|mono)-\d\d", prompt), "the prompt names a rule")

    def test_the_copied_workflow_prompt_names_two_copies(self):
        (name,) = [n for n in review_cases() if n.startswith("maint-03-")]
        prompt = read(os.path.join(case_dir(name), "prompt.md"))
        self.assertIn("example-api", prompt)
        self.assertIn("example-worker", prompt)


class NewFixtures(unittest.TestCase):
    """Fixtures of the job graph, maintainability, cost and monorepo cases keep private names out."""

    @classmethod
    def setUpClass(cls):
        cls.cases = [n for n in case_names()
                     if n.startswith(("graph-", "maint-", "cost-", "mono-"))
                     or n in ("fx-duplicate-build", "fx-inline-tests", "fx-no-limits", "fx-paths-required")]
        cls.texts = {}
        for name in cls.cases:
            base = os.path.join(case_dir(name), "repo")
            for path in glob.glob(os.path.join(base, "**", "*"), recursive=True):
                if os.path.isfile(path):
                    cls.texts[path] = read(path)

    def test_the_new_cases_exist(self):
        self.assertEqual(len(self.cases), 27)

    def test_no_new_fixture_holds_a_url(self):
        for path, text in self.texts.items():
            self.assertNotRegex(text, r"https?://", path)

    def test_every_uses_owner_is_actions_or_pnpm(self):
        for path, text in self.texts.items():
            for owner in re.findall(r"uses:\s*([^/\s@]+)/", text):
                self.assertIn(owner, ("actions", "pnpm"), path)

    def test_every_package_name_starts_with_example(self):
        for path, text in self.texts.items():
            if os.path.basename(path) == "package.json":
                self.assertTrue(json.loads(text)["name"].startswith("example-"), path)


class RecordedIntakeChecks:
    """The checks of a case that gives the review a known run history through a recorded intake output.

    A mixin: each case below sets CASE and adds its own checks.
    """
    CASE = None
    FACTS = ("default_branch", "package_manager", "node_version_app", "engines", "package_kind", "os_claims",
             "test_runners", "monorepo", "visibility", "runner_labels", "required_checks", "run_history",
             "existing_workflows", "installed_tools", "supported_node_majors")

    def setUp(self):
        with open(os.path.join(case_dir(self.CASE), "repo", "intake.json"), encoding="utf-8") as handle:
            self.intake = json.load(handle)

    def test_the_file_holds_the_15_intake_facts_with_their_three_keys(self):
        self.assertEqual(sorted(self.intake), sorted(self.FACTS))
        for name, fact in self.intake.items():
            self.assertEqual(sorted(fact), ["source", "status", "value"], name)

    def test_the_run_history_is_detected_with_10_runs(self):
        history = self.intake["run_history"]
        self.assertEqual(history["status"], "detected")
        self.assertEqual(history["value"]["runs"], 10)

    def test_the_tools_do_not_depend_on_the_machine(self):
        for tool in self.intake["installed_tools"]["value"].values():
            self.assertFalse(tool["installed"])

    def test_the_prompt_points_to_the_file(self):
        prompt = read(os.path.join(case_dir(self.CASE), "prompt.md"))
        self.assertIn("intake.json", prompt)
        self.assertIn("do not run the intake script", prompt)


class RecordedIntakeGraph05(RecordedIntakeChecks, unittest.TestCase):
    CASE = "graph-05-shards-with-history"

    def test_the_case_expects_graph_05(self):
        self.assertEqual(expect_lists(self.CASE), (["GRAPH-05"], []))

    def test_the_run_history_gives_4_shards(self):
        jobs = self.intake["run_history"]["value"]["jobs"]
        minutes = max(job["median_seconds"] for name, job in jobs.items() if name.startswith("Test")) / 60
        self.assertGreater(minutes, 10)
        self.assertEqual(min(8, math.ceil(minutes / 8)), 4)

    def test_the_sandbox_run_history_stays_unknown_elsewhere(self):
        other = read(os.path.join(case_dir("graph-05-shards-no-history"), "prompt.md"))
        self.assertNotIn("intake.json", other)


class RecordedIntakeCost04(RecordedIntakeChecks, unittest.TestCase):
    CASE = "cost-04-timeout-too-high-with-history"
    NO_HISTORY = "cost-04-timeout-too-high-no-history"

    def workflow(self, case):
        return read(os.path.join(case_dir(case), "repo", ".github", "workflows", "ci.yml"))

    def timeouts(self):
        found = re.findall(r"(?m)^    name: (.+)\n(?:    .*\n)*?    timeout-minutes: (\d+)\n", self.workflow(self.CASE))
        return {name: int(minutes) for name, minutes in found}

    def test_every_history_job_has_a_timeout_more_than_2x_above_the_proposal(self):
        timeouts = self.timeouts()
        jobs = self.intake["run_history"]["value"]["jobs"]
        self.assertTrue(jobs)
        for name, job in jobs.items():
            proposal = max(5, math.ceil(3 * job["median_seconds"] / 60))
            self.assertIn(name, timeouts, name)
            self.assertGreater(timeouts[name], 2 * proposal, name)

    def test_every_job_has_a_timeout_so_only_the_measured_part_can_fire(self):
        self.assertEqual(len(self.timeouts()), len(job_ids(self.workflow(self.CASE))))

    def test_the_gate_has_no_history_entry(self):
        self.assertNotIn("CI passed", self.intake["run_history"]["value"]["jobs"])
        self.assertIn("CI passed", self.timeouts())

    def test_the_no_history_case_has_the_same_workflow_and_no_recorded_intake(self):
        self.assertEqual(self.workflow(self.NO_HISTORY), self.workflow(self.CASE))
        self.assertFalse(os.path.exists(os.path.join(case_dir(self.NO_HISTORY), "repo", "intake.json")))
        self.assertNotIn("intake.json", read(os.path.join(case_dir(self.NO_HISTORY), "prompt.md")))


class CleanWorkflow(unittest.TestCase):
    def test_the_concurrency_group_is_the_cost_02_expression(self):
        text = read(os.path.join(case_dir("clean"), "repo", ".github", "workflows", "ci.yml"))
        self.assertIn("group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}", text)
        self.assertIn("cancel-in-progress: ${{ github.event_name == 'pull_request' }}", text)

    def test_every_job_has_a_timeout_and_a_pinned_runner(self):
        text = read(os.path.join(case_dir("clean"), "repo", ".github", "workflows", "ci.yml"))
        jobs = job_ids(text)
        self.assertEqual(len(re.findall(r"(?m)^    timeout-minutes: \d+$", text)), len(jobs))
        self.assertEqual(len(re.findall(r"(?m)^    runs-on: ubuntu-24\.04$", text)), len(jobs))


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
