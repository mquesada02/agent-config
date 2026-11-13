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
sys.path.insert(0, os.path.join(SKILL, "scripts"))

import sql_guard  # noqa: E402

VERSIONS = ("13", "18")
PULL_SECONDS = 300
READY_SECONDS = 120
SUPERUSER = "postgres"
APP_ROLE = "pgrun_app"
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
CREATE EXTENSION dblink SCHEMA pgrun_test;
CREATE EXTENSION tablefunc SCHEMA pgrun_test;
CREATE TABLE pgrun_test.probe_t (a int);
CREATE TABLE public.facts_t (id int NOT NULL, due_on date, note text);
INSERT INTO public.facts_t VALUES (1, DATE '2026-01-01', 'x'), (2, NULL, NULL);
CREATE FUNCTION pgrun_test.writes() RETURNS int LANGUAGE sql
  AS $f$ INSERT INTO pgrun_test.items VALUES (99) RETURNING a $f$;
CREATE FUNCTION pgrun_test.probe() RETURNS int LANGUAGE plpgsql STABLE AS $f$
BEGIN
  RAISE EXCEPTION 'ro=% st=% lt=% idle=% tt=%',
    current_setting('default_transaction_read_only'), current_setting('statement_timeout'),
    current_setting('lock_timeout'), current_setting('idle_in_transaction_session_timeout'),
    coalesce(current_setting('transaction_timeout', true), 'unset');
END $f$;
CREATE FUNCTION pgrun_test.writes_stable() RETURNS int LANGUAGE plpgsql STABLE AS $f$
BEGIN
  RETURN pgrun_test.writes();
END $f$;
CREATE FUNCTION pgrun_test.stable_fn() RETURNS int LANGUAGE plpgsql STABLE AS $f$ BEGIN RETURN 1; END $f$;
CREATE FUNCTION pgrun_test.immutable_fn() RETURNS int LANGUAGE plpgsql IMMUTABLE AS $f$ BEGIN RETURN 1; END $f$;
CREATE FUNCTION pgrun_test."My""Fn"() RETURNS int LANGUAGE plpgsql VOLATILE AS $f$ BEGIN RETURN 1; END $f$;
CREATE FUNCTION pgrun_test.vol_sfunc(int, int) RETURNS int LANGUAGE sql VOLATILE AS 'SELECT $1 + $2';
CREATE FUNCTION pgrun_test.stable_sfunc(int, int) RETURNS int LANGUAGE sql STABLE AS 'SELECT $1 + $2';
CREATE AGGREGATE pgrun_test.vol_sum(int) (SFUNC = pgrun_test.vol_sfunc, STYPE = int, INITCOND = '0');
CREATE AGGREGATE pgrun_test.stable_sum(int) (SFUNC = pgrun_test.stable_sfunc, STYPE = int, INITCOND = '0');
CREATE EXTENSION pgcrypto SCHEMA pgrun_test;
CREATE VIEW pgrun_test.v_xml AS SELECT query_to_xml('select 1', true, true, '') AS x;
CREATE VIEW pgrun_test.v_dblink AS SELECT pgrun_test.dblink_exec('dbname=nodb', 'select 1') AS r;
CREATE VIEW pgrun_test.v_vol AS SELECT a, pgrun_test.writes() AS w FROM pgrun_test.items;
CREATE VIEW pgrun_test.v_stable AS SELECT a, pgrun_test.stable_fn() AS s FROM pgrun_test.items;
CREATE VIEW pgrun_test.v_mixed AS SELECT a, pgrun_test."My""Fn"() AS m FROM pgrun_test.items;
CREATE DOMAIN pgrun_test.dom_x AS text CHECK (query_to_xml('select 1', true, true, '') IS NOT NULL OR VALUE IS NULL);
CREATE ROLE pgrun_app LOGIN PASSWORD 'pg-run-test-fixture';
GRANT USAGE ON SCHEMA pgrun_test TO pgrun_app;
CREATE TABLE pgrun_test.rls_xml (a int);
INSERT INTO pgrun_test.rls_xml VALUES (1);
ALTER TABLE pgrun_test.rls_xml ENABLE ROW LEVEL SECURITY;
CREATE POLICY p_xml ON pgrun_test.rls_xml FOR SELECT USING (query_to_xml('select 1', true, true, '') IS NOT NULL);
CREATE TABLE pgrun_test.rls_vol (a int);
INSERT INTO pgrun_test.rls_vol VALUES (1);
ALTER TABLE pgrun_test.rls_vol ENABLE ROW LEVEL SECURITY;
CREATE POLICY p_vol ON pgrun_test.rls_vol FOR SELECT USING (pgrun_test.writes() > 0);
CREATE TABLE pgrun_test.rls_ok (a int);
INSERT INTO pgrun_test.rls_ok VALUES (1);
ALTER TABLE pgrun_test.rls_ok ENABLE ROW LEVEL SECURITY;
CREATE POLICY p_ok ON pgrun_test.rls_ok FOR SELECT USING (true);
GRANT SELECT ON pgrun_test.rls_xml, pgrun_test.rls_vol, pgrun_test.rls_ok TO pgrun_app;
ALTER ROLE postgres SET search_path = "$user", public, pgrun_test;
CREATE TABLE public."Order" (id int NOT NULL, "Id" text);
CREATE TABLE public."order" (id text);
CREATE TABLE public."we ird.t""x" ("c ""1" numeric(10,2) NOT NULL);
CREATE TABLE public."café" ("naïve" boolean);
"""
# The server cuts the 70-letter name to 63 bytes (a NOTICE, no error).
SETUP_SQL += f"CREATE TABLE public.{'a' * 70} (id smallint NOT NULL);\n"

# (label, statement, ran, names in `downgrade`). Each runs on version 13 and 18.
STORED_SELECT_CASES = [
    ("a view body that calls a string-SQL function", "SELECT * FROM pgrun_test.v_xml", "explain", ["query_to_xml"]),
    ("a view body that calls a dblink function", "SELECT * FROM pgrun_test.v_dblink", "explain", ["dblink_exec"]),
    ("a direct VOLATILE user function", "SELECT pgrun_test.writes()", "explain", ["pgrun_test.writes"]),
    ("an unqualified VOLATILE user function on the search path", "SELECT writes()", "explain", ["pgrun_test.writes"]),
    ("a VOLATILE user function in a view", "SELECT * FROM pgrun_test.v_vol", "explain", ["pgrun_test.writes"]),
    ("a VOLATILE user function with a quoted name in a view", "SELECT * FROM pgrun_test.v_mixed", "explain", ['pgrun_test."My""Fn"']),
    ("a VOLATILE extension function", "SELECT pgrun_test.gen_random_bytes(4)", "explain", ["pgrun_test.gen_random_bytes"]),
    ("an aggregate with a VOLATILE transition function", "SELECT pgrun_test.vol_sum(a) FROM pgrun_test.items", "explain", ["pgrun_test.vol_sum"]),
    ("an aggregate with a STABLE transition function", "SELECT pgrun_test.stable_sum(a) FROM pgrun_test.items", "analyze", []),
    ("a STABLE user function", "SELECT pgrun_test.stable_fn()", "analyze", []),
    ("a STABLE user function in a view", "SELECT * FROM pgrun_test.v_stable", "analyze", []),
    ("an IMMUTABLE user function", "SELECT pgrun_test.immutable_fn()", "analyze", []),
    ("a built-in function", "SELECT lower('A'), now(), random()", "analyze", []),
    ("a cast to a domain whose constraint calls a scanned function (open case)", "SELECT 'x'::pgrun_test.dom_x", "analyze", []),
    ("a statement with no call", "SELECT 1", "analyze", []),
]


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
                # A role that is neither a superuser nor an owner, so that row-level security applies to it.
                handle.write(
                    f"[pgrun_{version}_app]\nhost=127.0.0.1\nport={self.ports[version]}\nuser={APP_ROLE}\n"
                    "dbname=postgres\noptions=-c default_transaction_read_only=off\n"
                )
        with open(self.pass_file, "w") as handle:
            for version in VERSIONS:
                handle.write(f"127.0.0.1:{self.ports[version]}:*:{SUPERUSER}:{FIXTURE_SECRET}\n")
                handle.write(f"127.0.0.1:{self.ports[version]}:*:{APP_ROLE}:{FIXTURE_SECRET}\n")
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
        services = ", ".join(f'"pgrun_{v}{suffix}"' for v in VERSIONS for suffix in ("", "_app"))
        with open(os.path.join(self.xdg, "sql-skill", "allowlist.toml"), "w") as handle:
            handle.write(f'["{REPO_KEY}"]\nservices = [{services}]\n{extra}')

    def run_explain(self, version, mode, statement, role=""):
        """`role` is "" (the superuser) or "_app" (the role that row-level security applies to)."""
        done = subprocess.run(
            [sys.executable, "-I", SCRIPT, "explain", "--repo", self.repo, "--service", f"pgrun_{version}{role}",
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

    def explain(self, version, statement, role=""):
        done = subprocess.run(
            [sys.executable, "-I", SCRIPT, "explain", "--repo", self.repo, "--service", f"pgrun_{version}{role}",
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
                data = self.explain(version, "SELECT pgrun_test.writes_stable()")
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

    def test_each_stored_sql_and_user_function_case_gives_the_expected_run(self):
        for version in VERSIONS:
            for label, statement, ran, names in STORED_SELECT_CASES:
                with self.subTest(version=version, case=label):
                    data = self.explain(version, statement)
                    self.assertTrue(data["ok"], data)
                    self.assertEqual(data["ran"], ran, data)
                    self.assertEqual([hit["name"] for hit in data["downgrade"]], names, data)
                    self.assertEqual({hit["kind"] for hit in data["downgrade"]} - {"function"}, set())
                    if ran == "analyze":
                        self.assertEqual(
                            data["reason"],
                            "no call of a function that runs SQL from a string, and no VOLATILE user function, in the plan",
                        )
                        self.assertIn("Execution Time", data["plan"][0])
                    else:
                        self.assertNotIn("Execution Time", data["plan"][0])
                        for name in names:
                            self.assertIn(name, data["reason"])
                    self.assertEqual(self.rows(version), "5|15")

    def test_a_policy_of_a_role_without_superuser_rights_is_found_with_the_same_rights(self):
        cases = (
            ("a policy that calls a string-SQL function", "SELECT * FROM pgrun_test.rls_xml", "explain", ["query_to_xml"]),
            ("a policy that calls a VOLATILE user function", "SELECT * FROM pgrun_test.rls_vol", "explain", ["pgrun_test.writes"]),
            ("a policy with no call", "SELECT * FROM pgrun_test.rls_ok", "analyze", []),
        )
        for version in VERSIONS:
            for label, statement, ran, names in cases:
                with self.subTest(version=version, case=label):
                    data = self.explain(version, statement, role="_app")
                    self.assertTrue(data["ok"], data)
                    self.assertEqual(data["ran"], ran, data)
                    self.assertEqual([hit["name"] for hit in data["downgrade"]], names, data)
                    self.assertEqual(self.rows(version), "5|15")

    def test_a_downgraded_stored_call_never_runs(self):
        # The view calls a function that inserts a row. A downgrade must not run it; a positive control shows that it does insert.
        for version in VERSIONS:
            with self.subTest(version=version):
                control = host_psql(self.ports[version], "-c", "SELECT sum(w) FROM pgrun_test.v_vol")
                self.assertEqual(control.returncode, 0, control.stderr)
                self.assertNotEqual(self.rows(version), "5|15")
                restore = host_psql(self.ports[version], "-c", "DELETE FROM pgrun_test.items WHERE a = 99")
                self.assertEqual(restore.returncode, 0, restore.stderr)
                data = self.explain(version, "SELECT * FROM pgrun_test.v_vol")
                self.assertEqual(data["ran"], "explain", data)
                self.assertEqual(self.rows(version), "5|15")

    def probe_rows(self, version):
        done = host_psql(self.ports[version], "-c", "SELECT count(*) FROM pgrun_test.probe_t")
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def test_a_string_sql_function_runs_a_plain_explain_and_its_hidden_sql_never_runs(self):
        # The text of query_to_xml opens a second connection (outside the read-only transaction) and inserts a row.
        # An ANALYZE run would run it; the downgraded plain EXPLAIN must not.
        connection = f"host=127.0.0.1 port=5432 user={SUPERUSER} dbname=postgres password={FIXTURE_SECRET}"
        hidden = f"SELECT pgrun_test.dblink_exec(''{connection}'', ''INSERT INTO pgrun_test.probe_t VALUES (1)'')"
        for version in VERSIONS:
            with self.subTest(version=version):
                # Positive control: the hidden statement does insert a row when it runs (the table is emptied after).
                control = host_psql(self.ports[version], "-c", hidden.replace("''", "'"))
                self.assertEqual(control.returncode, 0, control.stderr)
                self.assertEqual(self.probe_rows(version), "1")
                emptied = host_psql(self.ports[version], "-c", "TRUNCATE pgrun_test.probe_t")
                self.assertEqual(emptied.returncode, 0, emptied.stderr)
                data = self.explain(version, f"SELECT query_to_xml('{hidden}', true, true, '')")
                self.assertTrue(data["ok"], data)
                self.assertEqual(self.probe_rows(version), "0")
                self.assertEqual((data["ran"], data["mode"]), ("explain", "select"))
                self.assertEqual(data["downgrade"], [{"kind": "function", "name": "query_to_xml"}])

    def test_ts_rewrite_with_a_side_effect_statement_in_its_text_never_runs_it(self):
        # The text of ts_rewrite runs as SQL. This one opens a second connection (outside the read-only transaction)
        # and inserts a row. An ANALYZE run would run it; the downgraded plain EXPLAIN must not.
        connection = f"host=127.0.0.1 port=5432 user={SUPERUSER} dbname=postgres password={FIXTURE_SECRET}"
        inner = (
            "SELECT 'a'::tsquery, to_tsquery('simple', regexp_replace(pgrun_test.dblink_exec('" + connection
            + "', 'INSERT INTO pgrun_test.probe_t VALUES (1)'), '[^A-Za-z]', '', 'g'))"
        )
        statement = "SELECT ts_rewrite('a'::tsquery, '" + inner.replace("'", "''") + "')"
        for version in VERSIONS:
            with self.subTest(version=version):
                # Positive control: the statement does insert a row when it runs (the table is emptied after).
                control = host_psql(self.ports[version], "-c", statement)
                self.assertEqual(control.returncode, 0, control.stderr)
                self.assertEqual(self.probe_rows(version), "1")
                emptied = host_psql(self.ports[version], "-c", "TRUNCATE pgrun_test.probe_t")
                self.assertEqual(emptied.returncode, 0, emptied.stderr)
                data = self.explain(version, statement)
                self.assertTrue(data["ok"], data)
                self.assertEqual(self.probe_rows(version), "0")
                self.assertEqual((data["ran"], data["mode"]), ("explain", "select"))
                self.assertEqual(data["downgrade"], [{"kind": "function", "name": "ts_rewrite"}])

    def test_a_forbidden_function_in_the_text_argument_gives_a_plain_explain(self):
        for version in VERSIONS:
            for hidden in ("pg_notify(''chan'', ''x'')", "set_config(''pgrun.flag'', ''1'', false)"):
                with self.subTest(version=version, hidden=hidden):
                    data = self.explain(version, f"SELECT query_to_xml('SELECT {hidden}', true, true, '')")
                    self.assertEqual((data["ok"], data["ran"]), (True, "explain"), data)
                    self.assertEqual(data["downgrade"], [{"kind": "function", "name": "query_to_xml"}])

    def test_each_listed_function_gives_a_plain_explain_and_a_normal_select_still_analyzes(self):
        statements = {
            "ts_stat": "SELECT * FROM ts_stat('SELECT to_tsvector(''x'')')",
            "ts_rewrite": "SELECT ts_rewrite('a'::tsquery, 'SELECT ''a''::tsquery, ''b''::tsquery')",
            "crosstab": "SELECT * FROM pgrun_test.crosstab('SELECT 1, 1, 1') AS ct(a int, b int)",
            "connectby": "SELECT * FROM pgrun_test.connectby('pgrun_test.items', 'a', 'a', '1', 0) AS t(a int, p int, l int)",
            "cursor_to_xml": "SELECT cursor_to_xml('c'::refcursor, 1, true, true, '')",
        }
        for version in VERSIONS:
            for name, statement in statements.items():
                with self.subTest(version=version, name=name):
                    data = self.explain(version, statement)
                    self.assertEqual((data["ok"], data["ran"]), (True, "explain"), data)
                    self.assertEqual([hit["name"] for hit in data["downgrade"]], [name])
            with self.subTest(version=version, name="normal"):
                data = self.explain(version, "SELECT * FROM pgrun_test.items")
                self.assertEqual((data["ok"], data["ran"], data["downgrade"]), (True, "analyze", []))

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

    def server_run(self, version, text):
        """The text on the server as the user wrote it, with the result header shown."""
        return host_psql(self.ports[version], "-P", "tuples_only=off", "-c", text)

    def test_a_long_s_select_is_a_syntax_error_on_the_server_and_refused_by_the_guard(self):
        text = "ſelect 1"
        for version in VERSIONS:
            with self.subTest(version=version):
                done = self.server_run(version, text)
                self.assertNotEqual(done.returncode, 0)
                self.assertIn("syntax error", done.stderr)
        sql, refusal = sql_guard.check_select(text)
        self.assertEqual((sql, refusal["reason"]), (None, "not_select"))

    def test_the_text_that_the_guard_sends_gives_the_server_result_of_the_text_of_the_user(self):
        nbsp_text = "SELECT 1 AS a "
        vertical_tab_text = "SELECT 1 AS a\v"
        sent = {}
        for text in (nbsp_text, vertical_tab_text):
            sent[text], refusal = sql_guard.check_select(text)
            self.assertIsNone(refusal)
        for version in VERSIONS:
            results = {}
            for text in (nbsp_text, vertical_tab_text):
                with self.subTest(version=version, text=repr(text)):
                    written, guarded = self.server_run(version, text), self.server_run(version, sent[text])
                    self.assertEqual((written.returncode, written.stdout), (guarded.returncode, guarded.stdout))
                    results[text] = written
            nbsp, tab = results[nbsp_text], results[vertical_tab_text]
            self.assertEqual(nbsp.returncode, 0, nbsp.stderr)
            self.assertEqual(nbsp.stdout.splitlines()[0], "a ")
            if version == "13":
                self.assertNotEqual(tab.returncode, 0)
                self.assertIn("syntax error", tab.stderr)
            else:
                self.assertEqual(tab.returncode, 0, tab.stderr)
                self.assertEqual(tab.stdout.splitlines()[0], "a")

    def test_a_kelvin_sign_name_is_another_function_on_the_server_and_has_no_dblink_scan_in_the_guard(self):
        text = "SELECT dblinK('x')"
        result, refusal = sql_guard.check_select_scan(text)
        self.assertIsNone(refusal)
        self.assertEqual(result["scan"], [])
        for version in VERSIONS:
            with self.subTest(version=version):
                done = self.server_run(version, text)
                self.assertNotEqual(done.returncode, 0)
                self.assertIn("does not exist", done.stderr)

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

    def test_facts_reads_quoted_and_unquoted_names_with_the_server_rules(self):
        cases = {
            '"Order".id': {"nullable": False, "type": "integer"},
            "Order.id": {"nullable": True, "type": "text"},
            "order.id": {"nullable": True, "type": "text"},
            '"order".id': {"nullable": True, "type": "text"},
            'public."Order"."Id"': {"nullable": True, "type": "text"},
            'Order."Id"': {"missing": True},
            '"we ird.t""x"."c ""1"': {"nullable": False, "type": "numeric(10,2)"},
            'public."we ird.t""x"."c ""1"': {"nullable": False, "type": "numeric(10,2)"},
            "café.naïve": {"nullable": True, "type": "boolean"},
            '"café"."naïve"': {"nullable": True, "type": "boolean"},
            "CAFÉ.naïve": {"missing": True},
            f"{'a' * 70}.id": {"nullable": False, "type": "smallint"},
            "Order.id'; DROP TABLE facts_t; --": {"missing": True},
        }
        for version in VERSIONS:
            with self.subTest(version=version):
                data = self.facts(version, *cases)
                self.assertEqual(data, cases)
                self.assertEqual(list(data), list(cases))
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
    "t_default", "t_def_vol", "t_check", "t_chk_vol", "t_nn", "t_text", "t_dom", "t_dom_over", "t_dom_arr", "t_dom_rng",
    "t_dom_comp", "t_dom_vol", "t_gen", "t_rls_using", "t_rls_check", "t_rls_vol", "t_rls_mixed", "t_rls_ok",
    "t_null_policies",
)

WRITE_ANALYZE_REASON = "no trigger, rule, external call or VOLATILE user function on the reached tables"

# (label, statement, ran, names in `downgrade`). Each runs on version 13 and 18, as the superuser.
STORED_WRITE_CASES = [
    ("a column default that calls a string-SQL function", "INSERT INTO pgw.t_default (id) VALUES (1)", "explain", ["query_to_xml"]),
    ("a view body that calls a string-SQL function", "UPDATE pgw.v_where SET v = v + 1", "explain", ["query_to_xml"]),
    ("a view body that calls set_config", "UPDATE pgw.v_setcfg SET v = v + 1", "explain", ["set_config"]),
    ("the USING qual of a policy", "UPDATE pgw.t_rls_using SET id = 2", "explain", ["query_to_xml"]),
    ("the WITH CHECK qual of a policy", "INSERT INTO pgw.t_rls_check VALUES (1)", "explain", ["query_to_xml"]),
    ("a view with CHECK OPTION", "INSERT INTO pgw.v_check VALUES (700, 7)", "explain", ["query_to_xml"]),
    ("a CASCADED CHECK OPTION over a view that has none", "INSERT INTO pgw.v_cascaded VALUES (701, 7)", "explain", ["query_to_xml"]),
    ("a CHECK constraint", "INSERT INTO pgw.t_check VALUES (1)", "explain", ["query_to_xml"]),
    ("a domain constraint", "INSERT INTO pgw.t_dom VALUES (1)", "explain", ["query_to_xml"]),
    ("a domain over a domain", "INSERT INTO pgw.t_dom_over VALUES (1)", "explain", ["query_to_xml"]),
    ("a domain in an array", "INSERT INTO pgw.t_dom_arr VALUES (ARRAY[1])", "explain", ["query_to_xml"]),
    ("a domain in a range", "INSERT INTO pgw.t_dom_rng VALUES ('[1,2)'::pgw.rng)", "explain", ["query_to_xml"]),
    ("a domain in a composite type", "INSERT INTO pgw.t_dom_comp VALUES (ROW(1, 2))", "explain", ["query_to_xml"]),
    ("a direct VOLATILE user function", "INSERT INTO pgw.plain SELECT 400, pgw.vol_fn()", "explain", ["pgw.vol_fn"]),
    ("a VOLATILE user function in a column default", "INSERT INTO pgw.t_def_vol (id) VALUES (1)", "explain", ["pgw.vol_fn"]),
    ("a VOLATILE user function in a CHECK constraint", "INSERT INTO pgw.t_chk_vol VALUES (1)", "explain", ["pgw.vol_fn"]),
    ("a VOLATILE user function in a domain constraint", "INSERT INTO pgw.t_dom_vol VALUES (1)", "explain", ["pgw.vol_fn"]),
    ("a VOLATILE user function in a view", "UPDATE pgw.v_vol SET v = v + 1", "explain", ["pgw.vol_fn"]),
    ("a VOLATILE user function in a policy", "INSERT INTO pgw.t_rls_vol VALUES (1)", "explain", ["pgw.vol_fn"]),
    ("a VOLATILE user function with a quoted name in a view", "UPDATE pgw.v_mixed SET v = v + 1", "explain", ['pgw."MyFn"']),
    ("a VOLATILE user function with a quoted name in a policy", "INSERT INTO pgw.t_rls_mixed VALUES (1)", "explain", ['pgw."MyFn"']),
    ("a STABLE user function", "INSERT INTO pgw.plain SELECT 401, pgw.stable_fn()", "analyze", []),
    ("a built-in function", "INSERT INTO pgw.plain SELECT 402, floor(random() * 0)::int", "analyze", []),
    ("a generated column through an IMMUTABLE wrapper (open case)", "INSERT INTO pgw.t_gen (id) VALUES (1)", "analyze", []),
    ("a user-defined operator (open case)", "INSERT INTO pgw.plain SELECT 410, 1 WHERE 1 OPERATOR(pgw.===) 2", "analyze", []),
    ("a STABLE user function that calls a scanned function (open case)", "INSERT INTO pgw.plain SELECT 411, pgw.stable_calls_scanned()", "analyze", []),
    ("a cast to a domain in the statement (open case)", "INSERT INTO pgw.t_text VALUES ('x'::pgw.dom_txt)", "analyze", []),
    ("an INSERT policy, which has a NULL USING qual", "INSERT INTO pgw.t_null_policies VALUES (2)", "analyze", []),
    ("an UPDATE policy with no WITH CHECK", "UPDATE pgw.t_null_policies SET id = 3", "analyze", []),
    ("a NOT NULL constraint", "INSERT INTO pgw.t_nn VALUES (1)", "analyze", []),
    ("a write with no such call", "UPDATE pgw.plain SET v = v + 1", "analyze", []),
]


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
                        self.assertEqual(data["reason"], WRITE_ANALYZE_REASON)
                        self.assertIn("Execution Time", data["plan"][0])
                    else:
                        self.assertNotIn("Execution Time", data["plan"][0])
                    self.assertEqual(self.snapshot(version), before)

    def check_stored_case(self, version, label, statement, ran, names, role=""):
        before = self.snapshot(version)
        data = self.run_explain(version, "write", statement, role)
        self.assertTrue(data["ok"], data)
        self.assertEqual(data["ran"], ran, (label, data))
        self.assertEqual([hit["name"] for hit in data["downgrade"]], names, (label, data))
        if ran == "analyze":
            self.assertEqual(data["reason"], WRITE_ANALYZE_REASON)
            self.assertIn("Execution Time", data["plan"][0])
        else:
            self.assertNotIn("Execution Time", data["plan"][0])
            for name in names:
                self.assertIn(name, data["reason"])
        self.assertEqual(self.snapshot(version), before)

    def test_each_stored_sql_and_user_function_case_gives_the_expected_run_and_leaves_the_data_unchanged(self):
        for version in VERSIONS:
            for label, statement, ran, names in STORED_WRITE_CASES:
                with self.subTest(version=version, case=label):
                    self.check_stored_case(version, label, statement, ran, names)

    def test_a_domain_in_a_multirange_is_found_on_version_14_and_later(self):
        with self.subTest(version="18"):
            self.check_stored_case(
                "18", "a domain in a multirange", "INSERT INTO pgw.t_dom_mrng VALUES ('{[1,2)}'::pgw.rng_multirange)",
                "explain", ["query_to_xml"],
            )

    def test_the_role_without_superuser_rights_gets_the_catalog_run_and_the_function_check(self):
        cases = (
            ("a policy with no call", "INSERT INTO pgw.t_rls_ok SELECT 2 WHERE random() >= 0", "analyze", []),
            ("a policy with a call, WITH CHECK", "INSERT INTO pgw.t_rls_check VALUES (1)", "explain", ["query_to_xml"]),
            ("a policy with a call, USING", "UPDATE pgw.t_rls_using SET id = 2", "explain", ["query_to_xml"]),
        )
        for version in VERSIONS:
            for label, statement, ran, names in cases:
                with self.subTest(version=version, case=label):
                    self.check_stored_case(version, label, statement, ran, names, role="_app")

    def test_a_quoted_name_with_a_doubled_quote_is_matched_exactly(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                create = host_psql(
                    self.ports[version], "-c",
                    'CREATE FUNCTION pgw."My""Fn"() RETURNS int LANGUAGE plpgsql VOLATILE AS \'BEGIN RETURN 1; END\'; '
                    'CREATE VIEW pgw.v_dq AS SELECT id, v FROM pgw.plain WHERE pgw."My""Fn"() > 0',
                )
                self.assertEqual(create.returncode, 0, create.stderr)
                self.addCleanup(host_psql, self.ports[version], "-c", "DROP VIEW pgw.v_dq; DROP FUNCTION pgw.\"My\"\"Fn\"()")
                self.check_stored_case(
                    version, "a doubled quote", "UPDATE pgw.v_dq SET v = v + 1", "explain", ['pgw."My""Fn"']
                )

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
