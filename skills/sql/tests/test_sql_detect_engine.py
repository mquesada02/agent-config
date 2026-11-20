import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
SCRIPT = os.path.join(SKILL_DIR, "scripts", "detect_engine.py")
FENCE = "```"

FAKE_URL = "mysql://app_user:Sup3rSecret@db.example.invalid:3306/appdb"


def package_json(dependencies=(), dev_dependencies=()):
    data = {"name": "fixture"}
    if dependencies:
        data["dependencies"] = {name: "1.0.0" for name in dependencies}
    if dev_dependencies:
        data["devDependencies"] = {name: "1.0.0" for name in dev_dependencies}
    return json.dumps(data)


def rules_text(block):
    return f"# SQL rules\n\n{FENCE}toml\n{block}{FENCE}\n"


class EngineTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = self._tmp.name

    def write(self, name, text):
        path = os.path.join(self.repo, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def rules(self, block):
        self.write("docs/agents/sql.md", rules_text(block))

    def run_script(self, *args, repo=None):
        return subprocess.run(
            [sys.executable, SCRIPT, repo or self.repo, *args],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )

    def detect(self, *args):
        result = self.run_script(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def expect(self, out, engine, signal, ask=None):
        self.assertEqual((out["engine"], out["signal"], out["ask"]), (engine, signal, ask), out)

    def sources(self, out):
        return [entry["source"] for entry in out["evidence"]]


class RepoSignalsTest(EngineTestCase):
    def test_a_driver_in_dependencies_decides(self):
        self.write("package.json", package_json(dependencies=["mysql2"]))
        out = self.detect()
        self.expect(out, "mysql", "repo")
        self.assertEqual(out["evidence"], [{"signal": "repo", "engine": "mysql", "source": "dependency mysql2"}])

    def test_a_dev_dependencies_driver_decides(self):
        self.write("package.json", package_json(dev_dependencies=["better-sqlite3"]))
        self.expect(self.detect(), "sqlite", "repo")

    def test_every_driver_maps_to_its_engine(self):
        cases = {
            "pg": "postgres", "postgres": "postgres", "pg-promise": "postgres", "mysql": "mysql",
            "mysql2": "mysql", "better-sqlite3": "sqlite", "sqlite3": "sqlite", "mssql": "sqlserver",
            "tedious": "sqlserver", "oracledb": "oracle",
        }
        for driver, engine in cases.items():
            with self.subTest(driver=driver):
                self.write("package.json", package_json(dependencies=[driver]))
                self.expect(self.detect(), engine, "repo")

    def test_a_connection_string_decides(self):
        self.write(".env.example", "DATABASE_URL=" + FAKE_URL + "\n")
        out = self.detect()
        self.expect(out, "mysql", "repo")
        self.assertEqual(out["evidence"][0]["source"], "scheme mysql:// in .env.example")

    def test_every_scheme_maps_to_its_engine(self):
        cases = {
            "postgres://u:p@h.invalid/d": "postgres", "postgresql://u:p@h.invalid/d": "postgres",
            "mysql://u:p@h.invalid/d": "mysql", "sqlite:///data/app.db": "sqlite",
            "mssql://u:p@h.invalid/d": "sqlserver", "sqlserver://u:p@h.invalid/d": "sqlserver",
            "POSTGRES://u:p@h.invalid/d": "postgres",
        }
        for url, engine in cases.items():
            with self.subTest(url=url):
                self.write("config.txt", "url = " + url + "\n")
                self.expect(self.detect(), engine, "repo")

    def test_a_mysql2_scheme_is_not_mysql_and_a_word_before_a_scheme_blocks_it(self):
        self.write("config.txt", "a = mysql2://u:p@h.invalid/d\nb = xmysql://u:p@h.invalid/d\n")
        self.expect(self.detect(), "postgres", "default")

    def test_the_connection_string_never_appears_in_the_output(self):
        self.write(".env", "DATABASE_URL=" + FAKE_URL + "\n")
        self.write("package.json", package_json(dependencies=["mysql2"]))
        result = self.run_script()
        for secret in (FAKE_URL, "Sup3rSecret", "db.example.invalid", "app_user"):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, result.stdout)

    def test_a_driver_in_a_sub_folder_package_json_is_no_signal(self):
        self.write("services/api/package.json", package_json(dependencies=["mysql2"]))
        self.expect(self.detect(), "postgres", "default")

    def test_skipped_folders_and_dot_folders_are_not_searched(self):
        self.write("node_modules/x/c.txt", "mysql://u:p@h.invalid/d\n")
        self.write(".git/c.txt", "mysql://u:p@h.invalid/d\n")
        self.write("dist/c.txt", "mysql://u:p@h.invalid/d\n")
        self.expect(self.detect(), "postgres", "default")

    def test_a_binary_file_is_not_searched(self):
        with open(os.path.join(self.repo, "blob.bin"), "wb") as handle:
            handle.write(b"\0\0mysql://u:p@h.invalid/d\n")
        self.expect(self.detect(), "postgres", "default")

    def test_the_file_limit_is_1000_in_sorted_order(self):
        for index in range(1000):
            self.write("f%04d.txt" % index, "nothing\n")
        self.write("g-last.txt", "mysql://u:p@h.invalid/d\n")
        self.expect(self.detect(), "postgres", "default")

    def test_a_file_inside_the_limit_is_searched(self):
        for index in range(999):
            self.write("f%04d.txt" % index, "nothing\n")
        self.write("g-last.txt", "mysql://u:p@h.invalid/d\n")
        self.expect(self.detect(), "mysql", "repo")

    def test_no_signal_at_all_gives_postgres_by_default(self):
        self.expect(self.detect(), "postgres", "default")
        self.assertEqual(self.detect()["evidence"], [])

    def test_two_engines_in_a_repo_level_call_need_a_question(self):
        self.write("package.json", package_json(dependencies=["pg", "mysql2"]))
        self.expect(self.detect(), None, None, "no_signal")

    def test_two_engines_in_a_repo_level_call_and_a_request_the_request_decides(self):
        self.write("package.json", package_json(dependencies=["pg", "mysql2"]))
        self.expect(self.detect("--request", "sqlite"), "sqlite", "request")

    def test_a_repo_engine_against_a_different_request_is_a_clash(self):
        self.write("package.json", package_json(dependencies=["mysql2"]))
        out = self.detect("--request", "sqlite")
        self.expect(out, None, None, "clash")
        self.assertEqual(len(out["evidence"]), 2)

    def test_a_request_with_the_repo_engine_is_no_clash(self):
        self.write("package.json", package_json(dependencies=["mysql2"]))
        self.expect(self.detect("--request", "MySQL"), "mysql", "repo")


class RequestTest(EngineTestCase):
    def test_a_request_alone_decides_and_is_lowercase(self):
        self.expect(self.detect("--request", "MariaDB"), "mariadb", "request")

    def test_postgres_names_mean_postgres_in_any_case(self):
        for word in ("postgres", "postgresql", "PostgreSQL", "Postgres", "POSTGRESQL"):
            with self.subTest(word=word):
                self.expect(self.detect("--request", word), "postgres", "request")

    def test_an_unknown_engine_is_kept_in_lowercase(self):
        self.expect(self.detect("--request", "ExampleSQL"), "examplesql", "request")

    def test_an_empty_request_is_a_usage_error(self):
        result = self.run_script("--request", " ")
        self.assertEqual((result.returncode, result.stdout), (2, ""))


class RulesFileTest(EngineTestCase):
    def test_the_name_decides(self):
        self.rules('[engine]\nname = "MySQL"\n')
        out = self.detect()
        self.expect(out, "mysql", "name")
        self.assertEqual(out["evidence"], [{"signal": "name", "engine": "mysql", "source": "engine.name"}])

    def test_postgresql_in_the_name_is_postgres(self):
        self.rules('[engine]\nname = " PostgreSQL "\n')
        self.expect(self.detect(), "postgres", "name")

    def test_the_name_wins_over_a_different_request_with_no_question(self):
        self.rules('[engine]\nname = "mysql"\n')
        self.expect(self.detect("--request", "sqlite"), "mysql", "name")

    def test_the_name_wins_over_a_different_repo_engine_and_import(self):
        self.rules('[engine]\nname = "mysql"\n')
        self.write("package.json", package_json(dependencies=["pg"]))
        self.write("src/a.ts", "import { Client } from 'pg';\n")
        self.expect(self.detect("--file", "src/a.ts"), "mysql", "name")

    def test_paths_decide_a_file_and_win_over_the_name(self):
        self.rules('[engine]\nname = "postgres"\npaths = ["db/reporting=MySQL"]\n')
        self.expect(self.detect("--file", "db/reporting/q.sql"), "mysql", "paths")
        self.expect(self.detect("--file", "db/other/q.sql"), "postgres", "name")

    def test_the_longest_folder_wins_and_the_folder_form_is_cleaned(self):
        self.rules('[engine]\npaths = ["./db/=postgres", "db/reporting/=mysql", "./=sqlite"]\n')
        out = self.detect("--file", "db/reporting/q.sql")
        self.expect(out, "mysql", "paths")
        self.assertEqual(out["evidence"][0]["source"], "engine.paths db/reporting=mysql")
        self.expect(self.detect("--file", "db/q.sql"), "postgres", "paths")
        self.expect(self.detect("--file", "other/q.sql"), "sqlite", "paths")

    def test_a_folder_name_is_matched_whole_and_case_sensitive(self):
        self.rules('[engine]\npaths = ["db=mysql"]\n')
        self.expect(self.detect("--file", "db2/q.sql"), "postgres", "default")
        self.expect(self.detect("--file", "DB/q.sql"), "postgres", "default")

    def test_the_first_entry_of_a_repeated_folder_wins(self):
        self.rules('[engine]\npaths = ["db=mysql", "db=sqlite"]\n')
        self.expect(self.detect("--file", "db/q.sql"), "mysql", "paths")

    def test_paths_are_not_used_without_a_file(self):
        self.rules('[engine]\npaths = ["db=mysql"]\n')
        self.expect(self.detect(), "postgres", "default")

    def test_a_malformed_name_is_ignored(self):
        for value in ("5", '""', '"  "', "[]"):
            with self.subTest(value=value):
                self.rules("[engine]\nname = " + value + "\n")
                self.expect(self.detect(), "postgres", "default")

    def test_a_malformed_paths_entry_is_ignored_and_a_valid_one_still_works(self):
        self.rules(
            '[engine]\npaths = ["nothing", "=mysql", "db=", "/db=mysql", "../db=mysql", "a/../db=mysql", 5, "db=sqlite"]\n'
        )
        self.expect(self.detect("--file", "db/q.sql"), "sqlite", "paths")

    def test_paths_that_is_not_a_list_is_ignored(self):
        self.rules('[engine]\npaths = "db=mysql"\n')
        self.expect(self.detect("--file", "db/q.sql"), "postgres", "default")

    def test_an_engine_value_that_is_not_a_table_is_ignored(self):
        self.write("docs/agents/sql.md", rules_text('engine = "mysql"\n'))
        self.expect(self.detect(), "postgres", "default")

    def test_a_broken_rules_file_gives_no_signal(self):
        self.write("docs/agents/sql.md", rules_text("[engine\nname = 1\n"))
        self.expect(self.detect(), "postgres", "default")


class FileTest(EngineTestCase):
    def test_a_driver_import_decides(self):
        self.write("src/a.ts", "import mysql from 'mysql2';\n")
        out = self.detect("--file", "src/a.ts")
        self.expect(out, "mysql", "import")
        self.assertEqual(out["evidence"][0]["source"], "import mysql2 in src/a.ts")

    def test_import_forms(self):
        forms = {
            "subpath": "import { createPool } from 'mysql2/promise';",
            "require": "const db = require(\"mysql2\");",
            "dynamic": "const m = await import('mysql2');",
            "side effect": "import 'mysql2';",
            "export from": "export * from 'mysql2';",
            "type import": "import type { Pool } from 'mysql2/promise';",
            "multi line": "import {\n  a,\n  b,\n} from 'mysql2';",
        }
        for name, line in forms.items():
            with self.subTest(form=name):
                self.write("a.ts", line + "\n")
                self.expect(self.detect("--file", "a.ts"), "mysql", "import")

    def test_a_driver_name_in_a_comment_is_no_import(self):
        self.write("a.ts", "// import mysql from 'mysql2';\n/* const x = require('mysql2'); */\nconst y = 1;\n")
        self.expect(self.detect("--file", "a.ts"), "postgres", "default")

    def test_a_driver_name_in_a_string_that_looks_like_a_comment_is_kept(self):
        self.write("a.ts", "const url = 'http://x.invalid'; import m from 'mysql2';\n")
        self.expect(self.detect("--file", "a.ts"), "mysql", "import")

    def test_a_relative_or_scoped_module_is_no_import(self):
        self.write("a.ts", "import a from './mysql2';\nimport b from '@scope/mysql2';\nimport c from 'mysql2-extra';\n")
        self.expect(self.detect("--file", "a.ts"), "postgres", "default")

    def test_a_sql_file_has_no_import(self):
        self.write("q.sql", "select 1; -- import x from 'mysql2'\n")
        self.expect(self.detect("--file", "q.sql"), "postgres", "default")

    def test_a_file_with_two_engines_gives_no_import_signal(self):
        self.write("a.ts", "import a from 'pg';\nimport b from 'mysql2';\n")
        self.write("package.json", package_json(dependencies=["sqlite3"]))
        out = self.detect("--file", "a.ts")
        self.expect(out, "sqlite", "repo")
        self.assertEqual(
            [entry["source"] for entry in out["evidence"] if entry["signal"] == "import"],
            ["import mysql2 in a.ts", "import pg in a.ts"],
        )

    def test_a_missing_file_has_no_import(self):
        self.expect(self.detect("--file", "nothing/here.ts"), "postgres", "default")

    def test_an_import_against_a_request_is_a_clash(self):
        self.write("a.ts", "import mysql from 'mysql2';\n")
        self.expect(self.detect("--file", "a.ts", "--request", "sqlite"), None, None, "clash")

    def test_an_import_that_differs_from_the_repo_engine_wins_with_no_question(self):
        self.write("package.json", package_json(dependencies=["pg"]))
        self.write("a.ts", "import mysql from 'mysql2';\n")
        self.expect(self.detect("--file", "a.ts"), "mysql", "import")

    def test_a_request_equal_to_the_import_is_no_clash(self):
        self.write("a.ts", "import mysql from 'mysql2';\n")
        self.expect(self.detect("--file", "a.ts", "--request", "mysql"), "mysql", "import")

    def test_two_engines_and_a_file_with_no_signal_need_a_question(self):
        self.write("package.json", package_json(dependencies=["pg", "mysql2"]))
        self.write("q.sql", "select 1;\n")
        self.expect(self.detect("--file", "q.sql"), None, None, "no_signal")

    def test_two_engines_a_file_with_no_signal_and_a_request_the_request_decides(self):
        self.write("package.json", package_json(dependencies=["pg", "mysql2"]))
        self.expect(self.detect("--file", "q.sql", "--request", "oracle"), "oracle", "request")

    def test_two_engines_and_an_import_decide_with_no_question(self):
        self.write("package.json", package_json(dependencies=["pg", "mysql2"]))
        self.write("a.ts", "import mysql from 'mysql2';\n")
        self.expect(self.detect("--file", "a.ts"), "mysql", "import")

    def test_one_repo_engine_decides_a_file_with_no_import(self):
        self.write("package.json", package_json(dependencies=["mysql2"]))
        self.expect(self.detect("--file", "q.sql"), "mysql", "repo")

    def test_an_absolute_file_path_inside_the_repo_works(self):
        self.write("a.ts", "import mysql from 'mysql2';\n")
        self.expect(self.detect("--file", os.path.join(os.path.realpath(self.repo), "a.ts")), "mysql", "import")


class UsageTest(EngineTestCase):
    def assert_usage_error(self, result):
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.strip().splitlines()), 1)

    def test_a_file_outside_the_repo_is_a_usage_error(self):
        self.assert_usage_error(self.run_script("--file", "/etc/hosts"))

    def test_a_file_that_leaves_the_repo_through_dotdot_is_a_usage_error(self):
        self.assert_usage_error(self.run_script("--file", "a/../../b.ts"))

    def test_an_empty_file_is_a_usage_error(self):
        self.assert_usage_error(self.run_script("--file", " "))

    def test_a_repo_that_is_not_a_folder_is_a_usage_error(self):
        self.assert_usage_error(self.run_script(repo=os.path.join(self.repo, "missing")))

    def test_no_repo_is_a_usage_error(self):
        result = subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True)
        self.assert_usage_error(result)

    def test_an_unknown_option_is_a_usage_error(self):
        self.assert_usage_error(self.run_script("--other", "x"))


if __name__ == "__main__":
    unittest.main()
