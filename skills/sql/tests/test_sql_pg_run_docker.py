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


class DockerServers:
    """Two throwaway PostgreSQL servers (13 and 18 from the official images), one set per test class.
    A class that uses it sets `ports = {}` and `SETUP_SQL`, and has `unittest.TestCase` as its second base."""

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
            setup = host_psql(cls.ports[version], "-c", cls.SETUP_SQL)
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

    def run_explain(self, version, mode, statement):
        done = subprocess.run(
            [sys.executable, "-I", SCRIPT, "explain", "--repo", self.repo, "--service", f"pgrun_{version}",
             "--mode", mode, "--statement", statement],
            capture_output=True, text=True, env=self.env, timeout=120,
        )
        self.assertIn(done.returncode, (0, 1), done.stderr)
        return json.loads(done.stdout)


@unittest.skipIf(SKIP, SKIP or "")
class PgRunDockerTest(DockerServers, unittest.TestCase):
    """`pg_run explain` in select mode against real PostgreSQL servers."""

    ports = {}
    SETUP_SQL = SETUP_SQL

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


def read_write_setup():
    with open(os.path.join(HERE, "write_docker_setup.sql")) as handle:
        return handle.read()


# (statement, ran, table names in `downgrade`). Each runs on version 13 and 18.
WRITE_CASES = [
    ("a user trigger", "UPDATE pgw.trig SET v = 2", "explain", ["pgw.trig"]),
    ("a user trigger, insert", "INSERT INTO pgw.trig VALUES (5, 5)", "explain", ["pgw.trig"]),
    ("a user trigger, delete", "DELETE FROM pgw.trig", "explain", ["pgw.trig"]),
    ("a DO ALSO rule", "UPDATE pgw.ruled_also SET v = 2", "explain", ["pgw.ruled_also"]),
    ("a DO INSTEAD rule with an action", "INSERT INTO pgw.ruled_instead VALUES (1, 1)", "explain", ["pgw.ruled_instead"]),
    ("internal foreign key triggers only (child)", "INSERT INTO pgw.child VALUES (1, 1)", "analyze", []),
    ("internal foreign key triggers only (parent)", "DELETE FROM pgw.parent", "analyze", []),
    ("a cascade child with a user trigger", "DELETE FROM pgw.cparent", "explain", ["pgw.cchild"]),
    ("ON DELETE SET NULL child", "DELETE FROM pgw.nparent", "explain", ["pgw.nchild"]),
    ("ON DELETE SET DEFAULT child", "DELETE FROM pgw.dparent WHERE id = 1", "explain", ["pgw.dchild"]),
    ("ON UPDATE CASCADE child", "UPDATE pgw.uparent SET id = 2", "explain", ["pgw.uchild"]),
    ("a trigger cloned onto a partition, statement on the parent", "UPDATE pgw.part SET v = 2", "explain", ["pgw.part", "pgw.part1"]),
    ("a trigger cloned onto a partition, statement on the partition", "UPDATE pgw.part1 SET v = 2", "explain", ["pgw.part1"]),
    ("a trigger created on the partition, statement on the parent", "UPDATE pgw.partb SET v = 2", "explain", ["pgw.partb1"]),
    ("a trigger created on the partition, statement on the partition", "UPDATE pgw.partb1 SET v = 2", "explain", ["pgw.partb1"]),
    ("a constraint trigger cloned onto a partition, statement on the parent", "UPDATE pgw.partd SET v = 2", "explain", ["pgw.partd", "pgw.partd1"]),
    ("a constraint trigger cloned onto a partition, statement on the partition", "UPDATE pgw.partd1 SET v = 2", "explain", ["pgw.partd1"]),
    ("a partitioned table with no trigger", "UPDATE pgw.partc SET v = 2", "analyze", []),
    ("an INSTEAD OF trigger on a view", "UPDATE pgw.v_instead SET v = 2", "explain", ["pgw.v_instead"]),
    ("an auto-updatable view over a table with a user trigger", "UPDATE pgw.v_auto SET v = 2", "explain", ["pgw.trig"]),
    ("a statement-level trigger on a view", "UPDATE pgw.v_stmt SET v = 2", "explain", ["pgw.v_stmt"]),
    ("a view over a view over a table with a user trigger", "UPDATE pgw.v_outer2 SET v = 2", "explain", ["pgw.trig"]),
    ("a plain inheritance child with a user trigger", "UPDATE pgw.inh_parent SET v = 2", "explain", ["pgw.inh_child"]),
    ("a disabled trigger", "UPDATE pgw.dis SET v = 2", "analyze", []),
    ("a data-modifying CTE whose target has a trigger",
     "WITH d AS (DELETE FROM pgw.trig RETURNING id) INSERT INTO pgw.plain SELECT id + 1000, 0 FROM d", "explain", ["pgw.trig"]),
    ("a self-referencing cascade foreign key", "DELETE FROM pgw.selfref", "analyze", []),
    ("two tables with foreign keys that reference each other", "DELETE FROM pgw.cyc_a", "analyze", []),
    ("a table with no trigger", "UPDATE pgw.plain SET v = v + 1", "analyze", []),
]

WRITE_TABLES = (
    "plain", "trig", "dis", "audit", "ruled_also", "sink", "ruled_instead", "ruled_nothing", "parent", "child",
    "cparent", "cchild", "nparent", "nchild", "dparent", "dchild", "uparent", "uchild", "part", "partb", "partd",
    "stmt_base", "inh_parent", "selfref", "cyc_a", "cyc_b", "ident", "ser",
)


@unittest.skipIf(SKIP, SKIP or "")
class PgRunWriteDockerTest(DockerServers, unittest.TestCase):
    """`pg_run explain --mode write` against real PostgreSQL servers: its own containers and its own setup SQL."""

    ports = {}
    SETUP_SQL = None

    @classmethod
    def setUpClass(cls):
        cls.SETUP_SQL = read_write_setup()
        super().setUpClass()

    def write(self, version, statement):
        return self.run_explain(version, "write", statement)

    def snapshot(self, version):
        """One line per table: its row count and a hash of its rows (sequence counters are not part of it)."""
        parts = [
            f"SELECT '{t}' AS t, count(*) AS n, md5(coalesce(string_agg(x::text, ',' ORDER BY x::text), '')) AS h FROM pgw.{t} AS x"
            for t in WRITE_TABLES
        ]
        done = host_psql(self.ports[version], "-c", " UNION ALL ".join(parts) + " ORDER BY 1")
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def sequence_state(self, version):
        done = host_psql(
            self.ports[version], "-c",
            "SELECT (SELECT last_value || ',' || is_called FROM pgw.ident_id_seq), "
            "(SELECT last_value || ',' || is_called FROM pgw.ser_id_seq), "
            "(SELECT last_value || ',' || is_called FROM pgw.plain_seq)",
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def idle_sessions(self, version):
        done = host_psql(
            self.ports[version], "-c",
            "SELECT count(*) FROM pg_stat_activity WHERE state LIKE 'idle in transaction%'",
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        return int(done.stdout.strip())

    def test_each_trigger_check_case_gives_the_expected_ran_and_leaves_the_data_unchanged(self):
        for version in VERSIONS:
            for label, statement, ran, tables in WRITE_CASES:
                with self.subTest(version=version, case=label):
                    before = self.snapshot(version)
                    data = self.write(version, statement)
                    self.assertTrue(data["ok"], data)
                    self.assertEqual(data["ran"], ran, data)
                    self.assertEqual(sorted({h["name"] for h in data["downgrade"]}), sorted(tables), data)
                    for name in tables:
                        self.assertIn(name, data["reason"])
                    if ran == "analyze":
                        self.assertEqual(data["reason"], "no trigger, rule or external call on the reached tables")
                        self.assertIn("Execution Time", data["plan"][0])
                    else:
                        self.assertNotIn("Execution Time", data["plan"][0])
                    self.assertEqual(self.snapshot(version), before)

    def test_explain_analyze_of_an_insert_an_update_and_a_delete_leaves_the_table_unchanged(self):
        for version in VERSIONS:
            for statement in ("INSERT INTO pgw.plain VALUES (4, 40)", "UPDATE pgw.plain SET v = v + 100",
                              "DELETE FROM pgw.plain WHERE id = 1"):
                with self.subTest(version=version, statement=statement):
                    before = self.snapshot(version)
                    data = self.write(version, statement)
                    self.assertEqual((data["ok"], data["ran"]), (True, "analyze"), data)
                    self.assertEqual(data["downgrade"], [])
                    self.assertEqual(self.snapshot(version), before)
                    self.assertEqual(self.idle_sessions(version), 0)

    def test_the_session_is_read_write_although_the_service_entry_says_off_and_the_table_is_unchanged(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                data = self.write(version, "INSERT INTO pgw.plain VALUES (50, 5)")
                self.assertEqual((data["ok"], data["ran"]), (True, "analyze"), data)

    def test_a_do_instead_nothing_rule_gives_bad_output_and_runs_no_analyze(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                before = self.snapshot(version)
                data = self.write(version, "DELETE FROM pgw.ruled_nothing")
                self.assertEqual((data["ok"], data["error"]), (False, "bad_output"), data)
                self.assertEqual(self.snapshot(version), before)

    def test_a_failing_statement_leaves_no_row_and_no_open_transaction(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                before = self.snapshot(version)
                data = self.write(version, "INSERT INTO pgw.plain SELECT 200 + g, 1 / (g - 3) FROM generate_series(1, 5) AS g")
                self.assertEqual((data["ok"], data["error"]), (False, "statement_failed"), data)
                self.assertEqual(self.snapshot(version), before)
                self.assertEqual(self.idle_sessions(version), 0)

    def test_the_scan_statements_are_downgraded_and_nothing_runs(self):
        statements = {
            "dblink_exec": "INSERT INTO pgw.plain SELECT 100, length(pgw.dblink_exec('dbname=nodb', 'select 1'))",
            "pg_advisory_lock": "INSERT INTO pgw.plain SELECT 101, 1 WHERE pg_advisory_lock(7)::text = ''",
            "lo_export": "INSERT INTO pgw.plain SELECT 102, lo_export(1, '/tmp/sqlskill-never-written')",
        }
        for version in VERSIONS:
            for name, statement in statements.items():
                with self.subTest(version=version, name=name):
                    before = self.snapshot(version)
                    data = self.write(version, statement)
                    self.assertEqual((data["ok"], data["ran"]), (True, "explain"), data)
                    self.assertEqual(data["downgrade"], [{"kind": "function", "name": name}])
                    self.assertEqual(self.snapshot(version), before)
            locks = host_psql(self.ports[version], "-c", "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'")
            self.assertEqual(locks.stdout.strip(), "0")

    def test_the_sequence_warning_and_the_counter_that_rollback_does_not_undo(self):
        cases = (
            ("an identity column", "INSERT INTO pgw.ident (v) VALUES (1)", ["sequence"]),
            ("a serial column", "INSERT INTO pgw.ser (v) VALUES (1)", ["sequence"]),
            ("an explicit nextval", "INSERT INTO pgw.plain VALUES (nextval('pgw.plain_seq')::int + 500, 1)", ["sequence"]),
            ("a table with no sequence", "INSERT INTO pgw.plain VALUES (60, 6)", []),
            ("an update of a table with a sequence", "UPDATE pgw.ident SET v = 1", []),
        )
        for version in VERSIONS:
            for label, statement, warnings in cases:
                with self.subTest(version=version, case=label):
                    before_rows = self.snapshot(version)
                    data = self.write(version, statement)
                    self.assertEqual((data["ok"], data["ran"], data["warnings"]), (True, "analyze", warnings), data)
                    self.assertEqual(self.snapshot(version), before_rows)
            with self.subTest(version=version, case="the counter moved"):
                before = self.sequence_state(version)
                self.write(version, "INSERT INTO pgw.ident (v) VALUES (1)")
                self.assertNotEqual(self.sequence_state(version), before)

    def test_merge_on_version_18_only(self):
        version = "18"
        merge_trigger = (
            "MERGE INTO pgw.trig AS t USING (SELECT 1 AS id) AS s ON t.id = s.id "
            "WHEN MATCHED THEN UPDATE SET v = 9"
        )
        merge_identity = (
            "MERGE INTO pgw.ident AS t USING (SELECT 1 AS id) AS s ON t.v = s.id "
            "WHEN NOT MATCHED THEN INSERT (v) VALUES (1)"
        )
        before = self.snapshot(version)
        data = self.write(version, merge_trigger)
        self.assertEqual((data["ok"], data["ran"]), (True, "explain"), data)
        self.assertEqual([h["name"] for h in data["downgrade"]], ["pgw.trig"])
        data = self.write(version, merge_identity)
        self.assertEqual((data["ok"], data["ran"], data["warnings"]), (True, "analyze", ["sequence"]), data)
        self.assertEqual(self.snapshot(version), before)


def read_diff_setup():
    with open(os.path.join(HERE, "diff_docker_setup.sql")) as handle:
        return handle.read()


DIFF_TABLES = ("t", "dups_a", "dups_b", "ties", "big", "wide")


@unittest.skipIf(SKIP, SKIP or "")
class PgRunDiffDockerTest(DockerServers, unittest.TestCase):
    """`pg_run diff` against real PostgreSQL servers: its own containers and its own setup SQL (schema `diffs`)."""

    ports = {}
    SETUP_SQL = None

    @classmethod
    def setUpClass(cls):
        cls.SETUP_SQL = read_diff_setup()
        super().setUpClass()

    def diff(self, version, a, b):
        done = subprocess.run(
            [sys.executable, "-I", SCRIPT, "diff", "--repo", self.repo, "--service", f"pgrun_{version}", f"--a={a}", f"--b={b}"],
            capture_output=True, text=True, env=self.env, timeout=180,
        )
        self.assertIn(done.returncode, (0, 1), done.stderr)
        return json.loads(done.stdout)

    def each_version(self, a, b):
        """`(version, result)` of the same diff on each server. A failing assertion shows the whole result, which holds the version."""
        return [(version, self.diff(version, a, b)) for version in VERSIONS]

    def checksum(self, version):
        parts = [
            f"SELECT '{t}', count(*), md5(coalesce(string_agg(x::text, ',' ORDER BY x::text), '')) FROM diffs.{t} AS x"
            for t in DIFF_TABLES
        ]
        done = host_psql(self.ports[version], "-c", " UNION ALL ".join(parts) + " ORDER BY 1")
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_equal_results(self):
        for version, data in self.each_version("SELECT id, txt FROM diffs.t", "SELECT id, txt FROM diffs.t WHERE id > 0"):
            self.assertTrue(data["ok"], data)
            self.assertEqual((data["equal"], data["order"], data["rows"]), (True, "not_applicable", {"a": 30, "b": 30}), data)
            self.assertEqual((data["only_a"], data["only_b"]), ({"count": 0, "rows": []}, {"count": 0, "rows": []}))
            self.assertEqual(data["server_version_num"] // 10000, int(version))
            self.assertEqual(data["columns"]["a"], [{"name": "id", "type": "integer"}, {"name": "txt", "type": "text"}])

    def test_a_row_only_on_one_side(self):
        for version, data in self.each_version("SELECT id, txt FROM diffs.t", "SELECT id, txt FROM diffs.t WHERE id <> 5"):
            self.assertEqual((data["equal"], data["rows"]), (False, {"a": 30, "b": 29}), data)
            self.assertEqual(data["only_a"], {"count": 1, "rows": [[5, "row 5"]]})
            self.assertEqual(data["only_b"], {"count": 0, "rows": []})

    def test_a_duplicate_count_difference_is_found_by_except_all(self):
        for version, data in self.each_version("SELECT v FROM diffs.dups_a", "SELECT v FROM diffs.dups_b"):
            self.assertEqual(data["equal"], False, data)
            self.assertEqual(data["only_a"], {"count": 1, "rows": [[1]]})
            self.assertEqual(data["only_b"], {"count": 1, "rows": [[2]]})

    def test_a_column_type_difference(self):
        for version, data in self.each_version("SELECT id FROM diffs.t", "SELECT id::numeric AS id FROM diffs.t"):
            self.assertEqual((data["equal"], data["type_mismatch"]), (False, [{"position": 1, "name": "id"}]), data)
            self.assertEqual(data["columns"]["b"], [{"name": "id", "type": "numeric"}])
            self.assertEqual((data["only_a"]["count"], data["only_b"]["count"], data["casts"]), (0, 0, []))

    def test_a_column_count_difference_is_a_shape_result(self):
        for version, data in self.each_version("SELECT id, txt FROM diffs.t", "SELECT id FROM diffs.t"):
            self.assertEqual((data["equal"], data["reason"]), (False, "shape"), data)
            self.assertEqual(data["column_names"], {"a": ["id", "txt"], "b": ["id"]})
            self.assertNotIn("only_a", data)

    def test_a_json_column_is_cast_to_text_and_named_in_casts(self):
        for version, data in self.each_version("SELECT doc FROM diffs.t", "SELECT doc FROM diffs.t"):
            self.assertEqual((data["equal"], data["casts"], data["type_mismatch"]), (True, ["doc"], []), data)
            self.assertEqual(data["columns"]["a"], [{"name": "doc", "type": "json"}])
        for version, data in self.each_version("SELECT doc FROM diffs.t", "SELECT doc FROM diffs.t WHERE id <> 7"):
            self.assertEqual((data["equal"], data["only_a"]["count"]), (False, 1), data)

    def test_the_catalog_rule_for_equality_on_other_types(self):
        a = (
            "SELECT id, ARRAY[doc] AS docs, '[1]'::json AS j, 'x'::varchar AS vc, ARRAY[1.5::float8] AS fs, 1 AS n, "
            "'<a/>'::xml AS x FROM diffs.t"
        )
        for version, data in self.each_version(a, a):
            self.assertTrue(data["ok"], data)
            self.assertEqual(data["casts"], ["docs", "j", "x"], data)
            self.assertEqual(data["floats"], ["fs"], data)
            self.assertTrue(data["equal"], data)

    def test_a_float_column_is_named_in_floats_and_compared_exactly(self):
        for version, data in self.each_version("SELECT f FROM diffs.t", "SELECT f FROM diffs.t"):
            self.assertEqual((data["equal"], data["floats"], data["casts"]), (True, ["f"], []), data)
        for version, data in self.each_version("SELECT f FROM diffs.t", "SELECT f + 1e-9 AS f FROM diffs.t"):
            self.assertEqual((data["equal"], data["floats"]), (False, ["f"]), data)

    def test_more_than_twenty_rows_only_on_one_side_give_twenty_rows_and_the_full_count(self):
        for version, data in self.each_version("SELECT id FROM diffs.big", "SELECT id FROM diffs.big WHERE false"):
            self.assertEqual((data["only_a"]["count"], len(data["only_a"]["rows"])), (100, 20), data)
            self.assertEqual((data["only_b"]["count"], data["rows"]), (0, {"a": 100, "b": 0}))

    def test_the_same_rows_in_another_order_are_checked_and_equal_and_with_no_order_by_not_applicable(self):
        for version, data in self.each_version(
            "SELECT id FROM diffs.t ORDER BY id", "SELECT id FROM diffs.t ORDER BY id DESC"
        ):
            self.assertEqual((data["order"], data["equal"]), ("checked", True), data)
            self.assertEqual(data["order_mismatch"], {"count_a": 0, "count_b": 0, "a": [], "b": []})
        for version, data in self.each_version("SELECT id FROM diffs.t", "SELECT id FROM diffs.t ORDER BY id DESC"):
            self.assertEqual((data["order"], data["equal"]), ("not_applicable", True), data)

    def test_a_rewrite_that_changes_the_rank_of_a_row(self):
        a = "SELECT id FROM diffs.t ORDER BY id LIMIT 3"
        b = "SELECT id FROM diffs.t ORDER BY id LIMIT 3 OFFSET 1"
        for version, data in self.each_version(a, b):
            self.assertEqual(data["equal"], False, data)
            self.assertEqual((data["only_a"]["rows"], data["only_b"]["rows"]), ([[1]], [[4]]))
            self.assertEqual(data["order"], "checked")
            self.assertEqual((data["order_mismatch"]["count_a"], data["order_mismatch"]["count_b"]), (3, 3))
            self.assertEqual(data["order_mismatch"]["a"], [[1, 1], [2, 2], [3, 3]])

    def test_an_order_by_with_ties_is_partial(self):
        for version, data in self.each_version("SELECT id, k FROM diffs.ties ORDER BY k", "SELECT id, k FROM diffs.ties ORDER BY k, id"):
            self.assertEqual((data["order"], data["reason"], data["equal"]), ("partial", "ties", True), data)
            self.assertNotIn("order_mismatch", data)

    def test_an_order_by_only_in_a_subquery_is_not_applicable(self):
        for version, data in self.each_version("SELECT id FROM (SELECT id FROM diffs.t ORDER BY id) AS s", "SELECT id FROM diffs.t"):
            self.assertEqual((data["order"], data["equal"]), ("not_applicable", True), data)

    def test_an_expression_key_and_an_input_column_key_are_partial_with_sort_keys(self):
        for a in ("SELECT id FROM diffs.t ORDER BY id + 1", "SELECT txt FROM diffs.t ORDER BY id"):
            for version, data in self.each_version(a, a):
                self.assertEqual((data["order"], data["reason"], data["equal"]), ("partial", "sort_keys", True), data)

    def test_a_position_beyond_the_columns_is_a_statement_error_of_the_server(self):
        for version, data in self.each_version("SELECT id FROM diffs.t ORDER BY 5", "SELECT id FROM diffs.t"):
            self.assertEqual((data["ok"], data["error"]), (False, "statement_failed"), data)
            self.assertIn("ORDER BY position 5 is not in select list", data["message"])

    def test_a_position_key_and_a_quoted_name_key_are_checked(self):
        for key in ("1", '"My Id"'):
            a = f'SELECT id AS "My Id" FROM diffs.t ORDER BY {key}'
            for version, data in self.each_version(a, a):
                self.assertEqual((data["order"], data["equal"]), ("checked", True), data)

    def test_a_table_with_101_columns_builds_its_samples_with_no_argument_limit(self):
        columns = ", ".join(f"c{i}" for i in range(1, 102))
        changed = ", ".join(["c1 + 1 AS c1"] + [f"c{i}" for i in range(2, 102)])
        for version, data in self.each_version(f"SELECT {columns} FROM diffs.wide", f"SELECT {changed} FROM diffs.wide"):
            self.assertEqual(data["equal"], False, data)
            self.assertEqual((data["only_a"]["count"], len(data["only_a"]["rows"][0])), (3, 101), data)

    def test_a_statement_that_writes_fails_as_read_only_and_the_tables_are_unchanged(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                before = self.checksum(version)
                data = self.diff(version, "SELECT nextval('diffs.seq') AS n", "SELECT 1 AS n")
                self.assertEqual((data["ok"], data["error"]), (False, "statement_failed"), data)
                self.assertIn("read-only", data["message"])
                self.assertEqual(self.checksum(version), before)

    def test_the_tables_are_unchanged_after_a_run_although_the_service_entry_says_read_only_off(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                before = self.checksum(version)
                self.diff(version, "SELECT id FROM diffs.t ORDER BY id", "SELECT id FROM diffs.t ORDER BY id DESC")
                self.assertEqual(self.checksum(version), before)

    def test_the_proof_session_has_the_read_only_flag_and_the_version_gated_timeouts(self):
        expected = {"13": "ro=on st=30s lt=2s idle=10s tt=unset", "18": "ro=on st=30s lt=2s idle=10s tt=1min"}
        for version in VERSIONS:
            with self.subTest(version=version):
                data = self.diff(version, "SELECT diffs.probe() AS x", "SELECT 1::text AS x")
                self.assertEqual(data["error"], "statement_failed", data)
                self.assertIn(expected[version], data["message"])

    def test_a_per_service_timeout_override_cancels_a_slow_diff(self):
        self.write_allowlist(f'["{REPO_KEY}".timeouts.pgrun_18]\nstatement_timeout = "300ms"\n')
        data = self.diff("18", "SELECT pg_sleep(5)::text AS x", "SELECT 'a' AS x")
        self.assertEqual((data["ok"], data["error"]), (False, "statement_failed"), data)
        self.assertIn("statement timeout", data["message"])


if __name__ == "__main__":
    unittest.main()
