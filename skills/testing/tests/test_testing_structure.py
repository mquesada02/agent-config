import ast
import json
import os
import re
import sys
import unittest

import helper_testing_rules as helper

SKILL_MD = os.path.join(helper.SKILL, "SKILL.md")
LINK = re.compile(r"\]\(([^)\s]+)\)")
ID = re.compile(r"^(ASSERT|RUN|PAR|DBL|GRP|RS|TS)-\d{2}$")
SEVERITIES = ("critical", "required", "suggestion")
TEST_FILE_NAMES = re.compile(r"^(test_testing_|helper_testing_|grade_testing_).+\.py$")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def catalog_node():
    """The `CATALOG` dict literal of intake.py, read from its source (the script is never imported)."""
    tree = ast.parse(read(helper.SCRIPT))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "CATALOG" for target in node.targets
        ):
            return node.value
    raise AssertionError("intake.py has no CATALOG constant")


class SkillFilesTest(unittest.TestCase):
    def test_skill_md_names_the_skill(self):
        self.assertIn("\nname: testing\n", read(SKILL_MD).split("\n---\n", 1)[0] + "\n")

    def test_skill_md_names_the_detected_keys_and_the_file_arguments(self):
        text = read(SKILL_MD)
        for key in ("languages", "entries", "facts"):
            with self.subTest(key):
                self.assertIn(f"`{key}`", text)
        self.assertIn("intake.py <repo root> [file ...]", text)

    def test_every_file_the_router_links_exists(self):
        links = [link for link in LINK.findall(read(SKILL_MD)) if not re.match(r"^[a-z]+:", link)]
        self.assertIn("scripts/intake.py", links)
        for link in links:
            with self.subTest(link):
                self.assertTrue(os.path.exists(os.path.join(helper.SKILL, link.split("#")[0])))

    def test_every_test_module_follows_the_naming_rule(self):
        names = [n for n in os.listdir(helper.HERE) if n.endswith(".py") and n != "__init__.py"]
        self.assertTrue(names)
        for name in names:
            with self.subTest(name):
                self.assertRegex(name, TEST_FILE_NAMES)

    def test_test_folder_is_in_the_declared_test_command(self):
        text = read(os.path.join(helper.REPO, ".claude", "CLAUDE.md"))
        self.assertIn("'skills/testing/tests'", text)


class CatalogTest(unittest.TestCase):
    def test_catalog_is_a_literal_with_the_seed_ids_and_severities(self):
        node = catalog_node()
        self.assertIsInstance(node, ast.Dict)
        keys = [key.value for key in node.keys]
        self.assertEqual(len(keys), len(set(keys)), "a rule id is listed twice")
        self.assertEqual(ast.literal_eval(node), helper.SEEDS)

    def test_every_catalog_id_is_well_formed_with_a_known_severity(self):
        for rule_id, severity in ast.literal_eval(catalog_node()).items():
            with self.subTest(rule_id):
                self.assertRegex(rule_id, ID)
                self.assertIn(severity, SEVERITIES)


@unittest.skipUnless(sys.version_info >= (3, 11), "the script needs tomllib (Python 3.11 or newer)")
class CatalogUseTest(unittest.TestCase):
    def test_every_seed_id_is_known_to_unknown_ids(self):
        repo = helper.Repo()
        self.addCleanup(repo.close)
        listed = ", ".join(f'"{rule_id}"' for rule_id in helper.SEEDS)
        prose = "".join(f"- {rule_id}: reason\n" for rule_id in helper.SEEDS)
        text = helper.block(replace={"rules": f"[rules]\ndisabled = [{listed}]\n"})
        repo.write(helper.doc(text, prose_after=prose))
        rules, _, code = helper.run_json(repo.root)
        self.assertEqual(code, 0)
        self.assertEqual(rules["unknown_ids"], [])
        self.assertEqual(rules["disabled_without_reason"], [])


GENERAL_MD = os.path.join(helper.SKILL, "general.md")
REVIEW_MD = os.path.join(helper.SKILL, "review.md")
ENTRIES = os.path.join(helper.SKILL, "entries")
EVALS = os.path.join(helper.SKILL, "evals")
ANY_ID = re.compile(r"\b[A-Z]+-\d{2}\b")
SEVERITY_WORDS = re.compile(r"\b(critical|required|suggestion)\b", re.IGNORECASE)
TDD = re.compile(
    r"\b(load|invoke|call|run|use|follow)\b[^\n]{0,60}?(?<![\w-])(tdd|test-driven|mattpocock-skills:tdd)(?![\w-])",
    re.IGNORECASE,
)
ADAPTED_LINE = re.compile(r"^Adapted from .+ \(MIT\)\.$")
ROUTER_MARKERS = ("Scope", "Intake", "General", "Entries", "Review")
CRITICAL_TEXT_IDS = ("ASSERT-01", "ASSERT-02", "ASSERT-03", "RUN-01")
RULE_LABELS = ("**Finding when**", "**Not a finding when**", "**Fix**")
CASE_ENTRIES = ("case.yaml", "expect.json", "prompt.md", "scaffold.sh", "repo", "graders")


def section(text, heading):
    """The lines under a `## heading`, up to the next `## ` heading."""
    lines = text.splitlines()
    start = lines.index(heading)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start + 1:end]


def catalogue_rows(text):
    """(id, severity, rule) of each row of the `## Catalogue` table."""
    rows = []
    for line in section(text, "## Catalogue"):
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells[0] in ("Id",) or set(cells[0]) <= set("-: "):
            continue
        rows.append(tuple(cells))
    return rows


def catalogue_differences(script, table):
    """The ids that differ between two id-to-severity dicts: missing, extra or another severity."""
    return sorted(
        rule_id for rule_id in set(script) | set(table) if script.get(rule_id) != table.get(rule_id)
    )


def entry_violations(text):
    """Lines of an entry file that hold a catalogue id and a severity word, or start a table row."""
    return [
        line for line in text.splitlines()
        if ANY_ID.search(line) and (SEVERITY_WORDS.search(line) or line.lstrip().startswith("|"))
    ]


def tdd_violations(text):
    return [line for line in text.splitlines() if TDD.search(line)]


def adapted_violations(text):
    return [line for line in text.splitlines() if "Adapted from" in line and not ADAPTED_LINE.match(line)]


def entry_files():
    if not os.path.isdir(ENTRIES):
        return []
    return [os.path.join(ENTRIES, n) for n in sorted(os.listdir(ENTRIES)) if n.endswith(".md")]


def skill_text_files():
    paths = [SKILL_MD, GENERAL_MD, REVIEW_MD] + entry_files()
    scripts = os.path.join(helper.SKILL, "scripts")
    paths += [os.path.join(scripts, n) for n in sorted(os.listdir(scripts)) if n.endswith(".py")]
    return paths


class CatalogueTableTest(unittest.TestCase):
    def setUp(self):
        self.rows = catalogue_rows(read(GENERAL_MD))

    def test_ids_are_unique_and_well_formed(self):
        ids = [row[0] for row in self.rows]
        self.assertTrue(ids)
        self.assertEqual(len(ids), len(set(ids)), "a rule id is listed twice")
        for rule_id in ids:
            with self.subTest(rule_id):
                self.assertRegex(rule_id, ID)

    def test_severities_are_known_and_rules_are_not_empty(self):
        for rule_id, severity, rule in self.rows:
            with self.subTest(rule_id):
                self.assertIn(severity, SEVERITIES)
                self.assertTrue(rule)

    def test_script_constant_equals_the_table(self):
        table = {row[0]: row[1] for row in self.rows}
        self.assertEqual(catalogue_differences(ast.literal_eval(catalog_node()), table), [])

    def test_comparison_on_samples(self):
        same = {"RUN-02": "required", "DBL-01": "suggestion"}
        self.assertEqual(catalogue_differences(same, dict(same)), [])
        self.assertTrue(catalogue_differences(same, dict(same, **{"RUN-02": "critical"})))
        self.assertTrue(catalogue_differences(same, {"DBL-01": "suggestion"}))
        self.assertTrue(catalogue_differences(same, dict(same, **{"PAR-01": "required"})))


class IdUseTest(unittest.TestCase):
    def test_every_id_that_a_file_names_is_in_the_catalogue(self):
        catalogue = {row[0] for row in catalogue_rows(read(GENERAL_MD))}
        for path in [SKILL_MD, GENERAL_MD, REVIEW_MD] + entry_files():
            for found in sorted(set(ANY_ID.findall(read(path)))):
                with self.subTest(path=os.path.basename(path), id=found):
                    self.assertIn(found, catalogue)

    def test_id_pattern_catches_a_typo_in_the_area_and_skips_prose(self):
        self.assertEqual(ANY_ID.findall("ASERT-01 and SHA-256 and RUN-02"), ["ASERT-01", "RUN-02"])


class RuleTextTest(unittest.TestCase):
    def test_critical_ids_have_a_subsection_with_the_three_labels(self):
        rules = section(read(GENERAL_MD), "## Rules")
        for rule_id in CRITICAL_TEXT_IDS:
            with self.subTest(rule_id):
                self.assertIn(f"### {rule_id}", rules)
                start = rules.index(f"### {rule_id}")
                end = next((i for i in range(start + 1, len(rules)) if rules[i].startswith("### ")), len(rules))
                body = "\n".join(rules[start:end])
                positions = [body.find(label) for label in RULE_LABELS]
                self.assertNotIn(-1, positions)
                self.assertEqual(positions, sorted(positions))

    def test_every_subsection_is_a_catalogue_id(self):
        catalogue = {row[0] for row in catalogue_rows(read(GENERAL_MD))}
        for line in section(read(GENERAL_MD), "## Rules"):
            if line.startswith("### "):
                self.assertIn(line[4:].strip(), catalogue)


class RouterFlowTest(unittest.TestCase):
    def test_skill_md_has_the_five_router_steps_in_order(self):
        steps = re.findall(r"^\d+\. (\w+)\.", "\n".join(section(read(SKILL_MD), "## Review flow")), re.MULTILINE)
        self.assertEqual(tuple(steps), ROUTER_MARKERS)

    def test_skill_md_links_the_general_and_review_files(self):
        links = LINK.findall(read(SKILL_MD))
        for name in ("general.md", "review.md", "scripts/grade_testing_report.py"):
            with self.subTest(name):
                self.assertIn(name, links)


class EntryAndTextRulesTest(unittest.TestCase):
    def test_entry_files_hold_no_severity_and_no_rule_row(self):
        for path in entry_files():
            with self.subTest(os.path.basename(path)):
                self.assertEqual(entry_violations(read(path)), [])

    def test_entry_rule_on_samples(self):
        self.assertEqual(entry_violations("Check RS-01 by running `cargo test --doc`.\nA required step."), [])
        self.assertTrue(entry_violations("RS-01 is critical here."))
        self.assertTrue(entry_violations("| RS-01 | x | y |"))
        self.assertTrue(entry_violations("TS-01: this is a Required rule."))

    def test_no_skill_file_tells_the_agent_to_load_the_tdd_skill(self):
        for path in skill_text_files():
            with self.subTest(os.path.basename(path)):
                self.assertEqual(tdd_violations(read(path)), [])

    def test_tdd_rule_on_samples(self):
        self.assertTrue(tdd_violations("Load the TDD skill first."))
        self.assertTrue(tdd_violations("Then invoke mattpocock-skills:tdd for the loop."))
        self.assertTrue(tdd_violations("Use the test-driven loop of the other skill."))
        self.assertEqual(tdd_violations("Tests are not written test-first here. The tdd skill stays separate."), [])

    def test_every_adapted_from_line_has_the_attribution_form(self):
        for path in skill_text_files():
            with self.subTest(os.path.basename(path)):
                self.assertEqual(adapted_violations(read(path)), [])

    def test_attribution_rule_on_samples(self):
        self.assertEqual(adapted_violations("Adapted from some skill, v1 (MIT)."), [])
        self.assertTrue(adapted_violations("Adapted from some skill."))
        self.assertTrue(adapted_violations("Text. Adapted from x (MIT)."))
        self.assertTrue(adapted_violations("Adapted from (MIT)."))


class EvalCaseTest(unittest.TestCase):
    def cases(self):
        self.assertTrue(os.path.isdir(EVALS), "skills/testing/evals does not exist")
        return sorted(n for n in os.listdir(EVALS) if os.path.isdir(os.path.join(EVALS, n)))

    def test_each_case_has_its_files_and_folders(self):
        cases = self.cases()
        self.assertTrue(cases)
        for case in cases:
            for entry in CASE_ENTRIES:
                with self.subTest(case=case, entry=entry):
                    self.assertTrue(os.path.exists(os.path.join(EVALS, case, entry)))

    def test_scaffold_is_executable(self):
        for case in self.cases():
            with self.subTest(case):
                self.assertTrue(os.access(os.path.join(EVALS, case, "scaffold.sh"), os.X_OK))

    def test_expected_ids_are_in_the_catalogue(self):
        catalogue = {row[0] for row in catalogue_rows(read(GENERAL_MD))}
        for case in self.cases():
            with self.subTest(case):
                data = json.loads(read(os.path.join(EVALS, case, "expect.json")))
                for rule_id in data["expect"] + data["forbid"]:
                    self.assertIn(rule_id, catalogue)

    def test_expected_ids_have_rule_text(self):
        with_text = {line[4:].strip() for line in section(read(GENERAL_MD), "## Rules") if line.startswith("### ")}
        for case in self.cases():
            with self.subTest(case):
                data = json.loads(read(os.path.join(EVALS, case, "expect.json")))
                for rule_id in data["expect"]:
                    self.assertIn(rule_id, with_text)

    def test_cases_without_a_fresh_report_have_no_result_line_grader(self):
        for case in ("no-files-in-scope", "approve-1", "approve-invalid"):
            with self.subTest(case):
                self.assertFalse(os.path.exists(os.path.join(EVALS, case, "graders", "section-summary.md")))

    def test_evals_readme_exists(self):
        self.assertTrue(os.path.isfile(os.path.join(EVALS, "README.md")))


if __name__ == "__main__":
    unittest.main()
