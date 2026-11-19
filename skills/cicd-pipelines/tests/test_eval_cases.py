import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from report_fixtures import make_report, row
from skill_files import EVALS, SKILL, all_rules, frontmatter, level, read

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
    "mono-02-filter-full-history": ([], ["COST-08"]),
}
SEC_CASES = {
    "sec-01-tag-pin": (["SEC-01"], []),
    "sec-01-wrong-sha": (["SEC-01"], []),
    "sec-02-no-dependabot": (["SEC-02"], []),
    "sec-03-no-permissions": (["SEC-03"], []),
    "sec-04-untrusted-context-in-run": (["SEC-04"], []),
    "sec-04-matrix-in-run": (["SEC-04"], []),
    "sec-05-persist-credentials": (["SEC-05"], []),
    "sec-06-token-in-git-url": (["SEC-06"], []),
    "sec-07-pr-head-checkout": (["SEC-07"], []),
    "sec-07-privileged-trigger": (["SEC-07"], []),
    "sec-08-secrets-inherit": (["SEC-08"], []),
    "sec-09-cache-under-privileged-trigger": (["SEC-09"], []),
    "sec-10-audit-in-test-job": (["SEC-10"], []),
}
SEC_EXTRA_CASES = {
    "fx-token-in-run": (["SEC-04", "SEC-05", "SEC-06"], []),
    "merge-01-zizmor-unpinned": (["SEC-01"], ["unpinned-uses"]),
    "tool-01-zizmor-missing": (["SEC-01", "SEC-03"], []),
}
DEPLOY_CASES = {
    "deploy-01-build-in-deploy-job": (["DEPLOY-01"], []),
    "deploy-02-no-stage-environment": (["DEPLOY-02"], []),
    "deploy-02-tag-run-staging-record": ([], ["DEPLOY-02"]),
    "deploy-03-no-digest-check": (["DEPLOY-03"], []),
    "deploy-04-long-lived-key": (["DEPLOY-04"], []),
    "deploy-05-status-only-check": (["DEPLOY-05"], []),
    "deploy-06-silent-skip": (["DEPLOY-06"], []),
    "deploy-07-no-gradual-rollout": (["DEPLOY-07"], []),
    "deploy-08-docs-only-deploys": (["DEPLOY-08"], []),
    "deploy-09-missing-timeout": (["DEPLOY-09"], []),
    "deploy-09-timeout-too-high-with-history": (["DEPLOY-09"], []),
    "deploy-09-timeout-too-high-no-history": ([], ["DEPLOY-09"]),
    "deploy-10-no-pr-dry-run": (["DEPLOY-10"], []),
}
ROLLBACK_CASES = {
    "rollback-01-no-rollback-workflow": (["ROLLBACK-01"], []),
    "rollback-02-rollback-builds": (["ROLLBACK-02"], []),
    "rollback-03-run-artifact-only": (["ROLLBACK-03"], []),
    "rollback-04-parallel-prod-targets": (["ROLLBACK-04"], []),
    "rollback-05-native-rollback-disabled": (["ROLLBACK-05"], []),
    "rollback-06-other-concurrency-group": (["ROLLBACK-06"], []),
}
RELEASE_CASES = {
    "release-01-two-release-tools": (["RELEASE-01"], []),
    "release-02-lightweight-tag": (["RELEASE-02"], []),
    "release-03-no-tag-ruleset": (["RELEASE-03"], []),
    "release-04-pat-token": (["RELEASE-04"], []),
    "release-05-tag-push-trigger": (["RELEASE-05"], []),
    "release-06-no-release-notes": (["RELEASE-06"], []),
}
PUBLISH_CASES = {
    "publish-01-npm-token": (["PUBLISH-01"], []),
    "publish-02-cached-publish": (["PUBLISH-02"], []),
    "publish-03-no-dependency-order": (["PUBLISH-03"], []),
    "publish-04-no-published-version-check": (["PUBLISH-04"], []),
    "publish-05-publish-workflow-renamed": (["PUBLISH-05"], []),
}
PROTECT_CASES = {
    "protect-01-no-main-ruleset": (["PROTECT-01"], []),
    "protect-02-no-tag-ruleset": (["PROTECT-02"], []),
    "protect-03-env-accepts-any-branch": (["PROTECT-03"], []),
    "protect-04-prod-no-reviewers": (["PROTECT-04"], []),
    "protect-05-admin-bypass-on-prod": (["PROTECT-05"], []),
    "protect-06-classic-and-ruleset-stack": (["PROTECT-06"], []),
    "protect-07-claimed-protection-missing": (["PROTECT-07"], []),
    "protect-08-repo-wide-role-arn": (["PROTECT-08"], []),
}
# The cases whose report has a lock row (the protection writes of PROTECT-01 to PROTECT-04).
PROTECT_LOCK_CASES = ("protect-01-no-main-ruleset", "protect-02-no-tag-ruleset",
                      "protect-03-env-accepts-any-branch", "protect-04-prod-no-reviewers")
# The CD cases that have a fixture are selected by name. Each CD ticket adds its prefix cases and raises the count.
CD_PREFIXES = ("deploy-", "rollback-", "release-", "publish-", "protect-", "fx-cd-", "create-cd-")
CD_CASE_COUNT = 55  # the 45 earlier CD cases and the ten `fx-cd-*` candidates (the trigger cases are not counted)
FULL_SHA_PIN = r"^[\w.-]+/[\w.-]+@[0-9a-f]{40} # v\d"
UNPINNED_CASE = "fx-cd-tag-unpinned"
UNPINNED_USES = "aws-actions/example-workflows/.github/workflows/ci.yml@v2"
SECTION_GRADERS = {"section-summary", "section-intake", "section-checks", "section-tools",
                   "section-graph", "section-approve"}


def extra_graders(name):
    """The grader files that a case holds besides the expect, forbid, no-edit, section and judge ones."""
    if not name.startswith("protect-"):
        return set()
    return {"section-graph-triggers.md"} | ({"section-lock-note.md"} if name in PROTECT_LOCK_CASES else set())


def row_pattern(rule_id):
    """The pattern of an expect or forbid grader: the id in the Rule cell of a table row."""
    return r"^\|\s*\d+\s*\|\s*" + rule_id + r"(?:\s*⚑)?(?:\s*🔒)?\s*\|"


def job_ids(workflow_text):
    """The job ids of a workflow text: the keys at two spaces of indent under `jobs:`."""
    return re.findall(r"(?m)^  [a-z][\w-]*:\n", workflow_text.split("\njobs:\n")[1])


def job_text(workflow_text, job_id):
    """The text of one job: from its key at two spaces of indent to the next job key."""
    jobs = workflow_text.split("\njobs:\n")[1]
    return re.search(r"(?ms)^  " + re.escape(job_id) + r":\n(.*?)(?=^  [a-z][\w-]*:\n|\Z)", jobs).group(0)


def run_text(workflow_text):
    """Every `run:` value of a workflow text, block scalar bodies included.

    A multi-line plain or quoted scalar is not followed: the fixtures use one-line values and `|` blocks."""
    lines = workflow_text.splitlines()
    values = []
    for number, line in enumerate(lines):
        found = re.match(r"^(\s*(?:- )?)run:\s*(.*)$", line)
        if not found:
            continue
        value = found.group(2)
        if re.fullmatch(r"[|>][+-]?", value):
            key_indent = len(found.group(1))
            body = []
            for later in lines[number + 1:]:
                if later.strip() and len(later) - len(later.lstrip()) <= key_indent:
                    break
                body.append(later)
            value = "\n".join(body)
        values.append(value)
    return "\n".join(values)


def job_timeouts(workflow_text):
    """Map of job `name:` to its `timeout-minutes` for the jobs of a workflow text that set one."""
    found = re.findall(r"(?m)^    name: (.+)\n(?:    .*\n)*?    timeout-minutes: (\d+)\n", workflow_text)
    return {name: int(minutes) for name, minutes in found}


def checkout_blocks(workflow_text):
    """The step blocks of a workflow text that hold a checkout action."""
    steps = re.split(r"(?m)^(?= *- (?:name|uses|run):)", workflow_text)
    return [step for step in steps if "actions/checkout@" in step]


def case_names():
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(EVALS, "*")) if os.path.isdir(p))


def case_dir(name):
    return os.path.join(EVALS, name)


def expect_lists(name):
    with open(os.path.join(case_dir(name), "expect.json"), encoding="utf-8") as handle:
        data = json.load(handle)
    return data["expect"], data["forbid"]


def review_cases():
    return [n for n in case_names() if not n.startswith(("trigger-", "approve-", "create-", "protect-approve-"))]


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

    def test_every_case_but_a_create_case_holds_a_workflow_fixture(self):
        for name in case_names():
            if name.startswith("create-"):
                continue
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
        self.assertEqual(expect_lists("fx-sequential-quality"),
                         (["GRAPH-01", "NAME-04", "NAME-06", "SEC-01", "SEC-10"], []))
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

    def test_the_security_cases_are_exactly_these_with_their_lists(self):
        found = {n for n in review_cases() if n.startswith(("sec-", "merge-", "tool-")) or n == "fx-token-in-run"}
        self.assertEqual(found, set(SEC_CASES) | set(SEC_EXTRA_CASES))
        for name, lists in {**SEC_CASES, **SEC_EXTRA_CASES}.items():
            self.assertEqual(expect_lists(name), lists, name)

    def test_there_is_a_case_for_each_sec_rule_and_one_for_each_critical_part_next_to_its_required_part(self):
        for number in range(1, 11):
            self.assertTrue([n for n in SEC_CASES if n.startswith(f"sec-{number:02d}-")], f"SEC-{number:02d}")
        for number in (1, 4, 7):
            self.assertEqual(len([n for n in SEC_CASES if n.startswith(f"sec-{number:02d}-")]), 2, number)

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

    def test_the_clean_cases_forbid_every_critical_and_required_id(self):
        wanted = [rule_id for _, rule_id, fields in all_rules() if level(fields) in ("critical", "required")]
        for case in ("clean", "clean-cd"):
            expect, forbid = expect_lists(case)
            self.assertEqual(expect, [], case)
            self.assertEqual(sorted(forbid), sorted(wanted), case)

    def test_the_graders_match_the_expect_lists(self):
        for name in review_cases():
            expect, forbid = expect_lists(name)
            expected_files = ({f"expect-{r}.md" for r in expect} | {f"forbid-{r}.md" for r in forbid}
                              | set(NO_EDIT_GRADERS) | {f"{s}.md" for s in SECTION_GRADERS} | {"fix-quality.md"}
                              | extra_graders(name))
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

    def test_the_expect_pattern_accepts_the_flag_mark_the_lock_mark_or_both_in_that_order(self):
        for kwargs in ({}, {"flag": True}, {"lock": True}, {"flag": True, "lock": True}):
            report = make_report(required=[row("PROTECT-01", **kwargs)])
            self.assertTrue(re.search(row_pattern("PROTECT-01"), report, re.M), kwargs)
        for cell in ("PROTECT-01 🔒 ⚑", "PROTECT-01 ⚑ ⚑", "PROTECT-011", "PROTECT-01 x"):
            self.assertFalse(re.search(row_pattern("PROTECT-01"), f"| 1 | {cell} | ci.yml:3 | A. | B. |", re.M), cell)

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
            self.assertNotIn("cicd-pipelines", prompt)
            self.assertIsNone(re.search(r"\b(name|graph|maint|cost|mono|sec|deploy|rollback|release|publish|protect)-\d\d",
                                        prompt), "the prompt names a rule")

    def test_the_copied_workflow_prompt_names_two_copies(self):
        (name,) = [n for n in review_cases() if n.startswith("maint-03-")]
        prompt = read(os.path.join(case_dir(name), "prompt.md"))
        self.assertIn("example-api", prompt)
        self.assertIn("example-worker", prompt)


GIT_URLS = (
    r"https://github\.com/example-org/example-[a-z0-9-]+",
    r"https://x-access-token:\$\{\{ secrets\.EXAMPLE_TOKEN \}\}@github\.com/example-org/example-[a-z0-9-]+",
)


class NewFixtures(unittest.TestCase):
    """Fixtures of the job graph, maintainability, cost, monorepo, security and approval cases keep private names out."""

    @classmethod
    def setUpClass(cls):
        cls.cases = [n for n in case_names()
                     if n.startswith(("graph-", "maint-", "cost-", "mono-", "sec-", "merge-", "tool-", "approve-"))
                     or n in ("fx-duplicate-build", "fx-inline-tests", "fx-no-limits", "fx-paths-required",
                              "fx-token-in-run")]
        cls.texts = {}
        for name in cls.cases:
            base = os.path.join(case_dir(name), "repo")
            for path in glob.glob(os.path.join(base, "**", "*"), recursive=True):
                if os.path.isfile(path):
                    cls.texts[path] = read(path)

    def test_the_new_cases_exist(self):
        self.assertEqual(len(self.cases), 48)

    def test_no_new_fixture_holds_a_url_but_the_two_git_url_forms(self):
        for path, text in self.texts.items():
            for form in GIT_URLS:
                text = re.sub(form, "", text)
            self.assertNotRegex(text, r"https?://", path)

    def test_every_uses_owner_is_actions_or_pnpm_and_a_local_reference_is_skipped(self):
        for path, text in self.texts.items():
            for owner in re.findall(r"uses:\s*([A-Za-z][^/\s@]*)/", text):
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
             "existing_workflows", "installed_tools", "supported_node_majors",
             "environments", "plan", "rulesets", "classic_protection", "deploy_targets", "iac_tools",
             "aws_variables", "release_tool", "publish_target", "release_tag_pattern", "provenance",
             "deploy_history", "stack")

    def setUp(self):
        with open(os.path.join(case_dir(self.CASE), "repo", "intake.json"), encoding="utf-8") as handle:
            self.intake = json.load(handle)

    def test_the_file_holds_the_28_intake_facts_with_their_three_keys(self):
        self.assertEqual(sorted(self.intake), sorted(self.FACTS))
        for name, fact in self.intake.items():
            self.assertEqual(sorted(fact), ["source", "status", "value"], name)

    def test_the_offline_node_list_names_tools_md_and_not_the_deleted_file(self):
        source = self.intake["supported_node_majors"]["source"]
        self.assertIn("tools.md", source)
        self.assertNotIn("node-support-offline", source)

    def test_the_prompt_points_to_the_file(self):
        prompt = read(os.path.join(case_dir(self.CASE), "prompt.md"))
        self.assertIn("intake.json", prompt)
        self.assertIn("do not run the intake script", prompt)

    def installed(self):
        return {name: tool["installed"] for name, tool in self.intake["installed_tools"]["value"].items()}


class RecordedHistoryChecks(RecordedIntakeChecks):
    """The checks of the cases that record a detected run history (GRAPH-05 and COST-04)."""

    def test_the_run_history_is_detected_with_10_runs(self):
        history = self.intake["run_history"]
        self.assertEqual(history["status"], "detected")
        self.assertEqual(history["value"]["runs"], 10)

    def test_the_tools_do_not_depend_on_the_machine(self):
        for installed in self.installed().values():
            self.assertFalse(installed)


class RecordedIntakeGraph05(RecordedHistoryChecks, unittest.TestCase):
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


class RecordedIntakeCost04(RecordedHistoryChecks, unittest.TestCase):
    CASE = "cost-04-timeout-too-high-with-history"
    NO_HISTORY = "cost-04-timeout-too-high-no-history"

    def workflow(self, case):
        return read(os.path.join(case_dir(case), "repo", ".github", "workflows", "ci.yml"))

    def timeouts(self):
        return job_timeouts(self.workflow(self.CASE))

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


def workflow_text(case, name="ci.yml"):
    return read(os.path.join(case_dir(case), "repo", ".github", "workflows", name))


class RecordedIntakeMerge(RecordedIntakeChecks, unittest.TestCase):
    CASE = "merge-01-zizmor-unpinned"

    def test_only_zizmor_is_on_path_and_the_run_history_is_unknown(self):
        self.assertEqual(self.installed(), {"actionlint": False, "zizmor": True, "pinact": False})
        self.assertEqual(self.intake["run_history"]["status"], "unknown")

    def test_the_prompt_points_to_the_recorded_zizmor_output_and_runs_no_tool(self):
        prompt = read(os.path.join(case_dir(self.CASE), "prompt.md"))
        self.assertIn("zizmor.json", prompt)
        self.assertIn("do not run zizmor or any other tool", prompt)

    def test_the_recorded_zizmor_output_has_one_unpinned_uses_finding_on_the_tag_pinned_line(self):
        path = os.path.join(case_dir(self.CASE), "repo", "zizmor.json")
        text = read(path)
        self.assertNotRegex(text, r"https?://")
        findings = json.loads(text)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["ident"], "unpinned-uses")
        self.assertEqual(findings[0]["determinations"]["persona"], "Regular")
        location = findings[0]["locations"][0]
        self.assertEqual(location["symbolic"]["key"]["Local"]["given_path"], ".github/workflows/ci.yml")
        lines = workflow_text(self.CASE).splitlines()
        line = next(i for i, text in enumerate(lines, start=1) if "actions/checkout@v4" in text)
        self.assertEqual(location["concrete"]["location"]["start_point"]["row"] + 1, line)


class RecordedPinCheck(unittest.TestCase):
    CASE = "sec-01-wrong-sha"

    def setUp(self):
        with open(os.path.join(case_dir(self.CASE), "repo", "pins.json"), encoding="utf-8") as handle:
            self.pins = json.load(handle)

    def test_the_prompt_points_to_the_recorded_pin_check_and_runs_no_script(self):
        prompt = read(os.path.join(case_dir(self.CASE), "prompt.md"))
        self.assertIn("pins.json", prompt)
        self.assertIn("do not run the pin check script", prompt)

    def test_each_recorded_pin_is_the_uses_line_of_the_fixture_and_one_is_ok_and_two_are_wrong(self):
        lines = workflow_text(self.CASE).splitlines()
        for pin in self.pins["pins"]:
            self.assertIn(f"uses: {pin['uses']}@{pin['sha']} # {pin['tag']}", lines[pin["line"] - 1])
        self.assertEqual(sorted(p["result"] for p in self.pins["pins"]), ["ok", "tag-mismatch", "unknown-commit"])
        self.assertEqual(self.pins["status"], "verified")

    def test_the_pins_are_synthetic(self):
        for pin in self.pins["pins"]:
            self.assertRegex(pin["sha"], r"^(\w)\1{39}$")


class RecordedIntakeMissingTool(RecordedIntakeChecks, unittest.TestCase):
    CASE = "tool-01-zizmor-missing"

    def test_no_tool_is_on_path_and_the_run_history_is_unknown(self):
        self.assertEqual(self.installed(), {"actionlint": False, "zizmor": False, "pinact": False})
        self.assertEqual(self.intake["run_history"]["status"], "unknown")

    def test_the_fixture_has_a_tag_pin_and_no_permissions_block(self):
        text = workflow_text(self.CASE)
        self.assertRegex(text, r"uses: actions/checkout@v\d")
        self.assertNotIn("permissions:", text)


class WorkflowTextHelpers(unittest.TestCase):
    SAMPLE = (
        "name: x\njobs:\n  build:\n    steps:\n      - run: pnpm audit\n"
        "  test:\n    steps:\n      - run: |\n          echo \"${{ github.event.pull_request.title }}\"\n"
        "          echo two\n      - name: next\n        run: echo done\n"
    )

    def test_job_text_stops_at_the_next_job(self):
        self.assertIn("pnpm audit", job_text(self.SAMPLE, "build"))
        self.assertNotIn("pnpm audit", job_text(self.SAMPLE, "test"))

    def test_run_text_holds_block_scalar_bodies_and_stops_at_the_next_step(self):
        text = run_text(self.SAMPLE)
        self.assertIn("github.event.pull_request.title", text)
        self.assertIn("echo two", text)
        self.assertIn("echo done", text)
        self.assertNotIn("name: next", text)

    def test_checkout_blocks_are_split_per_step(self):
        sample = ("      - uses: actions/checkout@v4\n        with:\n          persist-credentials: false\n"
                  "      - uses: actions/checkout@v4\n")
        blocks = checkout_blocks(sample)
        self.assertEqual(len(blocks), 2)
        self.assertIn("persist-credentials: false", blocks[0])
        self.assertNotIn("persist-credentials: false", blocks[1])


class SecurityFixtures(unittest.TestCase):
    def text(self, case):
        folder = os.path.join(case_dir(case), "repo", ".github", "workflows")
        return "\n".join(read(path) for path in sorted(glob.glob(os.path.join(folder, "*.yml"))))

    def test_the_sec_04_critical_fixture_has_an_untrusted_context_in_run(self):
        self.assertIn('echo "${{ github.event.pull_request.title }}"', self.text("sec-04-untrusted-context-in-run"))

    def test_the_sec_04_required_fixture_has_only_a_matrix_context_in_run(self):
        text = self.text("sec-04-matrix-in-run")
        self.assertRegex(text, r"run: .*\$\{\{ matrix\.\w+ \}\}")
        run_values = run_text(text)
        for untrusted in ("github.event.", "github.head_ref", "inputs.", "secrets."):
            self.assertNotIn(untrusted, run_values)

    def test_the_sec_07_critical_fixture_checks_out_the_pr_head_under_a_privileged_trigger(self):
        text = self.text("sec-07-pr-head-checkout")
        self.assertIn("pull_request_target", text)
        self.assertIn("ref: ${{ github.event.pull_request.head.sha }}", text)

    def test_the_sec_07_required_fixture_has_the_trigger_and_no_pr_head_checkout_and_no_cache(self):
        text = self.text("sec-07-privileged-trigger")
        self.assertIn("workflow_run", text)
        self.assertNotIn("ref:", text)
        self.assertNotIn("cache:", text)

    def test_the_sec_08_fixture_calls_a_local_workflow_that_exists_with_secrets_inherit(self):
        text = self.text("sec-08-secrets-inherit")
        self.assertIn("secrets: inherit", text)
        self.assertRegex(text, r"uses: \./\.github/workflows/[a-z-]+\.yml")
        self.assertIn("workflow_call", text)

    def test_the_sec_09_fixture_caches_under_a_privileged_trigger(self):
        text = self.text("sec-09-cache-under-privileged-trigger")
        self.assertIn("pull_request_target", text)
        self.assertIn("cache: pnpm", text)

    def test_the_sec_10_fixture_audits_inside_the_test_job(self):
        text = self.text("sec-10-audit-in-test-job")
        self.assertIn("pnpm audit", job_text(text, "test"))

    def test_the_sec_02_fixture_has_sha_pins_and_no_dependabot_file(self):
        self.assertRegex(self.text("sec-02-no-dependabot"), r"uses: actions/checkout@[0-9a-f]{40} # v")
        self.assertFalse(os.path.exists(os.path.join(case_dir("sec-02-no-dependabot"), "repo", ".github",
                                                     "dependabot.yml")))

    def test_the_fx_token_in_run_fixture_writes_the_git_config_with_a_secret_and_keeps_credentials(self):
        text = self.text("fx-token-in-run")
        self.assertIn("${{ secrets.EXAMPLE_TOKEN }}", text)
        self.assertIn("git config --global", text)
        self.assertNotIn("persist-credentials", text)

    def test_fx_sequential_quality_has_tag_pins_and_one_audit_step(self):
        text = self.text("fx-sequential-quality")
        self.assertNotRegex(text, r"@[0-9a-f]{40}")
        self.assertRegex(text, r"uses: actions/checkout@v\d")
        self.assertEqual(text.count("pnpm audit"), 1)


class CleanWorkflow(unittest.TestCase):
    def test_the_concurrency_group_is_the_cost_02_expression(self):
        text = read(os.path.join(case_dir("clean"), "repo", ".github", "workflows", "ci.yml"))
        self.assertIn("group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}", text)
        self.assertIn("cancel-in-progress: ${{ github.event_name == 'pull_request' }}", text)

    def test_every_job_has_a_timeout_and_a_pinned_runner(self):
        for name in ("ci.yml", "security-audit.yml"):
            text = workflow_text("clean", name)
            jobs = job_ids(text)
            self.assertTrue(jobs, name)
            self.assertEqual(len(re.findall(r"(?m)^    timeout-minutes: \d+$", text)), len(jobs), name)
            self.assertEqual(len(re.findall(r"(?m)^    runs-on: ubuntu-24\.04$", text)), len(jobs), name)

    def test_every_uses_has_a_full_sha_and_a_version_comment_and_a_known_owner(self):
        for name in ("ci.yml", "security-audit.yml"):
            text = workflow_text("clean", name)
            uses = re.findall(r"uses: (\S+)(.*)", text)
            self.assertTrue(uses, name)
            for action, rest in uses:
                self.assertRegex(action, r"^(actions|pnpm|dorny)/[\w.-]+@[0-9a-f]{40}$", action)
                self.assertRegex(rest, r"^ # v\d", action)

    def test_every_checkout_keeps_no_credentials(self):
        for name in ("ci.yml", "security-audit.yml"):
            text = workflow_text("clean", name)
            blocks = checkout_blocks(text)
            self.assertTrue(blocks, name)
            for block in blocks:
                self.assertEqual(block.count("persist-credentials: false"), 1, name)

    def test_dependabot_has_the_github_actions_entry(self):
        text = read(os.path.join(case_dir("clean"), "repo", ".github", "dependabot.yml"))
        self.assertIn("package-ecosystem: github-actions", text)
        self.assertIn("directory: /", text)
        self.assertIn("interval: weekly", text)

    def test_the_audit_job_is_gated_on_the_lockfile_and_is_part_of_the_gate(self):
        text = workflow_text("clean")
        self.assertIn("  audit:\n", text)
        self.assertIn("pnpm audit --audit-level=high", text)
        self.assertIn("needs.changes.outputs.lockfile == 'true'", text)
        self.assertIn("needs: [changes, lint, typecheck, test, build, audit]", text)
        self.assertIn('.result == "success" or .result == "skipped"', text)

    def test_the_weekly_audit_workflow_uses_an_odd_minute(self):
        text = workflow_text("clean", "security-audit.yml")
        minute = int(re.search(r"cron: '(\d+) ", text).group(1))
        self.assertEqual(minute % 2, 1)
        self.assertIn("pnpm audit --audit-level=high", text)
        self.assertIn("contents: read", text)


class CleanCdCase(unittest.TestCase):
    """The clean CD fixture is a good CD repo: the structural assertions of the CD part pass on its files."""
    CHECK = os.path.join(os.path.dirname(EVALS), "scripts", "check_workflow.py")

    def check(self, name, *assertions):
        done = subprocess.run([sys.executable, "-I", self.CHECK, "-", "--assert", *assertions],
                              input=workflow_text("clean-cd", name), capture_output=True, text=True)
        self.assertEqual((done.returncode, done.stdout), (0, "PASS\n"), name)

    def test_the_ci_workflow_has_the_cd_part(self):
        self.check("ci.yml", "triggers-cd", "name=CI", "timeouts", "gate")
        self.assertIn("name: dist", workflow_text("clean-cd"))

    def test_the_deploy_rollback_and_release_workflows_pass_the_cd_assertions(self):
        self.check("deploy.yml", "name=Deploy", "stage-environments", "concurrency-cd", "no-install-in-deploy",
                   "digest-check", "package-upload", "timeouts", "permissions")
        self.check("rollback.yml", "name=Rollback", "rollback-workflow", "concurrency-cd", "no-install-in-deploy",
                   "digest-check", "timeouts", "permissions")
        self.check("release.yml", "name=Release", "timeouts", "permissions")

    def test_the_repo_holds_the_scripts_and_the_changesets_config(self):
        base = os.path.join(case_dir("clean-cd"), "repo")
        for path in ("scripts/deploy-and-verify.sh", "scripts/check-staged.sh", ".changeset/config.json"):
            self.assertTrue(os.path.isfile(os.path.join(base, path)), path)

    def test_the_scripts_equal_the_templates(self):
        skill = os.path.dirname(EVALS)
        for name in ("deploy-and-verify.sh", "check-staged.sh"):
            self.assertEqual(read(os.path.join(case_dir("clean-cd"), "repo", "scripts", name)),
                             read(os.path.join(skill, "templates", "scripts", name)), name)

    def test_the_workflows_equal_the_templates_except_for_the_pins(self):
        skill = os.path.dirname(EVALS)
        pin = re.compile(r"@[0-9a-f]{40} # v")
        for name in ("deploy.yml", "release.yml", "rollback.yml"):
            self.assertEqual(pin.sub("@PIN # v", workflow_text("clean-cd", name)),
                             pin.sub("@PIN # v", read(os.path.join(skill, "templates", name))), name)


class DeployCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.deploy_texts = {name: workflow_text(name, "deploy.yml") for name in DEPLOY_CASES}

    def deploy(self, case):
        return self.deploy_texts[case]

    def test_the_deploy_cases_are_exactly_these_with_their_lists(self):
        found = {n for n in review_cases() if n.startswith("deploy-")}
        self.assertEqual(found, set(DEPLOY_CASES))
        for name, lists in DEPLOY_CASES.items():
            self.assertEqual(expect_lists(name), lists, name)

    def test_deploy_09_has_a_case_for_each_part_and_one_that_forbids_it(self):
        expects = [n for n in DEPLOY_CASES if n.startswith("deploy-09-") and DEPLOY_CASES[n][0]]
        forbids = [n for n in DEPLOY_CASES if n.startswith("deploy-09-") and DEPLOY_CASES[n][1]]
        self.assertEqual(len(expects), 2)
        self.assertEqual(len(forbids), 1)

    def test_every_deploy_case_has_a_ci_workflow_with_the_cd_part_and_a_deploy_workflow(self):
        for name in DEPLOY_CASES:
            self.assertIn("workflow_call:", workflow_text(name), name)
            self.assertIn("uses: ./.github/workflows/ci.yml", self.deploy(name), name)

    def test_the_tag_run_case_has_a_prod_job_with_the_staging_record_check_and_no_needs(self):
        text = self.deploy("deploy-02-tag-run-staging-record")
        prod = job_text(text, "deploy-prod")
        self.assertIn("environment: prod", prod)
        self.assertIn('run: ./scripts/check-staged.sh "$SHA"', prod)
        self.assertIn("if: github.ref_type == 'tag'", prod)
        self.assertNotIn("needs:", prod)
        self.assertIn("needs: [ci, deploy-dev]", job_text(text, "deploy-staging"))
        self.assertTrue(os.path.exists(os.path.join(case_dir("deploy-02-tag-run-staging-record"), "repo",
                                                    "scripts", "check-staged.sh")))

    def test_the_no_stage_case_has_a_prod_job_with_no_environment_and_no_earlier_stage(self):
        text = self.deploy("deploy-02-no-stage-environment")
        prod = job_text(text, "deploy-prod")
        self.assertNotIn("environment:", prod)
        self.assertNotIn("deploy-staging", text)
        self.assertNotIn("check-staged.sh", text)

    def test_the_other_cases_keep_each_deploy_job_in_its_own_environment_and_group(self):
        for name in DEPLOY_CASES:
            if name == "deploy-02-no-stage-environment":
                continue
            text = self.deploy(name)
            for job, stage in (("deploy-dev", "dev"), ("deploy-staging", "staging"), ("deploy-prod", "prod")):
                body = job_text(text, job)
                self.assertIn(f"environment: {stage}\n", body, name)
                self.assertIn(f"group: deploy-{stage}\n", body, name)
                self.assertIn("cancel-in-progress: false", body, name)

    def test_the_fixtures_differ_from_the_good_workflow_only_where_the_rule_needs(self):
        good = self.deploy("deploy-02-tag-run-staging-record")
        self.assertNotIn("pnpm install", good)
        self.assertNotIn("aws-access-key-id", good)
        self.assertIn("role-to-assume: ${{ vars.AWS_ROLE_PROD }}", good)
        self.assertIn("timeout-minutes: 30", job_text(good, "deploy-prod"))
        self.assertIn("pnpm install", self.deploy("deploy-01-build-in-deploy-job"))
        self.assertIn("aws-access-key-id", self.deploy("deploy-04-long-lived-key"))
        self.assertNotIn("timeout-minutes", job_text(self.deploy("deploy-09-missing-timeout"), "deploy-dev"))
        self.assertIn("terraform apply", self.deploy("deploy-10-no-pr-dry-run"))
        self.assertNotIn("skip-notice", self.deploy("deploy-08-docs-only-deploys"))
        self.assertNotIn("needs.ci.outputs.code", job_text(self.deploy("deploy-08-docs-only-deploys"), "deploy-dev"))

    def test_the_script_fixtures_hold_the_check_that_their_case_removes(self):
        def script(case):
            return read(os.path.join(case_dir(case), "repo", "scripts", "deploy-lambda.sh"))
        good = script("deploy-02-tag-run-staging-record")
        self.assertIn("sha256sum", good)
        self.assertIn('grep -q "$sha"', good)
        self.assertNotIn("sha256sum", script("deploy-03-no-digest-check"))
        self.assertNotIn("grep", script("deploy-05-status-only-check"))
        self.assertIn("exit 0", script("deploy-06-silent-skip").split("aws s3 cp")[0])

    def test_the_two_timeout_cases_share_one_workflow_and_only_the_history_case_records_an_intake(self):
        with_history = "deploy-09-timeout-too-high-with-history"
        no_history = "deploy-09-timeout-too-high-no-history"
        self.assertEqual(self.deploy(with_history), self.deploy(no_history))
        self.assertFalse(os.path.exists(os.path.join(case_dir(no_history), "repo", "intake.json")))
        self.assertNotIn("intake.json", read(os.path.join(case_dir(no_history), "prompt.md")))


class RollbackCases(unittest.TestCase):
    NO_FILE = "rollback-01-no-rollback-workflow"
    BUILDS = "rollback-02-rollback-builds"
    RUN_ARTIFACT = "rollback-03-run-artifact-only"
    MATRIX = "rollback-04-parallel-prod-targets"
    NATIVE = "rollback-05-native-rollback-disabled"
    OTHER_GROUP = "rollback-06-other-concurrency-group"

    @classmethod
    def setUpClass(cls):
        cls.rollbacks = {name: workflow_text(name, "rollback.yml") for name in ROLLBACK_CASES if name != cls.NO_FILE}
        cls.deploys = {name: workflow_text(name, "deploy.yml") for name in ROLLBACK_CASES}

    def job(self, case):
        return job_text(self.rollbacks[case], "rollback")

    def test_the_rollback_cases_are_exactly_these_with_their_lists(self):
        found = {n for n in review_cases() if n.startswith("rollback-")}
        self.assertEqual(found, set(ROLLBACK_CASES))
        for name, lists in ROLLBACK_CASES.items():
            self.assertEqual(expect_lists(name), lists, name)

    def test_every_case_but_the_first_has_a_rollback_workflow_and_the_first_has_none(self):
        workflows = os.path.join(case_dir(self.NO_FILE), "repo", ".github", "workflows")
        self.assertFalse(os.path.exists(os.path.join(workflows, "rollback.yml")))
        self.assertTrue(os.path.exists(os.path.join(workflows, "deploy.yml")))

    def test_every_rollback_workflow_is_a_dispatch_on_a_tag_with_an_environment_choice(self):
        for name, text in self.rollbacks.items():
            self.assertIn("workflow_dispatch:", text, name)
            self.assertNotIn("push:", text, name)
            self.assertIn("type: choice", text, name)
            self.assertNotIn("type: string", text, name)
            self.assertIn("if: github.ref_type == 'tag'", self.job(name), name)

    def test_the_cases_that_keep_the_deploy_script_run_it_and_have_no_install_and_no_build(self):
        for name in self.rollbacks:
            if name in (self.BUILDS, self.NATIVE):
                continue
            job = self.job(name)
            self.assertIn('run: ./scripts/deploy-lambda.sh "$BUCKET" "$SHA" "$FUNCTION" "$VERSION_URL"', job, name)
            self.assertNotIn("pnpm install", job, name)
            self.assertNotIn("pnpm build", job, name)

    def test_the_rule_fixtures_differ_from_the_good_one_only_where_the_rule_needs(self):
        other_group = self.job(self.OTHER_GROUP)
        self.assertIn("group: rollback-${{ inputs.environment }}\n", other_group)
        for name in self.rollbacks:
            if name != self.OTHER_GROUP:
                job = self.job(name)
                self.assertIn("group: deploy-${{ inputs.environment }}\n", job, name)
                self.assertIn("cancel-in-progress: false", job, name)
        builds = self.job(self.BUILDS)
        self.assertIn("pnpm install --frozen-lockfile", builds)
        self.assertIn("pnpm build", builds)
        self.assertIn("deploy-lambda.sh", builds)
        matrix = self.job(self.MATRIX)
        self.assertIn("matrix:", matrix)
        self.assertNotIn("max-parallel", matrix)
        self.assertIn("options: [staging, prod]", self.rollbacks[self.MATRIX])
        native = self.job(self.NATIVE)
        self.assertIn("aws cloudformation deploy", native)
        self.assertIn("--disable-rollback", native)
        self.assertNotIn("deploy-lambda.sh", native)

    def test_the_run_artifact_case_stores_no_zip_in_s3_and_assumes_no_artifacts_role(self):
        package = job_text(self.deploys[self.RUN_ARTIFACT], "package")
        self.assertIn("actions/upload-artifact@", package)
        self.assertNotIn("aws s3 cp", package)
        self.assertNotIn("role-to-assume", package)

    def test_the_deploy_side_is_the_good_deploy_workflow_in_every_case_but_the_run_artifact_case(self):
        good = workflow_text("deploy-02-tag-run-staging-record", "deploy.yml")
        for name, text in self.deploys.items():
            if name != self.RUN_ARTIFACT:
                self.assertEqual(text, good, name)


class ReleasePublishCases(unittest.TestCase):
    """The RELEASE and PUBLISH cases: a good Changesets library, changed only where the rule of a case needs it."""
    ALL = {**RELEASE_CASES, **PUBLISH_CASES}
    RENAMED = "publish-05-publish-workflow-renamed"

    @classmethod
    def setUpClass(cls):
        cls.releases = {name: workflow_text(name, "publish.yml" if name == cls.RENAMED else "release.yml")
                        for name in cls.ALL}

    def test_the_cases_are_exactly_these_with_their_lists(self):
        found = {n for n in review_cases() if n.startswith(("release-", "publish-"))}
        self.assertEqual(found, set(self.ALL))
        for name, lists in self.ALL.items():
            self.assertEqual(expect_lists(name), lists, name)

    def test_every_case_has_a_ci_workflow_a_changeset_config_and_one_release_workflow(self):
        for name in self.ALL:
            workflows = os.path.join(case_dir(name), "repo", ".github", "workflows")
            self.assertEqual(sorted(os.listdir(workflows)),
                             ["ci.yml", "publish.yml" if name == self.RENAMED else "release.yml"], name)
            self.assertTrue(os.path.exists(os.path.join(case_dir(name), "repo", ".changeset", "config.json")), name)

    def test_the_good_files_hold_the_forms_that_the_rule_texts_pass(self):
        good = self.releases["release-01-two-release-tools"]
        job = job_text(good, "release")
        for text in ("branches: [main]", "workflow_dispatch:", "environment: release", "id-token: write",
                     "actions/create-github-app-token@", "private-key: ${{ secrets.RELEASE_APP_PRIVATE_KEY }}",
                     "node-version: 24", "package-manager-cache: false", "pnpm install --frozen-lockfile",
                     "publish: pnpm changeset publish"):
            self.assertIn(text, good)
        self.assertIn("timeout-minutes: 15", job)
        self.assertNotIn("cache: pnpm", good)
        for name in ("release-03-no-tag-ruleset", "publish-05-publish-workflow-renamed"):
            self.assertEqual(self.releases[name], good, name)

    def test_release_01_has_two_release_tools(self):
        package = read(os.path.join(case_dir("release-01-two-release-tools"), "repo", "package.json"))
        self.assertIn('"semantic-release"', package)
        self.assertIn('"@changesets/cli"', package)

    def test_release_02_makes_a_lightweight_tag(self):
        job = job_text(self.releases["release-02-lightweight-tag"], "release")
        self.assertIn('git tag "v$VERSION"', job)
        self.assertNotRegex(job, r"git tag (-a|-s|-m)")

    def test_release_04_uses_a_pat_and_no_app_token(self):
        text = self.releases["release-04-pat-token"]
        self.assertIn("secrets.RELEASE_PAT", text)
        self.assertNotIn("create-github-app-token", text)

    def test_release_05_runs_on_a_tag_push(self):
        text = self.releases["release-05-tag-push-trigger"]
        self.assertIn("tags: ['v*']", text)
        self.assertNotIn("branches: [main]", text)

    def test_release_06_turns_the_notes_off_in_the_config_and_in_the_action_input(self):
        config = read(os.path.join(case_dir("release-06-no-release-notes"), "repo", ".changeset", "config.json"))
        self.assertEqual(json.loads(config)["changelog"], False)
        self.assertIn("createGithubReleases: false", self.releases["release-06-no-release-notes"])

    def test_publish_01_stores_an_npm_token_and_has_no_id_token(self):
        text = self.releases["publish-01-npm-token"]
        self.assertIn("secrets.NPM_TOKEN", text)
        self.assertNotIn("id-token", text)

    def test_publish_02_caches_the_package_manager(self):
        text = self.releases["publish-02-cached-publish"]
        self.assertIn("cache: pnpm", text)
        self.assertNotIn("package-manager-cache", text)

    def test_publish_03_is_a_monorepo_that_publishes_each_package_in_a_loop(self):
        text = self.releases["publish-03-no-dependency-order"]
        self.assertIn("npm publish", text)
        self.assertNotIn("changeset publish", text)
        for package in ("core", "cli"):
            data = json.loads(read(os.path.join(case_dir("publish-03-no-dependency-order"), "repo", "packages",
                                                package, "package.json")))
            self.assertNotIn("private", data)
        self.assertIn("packages/*", read(os.path.join(case_dir("publish-03-no-dependency-order"), "repo",
                                                      "pnpm-workspace.yaml")))

    def test_publish_04_runs_a_plain_npm_publish_with_no_view_check(self):
        text = self.releases["publish-04-no-published-version-check"]
        self.assertIn("run: npm publish", text)
        self.assertNotIn("npm view", text)
        self.assertNotIn("changeset publish", text)


class RecordedIntakeRelease03(RecordedIntakeChecks, unittest.TestCase):
    CASE = "release-03-no-tag-ruleset"

    def test_the_rulesets_are_detected_and_hold_no_tag_ruleset(self):
        fact = self.intake["rulesets"]
        self.assertEqual(fact["status"], "detected")
        self.assertTrue(fact["value"])
        self.assertTrue(all(ruleset["target"] != "tag" for ruleset in fact["value"]))

    def test_the_repo_has_one_release_tool_a_published_package_and_a_release_workflow(self):
        self.assertEqual(self.intake["release_tool"]["value"], ["changesets"])
        self.assertEqual([entry["value"] for entry in self.intake["package_kind"]["value"]], ["published"])
        self.assertIn(".github/workflows/release.yml", self.intake["existing_workflows"]["value"])


class RecordedIntakeDeploy09(RecordedIntakeChecks, unittest.TestCase):
    CASE = "deploy-09-timeout-too-high-with-history"

    def timeouts(self):
        return job_timeouts(workflow_text(self.CASE, "deploy.yml"))

    def test_the_deploy_history_is_detected_with_10_runs_and_the_run_history_is_unknown(self):
        history = self.intake["deploy_history"]
        self.assertEqual(history["status"], "detected")
        self.assertEqual(history["value"]["runs"], 10)
        self.assertEqual(self.intake["run_history"]["status"], "unknown")
        self.assertIsNone(self.intake["run_history"]["value"])

    def test_each_median_is_at_most_270_seconds_so_the_session_cap_does_not_bind(self):
        for name, job in self.intake["deploy_history"]["value"]["jobs"].items():
            self.assertLessEqual(job["median_seconds"], 270, name)

    def test_every_history_job_has_a_timeout_more_than_2x_the_proposal_and_not_above_60(self):
        timeouts = self.timeouts()
        jobs = self.intake["deploy_history"]["value"]["jobs"]
        self.assertTrue(jobs)
        for name, job in jobs.items():
            proposal = min(60, max(5, math.ceil(3 * job["median_seconds"] / 60)))
            self.assertIn(name, timeouts, name)
            self.assertGreater(timeouts[name], 2 * proposal, name)
            self.assertLessEqual(timeouts[name], 60, name)

    def test_every_deploy_job_but_the_called_workflow_has_a_timeout(self):
        text = workflow_text(self.CASE, "deploy.yml")
        self.assertEqual(len(self.timeouts()), len(job_ids(text)) - 1)
        self.assertIn("uses: ./.github/workflows/ci.yml", job_text(text, "ci"))
        self.assertNotIn("timeout-minutes", job_text(text, "ci"))


PROTECT_GOOD = {
    "environments": [{"name": name, "reviewers": name == "prod", "wait_timer": 0, "branch_policy": "custom",
                      "admin_bypass": False} for name in ("artifacts", "dev", "staging", "prod")],
    "plan": {"visibility": "private", "plan": "enterprise", "reviewers_available": True},
    "rulesets": [{"name": "main", "target": "branch", "enforcement": "active"},
                 {"name": "release tags", "target": "tag", "enforcement": "active"}],
    "classic_protection": {"branch": "main", "protected": False, "required_pull_request_reviews": False,
                           "enforce_admins": False},
    "required_checks": ["CI passed"],
    "release_tag_pattern": "v*",
    "existing_workflows": [".github/workflows/ci.yml", ".github/workflows/deploy.yml",
                           ".github/workflows/rollback.yml"],
}


class ProtectCases(unittest.TestCase):
    """The PROTECT cases: one good deploy and rollback repo with a recorded intake, changed only where a rule needs."""
    FIRST = "protect-01-no-main-ruleset"
    COMMENT = "protect-07-claimed-protection-missing"
    ROLE = "protect-08-repo-wide-role-arn"
    GROUP = "group: deploy-${{ inputs.environment }}"

    @classmethod
    def setUpClass(cls):
        cls.deploys = {name: workflow_text(name, "deploy.yml") for name in PROTECT_CASES}
        cls.rollbacks = {name: workflow_text(name, "rollback.yml") for name in PROTECT_CASES}

    def test_the_cases_are_exactly_these_with_their_lists(self):
        self.assertEqual({n for n in review_cases() if n.startswith("protect-")}, set(PROTECT_CASES))
        for name, lists in PROTECT_CASES.items():
            self.assertEqual(expect_lists(name), lists, name)

    def test_every_case_has_a_ci_deploy_and_rollback_workflow_and_no_release_workflow(self):
        for name in PROTECT_CASES:
            workflows = os.path.join(case_dir(name), "repo", ".github", "workflows")
            self.assertEqual(sorted(os.listdir(workflows)), ["ci.yml", "deploy.yml", "rollback.yml"], name)

    def test_the_good_files_are_the_deploy_02_files_and_the_rollback_with_the_deploy_group(self):
        base = os.path.join("deploy-02-tag-run-staging-record", "repo")
        for rel in (".github/workflows/ci.yml", "package.json", "pnpm-lock.yaml", "scripts/check-staged.sh",
                    "scripts/deploy-lambda.sh"):
            good = read(os.path.join(EVALS, base, rel))
            for name in PROTECT_CASES:
                self.assertEqual(read(os.path.join(case_dir(name), "repo", rel)), good, (name, rel))
        source = workflow_text("rollback-06-other-concurrency-group", "rollback.yml")
        good_rollback = source.replace("group: rollback-${{ inputs.environment }}", self.GROUP)
        self.assertNotEqual(good_rollback, source)
        for name in PROTECT_CASES:
            self.assertEqual(self.rollbacks[name], good_rollback, name)

    def test_the_fixtures_differ_from_the_good_deploy_workflow_only_where_the_rule_needs(self):
        good = workflow_text("deploy-02-tag-run-staging-record", "deploy.yml")
        for name in PROTECT_CASES:
            if name not in (self.COMMENT, self.ROLE):
                self.assertEqual(self.deploys[name], good, name)
        self.assertEqual(self.deploys[self.COMMENT].replace("  # Required reviewers approve every prod deploy.\n", ""),
                         good)
        self.assertEqual(self.deploys[self.COMMENT].count("# Required reviewers approve every prod deploy."), 1)
        changed = good.replace("    environment: artifacts\n", "").replace("vars.AWS_ROLE_ARTIFACTS", "vars.AWS_ROLE_ARN")
        self.assertEqual(self.deploys[self.ROLE], changed)

    def test_protect_07_has_a_comment_with_a_listed_phrase_and_the_environment_name_before_the_prod_job(self):
        text = self.deploys[self.COMMENT]
        line = next(l for l in text.splitlines() if l.strip().startswith("# Required reviewers"))
        self.assertIn("required reviewer", line.lower())
        self.assertRegex(line, r"\bprod\b")
        self.assertLess(text.index(line), text.index("  deploy-prod:\n"))

    def test_protect_08_has_a_job_with_no_environment_that_reads_a_role_arn(self):
        job = job_text(self.deploys[self.ROLE], "package")
        self.assertNotIn("environment:", job)
        self.assertIn("vars.AWS_ROLE_ARN", job)
        for other in ("deploy-dev", "deploy-staging", "deploy-prod"):
            self.assertIn("environment:", job_text(self.deploys[self.ROLE], other))

    def test_every_job_that_names_an_environment_names_one_of_the_recorded_environments(self):
        names = {entry["name"] for entry in PROTECT_GOOD["environments"]}
        for name in PROTECT_CASES:
            for text in (self.deploys[name], self.rollbacks[name]):
                found = set(re.findall(r"(?m)^    environment: (.+)$", text))
                self.assertTrue(found, name)
                for environment in found - {"${{ inputs.environment }}"}:
                    self.assertIn(environment, names, (name, environment))

    def test_the_trigger_and_lock_note_graders_exist_exactly_where_the_design_says(self):
        for name in review_cases():
            files = grader_files(name)
            self.assertEqual("section-graph-triggers.md" in files, name in PROTECT_CASES, name)
            self.assertEqual("section-lock-note.md" in files, name in PROTECT_LOCK_CASES, name)

    def grader(self, case, file):
        return frontmatter(os.path.join(case_dir(case), "graders", file))

    def test_the_trigger_grader_wants_the_three_lines_in_order_and_no_fourth_trigger_line(self):
        meta = self.grader(self.FIRST, "section-graph-triggers.md")
        self.assertEqual((meta["type"], meta["flags"]), ("regex", "m"))
        for line in ("push main: Deploy", "tag v\\*: Deploy", "dispatch: Rollback"):
            self.assertIn(line, meta["pattern"])
        fence = "`" * 3
        lines = ["push main: Deploy ── ci ─ package ─ deploy-dev ─ deploy-staging",
                 "tag v*: Deploy ── deploy-prod (final tag, needs the staging record)",
                 "dispatch: Rollback ── rollback (a tag, one environment)"]

        def sketch(body):
            return "\n".join(["## Job graph after the fixes", "", fence] + body + [fence, "", "## Approve"])

        def matches(body):
            return re.search(meta["pattern"], sketch(body), re.M) is not None

        self.assertTrue(matches(lines))
        self.assertTrue(matches([lines[0], "  note", lines[1], lines[2], "  deploy-prod ─ done"]))
        self.assertFalse(matches(lines[:2]))
        self.assertFalse(matches([lines[1], lines[0], lines[2]]))
        self.assertFalse(matches(lines + ["push main: Release ── release"]))
        self.assertFalse(matches([lines[0], lines[1], "push main: Release ── release", lines[2]]))

    def test_the_lock_note_grader_matches_the_note_line_only(self):
        meta = self.grader(self.FIRST, "section-lock-note.md")
        self.assertEqual((meta["type"], meta["flags"]), ("regex", "m"))
        report = make_report(required=[row("PROTECT-02", lock=True)])
        self.assertTrue(re.search(meta["pattern"], report, re.M))
        self.assertFalse(re.search(meta["pattern"], make_report(required=[row("NAME-06")]), re.M))


class RecordedIntakeProtect(RecordedIntakeChecks):
    """A PROTECT case: the recorded intake holds the good state of each fact that a PROTECT rule reads, but one."""
    CHANGED = ()

    def test_every_fact_but_the_changed_one_is_the_good_state_and_detected(self):
        for name, good in PROTECT_GOOD.items():
            if name in self.CHANGED:
                self.assertNotEqual(self.intake[name]["value"], good, name)
            else:
                self.assertEqual(self.intake[name]["value"], good, name)
            self.assertEqual(self.intake[name]["status"], "detected", name)

    def environment(self, name):
        return next(e for e in self.intake["environments"]["value"] if e["name"] == name)


class RecordedIntakeProtect01(RecordedIntakeProtect, unittest.TestCase):
    CASE = "protect-01-no-main-ruleset"
    CHANGED = ("rulesets", "classic_protection")

    def test_the_changed_fact_differs_only_in_the_part_of_its_rule(self):
        self.assertEqual(self.intake["rulesets"]["value"], [PROTECT_GOOD["rulesets"][1]])
        self.assertEqual(self.intake["classic_protection"]["value"],
                         {"branch": "main", "protected": True, "required_pull_request_reviews": True,
                          "enforce_admins": True})


class RecordedIntakeProtect02(RecordedIntakeProtect, unittest.TestCase):
    CASE = "protect-02-no-tag-ruleset"
    CHANGED = ("rulesets",)

    def test_the_changed_fact_differs_only_in_the_part_of_its_rule(self):
        self.assertEqual(self.intake["rulesets"]["value"], [PROTECT_GOOD["rulesets"][0]])


class RecordedIntakeProtect03(RecordedIntakeProtect, unittest.TestCase):
    CASE = "protect-03-env-accepts-any-branch"
    CHANGED = ("environments",)

    def test_the_changed_fact_differs_only_in_the_part_of_its_rule(self):
        self.assertEqual(self.environment("prod")["branch_policy"], "none")
        self.assertEqual({e["branch_policy"] for e in self.intake["environments"]["value"]}, {"custom", "none"})


class RecordedIntakeProtect04(RecordedIntakeProtect, unittest.TestCase):
    CASE = "protect-04-prod-no-reviewers"
    CHANGED = ("environments",)

    def test_the_changed_fact_differs_only_in_the_part_of_its_rule(self):
        self.assertFalse(self.environment("prod")["reviewers"])
        self.assertTrue(self.intake["plan"]["value"]["reviewers_available"])


class RecordedIntakeProtect05(RecordedIntakeProtect, unittest.TestCase):
    CASE = "protect-05-admin-bypass-on-prod"
    CHANGED = ("environments",)

    def test_the_changed_fact_differs_only_in_the_part_of_its_rule(self):
        self.assertTrue(self.environment("prod")["admin_bypass"])
        self.assertTrue(self.environment("prod")["reviewers"])
        self.assertEqual(self.environment("prod")["branch_policy"], "custom")


class RecordedIntakeProtect06(RecordedIntakeProtect, unittest.TestCase):
    CASE = "protect-06-classic-and-ruleset-stack"
    CHANGED = ("classic_protection",)

    def test_the_changed_fact_differs_only_in_the_part_of_its_rule(self):
        self.assertTrue(self.intake["classic_protection"]["value"]["protected"])
        self.assertEqual(self.intake["rulesets"]["value"], PROTECT_GOOD["rulesets"])
        self.assertEqual(self.intake["required_checks"]["value"], ["CI passed"])


class RecordedIntakeProtect07(RecordedIntakeProtect, unittest.TestCase):
    CASE = "protect-07-claimed-protection-missing"
    CHANGED = ("environments",)

    def test_the_changed_fact_differs_only_in_the_part_of_its_rule(self):
        self.assertFalse(self.environment("prod")["reviewers"])


class RecordedIntakeProtect08(RecordedIntakeProtect, unittest.TestCase):
    CASE = "protect-08-repo-wide-role-arn"
    CHANGED = ()

    def test_the_changed_fact_differs_only_in_the_part_of_its_rule(self):
        self.assertEqual(self.intake["environments"]["value"], PROTECT_GOOD["environments"])


def repo_texts(repo):
    """Map of path to text for every file under a fixture repo folder, the hidden .github folder included.

    os.walk, not glob: glob skips hidden folders, so the workflow files were never checked."""
    return {os.path.join(folder, fname): read(os.path.join(folder, fname))
            for folder, _dirs, names in os.walk(repo) for fname in names}


class CdFixtures(unittest.TestCase):
    """Fixtures of every CD case that has a fixture keep private names out (the CD part of NewFixtures)."""
    OWNERS = ("actions", "pnpm", "dorny", "aws-actions", "changesets", "hashicorp")

    @classmethod
    def setUpClass(cls):
        cls.cases = [n for n in case_names() if n.startswith(CD_PREFIXES) or n == "clean-cd"]
        cls.texts = {}
        for name in cls.cases:
            cls.texts.update(repo_texts(os.path.join(case_dir(name), "repo")))

    def test_the_cd_cases_exist(self):
        self.assertEqual(len(self.cases), CD_CASE_COUNT)

    def test_the_four_create_cd_cases_exist(self):
        for name in ("create-cd-lambda-app", "create-cd-changesets-library", "create-cd-monorepo-publish",
                     "create-cd-terraform"):
            self.assertIn(name, self.cases)

    def test_no_cd_fixture_holds_a_url_but_the_two_git_url_forms(self):
        for path, text in self.texts.items():
            for form in GIT_URLS:
                text = re.sub(form, "", text)
            self.assertNotRegex(text, r"https?://", path)

    def test_every_uses_owner_is_on_the_allowlist_and_a_local_reference_is_skipped(self):
        for path, text in self.texts.items():
            for owner in re.findall(r"uses:\s*([A-Za-z][^/\s@]*)/", text):
                self.assertIn(owner, self.OWNERS, path)

    def test_every_external_uses_has_a_full_sha_and_a_version_comment(self):
        for path, text in self.texts.items():
            for line in re.findall(r"uses:\s*(?!\./)(\S.*)", text):
                if line == UNPINNED_USES and f"{os.sep}{UNPINNED_CASE}{os.sep}" in path:
                    continue  # the one mutable pin that fx-cd-tag-unpinned exists to hold (SEC-01)
                self.assertRegex(line, FULL_SHA_PIN, path)

    def test_every_package_name_starts_with_example(self):
        for path, text in self.texts.items():
            if os.path.basename(path) == "package.json":
                self.assertTrue(json.loads(text)["name"].startswith("example-"), path)

    def test_the_version_endpoint_is_a_variable_and_never_a_url(self):
        for path, text in self.texts.items():
            if path.endswith(".yml"):
                self.assertNotIn("version_url=http", text, path)
                self.assertNotRegex(text, r"VERSION_URL:\s*(?!\$\{\{)\S", path)


CANDIDATE_CASES = {
    "fx-cd-no-timeout": (["DEPLOY-09"], []),
    "fx-cd-no-concurrency": (["COST-02"], []),
    "fx-cd-rebuild-per-env": (["DEPLOY-01"], []),
    "fx-cd-prod-from-push": (["DEPLOY-02", "PROTECT-04"], []),
    "fx-cd-role-in-yaml": (["DEPLOY-04"], []),
    "fx-cd-tag-unpinned": (["SEC-01"], []),
    "fx-cd-rollback-by-input": (["ROLLBACK-01", "ROLLBACK-02"], []),
    "fx-cd-silent-skip": (["DEPLOY-06"], []),
    "fx-cd-publish-no-guard": (["RELEASE-02", "RELEASE-05", "PUBLISH-04"], []),
}
GOOD_REFERENCE = "fx-cd-good-reference"
# The candidates that start from the good deploy files of deploy-02 (the publish case starts from release-05).
DEPLOY_BASED = [n for n in CANDIDATE_CASES if n != "fx-cd-publish-no-guard"]
ALL_CANDIDATES = list(CANDIDATE_CASES) + [GOOD_REFERENCE]
WITH_DEPLOY = DEPLOY_BASED + [GOOD_REFERENCE]
SECTION_FILES = {f"{name}.md" for name in SECTION_GRADERS}


class CandidateCases(unittest.TestCase):
    """The ten fx-cd candidates of the sample catalog: nine bad fixtures and one good reference."""

    @classmethod
    def setUpClass(cls):
        cls.deploys = {n: workflow_text(n, "deploy.yml") for n in WITH_DEPLOY}
        cls.rollbacks = {n: workflow_text(n, "rollback.yml") for n in WITH_DEPLOY}
        cls.good_deploy = workflow_text("deploy-02-tag-run-staging-record", "deploy.yml")
        cls.good_rollback = workflow_text("protect-04-prod-no-reviewers", "rollback.yml")

    def test_the_candidates_are_exactly_these_with_their_lists(self):
        names = {n for n in case_names() if n.startswith("fx-cd-")}
        self.assertEqual(names, set(CANDIDATE_CASES) | {GOOD_REFERENCE})
        for name, lists in CANDIDATE_CASES.items():
            self.assertEqual(expect_lists(name), lists, name)

    def test_the_good_reference_expects_nothing_and_forbids_what_clean_cd_forbids(self):
        self.assertEqual(expect_lists(GOOD_REFERENCE), ([], expect_lists("clean-cd")[1]))

    def test_every_candidate_has_the_review_prompt_and_the_report_graders(self):
        for name in ALL_CANDIDATES:
            expect, forbid = expect_lists(name)
            wanted = SECTION_FILES | {"no-edit.md", "no-write.md", "no-shell-write.md", "fix-quality.md"}
            wanted |= {f"expect-{i}.md" for i in expect} | {f"forbid-{i}.md" for i in forbid}
            self.assertEqual(grader_files(name), wanted, name)
            prompt = read(os.path.join(case_dir(name), "prompt.md"))
            self.assertIn("Review our CI and CD setup in this repo.", prompt)

    def test_the_deploy_based_candidates_keep_the_good_ci_and_package_files(self):
        base = os.path.join(EVALS, "deploy-02-tag-run-staging-record", "repo")
        for name in DEPLOY_BASED:
            for rel in (".github/workflows/ci.yml", "package.json", "pnpm-lock.yaml", "scripts/check-staged.sh"):
                self.assertEqual(read(os.path.join(case_dir(name), "repo", rel)), read(os.path.join(base, rel)),
                                 (name, rel))

    def test_no_timeout_has_no_timeout_in_the_cd_workflows(self):
        self.assertNotIn("timeout-minutes", self.deploys["fx-cd-no-timeout"])
        self.assertNotIn("timeout-minutes", self.rollbacks["fx-cd-no-timeout"])
        self.assertIn("id-token:", self.deploys["fx-cd-no-timeout"])

    def test_no_concurrency_has_no_deploy_group_and_keeps_the_rest(self):
        text = self.deploys["fx-cd-no-concurrency"]
        self.assertNotIn("concurrency:", text)
        self.assertEqual(text.count("timeout-minutes"), self.good_deploy.count("timeout-minutes"))

    def test_rebuild_per_env_installs_and_builds_in_each_of_the_three_stage_jobs(self):
        text = self.deploys["fx-cd-rebuild-per-env"]
        for job in ("deploy-dev", "deploy-staging", "deploy-prod"):
            body = run_text(job_text(text, job))
            self.assertIn("pnpm install --frozen-lockfile", body, job)
            self.assertIn("pnpm build", body, job)
        self.assertNotIn("pnpm build", run_text(job_text(text, "package")))

    def test_prod_from_push_deploys_prod_without_a_tag_or_a_staging_check(self):
        job = job_text(self.deploys["fx-cd-prod-from-push"], "deploy-prod")
        self.assertIn("environment: prod", job)
        self.assertNotIn("check-staged", job)
        self.assertNotIn("ref_type", job)
        self.assertNotIn("deploy-staging", job)

    def test_role_in_yaml_types_a_role_arn_for_each_stage(self):
        text = self.deploys["fx-cd-role-in-yaml"]
        arns = re.findall(r"role-to-assume: (arn:aws:iam::\d{12}:role/\S+)", text)
        self.assertEqual(len(arns), 3)
        self.assertIn("vars.AWS_ROLE_ARTIFACTS", text)

    def test_tag_unpinned_has_one_mutable_pin_and_every_other_external_uses_is_a_full_sha(self):
        mutable = []
        for path in glob.glob(os.path.join(case_dir("fx-cd-tag-unpinned"), "repo", ".github", "workflows", "*.yml")):
            for line in re.findall(r"uses:\s*(?!\./)(\S.*)", read(path)):
                if not re.match(FULL_SHA_PIN, line):
                    mutable.append(line)
        self.assertEqual(mutable, [UNPINNED_USES])

    def test_rollback_by_input_takes_a_text_version_and_builds(self):
        text = self.rollbacks["fx-cd-rollback-by-input"]
        self.assertRegex(text, r"(?m)^      version:\n(?:        .*\n)*?        type: string")
        self.assertIn("ref: ${{ inputs.version }}", text)
        self.assertIn("pnpm build", run_text(text))
        self.assertNotIn("ref_type", text)

    def test_silent_skip_skips_on_an_empty_setting_and_exits_with_success(self):
        script = read(os.path.join(case_dir("fx-cd-silent-skip"), "repo", "scripts", "deploy-lambda.sh"))
        self.assertRegex(script, r'if \[ -z "\$function_name" \]; then\n(?:.*\n)*?  exit 0\nfi')
        self.assertIn("vars.FUNCTION_NAME != ''", job_text(self.deploys["fx-cd-silent-skip"], "deploy-dev"))

    def test_publish_no_guard_publishes_on_a_tag_push_with_no_main_check_and_no_published_version_check(self):
        text = workflow_text("fx-cd-publish-no-guard", "release.yml")
        self.assertRegex(text, r"(?m)^    tags: \['v\*'\]")
        self.assertIn("git tag -a", run_text(text))
        self.assertIn("npm publish", run_text(text))
        for absent in ("merge-base", "npm view", "changesets/action"):
            self.assertNotIn(absent, text)

    def test_the_good_reference_is_the_clean_flow_plus_a_record_job_that_runs_after_a_failure(self):
        text = self.deploys[GOOD_REFERENCE]
        clean = workflow_text("clean-cd", "deploy.yml")
        self.assertTrue(text.startswith(clean.rstrip("\n") + "\n  record:\n"))
        job = job_text(text, "record")
        self.assertIn("!cancelled()", job)
        self.assertIn("needs.deploy-prod.result", job)
        self.assertIn("timeout-minutes", job)
        self.assertEqual(self.rollbacks[GOOD_REFERENCE], workflow_text("clean-cd", "rollback.yml"))


class ProdFromPushIntake(RecordedIntakeChecks, unittest.TestCase):
    CASE = "fx-cd-prod-from-push"

    def test_prod_has_no_reviewers_and_the_other_environments_are_detected(self):
        environments = {e["name"]: e for e in self.intake["environments"]["value"]}
        self.assertFalse(environments["prod"]["reviewers"])
        self.assertEqual(self.intake["environments"]["status"], "detected")

    def test_the_intake_is_the_one_of_the_protect_cases(self):
        protect = read(os.path.join(case_dir("protect-04-prod-no-reviewers"), "repo", "intake.json"))
        self.assertEqual(read(os.path.join(case_dir(self.CASE), "repo", "intake.json")), protect)


class RecordedStackFacts(unittest.TestCase):
    def test_each_recorded_stack_fact_is_what_the_intake_script_finds_in_the_repo_folder(self):
        paths = sorted(glob.glob(os.path.join(EVALS, "*", "repo", "intake.json")))
        self.assertTrue(paths)
        for path in paths:
            with tempfile.TemporaryDirectory() as tmp:
                repo = os.path.join(tmp, "repo")
                shutil.copytree(os.path.dirname(path), repo, ignore=shutil.ignore_patterns("intake.json"))
                proc = subprocess.run([sys.executable, "-I", os.path.join(SKILL, "scripts", "intake.py"), repo],
                                      capture_output=True, text=True, env=dict(os.environ, CICD_PIPELINES_OFFLINE="1"))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with open(path, encoding="utf-8") as handle:
                recorded = json.load(handle)
            self.assertEqual(recorded["stack"], json.loads(proc.stdout)["stack"], path)


TRIGGER_CD_CASES = {
    "trigger-cd-protection": "Set up branch protection for this repo.",
    "trigger-cd-deploy": "Add a deploy workflow for this repo.",
    "trigger-cd-release": "Release this package.",
}


class TriggerCdCases(unittest.TestCase):
    """The three CD trigger cases: a CD request that names no skill, graded by `tool_used: Skill`."""

    def test_the_cases_exist_and_ask_for_their_request(self):
        found = {n for n in case_names() if n.startswith("trigger-cd-")}
        self.assertEqual(found, set(TRIGGER_CD_CASES))
        for name, line in TRIGGER_CD_CASES.items():
            prompt = read(os.path.join(case_dir(name), "prompt.md"))
            self.assertTrue(prompt.rstrip("\n").endswith("\n" + line), name)
            self.assertEqual(frontmatter(os.path.join(case_dir(name), "prompt.md")),
                             frontmatter(os.path.join(case_dir("trigger-edit-workflow"), "prompt.md")), name)

    def test_the_prompt_names_neither_the_skill_nor_a_rule(self):
        for name in TRIGGER_CD_CASES:
            prompt = read(os.path.join(case_dir(name), "prompt.md"))
            self.assertNotIn("cicd-pipelines", prompt)
            self.assertNotRegex(prompt, r"\b(?:[A-Z]+)-\d\d\b")

    def test_each_case_has_one_workflow_file_and_nothing_with_a_url(self):
        for name in TRIGGER_CD_CASES:
            repo = os.path.join(case_dir(name), "repo")
            workflows = os.listdir(os.path.join(repo, ".github", "workflows"))
            self.assertEqual(workflows, ["ci.yml"], name)
            for path, text in repo_texts(repo).items():
                self.assertNotRegex(text, r"https?://", path)
            package = json.loads(read(os.path.join(repo, "package.json")))
            self.assertTrue(package["name"].startswith("example-"), name)
            self.assertIn("build", package["scripts"], name)

    def test_each_case_has_the_empty_lists_and_the_skill_fired_grader_only(self):
        template = read(os.path.join(case_dir("trigger-edit-workflow"), "graders", "skill-fired.md"))
        for name in TRIGGER_CD_CASES:
            self.assertEqual(expect_lists(name), ([], []), name)
            self.assertEqual(grader_files(name), {"skill-fired.md"}, name)
            self.assertEqual(read(os.path.join(case_dir(name), "graders", "skill-fired.md")), template, name)


class TriggerCase(unittest.TestCase):
    def test_the_trigger_case_asks_for_a_workflow_edit_without_naming_the_skill(self):
        prompt = read(os.path.join(case_dir("trigger-edit-workflow"), "prompt.md"))
        self.assertIn(".github/workflows", prompt)
        self.assertNotIn("cicd-pipelines", prompt)

    def test_the_skill_fired_grader_checks_the_skill_tool(self):
        meta = frontmatter(os.path.join(case_dir("trigger-edit-workflow"), "graders", "skill-fired.md"))
        self.assertEqual((meta["type"], meta["tool"], meta["arm"]), ("tool_used", "Skill", "with-only"))
        self.assertTrue(re.search(meta["input_match"], '{"skill": "cicd-pipelines"}'))
        self.assertTrue(re.search(meta["input_match"], '{"skill": "plugin:cicd-pipelines"}'))
        self.assertFalse(re.search(meta["input_match"], '{"skill": "other-skill"}'))


if __name__ == "__main__":
    unittest.main()
