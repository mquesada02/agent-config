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
    "RUN-02", "RUN-03", "RUN-04", "RUN-05", "PAR-01", "PAR-02", "GRP-01", "DBL-01", "RS-01", "TS-01",
)
RUST_RULE_IDS = tuple(rule_id for rule_id in RULE_TEXT_IDS if rule_id != "TS-01")
TS_RULE_IDS = tuple(rule_id for rule_id in RULE_TEXT_IDS if rule_id != "RS-01")
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


CASE_NAME_ID = re.compile(r"(?:^|-)([a-z]+)-(\d\d)(?=-|$)")
CASE_NAME_AREAS = {"assert": "ASSERT", "run": "RUN", "par": "PAR", "dbl": "DBL", "grp": "GRP", "rs": "RS",
                   "ts": "TS", "jest": "TS", "node": "TS"}
GRADER_PATTERN = re.compile(r"^pattern: '(.*)'$", re.MULTILINE)
GRADER_FLAGS = re.compile(r"^flags: (\w+)$", re.MULTILINE)


def case_name_ids(name):
    """The rule ids that a case folder name carries, as `<area>-<nn>` (`jest` and `node` stand for `TS`).
    A name without such a part names a scenario, not a rule: the id check skips it."""
    return {f"{CASE_NAME_AREAS[area]}-{number}" for area, number in CASE_NAME_ID.findall(name)
            if area in CASE_NAME_AREAS}


def grader_row_matches(text, rule_id):
    """Whether the regex of an `expect-<id>.md` grader matches a report row of that id."""
    pattern = GRADER_PATTERN.search(text)
    if not pattern:
        return False
    flags = GRADER_FLAGS.search(text)
    multiline = re.MULTILINE if flags and "m" in flags.group(1) else 0
    row = f"| 1 | {rule_id} | a.py:1 | problem | fix |"
    return bool(re.search(pattern.group(1).replace("''", "'"), row, multiline))


def case_id_violations(name, expectation, graders, catalogue):
    """What a review case gets wrong about its ids: a folder name id that `expect` and `forbid` lack, and an
    `expect-<id>.md` grader of an id that is not expected, that misses a row of its id or that matches a row of
    another id. `graders` maps a grader file name to its text."""
    violations = [f"folder name id {rule_id} is in neither expect nor forbid" for rule_id in sorted(case_name_ids(name))
                  if rule_id not in expectation["expect"] + expectation["forbid"]]
    for file_name, text in sorted(graders.items()):
        found = re.fullmatch(r"expect-(.+)\.md", file_name)
        if not found:
            continue
        rule_id = found.group(1)
        if rule_id not in expectation["expect"]:
            violations.append(f"{file_name}: {rule_id} is not in expect")
        if not grader_row_matches(text, rule_id):
            violations.append(f"{file_name}: the pattern does not match a row of {rule_id}")
        violations += [f"{file_name}: the pattern matches a row of {other}" for other in sorted(catalogue)
                       if other != rule_id and grader_row_matches(text, other)]
    return violations


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

    def test_each_case_folder_name_and_expect_grader_match_the_ids_of_the_case(self):
        catalogue = {row[0] for row in catalogue_rows(read(GENERAL_MD))}
        for case in self.cases():
            folder = os.path.join(EVALS, case, "graders")
            graders = {n: read(os.path.join(folder, n)) for n in sorted(os.listdir(folder))}
            expectation = json.loads(read(os.path.join(EVALS, case, "expect.json")))
            with self.subTest(case):
                self.assertEqual(case_id_violations(case, expectation, graders, catalogue), [])

    def test_case_id_check_on_samples(self):
        catalogue = {"RUN-01", "RUN-02", "TS-01"}
        good = "---\ntype: regex\npattern: '^\\|\\s*\\d+\\s*\\|\\s*RUN-01\\s*\\|'\nflags: m\n---\n"
        expectation = {"expect": ["RUN-01"], "forbid": []}
        self.assertEqual(case_name_ids("jest-run-01-retry"), {"RUN-01"})
        self.assertEqual(case_name_ids("node-01-watch-script"), {"TS-01"})
        self.assertEqual(case_name_ids("disabled-no-reason"), set())
        self.assertEqual(case_id_violations("run-01-x", expectation, {"expect-RUN-01.md": good}, catalogue), [])
        self.assertTrue(case_id_violations("run-02-x", expectation, {"expect-RUN-01.md": good}, catalogue))
        wrong = good.replace("RUN-01", "RUN-02")
        self.assertTrue(case_id_violations("run-01-x", expectation, {"expect-RUN-01.md": wrong}, catalogue))
        loose = good.replace("RUN-01", "RUN-0\\d")
        self.assertTrue(case_id_violations("run-01-x", expectation, {"expect-RUN-01.md": loose}, catalogue))
        self.assertTrue(case_id_violations("run-01-x", expectation, {"expect-RUN-02.md": wrong}, catalogue))


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
        for rule_id in RUST_RULE_IDS:
            with self.subTest(rule_id):
                self.assertIn(f"### {rule_id}", rules)
                body = subsection(rules, f"### {rule_id}")
                positions = [body.find(label) for label in RUST_LABELS]
                self.assertNotIn(-1, positions)
                self.assertEqual(positions, sorted(positions))

    def test_the_entry_has_no_rule_subsection_for_an_id_without_rule_text(self):
        headings = [line[4:].strip() for line in section(self.text, "## Rules") if line.startswith("### ")]
        self.assertEqual(sorted(headings), sorted(RUST_RULE_IDS))

    def test_general_md_holds_the_rs_01_rule_text_and_the_catalogue_note(self):
        general = read(GENERAL_MD)
        body = subsection(section(general, "## Rules"), "### RS-01")
        finding = body.split("**Not a finding when**")[0]
        self.assertIn("nextest", finding)
        self.assertIn("doc", finding)
        note = next(line for line in general.splitlines() if line.startswith("The script constant `CATALOG`"))
        self.assertNotIn("none yet", note)
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

    def test_the_value_flags_of_the_name_filter_row_are_the_value_flags_of_the_grader(self):
        row = next(line for line in section(self.text, "## Commands") if line.startswith("| Name filter |"))
        self.assertIn("value flags:", row)
        listed = re.findall(r"`([^`]+)`", row.split("value flags:", 1)[1].split("|")[0])
        tree = ast.parse(read(os.path.join(helper.SKILL, "scripts", "grade_testing_write.py")))
        grader = next(
            ast.literal_eval(node.value) for node in tree.body
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "RUST_VALUE_FLAGS" for t in node.targets)
        )
        self.assertEqual(sorted(listed), sorted(grader))

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


TS_ENTRY = os.path.join(ENTRIES, "typescript.md")
TS_SECTIONS = RUST_SECTIONS
RUNNERS = ("Vitest", "Jest", "node:test")
JEST_CASES = (
    "jest-01-watch-script", "jest-01-run-mode", "jest-assert-03-update", "jest-run-01-retry",
    "jest-run-02-fake-timers", "jest-run-04-json-durations", "jest-run-04-wrapper-not-checked",
    "jest-grp-01-list-decides", "jest-grp-01-not-checked", "jest-assert-forms", "jest-net-port-skip",
    "jest-par-02-env-var",
)
NODE_CASES = (
    "node-01-watch-script", "node-01-run-mode", "node-assert-03-update", "node-run-01-rerun",
    "node-run-02-mock-timers", "node-run-04-spec-durations", "node-run-04-wrapper-not-checked",
    "node-grp-01-not-checked", "node-grp-01-readable", "node-assert-forms", "node-net-port-skip",
    "node-par-02-env-var",
)
TS_REVIEW_CASES = (
    "ts-assert-forms", "ts-net-and-port", "ts-skip-and-order", "ts-01-watch-script", "ts-01-run-mode",
    "ts-assert-03-update", "ts-run-01-retry", "ts-run-02-fake-timers", "ts-run-04-verbose-durations",
    "ts-run-04-wrapper-not-checked", "ts-grp-01-list-decides", "ts-grp-01-not-checked", "ts-par-02-env-var",
    "ts-gate-other-runner",
) + JEST_CASES + NODE_CASES
TS_WRITE_CASES = (
    "write-ts-derived-path", "write-ts-mirrored-path", "write-ts-project-group", "write-ts-no-group",
    "write-ts-no-path", "write-ts-existing-test", "write-ts-fakes", "write-ts-gate-other-runner",
    "write-mixed-rust-ts",
    "write-jest-derived-path", "write-jest-project-group", "write-jest-no-path", "write-jest-existing-test",
    "write-jest-fakes", "write-jest-no-group",
    "write-node-derived-path", "write-node-mirrored-path", "write-node-no-group", "write-node-no-path",
    "write-node-existing-test", "write-node-fakes",
    "write-mixed-rust-node",
)
DOCS = {"Vitest": "https://vitest.dev/", "Jest": "https://jestjs.io/", "node:test": "https://nodejs.org/"}
PRIVATE_NAMES = ("mquesada", "vtxlabs")
EXAMPLE = re.compile(r"^- Example: .+ => (row (\d+)|class (.+))$")
GATE_SENTENCE = "The runner gate:"
WATCH_FORM_PHRASE = "a form that a loaded entry names as a watch form"
REPORTER_PHRASE = "reporter argument that a loaded entry names"
WRAPPER_ENTRIES = (
    "`TS-01 (command of <names> is not a plain Vitest command)`",
    "`TS-01 (command of <names> is not a plain Jest command)`",
    "`TS-01 (command of <names> is not a plain node:test command)`",
)
TS_EXTENSIONS = (".ts", ".tsx", ".js", ".mjs", ".cjs")


def table_rows(lines):
    """The first cell of each numbered row of the tables in a list of lines."""
    return [m.group(1) for line in lines for m in [re.match(r"^\| (\d+) \|", line)] if m]


def table_classes(lines, first_header):
    """The first cell of each data row of the table whose header starts with `first_header`."""
    start = next(i for i, line in enumerate(lines) if line.startswith(f"| {first_header} |"))
    rows = []
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        rows.append(line.strip().strip("|").split("|")[0].strip())
    return rows


def example_marks(lines):
    return [m.group(2) or m.group(3) for line in lines for m in [EXAMPLE.match(line)] if m]


def grader_languages():
    """The `LANGUAGES` dict literal of the write grader, read from its source."""
    tree = ast.parse(read(os.path.join(helper.SKILL, "scripts", "grade_testing_write.py")))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "LANGUAGES" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("the write grader has no LANGUAGES constant")


COMMAND_EXAMPLE = re.compile(
    r"^- Example: `([^`]+)`(?: with the script `([^`]+)`| with no such script)? => (?:row (\d+)|class (.+))$"
)
EXEC_FORMS = {
    "vitest": (["npx", "vitest"], ["pnpm", "exec", "vitest"], ["yarn", "vitest"], ["bunx", "vitest"]),
    "jest": (["npx", "jest"], ["pnpm", "exec", "jest"], ["yarn", "jest"], ["bunx", "jest"]),
}
SCRIPT_CALL = re.compile(r"^(?:npm test|npm run (\S+)|pnpm test|pnpm run (\S+)|yarn test|yarn run (\S+)|bun run (\S+))( .*)?$")
WRAPPER_MARKERS = ("&&", "||", ";", "|", "$(", "`", ">", "<")
QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")
SUBCOMMANDS = ("run", "watch", "dev", "related", "list", "bench")
NAME_VALUE_FLAGS = ("-t", "--testNamePattern")
PROJECT_FLAGS = ("--project", "-p")
FIXED_VALUE_FLAGS = ("--maxWorkers", "--reporter", "--outputFile", "--retry")
FIXED_FLAGS = ("--run", "--silent", "--no-color", "--passWithNoTests", "--no-file-parallelism", "--update", "-u", "--coverage")
JEST_NON_TEST = ("--listTests", "--showConfig", "--clearCache", "--version", "--help")
JEST_FIXED_VALUE_FLAGS = ("--maxWorkers", "-w", "--outputFile", "--reporters")
JEST_FIXED_FLAGS = (
    "--ci", "--runInBand", "-i", "--verbose", "--json", "--silent", "--coverage", "--passWithNoTests",
    "--watchman", "--no-watchman", "--cache", "--no-cache", "--runTestsByPath", "-u", "--updateSnapshot",
)
NODE_NAME_FLAGS = ("--test-name-pattern", "--test-skip-pattern")
NODE_FIXED_VALUE_FLAGS = (
    "--test-concurrency", "--test-reporter", "--test-reporter-destination", "--test-timeout",
    "--test-isolation", "--import", "--require", "-r", "--env-file",
)
NODE_FIXED_FLAGS = ("--test-force-exit", "--test-update-snapshots", "--no-warnings", "--experimental-test-coverage")


def parse_command_example(line):
    """(command, scripts, mark) of an `Example:` bullet with a command, else None. A script is keyed by its name."""
    match = COMMAND_EXAMPLE.match(line)
    if not match:
        return None
    command, script, row, klass = match.groups()
    name = SCRIPT_CALL.match(command)
    scripts = {}
    if name and script is not None:
        scripts[next(g for g in name.groups()[:4] if g) if any(name.groups()[:4]) else "test"] = script
    return command, scripts, row or klass


def strip_assignments(tokens):
    while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
        tokens = tokens[1:]
    return tokens


def exec_length(tokens, runner, from_script):
    """How many leading tokens are the exec form of the runner, or None when the command has none."""
    if runner == "node:test":
        return 1 if tokens[:1] == ["node"] and "--test" in tokens else None
    form = next((f for f in EXEC_FORMS[runner] if tokens[:len(f)] == f), None)
    if form is None and from_script and tokens[:1] == [runner]:
        return 1
    return None if form is None else len(form)


def read_command(command, scripts, runner="vitest"):
    """(kind, tokens after the exec form) for steps 1 to 3 of the command reading; kind is plain or wrapper.

    For a wrapper the tokens are all words."""
    tokens = strip_assignments(command.split())
    from_script = False
    call = SCRIPT_CALL.match(" ".join(tokens))
    if call:
        name = next((g for g in call.groups()[:4] if g), "test")
        if name not in scripts:
            return "wrapper", tokens
        tokens = strip_assignments((scripts[name] + (call.group(5) or "")).split())
        from_script = True
        if SCRIPT_CALL.match(" ".join(tokens)):
            return "wrapper", tokens
    text = QUOTED.sub("", " ".join(tokens))
    length = exec_length(tokens, runner, from_script)
    if length is None or any(marker in text for marker in WRAPPER_MARKERS):
        return "wrapper", tokens
    return "plain", tokens[length:]


def has_update_mode(tokens, runner="vitest"):
    if runner == "jest":
        return any(t in ("-u", "--updateSnapshot", "--updateSnapshot=true") for t in tokens)
    if runner == "node:test":
        return "--test-update-snapshots" in tokens
    for index, token in enumerate(tokens):
        value = tokens[index + 1] if index + 1 < len(tokens) else ""
        if token == "-u" or (token == "--update" and value not in ("none", "false")):
            return True
        if token.startswith("--update=") and token.split("=", 1)[1] in ("true", "all", "new"):
            return True
    return False


def has_watch_marker(tokens, runner):
    if runner == "jest":
        return any(
            t in ("--watch", "--watchAll") or t.startswith("--watchAll=")
            or (t.startswith("--watch=") and t.split("=", 1)[1] != "false")
            for t in tokens
        )
    return any(t in ("--watch", "--watch-path") or t.startswith(("--watch=", "--watch-path=")) for t in tokens)


def table_4_row(command, scripts, runner="vitest"):
    kind, tokens = read_command(command, scripts, runner)
    if kind == "wrapper":
        return 1
    if runner == "jest":
        if any(t in JEST_NON_TEST for t in tokens):
            return 2
        return 3 if has_watch_marker(tokens, runner) else 4
    if runner == "node:test":
        return 2 if has_watch_marker(tokens, runner) else 3
    subcommand = next((t for t in tokens if t in SUBCOMMANDS), None)
    if subcommand in ("list", "bench"):
        return 2
    if subcommand in ("watch", "dev") or any(t in ("--watch", "-w") or t.startswith("--watch=") for t in tokens):
        return 3
    if subcommand == "run" or "--run" in tokens:
        return 4
    return 5 if subcommand == "related" else 6


def table_1_row(command, scripts, runner="vitest"):
    kind, tokens = read_command(command, scripts, runner)
    if has_update_mode(tokens, runner):
        return 1
    if kind == "wrapper":
        return 2
    if runner == "jest":
        if has_watch_marker(tokens, runner):
            return 3
        return 4 if any(t in JEST_NON_TEST for t in tokens) else 5
    if runner == "node:test":
        return 3 if has_watch_marker(tokens, runner) else 4
    verdict = table_4_row(command, scripts)
    return {2: 4, 4: 5}.get(verdict, 3)


def flat_tokens(tokens):
    flat = []
    for token in tokens:
        flat.extend(token.split("=", 1) if token.startswith("--") and "=" in token else [token])
    return flat


def token_classes(command, runner="vitest"):
    """The set of selector table classes of the tokens after the exec form (and the Vitest subcommand)."""
    if runner == "jest":
        return jest_token_classes(command)
    if runner == "node:test":
        return node_token_classes(command)
    _, tokens = read_command(command, {}, runner)
    flat = flat_tokens(tokens)
    classes, index, seen_subcommand = set(), 0, False
    while index < len(flat):
        token = flat[index]
        if not seen_subcommand and token in SUBCOMMANDS:
            seen_subcommand = True
            if token == "related":
                classes.add("Unreadable")
        elif token in NAME_VALUE_FLAGS:
            classes.add("Name filter")
            index += 1
        elif token in PROJECT_FLAGS:
            classes.add("Project")
            index += 1
        elif token == "--dir":
            classes.add("Directory")
            index += 1
        elif token in FIXED_VALUE_FLAGS:
            classes.add("Fixed")
            index += 1
        elif token in FIXED_FLAGS:
            classes.add("Fixed")
        elif token.startswith("-") or re.search(r":\d+$", token):
            classes.add("Unreadable")
        else:
            classes.add("Path operand")
        index += 1
    return classes


def flag_name(token):
    """(name, has an inline value) of a token: `--flag=value` is the name `--flag` with an inline value."""
    if token.startswith("--") and "=" in token:
        return token.split("=", 1)[0], True
    return token, False


def jest_token_classes(command):
    _, tokens = read_command(command, {}, "jest")
    classes, index = set(), 0
    while index < len(tokens):
        token = tokens[index]
        name, inline = flag_name(token)
        step = 1 if inline else 2
        if name in ("-t", "--testNamePattern"):
            classes.add("Name filter")
        elif name == "--selectProjects":
            classes.add("Project")
            step = 1
            while not inline and index + step < len(tokens) and not tokens[index + step].startswith("-"):
                step += 1
        elif name == "--testPathPatterns":
            classes.add("Path operand")
        elif name in JEST_FIXED_VALUE_FLAGS:
            classes.add("Fixed")
        elif name in JEST_FIXED_FLAGS:
            classes.add("Fixed")
            step = 1
        elif token.startswith(("-", "^", "/")):
            classes.add("Unreadable")
            step = 1
        else:
            classes.add("Path operand")
            step = 1
        index += step
    return classes


def node_token_classes(command):
    _, tokens = read_command(command, {}, "node:test")
    tokens = [t for t in tokens if t != "--test"]
    classes, index = set(), 0
    while index < len(tokens):
        token = tokens[index]
        name, inline = flag_name(token)
        step = 1 if inline else 2
        if name in NODE_NAME_FLAGS:
            classes.add("Name filter")
        elif name in NODE_FIXED_VALUE_FLAGS:
            classes.add("Fixed")
        elif name in NODE_FIXED_FLAGS:
            classes.add("Fixed")
            step = 1
        elif token.startswith("-"):
            classes.add("Unreadable")
            step = 1
        else:
            classes.add("Path operand")
            step = 1
        index += step
    return classes


def runner_part(lines, runner):
    """The lines of the `### <runner>` sub-heading of a list of section lines."""
    return subsection(lines, f"### {runner}").splitlines()


def labelled_table(lines, label):
    """The lines from a `Table ... :` label line to the next label line (or the end)."""
    start = lines.index(label)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("Table ") and lines[i].endswith(":")), len(lines))
    return lines[start:end]


RUNNER_KEY = {"Vitest": "vitest", "Jest": "jest", "node:test": "node:test"}
SPEC_LINE = re.compile(r"^(\s*)([✔✖]) (.+) \((\d+(?:\.\d+)?)(ms|s)\)$")


def location_row(example, runner):
    """The row of the location table (Table 3, J3 or N3) for an `Example:` bullet of the Layout section."""
    product = re.search(r"`P` = `([^`]+)`", example) or re.search(r"`([^`]+)`", example)
    product = product.group(1)
    paths = re.search(r"`test_paths` = `(\[[^`]*\])`", example)
    test_paths = json.loads(paths.group(1)) if paths else []
    name = os.path.basename(product)
    extensions = (".ts", ".js", ".mjs", ".cjs") if runner == "node:test" else (".ts", ".tsx", ".js", ".mjs", ".cjs")
    if name.endswith(".d.ts") or ".config." in name or not product.endswith(extensions):
        return 1
    if "beside it" in example:
        return 2
    if not test_paths or test_paths == ["."] or test_paths == [product.split("/")[0]]:
        return 3
    return 4 if len(test_paths) == 1 and test_paths[0] in ("test", "tests", "__tests__") else 5


def jest_durations(output):
    """Duration by (file, full name); a pair that more than one result holds gets none."""
    seen = [(r["name"], c["fullName"], c.get("duration")) for r in output["testResults"] for c in r["assertionResults"]]
    return {(f, n): d for f, n, d in seen if d is not None and sum(1 for g, m, _ in seen if (g, m) == (f, n)) == 1}


def spec_durations(text):
    """Duration in ms by full name (the enclosing `▶` suite names joined with ` > `); a name on several lines gets none."""
    stack, found = [], []
    for raw in text.splitlines():
        suite = re.match(r"^(\s*)▶ (.+)$", raw)
        if suite:
            stack = [s for s in stack if s[0] < len(suite.group(1))] + [(len(suite.group(1)), suite.group(2))]
            continue
        line = SPEC_LINE.match(raw)
        if line:
            stack = [s for s in stack if s[0] < len(line.group(1))]
            found.append((" > ".join([s[1] for s in stack] + [line.group(3)]), float(line.group(4)) * (1000 if line.group(5) == "s" else 1)))
    return {name: ms for name, ms in found if [n for n, _ in found].count(name) == 1}


class TypeScriptEntryTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(os.path.isfile(TS_ENTRY), "skills/testing/entries/typescript.md does not exist")
        self.text = read(TS_ENTRY)

    def commands(self, runner):
        return runner_part(section(self.text, "## Commands"), runner)

    def layout(self, runner):
        return runner_part(section(self.text, "## Layout"), runner)

    def ts_01(self):
        return subsection(section(self.text, "## Rules"), "### TS-01").splitlines()

    def test_the_entry_has_the_seven_sections_in_order(self):
        headings = [line for line in self.text.splitlines() if line.startswith("## ")]
        self.assertEqual(tuple(headings), TS_SECTIONS)

    def test_the_entry_has_a_sub_heading_for_each_runner_in_the_runner_sections(self):
        for heading in ("## Commands", "## Runner facts", "## Layout", "## Design how-to"):
            for runner in RUNNERS:
                with self.subTest(heading, runner=runner):
                    self.assertIn(f"### {runner}", section(self.text, heading))
        for heading in ("## Libraries", "## Detection notes"):
            for runner in RUNNERS[1:]:
                with self.subTest(heading, runner=runner):
                    self.assertIn(f"### {runner}", section(self.text, heading))

    def test_the_entry_has_a_subsection_with_both_labels_for_every_typescript_id_and_none_for_rs_01(self):
        rules = section(self.text, "## Rules")
        headings = [line[4:].strip() for line in rules if line.startswith("### ")]
        self.assertEqual(sorted(headings), sorted(TS_RULE_IDS))
        self.assertNotIn("RS-01", headings)
        for rule_id in TS_RULE_IDS:
            with self.subTest(rule_id):
                body = subsection(rules, f"### {rule_id}")
                positions = [body.find(label) for label in RUST_LABELS]
                self.assertNotIn(-1, positions)
                self.assertEqual(positions, sorted(positions))

    def test_each_label_of_each_rule_has_a_bullet_for_each_runner(self):
        rules = section(self.text, "## Rules")
        for rule_id in TS_RULE_IDS:
            body = subsection(rules, f"### {rule_id}")
            how, check = body.split("**Check details**")
            for label, part in (("how", how), ("check", check)):
                for runner in RUNNERS:
                    with self.subTest(rule_id, label=label, runner=runner):
                        self.assertIn(f"- {runner}:", part)

    def test_the_run_command_rows_name_the_worker_cap_and_the_reporter_of_each_runner(self):
        row_5 = next(line for line in self.commands("Jest") if line.startswith("| 5 |"))
        for option in ("--ci", "--maxWorkers=2", "--json", "--runTestsByPath"):
            with self.subTest(option):
                self.assertIn(option, row_5)
        row_4 = next(line for line in self.commands("node:test") if line.startswith("| 4 |"))
        for option in ("--test-concurrency=2", "--test-reporter=spec"):
            with self.subTest(option):
                self.assertIn(option, row_4)
        vitest_row_5 = next(line for line in self.commands("Vitest") if line.startswith("| 5 |"))
        for option in ("--maxWorkers=2", "--reporter=verbose"):
            with self.subTest(option):
                self.assertIn(option, vitest_row_5)
        for row, options in (
            (row_5, ("--maxWorkers", "-w", "--runInBand", "-i", "--json", "--outputFile", "--ci")),
            (row_4, ("--test-concurrency", "--test-reporter", "--test-reporter-destination")),
            (vitest_row_5, ("--maxWorkers", "--reporter")),
        ):
            removal = row.split("Remove every ", 1)[1].split(" option", 1)[0]
            self.assertEqual(re.findall(r"`([^`]+)`", removal), list(options))
        for runner in RUNNERS:
            with self.subTest(runner):
                self.assertIn("The commands run with `CI=true` set", "\n".join(self.commands(runner)))
        for path in (REVIEW_MD, WRITE_MD):
            for reporter in ("--reporter=verbose", "Jest: `--json`", "--test-reporter=spec"):
                with self.subTest(path=path, reporter=reporter):
                    self.assertIn(reporter, read(path))

    def test_the_runner_gate_sentence_is_in_the_entry_once_and_names_the_three_runners(self):
        self.assertEqual(self.text.count(GATE_SENTENCE), 1)
        notes = "\n".join(section(self.text, "## Detection notes"))
        self.assertIn(GATE_SENTENCE, notes)
        gate = next(line for line in notes.splitlines() if GATE_SENTENCE in line)
        for runner in ("`vitest`", "`jest`", "`node:test`"):
            with self.subTest(runner):
                self.assertIn(runner, gate)

    def test_every_runner_fact_is_confirmed_with_a_link_of_its_runner_or_unconfirmed_and_unused(self):
        runner, count = None, 0
        for line in section(self.text, "## Runner facts"):
            if line.startswith("### "):
                runner = line[4:].strip()
            if not line.startswith("- "):
                continue
            count += 1
            body = line[2:]
            with self.subTest(line[:60]):
                self.assertTrue(body.startswith("Confirmed:") or body.startswith("Unconfirmed, not used:"))
                if body.startswith("Confirmed:"):
                    self.assertIn(DOCS[runner], body)
                else:
                    self.assertNotIn("https://", body)
        self.assertGreater(count, 30)

    def test_each_runner_has_an_unconfirmed_bullet(self):
        part = {runner: "\n".join(runner_part(section(self.text, "## Runner facts"), runner)) for runner in RUNNERS}
        for runner in RUNNERS:
            with self.subTest(runner):
                self.assertIn("- Unconfirmed, not used:", part[runner])

    def test_the_list_reporter_workers_retry_and_update_facts_link_their_pages(self):
        facts = {line[2:] for line in section(self.text, "## Runner facts") if line.startswith("- ")}
        pages = {
            "Confirmed: `vitest list`": "https://vitest.dev/guide/cli",
            "Confirmed: Reporters": "https://vitest.dev/guide/reporters",
            "Confirmed: Options that the group reader names": "https://vitest.dev/config/maxworkers",
            "Confirmed: `retry`": "https://vitest.dev/config/retry",
            "Confirmed: `update` modes": "https://vitest.dev/config/update",
            "Confirmed: `--listTests`": "https://jestjs.io/docs/cli",
            "Confirmed: `--ci`": "https://jestjs.io/docs/snapshot-testing",
            "Confirmed: `--json`": "https://jestjs.io/docs/cli",
            "Confirmed: `jest.retryTimes": "https://jestjs.io/docs/jest-object",
            "Confirmed: `--test-reporter`": "https://nodejs.org/api/test.html",
            "Confirmed: `--test-concurrency`": "https://nodejs.org/api/cli.html",
            "Confirmed: `--test-update-snapshots`": "https://nodejs.org/api/test.html",
        }
        for start, page in pages.items():
            with self.subTest(start):
                matching = [f for f in facts if f.startswith(start)]
                self.assertEqual(len(matching), 1)
                self.assertIn(page, matching[0])

    def test_the_node_test_facts_record_no_confirmed_list_command(self):
        facts = [line[2:] for line in runner_part(section(self.text, "## Runner facts"), "node:test") if line.startswith("- ")]
        self.assertFalse([f for f in facts if f.startswith("Confirmed:") and "list command" in f])
        unconfirmed = next(f for f in facts if f.startswith("Unconfirmed, not used:"))
        self.assertIn("a `node:test` list command", unconfirmed)
        self.assertIn("no `node:test` list command", "\n".join(self.commands("node:test")))

    def test_an_unconfirmed_form_is_not_used_outside_the_runner_facts_section(self):
        outside = "\n".join(
            line for heading in TS_SECTIONS if heading != "## Runner facts" for line in section(self.text, heading)
        )
        for phrase in ("fail-on-retry", "does not type-check", "no-watch form", "--watch=false is not"):
            with self.subTest(phrase):
                self.assertNotIn(phrase, outside)
        jest_dbl = "\n".join(line for line in outside.splitlines() if line.startswith("- Jest:") and "toHaveBeenNthCalledWith" in line)
        self.assertTrue(jest_dbl)
        for phrase in ("toHaveBeenCalledBefore", "toHaveBeenCalledAfter", "invocationCallOrder"):
            with self.subTest(phrase):
                self.assertNotIn(phrase, jest_dbl)
        self.assertNotIn("--colors", self.text)
        self.assertNotIn("module registry", self.text)

    def test_the_entry_holds_no_private_name_and_only_the_three_doc_prefixes(self):
        for name in PRIVATE_NAMES:
            self.assertNotIn(name, self.text.lower())
        for url in re.findall(r"https?://[^\s)`]+", self.text):
            with self.subTest(url):
                self.assertTrue(url.startswith(tuple(DOCS.values())))
        for url in re.findall(r"\(/docs/[^)\s]*\)", self.text):
            self.fail(f"relative Jest link: {url}")

    def test_each_table_row_and_class_is_the_expected_mark_of_at_least_one_example(self):
        ts_01 = self.ts_01()
        tables = {
            "Table 1": self.commands("Vitest"),
            "Table J1": self.commands("Jest"),
            "Table N1": self.commands("node:test"),
            "Table 3": self.layout("Vitest"),
            "Table J3": self.layout("Jest"),
            "Table N3": self.layout("node:test"),
            "Table 4": labelled_table(ts_01, "Table 4 (Vitest):"),
            "Table J4": labelled_table(ts_01, "Table J4 (Jest):"),
            "Table N4": labelled_table(ts_01, "Table N4 (`node:test`):"),
        }
        for name, lines in tables.items():
            with self.subTest(name):
                rows = table_rows(lines)
                self.assertTrue(rows)
                examples = example_marks(lines)
                self.assertEqual(sorted(set(rows)), sorted({m for m in examples if m.isdigit()}))
        for runner in RUNNERS:
            with self.subTest("classes", runner=runner):
                lines = self.commands(runner)
                classes = table_classes(lines, "Class")
                self.assertEqual(sorted(set(classes)), sorted({m for m in example_marks(lines) if not m.isdigit()}))
        self.assertEqual(
            table_classes(self.commands("Jest"), "Class"), ["Path operand", "Project", "Name filter", "Fixed", "Unreadable"]
        )
        self.assertEqual(
            table_classes(self.commands("node:test"), "Class"), ["Path operand", "Name filter", "Fixed", "Unreadable"]
        )

    def test_each_command_example_has_exactly_the_expected_row_or_class(self):
        ts_01 = self.ts_01()
        parts = (
            ("vitest", self.commands("Vitest"), labelled_table(ts_01, "Table 4 (Vitest):")),
            ("jest", self.commands("Jest"), labelled_table(ts_01, "Table J4 (Jest):")),
            ("node:test", self.commands("node:test"), labelled_table(ts_01, "Table N4 (`node:test`):")),
        )
        for runner, commands, verdicts in parts:
            for line in commands:
                parsed = parse_command_example(line)
                if parsed is None:
                    continue
                command, scripts, mark = parsed
                with self.subTest(line):
                    if mark.isdigit():
                        self.assertEqual(str(table_1_row(command, scripts, runner)), mark)
                    else:
                        self.assertEqual(token_classes(command, runner), {mark})
            for line in verdicts:
                parsed = parse_command_example(line)
                if parsed is None:
                    continue
                command, scripts, mark = parsed
                with self.subTest(line):
                    self.assertEqual(str(table_4_row(command, scripts, runner)), mark)

    def test_the_table_examples_cover_the_wrapper_forms_of_requirement_c_for_each_runner(self):
        scripts = {"Vitest": "vitest run && tsc", "Jest": "jest && tsc", "node:test": "node --test && tsc"}
        for runner in RUNNERS:
            with self.subTest(runner):
                commands = "\n".join(self.commands(runner))
                self.assertIn("with no such script => row 2", commands)
                self.assertIn("with the script `npm run ci` => row 2", commands)
                self.assertIn(f"with the script `{scripts[runner]}`", commands)

    def test_the_table_classifiers_on_samples(self):
        self.assertEqual(table_1_row("npx vitest run", {}), 5)
        self.assertEqual(table_1_row("pnpm exec vitest run -u", {}), 1)
        self.assertEqual(table_1_row("vitest", {}), 2)
        self.assertEqual(table_1_row("npm test", {"test": "vitest"}), 3)
        self.assertEqual(table_1_row("npm test", {"test": "vitest run --update=none"}), 5)
        self.assertEqual(table_1_row("npm test", {}), 2)
        self.assertEqual(table_4_row("npx vitest run --watch", {}), 3)
        self.assertEqual(table_4_row("npx vitest list --watch", {}), 2)
        self.assertEqual(token_classes("npx vitest run -t slow src/a"), {"Name filter", "Path operand"})

    def test_the_jest_classifiers_on_samples(self):
        self.assertEqual(table_1_row("npx jest --ci", {}, "jest"), 5)
        self.assertEqual(table_1_row("yarn jest -u", {}, "jest"), 1)
        self.assertEqual(table_1_row("jest --ci", {}, "jest"), 2)
        self.assertEqual(table_1_row("npm test", {"test": "jest --ci"}, "jest"), 5)
        self.assertEqual(table_1_row("npx jest --watch --listTests", {}, "jest"), 3)
        self.assertEqual(table_4_row("npx jest --watch --listTests", {}, "jest"), 2)
        for command in ("npx jest --watch=false", "npx jest --no-watch", "npx jest -w 2", "npx jest --maxWorkers=2"):
            with self.subTest(command):
                self.assertEqual(table_4_row(command, {}, "jest"), 4)
        for command in ("npx jest --watch", "npx jest --watchAll", "npx jest --watchAll=false", "npx jest --watch=true",
                        "npx jest --watch --watch=false"):
            with self.subTest(command):
                self.assertEqual(table_4_row(command, {}, "jest"), 3)
        self.assertEqual(table_1_row("npx jest --updateSnapshot=false", {}, "jest"), 5)
        self.assertEqual(table_1_row("npx jest --updateSnapshot=true", {}, "jest"), 1)
        self.assertEqual(table_4_row("npx jest -u", {}, "jest"), 4)
        self.assertEqual(token_classes("npx jest -w 2", "jest"), {"Fixed"})
        self.assertEqual(token_classes("npx jest --selectProjects a b --testPathPatterns src/x", "jest"), {"Project", "Path operand"})
        self.assertEqual(token_classes("npx jest --selectProjects a src/x", "jest"), {"Project"})
        self.assertEqual(token_classes("npx jest /abs/path", "jest"), {"Unreadable"})

    def test_the_node_test_classifiers_on_samples(self):
        self.assertEqual(table_1_row("node --test", {}, "node:test"), 4)
        self.assertEqual(table_1_row("node --import tsx --test tests", {}, "node:test"), 4)
        self.assertEqual(table_1_row("node tests/a.test.js", {}, "node:test"), 2)
        self.assertEqual(table_1_row("node --test --test-update-snapshots", {}, "node:test"), 1)
        self.assertEqual(table_1_row("node --test --watch", {}, "node:test"), 3)
        self.assertEqual(table_4_row("node --test --watch-path src", {}, "node:test"), 2)
        self.assertEqual(table_4_row("node tests/a.test.js", {}, "node:test"), 1)
        self.assertEqual(table_4_row("node --test --test-update-snapshots", {}, "node:test"), 3)
        self.assertEqual(token_classes("node --test --test-name-pattern x tests", "node:test"), {"Name filter", "Path operand"})
        self.assertEqual(token_classes("node --test --test-shard=1/2", "node:test"), {"Unreadable"})

    def test_the_output_matchers_on_documented_samples(self):
        jest_output = json.loads(
            '{"testResults": [{"name": "/work/src/a.test.ts", "assertionResults": ['
            '{"fullName": "a adds", "duration": 12}, {"fullName": "a skips", "duration": null}]}]}'
        )
        self.assertEqual(jest_durations(jest_output), {("/work/src/a.test.ts", "a adds"): 12})
        jest_output["testResults"][0]["assertionResults"].append({"fullName": "a adds", "duration": 3})
        self.assertEqual(jest_durations(jest_output), {})
        jest_output["testResults"].append({"name": "/work/src/b.test.ts", "assertionResults": [{"fullName": "a adds", "duration": 4}]})
        self.assertEqual(jest_durations(jest_output), {("/work/src/b.test.ts", "a adds"): 4})
        spec_output = "▶ suite\n  ✔ adds (1.2ms)\n  ✔ adds (0.4ms)\n  ✖ fails (5s)\n✔ suite (7ms)\n"
        self.assertEqual(spec_durations(spec_output), {"suite > fails": 5000.0, "suite": 7.0})
        joined = "▶ outer\n  ▶ inner\n    ✔ adds (2ms)\n  ✔ inner (3ms)\n✔ adds (1ms)\n✔ outer (9ms)\n"
        self.assertEqual(spec_durations(joined), {"outer > inner > adds": 2.0, "outer > inner": 3.0, "adds": 1.0, "outer": 9.0})
        self.assertEqual(spec_durations("✔ adds (1ms)\n✔ adds (2ms)\n"), {})

    def test_the_location_examples_have_the_row_that_the_table_gives(self):
        for runner in RUNNERS:
            with self.subTest(runner):
                examples = [line for line in self.layout(runner) if line.startswith("- Example:") and "=> row" in line]
                self.assertEqual(len(examples), 6)
                for line in examples:
                    self.assertEqual(location_row(line, runner), int(line.rsplit("row ", 1)[1]), line)

    def test_a_quoted_wrapper_marker_is_not_a_wrapper_marker(self):
        self.assertEqual(table_1_row("npx vitest run -t 'a && b'", {}), 5)
        self.assertEqual(table_1_row("npx vitest run && tsc", {}), 2)

    def test_a_flag_with_a_concrete_value_in_an_unconfirmed_bullet_is_not_stated_outside_the_runner_facts(self):
        facts = "\n".join(section(self.text, "## Runner facts"))
        outside = "\n".join(line for heading in TS_SECTIONS if heading != "## Runner facts" for line in section(self.text, heading))
        flags = re.findall(r"`(--[A-Za-z-]+=[a-z]+)`", "\n".join(f for f in facts.splitlines() if f.startswith("- Unconfirmed")))
        self.assertIn("--watchAll=false", flags)
        for flag in flags:
            with self.subTest(flag):
                self.assertNotIn(flag, outside)

    def test_the_hand_run_marker_is_explained_in_the_intro_of_each_runner_with_a_hand_run_fact(self):
        facts = section(self.text, "## Runner facts")
        for runner in ("Jest", "node:test"):
            part = runner_part(facts, runner)
            with self.subTest(runner):
                self.assertTrue(any("(hand-run" in line for line in part if line.startswith("- ")))
                self.assertTrue(any("facts marked `hand-run`" in line for line in part if not line.startswith("- ")))

    def test_the_gate_cases_record_mocha_and_the_write_case_forbids_each_flag_of_the_entry(self):
        for name in ("ts-gate-other-runner", "write-ts-gate-other-runner"):
            rules = read(os.path.join(EVALS, name, "repo", "docs", "agents", "testing.md"))
            with self.subTest(name):
                self.assertIn('name = "mocha"', rules)
        graders = os.path.join(EVALS, "write-ts-gate-other-runner", "graders")
        for flag in ("--maxWorkers", "--reporter"):
            with self.subTest(flag):
                text = read(os.path.join(graders, f"no-{flag[2:].lower()}-flag.md"))
                self.assertIn(f"input_match: '{flag}'", text)
                self.assertIn("max: 0", text)

    def test_the_table_one_extension_lists_equal_the_grader_languages(self):
        typescript = tuple(ext for ext, language in grader_languages().items() if language == "typescript")
        for runner, expected in (
            ("Vitest", sorted(typescript)),
            ("Jest", sorted(typescript)),
            ("node:test", sorted(e for e in typescript if e != ".tsx")),
        ):
            with self.subTest(runner):
                row_1 = next(line for line in self.layout(runner) if line.startswith("| 1 |"))
                listed = tuple(re.findall(r"`(\.[a-z]+)`", row_1.split("|")[2]))
                self.assertEqual(sorted(listed), expected)

    def test_general_md_holds_the_ts_01_rule_text_and_the_catalogue_note_has_no_none_yet(self):
        general = read(GENERAL_MD)
        body = subsection(section(general, "## Rules"), "### TS-01")
        finding = body.split("**Not a finding when**")[0]
        self.assertIn("watch", finding)
        self.assertIn("single-run", finding)
        note = next(line for line in general.splitlines() if line.startswith("The script constant `CATALOG`"))
        self.assertNotIn("none yet", note)

    def test_libraries_holds_runner_text_only_under_a_runner_sub_heading(self):
        lines = section(self.text, "## Libraries")
        before = "\n".join(lines[:lines.index("### Vitest")])
        for phrase in ("vi.", "jest.", "mock.", "CI=true"):
            with self.subTest(phrase):
                self.assertNotIn(phrase, before)

    def test_ts_01_check_details_say_that_the_verdict_tables_ignore_row_1_of_table_1(self):
        body = subsection(section(self.text, "## Rules"), "### TS-01")
        self.assertIn("ignores row 1 of Table 1", body)
        self.assertEqual(table_4_row("npx vitest -u", {}), 6)

    def test_the_design_how_to_names_projects_for_each_runner_and_the_typecheck_sentence(self):
        design = section(self.text, "## Design how-to")
        self.assertEqual(sum("recorded `typecheck` command" in line for line in design), 1)
        self.assertIn("a Jest project is a group", "\n".join(runner_part(design, "Jest")))
        self.assertIn("`node:test` has no project", "\n".join(runner_part(design, "node:test")))

    def test_skill_md_links_the_entry_and_names_the_three_runners(self):
        text = read(SKILL_MD)
        self.assertIn("entries/typescript.md", LINK.findall(text))
        line = next(line for line in text.splitlines() if "entries/typescript.md" in line)
        for runner in ("Vitest", "Jest", "`node:test`"):
            with self.subTest(runner):
                self.assertIn(runner, line)

    def test_review_and_write_hold_the_reporter_watch_form_and_not_checked_phrases(self):
        review, write = read(REVIEW_MD), read(WRITE_MD)
        self.assertEqual(review.count(REPORTER_PHRASE), 1)
        self.assertEqual(write.count(REPORTER_PHRASE), 1)
        self.assertEqual(review.count(WATCH_FORM_PHRASE), 1)
        self.assertEqual(write.count(WATCH_FORM_PHRASE), 1)
        for entry in WRAPPER_ENTRIES:
            with self.subTest(entry):
                self.assertEqual(review.count(entry.strip("`")), 1)
                self.assertEqual(self.text.count(entry.strip("`")), 1)
        for marker in ("`--watchAll`", "`--watch-path`"):
            with self.subTest(marker):
                self.assertEqual(review.count(marker), 1)
                self.assertEqual(write.count(marker), 1)
        self.assertEqual(review.count("arguments that a loaded entry names"), 1)
        self.assertEqual(write.count("arguments that a loaded entry names"), 0)
        step_4 = "\n".join(section(write, "## Step 4: Self-check"))
        self.assertIn("TS-01", step_4)

    def test_the_typescript_eval_cases_exist_with_their_expectations(self):
        cases = case_expectations()
        for name in TS_REVIEW_CASES + TS_WRITE_CASES:
            with self.subTest(name):
                self.assertIn(name, cases)
        self.assertIn("TS-01", cases["ts-01-watch-script"]["expect"])
        self.assertIn("TS-01", cases["ts-01-run-mode"]["forbid"])
        self.assertIn("TS-01", cases["ts-gate-other-runner"]["forbid"])
        self.assertIn("RUN-04", cases["ts-run-04-wrapper-not-checked"]["forbid"])
        self.assertIn("GRP-01", cases["ts-grp-01-not-checked"]["forbid"])
        self.assertIn("GRP-01", cases["ts-grp-01-list-decides"]["expect"])
        for prefix in ("jest", "node"):
            self.assertIn("TS-01", cases[f"{prefix}-01-watch-script"]["expect"])
            self.assertIn("TS-01", cases[f"{prefix}-01-run-mode"]["forbid"])
            self.assertIn("RUN-04", cases[f"{prefix}-run-04-wrapper-not-checked"]["forbid"])
            self.assertIn("GRP-01", cases[f"{prefix}-grp-01-not-checked"]["forbid"])
            self.assertEqual(sorted(cases[f"{prefix}-assert-forms"]["expect"]), ["ASSERT-01", "ASSERT-02"])
            self.assertEqual(
                sorted(cases[f"{prefix}-net-port-skip"]["expect"]), ["DBL-01", "PAR-01", "RUN-03", "RUN-05"]
            )
        self.assertIn("GRP-01", cases["jest-grp-01-list-decides"]["expect"])
        self.assertIn("GRP-01", cases["node-grp-01-readable"]["expect"])

    def test_every_typescript_write_case_ships_an_expectation_file_with_tests(self):
        for name in TS_WRITE_CASES:
            with self.subTest(name):
                data = json.loads(read(os.path.join(EVALS, name, "expect-write.json")))
                self.assertIn("tests", data)

    def test_the_jest_and_node_derived_path_cases_check_the_flags_of_the_entry(self):
        for name, option, in_run in (
            ("write-jest-derived-path", "--maxWorkers=2", ("--ci", "--json")),
            ("write-node-derived-path", "--test-concurrency=2", ("--test-reporter=spec",)),
        ):
            with self.subTest(name):
                data = json.loads(read(os.path.join(EVALS, name, "expect-write.json")))
                self.assertEqual(data["command_contains"], option)
                graders = "\n".join(
                    read(os.path.join(EVALS, name, "graders", file)) for file in os.listdir(os.path.join(EVALS, name, "graders"))
                )
                for flag in in_run:
                    self.assertIn(f"^Command: .*{flag}", graders)

    def test_the_product_edit_graders_match_the_product_files_and_not_the_expected_test_files(self):
        for name in TS_WRITE_CASES:
            graders = os.path.join(EVALS, name, "graders")
            expect = json.loads(read(os.path.join(EVALS, name, "expect-write.json")))
            for grader in ("no-product-edit-write.md", "no-product-edit-edit.md"):
                path = os.path.join(graders, grader)
                if not os.path.exists(path):
                    continue
                pattern = re.search(r"^input_match: '(.*)'$", read(path), re.MULTILINE).group(1)
                for test in expect["tests"]:
                    with self.subTest(case=name, grader=grader, test=test):
                        self.assertIsNone(re.search(pattern, f'{{"file_path": "/work/{test}"}}'))
                for product in expect.get("product", []):
                    with self.subTest(case=name, grader=grader, product=product):
                        self.assertIsNotNone(re.search(pattern, f'{{"file_path": "/work/{product}"}}'))

    def test_the_mixed_case_prompts_name_files_that_the_fixture_holds(self):
        for case in ("write-mixed-rust-ts", "write-mixed-rust-node"):
            base = os.path.join(EVALS, case)
            prompt = read(os.path.join(base, "prompt.md"))
            for path in re.findall(r"\b[\w./-]+\.(?:rs|ts)\b", prompt):
                with self.subTest(case=case, path=path):
                    self.assertTrue(os.path.isfile(os.path.join(base, "repo", path)))

    def test_the_typescript_eval_cases_hold_no_private_name(self):
        for name in TS_REVIEW_CASES + TS_WRITE_CASES:
            base = os.path.join(EVALS, name)
            for folder, _, files in os.walk(base):
                if "node_modules" in folder:
                    continue
                for file in files:
                    with self.subTest(case=name, file=file):
                        text = read(os.path.join(folder, file)).lower()
                        for private in PRIVATE_NAMES:
                            self.assertNotIn(private, text)

    def test_the_gate_other_runner_cases_record_a_runner_that_the_entry_does_not_cover(self):
        for name in ("ts-gate-other-runner", "write-ts-gate-other-runner"):
            with self.subTest(name):
                rules = read(os.path.join(EVALS, name, "repo", "docs", "agents", "testing.md"))
                self.assertIn("mocha", rules)
                self.assertNotIn('"jest"', rules)
                self.assertNotIn("npx jest", rules)

    def test_the_wrapper_group_of_each_not_checked_case_resolves_to_a_wrapper(self):
        for name in ("jest-grp-01-not-checked", "node-grp-01-not-checked"):
            with self.subTest(name):
                scripts = json.loads(read(os.path.join(EVALS, name, "repo", "package.json")))["scripts"]
                self.assertTrue(any(marker in scripts["unit"] for marker in WRAPPER_MARKERS))

    def test_the_evals_readme_allows_the_jest_run_commands(self):
        readme = read(os.path.join(EVALS, "README.md"))
        self.assertIn("Bash(npx jest*)", readme)
        self.assertIn("Bash(CI=true npx jest*)", readme)

    def test_the_install_note_matches_the_scaffolds_of_the_jest_and_node_cases(self):
        self.assertIn("The `node-*` and `write-node-*` cases use `node --test` and need no install", read(os.path.join(EVALS, "README.md")))
        for name in sorted(os.listdir(EVALS)):
            if name.startswith(("jest-", "write-jest-", "node-", "write-node-")):
                installs = "npm install" in read(os.path.join(EVALS, name, "scaffold.sh"))
                with self.subTest(name):
                    self.assertEqual(installs, "jest" in name)

    def test_sample_example_parser(self):
        self.assertEqual(example_marks(["- Example: `a b` => row 3", "- Example: `x` => class Fixed", "text"]), ["3", "Fixed"])
        self.assertEqual(table_rows(["| 1 | a | b |", "| # | x |", "| 12 | z |"]), ["1", "12"])


if __name__ == "__main__":
    unittest.main()
