import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
SCRIPT = os.path.join(SKILL_DIR, "scripts", "run_formatter.py")

# A fake tool. It reads `<its own path>.json` for its behavior and appends one JSON line with its
# argv, its working folder and its stdin to `<its own path>.log`.
FAKE = """#!{python}
import json, os, re, sys
me = os.path.abspath(sys.argv[0])
config = json.load(open(me + ".json"))
text = sys.stdin.read()
with open(me + ".log", "a") as log:
    log.write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd(), "stdin": text}}) + "\\n")
mode = config.get("mode", "replace")
if mode == "exit":
    sys.stderr.write(config.get("stderr", "boom") + "\\n")
    sys.exit(config.get("code", 1))
if mode == "parse":
    sys.stderr.write("Parse error: Unexpected token\\n")
    sys.stdout.write(text)
    sys.exit(0)
if mode == "grow":
    text = re.sub(r"SELECT( *)", lambda m: "SELECT" + m.group(1) + " ", text)
for old, new in config.get("replace", []):
    text = text.replace(old, new)
sys.stdout.write(text)
"""

TS_FILE = """import postgres from "postgres";
const sql = postgres();

export const one = () => sql`select 1`;

export const two = (id: number) => sql`
  select a from t where id = ${id}
`;

export const three = () => sql`select 3`;
"""

SQL_FILE = "select 1;\n\nselect a\nfrom t where id = ${id};\nselect 2;\n"


class RunnerTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = os.path.join(self._tmp.name, "repo")
        self.bin = os.path.join(self._tmp.name, "bin")
        self.out = os.path.join(self._tmp.name, "out.txt")
        os.makedirs(self.repo)
        os.makedirs(self.bin)

    def write(self, name, text):
        path = os.path.join(self.repo, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def read(self, path):
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def fake(self, command, local=False, **config):
        folder = os.path.join(self.repo, "node_modules", ".bin") if local else self.bin
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, command)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(FAKE.format(python=sys.executable))
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        with open(path + ".json", "w", encoding="utf-8") as handle:
            json.dump(config, handle)
        return path

    def calls(self, path):
        if not os.path.exists(path + ".log"):
            return []
        with open(path + ".log", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]

    def snapshot(self):
        state = {}
        for folder, _, files in os.walk(self.repo):
            for name in files:
                path = os.path.join(folder, name)
                if os.sep + "node_modules" + os.sep in path:
                    continue
                with open(path, "rb") as handle:
                    state[path] = handle.read()
        return state

    def run_runner(self, file, tool, *ranges, output=None, extra=()):
        command = [sys.executable, SCRIPT, self.repo, file, "--tool", tool]
        for item in ranges:
            command += ["--range", item]
        command += ["--output", output or self.out, *extra]
        env = dict(os.environ)
        env["PATH"] = self.bin + os.pathsep + env["PATH"]
        return subprocess.run(command, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env)

    def run_ok(self, file, tool, *ranges, **kwargs):
        before = self.snapshot()
        result = self.run_runner(file, tool, *ranges, **kwargs)
        self.assertEqual(self.snapshot(), before, "the repo changed")
        out = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0 if out["ok"] else 1, result.stderr)
        return out

    def assert_failed(self, out, check):
        self.assertFalse(out["ok"])
        self.assertEqual(out["check"], check)
        self.assertTrue(out["reason"])
        self.assertIsNone(out["output"])
        self.assertEqual(out["ranges"], [])
        self.assertFalse(os.path.exists(self.out))


class StableRunTest(RunnerTestCase):
    def test_only_the_target_statement_changes_and_other_lines_stay_byte_for_byte(self):
        self.write("store.ts", TS_FILE)
        self.fake("prettier", local=True, replace=[["select", "SELECT"]])
        out = self.run_ok("store.ts", "prettier-plugin-embed", "6-8")
        self.assertTrue(out["ok"], out)
        self.assertIsNone(out["check"])
        self.assertIsNone(out["reason"])
        self.assertTrue(out["changed"])
        self.assertEqual(out["tool"], "prettier-plugin-embed")
        self.assertEqual(out["output"], self.out)
        expected = TS_FILE.replace("  select a from t where id = ${id}", "  SELECT a from t where id = ${id}")
        self.assertEqual(self.read(self.out), expected)
        self.assertEqual(out["ranges"], [{"start": 6, "end": 8, "new_start": 6, "new_end": 8}])

    def test_the_prettier_command_line(self):
        self.write("src/store.ts", TS_FILE)
        tool = self.fake("prettier", local=True, replace=[["select", "SELECT"]])
        self.run_ok("src/store.ts", "prettier-plugin-embed", "6-8")
        calls = self.calls(tool)
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertEqual(call["argv"], ["--stdin-filepath", os.path.join("src", "store.ts")])
            self.assertEqual(os.path.realpath(call["cwd"]), os.path.realpath(self.repo))
        self.assertEqual(calls[0]["stdin"], TS_FILE)

    def test_the_second_pass_gets_the_first_pass_output(self):
        self.write("store.ts", TS_FILE)
        tool = self.fake("prettier", local=True, replace=[["select", "SELECT"]])
        self.run_ok("store.ts", "prettier-plugin-embed", "6-8")
        calls = self.calls(tool)
        self.assertEqual(calls[1]["stdin"], TS_FILE.replace("select", "SELECT"))

    def test_a_run_that_changes_nothing_is_ok_and_unchanged(self):
        self.write("store.ts", TS_FILE)
        self.fake("prettier", local=True, replace=[])
        out = self.run_ok("store.ts", "prettier-plugin-embed", "6-8")
        self.assertTrue(out["ok"])
        self.assertFalse(out["changed"])
        self.assertEqual(self.read(self.out), TS_FILE)

    def test_the_tool_can_change_the_line_count_of_the_target(self):
        self.write("store.ts", TS_FILE)
        self.fake("prettier", local=True, replace=[["select a from t where id = ${id}", "SELECT a\n  FROM t\n  WHERE id = ${id}"]])
        out = self.run_ok("store.ts", "prettier-plugin-embed", "6-8", "10-10")
        self.assertTrue(out["ok"], out)
        self.assertEqual(
            out["ranges"],
            [{"start": 6, "end": 8, "new_start": 6, "new_end": 10},
             {"start": 10, "end": 10, "new_start": 12, "new_end": 12}],
        )
        self.assertEqual(len(self.read(self.out).split("\n")), len(TS_FILE.split("\n")) + 2)

    def test_two_targets_are_both_spliced_and_the_gap_stays(self):
        self.write("store.ts", TS_FILE)
        self.fake("prettier", local=True, replace=[["select", "SELECT"]])
        out = self.run_ok("store.ts", "prettier-plugin-embed", "4-4", "10-10")
        self.assertTrue(out["ok"], out)
        expected = TS_FILE.replace("sql`select 1`", "sql`SELECT 1`").replace("sql`select 3`", "sql`SELECT 3`")
        self.assertEqual(self.read(self.out), expected)

    def test_a_range_may_hold_several_statements(self):
        self.write("q.sql", SQL_FILE)
        self.fake("pg_format", replace=[["select", "SELECT"]])
        out = self.run_ok("q.sql", "pgFormatter", "3-5")
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.read(self.out), SQL_FILE.replace("select a", "SELECT a").replace("select 2", "SELECT 2"))
        self.assertEqual(
            out["ranges"],
            [{"start": 3, "end": 4, "new_start": 3, "new_end": 4}, {"start": 5, "end": 5, "new_start": 5, "new_end": 5}],
        )

    def test_the_tags_option_reaches_the_extractor(self):
        self.write("store.ts", TS_FILE.replace("sql`select 1`", "db`select 1`"))
        self.fake("prettier", local=True, replace=[["select", "SELECT"]])
        out = self.run_ok("store.ts", "prettier-plugin-embed", "4-4", extra=["--tags", "db"])
        self.assertTrue(out["ok"], out)
        self.assertIn("db`SELECT 1`", self.read(self.out))

    def test_a_missing_final_newline_of_the_original_is_kept_outside_the_target(self):
        self.write("q.sql", "select 1;\nselect 2;")
        self.fake("pg_format", replace=[["select 1", "SELECT 1"]])
        out = self.run_ok("q.sql", "pgFormatter", "1-1")
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.read(self.out), "SELECT 1;\nselect 2;")

    def test_the_output_is_overwritten(self):
        self.write("store.ts", TS_FILE)
        self.fake("prettier", local=True, replace=[["select", "SELECT"]])
        with open(self.out, "w") as handle:
            handle.write("old")
        self.run_ok("store.ts", "prettier-plugin-embed", "6-8")
        self.assertIn("SELECT", self.read(self.out))


class FailedCheckTest(RunnerTestCase):
    def test_a_tool_that_exits_with_an_error(self):
        self.write("store.ts", TS_FILE)
        self.fake("prettier", local=True, mode="exit", code=2)
        self.assert_failed(self.run_ok("store.ts", "prettier-plugin-embed", "6-8"), "tool_error")

    def test_a_tool_that_exits_with_an_error_on_the_second_pass(self):
        self.write("store.ts", TS_FILE)
        path = self.fake("prettier", local=True, replace=[["select", "SELECT"]])
        # the second call fails: the number of log lines decides
        script = open(path, encoding="utf-8").read().replace(
            'mode = config.get("mode", "replace")',
            'mode = "exit" if os.path.exists(me + ".log") and len(open(me + ".log").readlines()) > 1 else "replace"',
        )
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(script)
        self.assert_failed(self.run_ok("store.ts", "prettier-plugin-embed", "6-8"), "tool_error")

    def test_a_tool_that_prints_a_parse_failure_exits_zero_and_leaves_the_file_unchanged(self):
        self.write("store.ts", TS_FILE)
        self.fake("prettier", local=True, mode="parse")
        self.assert_failed(self.run_ok("store.ts", "prettier-plugin-embed", "6-8"), "parse_failure")

    def test_a_tool_that_is_not_idempotent(self):
        self.write("q.sql", "SELECT 1;\nSELECT 2;\n")
        self.fake("pg_format", mode="grow")
        self.assert_failed(self.run_ok("q.sql", "pgFormatter", "1-1"), "not_stable")

    def test_an_interpolation_change(self):
        self.write("store.ts", TS_FILE)
        self.fake("prettier", local=True, replace=[["${id}", "${ id }"]])
        self.assert_failed(self.run_ok("store.ts", "prettier-plugin-embed", "6-8"), "interpolation_changed")

    def test_a_dropped_interpolation(self):
        self.write("store.ts", TS_FILE)
        self.fake("prettier", local=True, replace=[["where id = ${id}", "where id = 1"]])
        self.assert_failed(self.run_ok("store.ts", "prettier-plugin-embed", "6-8"), "interpolation_changed")

    def test_a_keyword_position_interpolation(self):
        self.write("store.ts", "const sql = postgres();\nconst x = sql`${sel} * from t`;\n")
        tool = self.fake("prettier", local=True, replace=[])
        self.assert_failed(self.run_ok("store.ts", "prettier-plugin-embed", "2-2"), "keyword_position")
        self.assertEqual(self.calls(tool), [])

    def test_the_tool_command_is_missing(self):
        self.write("store.ts", TS_FILE)
        out = self.run_ok("store.ts", "prettier-plugin-embed", "6-8")
        self.assert_failed(out, "tool_missing")

    def test_the_tool_output_that_the_extractor_cannot_read(self):
        self.write("store.ts", TS_FILE)
        self.fake("prettier", local=True, replace=[["select a", "`select a"]])
        self.assert_failed(self.run_ok("store.ts", "prettier-plugin-embed", "6-8"), "extract")

    def test_a_statement_count_change(self):
        self.write("q.sql", "select 1;\nselect 2;\n")
        self.fake("pg_format", replace=[["select 1;", "select 1"]])
        self.assert_failed(self.run_ok("q.sql", "pgFormatter", "1-1"), "extract")

    def test_a_file_that_the_extractor_cannot_read_fails_on_the_original(self):
        self.write("store.ts", "const x = sql`select 1;\n")
        self.fake("prettier", local=True, replace=[])
        out = self.run_ok("store.ts", "prettier-plugin-embed", "1-1")
        self.assertFalse(out["ok"])
        self.assertEqual(out["check"], "extract")

    def test_a_neighbor_that_ends_up_on_a_line_of_the_target_in_the_output(self):
        self.write("q.sql", "select 1;\nselect 2;\nselect 3;\n")
        self.fake("pg_format", replace=[["select 1;\n", "select 1; "]])
        out = self.run_ok("q.sql", "pgFormatter", "1-1")
        self.assert_failed(out, "shared_line")

    def test_a_failed_run_never_writes_the_output_or_the_repo(self):
        self.write("store.ts", TS_FILE)
        self.fake("prettier", local=True, mode="exit")
        before = self.snapshot()
        self.run_runner("store.ts", "prettier-plugin-embed", "6-8")
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(os.path.exists(self.out))


class UnwritableOutputTest(RunnerTestCase):
    def test_an_output_that_cannot_be_written_is_a_failed_run_with_json(self):
        self.write("store.ts", TS_FILE)
        self.fake("prettier", local=True, replace=[["select", "SELECT"]])
        missing = os.path.join(self._tmp.name, "no-such-folder", "out.txt")
        before = self.snapshot()
        result = self.run_runner("store.ts", "prettier-plugin-embed", "6-8", output=missing)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        out = json.loads(result.stdout)
        self.assertFalse(out["ok"])
        self.assertEqual(out["check"], "tool_error")
        self.assertIn("output", out["reason"])
        self.assertIsNone(out["output"])
        self.assertEqual(out["ranges"], [])
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(os.path.exists(missing))


class SqlfluffTest(RunnerTestCase):
    def test_sqlfluff_never_runs_on_a_target_with_an_interpolation(self):
        self.write("q.sql", SQL_FILE)
        tool = self.fake("sqlfluff", replace=[["select", "SELECT"]])
        self.assert_failed(self.run_ok("q.sql", "sqlfluff", "3-4"), "sqlfluff_placeholder")
        self.assertEqual(self.calls(tool), [])

    def test_sqlfluff_runs_on_a_target_without_an_interpolation(self):
        self.write("q.sql", SQL_FILE)
        tool = self.fake("sqlfluff", replace=[["select", "SELECT"]])
        out = self.run_ok("q.sql", "sqlfluff", "1-1")
        self.assertTrue(out["ok"], out)
        for call in self.calls(tool):
            self.assertEqual(call["argv"], ["fix", "-", "--stdin-filename", "q.sql"])

    def test_sqlfluff_checks_the_interpolation_only_for_the_target(self):
        self.write("q.sql", SQL_FILE)
        self.fake("sqlfluff", replace=[["select 1", "SELECT 1"]])
        self.assertTrue(self.run_ok("q.sql", "sqlfluff", "1-1")["ok"])


class PlaceholderConfigTest(RunnerTestCase):
    PATTERN = r"\$\{[^}]*\}"

    def test_pg_format_gets_the_placeholder_pattern_and_the_repo_config(self):
        self.write("q.sql", SQL_FILE)
        self.write(".pg_format", "keyword-case=2\n")
        tool = self.fake("pg_format", replace=[["select a", "SELECT a"]])
        out = self.run_ok("q.sql", "pgFormatter", "3-4")
        self.assertTrue(out["ok"], out)
        for call in self.calls(tool):
            self.assertEqual(call["argv"], ["-c", os.path.join(self.repo, ".pg_format"), "-p", self.PATTERN, "-"])
        self.assertIn("${id}", self.read(self.out))

    def test_pg_format_with_no_interpolation_and_no_config_file_gets_only_stdin(self):
        self.write("q.sql", SQL_FILE)
        tool = self.fake("pg_format", replace=[["select 1", "SELECT 1"]])
        self.run_ok("q.sql", "pgFormatter", "1-1")
        for call in self.calls(tool):
            self.assertEqual(call["argv"], ["-"])

    def test_pg_format_with_a_config_file_and_no_interpolation_gets_no_pattern(self):
        self.write("q.sql", SQL_FILE)
        self.write(".pg_format", "")
        tool = self.fake("pg_format", replace=[["select 1", "SELECT 1"]])
        self.run_ok("q.sql", "pgFormatter", "1-1")
        for call in self.calls(tool):
            self.assertEqual(call["argv"], ["-c", os.path.join(self.repo, ".pg_format"), "-"])

    def test_sql_formatter_gets_a_config_with_the_placeholder_and_keeps_the_repo_config(self):
        self.write("q.sql", SQL_FILE)
        self.write(".sql-formatter.json", json.dumps({
            "language": "postgresql", "keywordCase": "upper",
            "paramTypes": {"custom": [{"regex": "\\{\\{x\\}\\}"}], "named": [":"]},
        }))
        tool = self.fake("sql-formatter", local=True, replace=[["select a", "SELECT a"]])
        out = self.run_ok("q.sql", "sql-formatter", "3-4")
        self.assertTrue(out["ok"], out)
        for call in self.calls(tool):
            self.assertEqual(call["argv"][0], "--config")
            self.assertEqual(len(call["argv"]), 2)
            config = json.loads(call["argv"][1])
            self.assertEqual(config["language"], "postgresql")
            self.assertEqual(config["keywordCase"], "upper")
            self.assertEqual(config["paramTypes"]["named"], [":"])
            self.assertEqual(config["paramTypes"]["custom"], [{"regex": "\\{\\{x\\}\\}"}, {"regex": self.PATTERN}])
        self.assertIn("${id}", self.read(self.out))

    def test_sql_formatter_with_no_repo_config_gets_only_the_placeholder_config(self):
        self.write("q.sql", SQL_FILE)
        tool = self.fake("sql-formatter", local=True, replace=[["select a", "SELECT a"]])
        self.run_ok("q.sql", "sql-formatter", "3-4")
        config = json.loads(self.calls(tool)[0]["argv"][1])
        self.assertEqual(config, {"paramTypes": {"custom": [{"regex": self.PATTERN}]}})

    def test_sql_formatter_with_no_interpolation_gets_no_config_option(self):
        self.write("q.sql", SQL_FILE)
        self.write(".sql-formatter.json", "{}")
        tool = self.fake("sql-formatter", local=True, replace=[["select 1", "SELECT 1"]])
        self.run_ok("q.sql", "sql-formatter", "1-1")
        for call in self.calls(tool):
            self.assertEqual(call["argv"], [])

    def test_a_repo_config_that_is_not_a_json_object_is_a_tool_error(self):
        self.write("q.sql", SQL_FILE)
        self.write(".sql-formatter.json", "[1]")
        self.fake("sql-formatter", local=True, replace=[])
        self.assert_failed(self.run_ok("q.sql", "sql-formatter", "3-4"), "tool_error")

    def test_prettier_sql_gets_no_placeholder_config(self):
        self.write("q.sql", SQL_FILE)
        tool = self.fake("prettier", local=True, replace=[["select a", "SELECT a"]])
        out = self.run_ok("q.sql", "prettier-plugin-sql", "3-4")
        self.assertTrue(out["ok"], out)
        for call in self.calls(tool):
            self.assertEqual(call["argv"], ["--stdin-filepath", "q.sql"])

    def test_a_tool_that_corrupts_a_placeholder_is_rejected(self):
        self.write("q.sql", SQL_FILE)
        self.fake("pg_format", replace=[["${id}", "$ {id}"]])
        self.assert_failed(self.run_ok("q.sql", "pgFormatter", "3-4"), "interpolation_changed")


class LookupTest(RunnerTestCase):
    def test_the_repo_local_command_wins_over_path(self):
        self.write("store.ts", TS_FILE)
        local = self.fake("prettier", local=True, replace=[["select", "SELECT"]])
        on_path = self.fake("prettier", replace=[["select", "Select"]])
        self.run_ok("store.ts", "prettier-plugin-embed", "6-8")
        self.assertTrue(self.calls(local))
        self.assertFalse(self.calls(on_path))

    def test_prettier_is_found_on_path_when_there_is_no_local_copy(self):
        self.write("store.ts", TS_FILE)
        on_path = self.fake("prettier", replace=[["select", "SELECT"]])
        self.assertTrue(self.run_ok("store.ts", "prettier-plugin-embed", "6-8")["ok"])
        self.assertTrue(self.calls(on_path))

    def test_sqlfluff_is_not_looked_up_in_node_modules(self):
        self.write("q.sql", SQL_FILE)
        self.fake("sqlfluff", local=True, replace=[])
        self.assert_failed(self.run_ok("q.sql", "sqlfluff", "1-1"), "tool_missing")


class UsageTest(RunnerTestCase):
    def assert_usage_error(self, *args, ranges=("1-1",), file="q.sql", tool="pgFormatter", output=None, extra=()):
        result = self.run_runner(file, tool, *ranges, output=output, extra=extra)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.strip().splitlines()), 1)
        self.assertFalse(os.path.exists(self.out))

    def setUp(self):
        super().setUp()
        self.write("q.sql", SQL_FILE)
        self.write("store.ts", TS_FILE)
        self.fake("pg_format", replace=[])
        self.fake("prettier", local=True, replace=[])

    def test_the_unsafe_tools_are_not_accepted(self):
        for tool in ("prettier-plugin-sql-cst", "eslint-plugin-sql", "black"):
            with self.subTest(tool=tool):
                self.assert_usage_error(file="store.ts", tool=tool, ranges=("4-4",))

    def test_a_tool_that_does_not_fit_the_form(self):
        self.assert_usage_error(file="store.ts", tool="pgFormatter", ranges=("4-4",))
        self.assert_usage_error(file="q.sql", tool="prettier-plugin-embed", ranges=("1-1",))

    def test_a_bad_range(self):
        for value in ("0-1", "3-2", "x", "1-99"):
            with self.subTest(value=value):
                self.assert_usage_error(ranges=(value,))

    def test_a_missing_range(self):
        self.assert_usage_error(ranges=())

    def test_a_range_with_no_statement(self):
        self.assert_usage_error(ranges=("2-2",))

    def test_a_range_that_crosses_a_statement_edge(self):
        self.assert_usage_error(ranges=("3-3",))
        self.assert_usage_error(ranges=("4-5",))

    def test_the_output_may_not_be_the_file(self):
        self.assert_usage_error(output=os.path.join(self.repo, "q.sql"))

    def test_a_file_outside_the_repo(self):
        other = os.path.join(self._tmp.name, "outside.sql")
        with open(other, "w") as handle:
            handle.write("select 1;\n")
        self.assert_usage_error(file=other)

    def test_a_missing_file_and_a_repo_that_is_not_a_folder(self):
        self.assert_usage_error(file="missing.sql")
        result = subprocess.run(
            [sys.executable, SCRIPT, os.path.join(self.repo, "nope"), "q.sql", "--tool", "pgFormatter",
             "--range", "1-1", "--output", self.out],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
        self.assertEqual(result.returncode, 2)

    def test_a_file_form_that_is_not_supported(self):
        self.write("notes.txt", "select 1;\n")
        self.assert_usage_error(file="notes.txt")

    def test_a_tool_and_an_output_are_required(self):
        result = subprocess.run([sys.executable, SCRIPT, self.repo, "q.sql", "--range", "1-1"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        result = subprocess.run([sys.executable, SCRIPT, self.repo, "q.sql", "--tool", "pgFormatter", "--range", "1-1"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
