import glob
import json
import os
import re
import unittest

from skill_files import LEVELS, PREFIXES, SKILL, all_rules, frontmatter, level, read, rule_entries, rule_files

FIELDS = ("Severity", "Rule", "Check", "Fix")
NAME_IDS = [f"NAME-{n:02d}" for n in range(1, 10)]
GRAPH_IDS = [f"GRAPH-{n:02d}" for n in range(1, 8)]
MAINT_IDS = [f"MAINT-{n:02d}" for n in range(1, 4)]
COST_IDS = [f"COST-{n:02d}" for n in range(1, 9)]
MONO_IDS = ["MONO-01", "MONO-02"]
SEC_IDS = [f"SEC-{n:02d}" for n in range(1, 11)]
ZIZMOR_MAPPING = {
    "unpinned-uses": "SEC-01", "excessive-permissions": "SEC-03", "template-injection": "SEC-04",
    "artipacked": "SEC-05", "dangerous-triggers": "SEC-07", "secrets-inherit": "SEC-08",
    "cache-poisoning": "SEC-09",
}
TOOLS_SECTIONS = ["Detection", "Install hints", "Running the tools", "Merging the output",
                  "zizmor to SEC mapping", "Pin a SHA", "Offline Node support list"]


def module_files():
    """Every module file that exists, as a path relative to the skill folder."""
    paths = [p for p in glob.glob(os.path.join(SKILL, "*.md")) if os.path.basename(p) != "SKILL.md"]
    paths += glob.glob(os.path.join(SKILL, "rules", "*.md"))
    paths += glob.glob(os.path.join(SKILL, "templates", "*.yml"))
    paths += glob.glob(os.path.join(SKILL, "scripts", "intake.py"))
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

    def test_every_check_is_mechanical(self):
        for rule_id, fields in self.sec.items():
            self.assertTrue(fields["Check"].startswith("mechanical"), rule_id)

    def test_every_fix_is_one_sentence(self):
        for rule_id, fields in self.sec.items():
            self.assertEqual(len(re.findall(r"[.!?](?:\s|$)", fields["Fix"])), 1, rule_id)

    def test_sec_01_fix_points_to_the_sha_lookup_in_tools_md(self):
        self.assertIn("tools.md", self.sec["SEC-01"]["Fix"])

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

    def test_the_name_is_ci_pipelines(self):
        self.assertEqual(self.meta["name"], "ci-pipelines")

    def test_the_description_leads_with_the_skill_name_and_stays_short(self):
        description = self.meta["description"]
        self.assertTrue(description.startswith("ci-pipelines"), description)
        self.assertLessEqual(len(description), 400)

    def test_the_description_triggers_on_workflow_files_and_names_both_branches(self):
        description = self.meta["description"].lower()
        self.assertIn(".github/workflows", description)
        self.assertIn("create", description)
        self.assertIn("review", description)

    def test_the_router_links_every_module_that_exists(self):
        for module in module_files():
            self.assertIn(module, self.text, f"SKILL.md does not point to {module}")

    def test_create_mode_is_not_built_yet_while_create_md_is_missing(self):
        if not os.path.exists(os.path.join(SKILL, "create.md")):
            self.assertIn("not built yet", self.text)

    def test_the_router_runs_the_intake_script_before_it_picks_the_branch(self):
        self.assertIn("scripts/intake.py", self.text)
        self.assertIn("## Intake", self.text)
        self.assertIn("## Pick the branch", self.text)
        self.assertLess(self.text.index("## Intake"), self.text.index("## Pick the branch"))
        intake = self.text[self.text.index("## Intake"):self.text.index("## Pick the branch")]
        self.assertIn("before you pick a branch", intake.lower())
        self.assertIn("tools.md", intake)
        self.assertNotIn("node-support-offline", self.text)

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

    def test_another_edit_points_to_every_rule_file(self):
        bullet = self.text[self.text.index("**Another edit**"):self.text.index("## Modules")]
        for rule_file in ("rules/naming.md", "rules/job-graph.md", "rules/cost.md", "rules/security.md",
                          "rules/maintainability.md"):
            self.assertIn(rule_file, bullet)
        self.assertIn("rules/monorepo.md", bullet)
        self.assertIn("when the intake finds a monorepo", bullet)

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
        self.assertIn("load every rule file", self.text)

    def test_it_writes_the_report_as_the_final_message(self):
        self.assertIn("final message", self.text)

    def test_it_puts_the_version_of_a_tool_on_path_in_its_bullet(self):
        self.assertIn("on path (", self.text)

    def test_it_takes_its_facts_from_the_intake_and_runs_no_gh_or_tool_calls(self):
        for fact in ("required_checks", "installed_tools", "runner_labels"):
            self.assertIn(fact, self.text)
        for gone in ("gh api", "command -v", "actionlint -version", "zizmor --version", "interim"):
            self.assertNotIn(gone, self.text)

    def test_section_2_names_defaults_and_unknown_facts(self):
        self.assertIn("`default`", self.text)
        self.assertIn("`unknown`", self.text)
        self.assertIn("offline", self.text)

    def test_it_keeps_the_name_09_row_and_the_flag_mark(self):
        self.assertIn("name-09 row", self.text)
        self.assertIn("⚑", self.text)

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
        step = self.text[self.text.index("1. load every rule file"):self.text.index("2. read the intake json")]
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

    def test_it_makes_no_edit(self):
        self.assertIn("edits nothing", self.text)
        self.assertIn("make no edit", self.text)


class EvalReadme(unittest.TestCase):
    def test_the_documented_run_has_the_spec_flags(self):
        text = read(os.path.join(SKILL, "evals", "README.md"))
        for flag in ("claude plugin eval", "--no-publish", "-j 2", "--runs 3", "--threshold 1.0",
                     "--scaffold", "--ablation with-without"):
            self.assertIn(flag, text)

    def test_the_allowed_tools_are_the_intake_call_and_no_gh_api(self):
        text = read(os.path.join(SKILL, "evals", "README.md"))
        self.assertIn('--allow-tools "Bash(python3 *scripts/intake.py*)"', text)
        self.assertNotIn("Bash(gh api", text)


if __name__ == "__main__":
    unittest.main()
