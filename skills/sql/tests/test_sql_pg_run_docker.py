import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SCRIPT = os.path.join(SKILL, "scripts", "pg_run.py")

VERSIONS = ("13", "18")
PULL_SECONDS = 300
READY_SECONDS = 120
SUPERUSER = "postgres"
# A synthetic value for a throwaway container that listens on 127.0.0.1 only.
FIXTURE_SECRET = "pg-run-test-fixture"
REPO_KEY = "example.invalid/o/r"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
}

SETUP_SQL = """
CREATE SCHEMA pgrun_test;
CREATE TABLE pgrun_test.items (a int);
INSERT INTO pgrun_test.items SELECT generate_series(1, 5);
CREATE VIEW pgrun_test.items_v AS SELECT a FROM pgrun_test.items;
CREATE TABLE public.facts_t (id int NOT NULL, due_on date, note text);
INSERT INTO public.facts_t VALUES (1, DATE '2026-01-01', 'x'), (2, NULL, NULL);
CREATE FUNCTION pgrun_test.writes() RETURNS int LANGUAGE sql
  AS $f$ INSERT INTO pgrun_test.items VALUES (99) RETURNING a $f$;
CREATE FUNCTION pgrun_test.probe() RETURNS int LANGUAGE plpgsql AS $f$
BEGIN
  RAISE EXCEPTION 'ro=% st=% lt=% idle=% tt=%',
    current_setting('default_transaction_read_only'), current_setting('statement_timeout'),
    current_setting('lock_timeout'), current_setting('idle_in_transaction_session_timeout'),
    coalesce(current_setting('transaction_timeout', true), 'unset');
END $f$;
"""


def docker(*args, timeout=60):
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


def host_psql(port, *args, timeout=30):
    env = {**os.environ, "PGPASSWORD": FIXTURE_SECRET, "PGCONNECT_TIMEOUT": "2"}
    return subprocess.run(
        ["psql", "-X", "-w", "-At", "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1", "-p", str(port),
         "-U", SUPERUSER, "-d", "postgres", *args],
        capture_output=True, text=True, env=env, timeout=timeout,
    )


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


@unittest.skipIf(SKIP, SKIP or "")
class PgRunDockerTest(unittest.TestCase):
    """`pg_run explain` against real PostgreSQL servers (13 and 18 from the official images)."""

    ports = {}

    @classmethod
    def setUpClass(cls):
        for version in VERSIONS:
            try:
                pulled = docker("pull", "-q", f"postgres:{version}", timeout=PULL_SECONDS)
            except subprocess.TimeoutExpired:
                raise unittest.SkipTest(f"docker pull of postgres:{version} timed out")
            if pulled.returncode != 0:
                raise unittest.SkipTest(f"docker pull of postgres:{version} failed")
        for version in VERSIONS:
            name = f"sqlskill-pgrun-{os.getpid()}-{uuid.uuid4().hex[:8]}-{version}"
            cls.addClassCleanup(docker, "rm", "-fv", name)
            started = docker(
                "run", "--rm", "-d", "--name", name, "-p", "127.0.0.1::5432",
                "-e", f"POSTGRES_PASSWORD={FIXTURE_SECRET}", f"postgres:{version}",
            )
            if started.returncode != 0:
                raise RuntimeError(f"docker run failed for postgres:{version}: {started.stderr}")
            mapping = docker("port", name, "5432/tcp").stdout.strip().splitlines()[0]
            cls.ports[version] = int(mapping.rsplit(":", 1)[1])
        for version in VERSIONS:
            cls.wait_ready(version)
            setup = host_psql(cls.ports[version], "-c", SETUP_SQL)
            if setup.returncode != 0:
                raise RuntimeError(f"the test schema failed on postgres:{version}: {setup.stderr}")

    @classmethod
    def wait_ready(cls, version):
        # The official image runs a temporary init server on a unix socket only, so a TCP
        # success means that the final server is up.
        deadline = time.monotonic() + READY_SECONDS
        while time.monotonic() < deadline:
            if host_psql(cls.ports[version], "-c", "SELECT 1").returncode == 0:
                return
            time.sleep(1)
        raise RuntimeError(f"postgres:{version} was not ready in {READY_SECONDS} seconds")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = self._tmp.name
        self.home = os.path.join(root, "home")
        self.xdg = os.path.join(root, "xdg")
        self.repo = os.path.join(root, "repo")
        for folder in (self.home, self.xdg, self.repo, os.path.join(self.xdg, "sql-skill")):
            os.makedirs(folder, exist_ok=True)
        self.service_file = os.path.join(root, "pg_service.conf")
        self.pass_file = os.path.join(root, "pgpass")
        with open(self.service_file, "w") as handle:
            for version in VERSIONS:
                # The service entry tries to turn the read-only flag off: the conninfo must win.
                handle.write(
                    f"[pgrun_{version}]\nhost=127.0.0.1\nport={self.ports[version]}\nuser={SUPERUSER}\n"
                    "dbname=postgres\noptions=-c default_transaction_read_only=off\n"
                )
        with open(self.pass_file, "w") as handle:
            for version in VERSIONS:
                handle.write(f"127.0.0.1:{self.ports[version]}:*:{SUPERUSER}:{FIXTURE_SECRET}\n")
        os.chmod(self.pass_file, 0o600)
        self.env = {
            "PATH": os.environ["PATH"], "HOME": self.home, "XDG_CONFIG_HOME": self.xdg,
            "PGSERVICEFILE": self.service_file, "PGPASSFILE": self.pass_file, **GIT_ENV,
        }
        for args in (("init", "-q"), ("remote", "add", "origin", "git@example.invalid:o/r.git")):
            done = subprocess.run(["git", *args], cwd=self.repo, env=self.env, capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
        self.write_allowlist("")

    def write_allowlist(self, extra):
        services = ", ".join(f'"pgrun_{v}"' for v in VERSIONS)
        with open(os.path.join(self.xdg, "sql-skill", "allowlist.toml"), "w") as handle:
            handle.write(f'["{REPO_KEY}"]\nservices = [{services}]\n{extra}')

    def explain(self, version, statement):
        done = subprocess.run(
            [sys.executable, "-I", SCRIPT, "explain", "--repo", self.repo, "--service", f"pgrun_{version}",
             "--mode", "select", "--statement", statement],
            capture_output=True, text=True, env=self.env, timeout=120,
        )
        self.assertIn(done.returncode, (0, 1), done.stderr)
        return json.loads(done.stdout)

    def rows(self, version):
        done = host_psql(self.ports[version], "-c", "SELECT count(*), sum(a) FROM pgrun_test.items")
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def test_a_plan_with_buffer_fields_comes_back_on_each_version(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                data = self.explain(version, "SELECT * FROM pgrun_test.items")
                self.assertTrue(data["ok"], data)
                self.assertEqual(data["server_version_num"] // 10000, int(version))
                self.assertIn("Shared Hit Blocks", data["plan"][0]["Plan"])
                self.assertIn("Execution Time", data["plan"][0])
                self.assertEqual(data["timeouts"].get("transaction_timeout"), "60s" if version == "18" else None)

    def test_the_session_is_read_only_although_the_service_entry_says_off(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                data = self.explain(version, "SELECT pgrun_test.writes()")
                self.assertFalse(data["ok"], data)
                self.assertEqual(data["error"], "statement_failed")
                self.assertIn("read-only", data["message"])
                self.assertEqual(self.rows(version), "5|15")

    def test_the_session_flags_and_the_timeouts_are_set(self):
        expected = {
            "13": "ro=on st=30s lt=2s idle=10s tt=unset",
            "18": "ro=on st=30s lt=2s idle=10s tt=1min",
        }
        for version in VERSIONS:
            with self.subTest(version=version):
                data = self.explain(version, "SELECT pgrun_test.probe()")
                self.assertEqual(data["error"], "statement_failed", data)
                self.assertIn(expected[version], data["message"])

    def test_a_per_service_override_is_set_and_cancels_a_slow_statement(self):
        self.write_allowlist(
            f'["{REPO_KEY}".timeouts.pgrun_13]\nstatement_timeout = "45s"\n'
            f'["{REPO_KEY}".timeouts.pgrun_18]\nstatement_timeout = "200ms"\ntransaction_timeout = "7min"\n'
        )
        probe = self.explain("13", "SELECT pgrun_test.probe()")
        self.assertIn("st=45s", probe["message"])
        slow = self.explain("18", "SELECT pg_sleep(5)")
        self.assertEqual(slow["error"], "statement_failed", slow)
        self.assertIn("statement timeout", slow["message"])
        probe = self.explain("18", "SELECT pgrun_test.probe()")
        self.assertIn("tt=7min", probe["message"])

    def test_the_rows_are_unchanged_after_the_runs(self):
        for version in VERSIONS:
            self.assertEqual(self.rows(version), "5|15")

    def facts(self, version, *names):
        done = subprocess.run(
            [sys.executable, "-I", SCRIPT, "facts", "--repo", self.repo, "--service", f"pgrun_{version}",
             "--names", *names],
            capture_output=True, text=True, env=self.env, timeout=120,
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        data = json.loads(done.stdout)
        self.assertTrue(data["ok"], data)
        return data["facts"]

    def facts_rows(self, version):
        done = host_psql(self.ports[version], "-c", "SELECT count(*), sum(id) FROM public.facts_t")
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def test_facts_reads_nullability_and_type_from_the_catalog(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                data = self.facts(
                    version, "pgrun_test.items.a", "public.facts_t.id", "facts_t.id", "facts_t.due_on", "facts_t.note",
                )
                self.assertEqual(data["pgrun_test.items.a"], {"nullable": True, "type": "integer"})
                self.assertEqual(data["public.facts_t.id"], {"nullable": False, "type": "integer"})
                self.assertEqual(data["facts_t.id"], {"nullable": False, "type": "integer"})
                self.assertEqual(data["facts_t.due_on"], {"nullable": True, "type": "date"})
                self.assertEqual(data["facts_t.note"], {"nullable": True, "type": "text"})

    def test_facts_reports_a_missing_column_table_or_schema_and_a_view_column_has_no_nullability(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                data = self.facts(
                    version, "facts_t.nope", "nope.id", "zz.facts_t.id", "pgrun_test.items_v.a", "pgrun_test.items.a",
                )
                self.assertEqual(data["facts_t.nope"], {"missing": True})
                self.assertEqual(data["nope.id"], {"missing": True})
                self.assertEqual(data["zz.facts_t.id"], {"missing": True})
                self.assertEqual(data["pgrun_test.items_v.a"], {"nullable": None, "type": "integer"})
                self.assertEqual(data["pgrun_test.items.a"], {"nullable": True, "type": "integer"})

    def test_a_name_that_holds_sql_text_is_a_value_that_runs_nothing(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                valid_shape = "facts_t.id'; DROP TABLE facts_t; --"
                data = self.facts(version, valid_shape, "x'; DROP TABLE facts_t; --", "facts_t.id")
                self.assertEqual(data[valid_shape], {"missing": True})
                self.assertEqual(data["x'; DROP TABLE facts_t; --"], {"missing": True})
                self.assertEqual(data["facts_t.id"], {"nullable": False, "type": "integer"})
                self.assertEqual(self.facts_rows(version), "2|3")

    def test_facts_leaves_the_data_unchanged_although_the_service_entry_says_read_write(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                data = self.facts(version, "facts_t.id", "pgrun_test.items.a", "facts_t.due_on")
                self.assertEqual(len(data), 3)
                self.assertEqual(self.facts_rows(version), "2|3")
                self.assertEqual(self.rows(version), "5|15")


if __name__ == "__main__":
    unittest.main()
