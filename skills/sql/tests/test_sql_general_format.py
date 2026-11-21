"""Structure tests for ticket 924: the router format entry, the General part of format.md and the general format eval cases."""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
ROUTER = os.path.join(SKILL_DIR, "SKILL.md")
FORMAT = os.path.join(SKILL_DIR, "format.md")
STYLE = os.path.join(SKILL_DIR, "style.md")
EVALS = os.path.join(SKILL_DIR, "evals")
README = os.path.join(EVALS, "README.md")

CASES = ("general-format-mysql", "general-format-mixed")
LAST_LINE = "The skill edits no file in general mode."
MYSQL_GRADERS = {
    "fallback-sentence.md", "title.md", "bullet.md", "last-line.md", "no-connection.md", "no-edit.md",
    "no-write.md", "no-shell-write.md", "no-formatter.md", "no-extractor.md",
}
MIXED_GRADERS = {
    "fallback-sentence.md", "title.md", "general-last-line.md", "postgres-part-form.md",
    "postgres-part-report.md", "no-connection.md", "no-edit-fallback-file.md", "no-write-fallback-file.md",
    "no-shell-write-fallback-file.md",
}


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def section(text, heading):
    match = re.search(rf"(?ms)^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text)
    assert match, f"no section {heading}"
    return match.group(1)


def squash(text):
    return " ".join(text.split())


class RouterFormatEntryTest(unittest.TestCase):
    def setUp(self):
        self.text = read(ROUTER)

    def test_the_format_entry_names_the_engine_step(self):
        line = next(l for l in self.text.splitlines() if l.startswith("- `/sql format`"))
        self.assertIn("engine step", line)
        self.assertIn("[format.md](format.md)", line)
        self.assertIn("[style.md](style.md)", line)

    def test_the_engine_step_text_names_both_modes(self):
        step = squash(section(self.text, "Engine step"))
        self.assertIn("`/sql optimize` and `/sql format` run the engine step once for each file", step)

    def test_the_layers_row_of_the_engine_step_names_format(self):
        row = next(l for l in self.text.splitlines() if l.startswith("| `scripts/detect_engine.py`"))
        self.assertIn("`/sql format`", row)

    def test_a_fallback_file_runs_no_tag_detection_and_no_formatter_detection(self):
        step = squash(section(self.text, "Rules file"))
        self.assertRegex(step, r"PostgreSQL files only: a fallback file runs no tag detection and no formatter detection")


class FormatGeneralPartTest(unittest.TestCase):
    def setUp(self):
        self.text = read(FORMAT)
        self.part = squash(section(self.text, "General part"))

    def test_the_form_has_the_sentence_the_title_the_notes_the_bullets_and_the_last_line(self):
        self.assertIn("Line 1: the fallback sentence of the router", self.part)
        self.assertIn("`# sql format (general): <scope>`", self.part)
        self.assertIn("lines that start with `Note:`", self.part)
        self.assertIn("`- <path>:<line>: <style point>`", self.part)
        self.assertIn("`" + LAST_LINE + "`", self.part)

    def test_the_scope_rule_and_pasted_sql(self):
        self.assertIn("the path of the file that the user named, or the words `the query`", self.part)
        self.assertIn("the path is `query`", self.part)

    def test_it_runs_no_formatter_no_extractor_and_no_write(self):
        for needle in ("runs no formatter and no extractor", "loads no source module", "makes no database call",
                       "edits no file"):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.part)

    def test_the_style_overrides_the_measurer_steps_and_names_the_default_values(self):
        self.assertIn("overrides steps 2 and 3 of the Choose the style section of `style.md`", self.part)
        for value in ("`keyword_case` upper", "`indent` 2 spaces", "`clause_per_line` true", "`comma` trailing",
                      "`alias_as` true"):
            with self.subTest(value=value):
                self.assertIn(value, self.part)
        self.assertIn("named once in a `Note:` line", self.part)

    def test_the_style_keys_are_the_five_general_ones_and_the_template_layout_never_applies(self):
        self.assertIn("Only these five style keys apply: `keyword_case`, `indent`, `clause_per_line`, `comma` and "
                      "`alias_as`", self.part)
        self.assertIn("The template layout never applies", self.part)
        self.assertIn("`${...}`", self.part)

    def test_the_postgresql_only_words_are_left_out_of_the_keyword_and_clause_checks(self):
        self.assertIn("without `ILIKE`, `CONFLICT`, `DO NOTHING` and `RETURNING`", self.part)
        self.assertIn("clause words of `style.md` without `RETURNING`", self.part)
        style = read(STYLE)
        for word in ("ILIKE", "CONFLICT", "DO NOTHING", "RETURNING"):
            with self.subTest(word=word):
                self.assertIn(word, style)

    def test_one_bullet_for_each_key_and_statement_with_the_first_line_of_the_departure(self):
        self.assertIn("A bullet names one style key and one statement", self.part)
        self.assertIn("the first line where that statement departs from the key", self.part)
        self.assertIn("one bullet for each key", self.part)

    def test_no_departure_and_no_statement_give_no_bullet(self):
        self.assertIn("no departure from the style, or a fallback target with no SQL statement, gives no bullet",
                      self.part)

    def test_the_mixed_reply_order(self):
        self.assertIn("the general part first, and then the PostgreSQL format report in full and unchanged",
                      self.part)
        self.assertIn("no new title and no Result line", self.part)
        self.assertIn("keeps every item of its Report section", self.part)
        self.assertIn("A reply with fallback files only has the general part and nothing else", self.part)

    def test_the_setup_suggestion_is_a_note_only_without_a_postgresql_part(self):
        self.assertIn("In a reply with a PostgreSQL part, the `/sql setup` suggestion is not a `Note:` line",
                      self.part)

    def test_the_target_section_limits_the_extractor_to_postgresql_files(self):
        target = squash(section(self.text, "Target"))
        self.assertIn("For a PostgreSQL file, find each statement with the extractor", target)
        self.assertIn("`scripts/extract.py`", target)
        self.assertIn("For a fallback file, read the file as text", target)
        self.assertIn("A diff target always names one file", target)

    def test_the_first_paragraph_names_the_general_part_and_keeps_the_pinned_words(self):
        head = self.text.split("\n## ", 1)[0]
        self.assertIn("safe formatter tool", head)
        self.assertIn("section General part", head)

    def test_the_postgresql_sections_keep_their_text(self):
        # Pins a few words of each PostgreSQL section. The older format tests pin the rest.
        for heading, needle in (("Style", "Choose the style as `style.md` says"), ("Write", "Keep every `${...}` text"),
                                ("pg statements", "scripts/write_back_pg.py"), ("Report", "Formatter: <chosen>"),
                                ("Safe tool path", "scripts/run_formatter.py")):
            with self.subTest(section=heading):
                self.assertIn(needle, section(self.text, heading))


class GeneralFormatCaseFilesTest(unittest.TestCase):
    def case(self, name):
        return os.path.join(EVALS, name)

    def test_each_case_has_its_files_and_no_expected_file(self):
        for name in CASES:
            with self.subTest(case=name):
                for entry in ("case.yaml", "scaffold.sh", "repo", "graders"):
                    self.assertTrue(os.path.exists(os.path.join(self.case(name), entry)), entry)
                for entry in ("expected.json", "expect.json"):
                    self.assertFalse(os.path.exists(os.path.join(self.case(name), entry)), entry)

    def test_the_case_yaml_is_named_by_its_folder_and_allows_edit_and_write(self):
        for name in CASES:
            with self.subTest(case=name):
                text = read(os.path.join(self.case(name), "case.yaml"))
                self.assertIn(f"name: {name}\n", text)
                match = re.search(r"allowed_tools: \[(.*)\]", text)
                self.assertTrue(match)
                tools = {tool.strip() for tool in match.group(1).split(",")}
                self.assertTrue({"Skill", "Bash", "Edit", "Write"} <= tools)

    def test_the_prompt_runs_the_format_mode_and_names_no_rule_or_style_point(self):
        for name, files in (("general-format-mysql", ("src/reports.ts",)),
                            ("general-format-mixed", ("src/reports.ts", "src/profile.ts"))):
            with self.subTest(case=name):
                text = read(os.path.join(self.case(name), "case.yaml"))
                self.assertIn("`/sql format " + " ".join(files) + "`", text)
                self.assertNotRegex(text, r"GEN-\d|keyword_case")

    def test_the_grader_files_of_each_case(self):
        for name, expected in (("general-format-mysql", MYSQL_GRADERS), ("general-format-mixed", MIXED_GRADERS)):
            with self.subTest(case=name):
                found = set(os.listdir(os.path.join(self.case(name), "graders")))
                self.assertEqual(found, expected)

    def test_the_regex_graders_state_the_patterns_of_the_spec(self):
        mysql = os.path.join(self.case("general-format-mysql"), "graders")
        self.assertIn(r"pattern: '^- \S+:\d+: \S'", read(os.path.join(mysql, "bullet.md")))
        self.assertIn(r"# sql format \(general\): \S", read(os.path.join(mysql, "title.md")))
        self.assertIn("The skill edits no file in general mode", read(os.path.join(mysql, "last-line.md")))
        sentence = (r"^General guidance: this repo uses \S.*, which the skill does not cover\. "
                    r"The advice is general, with no database and no rule script\.")
        for name in CASES:
            self.assertIn(sentence, read(os.path.join(self.case(name), "graders", "fallback-sentence.md")))

    def test_the_tool_graders_have_a_zero_maximum(self):
        for name in CASES:
            folder = os.path.join(self.case(name), "graders")
            for grader in sorted(os.listdir(folder)):
                text = read(os.path.join(folder, grader))
                if "type: tool_used" in text:
                    with self.subTest(case=name, grader=grader):
                        self.assertIn("max: 0", text)
                        self.assertIn("min: 0", text)

    def test_the_mixed_graders_name_only_the_fallback_file(self):
        folder = os.path.join(self.case("general-format-mixed"), "graders")
        for grader in ("no-edit-fallback-file.md", "no-write-fallback-file.md", "no-shell-write-fallback-file.md"):
            with self.subTest(grader=grader):
                self.assertIn(r"reports\.ts", read(os.path.join(folder, grader)))
                self.assertNotIn("profile", read(os.path.join(folder, grader)).split("---")[1])

    def test_the_mysql_no_extractor_and_no_formatter_graders(self):
        folder = os.path.join(self.case("general-format-mysql"), "graders")
        self.assertIn(r"input_match: 'extract\.py'", read(os.path.join(folder, "no-extractor.md")))
        self.assertIn("prettier", read(os.path.join(folder, "no-formatter.md")))

    def test_the_fixtures_are_the_synthetic_files_of_the_spec(self):
        mysql = os.path.join(self.case("general-format-mysql"), "repo")
        package = read(os.path.join(mysql, "package.json"))
        self.assertIn('"mysql2"', package)
        reports = read(os.path.join(mysql, "src", "reports.ts"))
        self.assertIn("mysql2", reports)
        self.assertRegex(reports, r"select u\.id, u\.name from users u where")
        rules = read(os.path.join(mysql, "docs", "agents", "sql.md"))
        self.assertIn('keyword_case = "upper"', rules)
        mixed = os.path.join(self.case("general-format-mixed"), "repo")
        package = read(os.path.join(mixed, "package.json"))
        self.assertIn('"mysql2"', package)
        self.assertIn('"postgres"', package)
        self.assertNotIn("[style]", read(os.path.join(mixed, "docs", "agents", "sql.md")))
        profile = read(os.path.join(mixed, "src", "profile.ts"))
        self.assertIn("select * from users where id = ${id}", profile)

    def test_no_fixture_holds_a_real_connection_string(self):
        for name in CASES:
            for root, _dirs, files in os.walk(os.path.join(self.case(name), "repo")):
                for file_name in files:
                    with self.subTest(case=name, file=file_name):
                        self.assertNotRegex(read(os.path.join(root, file_name)), r"://")


class ReadmeFormatRowsTest(unittest.TestCase):
    def setUp(self):
        self.text = read(README)

    def test_the_cases_table_has_a_row_for_each_case(self):
        for name in CASES:
            with self.subTest(case=name):
                self.assertRegex(self.text, rf"(?m)^\| `{re.escape(name)}` \|")

    def test_the_readme_names_the_grader_script_and_the_hand_check(self):
        self.assertIn("grade_format_general.py REPLY (--general | --mixed)", self.text)
        self.assertIn("cmp skills/sql/evals/general-format-mysql/repo/src/reports.ts", self.text)
        self.assertIn("no existing case uses `input_match` on `Edit` or `Write`", self.text)


if __name__ == "__main__":
    unittest.main()
