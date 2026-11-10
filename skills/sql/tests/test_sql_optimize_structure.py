import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(SKILL_DIR))
EVALS = os.path.join(SKILL_DIR, "evals")
OPTIMIZE = os.path.join(SKILL_DIR, "optimize.md")
DIALECT = os.path.join(SKILL_DIR, "dialects", "postgres.md")
SOURCE = os.path.join(SKILL_DIR, "sources", "postgres-js.md")
ROUTER = os.path.join(SKILL_DIR, "SKILL.md")
README = os.path.join(REPO, "README.md")

# The catalog of the ticket (severities of the general spec).
SEVERITIES = {
    "PGJS-01": "critical", "PGJS-02": "required", "PGJS-03": "critical", "PGJS-04": "critical",
    "PG-01": "critical", "PG-02": "critical", "PG-03": "required", "PG-04": "required",
    "PG-05": "suggestion", "PG-06": "suggestion", "PG-07": "suggestion",
    "PG-08": "suggestion", "PG-09": "suggestion", "PG-10": "suggestion",
}
FIELDS = ["Title", "Severity", "Detects", "Why it matters", "Fix", "Example"]
NO_ID_CRITICAL_REQUIRED = [rule for rule, level in SEVERITIES.items() if level in ("critical", "required")]
TOOL_GRADERS = {
    "no-connection.md": ("Bash", "psql|pg_run|PGSERVICE|service="),
    "no-edit.md": ("Edit", None),
    "no-write.md": ("Write", None),
    "no-shell-write.md": (
        "Bash",
        r"\bsed\s+-i|\b(?:tee|mv|cp|rm|patch)\b|(?<!&)>>?(?!&)\s*(?!/dev/null)\S|&>>?\s*(?!/dev/null)\S",
    ),
}


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def frontmatter(text):
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match, "no frontmatter"
    return match.group(1)


def key(head, name):
    match = re.search(rf"(?m)^{re.escape(name)}: (.*)$", head)
    return match.group(1) if match else None


def unquote(value):
    if value is not None and len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def section(text, heading):
    match = re.search(rf"^## {re.escape(heading)}$", text, re.M)
    assert match, f"no section {heading}"
    return text[match.end():].split("\n## ", 1)[0]


def entries(path):
    """The rule entries under `## Rules`: id -> list of (field, text) in order, and the heading ids in order."""
    body = section(read(path), "Rules")
    result, order = {}, []
    for block in re.split(r"(?m)^### ", body)[1:]:
        rule_id, _, rest = block.partition("\n")
        rule_id = rule_id.strip()
        order.append(rule_id)
        found = re.findall(r"(?m)^- \*\*([^*]+):\*\* ?(.*)$", rest)
        result[rule_id] = found
    return result, order


def catalog_ids():
    """The PGJS-* and PG-* ids of CATALOG in scripts/rules_file.py, read through the reader command line."""
    candidates = [f"PGJS-{n:02d}" for n in range(100)] + [f"PG-{n:02d}" for n in range(100)]
    toml = "[rules]\ndisabled = [" + ", ".join(f'"{c}"' for c in candidates) + "]\n"
    with tempfile.TemporaryDirectory() as repo:
        os.makedirs(os.path.join(repo, "docs", "agents"))
        with open(os.path.join(repo, "docs", "agents", "sql.md"), "w", encoding="utf-8") as handle:
            handle.write("# SQL rules\n\n```toml\n" + toml + "```\n")
        proc = subprocess.run(
            [sys.executable, os.path.join(SKILL_DIR, "scripts", "rules_file.py"), repo],
            capture_output=True, text=True, check=True,
        )
    return json.loads(proc.stdout)["disabled_without_reason"]


def case_folders():
    return sorted(
        name for name in os.listdir(EVALS)
        if name.startswith("opt-") and os.path.isdir(os.path.join(EVALS, name))
    )


class CatalogTest(unittest.TestCase):
    def test_each_module_holds_its_ids_in_order_with_all_fields(self):
        for path, prefix in ((DIALECT, "PG-"), (SOURCE, "PGJS-")):
            with self.subTest(module=os.path.basename(path)):
                found, order = entries(path)
                self.assertEqual(len(order), len(set(order)), "duplicate id")
                for rule_id in order:
                    self.assertRegex(rule_id, rf"^{re.escape(prefix)}\d\d$")
                for rule_id, fields in found.items():
                    self.assertEqual([name for name, _ in fields], FIELDS, rule_id)
                    self.assertTrue(all(text.strip() for _, text in fields), rule_id)

    def test_the_ids_equal_the_catalog_of_the_reader(self):
        catalog = catalog_ids()
        _, dialect = entries(DIALECT)
        _, source = entries(SOURCE)
        self.assertEqual(sorted(dialect), sorted(i for i in catalog if i.startswith("PG-")))
        self.assertEqual(sorted(source), sorted(i for i in catalog if i.startswith("PGJS-")))
        self.assertEqual(sorted(dialect + source), sorted(SEVERITIES))

    def test_each_severity_is_the_catalog_severity(self):
        for path in (DIALECT, SOURCE):
            found, _ = entries(path)
            for rule_id, fields in found.items():
                with self.subTest(rule=rule_id):
                    severity = dict(fields)["Severity"]
                    self.assertTrue(severity.startswith(SEVERITIES[rule_id]), severity)

    def test_each_example_has_a_bad_and_a_good_fenced_form(self):
        for path in (DIALECT, SOURCE):
            body = section(read(path), "Rules")
            for block in re.split(r"(?m)^### ", body)[1:]:
                rule_id = block.split("\n", 1)[0].strip()
                with self.subTest(rule=rule_id):
                    example = block.split("**Example:**", 1)[1]
                    self.assertGreaterEqual(example.count("```") // 2, 2, "two fenced forms")
                    self.assertRegex(example, r"(?i)bad")
                    self.assertRegex(example, r"(?i)good")

    def test_the_fact_rules_name_their_fact(self):
        source, _ = entries(SOURCE)
        dialect, _ = entries(DIALECT)
        self.assertRegex(dict(source["PGJS-02"])["Detects"], r"(?i)only when the repo shows")
        self.assertRegex(dict(dialect["PG-02"])["Detects"], r"(?i)only when the repo shows")

    def test_the_pg_09_fix_gives_replacement_sql(self):
        dialect, _ = entries(DIALECT)
        self.assertRegex(dict(dialect["PG-09"])["Fix"], r"(?i)join")

    def test_the_pg_09_good_example_keeps_the_zero_count_of_the_bad_one(self):
        # A LEFT JOIN to a grouped count gives NULL, not 0, for a row with no match.
        body = section(read(DIALECT), "Rules")
        example = body.split("### PG-09", 1)[1].split("### PG-10", 1)[0]
        good = example.split("Good:", 1)[1]
        self.assertRegex(good, r"(?i)coalesce\(")
        self.assertRegex(dict(entries(DIALECT)[0]["PG-09"])["Fix"], r"(?i)coalesce")

    def test_the_pgjs_02_explanation_says_the_driver_sends_utc(self):
        why = dict(entries(SOURCE)[0]["PGJS-02"])["Why it matters"]
        self.assertRegex(why, r"\bUTC\b")
        self.assertNotRegex(why, r"(?i)time zone of the process")

    def test_the_dialect_module_has_a_plan_reading_section_naming_the_ticket(self):
        plan = section(read(DIALECT), "Plan reading")
        self.assertIn("#395", plan)

    def test_the_source_module_keeps_the_filled_module_rules(self):
        text = read(SOURCE)
        self.assertNotRegex(text, r"(?i)\bstub\b")
        self.assertNotIn("#390", text)
        self.assertNotIn("holds no `PGJS-*` rule yet", text)


class OptimizeModuleTest(unittest.TestCase):
    def setUp(self):
        self.text = read(OPTIMIZE)

    def sentences(self):
        return re.split(r"(?<=[.!?])\s+", " ".join(self.text.split()))

    def has_sentence(self, *words):
        return any(all(word in s for word in words) for s in self.sentences())

    def test_it_holds_the_report_strings(self):
        for needle in (
            "Rewrite (unproven: no database):", "Disabled rules:", "Note:", "There is nothing to approve.",
            "/sql setup", "## Critical", "## Required", "## Suggestions", "## Approve", "database diff",
            "Note: no docs/agents/sql.md found.",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.text)

    def test_it_holds_the_approval_sentences(self):
        self.assertTrue(self.has_sentence("no file"), "no file before the reply")
        self.assertTrue(self.has_sentence("names its number"), "rewrite needs its number")
        self.assertTrue(any("`all`" in s and "does not cover" in s for s in self.sentences()), "all")
        self.assertTrue(self.has_sentence("Fix cell", "capitalised"), "capitalised Rewrite")

    def test_it_names_a_stub_section_for_each_later_ticket(self):
        parts = re.split(r"(?m)^## ", self.text)
        for ticket in ("#395", "#396", "#397", "#400"):
            with self.subTest(ticket=ticket):
                self.assertTrue(
                    any(ticket in part and re.search(r"(?i)stub|later|not yet", part) for part in parts[1:]),
                    ticket,
                )

    def test_it_names_no_database_call(self):
        self.assertNotRegex(self.text, r"\bpsql\b")
        database_path = section(self.text, "Database path")
        self.assertIn("pg_run", database_path)
        self.assertNotRegex(self.text.replace(database_path, ""), r"\bpg_run\b")

    def test_it_never_connects(self):
        self.assertRegex(self.text, r"(?i)never connect|no connection|does not connect")

    def test_the_router_text_stays_free_of_line_formats(self):
        text = read(ROUTER)
        self.assertNotIn("Disabled rules:", text)
        self.assertNotIn("Rewrite (unproven", text)


class CaseFilesTest(unittest.TestCase):
    def test_there_is_a_case_for_each_rule_and_the_special_cases(self):
        cases = case_folders()
        # one case for each rule, two negative fact cases, and the four special cases
        self.assertGreaterEqual(len(cases), len(SEVERITIES) + 2 + 4)
        for name in ("opt-clean", "opt-disabled-rule", "opt-rewrite-unproven", "opt-no-rules-file"):
            self.assertIn(name, cases)

    def test_every_rule_id_is_expected_by_some_case(self):
        expected = set()
        for name in case_folders():
            expected.update(json.loads(read(os.path.join(EVALS, name, "expect.json")))["expect"])
        self.assertEqual(sorted(set(SEVERITIES) - expected), [])

    def test_the_clean_case_forbids_every_critical_and_required_id(self):
        data = json.loads(read(os.path.join(EVALS, "opt-clean", "expect.json")))
        self.assertEqual(sorted(data["forbid"]), sorted(NO_ID_CRITICAL_REQUIRED))
        self.assertEqual(data["expect"], [])

    def test_the_disabled_case_expects_pg_08_forbids_pg_10_and_sets_disabled(self):
        data = json.loads(read(os.path.join(EVALS, "opt-disabled-rule", "expect.json")))
        self.assertEqual(data["expect"], ["PG-08"])
        self.assertEqual(data["forbid"], ["PG-10"])
        self.assertEqual(data["disabled"], ["PG-10"])
        rules = read(os.path.join(EVALS, "opt-disabled-rule", "repo", "docs", "agents", "sql.md"))
        self.assertRegex(rules, r"(?m)^disabled = \[.*\"PG-10\".*\]$")
        self.assertRegex(rules, r"(?m)^- PG-10: \S")

    def test_each_case_folder_has_the_files_and_the_graders_equal_expect_json(self):
        for name in case_folders():
            folder = os.path.join(EVALS, name)
            with self.subTest(case=name):
                for entry in ("case.yaml", "scaffold.sh", "repo", "expect.json", "graders"):
                    self.assertTrue(os.path.exists(os.path.join(folder, entry)), entry)
                data = json.loads(read(os.path.join(folder, "expect.json")))
                self.assertEqual(set(data) - {"disabled"}, {"expect", "forbid"})
                for rule_id in data["expect"] + data["forbid"] + data.get("disabled", []):
                    self.assertIn(rule_id, SEVERITIES)
                graders = os.listdir(os.path.join(folder, "graders"))
                expect_ids = sorted(g[len("expect-"):-3] for g in graders if g.startswith("expect-"))
                forbid_ids = sorted(g[len("forbid-"):-3] for g in graders if g.startswith("forbid-"))
                self.assertEqual(expect_ids, sorted(data["expect"]))
                self.assertEqual(forbid_ids, sorted(data["forbid"]))
                for grader in graders:
                    match = re.match(r"(expect|forbid)-(.+)\.md$", grader)
                    if not match:
                        continue
                    kind, rule_id = match.groups()
                    head = frontmatter(read(os.path.join(folder, "graders", grader)))
                    self.assertEqual(key(head, "type"), "regex")
                    self.assertEqual(key(head, "flags"), "m")
                    self.assertEqual(
                        unquote(key(head, "pattern")), rf"^\|\s*\d+\s*\|\s*{rule_id}\s*\|", grader
                    )
                    self.assertEqual(key(head, "match"), "not_contains" if kind == "forbid" else None)
                for grader, (tool, pattern) in TOOL_GRADERS.items():
                    head = frontmatter(read(os.path.join(folder, "graders", grader)))
                    self.assertEqual(key(head, "type"), "tool_used")
                    self.assertEqual(key(head, "tool"), tool)
                    self.assertEqual(key(head, "min"), "0")
                    self.assertEqual(key(head, "max"), "0")
                    if pattern is not None:
                        self.assertEqual(unquote(key(head, "input_match")), pattern, grader)
                self.assertNotIn("skill-fired.md", graders)

    def test_each_case_yaml_is_named_by_its_folder_and_has_a_prompt_with_no_rule_id(self):
        for name in case_folders():
            case = read(os.path.join(EVALS, name, "case.yaml"))
            with self.subTest(case=name):
                self.assertRegex(case, rf"(?m)^name: {re.escape(name)}$")
                # A plain YAML scalar with a colon and a space does not parse (plugin eval skips the case).
                description = re.search(r"(?m)^description: (.+)$", case).group(1)
                self.assertNotIn(": ", description)
                self.assertRegex(case, r"(?m)^  scaffold_script: scaffold\.sh$")
                self.assertIn("allowed_tools: [Skill, Read, Glob, Grep, Bash]", case)
                self.assertRegex(case, r"(?m)^  max_turns: 20$")
                prompt = case.split("prompt: |", 1)[1]
                self.assertIn("/sql optimize", prompt)
                self.assertRegex(prompt, r"\S+\.(?:ts|js|sql)\b")
                self.assertNotRegex(prompt, r"\bPGJS-\d|\bPG-\d|\bPLAN-\d")

    def test_each_scaffold_copies_the_repo_into_the_working_folder(self):
        for name in case_folders():
            folder = os.path.join(EVALS, name)
            with self.subTest(case=name), tempfile.TemporaryDirectory() as work:
                subprocess.run(
                    ["bash", os.path.join(folder, "scaffold.sh")],
                    cwd=work, check=True, env={"PATH": os.environ["PATH"]},
                )
                for base, _, names in os.walk(os.path.join(folder, "repo")):
                    for file_name in names:
                        source = os.path.join(base, file_name)
                        copied = os.path.join(work, os.path.relpath(source, os.path.join(folder, "repo")))
                        self.assertTrue(os.path.isfile(copied), copied)

    def test_the_rewrite_and_setup_cases_have_their_in_run_graders(self):
        rewrite = os.path.join(EVALS, "opt-rewrite-unproven", "graders")
        self.assertIn("unproven", read(os.path.join(rewrite, "unproven.md")))
        self.assertIn("database diff", read(os.path.join(rewrite, "database-diff.md")))
        setup = read(os.path.join(EVALS, "opt-no-rules-file", "graders", "suggests-setup.md"))
        head = frontmatter(setup)
        self.assertEqual(key(head, "type"), "regex")
        self.assertEqual(unquote(key(head, "pattern")), r"^Note:.*/sql setup")
        self.assertEqual(key(head, "flags"), "m")
        self.assertFalse(os.path.exists(
            os.path.join(EVALS, "opt-no-rules-file", "repo", "docs", "agents", "sql.md")))

    def test_no_fixture_is_a_python_test_file(self):
        for base, _, names in os.walk(EVALS):
            for file_name in names:
                self.assertFalse(re.fullmatch(r"test_.*\.py", file_name), file_name)

    def test_the_old_cases_are_not_touched(self):
        for name in ("trigger-write-query", "extract-tag-not-sql"):
            self.assertTrue(os.path.isdir(os.path.join(EVALS, name)))


class ReadmeTest(unittest.TestCase):
    def test_the_readme_still_holds_the_seven_globs(self):
        text = read(README)
        for glob in (
            "skills/sql/*.md", "skills/sql/dialects/*", "skills/sql/sources/*", "skills/sql/scripts/*",
            "skills/sql/graders/*", "skills/sql/tests/*", "skills/sql/evals/**",
        ):
            with self.subTest(glob=glob):
                self.assertIn(glob, text)

    def test_the_eval_procedure_names_the_cases_the_graders_and_the_run_flags(self):
        text = read(os.path.join(EVALS, "README.md"))
        for needle in (
            "grade_eval_results.py", "--keep-temp", "--json", "--output-dir", "opt-clean", "opt-no-rules-file",
            "grade_rule_ids.py", "grade_no_change.py", "grade_report.py",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
