import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(SKILL_DIR))
ROUTER = os.path.join(SKILL_DIR, "SKILL.md")
README = os.path.join(REPO, "README.md")
GITIGNORE = os.path.join(REPO, ".gitignore")
EVALS = os.path.join(SKILL_DIR, "evals")
PROCEDURE = os.path.join(EVALS, "README.md")
TRIGGER_CASE = os.path.join(EVALS, "trigger-write-query")

# Module file -> the tickets that fill it (spec: "Router and stubs").
MODULES = {
    "setup.md": ["#398"],
    "format.md": ["#391", "#392"],
    "optimize.md": ["#393"],
    "db-access.md": ["#394"],
    "style.md": ["#391"],
    "dialects/postgres.md": ["#393", "#395"],
    "sources/sql-files.md": ["#390"],
    "sources/postgres-js.md": ["#390"],
}


# The modules that are still stubs: MODULES without the source modules that #390 filled
# and the modules that #391, #392, #393, #394, #395 and #398 filled. The "format.md" entry of MODULES keeps
# #391 and #392 as an ownership mark that no test reads against the file text; the optimize
# tickets are asserted by test_sql_optimize_structure.py; db-access.md keeps stub sections for
# #396 and #397, asserted by test_sql_db_access.py (#400 filled its facts section).
FILLED = {"setup.md", "style.md", "format.md", "optimize.md", "dialects/postgres.md", "db-access.md"}
STUBS = {
    module: tickets
    for module, tickets in MODULES.items()
    if not module.startswith("sources/") and module not in FILLED
}

JS_EXTENSIONS = (".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx")
EXTRACT_CASE = os.path.join(EVALS, "extract-tag-not-sql")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def frontmatter(text):
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match, "no frontmatter"
    return match.group(1)


def section(text, heading):
    """Text of a `## <heading>` section, up to the next `## ` heading."""
    match = re.search(rf"^## {re.escape(heading)}$", text, re.M)
    assert match, f"no section {heading}"
    return text[match.end():].split("\n## ", 1)[0]


class RouterTest(unittest.TestCase):
    def setUp(self):
        self.text = read(ROUTER)

    def test_the_description_names_the_three_modes_and_the_trigger(self):
        head = frontmatter(self.text)
        self.assertRegex(head, r"(?m)^name: sql$")
        description = re.search(r"(?m)^description: (.+)$", head).group(1)
        for mode in ("/sql setup", "/sql format", "/sql optimize"):
            self.assertIn(mode, description)
        self.assertRegex(description, r"(?i)writing")
        self.assertRegex(description, r"(?i)editing")
        self.assertIn("SQL", description)

    def test_the_router_points_to_every_module(self):
        for module in MODULES:
            with self.subTest(module=module):
                self.assertIn(module, self.text)

    def test_no_mode_section(self):
        body = section(self.text, "No mode").lower()
        for word in ("ask", "setup", "format", "optimize"):
            self.assertIn(word, body)

    def test_model_invoked_path_section(self):
        body = section(self.text, "Model-invoked path")
        for word in ("connect", "formatter", "outside"):
            self.assertIn(word, body.lower())
        sentences = re.split(r"(?<=[.!?])\s+", " ".join(body.split()))
        self.assertTrue(
            any("style" in s.lower() and "static rules" in s.lower() for s in sentences),
            "no sentence names the style and the static rules",
        )

    def test_rules_file_section(self):
        body = section(self.text, "Rules file")
        self.assertIn("scripts/rules_file.py", body)
        self.assertIn("3.11", body)
        for phrase in ("parse error", "missing section", "no reason", "unknown", "disabled", "/sql setup"):
            self.assertIn(phrase, body.lower())


class StubTest(unittest.TestCase):
    """The modules that are still stubs (STUBS), each naming the tickets that fill it."""

    def test_every_module_exists_and_names_the_tickets_that_fill_it(self):
        for module, tickets in STUBS.items():
            with self.subTest(module=module):
                path = os.path.join(SKILL_DIR, module)
                self.assertTrue(os.path.isfile(path), f"{module} is missing")
                text = read(path)
                self.assertRegex(text, r"(?m)^# \S")
                for ticket in tickets:
                    self.assertIn(ticket, text)


class SourceModuleTest(unittest.TestCase):
    COMMON = ("scripts/extract.py", "--tags", "position", "start_line", "error")
    EXTRA = {
        "sources/postgres-js.md": (
            "detected_tags", "[sources]", "value", "fragment", "keyword", "this.sql",
        ),
        "sources/sql-files.md": ("statement",),
    }

    def test_the_source_modules_are_filled(self):
        for module, extra in self.EXTRA.items():
            with self.subTest(module=module):
                text = read(os.path.join(SKILL_DIR, module))
                self.assertRegex(text.splitlines()[0], r"^# \S")
                lower = text.lower()
                for needle in self.COMMON + extra:
                    self.assertIn(needle.lower(), lower, needle)
                self.assertNotRegex(text, r"(?i)\bstub\b")
                self.assertNotIn("#390", text)

    def test_the_source_modules_are_not_in_the_stub_list(self):
        for module in self.EXTRA:
            self.assertIn(module, MODULES)
            self.assertNotIn(module, STUBS)


class SourceModuleRouterTest(unittest.TestCase):
    def setUp(self):
        self.body = section(read(ROUTER), "Source module")

    def test_the_section_names_both_modules_the_script_and_the_extensions(self):
        for needle in ("sources/sql-files.md", "sources/postgres-js.md", "scripts/extract.py", ".sql", ".ts"):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.body)

    def test_every_js_extension_is_named(self):
        for extension in JS_EXTENSIONS:
            with self.subTest(extension=extension):
                self.assertIn(extension, self.body)

    def test_it_says_the_extension_is_case_insensitive_and_other_forms_are_not_supported(self):
        lower = self.body.lower()
        self.assertIn("case-insensitive", lower)
        self.assertIn("not supported", lower)

    def test_the_model_invoked_path_is_unchanged(self):
        self.assertIn("model-invoked", self.body.lower())


class FixtureNamesTest(unittest.TestCase):
    def test_test_files_exist_only_at_the_top_of_the_tests_folder(self):
        found = []
        for folder, _, names in os.walk(SKILL_DIR):
            for name in names:
                if re.fullmatch(r"test_.*\.py", name) and os.path.abspath(folder) != HERE:
                    found.append(os.path.join(folder, name))
        self.assertEqual(found, [])

    def test_every_test_file_is_named_test_sql(self):
        for name in os.listdir(HERE):
            if re.fullmatch(r"test_.*\.py", name):
                self.assertTrue(name.startswith("test_sql_"), name)


class EvalProcedureTest(unittest.TestCase):
    def setUp(self):
        self.text = read(PROCEDURE)

    def test_the_run_procedure_holds_each_flag_and_value(self):
        for needle in (
            "claude plugin eval",
            "--no-publish",
            "-j 2",
            "--runs 3",
            "--threshold 1.0",
            "--scaffold --allow-tools Bash",
            "repo test command",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.text)

    def test_the_fixture_rules_are_written(self):
        for needle in (
            "synthetic",
            "private inspiration repo",
            "test_*.py",
            "*.test.js",
            "*.test.ts",
            "docs/agents/sql.md",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.text)


class TriggerCaseTest(unittest.TestCase):
    def test_the_prompt_does_not_name_the_skill(self):
        prompt = read(os.path.join(TRIGGER_CASE, "prompt.md"))
        body = prompt.split("\n---\n", 1)[1]
        self.assertNotRegex(body, r"(?i)/sql|sql skill")
        self.assertRegex(body, r"(?i)query")

    def test_the_graders_check_the_skill_fired_and_no_connection_and_no_formatter(self):
        folder = os.path.join(TRIGGER_CASE, "graders")
        fired = read(os.path.join(folder, "skill-fired.md"))
        self.assertRegex(frontmatter(fired), r"(?m)^type: tool_used$")
        self.assertRegex(frontmatter(fired), r"(?m)^tool: Skill$")
        for name, needle in (("no-connection.md", "psql"), ("no-formatter.md", "prettier")):
            with self.subTest(name=name):
                head = frontmatter(read(os.path.join(folder, name)))
                self.assertRegex(head, r"(?m)^type: tool_used$")
                self.assertRegex(head, r"(?m)^tool: Bash$")
                self.assertRegex(head, r"(?m)^min: 0$")
                self.assertRegex(head, r"(?m)^max: 0$")
                self.assertIn(needle, head)


class ExtractCaseTest(unittest.TestCase):
    GRADERS = (
        "skill-fired.md", "extractor-ran.md", "names-each-template.md",
        "no-connection.md", "no-formatter.md",
    )

    def grader(self, name):
        return read(os.path.join(EXTRACT_CASE, "graders", name))

    def test_the_case_folder_has_a_case_file_a_scaffold_and_the_five_graders(self):
        self.assertTrue(os.path.isfile(os.path.join(EXTRACT_CASE, "case.yaml")))
        self.assertTrue(os.path.isfile(os.path.join(EXTRACT_CASE, "scaffold.sh")))
        found = sorted(os.listdir(os.path.join(EXTRACT_CASE, "graders")))
        self.assertEqual(found, sorted(self.GRADERS))

    def test_the_case_file_does_not_name_the_skill_and_sets_the_scaffold(self):
        case = read(os.path.join(EXTRACT_CASE, "case.yaml"))
        self.assertRegex(case, r"(?m)^  scaffold_script: scaffold\.sh$")
        self.assertIn("allowed_tools: [Skill, Read, Glob, Grep, Bash]", case)
        self.assertRegex(case, r"(?m)^  max_turns: 8$")
        prompt = case.split("prompt: |", 1)[1]
        self.assertNotRegex(prompt, r"(?i)/sql|sql skill")

    def test_the_scaffold_copies_the_fixture_into_the_working_folder(self):
        with tempfile.TemporaryDirectory() as work:
            subprocess.run(
                ["bash", os.path.join(EXTRACT_CASE, "scaffold.sh")],
                cwd=work, check=True, env={"PATH": os.environ["PATH"]},
            )
            copied = read(os.path.join(work, "billing-store.ts"))
        self.assertEqual(copied, read(os.path.join(EXTRACT_CASE, "billing-store.ts")))

    def test_the_tool_used_graders(self):
        skill = frontmatter(self.grader("skill-fired.md"))
        self.assertRegex(skill, r"(?m)^type: tool_used$")
        self.assertRegex(skill, r"(?m)^tool: Skill$")
        ran = frontmatter(self.grader("extractor-ran.md"))
        self.assertRegex(ran, r"(?m)^type: tool_used$")
        self.assertRegex(ran, r"(?m)^tool: Bash$")
        self.assertRegex(ran, r"(?m)^min: 1$")
        self.assertIn(r"extract\.py", ran)
        for name, needle in (
            ("no-connection.md", "psql|pg_run|PGSERVICE|service="),
            ("no-formatter.md", "prettier|pg_format|pgFormatter|sql-formatter|sqlfluff|eslint"),
        ):
            with self.subTest(name=name):
                head = frontmatter(self.grader(name))
                self.assertRegex(head, r"(?m)^type: tool_used$")
                self.assertRegex(head, r"(?m)^tool: Bash$")
                self.assertRegex(head, r"(?m)^min: 0$")
                self.assertRegex(head, r"(?m)^max: 0$")
                self.assertIn(needle, head)

    def test_the_rubric_has_a_type_and_names_the_tags(self):
        text = self.grader("names-each-template.md")
        self.assertRegex(frontmatter(text), r"(?m)^type: \S+")
        for tag in ("db", "this.db", "tx"):
            with self.subTest(tag=tag):
                self.assertIn("`" + tag + "`", text)

    def test_the_fixture_has_the_detection_forms_and_no_python_test_file(self):
        source = [n for n in os.listdir(EXTRACT_CASE) if n.endswith(".ts")]
        self.assertTrue(source)
        text = read(os.path.join(EXTRACT_CASE, source[0]))
        for needle in ("import postgres from 'postgres'", "const db = postgres(", "this.db = postgres(", "db.begin("):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_the_cases_table_names_the_case(self):
        self.assertIn("`extract-tag-not-sql`", read(PROCEDURE))


SQL_TEXT = os.path.join(SKILL_DIR, "scripts", "sql_text.py")
STYLE_KEYS = ("keyword_case", "indent", "clause_per_line", "comma", "alias_as")
FORMAT_CASES = (
    "format-template-written-style",
    "format-sql-file-written-style",
    "format-keyword-position",
    "format-no-rules-file",
)


def constant(name):
    """The words of a one-line string constant of scripts/sql_text.py."""
    match = re.search(rf'^{name} = "(.*)"$', read(SQL_TEXT), re.M)
    assert match, f"no one-line constant {name}"
    return match.group(1).split()


def headings(text):
    return re.findall(r"(?m)^## (.+)$", text)


class WordListConstantsTest(unittest.TestCase):
    def test_the_three_lists_are_one_line_constants_with_distinct_words(self):
        for name in ("KEYWORDS", "CLAUSE_WORDS", "ANCHOR_WORDS"):
            with self.subTest(name=name):
                words = constant(name)
                self.assertTrue(words)
                self.assertEqual(len(words), len(set(words)))
                self.assertTrue(all(word == word.upper() for word in words))

    def test_every_clause_word_is_a_keyword(self):
        self.assertTrue(set(constant("CLAUSE_WORDS")) <= set(constant("KEYWORDS")))


class StyleModuleTest(unittest.TestCase):
    def setUp(self):
        self.text = read(os.path.join(SKILL_DIR, "style.md"))

    def test_the_headings_are_in_order(self):
        self.assertEqual(
            headings(self.text),
            ["Choose the style", "Default style", "Written style", "Template layout"],
        )

    def test_the_module_is_filled(self):
        self.assertRegex(self.text.splitlines()[0], r"^# \S")
        self.assertNotRegex(self.text, r"(?i)\bstub\b")
        self.assertNotIn("#391", self.text)

    def test_the_keyword_and_clause_word_lines_hold_the_constants(self):
        for label, name in (("Keywords", "KEYWORDS"), ("Clause words", "CLAUSE_WORDS")):
            with self.subTest(label=label):
                match = re.search(rf"(?m)^{label}: (.*)$", self.text)
                self.assertIsNotNone(match, f"no {label} line")
                self.assertEqual(match.group(1).split(), constant(name))

    def test_the_default_values_and_the_two_examples(self):
        body = section(self.text, "Default style")
        for needle in (
            "`keyword_case` is `upper`",
            "`indent` is `2 spaces`",
            "`clause_per_line` is true",
            "`comma` is `trailing`",
            "`alias_as` is true",
            "JOIN orders AS o ON o.user_id = u.id",
            "${active ? sql`AND u.active` : sql``}",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, body)

    def test_every_style_key_is_named_and_the_choice_names_the_measurer(self):
        for key in STYLE_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, self.text)
        choose = section(self.text, "Choose the style")
        for needle in ("scripts/measure_style.py", "--tags", "[style]", "[sources]", "git ls-files", "fewer than 3"):
            with self.subTest(needle=needle):
                self.assertIn(needle, choose)

    def test_the_written_style_and_layout_hold_their_rules(self):
        written = section(self.text, "Written style")
        for needle in ("`BY`", "`JOIN`", "`--` comment", "fragment", "`leading`", "`AS`"):
            with self.subTest(needle=needle):
                self.assertIn(needle, written)
        layout = section(self.text, "Template layout")
        for needle in ("closing backtick", "opening backtick", "opaque word", "boundary"):
            with self.subTest(needle=needle):
                self.assertIn(needle, layout)


class FormatModuleTest(unittest.TestCase):
    def setUp(self):
        self.text = read(os.path.join(SKILL_DIR, "format.md"))

    def test_the_headings_are_in_order(self):
        self.assertEqual(headings(self.text), ["Target", "Style", "Write", "Report", "Safe tool path"])

    def test_the_module_is_filled_and_holds_no_formatter_command(self):
        self.assertRegex(self.text.splitlines()[0], r"^# \S")
        self.assertNotIn("#392", self.text)
        self.assertNotIn("#391", self.text)
        self.assertNotRegex(self.text, r"(?i)\bstub\b")
        self.assertNotRegex(self.text, r"npx|prettier --|sqlfluff (fix|format)")
        self.assertIn("safe formatter tool", self.text.split("\n## ", 1)[0])
        self.assertNotIn("this module runs no safe tool", self.text)

    def test_the_safe_tool_path_names_the_scripts_and_the_rules(self):
        path = section(self.text, "Safe tool path")
        for needle in (
            "scripts/detect_formatter.py", "scripts/run_formatter.py", "--form", "--tool", "--tags",
            "--range", "--output", "`cp`", "`cat`", "Write tool", "uncovered_tags", "`keyword`",
            "`none`", "`ok` is false", "start_line", "extractor again", "prettier-plugin-sql-cst",
            "eslint-plugin-sql --fix",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, path)

    def test_the_report_names_the_tools_and_the_gap(self):
        report = section(self.text, "Report")
        for needle in ("Formatter:", "Other tools found", "embeddedSqlTags", "uncovered_tags", "written style", "check <name>"):
            with self.subTest(needle=needle):
                self.assertIn(needle, report)

    def test_the_target_and_report_hold_their_rules(self):
        target = section(self.text, "Target")
        for needle in ("git diff -U0 HEAD", "scripts/extract.py", "ask"):
            with self.subTest(needle=needle):
                self.assertIn(needle, target)
        report = section(self.text, "Report")
        for needle in ("rules file", "repo majority", "default", "/sql setup", "written style"):
            with self.subTest(needle=needle):
                self.assertIn(needle.lower(), report.lower())


class FormatCasesTest(unittest.TestCase):
    def case(self, name, *parts):
        return os.path.join(EVALS, name, *parts)

    def test_each_case_has_its_files(self):
        for name in FORMAT_CASES:
            with self.subTest(case=name):
                for part in ("case.yaml", "scaffold.sh", "expected.json"):
                    self.assertTrue(os.path.isfile(self.case(name, part)), part)
                graders = sorted(os.listdir(self.case(name, "graders")))
                common = ["interpolations-same.md", "no-connection.md", "no-formatter.md", "only-target-changes.md", "style-matches.md"]
                extra = ["setup-suggested.md"] if name == "format-no-rules-file" else []
                self.assertEqual(graders, sorted(common + extra))

    def test_the_case_file_sets_the_scaffold_the_tools_and_the_turns(self):
        for name in FORMAT_CASES:
            with self.subTest(case=name):
                text = read(self.case(name, "case.yaml"))
                self.assertRegex(text, rf"(?m)^name: {name}$")
                self.assertRegex(text, r"(?m)^  scaffold_script: scaffold\.sh$")
                self.assertIn("allowed_tools: [Skill, Read, Glob, Grep, Bash, Edit, Write]", text)
                self.assertRegex(text, r"(?m)^  max_turns: 16$")
                prompt = text.split("prompt: |", 1)[1]
                self.assertIn("/sql format", prompt)
                self.assertIn("first-run.", prompt)

    def test_expected_json_names_the_file_target_style_and_tags(self):
        for name in FORMAT_CASES:
            with self.subTest(case=name):
                expected = json.loads(read(self.case(name, "expected.json")))
                self.assertEqual(sorted(expected), ["file", "style", "tags", "target"])
                self.assertTrue(os.path.isfile(self.case(name, expected["file"])))
                self.assertRegex(expected["target"], r"^\d+-\d+$")
                self.assertEqual(sorted(expected["style"]), sorted(STYLE_KEYS))
                self.assertIsInstance(expected["tags"], list)

    def test_the_scaffold_copies_the_fixture_and_the_rules_file(self):
        for name in FORMAT_CASES:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as work:
                expected = json.loads(read(self.case(name, "expected.json")))
                subprocess.run(
                    ["bash", self.case(name, "scaffold.sh")],
                    cwd=work, check=True, env={"PATH": os.environ["PATH"]},
                )
                self.assertEqual(read(os.path.join(work, expected["file"])), read(self.case(name, expected["file"])))
                rules = os.path.join(work, "docs", "agents", "sql.md")
                self.assertEqual(os.path.isfile(rules), name != "format-no-rules-file")

    def test_the_target_lies_inside_the_fixture_and_the_keyword_case_has_a_keyword_interpolation(self):
        for name in FORMAT_CASES:
            with self.subTest(case=name):
                expected = json.loads(read(self.case(name, "expected.json")))
                start, end = map(int, expected["target"].split("-"))
                lines = read(self.case(name, expected["file"])).splitlines()
                self.assertTrue(1 <= start <= end <= len(lines))
        text = read(self.case("format-keyword-position", "rows-store.ts"))
        self.assertRegex(text, r"(?m)^  \$\{sel\} \* from")

    def test_the_fixtures_have_the_binding_no_formatter_and_the_rules_file_tags(self):
        for name in FORMAT_CASES:
            with self.subTest(case=name):
                expected = json.loads(read(self.case(name, "expected.json")))
                if expected["file"].endswith(".ts"):
                    text = read(self.case(name, expected["file"]))
                    self.assertIn("import postgres from 'postgres'", text)
                    self.assertIn("const sql = postgres(", text)
                self.assertFalse(os.path.exists(self.case(name, "package.json")))
        for name in FORMAT_CASES[:3]:
            self.assertIn('tags = ["sql"]', read(self.case(name, "docs", "agents", "sql.md")))
        self.assertFalse(os.path.exists(self.case("format-no-rules-file", "docs")))

    def test_the_tool_used_graders(self):
        for name in FORMAT_CASES:
            for grader, needle in (
                ("no-connection.md", "psql|pg_run|PGSERVICE|service="),
                ("no-formatter.md", "prettier|pg_format|pgFormatter|sql-formatter|sqlfluff|eslint"),
            ):
                with self.subTest(case=name, grader=grader):
                    head = frontmatter(read(self.case(name, "graders", grader)))
                    self.assertRegex(head, r"(?m)^type: tool_used$")
                    self.assertRegex(head, r"(?m)^tool: Bash$")
                    self.assertRegex(head, r"(?m)^min: 0$")
                    self.assertRegex(head, r"(?m)^max: 0$")
                    self.assertIn(needle, head)

    def test_the_rubrics_are_llm_graders_and_the_no_rules_case_names_setup(self):
        for name in FORMAT_CASES:
            for grader in ("interpolations-same.md", "only-target-changes.md", "style-matches.md"):
                with self.subTest(case=name, grader=grader):
                    self.assertRegex(frontmatter(read(self.case(name, "graders", grader))), r"(?m)^type: llm$")
        setup = read(self.case("format-no-rules-file", "graders", "setup-suggested.md"))
        self.assertRegex(frontmatter(setup), r"(?m)^type: llm$")
        self.assertIn("/sql setup", setup)

    def test_the_procedure_names_the_cases_and_the_run_command(self):
        text = read(PROCEDURE)
        for name in FORMAT_CASES:
            with self.subTest(case=name):
                self.assertIn("`" + name + "`", text)
        self.assertIn("--scaffold --allow-tools Bash Write Edit", text)
        self.assertIn("--keep-temp", text)
        for command in ("interpolations_same.py", "only_target_changes.py", "style_matches.py"):
            with self.subTest(command=command):
                self.assertIn(command, text)


SAFE_TOOL_CASES = {
    "format-template-safe-tool": ("template", "prettier-plugin-embed", "runner-ran.md"),
    "format-sql-file-safe-tool": ("sql", "prettier-plugin-sql", "runner-ran.md"),
    "format-tag-outside-embedded-tags": ("template", "prettier-plugin-embed", "runner-not-run.md"),
}
SAFE_TOOL_GRADERS = [
    "interpolations-same.md", "no-connection.md", "no-raw-formatter.md",
    "only-target-changes.md", "style-matches.md",
]


class FormatSafeToolCasesTest(unittest.TestCase):
    def case(self, name, *parts):
        return os.path.join(EVALS, name, *parts)

    def scaffold(self, name, work, installs_on=1, check=True):
        """Run the scaffold with a stub `npm` that creates node_modules/.bin/prettier on its
        `installs_on`-th call (0: never)."""
        stub = tempfile.mkdtemp(dir=work)
        npm = os.path.join(stub, "npm")
        with open(npm, "w", encoding="utf-8") as handle:
            handle.write(
                '#!/bin/sh\nd="$(dirname "$0")"\npwd > "$d/npm-cwd"\necho "$@" > "$d/npm-args"\n'
                'echo x >> "$d/npm-calls"\n'
                'if [ "%d" -gt 0 ] && [ "$(wc -l < "$d/npm-calls")" -ge %d ]; then\n'
                '  mkdir -p node_modules/.bin && : > node_modules/.bin/prettier && chmod +x node_modules/.bin/prettier\n'
                'fi\n' % (installs_on, installs_on)
            )
        os.chmod(npm, 0o755)
        run = os.path.join(work, "run")
        os.makedirs(run)
        env = {"PATH": stub + os.pathsep + os.environ["PATH"]}
        result = subprocess.run(
            ["bash", self.case(name, "scaffold.sh")], cwd=run, env=env, capture_output=True, text=True
        )
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return run, stub, result

    def test_each_case_has_its_files_and_its_exact_grader_set(self):
        for name, (_, _, runner) in SAFE_TOOL_CASES.items():
            with self.subTest(case=name):
                expected = json.loads(read(self.case(name, "expected.json")))
                for part in ("case.yaml", "scaffold.sh", "expected.json", "package.json", "package-lock.json",
                             ".prettierrc.json", os.path.join("docs", "agents", "sql.md"), expected["file"]):
                    self.assertTrue(os.path.isfile(self.case(name, part)), part)
                self.assertEqual(sorted(os.listdir(self.case(name, "graders"))), sorted(SAFE_TOOL_GRADERS + [runner]))

    def test_the_case_file_sets_the_scaffold_the_tools_and_the_turns(self):
        for name in SAFE_TOOL_CASES:
            with self.subTest(case=name):
                text = read(self.case(name, "case.yaml"))
                self.assertRegex(text, rf"(?m)^name: {name}$")
                self.assertRegex(text, r"(?m)^  scaffold_script: scaffold\.sh$")
                self.assertIn("allowed_tools: [Skill, Read, Glob, Grep, Bash, Edit, Write]", text)
                self.assertRegex(text, r"(?m)^  max_turns: 20$")
                prompt = text.split("prompt: |", 1)[1]
                self.assertIn("/sql format", prompt)
                self.assertIn("first-run.", prompt)
                self.assertIn("the current folder is the repo root", prompt)

    def test_expected_json_names_the_file_target_style_and_tags(self):
        for name in SAFE_TOOL_CASES:
            with self.subTest(case=name):
                expected = json.loads(read(self.case(name, "expected.json")))
                self.assertEqual(sorted(expected), ["file", "style", "tags", "target"])
                self.assertRegex(expected["target"], r"^\d+-\d+$")
                self.assertEqual(sorted(expected["style"]), sorted(STYLE_KEYS))
                self.assertIsInstance(expected["tags"], list)
                lines = read(self.case(name, expected["file"])).split("\n")
                start, end = (int(part) for part in expected["target"].split("-"))
                self.assertLessEqual(end, len(lines) - 1)
                self.assertGreaterEqual(start, 1)

    def test_the_tool_used_graders(self):
        for name, (_, _, runner) in SAFE_TOOL_CASES.items():
            expectations = {
                "no-connection.md": ("psql|pg_run|PGSERVICE|service=", 0, 0),
                "no-raw-formatter.md": (r"(node_modules/\.bin/|npx +|^ *)(prettier|sqlfluff|pg_format|sql-formatter)( |$)", 0, 0),
                runner: (r"run_formatter\.py", 0 if runner == "runner-not-run.md" else 1, 0 if runner == "runner-not-run.md" else None),
            }
            for grader, (needle, minimum, maximum) in expectations.items():
                with self.subTest(case=name, grader=grader):
                    head = frontmatter(read(self.case(name, "graders", grader)))
                    self.assertRegex(head, r"(?m)^type: tool_used$")
                    self.assertRegex(head, r"(?m)^tool: Bash$")
                    self.assertIn(needle, head)
                    self.assertRegex(head, rf"(?m)^min: {minimum}$")
                    if maximum is None:
                        self.assertNotRegex(head, r"(?m)^max:")
                    else:
                        self.assertRegex(head, rf"(?m)^max: {maximum}$")

    def test_the_rubrics_are_llm_graders(self):
        for name in SAFE_TOOL_CASES:
            for grader in ("interpolations-same.md", "only-target-changes.md", "style-matches.md"):
                with self.subTest(case=name, grader=grader):
                    self.assertRegex(frontmatter(read(self.case(name, "graders", grader))), r"(?m)^type: llm$")

    def test_the_packages_are_pinned_and_locked(self):
        for name in SAFE_TOOL_CASES:
            with self.subTest(case=name):
                package = json.loads(read(self.case(name, "package.json")))
                versions = package["devDependencies"]
                self.assertEqual(sorted(versions), ["prettier", "prettier-plugin-embed", "prettier-plugin-sql"])
                for version in versions.values():
                    self.assertRegex(version, r"^\d+\.\d+\.\d+$")
                lock = json.loads(read(self.case(name, "package-lock.json")))
                self.assertEqual(lock["packages"][""]["devDependencies"], versions)

    def test_the_scaffold_copies_the_fixture_and_installs_in_the_run_folder(self):
        for name in SAFE_TOOL_CASES:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as work:
                expected = json.loads(read(self.case(name, "expected.json")))
                run, stub, _ = self.scaffold(name, work)
                self.assertEqual(read(os.path.join(run, expected["file"])), read(self.case(name, expected["file"])))
                for part in (".prettierrc.json", "package.json", "package-lock.json", os.path.join("docs", "agents", "sql.md")):
                    self.assertEqual(read(os.path.join(run, part)), read(self.case(name, part)))
                self.assertEqual(os.path.realpath(read(os.path.join(stub, "npm-cwd")).strip()), os.path.realpath(run))
                args = read(os.path.join(stub, "npm-args")).split()
                self.assertEqual(args[0], "ci")
                self.assertIn("--ignore-scripts", args)
                self.assertIn("--include=dev", args)
                self.assertEqual(args[args.index("--cache") + 1], os.path.join(os.path.realpath(run), ".npm-cache"))

    def test_the_scaffold_retries_a_missing_install_and_then_fails_loudly(self):
        for name in SAFE_TOOL_CASES:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as work:
                _, stub, result = self.scaffold(name, work, installs_on=2)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(len(read(os.path.join(stub, "npm-calls")).split()), 2)
            with self.subTest(case=name, never=True), tempfile.TemporaryDirectory() as work:
                _, stub, result = self.scaffold(name, work, installs_on=0, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("node_modules/.bin/prettier is missing", result.stderr)
                self.assertEqual(len(read(os.path.join(stub, "npm-calls")).split()), 3)

    def test_the_detector_picks_the_tool_that_each_case_expects(self):
        detector = os.path.join(SKILL_DIR, "scripts", "detect_formatter.py")
        for name, (form, tool, _) in SAFE_TOOL_CASES.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory() as work:
                run, _, _ = self.scaffold(name, work)
                expected = json.loads(read(self.case(name, "expected.json")))
                command = [sys.executable, detector, run, "--form", form, "--tags", ",".join(expected["tags"])]
                out = json.loads(subprocess.run(command, capture_output=True, text=True, check=True).stdout)
                self.assertEqual(out["chosen"], tool)
                self.assertEqual(out["uncovered_tags"], ["db"] if name == "format-tag-outside-embedded-tags" else [])

    def test_the_tag_case_has_a_db_tag_and_a_style_that_is_not_the_tools(self):
        name = "format-tag-outside-embedded-tags"
        self.assertIn('tags = ["db"]', read(self.case(name, "docs", "agents", "sql.md")))
        self.assertIn("const db = postgres(", read(self.case(name, "inventory-store.ts")))
        self.assertIn('"embeddedSqlTags": ["sql"]', read(self.case(name, ".prettierrc.json")))
        expected = json.loads(read(self.case(name, "expected.json")))
        self.assertEqual(expected["style"]["keyword_case"], "lower")

    def test_the_template_fixtures_keep_the_fragment_in_the_text_that_the_tool_keeps(self):
        text = read(self.case("format-template-safe-tool", "inventory-store.ts"))
        self.assertIn("${onlyLow ? sql`AND s.qty < 5` : sql``}", text)

    def test_the_procedure_names_the_cases_and_the_install(self):
        text = read(PROCEDURE)
        for name in SAFE_TOOL_CASES:
            with self.subTest(case=name):
                self.assertIn("`" + name + "`", text)
        for needle in ("npm ci", "run_formatter.py", "--output", "read-only"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)


class GraderFilesTest(unittest.TestCase):
    def test_the_graders_folder_holds_the_grader_commands_and_no_test_files(self):
        # The format graders of #391, the optimize graders and runner of #393, and the DB graders
        # and runner of #399. The runners import other graders, so a test run leaves a git-ignored
        # __pycache__ folder.
        folder = os.path.join(SKILL_DIR, "graders")
        self.assertEqual(
            sorted(name for name in os.listdir(folder) if name != "__pycache__"),
            [
                "grade_db_eval_results.py", "grade_db_unchanged.py", "grade_eval_results.py",
                "grade_leak_scan.py", "grade_no_change.py", "grade_refusals.py", "grade_report.py",
                "grade_rule_ids.py", "grade_setup.py", "interpolations_same.py", "only_target_changes.py",
                "style_matches.py",
            ],
        )


class RepoFilesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        shutil.copy(GITIGNORE, os.path.join(self.root, ".gitignore"))
        env = {"PATH": os.environ["PATH"], "HOME": self.root}
        subprocess.run(["git", "init", "-q", self.root], check=True, env=env)
        self.env = env

    def ignored(self, path):
        result = subprocess.run(["git", "-C", self.root, "check-ignore", "-q", path], env=self.env)
        self.assertIn(result.returncode, (0, 1))
        return result.returncode == 0

    def test_the_eval_results_folder_is_ignored_and_the_router_is_not(self):
        self.assertTrue(self.ignored("skills/sql/evals/results/2026-01-01T00-00-00/aggregate-result.json"))
        self.assertFalse(self.ignored("skills/sql/SKILL.md"))
        self.assertFalse(self.ignored("skills/sql/evals/trigger-write-query/prompt.md"))

    def test_the_readme_table_names_the_scripts_tests_and_evals(self):
        text = read(README)
        rows = [line for line in text.splitlines() if line.startswith("| `skills/sql/")]
        by_path = {re.match(r"\| `([^`]+)`", row).group(1): row for row in rows}
        for glob in ("skills/sql/scripts/*", "skills/sql/tests/*", "skills/sql/evals/**"):
            with self.subTest(glob=glob):
                self.assertIn(glob, by_path)
        self.assertIn("3.11", by_path["skills/sql/scripts/*"])

    def test_the_declared_test_command_lists_the_tests_folder(self):
        text = read(os.path.join(REPO, ".claude", "CLAUDE.md"))
        self.assertIn("'skills/sql/tests'", text)


if __name__ == "__main__":
    unittest.main()
