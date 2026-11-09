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
    def test_every_module_exists_and_names_the_tickets_that_fill_it(self):
        for module, tickets in MODULES.items():
            with self.subTest(module=module):
                path = os.path.join(SKILL_DIR, module)
                self.assertTrue(os.path.isfile(path), f"{module} is missing")
                text = read(path)
                self.assertRegex(text, r"(?m)^# \S")
                for ticket in tickets:
                    self.assertIn(ticket, text)


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
