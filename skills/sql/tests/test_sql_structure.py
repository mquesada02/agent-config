import os
import re
import shutil
import subprocess
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
# and the modules that #393 filled (their tickets are asserted by test_sql_optimize_structure.py).
FILLED = {"optimize.md", "dialects/postgres.md"}
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
