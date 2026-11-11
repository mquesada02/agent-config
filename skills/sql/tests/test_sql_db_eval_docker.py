import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
DB_EVAL = os.path.join(SKILL, "evals", "db", "db_eval.py")
PG_RUN = os.path.join(SKILL, "scripts", "pg_run.py")
RULES_SOURCE = os.path.join(SKILL, "evals", "db", "cases", "plan-select", "repo", "docs", "agents", "sql.md")
ORIGIN = "https://example.invalid/eval/sql-db-case.git"
STATEMENT = "SELECT c.name, count(*) FROM shop.orders AS o JOIN shop.customers AS c ON c.id = o.customer_id GROUP BY 1"
PULL_SECONDS = 300

with open(os.path.join(SKILL, "evals", "db", "canaries.json"), encoding="utf-8") as handle:
    CANARIES = json.load(handle)


def docker(*args, timeout=60):
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


def skip_reason():
    if sys.version_info < (3, 11):
        return "the scripts need tomllib (Python 3.11 or newer)"
    if shutil.which("docker") is None:
        return "docker is not installed"
    if shutil.which("psql") is None:
        return "psql is not on PATH of the host"
    try:
        info = docker("info", timeout=30)
    except subprocess.TimeoutExpired:
        return "docker info timed out"
    if info.returncode != 0:
        return "the docker daemon does not answer docker info"
    return None


SKIP = skip_reason()


def dangling_volumes():
    return set(docker("volume", "ls", "-q", "-f", "dangling=true").stdout.split())


def container_names():
    return set(docker("ps", "-a", "--format", "{{.Names}}").stdout.split())


def pull_images():
    for version in ("13", "18"):
        try:
            pulled = docker("pull", "-q", f"postgres:{version}", timeout=PULL_SECONDS)
        except subprocess.TimeoutExpired:
            raise unittest.SkipTest(f"docker pull of postgres:{version} timed out")
        if pulled.returncode != 0:
            raise unittest.SkipTest(f"docker pull of postgres:{version} failed")


def db_eval(*args):
    return subprocess.run([sys.executable, "-I", DB_EVAL, *args], capture_output=True, text=True, timeout=600)


@unittest.skipIf(SKIP, SKIP or "")
class DbEvalDockerTest(unittest.TestCase):
    """`db_eval.py setup` with the real PostgreSQL 13 and 18 images, and `pg_run explain` through its files."""

    @classmethod
    def setUpClass(cls):
        pull_images()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.state = os.path.join(cls._tmp.name, "state")
        cls.volumes_before = dangling_volumes()
        cls.addClassCleanup(db_eval, "teardown", "--state", cls.state)
        started = db_eval("setup", "--state", cls.state)
        if started.returncode != 0:
            raise RuntimeError(f"db_eval setup failed: {started.stderr}")
        cls.repo = os.path.join(cls._tmp.name, "repo")
        os.makedirs(os.path.join(cls.repo, "docs", "agents"))
        shutil.copy(RULES_SOURCE, os.path.join(cls.repo, "docs", "agents", "sql.md"))
        home = os.path.join(cls._tmp.name, "home")
        os.makedirs(home)
        cls.env = {"PATH": os.environ["PATH"], "HOME": home,
                   "PGSERVICEFILE": os.path.join(cls.state, "pg_service.conf"),
                   "PGPASSFILE": os.path.join(cls.state, "pgpass"),
                   "XDG_CONFIG_HOME": os.path.join(cls.state, "xdg")}
        for argv in (["git", "init", "-q", cls.repo], ["git", "-C", cls.repo, "remote", "add", "origin", ORIGIN]):
            subprocess.run(argv, check=True, env={"PATH": os.environ["PATH"], "HOME": home})
        with open(os.path.join(cls.state, "state.json"), encoding="utf-8") as handle:
            cls.names = json.load(handle)["containers"]

    def pg_run(self, service):
        proc = subprocess.run(
            [sys.executable, "-I", PG_RUN, "explain", "--repo", self.repo, "--service", service, "--mode", "select",
             "--statement", STATEMENT], capture_output=True, text=True, env=self.env, timeout=120)
        return proc, json.loads(proc.stdout)

    def snapshot(self, version, name):
        out = os.path.join(self._tmp.name, name)
        proc = db_eval("snapshot", "--state", self.state, "--version", version, "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(out, encoding="utf-8") as handle:
            return json.load(handle)

    def test_the_generated_files_exist(self):
        for relative in ("pg_service.conf", "pgpass", os.path.join("xdg", "sql-skill", "allowlist.toml"), "state.json"):
            self.assertTrue(os.path.isfile(os.path.join(self.state, relative)), relative)

    def test_pg_run_gets_a_plan_on_both_versions_through_the_generated_files(self):
        for version in ("13", "18"):
            with self.subTest(version=version):
                proc, data = self.pg_run(f"app-pg{version}")
                self.assertEqual(proc.returncode, 0, proc.stdout)
                self.assertTrue(data["ok"], data)
                self.assertTrue(data["plan"])

    def test_both_servers_run_with_the_small_cache_and_the_snapshot_holds_the_events_table(self):
        for version in ("13", "18"):
            with self.subTest(version=version):
                shown = docker("exec", self.names[version], "psql", "-U", CANARIES["user"], "-d", CANARIES["dbname"],
                               "-tA", "-c", "SHOW shared_buffers")
                self.assertEqual((shown.returncode, shown.stdout.strip()), (0, "2MB"), shown.stderr)
                self.assertIn("shop.events", self.snapshot(version, f"e-{version}.json")["tables"])

    def test_a_bad_password_and_a_wrong_host_give_connection_failed_and_leak_no_canary(self):
        for service in ("app-badpw", "app-wronghost"):
            with self.subTest(service=service):
                proc, data = self.pg_run(service)
                self.assertEqual((proc.returncode, data.get("error")), (1, "connection_failed"), proc.stdout)
                for key, value in CANARIES.items():
                    self.assertNotIn(value, proc.stdout + proc.stderr, key)

    def test_a_service_off_the_allowlist_is_not_allowed(self):
        proc, data = self.pg_run("other-db")
        self.assertEqual((proc.returncode, data.get("error")), (1, "not_allowed"), proc.stdout)

    def test_two_snapshots_of_an_untouched_database_are_equal_and_a_changed_row_changes_one(self):
        baseline = {}
        for version in ("13", "18"):
            with self.subTest(version=version):
                baseline[version] = self.snapshot(version, f"a-{version}.json")
                self.assertEqual(baseline[version], self.snapshot(version, f"b-{version}.json"))
                self.assertTrue(baseline[version]["tables"])
                self.assertTrue(baseline[version]["sequences"])
        name = self.names["18"]
        changed = docker("exec", name, "psql", "-U", CANARIES["user"], "-d", CANARIES["dbname"], "-v", "ON_ERROR_STOP=1",
                         "-c", "UPDATE shop.customers SET name = name || 'x' WHERE id = (SELECT min(id) FROM shop.customers)")
        self.assertEqual(changed.returncode, 0, changed.stderr)
        self.assertNotEqual(self.snapshot("18", "c-18.json")["tables"], baseline["18"]["tables"])


@unittest.skipIf(SKIP, SKIP or "")
class DbEvalTeardownDockerTest(unittest.TestCase):
    def test_teardown_leaves_no_container_and_no_new_dangling_volume(self):
        pull_images()
        with tempfile.TemporaryDirectory() as root:
            state = os.path.join(root, "state")
            volumes_before = dangling_volumes()
            self.addCleanup(db_eval, "teardown", "--state", state)
            self.assertEqual(db_eval("setup", "--state", state).returncode, 0)
            with open(os.path.join(state, "state.json"), encoding="utf-8") as handle:
                names = set(json.load(handle)["containers"].values())
            self.assertTrue(names <= container_names())
            self.assertEqual(db_eval("teardown", "--state", state).returncode, 0)
            self.assertEqual(names & container_names(), set())
            self.assertEqual(dangling_volumes() - volumes_before, set())
            self.assertFalse(os.path.exists(state))


if __name__ == "__main__":
    unittest.main()
