"""Structure tests for ticket 923: the router engine step, the general part of optimize.md and the general eval cases."""
import json
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
ROUTER = os.path.join(SKILL_DIR, "SKILL.md")
OPTIMIZE = os.path.join(SKILL_DIR, "optimize.md")
GENERAL = os.path.join(SKILL_DIR, "dialects", "general.md")
EVALS = os.path.join(SKILL_DIR, "evals")
README = os.path.join(EVALS, "README.md")

FALLBACK_SENTENCE = ("General guidance: this repo uses <Engine>, which the skill does not cover. "
                     "The advice is general, with no database and no rule script.")
CASES = ("general-opt-mysql", "general-opt-mixed")
TOOL_GRADERS = ("no-connection.md", "no-edit.md", "no-write.md", "no-shell-write.md")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def section(text, heading):
    match = re.search(rf"(?ms)^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text)
    assert match, f"no section {heading}"
    return match.group(1)


def squash(text):
    return " ".join(text.split())


class RouterEngineStepTest(unittest.TestCase):
    def setUp(self):
        self.text = read(ROUTER)
        self.step = squash(section(self.text, "Engine step"))

    def test_the_step_runs_the_script_with_file_and_request(self):
        self.assertIn("scripts/detect_engine.py <repo root> --file <path> [--request <engine name>]", self.step)
        self.assertRegex(self.step, r"(?i)pass `--request` only when the user's request names an engine")

    def test_it_asks_one_question_only_when_ask_is_not_null_and_writes_nothing(self):
        self.assertRegex(self.step, r"`ask` is not null")
        self.assertIn("ask one question", self.step)
        self.assertIn("in this run only", self.step)
        self.assertIn("The skill writes it nowhere", self.step)

    def test_no_signal_keeps_postgresql(self):
        self.assertIn("`default`", self.step)
        self.assertIn("same report as before", self.step)

    def test_it_holds_the_exact_fallback_sentence(self):
        self.assertIn(FALLBACK_SENTENCE, self.text)

    def test_it_loads_each_dialect_module_by_the_engine(self):
        self.assertIn("[dialects/general.md](dialects/general.md)", self.step)
        self.assertIn("[dialects/postgres.md](dialects/postgres.md)", self.step)

    def test_the_router_no_longer_says_that_postgresql_is_the_only_dialect(self):
        self.assertNotIn("PostgreSQL is the only dialect", self.text)

    def test_a_fallback_file_skips_the_extractor_and_the_source_modules_for_every_file_form(self):
        body = squash(section(self.text, "Source module"))
        self.assertIn("A fallback file skips it", body)
        self.assertIn("run no extractor", body.lower())
        self.assertIn("load no source module", body.lower())
        self.assertIn("every file form", body)
        self.assertRegex(body, r"\"not supported\" rule below applies to PostgreSQL files only")

    def test_the_layers_table_names_the_engine_step_the_fallback_sentence_and_the_general_module(self):
        layers = section(self.text, "Layers")
        self.assertIn("`scripts/detect_engine.py` (the engine step)", layers)
        self.assertIn("fallback sentence", layers)
        self.assertRegex(layers, r"\| \[dialects/general\.md\]\(dialects/general\.md\) \|")
        self.assertRegex(layers, r"\| \[dialects/postgres\.md\]\(dialects/postgres\.md\) \|")
        self.assertIn("can load two source modules", squash(layers))

    def test_the_optimize_entry_names_the_engine_step(self):
        line = next(l for l in self.text.splitlines() if l.startswith("- `/sql optimize`"))
        self.assertIn("engine step", line)

    def test_the_format_entry_is_not_changed(self):
        line = next(l for l in self.text.splitlines() if l.startswith("- `/sql format`"))
        self.assertEqual(line, "- `/sql format`: load [format.md](format.md) and [style.md](style.md).")


class OptimizeGeneralPartTest(unittest.TestCase):
    def setUp(self):
        self.text = read(OPTIMIZE)
        self.part = squash(section(self.text, "General part"))
        self.raw = section(self.text, "General part")

    def test_the_form_has_the_title_the_last_line_and_the_result_line(self):
        for needle in (
            "`# sql optimize (general): <scope>`", "`The skill edits no file in general mode.`",
            "`**Result: N critical, N required, N suggestions.**`", "the fallback sentence of the router",
            "`## Critical`, `## Required`, `## Suggestions`",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.part)

    def test_it_has_no_approve_no_rewrite_no_database_path_and_no_plan_finding(self):
        self.assertIn("no `## Approve` section, no rewrite, no Database path and no `PLAN-*` finding", self.part)
        self.assertIn("never holds the capitalised word `Rewrite`", self.part)

    def test_the_rule_cell_holds_the_id_and_the_source(self):
        self.assertIn("`GEN-08 (SQLFluff)`", self.part)
        self.assertIn("`GEN-01 (skill rule)`", self.part)
        self.assertIn("`GEN-11 (OWASP SQL Injection Prevention Cheat Sheet)`", self.part)

    def test_the_example_sources_are_the_sources_of_the_module(self):
        module = read(GENERAL)
        for source in re.findall(r"`GEN-\d\d \((.+?)\)`", self.part):
            with self.subTest(source=source):
                self.assertTrue(source == "skill rule" or f"- **{source}:**" in module, source)

    def test_the_example_ids_have_the_source_that_the_example_shows(self):
        module = read(GENERAL)
        for rule, source in re.findall(r"`(GEN-\d\d) \((.+?)\)`", self.part):
            body = re.search(rf"(?ms)^### {rule}\n(.*?)(?=^### |^## )", module).group(1)
            with self.subTest(rule=rule):
                self.assertIn(f"- **Source:** {source}", body)

    def test_the_title_rule_is_changed_for_a_general_part_and_the_mixed_reply(self):
        report = squash(section(self.text, "Report"))
        self.assertIn("In a PostgreSQL report, write no text before the title line", report)
        self.assertIn("has one line before its title, the fallback sentence", report)
        self.assertIn("The PostgreSQL part starts at its own title line `# sql optimize: <scope>`", self.part)
        self.assertIn("The only text before the PostgreSQL title is the general part", self.part)
        self.assertIn("general part first, and then the PostgreSQL report in full", self.part)
        self.assertIn("Each part has its own title and its own Result line", self.part)
        self.assertIn("`## Approve` is the last section of the reply", self.part)

    def test_the_steps_run_the_extractor_and_the_database_for_postgresql_files_only(self):
        steps = squash(section(self.text, "Steps"))
        self.assertIn("Steps 2 to 5 below run for each PostgreSQL file", steps)
        self.assertIn("A fallback file (any other engine) runs none of steps 2 to 5", steps)

    def test_the_general_part_names_no_database_call(self):
        self.assertNotRegex(self.raw, r"\bpg_run\b")
        self.assertNotRegex(self.raw, r"\bpsql\b")

    def test_the_where_cell_covers_several_places_and_pasted_sql(self):
        self.assertIn("lists every place", self.part)
        self.assertIn("the path is `query`", self.part)


class GeneralCaseFilesTest(unittest.TestCase):
    def case(self, name):
        return os.path.join(EVALS, name)

    def test_each_case_has_its_files(self):
        for name in CASES:
            with self.subTest(case=name):
                for entry in ("case.yaml", "scaffold.sh", "expect.json", "repo", "graders"):
                    self.assertTrue(os.path.exists(os.path.join(self.case(name), entry)), entry)

    def test_the_case_names_do_not_start_with_opt(self):
        for name in CASES:
            self.assertFalse(name.startswith("opt-"))

    def test_the_case_yaml_is_named_by_its_folder_and_the_prompt_names_no_rule_id(self):
        for name in CASES:
            with self.subTest(case=name):
                text = read(os.path.join(self.case(name), "case.yaml"))
                self.assertRegex(text, rf"(?m)^name: {name}$")
                self.assertIn("prompt: |", text)
                self.assertNotRegex(text, r"\b(?:GEN|PG|PGJS|PGN)-\d\d\b")

    def test_the_expect_json_has_the_report_key_and_the_ids(self):
        mysql = json.loads(read(os.path.join(self.case("general-opt-mysql"), "expect.json")))
        self.assertEqual(mysql["report"], "general")
        self.assertEqual(mysql["expect"], ["GEN-08"])
        self.assertIn("PG-08", mysql["forbid"])
        mixed = json.loads(read(os.path.join(self.case("general-opt-mixed"), "expect.json")))
        self.assertEqual(mixed["report"], "mixed")
        self.assertEqual(mixed["expect"], ["GEN-08", "PG-08"])

    def test_the_expect_and_forbid_graders_use_the_patterns_of_the_spec(self):
        for name in CASES:
            expect = json.loads(read(os.path.join(self.case(name), "expect.json")))
            for kind in ("expect", "forbid"):
                for rule in expect[kind]:
                    path = os.path.join(self.case(name), "graders", f"{kind}-{rule}.md")
                    with self.subTest(case=name, grader=f"{kind}-{rule}"):
                        text = read(path)
                        if rule.startswith("GEN-"):
                            pattern = rf"^\|\s*\d+\s*\|\s*{rule} \("
                        else:
                            pattern = rf"^\|\s*\d+\s*\|\s*{rule}\s*\|"
                        self.assertIn("type: regex", text)
                        self.assertIn(f"pattern: '{pattern}'", text)

    def test_the_graders_equal_the_expect_json_plus_the_tool_graders(self):
        for name in CASES:
            expect = json.loads(read(os.path.join(self.case(name), "expect.json")))
            wanted = {f"{kind}-{rule}.md" for kind in ("expect", "forbid") for rule in expect[kind]}
            wanted |= set(TOOL_GRADERS)
            wanted.add("fallback-sentence.md")
            if name == "general-opt-mysql":
                wanted.add("no-extractor.md")
            with self.subTest(case=name):
                self.assertEqual(set(os.listdir(os.path.join(self.case(name), "graders"))), wanted)

    def test_the_no_extractor_grader_is_a_bash_grader_with_a_zero_maximum(self):
        text = read(os.path.join(self.case("general-opt-mysql"), "graders", "no-extractor.md"))
        for needle in ("type: tool_used", "tool: Bash", "input_match: 'extract\\.py'", "min: 0", "max: 0"):
            self.assertIn(needle, text)

    def test_the_fallback_sentence_grader_checks_line_one(self):
        for name in CASES:
            text = read(os.path.join(self.case(name), "graders", "fallback-sentence.md"))
            with self.subTest(case=name):
                self.assertIn("type: regex", text)
                self.assertIn("General guidance: this repo uses", text)

    def test_the_mixed_case_has_no_extractor_grader(self):
        self.assertFalse(os.path.exists(os.path.join(self.case("general-opt-mixed"), "graders", "no-extractor.md")))

    def test_the_fixtures_are_the_synthetic_files_of_the_spec(self):
        mysql = self.case("general-opt-mysql")
        self.assertIn("mysql2", read(os.path.join(mysql, "repo", "package.json")))
        self.assertIn("SELECT * FROM users WHERE id = ?", read(os.path.join(mysql, "repo", "src", "reports.ts")))
        mixed = self.case("general-opt-mixed")
        package = read(os.path.join(mixed, "repo", "package.json"))
        self.assertIn("mysql2", package)
        self.assertIn('"postgres"', package)
        self.assertIn("mysql2", read(os.path.join(mixed, "repo", "src", "reports.ts")))
        self.assertIn("postgres", read(os.path.join(mixed, "repo", "src", "profile.ts")))

    def test_each_scaffold_copies_the_repo_into_the_working_folder(self):
        for name in CASES:
            with self.subTest(case=name):
                text = read(os.path.join(self.case(name), "scaffold.sh"))
                self.assertIn('cp -R "$(dirname "$0")/repo/." .', text)

    def test_no_fixture_is_a_python_test_file(self):
        for name in CASES:
            for folder, _, names in os.walk(self.case(name)):
                for file in names:
                    self.assertNotRegex(file, r"^test_.*\.py$")

    def test_the_readme_has_a_row_for_each_case_and_names_the_grader_flags(self):
        text = read(README)
        for name in CASES:
            with self.subTest(case=name):
                self.assertRegex(text, rf"(?m)^\| `{name}` \|")
        for needle in ("--general", "--mixed", "`report`"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
