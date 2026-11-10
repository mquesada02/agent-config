import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
SCRIPT = os.path.join(SKILL_DIR, "scripts", "detect_formatter.py")

CHAIN = ["prettier-plugin-embed", "prettier-plugin-sql"]


def package_json(dependencies=(), dev_dependencies=(), **extra):
    data = {"name": "fixture"}
    if dependencies:
        data["dependencies"] = {name: "1.0.0" for name in dependencies}
    if dev_dependencies:
        data["devDependencies"] = {name: "1.0.0" for name in dev_dependencies}
    data.update(extra)
    return json.dumps(data)


class DetectorTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = self._tmp.name

    def write(self, name, text):
        path = os.path.join(self.repo, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def run_detector(self, *args, repo=None):
        result = subprocess.run(
            [sys.executable, SCRIPT, repo or self.repo, *args],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
        return result

    def detect(self, *args):
        result = self.run_detector(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def full_chain(self, prettierrc=None):
        self.write("package.json", package_json(dev_dependencies=CHAIN))
        config = {"plugins": CHAIN, "language": "postgresql"}
        config.update(prettierrc or {})
        self.write(".prettierrc.json", json.dumps(config))


class TemplateSignalsTest(DetectorTestCase):
    def test_a_full_chain_gives_the_template_tool(self):
        self.full_chain()
        out = self.detect("--form", "template")
        self.assertEqual(out["chosen"], "prettier-plugin-embed")
        self.assertEqual([item["tool"] for item in out["found"]], ["prettier-plugin-embed"])
        self.assertTrue(out["found"][0]["signals"])
        self.assertIn("found by", out["reason"])
        self.assertIsNone(out["override"])
        self.assertEqual(out["notes"], [])
        self.assertNotIn("error", out)

    def test_dependencies_count_as_well_as_dev_dependencies(self):
        self.write("package.json", package_json(dependencies=CHAIN))
        self.write(".prettierrc.json", json.dumps({"plugins": CHAIN, "language": "postgresql"}))
        self.assertEqual(self.detect("--form", "template")["chosen"], "prettier-plugin-embed")

    def test_a_plugin_missing_from_package_json_gives_none(self):
        self.write("package.json", package_json(dev_dependencies=["prettier-plugin-embed"]))
        self.write(".prettierrc.json", json.dumps({"plugins": CHAIN, "language": "postgresql"}))
        out = self.detect("--form", "template")
        self.assertEqual(out["chosen"], "none")
        self.assertEqual(out["found"], [])
        self.assertIn("prettier-plugin-sql is not in package.json", out["reason"])

    def test_a_plugin_missing_from_the_config_gives_none(self):
        self.write("package.json", package_json(dev_dependencies=CHAIN))
        self.write(".prettierrc.json", json.dumps({"plugins": ["prettier-plugin-sql"], "language": "postgresql"}))
        out = self.detect("--form", "template")
        self.assertEqual(out["chosen"], "none")
        self.assertIn("prettier-plugin-embed is not in the Prettier config plugins", out["reason"])

    def test_a_full_chain_with_no_language_gives_none(self):
        self.write("package.json", package_json(dev_dependencies=CHAIN))
        self.write(".prettierrc.json", json.dumps({"plugins": CHAIN}))
        out = self.detect("--form", "template")
        self.assertEqual(out["chosen"], "none")
        self.assertIn("no language option", out["reason"])

    def test_a_full_chain_with_another_dialect_gives_none(self):
        self.write("package.json", package_json(dev_dependencies=CHAIN))
        self.write(".prettierrc.json", json.dumps({"plugins": CHAIN, "language": "mysql"}))
        out = self.detect("--form", "template")
        self.assertEqual(out["chosen"], "none")
        self.assertIn('language is "mysql", not "postgresql"', out["reason"])

    def test_nothing_in_the_repo_names_all_three_parts(self):
        out = self.detect("--form", "template")
        self.assertEqual(out["chosen"], "none")
        for needle in ("package.json", "plugins", "language"):
            self.assertIn(needle, out["reason"])

    def test_the_sql_cst_plugin_and_the_eslint_plugin_are_never_a_template_tool(self):
        self.write(
            "package.json",
            package_json(dev_dependencies=["prettier-plugin-sql-cst", "eslint-plugin-sql", "prettier-plugin-embed"]),
        )
        self.write(".prettierrc.json", json.dumps({"plugins": ["prettier-plugin-embed", "prettier-plugin-sql-cst"], "language": "postgresql"}))
        out = self.detect("--form", "template")
        self.assertEqual(out["chosen"], "none")
        self.assertEqual(out["found"], [])
        self.assertNotIn("sql-cst", json.dumps(out["found"]))

    def test_a_prettier_key_in_package_json_is_read(self):
        self.write(
            "package.json",
            package_json(dev_dependencies=CHAIN, prettier={"plugins": CHAIN, "language": "postgresql"}),
        )
        self.assertEqual(self.detect("--form", "template")["chosen"], "prettier-plugin-embed")

    def test_a_plain_prettierrc_that_is_json_is_read(self):
        self.write("package.json", package_json(dev_dependencies=CHAIN))
        self.write(".prettierrc", json.dumps({"plugins": CHAIN, "language": "postgresql"}))
        self.assertEqual(self.detect("--form", "template")["chosen"], "prettier-plugin-embed")

    def test_a_toml_config_is_read(self):
        self.write("package.json", package_json(dev_dependencies=CHAIN))
        self.write(
            ".prettierrc.toml",
            'plugins = ["prettier-plugin-embed", "prettier-plugin-sql"]\nlanguage = "postgresql"\n',
        )
        self.assertEqual(self.detect("--form", "template")["chosen"], "prettier-plugin-embed")

    def test_the_first_config_file_in_the_prettier_order_decides(self):
        self.write("package.json", package_json(dev_dependencies=CHAIN))
        self.write(".prettierrc.json", json.dumps({"plugins": CHAIN, "language": "mysql"}))
        self.write(".prettierrc.toml", 'plugins = ["prettier-plugin-embed", "prettier-plugin-sql"]\nlanguage = "postgresql"\n')
        self.assertEqual(self.detect("--form", "template")["chosen"], "none")

    def test_the_plugins_that_are_not_strings_do_not_count(self):
        self.write("package.json", package_json(dev_dependencies=CHAIN))
        self.write(".prettierrc.json", json.dumps({"plugins": [{"name": "prettier-plugin-embed"}, "prettier-plugin-sql"], "language": "postgresql"}))
        self.assertEqual(self.detect("--form", "template")["chosen"], "none")


@unittest.skipUnless(shutil.which("node"), "the Node read needs node on PATH")
class NodeResolvedConfigTest(DetectorTestCase):
    def stub_prettier(self, body):
        folder = os.path.join(self.repo, "node_modules", "prettier")
        os.makedirs(folder)
        with open(os.path.join(folder, "package.json"), "w", encoding="utf-8") as handle:
            handle.write('{"name": "prettier", "version": "3.0.0", "main": "index.js"}')
        with open(os.path.join(folder, "index.js"), "w", encoding="utf-8") as handle:
            handle.write(body)

    def test_a_js_config_is_resolved_with_the_repo_prettier(self):
        self.write("package.json", package_json(dev_dependencies=CHAIN))
        self.write("prettier.config.js", "module.exports = {};\n")
        self.stub_prettier(
            "exports.resolveConfig = async (file) => ({plugins: %s, language: 'postgresql', embeddedSqlTags: ['sql', 'db']});\n"
            % json.dumps(CHAIN)
        )
        out = self.detect("--form", "template", "--tags", "sql,db,tx")
        self.assertEqual(out["chosen"], "prettier-plugin-embed")
        self.assertEqual(out["embedded_sql_tags"], ["sql", "db"])
        self.assertEqual(out["uncovered_tags"], ["tx"])

    def test_the_dummy_path_is_a_ts_file_for_a_template_and_a_sql_file_for_sql(self):
        self.write("package.json", package_json(dev_dependencies=CHAIN))
        self.write("prettier.config.js", "module.exports = {};\n")
        self.stub_prettier(
            "exports.resolveConfig = async (file) => ({plugins: file.endsWith('index.ts') ? %s : [], language: 'postgresql'});\n"
            % json.dumps(CHAIN)
        )
        self.assertEqual(self.detect("--form", "template")["chosen"], "prettier-plugin-embed")
        self.write("query.sql", "select 1;\n")
        self.assertEqual(self.detect("--form", "sql")["chosen"], "none")

    def test_a_config_that_cannot_be_resolved_gives_a_note_and_no_tool(self):
        self.write("package.json", package_json(dev_dependencies=CHAIN))
        self.write("prettier.config.js", "module.exports = {};\n")
        self.stub_prettier("exports.resolveConfig = async () => { throw new Error('broken'); };\n")
        out = self.detect("--form", "template")
        self.assertEqual(out["chosen"], "none")
        self.assertEqual(len(out["notes"]), 1)
        self.assertIn("Prettier config", out["notes"][0])

    def test_a_js_config_with_no_prettier_in_the_repo_gives_a_note(self):
        self.write("package.json", package_json(dev_dependencies=CHAIN))
        self.write("prettier.config.mjs", "export default {};\n")
        out = self.detect("--form", "template")
        self.assertEqual(out["chosen"], "none")
        self.assertEqual(len(out["notes"]), 1)

    def test_a_prettier_key_that_is_a_string_is_resolved_with_node(self):
        self.write("package.json", package_json(dev_dependencies=CHAIN, prettier="@shared/prettier-config"))
        self.stub_prettier(
            "exports.resolveConfig = async () => ({plugins: %s, language: 'postgresql'});\n" % json.dumps(CHAIN)
        )
        self.assertEqual(self.detect("--form", "template")["chosen"], "prettier-plugin-embed")


class TagCoverageTest(DetectorTestCase):
    def test_a_tag_that_the_option_misses_is_reported(self):
        self.full_chain({"embeddedSqlTags": ["sql"]})
        out = self.detect("--form", "template", "--tags", "sql,db,this.sql")
        self.assertEqual(out["chosen"], "prettier-plugin-embed")
        self.assertEqual(out["embedded_sql_tags"], ["sql"])
        self.assertEqual(out["uncovered_tags"], ["db", "this.sql"])

    def test_an_option_that_covers_every_tag_leaves_nothing_uncovered(self):
        self.full_chain({"embeddedSqlTags": ["sql", "db"]})
        out = self.detect("--form", "template", "--tags", "db,sql")
        self.assertEqual(out["uncovered_tags"], [])

    def test_with_no_option_the_default_is_sql(self):
        self.full_chain()
        out = self.detect("--form", "template", "--tags", "sql,tx")
        self.assertEqual(out["embedded_sql_tags"], ["sql"])
        self.assertEqual(out["uncovered_tags"], ["tx"])

    def test_with_no_tags_argument_nothing_is_uncovered(self):
        self.full_chain({"embeddedSqlTags": ["sql"]})
        out = self.detect("--form", "template")
        self.assertEqual(out["embedded_sql_tags"], ["sql"])
        self.assertEqual(out["uncovered_tags"], [])

    def test_a_tag_gap_does_not_turn_the_tool_into_none(self):
        self.full_chain({"embeddedSqlTags": ["sql"]})
        self.assertEqual(self.detect("--form", "template", "--tags", "db")["chosen"], "prettier-plugin-embed")

    def test_without_a_template_tool_the_coverage_is_null(self):
        out = self.detect("--form", "template", "--tags", "sql")
        self.assertIsNone(out["embedded_sql_tags"])
        self.assertEqual(out["uncovered_tags"], [])

    def test_form_sql_has_no_coverage(self):
        self.full_chain({"embeddedSqlTags": ["sql"]})
        out = self.detect("--form", "sql", "--tags", "db")
        self.assertIsNone(out["embedded_sql_tags"])
        self.assertEqual(out["uncovered_tags"], [])


class SqlSignalsTest(DetectorTestCase):
    def found(self, **kwargs):
        out = self.detect("--form", "sql", *sum((["--" + k.replace("_", "-"), v] for k, v in kwargs.items()), []))
        return out, [item["tool"] for item in out["found"]]

    def test_a_sqlfluff_file_alone(self):
        self.write(".sqlfluff", "[sqlfluff]\ndialect = postgres\n")
        out, tools = self.found()
        self.assertEqual(tools, ["sqlfluff"])
        self.assertEqual(out["chosen"], "sqlfluff")
        self.assertIn(".sqlfluff", out["found"][0]["signals"])

    def test_a_tool_sqlfluff_table_in_pyproject_alone(self):
        self.write("pyproject.toml", '[tool.sqlfluff]\ndialect = "postgres"\n')
        self.assertEqual(self.found()[1], ["sqlfluff"])

    def test_a_pyproject_with_no_sqlfluff_table_gives_nothing(self):
        self.write("pyproject.toml", '[tool.black]\nline-length = 88\n')
        out, tools = self.found()
        self.assertEqual(tools, [])
        self.assertEqual(out["chosen"], "none")
        self.assertIn("no safe formatter tool has a signal in the repo", out["reason"])

    def test_an_unparsable_pyproject_gives_a_note_and_no_signal(self):
        self.write("pyproject.toml", "[tool.sqlfluff\n")
        out, tools = self.found()
        self.assertEqual(tools, [])
        self.assertEqual(len(out["notes"]), 1)
        self.assertIn("pyproject.toml", out["notes"][0])

    def test_a_pg_format_file_alone(self):
        self.write(".pg_format", "keyword-case=2\n")
        self.assertEqual(self.found()[1], ["pgFormatter"])

    def test_the_prettier_sql_plugin_in_the_config_alone(self):
        self.write(".prettierrc.json", json.dumps({"plugins": ["prettier-plugin-sql"]}))
        out, tools = self.found()
        self.assertEqual(tools, ["prettier-plugin-sql"])
        self.assertEqual(out["chosen"], "prettier-plugin-sql")

    def test_the_prettier_sql_plugin_only_in_package_json_gives_nothing(self):
        self.write("package.json", package_json(dev_dependencies=["prettier-plugin-sql"]))
        self.assertEqual(self.found()[1], [])

    def test_a_sql_formatter_config_file_alone(self):
        self.write(".sql-formatter.json", "{}")
        self.assertEqual(self.found()[1], ["sql-formatter"])

    def test_a_sql_formatter_dependency_alone(self):
        self.write("package.json", package_json(dev_dependencies=["sql-formatter"]))
        self.assertEqual(self.found()[1], ["sql-formatter"])

    def test_a_package_json_that_is_not_json_gives_a_note(self):
        self.write("package.json", "{ not json")
        out, tools = self.found()
        self.assertEqual(tools, [])
        self.assertEqual(len(out["notes"]), 1)
        self.assertIn("package.json", out["notes"][0])

    def test_several_tools_are_listed_and_the_order_picks(self):
        self.write(".sql-formatter.json", "{}")
        self.write(".pg_format", "")
        self.write(".prettierrc.json", json.dumps({"plugins": ["prettier-plugin-sql"]}))
        out, tools = self.found()
        self.assertEqual(tools, ["pgFormatter", "prettier-plugin-sql", "sql-formatter"])
        self.assertEqual(out["chosen"], "pgFormatter")
        self.write(".sqlfluff", "[sqlfluff]\n")
        out, tools = self.found()
        self.assertEqual(tools[0], "sqlfluff")
        self.assertEqual(out["chosen"], "sqlfluff")

    def test_a_repo_with_no_tool_gives_none(self):
        out, tools = self.found()
        self.assertEqual((out["chosen"], tools), ("none", []))
        self.assertIsNone(out["embedded_sql_tags"])


class OverrideTest(DetectorTestCase):
    def setUp(self):
        super().setUp()
        self.write(".sqlfluff", "[sqlfluff]\n")
        self.write(".sql-formatter.json", "{}")

    def test_a_rules_file_tool_that_is_installed_wins_over_the_order(self):
        out = self.detect("--form", "sql", "--tool", "sql-formatter")
        self.assertEqual(out["chosen"], "sql-formatter")
        self.assertEqual(out["override"]["tool"], "sql-formatter")
        self.assertTrue(out["override"]["used"])
        self.assertEqual(out["override"]["reason"], "the rules file names a safe tool that is installed and fits")
        self.assertEqual(out["reason"], "the rules file names it")
        self.assertEqual([item["tool"] for item in out["found"]], ["sqlfluff", "sql-formatter"])

    def test_a_tool_that_is_not_installed_is_ignored_with_a_reason(self):
        out = self.detect("--form", "sql", "--tool", "pgFormatter")
        self.assertEqual(out["chosen"], "sqlfluff")
        self.assertFalse(out["override"]["used"])
        self.assertEqual(out["override"]["reason"], "has no signal in the repo")

    def test_a_tool_for_the_other_form_is_ignored(self):
        out = self.detect("--form", "sql", "--tool", "prettier-plugin-embed")
        self.assertEqual(out["chosen"], "sqlfluff")
        self.assertFalse(out["override"]["used"])
        self.assertEqual(out["override"]["reason"], "does not fit the form")

    def test_a_sql_tool_does_not_fit_a_template(self):
        self.full_chain()
        out = self.detect("--form", "template", "--tool", "sqlfluff")
        self.assertEqual(out["chosen"], "prettier-plugin-embed")
        self.assertEqual(out["override"]["reason"], "does not fit the form")

    def test_the_template_tool_wins_for_a_template(self):
        self.full_chain()
        out = self.detect("--form", "template", "--tool", "prettier-plugin-embed")
        self.assertTrue(out["override"]["used"])
        self.assertEqual(out["chosen"], "prettier-plugin-embed")

    def test_none_is_not_a_safe_tool_name(self):
        out = self.detect("--form", "sql", "--tool", "none")
        self.assertEqual(out["chosen"], "sqlfluff")
        self.assertFalse(out["override"]["used"])
        self.assertEqual(out["override"]["reason"], "not a safe tool name")

    def test_an_unknown_name_and_the_unsafe_tools_are_ignored(self):
        for name in ("black", "prettier-plugin-sql-cst", "eslint-plugin-sql"):
            with self.subTest(name=name):
                out = self.detect("--form", "sql", "--tool", name)
                self.assertEqual(out["chosen"], "sqlfluff")
                self.assertEqual(out["override"]["reason"], "not a safe tool name")

    def test_an_ignored_value_with_no_tool_found_still_gives_none(self):
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        out = json.loads(self.run_detector("--form", "sql", "--tool", "sqlfluff", repo=other.name).stdout)
        self.assertEqual(out["chosen"], "none")
        self.assertFalse(out["override"]["used"])


class UsageTest(DetectorTestCase):
    def assert_usage_error(self, *args, repo=None):
        result = self.run_detector(*args, repo=repo)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.strip().splitlines()), 1)

    def test_the_form_is_required_and_checked(self):
        self.assert_usage_error()
        self.assert_usage_error("--form", "yaml")

    def test_an_empty_tags_value_is_a_usage_error(self):
        self.assert_usage_error("--form", "sql", "--tags", "")

    def test_a_repo_that_is_not_a_folder_is_a_usage_error(self):
        self.assert_usage_error("--form", "sql", repo=os.path.join(self.repo, "missing"))

    def test_an_unknown_option_and_a_repeated_option_are_usage_errors(self):
        self.assert_usage_error("--form", "sql", "--bogus", "x")
        self.assert_usage_error("--form", "sql", "--form", "template")


if __name__ == "__main__":
    unittest.main()
