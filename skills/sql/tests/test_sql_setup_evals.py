import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL_DIR, "scripts")
EVALS = os.path.join(SKILL_DIR, "evals")
GRADER = os.path.join(SKILL_DIR, "graders", "grade_setup.py")
SETUP = os.path.join(SKILL_DIR, "setup.md")
sys.path.insert(0, SCRIPTS)


CASES = ("setup-tags-fixture", "setup-no-sql", "setup-rerun")
KEY = "example.com/acme/shop"
SCRIPT_NAMES = (
    "rules_file.py", "allowlist.py", "setup_scan.py", "measure_style.py", "detect_formatter.py",
    "formatter_install.py", "setup_files.py",
)
STEPS = ("Step 1: Detect", "Step 2: Tags", "Step 3: Style and formatter", "Step 4: Allowlist",
         "Step 5: Interview", "Step 6: Write", "Step 7: Report")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def case_path(case, *parts):
    return os.path.join(EVALS, case, *parts)


class SetupModuleTest(unittest.TestCase):
    def test_setup_is_no_longer_a_stub_and_names_every_script(self):
        text = read(SETUP)
        self.assertNotIn("Stub.", text)
        self.assertNotIn("#398", text)
        for name in SCRIPT_NAMES:
            with self.subTest(script=name):
                self.assertIn(name, text)

    def test_the_steps_come_in_the_order_of_the_flow(self):
        text = read(SETUP)
        positions = [text.index("## " + step) for step in STEPS]
        self.assertEqual(positions, sorted(positions))

    def test_the_commands_of_the_flow(self):
        text = read(SETUP)
        for command in (
            "setup_scan.py <repo root>", "--tags <confirmed tags>", "setup_files.py services",
            "setup_files.py plan", "setup_files.py write", "--confirm <digest>", "formatter_install.py offer",
            "formatter_install.py apply", "--form <template|sql>",
        ):
            with self.subTest(command=command):
                self.assertIn(command, text)

    def test_the_rules_of_the_flow(self):
        text = read(SETUP).lower()
        for phrase in (
            "own approval", "before the final confirmation", "write_failed", "stale_digest",
            "never read the pg password file", "system temp folder", "no change", "stop",
            "confirm the list or to edit it", "no `--tags` option", "keep the current `[rules] disabled`",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)


class CaseFilesTest(unittest.TestCase):
    def test_each_case_has_its_files(self):
        for case in CASES:
            with self.subTest(case=case):
                for name in ("case.yaml", "scaffold.sh", "expected.json"):
                    self.assertTrue(os.path.isfile(case_path(case, name)), name)
                self.assertTrue(os.path.isdir(case_path(case, "repo")))
                graders = [n for n in os.listdir(case_path(case, "graders")) if n.endswith(".md")]
                self.assertTrue(graders)
                yaml = read(case_path(case, "case.yaml"))
                self.assertIn("name: " + case, yaml)
                self.assertRegex(yaml, r"(?m)^  max_turns: 30$")
                self.assertIn("allowed_tools: [Skill, Read, Glob, Grep, Bash, Edit, Write]", yaml)
                self.assertIn("scaffold_script: scaffold.sh", yaml)
                types = {re.search(r"(?m)^type: (\w+)$", read(case_path(case, "graders", n))).group(1) for n in graders}
                self.assertEqual(types, {"tool_used", "llm"})

    def test_the_fixtures_hold_no_test_files(self):
        for case in CASES:
            for folder, _, files in os.walk(case_path(case)):
                for name in files:
                    self.assertFalse(name.startswith("test_"), os.path.join(folder, name))

    def test_the_tool_used_graders_name_a_real_script(self):
        for case in CASES:
            for name in os.listdir(case_path(case, "graders")):
                text = read(case_path(case, "graders", name))
                match = re.search(r"(?m)^input_match: '(.*)'$", text)
                if match:
                    re.compile(match.group(1))


class ScaffoldTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.work = os.path.join(self.tmp, "work")
        self.home = os.path.join(self.tmp, "home")
        self.xdg = os.path.join(self.tmp, "xdg")
        for folder in (self.work, self.home, self.xdg):
            os.makedirs(folder)
        self.env = dict(os.environ, HOME=self.home, XDG_CONFIG_HOME=self.xdg)

    def scaffold(self, case, env=None, check=True):
        done = subprocess.run(
            ["bash", case_path(case, "scaffold.sh")], cwd=self.work, env=env or self.env, capture_output=True, text=True
        )
        if check:
            self.assertEqual(done.returncode, 0, done.stderr)
        return done

    def origin(self):
        done = subprocess.run(["git", "-C", self.work, "remote", "get-url", "origin"], capture_output=True, text=True, env=self.env)
        return done.stdout.strip()

    def test_tags_fixture_scaffold(self):
        self.scaffold("setup-tags-fixture")
        self.assertTrue(os.path.isfile(os.path.join(self.work, "src", "reports.ts")))
        self.assertEqual(self.origin(), "https://example.com/acme/shop.git")
        self.assertEqual(os.listdir(self.home), [".pg_service.conf"])
        self.assertIn("[app-dev]", read(os.path.join(self.home, ".pg_service.conf")))
        self.assertEqual(os.listdir(self.xdg), [])

    def test_no_sql_scaffold_writes_nothing_outside_the_run_folder(self):
        self.scaffold("setup-no-sql")
        self.assertEqual(self.origin(), "https://example.com/acme/shop.git")
        self.assertEqual(os.listdir(self.home), [])
        self.assertEqual(os.listdir(self.xdg), [])

    def test_rerun_scaffold_writes_the_service_file_and_the_allowlist(self):
        self.scaffold("setup-rerun")
        self.assertTrue(os.path.isfile(os.path.join(self.work, "docs", "agents", "sql.md")))
        self.assertEqual(os.listdir(self.home), [".pg_service.conf"])
        self.assertEqual(
            read(os.path.join(self.xdg, "sql-skill", "allowlist.toml")),
            '["example.com/acme/shop"]\nservices = ["app-dev"]\n',
        )

    def test_a_scaffold_refuses_an_unset_home_or_the_real_home(self):
        for case in ("setup-tags-fixture", "setup-rerun"):
            with self.subTest(case=case, kind="unset"):
                env = {k: v for k, v in self.env.items() if k not in ("HOME", "XDG_CONFIG_HOME")}
                self.assertEqual(self.scaffold(case, env=env, check=False).returncode, 1)
            with self.subTest(case=case, kind="real home"):
                # A python3 shim that reports the temp HOME as the real home folder: the scaffold must refuse.
                shim = os.path.join(self.tmp, "bin")
                os.makedirs(shim, exist_ok=True)
                path = os.path.join(shim, "python3")
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("#!/bin/sh\necho " + self.home + "\n")
                os.chmod(path, 0o755)
                env = dict(self.env, PATH=shim + os.pathsep + os.environ["PATH"])
                done = self.scaffold(case, env=env, check=False)
                self.assertEqual(done.returncode, 1)
                self.assertEqual(os.listdir(self.home), [])
                self.assertEqual(os.listdir(self.xdg), [])

    def shim_env(self, home, xdg=None):
        shim = os.path.join(self.tmp, "bin")
        os.makedirs(shim, exist_ok=True)
        path = os.path.join(shim, "python3")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\necho " + self.home + "\n")
        os.chmod(path, 0o755)
        return dict(self.env, HOME=home, XDG_CONFIG_HOME=xdg or self.xdg, PATH=shim + os.pathsep + os.environ["PATH"])

    def test_a_symlink_or_dot_dot_path_to_the_real_home_is_refused(self):
        link = os.path.join(self.tmp, "link")
        os.symlink(self.home, link)
        dotted = os.path.join(self.tmp, "work", "..", "home")
        for case in ("setup-tags-fixture", "setup-rerun"):
            for kind, home, xdg in (("symlink", link, None), ("dot-dot", dotted, None), ("xdg symlink", self.home + "x", os.path.join(link, ".config"))):
                with self.subTest(case=case, kind=kind):
                    os.makedirs(self.home + "x", exist_ok=True)
                    done = self.scaffold(case, env=self.shim_env(home, xdg), check=False)
                    self.assertEqual(done.returncode, 1, done.stderr)
                    self.assertEqual(os.listdir(self.home), [])


class FixtureProofTest(unittest.TestCase):
    """The expected.json of each case is what the scripts produce for the replies of the case prompt."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.work = os.path.join(self.tmp, "work")
        self.home = os.path.join(self.tmp, "home")
        self.xdg = os.path.join(self.tmp, "xdg")
        for folder in (self.work, self.home, self.xdg):
            os.makedirs(folder)
        self.env = dict(
            os.environ, HOME=self.home, XDG_CONFIG_HOME=self.xdg,
            PGSERVICEFILE=os.path.join(self.home, ".pg_service.conf"), PGPASSFILE=os.path.join(self.tmp, "pgpass"),
        )

    def script(self, name, *args):
        done = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, name), *args], capture_output=True, text=True, env=self.env, cwd=self.work)
        self.assertIn(done.returncode, (0, 1), done.stderr)
        return json.loads(done.stdout)

    def scaffold(self, case):
        done = subprocess.run(["bash", case_path(case, "scaffold.sh")], cwd=self.work, env=self.env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def expected(self, case):
        return json.loads(read(case_path(case, "expected.json")))

    def run_case(self, case, style, tags, formatter, prose_rules, services, drop_conflicts=(), kept_conflicts=(), extra_expect=None):
        self.scaffold(case)
        proposal = {
            "settings": {
                "style": style, "formatter": {"tool": formatter}, "sources": {"tags": tags}, "rules": {"disabled": []},
            },
            "prose_rules": prose_rules,
        }
        if services:
            proposal["services"] = services
        path = os.path.join(self.tmp, "proposal.json")

        def save():
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(proposal, handle)

        save()
        plan = self.script("setup_files.py", "plan", self.work, "--proposal", path)
        self.assertTrue(plan["ok"], plan)
        for conflict in plan["conflicts"]:
            if conflict["key"] in drop_conflicts:
                del proposal["settings"][conflict["section"]][conflict["key"]]
        if drop_conflicts:
            save()
            plan = self.script("setup_files.py", "plan", self.work, "--proposal", path)
        self.assertEqual([c["key"] for c in plan["conflicts"]], list(kept_conflicts))
        diff = plan["rules_file"]["diff"] + plan.get("allowlist", {}).get("diff", "")
        trace = [
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "p", "name": "Bash", "input": {"command": "python3 setup_files.py plan " + self.work + " --proposal p.json"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "p", "content": json.dumps(plan)}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": diff}]}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "w", "name": "Bash", "input": {"command": "python3 setup_files.py write " + self.work + " --proposal p.json --confirm " + plan["digest"]}}]}},
        ]
        written = self.script("setup_files.py", "write", self.work, "--proposal", path, "--confirm", plan["digest"])
        self.assertTrue(written["ok"], written)
        trace_path = os.path.join(self.tmp, "trace.jsonl")
        with open(trace_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(json.dumps(line) for line in trace) + "\n")
        expect = dict(self.expected(case), **(extra_expect or {}))
        expect_path = os.path.join(self.tmp, "expect.json")
        with open(expect_path, "w", encoding="utf-8") as handle:
            json.dump(expect, handle)
        args = [sys.executable, "-I", GRADER, trace_path, "--repo", self.work, "--expect", expect_path,
                "--allowlist", os.path.join(self.xdg, "sql-skill", "allowlist.toml"), "--key", KEY]
        done = subprocess.run(args, capture_output=True, text=True, env=self.env)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_the_tags_fixture(self):
        self.scaffold("setup-tags-fixture")
        scan = self.script("setup_scan.py", self.work)
        self.assertEqual(scan["detected_tags"], ["sql", "this.sql", "tx"])
        self.assertEqual([c["id"] for c in scan["candidates"]], ["PGJS-01", "PG-06", "PG-08"])
        self.assertGreaterEqual(scan["statements"], 3)
        measured = self.script("measure_style.py", "--tags", "sql,this.sql,tx", *[os.path.join(self.work, f) for f in scan["files_with_sql"]])
        expected = self.expected("setup-tags-fixture")
        self.assertEqual(measured["style"], expected["settings"]["style"])
        texts = {c["id"]: c["text"] for c in scan["candidates"]}
        self.assertEqual(expected["contains"][0], texts["PGJS-01"])
        self.assertEqual(expected["absent"], [texts["PG-06"], texts["PG-08"]])

    def test_the_tags_fixture_flow_passes_grader_d(self):
        style = self.expected("setup-tags-fixture")["settings"]["style"]
        texts = self.expected("setup-tags-fixture")["contains"]
        self.run_case("setup-tags-fixture", style, ["sql", "this.sql", "tx"], "none", texts, ["app-dev"], extra_expect={"services": ["app-dev"]})

    def test_the_no_sql_flow_passes_grader_d(self):
        style = self.expected("setup-no-sql")["settings"]["style"]
        self.run_case("setup-no-sql", style, [], "none", [], None)

    def test_the_no_sql_scan_finds_nothing(self):
        self.scaffold("setup-no-sql")
        scan = self.script("setup_scan.py", self.work)
        self.assertEqual((scan["files_with_sql"], scan["detected_tags"], scan["candidates"]), ([], [], []))

    def test_the_rerun_fixture_measures_as_the_case_says(self):
        self.scaffold("setup-rerun")
        scan = self.script("setup_scan.py", self.work)
        self.assertEqual((scan["detected_tags"], scan["candidates"]), (["sql"], []))
        measured = self.script("measure_style.py", "--tags", "sql", *[os.path.join(self.work, f) for f in scan["files_with_sql"]])
        self.assertEqual(measured["style"]["keyword_case"], "upper")
        self.assertEqual(measured["style"]["indent"], "2 spaces")
        for key in ("clause_per_line", "comma", "alias_as"):
            self.assertEqual(measured["style"][key], self.expected("setup-rerun")["settings"]["style"][key])

    def test_the_rerun_flow_passes_grader_d(self):
        style = dict(self.expected("setup-rerun")["settings"]["style"], keyword_case="upper", indent="2 spaces")
        # The developer keeps the current indent: the proposal drops that key after the first plan.
        self.run_case("setup-rerun", style, ["sql"], "none", ["Never build SQL with string concatenation."], ["app-dev"], drop_conflicts=("indent",), kept_conflicts=("keyword_case",))


if __name__ == "__main__":
    unittest.main()
