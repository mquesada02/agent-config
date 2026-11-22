"""Structure tests for ticket 925: the model-invoked path of the router, the skill description and the model-invoked eval case."""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
ROUTER = os.path.join(SKILL_DIR, "SKILL.md")
EVALS = os.path.join(SKILL_DIR, "evals")
README = os.path.join(EVALS, "README.md")
CASE = os.path.join(EVALS, "trigger-write-query-general")

SENTENCE_START = "General guidance: this repo uses"
GRADERS = {
    "skill-fired.md", "fallback-sentence.md", "no-connection.md", "no-formatter.md", "no-extractor.md",
    "no-edit.md", "no-write.md", "no-shell-write.md",
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


class ModelInvokedPathTest(unittest.TestCase):
    def setUp(self):
        self.text = read(ROUTER)
        self.body = squash(section(self.text, "Model-invoked path"))

    def test_the_section_names_the_engine_step_and_the_two_dialect_modules(self):
        self.assertIn("Engine step", self.body)
        self.assertIn("dialects/general.md", self.body)
        self.assertIn("dialects/postgres.md", self.body)
        self.assertIn("`GEN-*`", self.body)

    def test_the_section_says_line_1_is_the_fallback_sentence(self):
        self.assertRegex(self.body, r"(?i)first line of the reply is the fallback sentence")

    def test_the_setup_suggestion_comes_after_the_fallback_sentence(self):
        self.assertRegex(self.body, r"(?i)`/sql setup` suggestion[^.]*after the fallback sentence")

    def test_the_section_does_not_hold_the_sentence_text_and_the_router_holds_it_once(self):
        self.assertNotIn(SENTENCE_START, self.body)
        self.assertEqual(self.text.count(SENTENCE_START), 1)

    def test_the_section_keeps_the_prohibitions_and_the_words_of_the_old_test(self):
        lower = self.body.lower()
        for word in ("connect", "formatter", "outside"):
            self.assertIn(word, lower)
        sentences = re.split(r"(?<=[.!?])\s+", self.body)
        self.assertTrue(any("style" in s.lower() and "static rules" in s.lower() for s in sentences))

    def test_the_section_states_the_call_rules_of_the_engine_step(self):
        self.assertIn("--file <path>", self.body)
        self.assertRegex(self.body, r"(?i)no `--file`")
        self.assertIn("--request", self.body)
        self.assertIn("`ask`", self.body)
        self.assertRegex(self.body, r"(?i)fallback sentence once")

    def test_the_section_says_postgres_works_as_before_with_no_fallback_sentence(self):
        self.assertRegex(self.body, r"(?i)`postgres`.*as today.*no fallback sentence")

    def test_the_section_names_the_style_source_and_the_display_names(self):
        self.assertIn("`[style]`", self.body)
        self.assertIn("reader script", self.body)
        self.assertRegex(self.body, r"(?i)display names?")

    def test_the_section_runs_no_extractor_and_loads_no_source_module_for_a_fallback_file(self):
        self.assertRegex(self.body, r"(?i)no extractor")
        self.assertRegex(self.body, r"(?i)no source module")

    def test_the_old_static_rules_sentence_is_gone(self):
        self.assertNotIn("the static rules from the dialect module", self.body)


class SourceModuleAndLayersTest(unittest.TestCase):
    def setUp(self):
        self.text = read(ROUTER)

    def test_the_source_module_section_keeps_the_word_model_invoked(self):
        self.assertIn("model-invoked", squash(section(self.text, "Source module")).lower())

    def test_the_old_model_invoked_sentence_is_gone_from_the_whole_router(self):
        self.assertNotIn("(you write SQL yourself) does not change", squash(self.text))

    def test_the_layers_row_of_the_engine_step_names_the_model_invoked_path(self):
        row = next(l for l in self.text.splitlines() if l.startswith("| `scripts/detect_engine.py`"))
        self.assertIn("the model-invoked path", row)
        self.assertIn("`/sql format`", row)
        self.assertIn("fallback sentence", row)


class DescriptionTest(unittest.TestCase):
    def setUp(self):
        head = read(ROUTER).split("---")[1]
        self.lines = [l for l in head.splitlines() if l.startswith("description:")]
        self.description = self.lines[0][len("description: "):]

    def test_the_description_is_one_line(self):
        self.assertEqual(len(self.lines), 1)

    def test_the_description_names_full_rules_for_postgresql_and_general_advice_for_other_engines(self):
        self.assertRegex(self.description, r"(?i)full rules for PostgreSQL")
        self.assertRegex(self.description, r"(?i)general advice for other engines")

    def test_the_description_keeps_the_trigger_words_and_the_mode_summary(self):
        for word in ("writing", "editing", "SQL", "/sql setup", "/sql format", "/sql optimize"):
            self.assertIn(word, self.description)
        self.assertIn("Setup writes the repo SQL rules file", self.description)
        self.assertIn("format formats only the SQL the user points at", self.description)
        self.assertIn("optimize reports problems in a query", self.description)


class EvalCaseTest(unittest.TestCase):
    def test_the_case_files_exist(self):
        for name in ("case.yaml", "scaffold.sh", "repo/package.json", "repo/docs/agents/sql.md"):
            self.assertTrue(os.path.isfile(os.path.join(CASE, name)), name)
        self.assertFalse(os.path.exists(os.path.join(CASE, "expect.json")))
        self.assertFalse(os.path.exists(os.path.join(CASE, "prompt.md")))

    def test_the_case_yaml_is_named_by_its_folder_allows_edit_and_write_and_does_not_name_the_skill(self):
        text = read(os.path.join(CASE, "case.yaml"))
        self.assertIn("name: trigger-write-query-general\n", text)
        match = re.search(r"allowed_tools: \[(.*)\]", text)
        tools = {tool.strip() for tool in match.group(1).split(",")}
        self.assertTrue({"Skill", "Bash", "Edit", "Write"} <= tools)
        prompt = text.split("prompt:", 1)[1]
        self.assertNotIn("/sql", prompt)
        self.assertNotRegex(prompt, r"(?i)\bskill\b")

    def test_the_description_has_no_colon_and_space(self):
        text = read(os.path.join(CASE, "case.yaml"))
        description = re.search(r"(?m)^description: (.+)$", text).group(1)
        self.assertNotIn(": ", description)

    def test_the_fixture_is_a_mysql_repo_with_synthetic_content_only(self):
        self.assertIn('"mysql2"', read(os.path.join(CASE, "repo", "package.json")))
        for folder, _, names in os.walk(os.path.join(CASE, "repo")):
            for name in names:
                text = read(os.path.join(folder, name))
                self.assertNotRegex(text, r"(?i)://[^\s'\"]*@|password\s*=\s*\S")

    def test_the_grader_files(self):
        self.assertEqual(set(os.listdir(os.path.join(CASE, "graders"))), GRADERS)

    def test_the_fallback_sentence_grader_states_the_sentence_pattern(self):
        sentence = (r"^General guidance: this repo uses \S.*, which the skill does not cover\. "
                    r"The advice is general, with no database and no rule script\.")
        self.assertIn(sentence, read(os.path.join(CASE, "graders", "fallback-sentence.md")))

    def test_the_skill_fired_grader_matches_the_sql_skill(self):
        text = read(os.path.join(CASE, "graders", "skill-fired.md"))
        self.assertIn("tool: Skill", text)
        self.assertIn(r'"skill"\s*:\s*"(?:[\w-]+:)?sql"', text)

    def test_the_tool_graders_have_a_zero_maximum(self):
        folder = os.path.join(CASE, "graders")
        for grader in sorted(GRADERS - {"skill-fired.md", "fallback-sentence.md"}):
            with self.subTest(grader=grader):
                text = read(os.path.join(folder, grader))
                self.assertIn("type: tool_used", text)
                self.assertIn("max: 0", text)

    def test_the_readme_has_a_row_for_the_case_next_to_the_trigger_case(self):
        lines = read(README).splitlines()
        trigger = next(i for i, l in enumerate(lines) if l.startswith("| `trigger-write-query` |"))
        self.assertTrue(lines[trigger + 1].startswith("| `trigger-write-query-general` |"))


if __name__ == "__main__":
    unittest.main()
