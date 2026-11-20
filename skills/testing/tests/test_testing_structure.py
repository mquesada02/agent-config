import ast
import functools
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
SETUP_MD = os.path.join(helper.SKILL, "setup.md")
WRITE_MD = os.path.join(helper.SKILL, "write.md")
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
RULE_TEXT_IDS = (
    "ASSERT-01", "ASSERT-02", "ASSERT-03", "RUN-01",
    "RUN-02", "RUN-03", "RUN-04", "RUN-05", "PAR-01", "PAR-02", "GRP-01", "DBL-01", "RS-01",
)
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
    paths = [SKILL_MD, GENERAL_MD, REVIEW_MD, SETUP_MD, WRITE_MD] + entry_files()
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
        for path in [SKILL_MD, GENERAL_MD, REVIEW_MD, SETUP_MD, WRITE_MD] + entry_files():
            for found in sorted(set(ANY_ID.findall(read(path)))):
                with self.subTest(path=os.path.basename(path), id=found):
                    self.assertIn(found, catalogue)

    def test_id_pattern_catches_a_typo_in_the_area_and_skips_prose(self):
        self.assertEqual(ANY_ID.findall("ASERT-01 and SHA-256 and RUN-02"), ["ASERT-01", "RUN-02"])


class RuleTextTest(unittest.TestCase):
    def test_listed_ids_have_a_subsection_with_the_three_labels(self):
        rules = section(read(GENERAL_MD), "## Rules")
        for rule_id in RULE_TEXT_IDS:
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


SETUP_STEPS = (
    "## Step 1: Detect", "## Step 2: Interview", "## Step 3: Unknown ids", "## Step 4: Draft",
    "## Step 5: Approve and write", "## Step 6: Check", "## Step 7: Report",
)
SETUP_EXPECT_KEYS = {"set", "unset", "allow_missing", "contains", "absent"}


class SetupModeTest(unittest.TestCase):
    def test_skill_md_links_the_setup_file_and_it_exists(self):
        self.assertIn("setup.md", LINK.findall(read(SKILL_MD)))
        self.assertTrue(os.path.isfile(SETUP_MD))

    def test_skill_md_links_the_setup_grader(self):
        self.assertIn("scripts/grade_testing_setup.py", LINK.findall(read(SKILL_MD)))

    def test_skill_md_has_a_setup_flow_section(self):
        self.assertIn("## Setup flow", read(SKILL_MD).splitlines())

    def test_setup_md_has_the_seven_steps_in_order(self):
        headings = [line for line in read(SETUP_MD).splitlines() if line.startswith("## Step ")]
        self.assertEqual(tuple(headings), SETUP_STEPS)

    def test_every_setup_case_has_an_expectation_file_with_known_keys(self):
        cases = [n for n in sorted(os.listdir(EVALS)) if n.startswith("setup-") and os.path.isdir(os.path.join(EVALS, n))]
        self.assertTrue(cases)
        for case in cases:
            with self.subTest(case):
                data = json.loads(read(os.path.join(EVALS, case, "expect-setup.json")))
                self.assertIsInstance(data, dict)
                self.assertLessEqual(set(data), SETUP_EXPECT_KEYS)


WRITE_MARKERS = ("Scope", "Intake", "General", "Entries", "Write")
WRITE_STEPS = (
    "## Step 1: Settings", "## Step 2: Choose", "## Step 3: Write", "## Step 4: Self-check",
    "## Step 5: Run", "## Step 6: Fix", "## Step 7: Report",
)
WRITE_EXPECT_KEYS = {
    "tests", "product", "existing", "grouped", "fallback", "error_line", "result", "bugs",
    "command_contains",
}


class WriteModeTest(unittest.TestCase):
    def test_skill_md_has_the_five_write_steps_in_order(self):
        steps = re.findall(r"^\d+\. (\w+)\.", "\n".join(section(read(SKILL_MD), "## Write flow")), re.MULTILINE)
        self.assertEqual(tuple(steps), WRITE_MARKERS)

    def test_skill_md_links_the_write_file_and_grader_and_they_exist(self):
        links = LINK.findall(read(SKILL_MD))
        for name in ("write.md", "scripts/grade_testing_write.py"):
            with self.subTest(name):
                self.assertIn(name, links)
                self.assertTrue(os.path.isfile(os.path.join(helper.SKILL, name)))

    def test_write_md_has_the_seven_steps_in_order(self):
        headings = [line for line in read(WRITE_MD).splitlines() if line.startswith("## Step ")]
        self.assertEqual(tuple(headings), WRITE_STEPS)

    def test_general_md_has_the_kinds_and_test_points_between_flakiness_and_rules(self):
        headings = [line for line in read(GENERAL_MD).splitlines() if line.startswith("## ")]
        order = ("## Flakiness", "## Kinds of tests", "## Test points", "## Rules")
        positions = [headings.index(h) for h in order]
        self.assertEqual(positions, sorted(positions))

    def test_every_write_case_has_an_expectation_file_with_known_keys(self):
        cases = [n for n in sorted(os.listdir(EVALS)) if n.startswith("write-") and os.path.isdir(os.path.join(EVALS, n))]
        self.assertTrue(cases)
        for case in cases:
            with self.subTest(case):
                data = json.loads(read(os.path.join(EVALS, case, "expect-write.json")))
                self.assertIsInstance(data, dict)
                self.assertLessEqual(set(data), WRITE_EXPECT_KEYS)
                self.assertIn("tests", data)


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


RUNNABLE_IDS = RULE_TEXT_IDS[4:]
RUNNABLE_SECTIONS = ("## Sizes and groups", "## Doubles and seams", "## Parallel safety", "## Flakiness")
CASE_TICKS = re.compile(r"`([a-z0-9-]+)`")


@functools.lru_cache(maxsize=None)
def case_expectations():
    """case name -> parsed expect.json of every eval case (read once)."""
    names = sorted(n for n in os.listdir(EVALS) if os.path.isdir(os.path.join(EVALS, n)))
    return {n: json.loads(read(os.path.join(EVALS, n, "expect.json"))) for n in names}


class RunnableRulesTest(unittest.TestCase):
    def test_general_sections_exist_in_order_between_catalogue_and_rules(self):
        headings = [line for line in read(GENERAL_MD).splitlines() if line.startswith("## ")]
        positions = [headings.index(h) for h in ("## Catalogue",) + RUNNABLE_SECTIONS + ("## Rules",)]
        self.assertEqual(positions, sorted(positions))

    def test_review_md_states_the_not_checked_prefix_and_the_timed_run(self):
        text = read(REVIEW_MD)
        self.assertIn("`Not checked: <entry>[; <entry>...].`", text)
        self.assertIn("## Timed run", text)

    def test_every_runnable_id_is_expected_by_a_case_and_grp_01_by_two(self):
        expected = [rule_id for data in case_expectations().values() for rule_id in data["expect"]]
        for rule_id in RUNNABLE_IDS:
            with self.subTest(rule_id):
                self.assertGreaterEqual(expected.count(rule_id), 2 if rule_id == "GRP-01" else 1)

    def test_no_groups_case_forbids_the_three_size_ids(self):
        data = case_expectations()["no-groups"]
        self.assertEqual(data["expect"], [])
        self.assertEqual(sorted(data["forbid"]), ["GRP-01", "RUN-03", "RUN-04"])

    def test_medium_loopback_case_forbids_run_03(self):
        self.assertIn("RUN-03", case_expectations()["run-03-medium-loopback"]["forbid"])

    def test_readme_lists_every_case_folder_as_a_backticked_name(self):
        listed = set(CASE_TICKS.findall(read(os.path.join(EVALS, "README.md"))))
        for case in case_expectations():
            with self.subTest(case):
                self.assertIn(case, listed)


RUST_ENTRY = os.path.join(ENTRIES, "rust.md")
RUST_SECTIONS = (
    "## Detection notes", "## Commands", "## Runner facts", "## Layout", "## Libraries", "## Rules",
    "## Design how-to",
)
RUST_LABELS = ("**How to write**", "**Check details**")
NEXTEST_LIST_PAGE = "https://nexte.st/docs/listing/"
NEXTEST_RUNNING_PAGE = "https://nexte.st/docs/running/"
CARGO_TEST_PAGE = "https://doc.rust-lang.org/cargo/commands/cargo-test.html"


def subsection(lines, heading):
    start = lines.index(heading)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("### ")), len(lines))
    return "\n".join(lines[start:end])


class RustEntryTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(os.path.isfile(RUST_ENTRY), "skills/testing/entries/rust.md does not exist")
        self.text = read(RUST_ENTRY)

    def test_the_entry_has_the_seven_sections_in_order(self):
        headings = [line for line in self.text.splitlines() if line.startswith("## ")]
        self.assertEqual(tuple(headings), RUST_SECTIONS)

    def test_the_entry_has_a_subsection_with_both_labels_for_every_rule_text_id(self):
        rules = section(self.text, "## Rules")
        for rule_id in RULE_TEXT_IDS:
            with self.subTest(rule_id):
                self.assertIn(f"### {rule_id}", rules)
                body = subsection(rules, f"### {rule_id}")
                positions = [body.find(label) for label in RUST_LABELS]
                self.assertNotIn(-1, positions)
                self.assertEqual(positions, sorted(positions))

    def test_the_entry_has_no_rule_subsection_for_an_id_without_rule_text(self):
        headings = [line[4:].strip() for line in section(self.text, "## Rules") if line.startswith("### ")]
        self.assertEqual(sorted(headings), sorted(RULE_TEXT_IDS))

    def test_general_md_holds_the_rs_01_rule_text_and_the_catalogue_note(self):
        general = read(GENERAL_MD)
        body = subsection(section(general, "## Rules"), "### RS-01")
        finding = body.split("**Not a finding when**")[0]
        self.assertIn("nextest", finding)
        self.assertIn("doc", finding)
        note = next(line for line in general.splitlines() if line.startswith("The script constant `CATALOG`"))
        self.assertIn("`TS-01` has none yet", note)
        self.assertNotIn("RS-01", note)

    def test_every_runner_fact_is_confirmed_with_a_link_or_unconfirmed_and_unused(self):
        facts = [line for line in section(self.text, "## Runner facts") if line.startswith("- ")]
        self.assertTrue(facts)
        for line in facts:
            with self.subTest(line[:60]):
                body = line[2:]
                self.assertTrue(
                    (body.startswith("Confirmed:") and "https://" in body) or body.startswith("Unconfirmed, not used:")
                )

    def test_the_list_fact_and_the_two_narrowing_facts_link_their_pages(self):
        facts = [line[2:] for line in section(self.text, "## Runner facts") if line.startswith("- ")]
        listing = [f for f in facts if f.startswith("Confirmed: `cargo nextest list`") or f.startswith("Confirmed: cargo nextest list")]
        self.assertEqual(len(listing), 1)
        self.assertIn(NEXTEST_LIST_PAGE, listing[0])
        narrowing = [f for f in facts if f.startswith("Confirmed: Narrowing flags")]
        self.assertEqual(len(narrowing), 2)
        self.assertEqual(sum(CARGO_TEST_PAGE in f for f in narrowing), 1)
        self.assertEqual(sum(NEXTEST_RUNNING_PAGE in f for f in narrowing), 1)

    def test_an_unconfirmed_fact_is_not_used_outside_the_runner_facts_section(self):
        outside = "\n".join(
            line for heading in RUST_SECTIONS if heading != "## Runner facts" for line in section(self.text, heading)
        )
        self.assertNotIn("--report-time", outside)
        self.assertNotIn("cargo test -- --list", outside)

    def test_skill_md_links_the_entry_and_step_4_still_loads_entries_by_value(self):
        text = read(SKILL_MD)
        self.assertIn("entries/rust.md", LINK.findall(text))
        review_flow = "\n".join(section(text, "## Review flow"))
        self.assertIn("`entries/<value>.md`", review_flow)

    def test_the_narrowing_and_placement_phrases_are_in_the_right_files(self):
        review, write = read(REVIEW_MD), read(WRITE_MD)
        self.assertEqual(review.count("arguments that a loaded entry names"), 1)
        self.assertEqual(write.count("arguments that a loaded entry names"), 0)
        self.assertEqual(write.count("path that a loaded entry derives"), 1)
        self.assertEqual(write.count("a path that a recorded group selects"), 1)
        for gone in ("Until they land", "the test location is the user-named path", "Write does not choose the file by group"):
            with self.subTest(gone):
                self.assertNotIn(gone, write)
        step_4 = "\n".join(section(write, "## Step 4: Self-check"))
        self.assertIn("RS-01", step_4)
        self.assertIn("`No group: <languages>. Tests are placed at the named or derived path.`", write)

    def test_the_rust_eval_cases_expect_and_forbid_rs_01_and_forbid_run_04_under_cargo_test(self):
        cases = case_expectations()
        self.assertEqual(sum("RS-01" in data["expect"] for data in cases.values()), 1)
        self.assertEqual(sum("RS-01" in data["forbid"] for data in cases.values()), 1)
        self.assertIn("RUN-04", cases["rs-run-04-cargo-test-not-checked"]["forbid"])
        for name in ("write-rs-derived-path", "write-rs-group-path", "write-rs-no-group", "write-rs-binary-only"):
            with self.subTest(name):
                self.assertIn(name, cases)


if __name__ == "__main__":
    unittest.main()
