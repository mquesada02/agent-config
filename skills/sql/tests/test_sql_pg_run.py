import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SCRIPT = os.path.join(SKILL, "scripts", "pg_run.py")

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
}

# Canary values: none of them may leave the wrapper in any output.
HOST = "db-canary.internal.example"
ADDR = "10.9.8.7"
PORT = "54329"
USER = "canary_user"
DBNAME = "canary_db"
PASSWORD = "canary-pass-123"
PASSFILE = "/home/canary_home/.pgpass"
CANARIES = (HOST, ADDR, PORT, USER, DBNAME, PASSWORD, PASSFILE, "canary_home", "canary_sock", "canary_opt")

FAKE_PSQL = r'''#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
names = ["PGOPTIONS", "PGPASSWORD", "PGSERVICE", "PGHOST", "PGHOSTADDR", "PGPORT", "PGUSER", "PGDATABASE",
         "PGSERVICEFILE", "PGPASSFILE", "PGCONNECT_TIMEOUT", "PGSSLMODE", "LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"]
stdin = sys.stdin.read() if os.environ.get("FAKE_READ_STDIN") else None
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({"argv": argv, "stdin": stdin, "env": {n: os.environ.get(n) for n in names}}) + "\n")
probe = any("SHOW server_version_num" in a for a in argv)
fail = os.environ.get("FAKE_FAIL_PROBE") if probe else os.environ.get("FAKE_FAIL")
if fail:
    if os.environ.get("FAKE_STDERR_HEX"):
        sys.stderr.buffer.write(bytes.fromhex(os.environ["FAKE_STDERR_HEX"]))
    else:
        sys.stderr.write(os.environ["FAKE_STDERR"])
    sys.exit(int(os.environ.get("FAKE_EXIT", "2")))
if probe:
    sys.stdout.write(os.environ.get("FAKE_VERSION", "180000") + "\n")
else:
    out = os.environ.get("FAKE_STDOUT")
    if out is None:
        out = json.dumps([{"Plan": {"Node Type": "Result", "Shared Hit Blocks": 0}}], indent=2)
    sys.stdout.write(out)
'''

AUTH_STDERR = (
    f'psql: error: connection to server at "{HOST}" ({ADDR}), port {PORT} failed: '
    f'FATAL:  password authentication failed for user "{USER}"\n'
    f'connection to server at "{HOST}" ({ADDR}), port {PORT} failed: FATAL:  no pg_hba.conf entry for host '
    f'"10.1.1.1", user "{USER}", database "{DBNAME}", no encryption\n'
    f'DETAIL:  Connection matched file "/etc/canary_home/pg_hba.conf" line 99: "host all all all md5"\n'
    f'WARNING: password file "{PASSFILE}" has group or world access; permissions should be u=rw (0600) or less\n'
)
UNREACHABLE_STDERR = (
    f'psql: error: connection to server at "{HOST}" ({ADDR}), port {PORT} failed: Connection refused\n'
    "\tIs the server running on that host and accepting TCP/IP connections?\n"
    f'psql: error: could not translate host name "{HOST}" to address: Name or service not known\n'
    f'psql: error: connection to server on socket "/var/run/canary_sock/.s.PGSQL.{PORT}" failed: No such file or directory\n'
    f"\tIs the server running locally and accepting connections on that socket? port {PORT}\n"
)
CONNINFO_STDERR = (
    f'psql: error: missing "=" after "{PASSWORD}" in connection info string\n'
    f'psql: error: invalid connection option "canary_opt"\n'
    f'psql: error: invalid URI query parameter: "{USER}"\n'
    f"psql: error: could not parse postgresql://{USER}:{PASSWORD}@{HOST}:{PORT}/{DBNAME}\n"
    f"psql: error: bad conninfo host={HOST} port={PORT} user={USER} password={PASSWORD} "
    f"dbname=\"{DBNAME}\" passfile='{PASSFILE}' HOST={HOST}\n"
)
SERVICE_STDERR = (
    f'psql: error: definition of service "app-dev" not found\n'
    f'psql: error: service file "{PASSFILE}" not found\n'
)


@unittest.skipUnless(sys.version_info >= (3, 11), "the scripts need tomllib (Python 3.11 or newer)")
class PgRunTestCase(unittest.TestCase):
    """`pg_run` run as a command, in a temp home, with a fake `psql` first on PATH."""

    ALLOWLIST_BODY = 'services = ["app-dev", "app-test"]\n'

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.home = os.path.join(self.root, "home")
        self.xdg = os.path.join(self.root, "xdg")
        self.repo = os.path.join(self.root, "repo")
        self.bin = os.path.join(self.root, "bin")
        self.log = os.path.join(self.root, "fake-psql.log")
        for folder in (self.home, self.xdg, self.repo, self.bin):
            os.makedirs(folder)
        fake = os.path.join(self.bin, "psql")
        with open(fake, "w") as handle:
            handle.write(FAKE_PSQL)
        os.chmod(fake, 0o755)
        self.env = {
            "PATH": self.bin + os.pathsep + os.environ["PATH"], "HOME": self.home,
            "XDG_CONFIG_HOME": self.xdg, "FAKE_LOG": self.log, **GIT_ENV,
        }
        self.git("init", "-q")
        self.git("remote", "add", "origin", "git@github.com:o/r.git")
        self.write_allowlist(self.ALLOWLIST_BODY)

    def git(self, *args):
        done = subprocess.run(["git", *args], cwd=self.repo, env=self.env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def write_allowlist(self, body):
        folder = os.path.join(self.xdg, "sql-skill")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "allowlist.toml"), "w") as handle:
            handle.write(f'["github.com/o/r"]\n{body}')

    def run_pg(self, *args, env=None, stdin=None):
        done = subprocess.run(
            [sys.executable, "-I", SCRIPT, *args], capture_output=True, text=True,
            env={**self.env, **(env or {})}, input=stdin, timeout=60,
        )
        return done

    def explain(self, statement, service="app-dev", env=None, extra=()):
        done = self.run_pg(
            "explain", "--repo", self.repo, "--service", service, "--mode", "select",
            "--statement", statement, *extra, env=env,
        )
        self.assertIn(done.returncode, (0, 1), done.stderr)
        return done.returncode, json.loads(done.stdout)

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as handle:
            return [json.loads(line) for line in handle]

    def probe_call(self):
        return next(c for c in self.calls() if any("SHOW server_version_num" in a for a in c["argv"]))

    def explain_call(self):
        return next(c for c in self.calls() if not any("SHOW server_version_num" in a for a in c["argv"]))


class GuardTest(PgRunTestCase):
    """The select guard, through the command line."""

    ACCEPTED = [
        "SELECT 1",
        "select 1;",
        "  /* c */ SELECT 1 -- x",
        "SELECT 1; -- trailing",
        "SELECT 1 ;  \n",
        "WITH a AS (SELECT 1) SELECT * FROM a",
        "SELECT ';' AS a, 'it''s' AS b",
        "SELECT E'a\\'b; c'",
        "SELECT $$a;b$$",
        "SELECT $t$x'y$t$",
        "SELECT /* a /* nested */ ; */ 1",
        "SELECT $1",
        "SELECT a, $1, $2 FROM t WHERE b = $1",
        'SELECT "update" FROM t',
        "SELECT a::text FROM t WHERE x = ANY($1)",
        "SELECT 1 -- ; SELECT 2",
        "SELECT E'a'\n'b\\'c'",
        "SELECT 'a'\n'b' AS x",
        "SELECT 'café' AS ñ",
        "SELECT 1\f,\v2",
    ]

    # (statement, reason, static_review_only)
    REFUSED = [
        ("", "empty", False),
        (";", "empty", False),
        ("-- only a comment", "empty", False),
        ("SELECT 'x", "unterminated", False),
        ("SELECT /* x", "unterminated", False),
        ("SELECT $$x", "unterminated", False),
        ('SELECT "x', "unterminated", False),
        ("SELECT 1; SELECT 2", "multiple_statements", False),
        ("SELECT 1;;", "multiple_statements", False),
        ("SELECT 1 --x\r; COMMIT; SET default_transaction_read_only=off", "multiple_statements", False),
        ("SELECT 1 -- x\r; DROP TABLE t", "multiple_statements", False),
        ("SELECT 1into t2", "data_modifying", False),
        ("SELECT 1.5into t2", "data_modifying", False),
        ("SELECT 1e5into t2", "data_modifying", False),
        ("SELECT 1.5E+5into t2", "data_modifying", False),
        ("SELECT .5e3into t2", "data_modifying", False),
        # PostgreSQL reads every non-ASCII character as an identifier character, so the guard must too.
        ("SELECT 1 ×$a$; COMMIT; DELETE FROM t; SELECT 1 ×$a$", "multiple_statements", False),
        ("SELECT 1  $a$; COMMIT; DELETE FROM t; SELECT 1  $a$", "multiple_statements", False),
        ("SELECT 1 \u0085$a$; COMMIT; DELETE FROM t; SELECT 1 \u0085$a$", "multiple_statements", False),
        ("SELECT 1 ; DELETE FROM t", "multiple_statements", False),
        # Only ASCII digits make a number or a placeholder: a Unicode digit is an identifier character.
        ("SELECT $١$ ' $١$; DELETE FROM t -- '", "multiple_statements", False),
        ("SELECT $１$ ' $１$; DELETE FROM t -- '", "multiple_statements", False),
        ("SELECT 1١$a$; DELETE FROM t; SELECT 1١$a$", "multiple_statements", False),
        ("SELECT 1.5١$a$; DELETE FROM t; SELECT 1.5١$a$", "multiple_statements", False),
        # A continued E string stays an escape string in the server (scan.l quotecontinue).
        ("SELECT E'a'\n'\\''; DELETE FROM t; SELECT 1 -- '", "multiple_statements", False),
        ("SELECT E'a'\r'\\''; DELETE FROM t; SELECT 1 -- '", "multiple_statements", False),
        ("SELECT E'a' -- c\n'\\''; DELETE FROM t; SELECT 1 -- '", "multiple_statements", False),
        ("SELECT E'a'\n  -- c\n  '\\''; DELETE FROM t; SELECT 1 -- '", "multiple_statements", False),
        ("SELECT E'a'\n'b'\n'\\''; DELETE FROM t; SELECT 1 -- '", "multiple_statements", False),
        ("SELECT 1; -- x\nSELECT 2", "multiple_statements", False),
        # A placeholder that is not at the start must not make the guard skip the text after it.
        ("SELECT $1; DELETE FROM t", "multiple_statements", False),
        ("SELECT a FROM t WHERE x = $1 AND y = $2; SELECT 2", "multiple_statements", False),
        ("SELECT 1 FROM t WHERE x = $1 INTO o", "data_modifying", False),
        ("SELECT $12, $0; DELETE FROM t", "multiple_statements", False),
        ("SELECT x$1; DELETE FROM t", "multiple_statements", False),
        ("SELECT 'a', $1; DELETE FROM t", "multiple_statements", False),
        ("SELECT E'a\\'b', $1; DELETE FROM t", "multiple_statements", False),
        ("SELECT $a$x$a$, $1; DELETE FROM t", "multiple_statements", False),
        ('SELECT "a""b", $1; DELETE FROM t', "multiple_statements", False),
        ("SELECT $1 /* c */ ; DELETE FROM t", "multiple_statements", False),
        ("SELECT $1 -- c\n; DELETE FROM t", "multiple_statements", False),
        ("SET x = 1; SELECT 1", "multiple_statements", False),
        ("INSERT INTO t VALUES (1)", "write_statement", False),
        ("update t set a = 1", "write_statement", False),
        ("DELETE FROM t", "write_statement", False),
        ("MERGE INTO t USING s ON true WHEN MATCHED THEN DELETE", "write_statement", False),
        ("INSERT INTO t SELECT pg_advisory_lock(1)", "write_statement", False),
    ] + [
        (statement, "not_select", True)
        for statement in (
            "SET default_transaction_read_only = off", "RESET ALL", "BEGIN", "START TRANSACTION", "COMMIT",
            "END", "ROLLBACK", "ABORT", "SET TRANSACTION READ WRITE", "VACUUM t", "LISTEN c", "UNLISTEN c",
            "NOTIFY c", "CREATE TABLE t (a int)", "CREATE INDEX CONCURRENTLY i ON t (a)", "DROP TABLE t",
            "ALTER TABLE t ADD c int", "EXPLAIN SELECT 1", "TRUNCATE t", "COPY t TO STDOUT",
            "DO $$ begin end $$", "CALL p()", "DISCARD ALL", "LOCK t", "REINDEX TABLE t", "GRANT ALL ON t TO u",
            "\\! rm x", "foo",
        )
    ] + [
        (statement, "not_select", False)
        for statement in ("TABLE t", "VALUES (1)", "(SELECT 1)", "(SELECT 1) UNION (SELECT 2)")
    ] + [
        (statement, "data_modifying", False)
        for statement in (
            "WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d",
            "WITH i AS (INSERT INTO t VALUES (1) RETURNING a) SELECT a FROM i",
            "WITH u AS (UPDATE t SET a = 1 RETURNING a) SELECT * FROM u",
            "WITH m AS (MERGE INTO t USING s ON true WHEN MATCHED THEN DELETE RETURNING 1) SELECT 1",
            "SELECT * INTO newt FROM t",
            "SELECT * FROM t FOR UPDATE",
            "SELECT update FROM t",
        )
    ] + [
        (statement, "forbidden_function", False)
        for statement in (
            "SELECT set_config('default_transaction_read_only', 'off', false)",
            "SELECT \"set_config\"('default_transaction_read_only', 'off', false)",
            "SELECT \"SET_CONFIG\"('a', 'b', false)",
            "SELECT SET_CONFIG('a', 'b', false)",
            "SELECT pg_catalog.set_config('a', 'b', false)",
            "SELECT pg_catalog.\"set_config\"('a', 'b', false)",
            "SELECT pg_advisory_lock(1)",
            "SELECT pg_try_advisory_xact_lock(1)",
            "SELECT pg_advisory_unlock_all()",
            "SELECT pg_notify('c', 'p')",
            "SELECT dblink_exec('x', 'y')",
            "SELECT dblink('x', 'y')",
            "SELECT lo_export(1, '/tmp/x')",
            "SELECT pg_advisory_lock FROM t",
        )
    ] + [
        ('SELECT U&"set\\005fconfig"(1)', "unicode_identifier", False),
    ]

    def test_each_accepted_form_reaches_psql(self):
        for statement in self.ACCEPTED:
            with self.subTest(statement=statement):
                if os.path.exists(self.log):
                    os.remove(self.log)
                code, data = self.explain(statement)
                self.assertEqual((code, data["ok"]), (0, True), data)
                self.assertEqual(len(self.calls()), 2)

    def test_each_refusal_has_its_reason_and_never_reaches_psql(self):
        for statement, reason, static in self.REFUSED:
            with self.subTest(statement=statement):
                if os.path.exists(self.log):
                    os.remove(self.log)
                code, data = self.explain(statement)
                self.assertEqual(code, 1)
                self.assertEqual(
                    (data["ok"], data["error"], data["reason"], data["static_review_only"]),
                    (False, "refused", reason, static),
                    data,
                )
                self.assertTrue(data["message"])
                self.assertEqual(self.calls(), [])

    def test_a_long_run_of_blanks_or_comments_after_an_e_string_is_scanned_in_linear_time(self):
        for statement in (
            "select e'a'\n" + " " * 5000 + "x",
            "select e'a' " + "-- " * 5000 + "\n x",
            "select e'a'\n" + "-- c\n" * 3000 + "x",
            "select e'a'\n" + " \n" * 3000 + "x",
        ):
            with self.subTest(statement=statement[:30]):
                started = time.monotonic()
                code, data = self.explain(statement)
                self.assertLess(time.monotonic() - started, 10)
                self.assertIn(code, (0, 1))

    def test_the_trailing_semicolon_and_everything_after_it_are_cut(self):
        self.explain("SELECT 1; -- x")
        text = self.explain_call()["argv"]
        explain_text = next(a for a in text if a.startswith("EXPLAIN"))
        self.assertTrue(explain_text.endswith("SELECT 1"), explain_text)

    def test_a_statement_is_read_from_stdin_when_there_is_no_statement_option(self):
        done = self.run_pg("explain", "--repo", self.repo, "--service", "app-dev", "--mode", "select", stdin="SELECT 42\n")
        self.assertEqual(done.returncode, 0, done.stderr)
        explain_text = next(a for a in self.explain_call()["argv"] if a.startswith("EXPLAIN"))
        self.assertIn("SELECT 42", explain_text)


class AllowlistFirstTest(PgRunTestCase):
    def test_a_service_that_is_not_listed_is_refused_with_no_psql_run(self):
        for service in ("other", "app-dev2", "a b", "app-dev'"):
            with self.subTest(service=service):
                code, data = self.explain("SELECT 1", service=service)
                self.assertEqual(code, 1)
                self.assertEqual((data["ok"], data["error"], data["reason"]), (False, "not_allowed", "service_not_listed"))
                self.assertNotIn("message", data)
                self.assertEqual(self.calls(), [])

    def test_no_allowlist_file_gives_not_allowed_with_the_reader_reason(self):
        os.remove(os.path.join(self.xdg, "sql-skill", "allowlist.toml"))
        code, data = self.explain("SELECT 1")
        self.assertEqual((code, data["error"], data["reason"]), (1, "not_allowed", "missing_file"))
        self.assertEqual(self.calls(), [])

    def test_a_malformed_allowlist_gives_not_allowed(self):
        self.write_allowlist('services = "x"\n')
        code, data = self.explain("SELECT 1")
        self.assertEqual((code, data["error"], data["reason"]), (1, "not_allowed", "malformed_file"))
        self.assertEqual(self.calls(), [])

    def test_the_allowlist_is_checked_before_the_guard(self):
        code, data = self.explain("DROP TABLE t", service="other")
        self.assertEqual(data["error"], "not_allowed")


class UsageTest(PgRunTestCase):
    def test_write_mode_the_diff_action_and_a_facts_call_with_no_names_are_usage_errors(self):
        cases = [
            ("explain", "--repo", self.repo if False else "r", "--service", "app-dev", "--mode", "write", "--statement", "DELETE FROM t"),
            ("diff", "--repo", "r", "--service", "app-dev"),
            ("facts", "--repo", "r", "--service", "app-dev"),
            ("bogus",),
            (),
            ("explain", "--repo", "r", "--service", "app-dev", "--statement", "SELECT 1"),
            ("explain", "--service", "app-dev", "--mode", "select", "--statement", "SELECT 1"),
            ("explain", "--repo", "r", "--mode", "select", "--statement", "SELECT 1"),
            ("explain", "--repo", "r", "--service", "app-dev", "--mode", "select", "--bogus"),
        ]
        for args in cases:
            with self.subTest(args=args):
                done = self.run_pg(*args)
                self.assertEqual(done.returncode, 2)
                self.assertEqual(done.stdout, "")
                self.assertTrue(done.stderr.strip())
                self.assertEqual(self.calls(), [])


class ConnectionTest(PgRunTestCase):
    def test_the_psql_command_lines(self):
        code, data = self.explain("SELECT 1 AS one")
        self.assertEqual(code, 0)
        probe, run = self.calls()
        for call in (probe, run):
            self.assertIn("-X", call["argv"])
            self.assertIn("-w", call["argv"])
            self.assertTrue(call["argv"][-1].startswith("service=app-dev options='"), call["argv"][-1])
            self.assertNotIn("password", json.dumps(call["argv"]).lower())
            self.assertNotIn("host=", json.dumps(call["argv"]))
        self.assertIn("-At", probe["argv"])
        self.assertEqual(probe["argv"][probe["argv"].index("-c") + 1], "SHOW server_version_num")
        self.assertIn("ON_ERROR_STOP=1", run["argv"])
        commands = [run["argv"][i + 1] for i, a in enumerate(run["argv"]) if a == "-c"]
        self.assertEqual(
            commands,
            ["BEGIN READ ONLY", "EXPLAIN (ANALYZE, FORMAT JSON) SELECT 1 AS one", "ROLLBACK"],
        )

    def test_the_session_options_per_version(self):
        base = (
            "-c default_transaction_read_only=on -c standard_conforming_strings=on "
            "-c statement_timeout=30s -c lock_timeout=2s -c idle_in_transaction_session_timeout=10s"
        )
        cases = [
            ("130005", base, "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT 1"),
            ("160013", base, "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT 1"),
            ("170002", base + " -c transaction_timeout=60s", "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT 1"),
            ("180000", base + " -c transaction_timeout=60s", "EXPLAIN (ANALYZE, FORMAT JSON) SELECT 1"),
        ]
        for version, options, explain_text in cases:
            with self.subTest(version=version):
                if os.path.exists(self.log):
                    os.remove(self.log)
                code, data = self.explain("SELECT 1", env={"FAKE_VERSION": version})
                self.assertEqual(code, 0, data)
                self.assertEqual(data["server_version_num"], int(version))
                self.assertEqual(self.probe_call()["argv"][-1], f"service=app-dev options='{base}'")
                self.assertEqual(self.explain_call()["argv"][-1], f"service=app-dev options='{options}'")
                commands = [self.explain_call()["argv"][i + 1] for i, a in enumerate(self.explain_call()["argv"]) if a == "-c"]
                self.assertEqual(commands[1], explain_text)
                expected = {"statement_timeout": "30s", "lock_timeout": "2s", "idle_in_transaction_session_timeout": "10s"}
                if int(version) >= 170000:
                    expected["transaction_timeout"] = "60s"
                self.assertEqual(data["timeouts"], expected)

    def test_a_per_service_override_wins_in_the_probe_and_the_run(self):
        self.write_allowlist(
            'services = ["app-dev", "app-test"]\n'
            '["github.com/o/r".timeouts.app-dev]\n'
            'statement_timeout = "45s"\ntransaction_timeout = "5min"\nlock_timeout = "500ms"\n'
        )
        for version, with_tt in (("160000", False), ("170000", True)):
            with self.subTest(version=version):
                if os.path.exists(self.log):
                    os.remove(self.log)
                code, data = self.explain("SELECT 1", env={"FAKE_VERSION": version})
                self.assertEqual(code, 0, data)
                probe = self.probe_call()["argv"][-1]
                run = self.explain_call()["argv"][-1]
                self.assertIn("-c statement_timeout=45s -c lock_timeout=500ms", probe)
                self.assertNotIn("transaction_timeout", probe)
                self.assertIn("-c statement_timeout=45s -c lock_timeout=500ms", run)
                self.assertEqual("-c transaction_timeout=5min" in run, with_tt)
                self.assertEqual(data["timeouts"]["statement_timeout"], "45s")
        code, other = self.explain("SELECT 1", service="app-test")
        self.assertEqual(other["timeouts"]["statement_timeout"], "30s")

    def test_the_environment_of_psql(self):
        env = {
            "PGPASSWORD": PASSWORD, "PGSERVICE": "other", "PGOPTIONS": "-c default_transaction_read_only=off",
            "PGHOST": HOST, "PGHOSTADDR": ADDR, "PGPORT": PORT, "PGUSER": USER, "PGDATABASE": DBNAME,
            "PGSERVICEFILE": "/tmp/service-file-fixture", "PGPASSFILE": "/tmp/pass-file-fixture", "PGSSLMODE": "require",
        }
        code, data = self.explain("SELECT 1", env=env)
        self.assertEqual(code, 0, data)
        for call in self.calls():
            seen = call["env"]
            for name in ("PGPASSWORD", "PGSERVICE", "PGOPTIONS", "PGHOST", "PGHOSTADDR", "PGPORT", "PGUSER", "PGDATABASE"):
                self.assertIsNone(seen[name], name)
            self.assertEqual(seen["PGSERVICEFILE"], "/tmp/service-file-fixture")
            self.assertEqual(seen["PGPASSFILE"], "/tmp/pass-file-fixture")
            self.assertEqual(seen["PGSSLMODE"], "require")
            self.assertEqual(seen["PGCONNECT_TIMEOUT"], "10")
        self.assertNotIn(PASSWORD, json.dumps(data))

    def test_psql_always_talks_english_so_that_the_redaction_reads_its_messages(self):
        env = {"LANGUAGE": "de", "LC_ALL": "de_DE.UTF-8", "LC_MESSAGES": "de_DE.UTF-8", "LANG": "de_DE.UTF-8"}
        code, data = self.explain("SELECT 1", env=env)
        self.assertEqual(code, 0, data)
        for call in self.calls():
            seen = call["env"]
            self.assertEqual(seen["LC_ALL"], "C")
            for name in ("LANGUAGE", "LC_MESSAGES", "LANG"):
                self.assertIsNone(seen[name], name)

    def test_the_success_output_has_a_plan_and_no_other_psql_text(self):
        code, data = self.explain("SELECT 1")
        self.assertEqual(code, 0)
        self.assertEqual(
            sorted(data),
            sorted(["ok", "action", "service", "mode", "server_version_num", "ran", "reason", "timeouts", "warnings", "plan"]),
        )
        self.assertEqual((data["ok"], data["action"], data["service"], data["mode"], data["ran"]), (True, "explain", "app-dev", "select", "analyze"))
        self.assertEqual(data["warnings"], [])
        self.assertIsInstance(data["plan"], list)
        self.assertEqual(data["plan"][0]["Plan"]["Node Type"], "Result")


class FailureTest(PgRunTestCase):
    def failure(self, stderr, exit_code="2", **env):
        code, data = self.explain("SELECT 1", env={"FAKE_FAIL": "1", "FAKE_STDERR": stderr, "FAKE_EXIT": exit_code, **env})
        self.assertEqual(code, 1)
        self.assertFalse(data["ok"])
        return data

    def assertNoCanary(self, data):
        text = json.dumps(data)
        for canary in CANARIES:
            self.assertNotIn(canary, text)

    def test_each_connection_failure_kind_leaks_no_connection_value(self):
        for name, stderr in (
            ("service", SERVICE_STDERR), ("auth", AUTH_STDERR), ("unreachable", UNREACHABLE_STDERR),
            ("conninfo", CONNINFO_STDERR),
        ):
            with self.subTest(kind=name):
                data = self.failure(stderr)
                self.assertEqual(data["error"], "connection_failed")
                self.assertNoCanary(data)
                self.assertIn("app-dev", data["message"])
                self.assertEqual(sorted(data), ["error", "message", "ok"])

    def test_the_probe_failure_gives_the_same_output(self):
        code, data = self.explain("SELECT 1", env={"FAKE_FAIL_PROBE": "1", "FAKE_STDERR": AUTH_STDERR, "FAKE_EXIT": "2"})
        self.assertEqual((code, data["error"]), (1, "connection_failed"))
        self.assertNoCanary(data)
        self.assertEqual(len(self.calls()), 1)

    def test_a_statement_error_keeps_its_relation_names_and_the_line_echo(self):
        stderr = (
            'ERROR:  relation "orders_canary" does not exist\n'
            'LINE 1: EXPLAIN (ANALYZE, FORMAT JSON) SELECT * FROM "orders_canary" WHERE "x_col" = 1\n'
            "                                                     ^\n"
            'HINT:  Perhaps you meant column "x_col".\n'
        )
        for exit_code in ("1", "3"):
            with self.subTest(exit=exit_code):
                data = self.failure(stderr, exit_code)
                self.assertEqual(data["error"], "statement_failed")
                self.assertIn('relation "orders_canary" does not exist', data["message"])
                self.assertIn('FROM "orders_canary" WHERE "x_col"', data["message"])
                self.assertIn('column "x_col"', data["message"])

    def test_a_quoted_role_or_database_in_an_error_block_is_replaced(self):
        stderr = (
            f'ERROR:  role "{USER}" does not exist\n'
            f'DETAIL:  database "{DBNAME}" is bad; host={HOST} port {PORT} ({ADDR})\n'
            f"HINT:  see postgresql://{USER}:{PASSWORD}@{HOST}/{DBNAME}\n"
        )
        data = self.failure(stderr, "3")
        self.assertEqual(data["error"], "statement_failed")
        self.assertNoCanary(data)
        self.assertIn("app-dev", data["message"])

    def test_a_line_after_the_error_block_is_redacted_again(self):
        stderr = f'ERROR:  relation "keep_me" does not exist\nFATAL:  terminating connection for user "{USER}"\n'
        data = self.failure(stderr, "3")
        self.assertIn('relation "keep_me"', data["message"])
        self.assertNoCanary(data)

    def test_the_object_words_match_in_any_case_and_a_quote_with_no_word_is_replaced(self):
        stderr = f'ERROR:  Table "t_canary_ok" is bad\n"{USER}" alone\n  "{DBNAME}"\n'
        data = self.failure(stderr, "3")
        self.assertIn('Table "t_canary_ok"', data["message"])
        self.assertNoCanary(data)

    def test_the_whole_conninfo_assignment_forms_are_replaced(self):
        stderr = (
            f"psql: error: x host = {HOST} hostaddr={ADDR} PORT='{PORT}' User={USER} "
            f'password="{PASSWORD}" dbname={DBNAME} service=svc options=\'-c a=b\' sslrootcert=/x/y ghost=keep\n'
        )
        data = self.failure(stderr)
        self.assertNoCanary(data)
        self.assertIn("ghost=keep", data["message"])
        self.assertNotIn("sslrootcert=/x/y", data["message"])
        self.assertNotIn("-c a=b", data["message"])

    def test_the_port_number_is_replaced_after_the_word_port(self):
        data = self.failure("psql: error: no listener on host, Port 5999 refused\n")
        self.assertNotIn("5999", data["message"])
        for text in ("port  5998 x", "port\t\t5997 x", "port   5996 x"):
            with self.subTest(text=text):
                data = self.failure(f"psql: error: {text}\n")
                self.assertNotRegex(data["message"], r"599\d")

    def test_an_ipv6_address_with_a_zone_in_parentheses_is_replaced(self):
        data = self.failure('psql: error: connection to server at "h" (fe80::1%canary_eth0), port 5432 failed\n')
        self.assertNotIn("canary_eth0", data["message"])
        self.assertNotIn("fe80", data["message"])

    def test_a_version_with_a_huge_number_of_digits_is_bad_output(self):
        code, data = self.explain("SELECT 1", env={"FAKE_VERSION": "1" * 5000})
        self.assertEqual((code, data["error"]), (1, "bad_output"))

    def test_a_quoted_value_with_a_backslash_escape_is_replaced_whole(self):
        for stderr in (
            "psql: error: host='canary_a\\'canary_b canary_c' x\n",
            'psql: error: host="canary_a\\"canary_b canary_c" x\n',
            "psql: error: dbname='canary_a\\\\' canary_b\n",
        ):
            with self.subTest(stderr=stderr):
                data = self.failure(stderr)
                self.assertNotIn("canary_a", data["message"])
                self.assertNotIn("canary_c", data["message"])

    def test_a_uri_is_replaced_when_a_digit_or_a_sign_comes_right_before_its_scheme(self):
        for text in ("1postgres://canary_u:canary_p@canary_h/db", "ok 9http://canary_u@canary_h/x", "-+.x://canary_h"):
            with self.subTest(text=text):
                data = self.failure(f"psql: error: {text}\n")
                self.assertNotIn("canary", data["message"])

    def test_a_very_long_token_is_redacted_in_linear_time(self):
        for stderr in (
            "ERROR:  x: " + "a" * 60000 + "\n",
            "ERROR:  x: " + "a" * 60000 + ' "x"\n',
            "psql: error: " + "a" * 60000 + "\n",
        ):
            with self.subTest(stderr=stderr[:20]):
                started = time.monotonic()
                self.failure(stderr, "3")
                self.assertLess(time.monotonic() - started, 5)

    def test_an_assignment_with_an_unterminated_quote_is_replaced_to_the_end_of_the_line(self):
        for stderr in ("psql: error: host='canary_a canary_b\n", 'psql: error: dbname="canary_a canary_b\n'):
            with self.subTest(stderr=stderr):
                data = self.failure(stderr)
                self.assertNotIn("canary", data["message"])

    def test_redaction_runs_before_the_cut_to_2000_characters(self):
        stderr = "psql: error: " + "a" * 1980 + f" password={PASSWORD} end\n" + "b" * 3000
        data = self.failure(stderr)
        self.assertLessEqual(len(data["message"]), 2000)
        self.assertNotIn("canary", data["message"])
        self.assertNotIn("password=", data["message"])

    def test_an_exit_with_no_error_line_is_psql_failed(self):
        data = self.failure("psql: fatal: out of memory\n", "1")
        self.assertEqual(data["error"], "psql_failed")
        self.assertTrue(data["message"])

    def test_a_psql_that_is_not_on_path_is_psql_failed(self):
        only_git = os.path.join(self.root, "only-git")
        os.makedirs(only_git)
        os.symlink(shutil.which("git"), os.path.join(only_git, "git"))
        code, data = self.explain("SELECT 1", env={"PATH": only_git})
        self.assertEqual((code, data["ok"], data["error"], data["message"]), (1, False, "psql_failed", "psql was not found on PATH"))

    def test_bytes_that_are_not_utf8_are_replaced_and_redacted_with_one_json_object(self):
        stderr = ("psql: error: caf\xff host=" + HOST + " end\n").encode("latin-1")
        code, data = self.explain(
            "SELECT 1", env={"FAKE_FAIL": "1", "FAKE_STDERR_HEX": stderr.hex(), "FAKE_STDERR": "x", "FAKE_EXIT": "2"}
        )
        self.assertEqual((code, data["error"]), (1, "connection_failed"))
        self.assertNotIn(HOST, data["message"])

    def test_a_statement_with_a_nul_byte_or_bad_bytes_on_stdin_gives_one_json_object(self):
        for stdin in (b"SELECT 1\x00", b"SELECT 1 -- \xff"):
            with self.subTest(stdin=stdin):
                done = subprocess.run(
                    [sys.executable, "-I", SCRIPT, "explain", "--repo", self.repo, "--service", "app-dev",
                     "--mode", "select"],
                    capture_output=True, env=self.env, input=stdin, timeout=60,
                )
                self.assertIn(done.returncode, (0, 1), done.stderr)
                self.assertNotIn(b"Traceback", done.stderr)
                json.loads(done.stdout)

    def test_a_psql_that_cannot_be_run_is_psql_failed_with_one_json_object(self):
        only_git = os.path.join(self.root, "only-git-2")
        os.makedirs(only_git)
        os.symlink(shutil.which("git"), os.path.join(only_git, "git"))
        locked = os.path.join(only_git, "psql")
        with open(locked, "w") as handle:
            handle.write("#!/bin/sh\n")
        os.chmod(locked, 0o644)
        code, data = self.explain("SELECT 1", env={"PATH": only_git})
        self.assertEqual((code, data["ok"], data["error"]), (1, False, "psql_failed"))
        self.assertTrue(data["message"])

    def test_output_that_is_not_one_json_list_is_bad_output(self):
        for out in ("", "not json", '{"a": 1}', '[1] [2]', "[1]\ngarbage"):
            with self.subTest(stdout=out):
                code, data = self.explain("SELECT 1", env={"FAKE_STDOUT": out})
                self.assertEqual((code, data["ok"], data["error"]), (1, False, "bad_output"))
                self.assertTrue(data["message"])
                self.assertNotIn("not json", data["message"])

    def test_a_version_that_is_not_an_integer_is_bad_output(self):
        code, data = self.explain("SELECT 1", env={"FAKE_VERSION": "abc"})
        self.assertEqual((code, data["error"]), (1, "bad_output"))
        self.assertEqual(len(self.calls()), 1)


class FactsTest(PgRunTestCase):
    """The `facts` action, through the command line, with the fake `psql` (it records its stdin here)."""

    def run_facts(self, *names, service="app-dev", rows=None, env=None):
        env = {"FAKE_READ_STDIN": "1", **(env or {})}
        if rows is not None:
            env["FAKE_STDOUT"] = json.dumps(rows)
        done = self.run_pg("facts", "--repo", self.repo, "--service", service, "--names", *names, env=env)
        self.assertIn(done.returncode, (0, 1), done.stderr)
        return done.returncode, json.loads(done.stdout)

    def facts_call(self):
        return self.explain_call()

    @staticmethod
    def sent_names(call):
        argv = call["argv"]
        value = next(argv[i + 1] for i, a in enumerate(argv) if a == "-v" and argv[i + 1].startswith("names="))
        return json.loads(value[len("names="):])

    def test_a_service_that_is_not_listed_or_no_allowlist_gives_not_allowed_with_no_psql_run(self):
        code, data = self.run_facts("t.c", service="other")
        self.assertEqual((code, data["ok"], data["error"], data["reason"]), (1, False, "not_allowed", "service_not_listed"))
        os.remove(os.path.join(self.xdg, "sql-skill", "allowlist.toml"))
        code, data = self.run_facts("t.c")
        self.assertEqual((code, data["error"], data["reason"]), (1, "not_allowed", "missing_file"))
        self.assertEqual(self.calls(), [])

    def test_the_probe_runs_first_then_one_run_with_the_read_only_session_options(self):
        self.write_allowlist('services = ["app-dev"]\n["github.com/o/r".timeouts.app-dev]\nstatement_timeout = "45s"\n')
        code, data = self.run_facts("users.id", rows=[{"i": 0, "nullable": False, "type": "integer"}])
        self.assertEqual(code, 0, data)
        probe, run = self.calls()
        self.assertEqual(probe["argv"][probe["argv"].index("-c") + 1], "SHOW server_version_num")
        for call in (probe, run):
            self.assertIn("-X", call["argv"])
            self.assertIn("-w", call["argv"])
        self.assertIn("ON_ERROR_STOP=1", run["argv"])
        self.assertNotIn("-c", run["argv"])
        last = run["argv"][-1]
        self.assertTrue(last.startswith("service=app-dev options='"), last)
        self.assertIn("-c default_transaction_read_only=on", last)
        self.assertIn("-c statement_timeout=45s", last)
        self.assertIn("-c lock_timeout=2s", last)
        self.assertIn("-c idle_in_transaction_session_timeout=10s", last)
        self.assertIn("-c transaction_timeout=60s", last)

    def test_the_script_on_stdin_is_constant_and_holds_none_of_the_names(self):
        hostile = ["t.c'; DROP TABLE secret; --", 'a."b"', "x.y\\z", "s.t.$$c$$"]
        self.run_facts("users.id", rows=[])
        self.run_facts(*hostile, rows=[])
        first, second = [c for c in self.calls() if c["stdin"]]
        self.assertEqual(first["stdin"], second["stdin"])
        script = first["stdin"]
        self.assertTrue(script.startswith("BEGIN READ ONLY;"), script)
        self.assertTrue(script.rstrip().endswith("ROLLBACK;"), script)
        self.assertIn(":'names'", script)
        self.assertNotIn("DROP", script)
        for call in (first, second):
            self.assertNotIn("-c", call["argv"])
        outside = [a for a in second["argv"] if not a.startswith("names=")]
        self.assertNotIn("DROP TABLE secret", json.dumps(outside))
        self.assertIn("DROP TABLE secret", json.dumps(second["argv"]))

    def test_the_names_value_holds_the_parsed_parts_and_a_repeated_name_is_sent_once(self):
        code, data = self.run_facts(
            "users.id", "shop.orders.total", "users.id",
            rows=[{"i": 0, "nullable": False, "type": "integer"}, {"i": 1, "nullable": True, "type": "numeric(10,2)"}],
        )
        self.assertEqual(code, 0, data)
        self.assertEqual(self.sent_names(self.facts_call()), [[0, None, "users", "id"], [1, "shop", "orders", "total"]])
        self.assertEqual(list(data["facts"]), ["users.id", "shop.orders.total"])

    def test_a_name_of_an_invalid_shape_is_missing_and_is_not_sent(self):
        names = ["nodot", "a.b.c.d", "a..b", ".x", "a.", "users.id"]
        code, data = self.run_facts(*names, rows=[{"i": 0, "nullable": True, "type": "text"}])
        self.assertEqual(code, 0, data)
        self.assertEqual(self.sent_names(self.facts_call()), [[0, None, "users", "id"]])
        self.assertEqual(list(data["facts"]), names)
        for name in names[:-1]:
            self.assertEqual(data["facts"][name], {"missing": True})
        self.assertEqual(data["facts"]["users.id"], {"nullable": True, "type": "text"})

    def test_when_no_name_has_a_valid_shape_psql_is_never_called(self):
        code, data = self.run_facts("nodot", "a.b.c.d")
        self.assertEqual(code, 0, data)
        self.assertEqual(data, {"ok": True, "action": "facts", "service": "app-dev",
                                "facts": {"nodot": {"missing": True}, "a.b.c.d": {"missing": True}}})
        self.assertEqual(self.calls(), [])

    def test_a_name_with_a_non_ascii_or_control_character_is_missing_and_is_not_sent(self):
        names = ["users.café", "users.i\td", "users.ok"]
        code, data = self.run_facts(*names, rows=[{"i": 0, "nullable": False, "type": "text"}])
        self.assertEqual(code, 0, data)
        self.assertEqual(self.sent_names(self.facts_call()), [[0, None, "users", "ok"]])
        self.assertEqual(data["facts"]["users.café"], {"missing": True})
        self.assertEqual(data["facts"]["users.i\td"], {"missing": True})

    def test_the_rows_map_to_nullable_type_and_missing(self):
        rows = [
            {"i": 0, "nullable": True, "type": "text"},
            {"i": 1, "nullable": False, "type": "integer"},
            {"i": 2, "nullable": None, "type": "date"},
        ]
        code, data = self.run_facts("t.a", "t.b", "v.c", "t.gone", rows=rows)
        self.assertEqual(code, 0, data)
        self.assertEqual(sorted(data), ["action", "facts", "ok", "service"])
        self.assertEqual(data["facts"], {
            "t.a": {"nullable": True, "type": "text"}, "t.b": {"nullable": False, "type": "integer"},
            "v.c": {"nullable": None, "type": "date"}, "t.gone": {"missing": True},
        })

    def test_an_empty_row_list_is_every_name_missing_and_not_bad_output(self):
        code, data = self.run_facts("t.a", rows=[])
        self.assertEqual((code, data["facts"]), (0, {"t.a": {"missing": True}}))

    def test_a_result_that_is_not_a_list_of_valid_rows_is_bad_output(self):
        for out in ("", "not json", "{}", "[1]", '[{"i": 5, "nullable": true, "type": "x"}]',
                    '[{"i": "0", "nullable": true, "type": "x"}]', '[{"i": true, "nullable": true, "type": "x"}]',
                    '[{"i": -1, "nullable": true, "type": "x"}]', '[{"nullable": true, "type": "x"}]',
                    '[{"i": 0, "nullable": "yes", "type": "x"}]', '[{"i": 0, "nullable": true, "type": 7}]'):
            with self.subTest(stdout=out):
                code, data = self.run_facts("t.a", env={"FAKE_STDOUT": out})
                self.assertEqual((code, data["ok"], data["error"]), (1, False, "bad_output"))
                self.assertNotIn("not json", data["message"])

    def test_no_names_is_a_usage_error(self):
        done = self.run_pg("facts", "--repo", self.repo, "--service", "app-dev")
        self.assertEqual((done.returncode, done.stdout), (2, ""))
        self.assertTrue(done.stderr.strip())
        self.assertEqual(self.calls(), [])

    def test_each_connection_failure_kind_leaks_no_connection_value_in_the_probe_and_the_run(self):
        for name, stderr in (
            ("service", SERVICE_STDERR), ("auth", AUTH_STDERR), ("unreachable", UNREACHABLE_STDERR),
            ("conninfo", CONNINFO_STDERR),
        ):
            for stage in ("FAKE_FAIL_PROBE", "FAKE_FAIL"):
                with self.subTest(kind=name, stage=stage):
                    code, data = self.run_facts("t.a", env={stage: "1", "FAKE_STDERR": stderr, "FAKE_EXIT": "2"})
                    self.assertEqual((code, data["error"]), (1, "connection_failed"))
                    text = json.dumps(data)
                    for canary in CANARIES:
                        self.assertNotIn(canary, text)
                    self.assertIn("app-dev", data["message"])

    def test_the_version_gate_applies_to_the_run(self):
        self.run_facts("t.a", rows=[], env={"FAKE_VERSION": "130005"})
        self.assertNotIn("transaction_timeout", self.facts_call()["argv"][-1])


if __name__ == "__main__":
    unittest.main()
