import glob
import os
import re
import unittest

from skill_files import LEVELS, PREFIXES, SKILL, all_rules, frontmatter, level, read, rule_entries, rule_files

FIELDS = ("Severity", "Rule", "Check", "Fix")
NAME_IDS = [f"NAME-{n:02d}" for n in range(1, 10)]


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
        self.assertIn("scripts/node-support-offline.json", self.text)

    def test_the_naming_rule_09_reads_the_intake_fact_not_gh_calls(self):
        fields = dict(rule_entries(rule_files()["naming"]))["NAME-09"]
        self.assertIn("required_checks", fields["Check"])
        self.assertNotIn("gh api", " ".join(fields.values()))

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
