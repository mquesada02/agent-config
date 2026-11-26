import fnmatch
import glob
import json
import os
import re
import shutil
import subprocess
import unittest

from report_fixtures import TempReport, make_report, run_script
from skill_files import LEVELS, PREFIXES, SKILL, all_rules, frontmatter, level, read, rule_entries, rule_files

FIELDS = ("Severity", "Rule", "Check", "Fix")
NAME_IDS = [f"NAME-{n:02d}" for n in range(1, 10)]
GRAPH_IDS = [f"GRAPH-{n:02d}" for n in range(1, 8)]
MAINT_IDS = [f"MAINT-{n:02d}" for n in range(1, 4)]
COST_IDS = [f"COST-{n:02d}" for n in range(1, 9)]
MONO_IDS = ["MONO-01", "MONO-02"]
SEC_IDS = [f"SEC-{n:02d}" for n in range(1, 11)]
DEPLOY_IDS = [f"DEPLOY-{n:02d}" for n in range(1, 11)]
ROLLBACK_IDS = [f"ROLLBACK-{n:02d}" for n in range(1, 7)]
RELEASE_IDS = [f"RELEASE-{n:02d}" for n in range(1, 7)]
PUBLISH_IDS = [f"PUBLISH-{n:02d}" for n in range(1, 6)]
PROTECT_IDS = [f"PROTECT-{n:02d}" for n in range(1, 9)]
ZIZMOR_MAPPING = {
    "unpinned-uses": "SEC-01", "excessive-permissions": "SEC-03", "template-injection": "SEC-04",
    "artipacked": "SEC-05", "dangerous-triggers": "SEC-07", "secrets-inherit": "SEC-08",
    "cache-poisoning": "SEC-09",
}
TOOLS_SECTIONS = ["Detection", "Install hints", "Running the tools", "Merging the output",
                  "zizmor to SEC mapping", "Pin a SHA", "Check the pins", "Offline Node support list"]


def module_files():
    """Every module file that exists, as a path relative to the skill folder."""
    paths = [p for p in glob.glob(os.path.join(SKILL, "*.md")) if os.path.basename(p) != "SKILL.md"]
    paths += glob.glob(os.path.join(SKILL, "rules", "*.md"))
    paths += glob.glob(os.path.join(SKILL, "templates", "*.yml"))
    for script in ("intake.py", "check_workflow.py", "grade_create_results.py"):
        paths += glob.glob(os.path.join(SKILL, "scripts", script))
    return sorted(os.path.relpath(p, SKILL) for p in paths)


class RuleFiles(unittest.TestCase):
    def test_every_rule_file_has_a_known_prefix(self):
        self.assertTrue(rule_files(), "no rule file found")
        for name in rule_files():
            self.assertIn(name, PREFIXES, f"rules/{name}.md has no known prefix")

    def test_rule_ids_are_unique_and_match_their_file_prefix(self):
        seen = set()
        for name, rule_id, _ in all_rules():
            self.assertRegex(rule_id, rf"^{PREFIXES[name]}-\d{{2}}$", f"{rule_id} in rules/{name}.md")
            self.assertNotIn(rule_id, seen, f"{rule_id} appears twice")
            seen.add(rule_id)

    def test_every_rule_entry_has_all_its_fields(self):
        for _, rule_id, fields in all_rules():
            for field in FIELDS:
                self.assertTrue(fields.get(field), f"{rule_id} has no {field}")

    def test_every_severity_starts_with_a_known_level(self):
        for _, rule_id, fields in all_rules():
            self.assertIn(level(fields), LEVELS, f"{rule_id}: {fields['Severity']}")

    def test_the_naming_file_holds_name_01_to_name_09(self):
        ids = [rule_id for rule_id, _ in rule_entries(rule_files()["naming"])]
        self.assertEqual(ids, NAME_IDS)

    def test_name_08_carries_the_flag_mark(self):
        fields = dict(rule_entries(rule_files()["naming"]))["NAME-08"]
        self.assertIn("⚑", " ".join(fields.values()))

    def test_the_naming_file_no_longer_says_the_job_graph_rules_are_coming(self):
        self.assertNotIn("later version of this skill", read(rule_files()["naming"]))
        rule = dict(rule_entries(rule_files()["naming"]))["NAME-04"]["Rule"]
        self.assertTrue(rule.endswith("and the report says to split the job."), rule)


class JobGraphAndMaintainabilityRules(unittest.TestCase):
    def setUp(self):
        self.graph = dict(rule_entries(rule_files()["job-graph"]))
        self.maint = dict(rule_entries(rule_files()["maintainability"]))

    def test_the_job_graph_file_holds_graph_01_to_graph_07_in_order(self):
        ids = [rule_id for rule_id, _ in rule_entries(rule_files()["job-graph"])]
        self.assertEqual(ids, GRAPH_IDS)

    def test_the_maintainability_file_holds_maint_01_to_maint_03_in_order(self):
        ids = [rule_id for rule_id, _ in rule_entries(rule_files()["maintainability"])]
        self.assertEqual(ids, MAINT_IDS)

    def test_the_severity_levels_follow_the_spec_table(self):
        expected = {"GRAPH-01": "required", "GRAPH-02": "suggestion", "GRAPH-03": "required",
                    "GRAPH-04": "required", "GRAPH-05": "suggestion", "GRAPH-06": "required",
                    "GRAPH-07": "required", "MAINT-01": "required", "MAINT-02": "required",
                    "MAINT-03": "suggestion"}
        for rule_id, fields in list(self.graph.items()) + list(self.maint.items()):
            self.assertEqual(level(fields), expected[rule_id], rule_id)

    def test_graph_05_is_a_measured_suggestion_with_the_shard_formula(self):
        fields = self.graph["GRAPH-05"]
        self.assertTrue(fields["Severity"].startswith("suggestion (measured)"), fields["Severity"])
        text = " ".join(fields.values())
        self.assertIn("ceil(m / 8)", text)
        self.assertIn("at most 8", text)
        self.assertIn("`run_history`", text)
        self.assertIn("`unknown`", fields["Check"])
        self.assertNotIn("gh run", text)

    def test_graph_04_holds_the_exact_fail_fast_expression(self):
        self.assertIn("fail-fast: ${{ github.event_name == 'pull_request' }}", self.graph["GRAPH-04"]["Rule"])

    def test_graph_03_names_the_intake_facts(self):
        check = self.graph["GRAPH-03"]["Check"]
        for fact in ("engines", "package_kind", "os_claims", "node_version_app", "supported_node_majors"):
            self.assertIn(f"`{fact}`", check)

    def test_the_thresholds_are_the_rule_table_numbers(self):
        self.assertIn("more than 5 steps", self.graph["GRAPH-07"]["Rule"])
        self.assertIn("more than 10 lines", self.maint["MAINT-01"]["Rule"])
        self.assertIn("3 lines or less", self.maint["MAINT-02"]["Rule"])

    def test_each_file_says_that_no_rule_in_it_is_critical(self):
        self.assertIn("No job graph rule is critical", read(rule_files()["job-graph"]))
        self.assertIn("No maintainability rule is critical", read(rule_files()["maintainability"]))
        self.assertIn("NAME-08", read(rule_files()["job-graph"]))

    def test_every_fix_is_one_sentence(self):
        for rule_id, fields in list(self.graph.items()) + list(self.maint.items()):
            self.assertEqual(len(re.findall(r"[.!?](?:\s|$)", fields["Fix"])), 1, rule_id)


class CostAndMonorepoRules(unittest.TestCase):
    def setUp(self):
        self.cost = dict(rule_entries(rule_files()["cost"]))
        self.mono = dict(rule_entries(rule_files()["monorepo"]))

    def test_the_cost_file_holds_cost_01_to_cost_08_in_order(self):
        self.assertEqual(list(self.cost), COST_IDS)

    def test_the_monorepo_file_holds_mono_01_and_mono_02_in_order(self):
        self.assertEqual(list(self.mono), MONO_IDS)

    def test_the_severity_levels_follow_the_spec_table(self):
        for rule_id, fields in list(self.cost.items()) + list(self.mono.items()):
            self.assertEqual(level(fields), "required", rule_id)

    def test_cost_04_has_a_required_part_and_a_measured_suggestion_part(self):
        fields = self.cost["COST-04"]
        self.assertIn("required (", fields["Severity"])
        self.assertIn("suggestion (measured", fields["Severity"])
        text = " ".join(fields.values())
        self.assertIn("max(5, ceil(3 × m))", text)
        self.assertIn("2×", text)
        self.assertIn("`run_history`", text)
        self.assertIn("`unknown`", fields["Check"])
        self.assertIn("create values", fields["Check"])
        self.assertIn("`median_seconds`", fields["Check"])
        self.assertIn("matrix", fields["Check"])
        for create_value in ("5", "10", "15"):
            self.assertIn(create_value, fields["Rule"])
        self.assertNotIn("gh run", text)

    def test_cost_02_holds_the_exact_concurrency_expressions(self):
        rule = self.cost["COST-02"]["Rule"]
        self.assertIn("group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}", rule)
        self.assertIn("cancel-in-progress: ${{ github.event_name == 'pull_request' }}", rule)

    def test_cost_01_and_cost_03_hold_their_trigger_and_paths_text(self):
        self.assertIn("push: branches: [main]", self.cost["COST-01"]["Rule"])
        self.assertIn("paths-ignore", self.cost["COST-03"]["Rule"])
        self.assertIn("dorny/paths-filter", self.cost["COST-03"]["Rule"])

    def test_cost_05_never_caches_node_modules_or_playwright_browsers(self):
        rule = self.cost["COST-05"]["Rule"]
        for text in ("pnpm install --frozen-lockfile", "npm ci", "yarn install --immutable", "node_modules", "Playwright"):
            self.assertIn(text, rule)

    def test_cost_06_uses_the_intake_facts_and_the_default_vcpu_count(self):
        fields = self.cost["COST-06"]
        for fact in ("visibility", "runner_labels"):
            self.assertIn(f"`{fact}`", fields["Check"])
        self.assertIn("private", fields["Check"])
        self.assertIn("`default`", fields["Check"])
        self.assertIn("2 for a private repo and 4 for a public repo", fields["Rule"])
        self.assertIn("`workers: 1`", fields["Rule"])

    def test_cost_07_pins_the_runner_label(self):
        self.assertIn("ubuntu-24.04", self.cost["COST-07"]["Rule"])

    def test_cost_08_and_mono_01_name_the_fetch_depth_and_each_other(self):
        self.assertIn("`fetch-depth: 0`", self.cost["COST-08"]["Rule"])
        self.assertIn("MONO-01", self.cost["COST-08"]["Rule"])
        rule = self.mono["MONO-01"]["Rule"]
        for text in ("turbo run <task> --affected", "nx affected -t <task>", "nrwl/nx-set-shas",
                     'pnpm --filter "...[origin/<base>]"', "`fetch-depth: 0`", "filter: blob:none"):
            self.assertIn(text, rule)
        self.assertIn("`monorepo`", self.mono["MONO-01"]["Check"])

    def test_cost_08_rule_names_mono_02_as_a_history_need(self):
        self.assertIn("(MONO-01, MONO-02, or a `changes` script that uses git)", self.cost["COST-08"]["Rule"])

    def test_cost_08_skips_a_checkout_that_mono_01_covers(self):
        fields = self.cost["COST-08"]
        self.assertIn("MONO-01", fields["Check"])
        self.assertIn("never a COST-08 finding", fields["Check"])
        self.assertIn("in a job of a PR run is never a COST-08 finding when MONO-01 or MONO-02 applies", fields["Check"])
        self.assertIn("A job that runs only on a push to main is still a COST-08 finding", fields["Check"])

    def test_cost_08_skips_a_checkout_of_a_job_that_runs_the_mono_02_pnpm_filter(self):
        fields = self.cost["COST-08"]
        self.assertIn("has the tool `turbo`, `nx` or `pnpm`, or the workflow runs the pnpm filter.", fields["Check"])
        self.assertIn("MONO-01 and MONO-02 cover every PR-run job of that repo", fields["Check"])
        self.assertIn("whose job no MONO-01 or MONO-02 rule covers", fields["Fix"])
        self.assertIn("a job that MONO-01 or MONO-02 covers", fields["Fix"])

    def test_mono_02_proposes_the_pnpm_filter_and_adds_no_tool(self):
        fields = self.mono["MONO-02"]
        self.assertIn("pnpm filter", fields["Rule"])
        self.assertIn("does not add Turborepo or Nx", fields["Rule"])
        self.assertIn("pnpm", fields["Check"])
        self.assertIn("`monorepo`", fields["Check"])

    def test_every_fix_is_one_sentence(self):
        for rule_id, fields in list(self.cost.items()) + list(self.mono.items()):
            self.assertEqual(len(re.findall(r"[.!?](?:\s|$)", fields["Fix"])), 1, rule_id)

    def test_each_file_says_that_no_rule_in_it_is_critical(self):
        self.assertIn("No cost rule is critical", read(rule_files()["cost"]))
        self.assertIn("No monorepo rule is critical", read(rule_files()["monorepo"]))

    def test_the_monorepo_file_says_it_loads_only_for_a_monorepo(self):
        text = read(rule_files()["monorepo"])
        self.assertIn("only when", text)
        self.assertIn("`monorepo`", text)


class DeployRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = rule_files()["deploy"]
        cls.entries = rule_entries(cls.path)
        cls.deploy = dict(cls.entries)

    def test_the_deploy_file_holds_deploy_01_to_deploy_10_in_order(self):
        self.assertEqual([rule_id for rule_id, _ in self.entries], DEPLOY_IDS)

    def test_the_severity_levels_follow_the_ticket_table(self):
        expected = {"DEPLOY-01": "required", "DEPLOY-02": "required", "DEPLOY-03": "required",
                    "DEPLOY-04": "required", "DEPLOY-05": "required", "DEPLOY-06": "required",
                    "DEPLOY-07": "suggestion", "DEPLOY-08": "required", "DEPLOY-09": "required",
                    "DEPLOY-10": "suggestion"}
        self.assertEqual({rule_id: level(fields) for rule_id, fields in self.deploy.items()}, expected)

    def test_the_file_says_that_no_rule_in_it_is_critical(self):
        self.assertIn("No deploy rule is critical", read(self.path))

    def test_every_check_starts_with_its_kind(self):
        kinds = {"DEPLOY-07": "judgement", "DEPLOY-10": "judgement", "DEPLOY-09": "mechanical + measured"}
        for rule_id, fields in self.deploy.items():
            self.assertTrue(fields["Check"].startswith(kinds.get(rule_id, "mechanical")), rule_id)

    def test_every_fix_is_one_sentence(self):
        for rule_id, fields in self.deploy.items():
            self.assertEqual(len(re.findall(r"[.!?](?:\s|$)", fields["Fix"])), 1, rule_id)

    def test_deploy_02_accepts_the_staging_record_check_in_place_of_needs(self):
        rule = self.deploy["DEPLOY-02"]["Rule"]
        self.assertIn("replaces `needs`", rule)
        self.assertIn("scripts/check-staged.sh", rule)
        self.assertIn("A prod job with the staging-record check and no `needs` is no finding.",
                      self.deploy["DEPLOY-02"]["Check"])

    def test_deploy_04_has_a_required_key_part_and_a_suggestion_role_arn_part(self):
        severity = self.deploy["DEPLOY-04"]["Severity"]
        self.assertIn("required (a long-lived AWS key)", severity)
        self.assertIn("suggestion (a role ARN typed into the YAML)", severity)
        rule = self.deploy["DEPLOY-04"]["Rule"]
        for name in ("the `package` job", "the `artifacts` role", "the deploy jobs", "the rollback jobs"):
            self.assertIn(name, rule)
        self.assertNotIn("after install and build", rule)

    def test_deploy_08_is_an_intended_skip_and_not_a_deploy_06_finding(self):
        rule = self.deploy["DEPLOY-08"]["Rule"]
        self.assertIn("The skip is intended, so it is never a DEPLOY-06 finding.", rule)
        self.assertIn("skip with a notice", rule)

    def test_deploy_09_holds_the_create_values_the_cap_and_the_measured_formula(self):
        fields = self.deploy["DEPLOY-09"]
        self.assertIn("measured", fields["Severity"])
        rule = fields["Rule"]
        for text in ("30 minutes for a deploy job", "10 for a separate verification job", "15 for a release job",
                     "30 for a rollback job", "10 for the `package` job", "5 for the `skip-notice` job",
                     "never above the OIDC role session (60 minutes by default)",
                     "`min(session, max(5, ceil(3 × m)))`", "`m = median_seconds / 60`", "`uses:` at job level"):
            self.assertIn(text, rule)
        self.assertIn("A timeout of exactly 2× the proposal is no finding", fields["Check"])
        self.assertIn("`deploy_history`", fields["Check"])
        self.assertIn("no measured finding", fields["Check"])

    def test_the_rule_text_quotes_no_write_api_call(self):
        text = read(self.path)
        self.assertNotIn("gh api", text)
        self.assertIsNone(re.search(r"-X (POST|PUT|PATCH|DELETE)", text))


class RollbackRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = rule_files()["rollback"]
        cls.entries = rule_entries(cls.path)
        cls.rollback = dict(cls.entries)

    def test_the_rollback_file_holds_rollback_01_to_rollback_06_in_order(self):
        self.assertEqual([rule_id for rule_id, _ in self.entries], ROLLBACK_IDS)

    def test_the_severity_levels_follow_the_ticket_table(self):
        expected = {"ROLLBACK-01": "required", "ROLLBACK-02": "required", "ROLLBACK-03": "required",
                    "ROLLBACK-04": "suggestion", "ROLLBACK-05": "suggestion", "ROLLBACK-06": "required"}
        self.assertEqual({rule_id: level(fields) for rule_id, fields in self.rollback.items()}, expected)

    def test_the_file_says_that_no_rule_in_it_is_critical(self):
        self.assertIn("No rollback rule is critical", read(self.path))

    def test_every_check_starts_with_its_kind(self):
        kinds = {"ROLLBACK-04": "judgement", "ROLLBACK-05": "judgement"}
        for rule_id, fields in self.rollback.items():
            self.assertTrue(fields["Check"].startswith(kinds.get(rule_id, "mechanical")), rule_id)

    def test_every_fix_is_one_sentence(self):
        for rule_id, fields in self.rollback.items():
            self.assertEqual(len(re.findall(r"[.!?](?:\s|$)", fields["Fix"])), 1, rule_id)

    def test_rollback_01_takes_the_version_from_the_ref_and_reports_a_missing_file_by_name(self):
        fields = self.rollback["ROLLBACK-01"]
        for text in ("Its only trigger is `workflow_dispatch`", "never from a free-text input", "A final tag has no pre-release suffix",
                     "does not read which tag is older", "`type: string`", "`version`, `tag` or `ref`",
                     "An environment choice input (`type: choice`) is allowed"):
            self.assertIn(text, fields["Rule"])
        self.assertIn("github.ref_type == 'tag'", fields["Check"])
        self.assertIn("`rollback.yml` as its location", fields["Check"])

    def test_rollback_02_forbids_a_build_and_keeps_the_digest_and_version_checks(self):
        rule = self.rollback["ROLLBACK-02"]["Rule"]
        for text in ("never builds", "reuses the stored artifact of the tag, or the previous version on the target",
                     "the digest check of DEPLOY-03", "the version check of DEPLOY-05",
                     "the same deploy script as the deploy jobs", "DEPLOY-01 covers `deploy.yml` only"):
            self.assertIn(text, rule)

    def test_rollback_03_names_the_storage_places_and_flags_the_run_artifact_action(self):
        fields = self.rollback["ROLLBACK-03"]
        for text in ("S3 with versioning", "in a registry", "as Lambda versions", "under the commit SHA",
                     "does not check it", "`actions/upload-artifact`", "1 to 90 days"):
            self.assertIn(text, fields["Rule"])
        for text in ("S3", "commit SHA", "registry", "Lambda version"):
            self.assertIn(text, fields["Fix"])

    def test_rollback_04_defines_the_prod_target_and_leaves_fail_fast_to_graph_04(self):
        rule = self.rollback["ROLLBACK-04"]["Rule"]
        for text in ("`environment: prod`", "`options` include `prod`", "a matrix with more than one value",
                     "chained with `needs`", "GRAPH-04 owns that key"):
            self.assertIn(text, rule)
        self.assertNotIn("fail-fast: false", self.rollback["ROLLBACK-04"]["Fix"])

    def test_rollback_04_offers_chained_jobs_and_no_matrix_for_several_prod_targets(self):
        fields = self.rollback["ROLLBACK-04"]
        for text in ("A matrix over several prod targets is a finding, also with `max-parallel: 1`",
                     "one running and one pending job", "a third leg replaces the pending one and is dropped"):
            self.assertIn(text, fields["Rule"])
        self.assertIn("they are a matrix", fields["Check"])
        self.assertIn("its own rollback job, with no matrix", fields["Fix"])
        self.assertIn("chain the jobs with `needs`", fields["Fix"])
        self.assertNotIn("max-parallel: 1", fields["Fix"])
        self.assertIn("`deploy-<env>`", self.rollback["ROLLBACK-06"]["Rule"])
        self.assertIn("`cancel-in-progress: false`", self.rollback["ROLLBACK-06"]["Rule"])

    def test_rollback_05_has_exactly_three_finding_forms_and_passes_an_unset_cloudformation_rollback(self):
        rule = self.rollback["ROLLBACK-05"]["Rule"]
        for text in ("these three forms, and nothing else is a finding", "`--disable-rollback` or `--no-rollback`",
                     "a step with no flag passes", "circuit breaker rollback off", "`--auto-rollback-configuration`",
                     "a Lambda alias or an S3 bucket) gets no finding"):
            self.assertIn(text, rule)

    def test_rollback_06_uses_the_deploy_group_with_no_cancel_and_leaves_its_form_to_cost_02(self):
        rule = self.rollback["ROLLBACK-06"]["Rule"]
        for text in ("`deploy-<env>`", "`deploy-${{ inputs.environment }}`", "`cancel-in-progress: false`",
                     "COST-02 owns the deploy group form"):
            self.assertIn(text, rule)
        self.assertIn("job-level `concurrency.group`", self.rollback["ROLLBACK-06"]["Check"])

    def test_the_rule_text_quotes_no_write_api_call(self):
        text = read(self.path)
        self.assertNotIn("gh api", text)
        self.assertIsNone(re.search(r"-X (POST|PUT|PATCH|DELETE)", text))


def names_no_url_and_no_repo_link(test, text):
    """The rule text is generic: no URL and no link to a repository (the sample repos stay private)."""
    test.assertNotRegex(text, r"https?://")
    test.assertNotIn("github.com", text)


class ReleaseRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = rule_files()["release"]
        cls.entries = rule_entries(cls.path)
        cls.release = dict(cls.entries)

    def test_the_release_file_holds_release_01_to_release_06_in_order(self):
        self.assertEqual([rule_id for rule_id, _ in self.entries], RELEASE_IDS)

    def test_the_severity_levels_follow_the_ticket_table(self):
        self.assertEqual({rule_id: level(fields) for rule_id, fields in self.release.items()},
                         {rule_id: "required" for rule_id in RELEASE_IDS})
        self.assertIn("suggestion (an app)", self.release["RELEASE-06"]["Severity"])

    def test_the_file_says_that_no_rule_in_it_is_critical(self):
        self.assertIn("No release rule is critical", read(self.path))

    def test_every_check_starts_with_mechanical(self):
        for rule_id, fields in self.release.items():
            self.assertTrue(fields["Check"].startswith("mechanical"), rule_id)

    def test_every_fix_is_one_sentence(self):
        for rule_id, fields in self.release.items():
            self.assertEqual(len(re.findall(r"[.!?](?:\s|$)", fields["Fix"])), 1, rule_id)

    def test_release_01_wants_exactly_one_tool_and_adds_changesets_when_none(self):
        fields = self.release["RELEASE-01"]
        for text in ("The skill keeps the existing tool", "Two or more values are a finding", "An empty value (status `default`)",
                     "create mode adds Changesets"):
            self.assertIn(text, fields["Rule"])
        self.assertIn("exactly one value", fields["Check"])

    def test_release_02_wants_annotated_tags_on_a_commit_on_main(self):
        rule = self.release["RELEASE-02"]["Rule"]
        for text in ("`-a`, `-s` or `-m`", "`git merge-base --is-ancestor <sha> origin/main`", "A job with a `workflow_dispatch` trigger needs that ancestor step",
                     "only a job that runs for a push to main alone passes without it", "A tag that a release tool action makes is not read"):
            self.assertIn(text, rule)

    def test_release_03_reads_the_rulesets_fact_and_checks_only_that_an_active_tag_ruleset_exists(self):
        rule = self.release["RELEASE-03"]["Rule"]
        for text in ("restricted creation, no update and no delete", "`target: tag` and `enforcement: active`",
                     "With any other status there is no finding", "Only the existence of an active tag ruleset is checked",
                     "The PROTECT rules give the content of the ruleset"):
            self.assertIn(text, rule)

    def test_release_04_defines_the_release_actor_and_the_token_rules(self):
        rule = self.release["RELEASE-04"]["Rule"]
        for text in ("never a personal access token (PAT)", "`app-id`, `client-id` and `private-key`",
                     "an App token with no `environment` on the job is a finding", "`push: tags` trigger",
                     "start no new workflow run", "The release actor is the identity that creates the tag",
                     "`github-actions[bot]`"):
            self.assertIn(text, rule)

    def test_release_05_allows_only_a_push_to_main_and_a_dispatch(self):
        rule = self.release["RELEASE-05"]["Rule"]
        for text in ("only `push` to main and `workflow_dispatch`", "A `pull_request` trigger is a finding",
                     "A tag push trigger (`push: tags:`) in the release workflow is a finding too",
                     "`schedule`, `workflow_run`, `release`, `workflow_call`"):
            self.assertIn(text, rule)

    def test_release_06_has_two_severities_and_a_verdict_for_each_tool(self):
        rule = self.release["RELEASE-06"]["Rule"]
        for text in ("`required` when any `package_kind` entry is published", "`softprops/action-gh-release`",
                     "A repo with semantic-release has notes", "release-it) is not read and gives no finding"):
            self.assertIn(text, rule)

    def test_the_text_holds_no_url_and_no_write_api_call(self):
        text = read(self.path)
        names_no_url_and_no_repo_link(self, text)
        self.assertNotIn("gh api", text)
        self.assertIsNone(re.search(r"-X (POST|PUT|PATCH|DELETE)", text))


class PublishRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = rule_files()["publish"]
        cls.entries = rule_entries(cls.path)
        cls.publish = dict(cls.entries)

    def test_the_publish_file_holds_publish_01_to_publish_05_in_order(self):
        self.assertEqual([rule_id for rule_id, _ in self.entries], PUBLISH_IDS)

    def test_the_severity_levels_follow_the_ticket_table(self):
        expected = {"PUBLISH-01": "required", "PUBLISH-02": "required", "PUBLISH-03": "required",
                    "PUBLISH-04": "suggestion", "PUBLISH-05": "suggestion"}
        self.assertEqual({rule_id: level(fields) for rule_id, fields in self.publish.items()}, expected)

    def test_the_file_says_that_no_rule_in_it_is_critical(self):
        self.assertIn("No publish rule is critical", read(self.path))

    def test_every_check_starts_with_its_kind(self):
        for rule_id, fields in self.publish.items():
            kind = "judgement" if rule_id == "PUBLISH-04" else "mechanical"
            self.assertTrue(fields["Check"].startswith(kind), rule_id)

    def test_every_fix_is_one_sentence(self):
        for rule_id, fields in self.publish.items():
            self.assertEqual(len(re.findall(r"[.!?](?:\s|$)", fields["Fix"])), 1, rule_id)

    def test_publish_01_holds_the_trusted_publishing_versions_and_names_the_registry_url_conflict(self):
        rule = self.publish["PUBLISH-01"]["Rule"]
        for text in ("`permissions: id-token: write`", "GitHub-hosted runner", "Node 22.14.0 or later", "npm 11.5.1 or later",
                     "`NPM_TOKEN`", "A version below 22.14.0 is a finding", "A major `24` or later, and an exact version `24.5.0` or later, pass both checks",
                     "`lts/*`, a `node-version-file`", "The sources conflict on `registry-url`",
                     "the semantic-release recipe says not to set it", "The rule takes no side",
                     "does not affect Changesets"):
            self.assertIn(text, rule)

    def test_publish_01_treats_an_exact_node_24_below_24_5_0_as_an_npm_finding(self):
        rule = self.publish["PUBLISH-01"]["Rule"]
        for text in ("24.5.0 is the first Node 24 release that bundles npm 11.5.1",
                     "an exact version from `24.0.0` up to, but not including, `24.5.0`, pass the Node check, "
                     "and it is a finding for the npm check unless a step"):
            self.assertIn(text, rule)

    def test_publish_02_wants_a_frozen_install_and_no_cache(self):
        rule = self.publish["PUBLISH-02"]["Rule"]
        for text in ("`pnpm install --frozen-lockfile`", "`package-manager-cache: false`", "`actions/cache`", "COST-05 owns the CI install"):
            self.assertIn(text, rule)

    def test_publish_03_names_the_tool_forms_of_the_dependency_order(self):
        rule = self.publish["PUBLISH-03"]["Rule"]
        for text in ("`changeset publish`", "`pnpm -r publish`", "`npm publish --workspaces` is a finding", "at least two `package_kind` entries"):
            self.assertIn(text, rule)

    def test_publish_04_skips_a_published_version(self):
        rule = self.publish["PUBLISH-04"]["Rule"]
        for text in ("`npm view <name>@<version>`", "A plain `npm publish` with no check is a finding"):
            self.assertIn(text, rule)

    def test_publish_05_names_release_yml_marks_the_row_with_the_flag_and_never_renames(self):
        fields = self.publish["PUBLISH-05"]
        for text in ("names `release.yml` exactly", "its row gets the ⚑ mark", "The skill never renames the file"):
            self.assertIn(text, fields["Rule"])
        self.assertIn("trusted-publisher entry of each package on npm to `release.yml`", fields["Fix"])

    def test_provenance_is_not_a_rule_and_the_text_holds_no_url(self):
        text = read(self.path)
        self.assertIn("Provenance is not a rule", text)
        names_no_url_and_no_repo_link(self, text)


class ProtectRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = rule_files()["protect"]
        cls.text = read(cls.path)
        cls.entries = rule_entries(cls.path)
        cls.protect = dict(cls.entries)

    def test_the_protect_file_holds_protect_01_to_protect_08_in_order(self):
        self.assertEqual([rule_id for rule_id, _ in self.entries], PROTECT_IDS)

    def test_the_severities_and_the_check_kinds_follow_the_ticket_table(self):
        self.assertEqual({rule_id: level(fields) for rule_id, fields in self.protect.items()},
                         {**{f"PROTECT-0{n}": "required" for n in range(1, 6)},
                          "PROTECT-06": "suggestion", "PROTECT-07": "suggestion", "PROTECT-08": "suggestion"})
        for rule_id, fields in self.protect.items():
            kind = "judgement" if rule_id == "PROTECT-08" else "mechanical"
            self.assertTrue(fields["Check"].startswith(kind), rule_id)

    def test_the_file_says_that_no_rule_in_it_is_critical(self):
        self.assertIn("No protect rule is critical", self.text)

    def test_every_fix_is_one_sentence(self):
        for rule_id, fields in self.protect.items():
            self.assertEqual(len(re.findall(r"[.!?](?:\s|$)", fields["Fix"])), 1, rule_id)

    def test_the_four_verified_facts_name_their_doc_pages(self):
        section = self.text[self.text.index("## Verified GitHub facts"):self.text.index("## Definitions")]
        for text in ("Ruleset `PUT`: replace or merge", "Not stated", "\"Update a repository ruleset\"",
                     "An array of rules within the ruleset", "whole ruleset object",
                     "Classic PAT scopes for rulesets and branch protection", "\"Update branch protection\"",
                     "requires admin or owner permissions to the repository", "\"Scopes for OAuth apps\"",
                     "treat a 403 or a 404 on the first `GET` as no admin scope",
                     "\"Create or update an environment\"", "`can_admins_bypass`",
                     "The REST API cannot clear the admin bypass", "PROTECT-05 is a manual ⚑ step",
                     "Environment `PUT`: replace or merge", "sends the whole object"):
            self.assertIn(text, section)

    def test_the_file_holds_no_runnable_write_call_and_no_url_but_doc_paths(self):
        for banned in ("gh api", "curl", "--method", "-X PUT", "-X POST", "http://", "https://"):
            self.assertNotIn(banned, self.text)

    def test_the_definitions_hold_the_reads_the_status_rule_and_the_marks(self):
        section = self.text[self.text.index("## Definitions"):self.text.index("### PROTECT-01")]
        for text in ("the 2-step flow", "A ⚑ mark means a manual admin step", "and nothing else",
                     "only by PROTECT-03", "raises no finding of a rule when the finding condition of that rule uses the fact",
                     "A fact that only the Fix uses never suppresses a finding",
                     "`classic_protection` in PROTECT-01 and `release_tag_pattern` in PROTECT-02",
                     "PROTECT-04 also accepts the `plan` fact with the status `default`",
                     "Its other fact, `environments`, must still be `detected`",
                     "The facts do not hold the rule content of a ruleset, the bypass actors of a ruleset"):
            self.assertIn(text, section)

    def test_protect_01_writes_the_main_ruleset_and_carries_the_classic_settings(self):
        rule = self.protect["PROTECT-01"]["Rule"]
        for text in ("`target: branch` and `enforcement: active`", "does not hold `CI passed` as its only name",
                     "an empty list is a finding too", "Content: a PR is required", "force pushes and deletions are blocked",
                     "the bypass list is empty", "`enforce_admins` is true",
                     "deleting the classic rule is a ⚑ step on the same row"):
            self.assertIn(text, rule)

    def test_protect_02_needs_only_an_active_tag_ruleset(self):
        rule = self.protect["PROTECT-02"]["Rule"]
        for text in ("`target: tag` and `enforcement: active`", "The rule has no other condition",
                     "a tag ruleset for another pattern passes", "a `default` value such as `v*` is usable",
                     "RELEASE-04 defines it", "the reason \"the PROTECT-02 row writes the ruleset\""):
            self.assertIn(text, rule)

    def test_protect_03_defines_a_tag_run_and_an_expression_environment_and_the_replacement_step(self):
        rule = self.protect["PROTECT-03"]["Rule"]
        for text in ("`github.ref_type == 'tag'`", "`startsWith(github.ref, 'refs/tags/')`",
                     "whatever the workflow triggers are (a `needs` link decides nothing)",
                     "stands for each value in the `options` of that input",
                     "is not checked and raises no finding", "`branch_policy` is `none`",
                     "a protected-branch policy does not accept tags", "A `custom` policy passes",
                     "prod accepts only the final-tag pattern, and every other environment accepts only `main`",
                     "GitHub cannot rename an environment", "deleting the old environment after the first deploy is a ⚑ manual step",
                     "its secrets do not move"):
            self.assertIn(text, rule)

    def test_protect_04_needs_the_plan_and_names_the_default_plan_and_the_no_reviewers_plan(self):
        rule = self.protect["PROTECT-04"]["Rule"]
        for text in ("`reviewers: false`, and `plan.reviewers_available` is true", "the merged PR is the approval",
                     "may need GitHub Enterprise", "`prevent_self_review: true`", "no `prevent_self_review` value"):
            self.assertIn(text, rule)

    def test_protect_05_is_a_manual_step_and_names_the_ruleset_bypass_limit(self):
        rule = self.protect["PROTECT-05"]["Rule"]
        for text in ("`admin_bypass: true`", "no field for the admin bypass", "manual ⚑ step with no 🔒",
                     "not checked on an existing ruleset", "The facts do not hold the bypass actors of a ruleset"):
            self.assertIn(text, rule)

    def test_protect_06_yields_to_protect_01_so_one_repo_gets_one_classic_deletion(self):
        rule = self.protect["PROTECT-06"]["Rule"]
        for text in ("both apply and stack", "PROTECT-01 raises no row", "PROTECT-06 raises none"):
            self.assertIn(text, rule)

    def test_protect_07_reads_one_comment_line_for_the_listed_phrases(self):
        rule = self.protect["PROTECT-07"]["Rule"]
        for text in ("one comment line", "`branch protection`, `protected branch`, `ruleset`, `tag protection`, "
                     "`protected tag`, `required reviewer`, `required review`", "case does not matter",
                     "need an active branch ruleset or `classic_protection.protected: true`",
                     "the environment whose name the same comment line holds as a word, or on `prod`",
                     "every fact that could show it is `detected`", "A comment that holds none of these phrases is not read"):
            self.assertIn(text, rule)
        self.assertIn("(a file edit, no mark)", self.protect["PROTECT-07"]["Fix"])

    def test_protect_07_checks_a_ruleset_comment_with_the_word_tag_against_a_tag_ruleset(self):
        rule = self.protect["PROTECT-07"]["Rule"]
        self.assertIn("a line that holds `ruleset` and the word `tag` needs an active tag ruleset", rule)
        self.assertIn("`ruleset` without the word `tag`, both `rulesets` and `classic_protection`", rule)

    def test_protect_08_is_a_judgement_on_repo_wide_role_arns_and_app_keys(self):
        rule = self.protect["PROTECT-08"]["Rule"]
        for text in ("names no `environment`", "`AWS_ROLE` or `ROLE_ARN`", "`APP_PRIVATE_KEY` or `APP_ID`",
                     "so that case is not a finding", "The skill writes no secret or variable"):
            self.assertIn(text, rule)

    def test_the_marks_of_each_fix_follow_the_design(self):
        for rule_id, mark in (("PROTECT-01", "marks ⚑ 🔒"), ("PROTECT-02", "mark 🔒"), ("PROTECT-03", "mark 🔒, and ⚑"),
                              ("PROTECT-04", "mark 🔒"), ("PROTECT-05", "mark ⚑"), ("PROTECT-06", "mark ⚑"),
                              ("PROTECT-08", "mark ⚑")):
            self.assertIn(mark, self.protect[rule_id]["Fix"], rule_id)
        self.assertNotIn("🔒", self.protect["PROTECT-07"]["Fix"])


class SecurityRules(unittest.TestCase):
    def setUp(self):
        self.sec = dict(rule_entries(rule_files()["security"]))

    def test_the_security_file_holds_sec_01_to_sec_10_in_order(self):
        self.assertEqual(list(self.sec), SEC_IDS)

    def test_the_severity_levels_follow_the_spec_table(self):
        for rule_id, fields in self.sec.items():
            expected = "critical" if rule_id in ("SEC-04", "SEC-06", "SEC-07") else "required"
            self.assertEqual(level(fields), expected, rule_id)

    def test_sec_04_has_a_critical_part_for_untrusted_contexts_and_a_required_part(self):
        fields = self.sec["SEC-04"]
        self.assertRegex(fields["Severity"], r"critical \(.*untrusted.*\), required \(.*matrix")
        text = " ".join(fields.values())
        for context in ("github.event.*", "github.head_ref", "inputs.*", "secrets.*", "matrix.*"):
            self.assertIn(context, text)

    def test_sec_06_is_critical_as_a_whole(self):
        self.assertEqual(self.sec["SEC-06"]["Severity"].strip(), "critical")

    def test_sec_07_is_critical_for_a_pr_head_checkout_and_required_for_the_plain_use(self):
        fields = self.sec["SEC-07"]
        self.assertRegex(fields["Severity"], r"critical \(.*PR head.*\), required \(.*plain use")
        text = " ".join(fields.values())
        for context in ("github.event.pull_request.head.sha", "github.event.workflow_run.head_sha"):
            self.assertIn(context, text)

    def test_the_rule_text_holds_its_key_phrases(self):
        phrases = {
            "SEC-01": ["40-character commit SHA"], "SEC-02": [".github/dependabot.yml", "github-actions"],
            "SEC-03": ["contents: read"], "SEC-04": ["${{ ... }}", "env:"],
            "SEC-05": ["persist-credentials: false"],
            "SEC-06": ["submodules: recursive", "actions/create-github-app-token"],
            "SEC-07": ["pull_request_target", "workflow_run"], "SEC-08": ["secrets: inherit"],
            "SEC-09": ["privileged trigger"], "SEC-10": ["--audit-level=high", "security-audit.yml"],
        }
        for rule_id, wanted in phrases.items():
            for phrase in wanted:
                self.assertIn(phrase, self.sec[rule_id]["Rule"], rule_id)

    def test_sec_10_fix_gives_a_cron_with_an_odd_minute_that_a_user_can_paste(self):
        fix = self.sec["SEC-10"]["Fix"]
        cron = re.search(r"cron: '(\d+) \d+ \* \* \d'", fix)
        self.assertIsNotNone(cron, fix)
        self.assertEqual(int(cron.group(1)) % 2, 1)

    def test_sec_10_fix_names_the_gate_edit_that_accepts_a_skipped_audit_only(self):
        fix = self.sec["SEC-10"]["Fix"]
        check = ("echo \"$RESULTS\" | jq -e 'all(to_entries[]; .value.result == \"success\" or "
                 "(.key == \"audit\" and .value.result == \"skipped\"))'")
        self.assertIn(check, fix)
        self.assertIn("RESULTS: ${{ toJSON(needs) }}", read(os.path.join(SKILL, "templates", "single-package.yml")))
        self.assertIn("only `audit` may be `skipped`", fix)
        self.assertIn("every other job must be `success`", fix)
        self.assertIn("COST-03", fix)
        self.assertIn('.key == "<job id>"', fix)
        self.assertIn("never a general skip", fix)

    @unittest.skipUnless(shutil.which("jq"), "jq is not installed")
    def test_sec_10_gate_check_passes_a_skipped_audit_and_fails_any_other_skip(self):
        fix = self.sec["SEC-10"]["Fix"]
        expr = re.search(r"jq -e '([^']+)'", fix).group(1)

        def gate(results):
            return subprocess.run(["jq", "-e", expr], input=json.dumps(results), text=True,
                                  capture_output=True).returncode

        self.assertEqual(gate({"lint": {"result": "success"}, "audit": {"result": "skipped"}}), 0)
        self.assertEqual(gate({"lint": {"result": "success"}, "audit": {"result": "success"}}), 0)
        self.assertNotEqual(gate({"lint": {"result": "skipped"}, "audit": {"result": "success"}}), 0)
        self.assertNotEqual(gate({"lint": {"result": "success"}, "audit": {"result": "failure"}}), 0)

    def test_sec_10_flags_a_gate_that_fails_a_skipped_audit_and_not_one_that_accepts_it(self):
        rule = self.sec["SEC-10"]["Rule"]
        self.assertIn("A gate check that fails when `audit` is `skipped` is also a finding.", rule)
        self.assertIn("A gate check that already accepts a skipped `audit` is no finding", rule)
        self.assertIn("when the gate check fails a skipped `audit`, change it to", self.sec["SEC-10"]["Fix"])

    def test_every_rule_line_of_a_pinned_action_equals_the_create_template_line(self):
        pinned = {}
        for name in ("single-package.yml", "monorepo.yml", "deploy.yml", "release.yml", "rollback.yml"):
            template = read(os.path.join(SKILL, "templates", name))
            for match in re.finditer(r"uses: ([\w.-]+/[\w.-]+)@[0-9a-f]{40} # \S+", template):
                self.assertEqual(pinned.setdefault(match.group(1), match.group(0)), match.group(0), name)
        line = pinned["dorny/paths-filter"]
        for name, path in rule_files().items():
            for match in re.finditer(r"uses: ([\w.-]+/[\w.-]+)@[^\s`]+(?: # [^\s`]+)?", read(path)):
                if match.group(1) in pinned:
                    self.assertEqual(match.group(0), pinned[match.group(1)], f"rules/{name}.md")
        cost = dict(rule_entries(rule_files()["cost"]))
        for rule_id, fix in (("COST-03", cost["COST-03"]["Fix"]), ("SEC-10", self.sec["SEC-10"]["Fix"])):
            self.assertEqual(re.findall(r"`(uses: dorny/paths-filter@[^`]+)`", fix), [line], rule_id)
            self.assertNotIn("pinned to a full commit SHA", fix, rule_id)
            self.assertIn("never a SHA that you wrote yourself", fix, rule_id)

    def test_sec_10_fix_adds_a_changes_job_and_removes_the_old_audit_step(self):
        fix = self.sec["SEC-10"]["Fix"]
        self.assertIn("`changes` job", fix)
        self.assertIn("`lockfile` output", fix)
        self.assertIn("when the workflow has none", fix)
        self.assertIn("remove the old audit step from the other job", fix)

    def test_every_check_is_mechanical(self):
        for rule_id, fields in self.sec.items():
            self.assertTrue(fields["Check"].startswith("mechanical"), rule_id)

    def test_every_fix_is_one_sentence(self):
        for rule_id, fields in self.sec.items():
            self.assertEqual(len(re.findall(r"[.!?](?:\s|$)", fields["Fix"])), 1, rule_id)

    def test_sec_01_fix_points_to_the_sha_lookup_in_tools_md(self):
        self.assertIn("tools.md", self.sec["SEC-01"]["Fix"])

    def test_sec_01_checks_the_form_and_the_commit_of_the_pin_with_the_pin_check(self):
        rule = self.sec["SEC-01"]["Rule"]
        self.assertIn("The check has two parts", rule)
        for result in ("tag-mismatch", "unknown-tag", "unknown-commit"):
            self.assertIn(f"`{result}`", rule)
        self.assertIn("`unverified` is never a finding", rule)
        self.assertNotIn("Do not judge whether the SHA is a real commit", rule)

    def test_tools_md_and_review_md_wire_the_pin_check(self):
        tools = read(os.path.join(SKILL, "tools.md"))
        section = tools[tools.index("## Check the pins"):tools.index("## Offline Node support list")]
        self.assertIn("python3 <skill folder>/scripts/check_pins.py <repo path>", section)
        self.assertIn("SEC-01 pins not verified (<reason>)", section)
        review = read(os.path.join(SKILL, "review.md"))
        self.assertIn('"Check the pins"', review)
        self.assertIn("SEC-01 pins not verified (<reason>)", review)

    def test_the_file_says_which_rules_have_critical_parts(self):
        text = read(rule_files()["security"])
        self.assertIn("SEC-04, SEC-06 and SEC-07", text)


class ToolsModule(unittest.TestCase):
    def setUp(self):
        self.text = read(os.path.join(SKILL, "tools.md"))

    def section(self, name):
        start = self.text.index(f"## {name}")
        end = self.text.find("\n## ", start + 1)
        return self.text[start:end if end != -1 else len(self.text)]

    def test_it_has_the_seven_sections_in_order(self):
        headings = re.findall(r"^## (.+)$", self.text, re.M)
        self.assertEqual(headings, TOOLS_SECTIONS)

    def test_detection_uses_the_intake_fact_only(self):
        section = self.section("Detection")
        self.assertIn("installed_tools", section)
        self.assertIn("installed: true", section)

    def test_the_install_hints_name_the_three_tools(self):
        section = self.section("Install hints")
        for hint in ("brew install actionlint", "uvx zizmor", "brew install zizmor", "brew install pinact"):
            self.assertIn(hint, section)
        self.assertIn("Install it with", section)

    def test_the_run_commands_use_the_default_persona(self):
        section = self.section("Running the tools")
        self.assertIn("actionlint -format", section)
        self.assertIn("zizmor --format=json-v1", section)
        self.assertIn("no `--persona` flag", section)

    def test_the_mapping_table_has_exactly_the_seven_audits_and_every_sec_id_exists(self):
        section = self.section("zizmor to SEC mapping")
        rows = re.findall(r"^\| `([a-z-]+)` \| (SEC-\d\d)", section, re.M)
        self.assertEqual(dict(rows), ZIZMOR_MAPPING)
        self.assertEqual(len(rows), 7)
        known = {rule_id for _, rule_id, _ in all_rules()}
        for audit, sec_id in rows:
            self.assertIn(sec_id, known, audit)

    def test_the_mapping_table_has_the_header_of_the_decision(self):
        self.assertIn("| zizmor audit | SEC rule |", self.section("zizmor to SEC mapping"))

    def test_the_merge_text_gives_one_row_with_the_sec_severity(self):
        section = self.section("Merging the output")
        for phrase in ("row + 1", "never write the audit id", "suggestion", "once", "`actionlint-<kind>`",
                       "whatever zizmor says about its own severity"):
            self.assertIn(phrase, section)

    def test_the_pin_section_names_pinact_and_the_annotated_tag_dereference(self):
        section = self.section("Pin a SHA")
        for phrase in ("pinact run", "git/ref/tags", "git/tags/<sha>", "annotated"):
            self.assertIn(phrase, section)

    def test_the_offline_block_parses_with_the_three_fields(self):
        block = re.search(r"```json\n(.*?)\n```", self.section("Offline Node support list"), re.S).group(1)
        data = json.loads(block)
        self.assertEqual(sorted(data), ["date", "majors", "newest_lts"])
        self.assertIn(data["newest_lts"], data["majors"])


class Router(unittest.TestCase):
    def setUp(self):
        self.text = read(os.path.join(SKILL, "SKILL.md"))
        self.meta = frontmatter(os.path.join(SKILL, "SKILL.md"))

    def test_the_name_is_cicd_pipelines(self):
        self.assertEqual(self.meta["name"], "cicd-pipelines")

    def test_the_description_leads_with_the_skill_name_and_stays_short(self):
        description = self.meta["description"]
        self.assertTrue(description.startswith("cicd-pipelines"), description)
        self.assertLessEqual(len(description), 400)

    def test_the_description_triggers_on_workflow_files_and_names_both_branches(self):
        description = self.meta["description"].lower()
        self.assertIn(".github/workflows", description)
        self.assertIn("create", description)
        self.assertIn("review", description)

    def test_the_description_names_the_other_ci_files_and_the_general_advice(self):
        description = self.meta["description"]
        for text in (".gitlab-ci.yml", "Jenkinsfile", "general advice for other stacks"):
            self.assertIn(text, description)

    def test_the_description_names_the_cd_kinds_and_the_protection_requests(self):
        description = self.meta["description"].lower()
        for word in ("deploy", "release", "rollback", "npm publish", "branch protection", "rulesets", "environments"):
            self.assertIn(word, description)

    def test_the_router_links_every_module_that_exists(self):
        for module in module_files():
            self.assertIn(module, self.text, f"SKILL.md does not point to {module}")

    def test_the_modules_list_names_the_cd_templates_and_the_template_scripts_folder(self):
        modules = self.text[self.text.index("## Modules"):]
        for name in ("templates/deploy.yml", "templates/release.yml", "templates/rollback.yml"):
            self.assertIn(f"[{name}]({name})", modules)
        self.assertIn("templates/scripts/", modules)
        for script in sorted(os.listdir(os.path.join(SKILL, "templates", "scripts"))):
            self.assertIn(script, modules)

    def test_the_create_branch_points_to_the_create_steps_and_is_not_marked_as_unbuilt(self):
        self.assertTrue(os.path.exists(os.path.join(SKILL, "create.md")))
        self.assertNotIn("not built", self.text)
        create = next(line for line in self.text.splitlines() if line.startswith("- **Create**"))
        self.assertIn("[create.md](create.md)", create)

    def test_the_modules_list_names_the_create_steps_the_templates_and_the_new_scripts(self):
        modules = self.text[self.text.index("## Modules"):]
        for name in ("create.md", "templates/single-package.yml", "templates/monorepo.yml",
                     "scripts/check_workflow.py", "scripts/grade_create_results.py"):
            self.assertIn(f"[{name}]({name})", modules)

    def test_the_router_runs_the_intake_script_before_it_picks_the_branch(self):
        self.assertIn("scripts/intake.py", self.text)
        self.assertIn("## Intake", self.text)
        self.assertIn("## Pick the branch", self.text)
        self.assertLess(self.text.index("## Intake"), self.text.index("## Pick the branch"))
        intake = self.text[self.text.index("## Intake"):self.text.index("## Pick the branch")]
        self.assertIn("before you pick a branch", intake.lower())
        self.assertIn("tools.md", intake)
        self.assertNotIn("node-support-offline", self.text)

    def test_the_router_runs_the_intake_as_one_plain_command_with_the_full_script_path(self):
        intake = self.text[self.text.index("## Intake"):self.text.index("## Pick the branch")]
        self.assertIn("python3 <skill folder>/scripts/intake.py <repo path>", intake)
        for word in ("`cd`", "`;`", "`&&`"):
            self.assertIn(word, intake)
        self.assertIn("one plain command", intake)

    def test_the_router_says_to_read_the_whole_branch_file_and_not_a_part_of_it(self):
        branches = self.text[self.text.index("## Pick the branch"):self.text.index("## Modules")]
        self.assertIn("Read the whole branch file with the Read tool", branches)
        self.assertIn("never only a part of it with a search", branches)

    def test_the_router_points_to_the_tools_module_and_the_security_rules(self):
        modules = self.text[self.text.index("## Modules"):]
        self.assertIn("[tools.md](tools.md)", modules)
        self.assertIn("offline list", modules)
        self.assertIn("SEC-01 to SEC-10", modules)
        self.assertIn("[rules/security.md](rules/security.md)", modules)

    def test_the_intake_script_bullet_says_it_reads_the_offline_node_list_from_the_tools_module(self):
        modules = self.text[self.text.index("## Modules"):]
        bullet = next(line for line in modules.splitlines() if "scripts/intake.py" in line)
        self.assertIn("reads the dated offline Node list from [tools.md](tools.md)", bullet)

    def test_the_naming_rule_09_reads_the_intake_fact_not_gh_calls(self):
        fields = dict(rule_entries(rule_files()["naming"]))["NAME-09"]
        self.assertIn("required_checks", fields["Check"])
        self.assertNotIn("gh api", " ".join(fields.values()))

    def test_every_naming_rule_09_row_carries_the_flag_mark_with_the_fix_in_the_flag_section(self):
        fields = dict(rule_entries(rule_files()["naming"]))["NAME-09"]
        self.assertIn("Mark every NAME-09 row ⚑", fields["Rule"])
        self.assertIn("After the merge, an admin changes the required checks as the ⚑ section shows.",
                      fields["Fix"])
        self.assertNotIn("before merging", fields["Fix"].lower())

    def test_another_edit_points_to_every_rule_file(self):
        bullet = self.text[self.text.index("**Another edit**"):self.text.index("## Modules")]
        for rule_file in ("rules/naming.md", "rules/job-graph.md", "rules/cost.md", "rules/security.md",
                          "rules/maintainability.md"):
            self.assertIn(rule_file, bullet)
        self.assertIn("rules/monorepo.md", bullet)
        self.assertIn("when the intake finds a monorepo", bullet)
        self.assertIn("rules/deploy.md", bullet)
        self.assertIn("rules/rollback.md", bullet)
        self.assertIn("when the repo has a deploy workflow", bullet)
        self.assertIn("[rules/protect.md](rules/protect.md)", bullet)
        self.assertIn("under their own load rules", bullet)

    def test_the_modules_list_names_the_protect_file_with_its_load_rule(self):
        modules = self.text[self.text.index("## Modules"):]
        self.assertIn("- [rules/protect.md](rules/protect.md): PROTECT-01 to PROTECT-08", modules)
        self.assertIn("Load it by the PROTECT rule of \"Loading by need\"", modules)
        section = self.text[self.text.index("## Loading by need"):self.text.index("## Modules")]
        self.assertIn("- `PROTECT` ([rules/protect.md](rules/protect.md)):", section)

    def test_loading_by_need_gives_the_load_rule_of_each_cd_family_before_the_modules_list(self):
        start = self.text.index("## Loading by need")
        section = self.text[start:self.text.index("## Modules")]
        self.assertGreater(start, self.text.index("## Pick the branch"))
        self.assertIn("load always", section)
        self.assertIn("only for a monorepo", section)
        for family, rule_file in (("DEPLOY", "rules/deploy.md"), ("ROLLBACK", "rules/rollback.md"),
                                  ("RELEASE", "rules/release.md"), ("PUBLISH", "rules/publish.md"),
                                  ("PROTECT", "rules/protect.md")):
            self.assertIn(f"`{family}`", section)
            self.assertIn(rule_file, section)
        for text in ("the request names a deploy or a rollback", "the repo has a deploy workflow",
                     "the request names a release", "a published package",
                     "with any CD rule file", "branch protection, rulesets or environments"):
            self.assertIn(text, section)
        self.assertNotIn("does not exist yet", self.text)

    def test_the_modules_list_names_the_deploy_rules_and_their_load_rule(self):
        modules = self.text[self.text.index("## Modules"):]
        self.assertIn("[rules/deploy.md](rules/deploy.md): DEPLOY-01 to DEPLOY-10", modules)
        self.assertIn("\"Loading by need\"", modules)

    def test_the_loading_section_links_the_rollback_file_and_the_modules_list_names_its_rules(self):
        start = self.text.index("## Loading by need")
        section = self.text[start:self.text.index("## Modules")]
        self.assertIn("[rules/rollback.md](rules/rollback.md)", section)
        modules = self.text[self.text.index("## Modules"):]
        self.assertIn("[rules/rollback.md](rules/rollback.md): ROLLBACK-01 to ROLLBACK-06", modules)

    def test_the_release_load_rule_covers_a_tag_driven_release_and_both_files_are_linked(self):
        start = self.text.index("## Loading by need")
        section = self.text[start:self.text.index("## Modules")]
        for text in ("[rules/release.md](rules/release.md)", "[rules/publish.md](rules/publish.md)",
                     "the `release_tool` fact has a value", "the `existing_workflows` fact lists `release.yml`",
                     "the `release_tag_pattern` fact has the status `detected`"):
            self.assertIn(text, section)
        modules = self.text[self.text.index("## Modules"):]
        self.assertIn("[rules/release.md](rules/release.md): RELEASE-01 to RELEASE-06", modules)
        self.assertIn("[rules/publish.md](rules/publish.md): PUBLISH-01 to PUBLISH-05", modules)
        bullet = self.text[self.text.index("**Another edit**"):start]
        self.assertIn("rules/release.md", bullet)
        self.assertIn("rules/publish.md", bullet)

    def test_the_modules_list_names_the_cost_and_monorepo_rules(self):
        modules = self.text[self.text.index("## Modules"):]
        self.assertIn("COST-01 to COST-08", modules)
        self.assertIn("MONO-01 to MONO-02", modules)
        self.assertIn("only for a monorepo", modules)

    def test_the_router_does_not_link_a_module_that_is_missing(self):
        for target in re.findall(r"\]\(([^)#]+)\)", self.text):
            self.assertTrue(os.path.exists(os.path.join(SKILL, target)), f"SKILL.md links {target}")


class ReviewSteps(unittest.TestCase):
    def setUp(self):
        self.text = read(os.path.join(SKILL, "review.md")).lower()

    def test_it_loads_the_rule_files(self):
        self.assertIn("load the rule files by need", self.text)
        self.assertNotIn("load every rule file", self.text)
        step = self.text[self.text.index("1. load the rule files by need"):self.text.index("2. read the intake json")]
        self.assertIn("load the ci rule files always", step)
        self.assertIn("each cd rule file that exists in `rules/` only when its load rule", step)
        self.assertIn("\"loading by need\" in [skill.md](skill.md)", step)

    def test_it_writes_the_report_as_the_final_message(self):
        self.assertIn("final message", self.text)

    def test_it_puts_the_version_of_a_tool_on_path_in_its_bullet(self):
        self.assertIn("on path (", self.text)

    def test_the_tool_bullet_follows_the_intake_fact_even_when_a_run_of_the_tool_fails(self):
        section = self.text[self.text.index("## tool status"):self.text.index("## report contract")]
        self.assertIn("the bullet always follows the `installed_tools` fact", section)
        self.assertIn("even when a run of the tool fails", section)
        self.assertIn("never in the bullet", section)

    def test_the_contract_fixes_the_exact_text_of_the_tool_bullets_and_the_approval_line(self):
        contract = self.text[self.text.index("## report contract"):self.text.index("## fix on approval")]
        self.assertIn("a bullet has no other text than one of these two forms", contract)
        self.assertIn("copy this sentence exactly", contract)
        self.assertIn("never change its examples", contract)

    def test_the_fix_flow_opens_with_the_rule_that_the_final_message_has_the_parts_of_step_10(self):
        opening = self.text[self.text.index("## fix on approval"):self.text.index("1. **read the reply.**")]
        self.assertIn("never end with a prose note", opening)
        self.assertIn("step 10", opening)

    def test_a_failed_actionlint_run_does_not_end_the_fix_flow(self):
        step = self.text[self.text.index("7. **actionlint.**"):self.text.index("8. **diff.**")]
        self.assertIn("a failed run of actionlint", step)
        self.assertIn("does not end the fix flow", step)
        self.assertIn("steps 8 to 10", step)

    def test_the_intake_line_starts_with_the_word_and_the_colon(self):
        contract = self.text[self.text.index("## report contract"):self.text.index("## fix on approval")]
        self.assertIn("starts exactly with `intake:`", contract)

    def test_the_post_fix_report_is_the_whole_contract_and_never_a_prose_summary(self):
        step = self.text[self.text.index("10. **final message.**"):self.text.index("**admin steps.**")]
        self.assertIn("never a prose summary", step)
        self.assertIn("all 8 sections", step)

    def test_the_approval_line_is_the_last_text_of_the_report(self):
        section = self.text[self.text.index("8. `## approve`"):self.text.index("## fix on approval")]
        self.assertIn("write no text after the approval line", section)
        self.assertIn("`tools:`", section)

    def test_it_takes_its_facts_from_the_intake_and_runs_no_gh_or_tool_calls(self):
        for fact in ("required_checks", "installed_tools", "runner_labels"):
            self.assertIn(fact, self.text)
        for gone in ("command -v", "actionlint -version", "zizmor --version", "interim"):
            self.assertNotIn(gone, self.text)

    def test_section_2_names_defaults_and_unknown_facts(self):
        self.assertIn("`default`", self.text)
        self.assertIn("`unknown`", self.text)
        self.assertIn("offline", self.text)

    def test_section_2_gives_two_example_intake_lines_that_the_grader_accepts(self):
        contract = read(os.path.join(SKILL, "review.md"))
        examples = re.findall(r"^\s*- `(Intake: [^`]*)`$", contract, re.MULTILINE)
        self.assertEqual(len(examples), 2)
        with_defaults, no_defaults = examples
        self.assertTrue(with_defaults.endswith(")."))
        self.assertGreater(len(re.findall(r"\w+ \([^)]*\)", with_defaults.split("Defaults:")[1])), 1)
        self.assertTrue(no_defaults.endswith("Defaults: none."))
        self.assertIn("stays on one line, also when it is long", contract)
        base = make_report()
        fixture_line = "Intake: pnpm, single package, private repo (2 vCPU). Defaults: none."
        self.assertIn(fixture_line, base)

        def grade_with(intake_line):
            report = TempReport(base.replace(fixture_line, intake_line))
            self.addCleanup(report.cleanup)
            return run_script("grade_report.py", [report.path])

        for example in examples:
            code, out, _ = grade_with(example)
            self.assertEqual((code, out.strip().splitlines()[-1]), (0, "PASS"), out)
        code, out, _ = grade_with(with_defaults.replace(" Defaults:", "\nDefaults:"))
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL defaults:", out)

    def test_it_keeps_the_name_09_row_and_the_flag_mark(self):
        self.assertIn("name-09 row", self.text)
        self.assertIn("⚑", self.text)

    def test_the_report_contract_gives_every_name_09_row_the_flag_mark(self):
        contract = self.text[self.text.index("## report contract"):]
        self.assertIn("always on a name-09 row", contract)
        checks = self.text[self.text.index("## required checks"):self.text.index("## tool status")]
        self.assertIn("add a name-09 row (suggestion) marked with ⚑", checks)
        self.assertIn("fixed sentence of name-09", checks)

    def test_the_publish_05_row_gets_the_flag_mark_the_npm_admin_step_and_is_never_edited(self):
        contract = self.text[self.text.index("## report contract"):self.text.index("## fix on approval")]
        self.assertIn("a publish-05 row also gets ⚑", contract)
        self.assertIn("for a publish-05 row, this section also holds the npm admin step", contract)
        self.assertIn("6. `## ⚑ admin steps`", contract)
        self.assertNotIn("branch protection change needed", self.text)
        self.assertNotIn("reword it", contract)
        approval = self.text[self.text.index("## fix on approval"):]
        self.assertIn("a publish-05 row is never edited", approval)
        self.assertIn("a skipped ⚑ row gets no admin steps", approval)

    def test_the_rule_cell_has_the_lock_mark_after_the_flag_mark_and_a_name_09_row_may_hold_both(self):
        contract = self.text[self.text.index("## report contract"):self.text.index("## fix on approval")]
        for text in ("a 🔒 follows the id (after the ⚑ when there is one: `⚑ 🔒`)", "the 2-step flow",
                     "a name-09 row also gets 🔒 when the `rulesets` fact is `detected` and holds an active branch ruleset",
                     "a row stays one rule at one severity"):
            self.assertIn(text, contract)
        naming = read(rule_files()["naming"])
        for text in ("Never edit classic branch protection.", "the row also gets 🔒 (Rule cell `NAME-09 ⚑ 🔒`)",
                     "never write them yourself, except a ruleset change that the 2-step flow writes after its own approval",
                     "After the merge, an admin changes the required checks as the ⚑ section shows."):
            self.assertIn(text, naming)

    def test_the_lock_note_comes_after_the_last_table_and_only_with_a_lock_row(self):
        contract = self.text[self.text.index("## report contract"):self.text.index("## fix on approval")]
        for text in ("directly after the last table, write the lock note", "starts `🔒 = a protection write.`",
                     "write the note only when at least one row has 🔒", "it is not a numbered section",
                     "it comes before the ⚑ section and the job graph",
                     "the flow is the protection step of \"fix on approval\""):
            self.assertIn(text, contract)
        self.assertNotIn("skips a 🔒 row", contract)
        self.assertLess(contract.index("write the lock note"), contract.index("6. `## ⚑ admin steps`"))

    def test_the_job_graph_sketch_has_one_line_for_each_trigger_and_the_intake_line_names_the_defaults(self):
        contract = self.text[self.text.index("## report contract"):self.text.index("## fix on approval")]
        for text in ("one line for each trigger", "`push main: deploy ── ...`",
                     "`tag <pattern>: deploy ── deploy-prod (...)`", "`<pattern>` is the `release_tag_pattern` value",
                     "`dispatch: rollback ── ...`", "`push main: release ── ...`",
                     "a repo with no `release.yml` has three lines", "ends with `defaults:`", "`defaults: none.`"):
            self.assertIn(text, contract)

    def test_the_edit_step_leaves_a_lock_row_to_the_protection_step_and_skips_the_manual_rows(self):
        step = self.text[self.text.index("4. **edit.**"):self.text.index("5. **protection writes.**")]
        for text in ("a 🔒 row is not a file edit: leave it for step 5",
                     "a protect-05, protect-06 or protect-08 row", "\"the fix is a manual admin step\"",
                     "a release-03 row is skipped with the reason \"the protect-02 row writes the ruleset\""):
            self.assertIn(text, step)

    def test_the_temporary_skip_of_the_lock_rows_and_its_marker_are_gone(self):
        for gone in ("temporary", "ticket 674", "never edited in this version", "not part of this version"):
            self.assertNotIn(gone, self.text)

    def test_it_loads_the_job_graph_and_maintainability_rule_files(self):
        self.assertIn("rules/job-graph.md", self.text)
        self.assertIn("rules/maintainability.md", self.text)

    def test_the_job_graph_facts_section_names_the_facts_and_the_measured_rule(self):
        start = self.text.index("## job graph facts")
        section = self.text[start:self.text.index("\n## ", start + 1)]
        for fact in ("package_kind", "engines", "os_claims", "node_version_app",
                     "supported_node_majors", "run_history"):
            self.assertIn(fact, section)
        self.assertIn("only a test job has a matrix", section)
        self.assertIn("measured finding is a suggestion", section)
        for banned in ("gh api", "command -v", "interim"):
            self.assertNotIn(banned, section)

    def test_it_loads_the_cost_file_always_and_the_monorepo_file_only_for_a_monorepo(self):
        self.assertIn("rules/cost.md", self.text)
        self.assertIn("rules/monorepo.md", self.text)
        step = self.text[self.text.index("1. load the rule files by need"):self.text.index("2. read the intake json")]
        self.assertIn("only when", step)
        self.assertIn("`monorepo`", step)
        self.assertNotIn("does not exist yet", self.text)

    def test_the_no_lockfile_bullet_no_longer_waits_for_the_cost_rules(self):
        self.assertNotIn("when the cost rules exist", self.text)
        self.assertIn("a cost-05 finding", self.text)

    def test_the_cost_and_monorepo_facts_section_names_the_facts(self):
        start = self.text.index("## cost and monorepo facts")
        section = self.text[start:self.text.index("\n## ", start + 1)]
        for fact in ("run_history", "visibility", "runner_labels", "monorepo", "package_manager"):
            self.assertIn(fact, section)
        self.assertIn("measured finding is a suggestion", section)
        self.assertIn("create values", section)
        for banned in ("gh api", "command -v", "interim"):
            self.assertNotIn(banned, section)

    def test_it_loads_the_security_file_and_names_the_tools_module(self):
        self.assertIn("rules/security.md", self.text)
        self.assertIn("tools.md", self.text)

    def test_step_4_points_to_the_tools_module_for_the_hints(self):
        step = self.text[self.text.index("\n4. take the tool status"):self.text.index("\n5.")]
        self.assertIn("[tools.md](tools.md)", step)

    def test_the_tool_step_runs_the_tools_only_when_on_path_and_merges_the_output(self):
        step = self.text[self.text.index("run the installed tools"):]
        step = step[:step.index("\n7.")]
        self.assertIn("`installed: true`", step)
        self.assertIn("merging the output", step)

    def test_the_security_and_tool_facts_section_names_what_it_reads(self):
        start = self.text.index("## security and tool facts")
        section = self.text[start:self.text.index("\n## ", start + 1)]
        for phrase in (".github/dependabot.yml", "severity of its sec rule part", "suggestion", "no other command"):
            self.assertIn(phrase, section)

    def test_the_tool_status_section_points_to_tools_md_for_the_hints(self):
        start = self.text.index("## tool status")
        section = self.text[start:self.text.index("\n## ", start + 1)]
        self.assertIn("tools.md", section)

    def test_it_makes_no_edit_before_the_user_approves_and_points_to_the_fix_section(self):
        steps = self.text[self.text.index("## steps"):self.text.index("\n## ", self.text.index("## steps") + 1)]
        self.assertIn("make no edit", steps)
        self.assertIn("before the user approves", steps)
        self.assertIn("fix on approval", steps)


class EvalReadme(unittest.TestCase):
    def test_the_documented_run_has_the_spec_flags(self):
        text = read(os.path.join(SKILL, "evals", "README.md"))
        for flag in ("claude plugin eval", "--no-publish", "-j 2", "--runs 3", "--threshold 1.0",
                     "--scaffold", "--ablation with-without"):
            self.assertIn(flag, text)

    def test_it_describes_each_protect_case_and_the_new_report_parts(self):
        text = read(os.path.join(SKILL, "evals", "README.md"))
        for name in ("protect-01-no-main-ruleset", "protect-02-no-tag-ruleset", "protect-03-env-accepts-any-branch",
                     "protect-04-prod-no-reviewers", "protect-05-admin-bypass-on-prod",
                     "protect-06-classic-and-ruleset-stack", "protect-07-claimed-protection-missing",
                     "protect-08-repo-wide-role-arn", "section-lock-note.md", "section-graph-triggers.md",
                     "the required PROTECT ids (01 to 05)"):
            self.assertIn(name, text)

    def test_the_allowed_tools_are_the_intake_call_and_no_gh_api(self):
        text = read(os.path.join(SKILL, "evals", "README.md"))
        self.assertIn('--allow-tools "Bash(python3 *scripts/intake.py*)" '
                      '"Bash(python3 *scripts/check_pins.py*)"', text)
        self.assertNotIn("Bash(gh api", text)

    @staticmethod
    def group_globs(text):
        """The `--case` globs of the group table: the backticked words of the second column."""
        start = text.index("## Run the CD groups")
        end = text.find("\n## ", start + 1)
        section = text[start:end if end != -1 else len(text)]
        globs = []
        for line in section.splitlines():
            cells = line.split("|")
            if line.startswith("| ") and len(cells) > 3 and "`" in cells[2] and cells[1].strip() != "Group":
                globs += re.findall(r"`([^`]+)`", cells[2])
        return globs

    @staticmethod
    def unmatched_cases(text, cases):
        globs = EvalReadme.group_globs(text)
        return [c for c in cases if not any(fnmatch.fnmatchcase(c, g) for g in globs)]

    def test_every_case_folder_is_in_a_group_row(self):
        cases = sorted(p for p in os.listdir(os.path.join(SKILL, "evals"))
                       if os.path.isdir(os.path.join(SKILL, "evals", p)))
        text = read(os.path.join(SKILL, "evals", "README.md"))
        self.assertTrue(cases)
        self.assertTrue(self.group_globs(text))
        self.assertEqual([], self.unmatched_cases(text, cases))

    def test_a_case_folder_in_no_group_row_is_reported(self):
        table = "## Run the CD groups\n\n| Group | `--case` glob | Run |\n|---|---|---|\n| A | `deploy-*` | x |\n"
        self.assertEqual(["zzz-01"], self.unmatched_cases(table, ["deploy-01", "zzz-01"]))

    def test_a_missing_group_table_fails(self):
        with self.assertRaises(ValueError):
            self.group_globs("no table here")


if __name__ == "__main__":
    unittest.main()
