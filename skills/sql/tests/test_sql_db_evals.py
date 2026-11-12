import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
EVALS = os.path.join(SKILL_DIR, "evals")
DB = os.path.join(EVALS, "db")
DRIVER_CASES = os.path.join(DB, "cases")
RULES_FILE = os.path.join(SKILL_DIR, "scripts", "rules_file.py")
README = os.path.join(EVALS, "README.md")
PLUGIN_CASES = ("db-off-allowlist", "db-bypass-refused", "db-connection-fails")
KIND = re.compile(
    r"(not_allowed|refused|connection_failed|plan|facts|analyzed|sequence_warning|downgraded|diff)(:[A-Za-z0-9_.-]+)?"
    r"|no_connection:[A-Za-z0-9_.-]+"
)
ROOT_README = os.path.join(os.path.dirname(os.path.dirname(SKILL_DIR)), "README.md")

with open(os.path.join(DB, "canaries.json"), encoding="utf-8") as handle:
    CANARIES = json.load(handle)


def slurp(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def files_under(folder):
    for current, folders, names in os.walk(folder):
        folders[:] = [name for name in folders if name not in ("__pycache__", "results")]
        for name in names:
            yield os.path.join(current, name)


def case_folders():
    return [os.path.join(EVALS, name) for name in PLUGIN_CASES] + [
        os.path.join(DRIVER_CASES, name) for name in sorted(os.listdir(DRIVER_CASES))]


class CanariesTest(unittest.TestCase):
    def test_the_keys_and_the_values(self):
        self.assertEqual(sorted(CANARIES), sorted(
            ["password", "wrong_password", "user", "dbname", "host", "host_badpw", "host_down"]))
        values = list(CANARIES.values())
        self.assertEqual(len(set(values)), len(values))
        for value in values:
            self.assertGreaterEqual(len(value), 8)

    def test_no_committed_file_holds_a_canary_value_except_canaries_json_and_the_tests(self):
        for path in files_under(SKILL_DIR):
            if path == os.path.join(DB, "canaries.json") or os.path.dirname(path) == HERE:
                continue
            try:
                text = slurp(path)
            except UnicodeDecodeError:
                continue
            for key, value in CANARIES.items():
                with self.subTest(path=os.path.relpath(path, SKILL_DIR), key=key):
                    self.assertNotIn(value, text)

    def test_the_prompts_hold_no_canary_value(self):
        for folder in case_folders():
            prompt = os.path.join(folder, "case.yaml" if os.path.exists(os.path.join(folder, "case.yaml"))
                                  else "prompt.txt")
            for value in CANARIES.values():
                with self.subTest(prompt=prompt):
                    self.assertNotIn(value, slurp(prompt))


class PluginCasesTest(unittest.TestCase):
    def case(self, name, *parts):
        return os.path.join(EVALS, name, *parts)

    def graders(self, name):
        common = ["final-message.md", "no-raw-client.md"]
        return common + (["ran-allowlist.md"] if name == "db-off-allowlist" else ["ran-pg-run.md"])

    def test_each_case_has_its_files(self):
        for name in PLUGIN_CASES:
            with self.subTest(case=name):
                for part in ("case.yaml", "scaffold.sh", "db-expect.json",
                             os.path.join("repo", "docs", "agents", "sql.md")):
                    self.assertTrue(os.path.isfile(self.case(name, part)), part)
                self.assertEqual(sorted(os.listdir(self.case(name, "graders"))), sorted(self.graders(name)))
    def test_the_case_file_sets_the_name_the_scaffold_the_tools_and_the_turns(self):
        for name in PLUGIN_CASES:
            with self.subTest(case=name):
                text = slurp(self.case(name, "case.yaml"))
                self.assertIn(f"name: {name}\n", text)
                self.assertIn("scaffold_script: scaffold.sh", text)
                self.assertIn("allowed_tools: [Skill, Read, Glob, Grep, Bash]", text)
                self.assertIn("max_turns: 20", text)
                self.assertIn('schema_version: "1.0"', text)
                self.assertIn("/sql optimize src/revenue.ts", text)
                description = re.search(r"^description: (.*)$", text, re.M).group(1)
                self.assertNotIn(": ", description)

    def test_each_case_names_its_service_or_statement(self):
        self.assertIn("`other-db`", slurp(self.case("db-off-allowlist", "case.yaml")))
        self.assertIn("`app-pg18`", slurp(self.case("db-bypass-refused", "case.yaml")))
        self.assertIn("set_config('default_transaction_read_only'",
                      slurp(self.case("db-bypass-refused", "repo", "src", "revenue.ts")))
        self.assertIn("`app-wronghost`", slurp(self.case("db-connection-fails", "case.yaml")))

    def test_the_expectations(self):
        expected = {"db-off-allowlist": ["no_connection:other-db"],
                    "db-bypass-refused": ["refused:forbidden_function"],
                    "db-connection-fails": ["connection_failed:app-wronghost"]}
        for name, kinds in expected.items():
            with self.subTest(case=name):
                self.assertEqual(json.loads(slurp(self.case(name, "db-expect.json")))["expect"], kinds)

    def test_the_graders_have_the_spec_front_matter(self):
        for name in PLUGIN_CASES:
            for grader in self.graders(name):
                with self.subTest(case=name, grader=grader):
                    text = slurp(self.case(name, "graders", grader))
                    self.assertTrue(text.startswith("---\ntype: "))
                    if grader == "no-raw-client.md":
                        self.assertIn("psql|pg_dump|pg_isready|pgcli", text)
                        self.assertIn("max: 0", text)
                    if grader == "ran-pg-run.md":
                        self.assertIn(r"pg_run\.py", text)
                        self.assertIn("min: 1", text)
                    if grader == "ran-allowlist.md":
                        self.assertIn(r"allowlist\.py", text)
                    if grader == "final-message.md":
                        self.assertIn("type: llm", text)

    def real_state(self):
        home = os.path.expanduser("~")
        state = {}
        for path in (os.path.join(home, ".pgpass"), os.path.join(home, ".pg_service.conf"),
                     os.path.join(home, ".config", "sql-skill")):
            state[path] = sorted((p, os.stat(p).st_mtime_ns) for p in (
                [path] if os.path.isfile(path) else list(files_under(path)) if os.path.isdir(path) else []))
        return state

    def test_each_scaffold_runs_in_a_temp_folder_and_writes_only_under_the_temp_home(self):
        before = self.real_state()
        for name in PLUGIN_CASES:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as root:
                work, home, xdg = (os.path.join(root, n) for n in ("work", "home", "xdg"))
                for folder in (work, home, xdg):
                    os.makedirs(folder)
                env = {"PATH": os.environ["PATH"], "HOME": home, "XDG_CONFIG_HOME": xdg}
                proc = subprocess.run(["bash", self.case(name, "scaffold.sh")], cwd=work, env=env,
                                      capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertTrue(os.path.isfile(os.path.join(work, "src", "revenue.ts")))
                self.assertTrue(os.path.isdir(os.path.join(work, ".git")))
                self.assertEqual(oct(os.stat(os.path.join(home, ".pgpass")).st_mode & 0o777), "0o600")
                self.assertTrue(os.path.isfile(os.path.join(home, ".pg_service.conf")))
                self.assertTrue(os.path.isfile(os.path.join(home, ".config", "sql-skill", "allowlist.toml")))
                self.assertEqual(os.listdir(xdg), [])
        self.assertEqual(self.real_state(), before)


class DriverCasesTest(unittest.TestCase):
    def test_each_case_has_a_prompt_an_expectation_and_a_repo_and_nothing_that_plugin_eval_finds(self):
        names = sorted(os.listdir(DRIVER_CASES))
        self.assertEqual(names, [
            "bad-password", "facts-pg-02", "plan-01-estimate", "plan-02-seq-scan", "plan-03-spill",
            "plan-04-nested-loop", "plan-05-cache", "plan-clean", "plan-disabled", "plan-select", "rewrite-no-tests",
            "rewrite-proven", "rewrite-write-unproven", "select-query-to-xml", "write-analyze", "write-dblink-trigger",
            "write-sequence", "wrong-host"])
        for name in names:
            folder = os.path.join(DRIVER_CASES, name)
            with self.subTest(case=name):
                for part in ("prompt.txt", "db-expect.json", os.path.join("repo", "docs", "agents", "sql.md")):
                    self.assertTrue(os.path.isfile(os.path.join(folder, part)), part)
                for part in ("case.yaml", "prompt.md", "graders"):
                    self.assertFalse(os.path.exists(os.path.join(folder, part)), part)


class RewriteCasesTest(unittest.TestCase):
    """The three rewrite cases of #397: `diff` kinds for the two read cases, write kinds for the write case."""

    def expectation(self, name):
        return json.loads(slurp(os.path.join(DRIVER_CASES, name, "db-expect.json")))

    def test_the_proven_case_runs_the_repo_tests_with_one_exact_command_and_checks_the_label_and_the_test_title(self):
        data = self.expectation("rewrite-proven")
        self.assertEqual(data["expect"], ["diff:app-pg13", "diff:app-pg18"])
        self.assertEqual(data["bash"], ["node --test --test-concurrency=2"])
        self.assertEqual(data["final"]["contains"], ["Rewrite (proven: database diff and repo tests):", "rewrite-proof-ok"])
        self.assertEqual(data["final"]["absent"], ["Rewrite (unproven"])
        repo = os.path.join(DRIVER_CASES, "rewrite-proven", "repo")
        self.assertTrue(os.path.isfile(os.path.join(repo, "AGENTS.md")))
        self.assertFalse(os.path.exists(os.path.join(repo, "CLAUDE.md")))
        self.assertIn("node --test", slurp(os.path.join(repo, "AGENTS.md")))
        self.assertEqual(json.loads(slurp(os.path.join(repo, "package.json")))["scripts"]["test"], "node --test")
        self.assertIn("'rewrite-proof-ok'", slurp(os.path.join(repo, "test", "query.test.js")))
        self.assertIn("PG-09", slurp(os.path.join(DRIVER_CASES, "rewrite-proven", "prompt.txt")))

    def test_the_write_case_expects_the_write_path_and_the_unproven_label(self):
        data = self.expectation("rewrite-write-unproven")
        self.assertEqual(data["expect"], ["analyzed:app-pg13", "analyzed:app-pg18"])
        self.assertNotIn("bash", data)
        self.assertEqual(data["final"]["contains"], ["Rewrite (unproven: write statement, no database diff):"])
        self.assertEqual(data["final"]["absent"], ["proven by the database diff"])
        statement = slurp(os.path.join(DRIVER_CASES, "rewrite-write-unproven", "repo", "src", "orders.ts"))
        self.assertRegex(statement, r"UPDATE shop\.orders")

    def test_the_no_tests_case_has_no_test_command_in_its_repo(self):
        data = self.expectation("rewrite-no-tests")
        self.assertEqual(data["expect"], ["diff:app-pg13", "diff:app-pg18"])
        self.assertNotIn("bash", data)
        self.assertEqual(data["final"]["contains"], [
            "Rewrite (proven by the database diff only: no repo tests ran):", "no repo tests ran"])
        repo = os.path.join(DRIVER_CASES, "rewrite-no-tests", "repo")
        for name in ("AGENTS.md", "CLAUDE.md", "package.json"):
            self.assertFalse(os.path.exists(os.path.join(repo, name)), name)


class CaseRepoTest(unittest.TestCase):
    @unittest.skipUnless(sys.version_info >= (3, 11), "the reader needs tomllib (Python 3.11 or newer)")
    def test_every_case_repo_holds_a_rules_file_that_the_reader_accepts(self):
        for folder in case_folders():
            with self.subTest(case=os.path.basename(folder)):
                repo = os.path.join(folder, "repo")
                self.assertTrue(os.path.isfile(os.path.join(repo, "docs", "agents", "sql.md")))
                proc = subprocess.run([sys.executable, "-I", RULES_FILE, repo], capture_output=True, text=True)
                data = json.loads(proc.stdout)
                self.assertTrue(data["found"])
                self.assertIsNone(data["error"])
                self.assertEqual(data["unknown_ids"], [])

    def test_every_expectation_file_holds_only_known_kinds(self):
        for folder in case_folders():
            with self.subTest(case=os.path.basename(folder)):
                data = json.loads(slurp(os.path.join(folder, "db-expect.json")))
                self.assertTrue(data["expect"])
                for kind in data["expect"]:
                    self.assertRegex(kind, KIND)
                self.assertLessEqual(
                    set(data), {"expect", "sequences_may_differ", "rules", "report", "judge", "disabled", "bash", "final"})
                if "bash" in data:
                    self.assertTrue(data["bash"] and all(isinstance(item, str) and item for item in data["bash"]))
                if "final" in data:
                    self.assertLessEqual(set(data["final"]), {"contains", "absent"})
                    for strings in data["final"].values():
                        self.assertTrue(strings and all(isinstance(item, str) and item for item in strings))
                if "report" in data:
                    self.assertIs(data["report"], True)
                if "judge" in data:
                    self.assertTrue(os.path.isfile(os.path.join(DB, data["judge"])), data["judge"])
                if "disabled" in data:
                    self.assertTrue(data["report"])
                    self.assertTrue(all(re.fullmatch(r"(PGJS|PG|PLAN)-\d\d", item) for item in data["disabled"]))
                if "rules" in data:
                    self.assertEqual(set(data["rules"]), {"expect", "forbid"})
                    for ids in data["rules"].values():
                        self.assertTrue(all(re.fullmatch(r"(PGJS|PG|PLAN)-\d\d", item) for item in ids))

    def test_no_fixture_is_a_python_test_file(self):
        for path in files_under(EVALS):
            self.assertFalse(os.path.basename(path).startswith("test_"), path)


class ReadmeTest(unittest.TestCase):
    def test_the_readme_names_the_new_graders_the_driver_and_the_sandbox_limit(self):
        text = slurp(README)
        for needle in ("grade_db_unchanged.py", "grade_refusals.py", "grade_leak_scan.py", "grade_db_eval_results.py",
                       "run_db_cases.py", "db_eval.py", "no network", "Unix socket", "db-off-allowlist",
                       "db-bypass-refused", "db-connection-fails", "plan-select", "bad-password", "wrong-host",
                       "facts-pg-02", "facts[:SERVICE]", "`rules`", "plan-01-estimate", "plan-02-seq-scan",
                       "plan-03-spill", "plan-04-nested-loop", "plan-05-cache", "plan-clean", "plan-disabled",
                       "plan_findings.py", "`report`", "`judge`", "`disabled`", "rubric-plan.md", "shop.events",
                       "canaries.json", "db-expect.json", "grader G and the leak scan", "select-query-to-xml"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def tracked_patterns(self):
        globs = re.findall(r"^\| ((?:`[^`]+`(?:, )?)+) \|", slurp(ROOT_README), re.MULTILINE)
        patterns = []
        for cell in globs:
            for glob in re.findall(r"`([^`]+)`", cell):
                regex = re.escape(glob).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
                patterns.append(re.compile(regex + r"\Z"))
        return patterns

    def test_the_tracked_table_of_the_root_readme_covers_every_file_of_the_facts_case(self):
        patterns = self.tracked_patterns()
        repo_root = os.path.dirname(os.path.dirname(SKILL_DIR))
        paths = [os.path.relpath(path, repo_root) for path in files_under(os.path.join(DRIVER_CASES, "facts-pg-02"))]
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue(any(pattern.match(path) for pattern in patterns), path)

    def test_the_tracked_table_covers_every_file_of_the_plan_findings_ticket(self):
        patterns = self.tracked_patterns()
        repo_root = os.path.dirname(os.path.dirname(SKILL_DIR))
        found = [os.path.join(SKILL_DIR, "scripts", "plan_findings.py"), os.path.join(DB, "rubric-plan.md"),
                 os.path.join(HERE, "test_sql_plan_findings.py")]
        # The fixtures sit in a subfolder of tests, as the style fixtures do: `skills/sql/tests/*` covers them
        # in the table, and the `!skills/**` line of .gitignore tracks them.
        for name in sorted(os.listdir(DRIVER_CASES)):
            if name.startswith("plan-") and name != "plan-select":
                found += list(files_under(os.path.join(DRIVER_CASES, name)))
        self.assertGreater(len(found), 20)
        for path in found:
            relative = os.path.relpath(path, repo_root)
            with self.subTest(path=relative):
                self.assertTrue(os.path.isfile(path))
                self.assertTrue(any(pattern.match(relative) for pattern in patterns), relative)


class PlanCasesTest(unittest.TestCase):
    PLAN_CASES = ("plan-01-estimate", "plan-02-seq-scan", "plan-03-spill", "plan-04-nested-loop", "plan-05-cache",
                  "plan-clean", "plan-disabled")

    def expectation(self, name):
        return json.loads(slurp(os.path.join(DRIVER_CASES, name, "db-expect.json")))

    def test_every_plan_rule_is_expected_by_a_driver_case(self):
        expected = set()
        for name in os.listdir(DRIVER_CASES):
            expected.update(self.expectation(name).get("rules", {}).get("expect", []))
        self.assertEqual(sorted(i for i in expected if i.startswith("PLAN-")), [f"PLAN-0{n}" for n in range(1, 6)])

    def test_each_rule_case_expects_its_rule_and_the_plan_of_both_services(self):
        for number, name in enumerate(self.PLAN_CASES[:5], start=1):
            with self.subTest(case=name):
                data = self.expectation(name)
                self.assertEqual(data["expect"], ["plan:app-pg13", "plan:app-pg18"])
                self.assertEqual(data["rules"], {"expect": [f"PLAN-0{number}"], "forbid": []})
                self.assertIs(data["report"], True)
                self.assertEqual(data["judge"], "rubric-plan.md")
                self.assertFalse(data["sequences_may_differ"])

    def test_the_clean_case_forbids_the_five_ids_and_has_no_judge(self):
        data = self.expectation("plan-clean")
        self.assertEqual(data["rules"], {"expect": [], "forbid": [f"PLAN-0{n}" for n in range(1, 6)]})
        self.assertNotIn("judge", data)
        self.assertIs(data["report"], True)

    def test_the_disabled_case_disables_plan_02_with_a_reason_line_and_forbids_it(self):
        data = self.expectation("plan-disabled")
        self.assertEqual(data["disabled"], ["PLAN-02"])
        self.assertEqual(data["rules"], {"expect": [], "forbid": ["PLAN-02"]})
        rules = slurp(os.path.join(DRIVER_CASES, "plan-disabled", "repo", "docs", "agents", "sql.md"))
        self.assertRegex(rules, r'(?m)^disabled = \["PLAN-02"\]$')
        self.assertRegex(rules, r"(?m)^- PLAN-02: \S")
        self.assertEqual(slurp(os.path.join(DRIVER_CASES, "plan-disabled", "repo", "src", "report.ts")),
                         slurp(os.path.join(DRIVER_CASES, "plan-02-seq-scan", "repo", "src", "report.ts")))

    def test_no_prompt_names_a_rule_id_or_an_interpolation_holds_in_a_template(self):
        for name in self.PLAN_CASES:
            with self.subTest(case=name):
                prompt = slurp(os.path.join(DRIVER_CASES, name, "prompt.txt"))
                self.assertNotRegex(prompt, r"\bPGJS-\d|\bPG-\d|\bPLAN-\d")
                self.assertIn("plan_findings.py", prompt)
                self.assertRegex(prompt, r"(?i)no `cd`, no `&&`, no `;` and no heredoc")
                template = slurp(os.path.join(DRIVER_CASES, name, "repo", "src", "report.ts"))
                self.assertEqual(template.count("sql`"), 1)
                self.assertNotIn("${", template)

    def test_the_rubric_asks_for_one_score_line(self):
        text = slurp(os.path.join(DB, "rubric-plan.md"))
        self.assertIn("SCORE: <n>/5", text)


if __name__ == "__main__":
    unittest.main()
