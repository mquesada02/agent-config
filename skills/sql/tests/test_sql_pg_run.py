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
stdin = sys.stdin.read() if os.environ.get("FAKE_READ_STDIN") or any(a.startswith("targets=") for a in argv) else None
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({"argv": argv, "stdin": stdin, "env": {n: os.environ.get(n) for n in names}}) + "\n")
# The three sessions of `diff` are told apart by their argv: the describe session has `LIMIT 0`, the type session
# `pg_typeof`, the proof session its first CTE.
describe = any("LIMIT 0" in a for a in argv)
probe = any("SHOW server_version_num" in a for a in argv) and not describe
# The kind of a write-mode run, from its argv: the catalog script has the `targets=` variable, the others
# are told apart by the start of their EXPLAIN text.
kind = "probe" if probe else "run"
if describe:
    kind = "describe"
if any("pg_typeof" in a for a in argv):
    kind = "types"
if any("pgrun_ra AS MATERIALIZED" in a for a in argv):
    kind = "proof"
if any(a.startswith("targets=") for a in argv):
    kind = "catalog"
for a in argv:
    for prefix, name in (("EXPLAIN (VERBOSE", "discovery"), ("EXPLAIN (FORMAT JSON)", "plain"), ("EXPLAIN (ANALYZE", "analyze")):
        if a.startswith(prefix):
            kind = name
fail = os.environ.get("FAKE_FAIL_PROBE") if probe else os.environ.get("FAKE_FAIL")
if kind in os.environ.get("FAKE_FAIL_KIND", "").split(","):
    fail = "1"
if fail:
    if os.environ.get("FAKE_STDERR_HEX"):
        sys.stderr.buffer.write(bytes.fromhex(os.environ["FAKE_STDERR_HEX"]))
    else:
        sys.stderr.write(os.environ.get("FAKE_STDERR", "ERROR:  fake failure\n"))
    sys.exit(int(os.environ.get("FAKE_EXIT", "2")))
if probe:
    sys.stdout.write(os.environ.get("FAKE_VERSION", "180000") + "\n")
else:
    out = os.environ.get("FAKE_STDOUT_" + kind.upper(), os.environ.get("FAKE_STDOUT"))
    if out is None and kind == "discovery":
        out = json.dumps([{"Plan": {"Node Type": "ModifyTable", "Operation": "Update", "Schema": "public", "Relation Name": "t"}}])
    if out is None and kind == "catalog":
        out = json.dumps({"hits": [], "sequence": False})
    if out is None and kind == "describe":
        out = "server_version_num\n" + os.environ.get("FAKE_VERSION", "180000") + "\n" + os.environ.get("FAKE_HEADERS", "id\nid\n")
    if out is None and kind == "types":
        out = json.dumps({"a": [23], "b": [23], "types": {"23": {"name": "integer", "float": False, "equality": True, "leaf": 23}}})
    if out is None and kind == "proof":
        out = json.dumps({"ra": 0, "rb": 0, "oa_count": 0, "ob_count": 0, "oa": [], "ob": []})
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

    def explain_write(self, statement, service="app-dev", env=None, extra=()):
        done = self.run_pg(
            "explain", "--repo", self.repo, "--service", service, "--mode", "write",
            "--statement", statement, *extra, env=env,
        )
        self.assertIn(done.returncode, (0, 1), done.stderr)
        return done.returncode, json.loads(done.stdout)

    def reset_log(self):
        if os.path.exists(self.log):
            os.remove(self.log)

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
    def test_an_unknown_mode_a_diff_or_facts_call_with_a_missing_argument_and_other_bad_calls_are_usage_errors(self):
        cases = [
            ("explain", "--repo", "r", "--service", "app-dev", "--mode", "rewrite", "--statement", "DELETE FROM t"),
            ("diff", "--repo", "r", "--service", "app-dev"),
            ("diff", "--repo", "r", "--service", "app-dev", "--a=SELECT 1"),
            ("diff", "--repo", "r", "--service", "app-dev", "--b=SELECT 1"),
            ("diff", "--repo", "r", "--a=SELECT 1", "--b=SELECT 1"),
            ("diff", "--service", "app-dev", "--a=SELECT 1", "--b=SELECT 1"),
            ("diff", "--repo", "r", "--service", "app-dev", "--a", "--x", "--b=SELECT 1"),
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
            sorted(["ok", "action", "service", "mode", "server_version_num", "ran", "reason", "timeouts", "downgrade", "warnings", "plan"]),
        )
        self.assertEqual(data["downgrade"], [])
        self.assertEqual(data["reason"], "no call of a function that runs SQL from a string")
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
        self.assertEqual(self.sent_names(self.explain_call()), [[0, None, "users", "id"], [1, "shop", "orders", "total"]])
        self.assertEqual(list(data["facts"]), ["users.id", "shop.orders.total"])

    def test_a_name_of_an_invalid_shape_is_missing_and_is_not_sent(self):
        names = ["nodot", "a.b.c.d", "a..b", ".x", "a.", "users.id"]
        code, data = self.run_facts(*names, rows=[{"i": 0, "nullable": True, "type": "text"}])
        self.assertEqual(code, 0, data)
        self.assertEqual(self.sent_names(self.explain_call()), [[0, None, "users", "id"]])
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
        self.assertEqual(self.sent_names(self.explain_call()), [[0, None, "users", "ok"]])
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
        self.assertNotIn("transaction_timeout", self.explain_call()["argv"][-1])


def as_write(statement):
    """A select-mode lexer case turned into a write statement: the text after `INSERT INTO t` is the same."""
    return "INSERT INTO t " + statement if statement.lstrip().upper().startswith(("SELECT", "WITH", "/*")) else statement


class WriteGuardTest(PgRunTestCase):
    """The write guard, through the command line (`--mode write`)."""

    ACCEPTED = [
        "INSERT INTO t VALUES (1)",
        "insert into t values (1);",
        "UPDATE t SET a = 1",
        "DELETE FROM t WHERE a = 1",
        "MERGE INTO t USING s ON true WHEN MATCHED THEN DELETE",
        "WITH a AS (SELECT 1) INSERT INTO t SELECT * FROM a",
        "WITH RECURSIVE a AS (SELECT 1) INSERT INTO t SELECT * FROM a",
        "WITH a AS (SELECT 1), b AS (SELECT 2) DELETE FROM t",
        "WITH a (x, y) AS (SELECT 1, 2) UPDATE t SET a = 1",
        "WITH a AS MATERIALIZED (SELECT 1) DELETE FROM t",
        "WITH a AS NOT MATERIALIZED (SELECT 1) DELETE FROM t",
        "WITH d AS (DELETE FROM u RETURNING *) INSERT INTO t SELECT * FROM d",
        "WITH update AS (SELECT 1) UPDATE t SET a = 1",
        'WITH "delete" AS (SELECT 1) DELETE FROM t',
        "WITH a AS (SELECT ')') DELETE FROM t",
        "INSERT INTO t SELECT pg_notify('c', 'p')",
        "INSERT INTO t SELECT pg_advisory_xact_lock(1)",
        "INSERT INTO t SELECT pg_try_advisory_xact_lock(1)",
    ] + [as_write(statement) for statement in GuardTest.ACCEPTED]

    # (statement, reason, static_review_only)
    REFUSED = [
        (as_write(statement), reason, static)
        for statement, reason, static in GuardTest.REFUSED
        if reason in ("empty", "unterminated", "multiple_statements")
    ] + [
        ("INSERT INTO t VALUES (1); DELETE FROM t", "multiple_statements", False),
        ("INSERT INTO t VALUES (1);;", "multiple_statements", False),
        ("INSERT INTO t VALUES (1) -- x\r; COMMIT", "multiple_statements", False),
        ("WITH a AS (SELECT 1) DELETE FROM t; SELECT 2", "multiple_statements", False),
        ("SELECT 1", "not_write", False),
        ("select 1;", "not_write", False),
        ("WITH x AS (SELECT 1) SELECT * FROM x", "not_write", False),
        ("TABLE t", "not_write", False),
        ("VALUES (1)", "not_write", False),
        ("(SELECT 1)", "not_write", False),
        ("(SELECT 1) UNION (SELECT 2)", "not_write", False),
        ("WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d", "not_write", True),
        ("SELECT * FROM t FOR UPDATE", "not_write", True),
        ("SELECT * INTO newt FROM t", "not_write", True),
        ("WITH a AS (SELECT 1) SELECT * INTO newt FROM a", "not_write", True),
        ("SELECT set_config('a', 'b', false)", "not_write", False),
    ] + [
        (statement, "not_write", True)
        for statement in (
            "SET default_transaction_read_only = off", "SET x = 1", "RESET ALL", "RESET x", "BEGIN",
            "START TRANSACTION", "COMMIT", "END", "ROLLBACK", "ABORT", "SET TRANSACTION READ WRITE",
            "VACUUM t", "LISTEN c", "NOTIFY c", "CREATE TABLE t (a int)", "DROP TABLE t", "ALTER TABLE t ADD c int",
            "EXPLAIN SELECT 1", "EXPLAIN ANALYZE INSERT INTO t VALUES (1)", "TRUNCATE t", "COPY t TO STDOUT",
            "DO $$ begin end $$", "CALL p()", "DISCARD ALL", "LOCK t", "GRANT ALL ON t TO u", "\\! rm x", "foo",
        )
    ] + [
        (statement, "not_write", True)
        for statement in (
            "WITH a AS (SELECT 1) SEARCH DEPTH FIRST BY x SET o INSERT INTO t VALUES (1)",
            "WITH a AS (SELECT 1) CYCLE x SET is_cycle USING path INSERT INTO t VALUES (1)",
            "WITH a (SELECT 1) INSERT INTO t VALUES (1)",
            "WITH a AS (SELECT 1 INSERT INTO t VALUES (1)",
            "WITH a AS SELECT 1 INSERT INTO t VALUES (1)",
            "WITH a AS NOT (SELECT 1) INSERT INTO t VALUES (1)",
            "WITH a AS (SELECT 1), INSERT INTO t VALUES (1)",
            "WITH a AS (SELECT 1) b AS (SELECT 2) INSERT INTO t VALUES (1)",
            "WITH RECURSIVE INSERT INTO t VALUES (1)",
            "WITH 1 AS (SELECT 1) INSERT INTO t VALUES (1)",
            "WITH a AS (SELECT 1) (INSERT INTO t VALUES (1))",
            "WITH a AS (SELECT 1) SELECT * FROM a UNION ALL INSERT INTO t VALUES (1)",
        )
    ] + [
        ("WITH a AS (SELECT 1)", "not_write", False),
        ("WITH", "not_write", False),
    ] + [
        (statement, "forbidden_function", False)
        for statement in (
            "INSERT INTO t SELECT set_config('a', 'b', false)",
            "INSERT INTO t SELECT pg_catalog.set_config('a', 'b', false)",
            'INSERT INTO t SELECT "set_config"(\'a\', \'b\', false)',
            'INSERT INTO t SELECT pg_catalog."set_config"(\'a\', \'b\', false)',
            "INSERT INTO t SELECT SET_CONFIG('a', 'b', false)",
            "UPDATE t SET a = set_config('default_transaction_read_only', 'off', false)",
            "WITH a AS (SELECT set_config('a', 'b', false)) DELETE FROM t",
        )
    ] + [
        ('INSERT INTO t SELECT U&"set\\005fconfig"(1)', "unicode_identifier", False),
        ("DELETE FROM t WHERE U&\"a\" = 1", "unicode_identifier", False),
    ]

    def test_each_accepted_form_reaches_psql(self):
        for statement in self.ACCEPTED:
            with self.subTest(statement=statement):
                self.reset_log()
                code, data = self.explain_write(statement)
                self.assertEqual((code, data["ok"]), (0, True), data)
                self.assertTrue(self.calls())

    def test_each_refusal_has_its_reason_and_never_reaches_psql(self):
        for statement, reason, static in self.REFUSED:
            with self.subTest(statement=statement):
                self.reset_log()
                code, data = self.explain_write(statement)
                self.assertEqual(code, 1)
                self.assertEqual(
                    (data["ok"], data["error"], data["reason"], data["static_review_only"]),
                    (False, "refused", reason, static),
                    data,
                )
                self.assertTrue(data["message"])
                self.assertEqual(self.calls(), [])

    def test_the_reasons_are_checked_in_order(self):
        order = [
            ("", "empty"), ("INSERT INTO t SELECT 'x", "unterminated"),
            ("SELECT set_config('a', 'b', false); SELECT 1", "multiple_statements"),
            ("SELECT set_config('a', 'b', false)", "not_write"),
            ("INSERT INTO t SELECT set_config('a', 'b', false), U&\"x\"", "forbidden_function"),
            ("INSERT INTO t SELECT U&\"x\"", "unicode_identifier"),
        ]
        for statement, reason in order:
            with self.subTest(reason=reason):
                self.assertEqual(self.explain_write(statement)[1]["reason"], reason)

    def test_the_write_messages_are_not_the_select_messages(self):
        _, multiple = self.explain_write("INSERT INTO t VALUES (1); DELETE FROM t")
        self.assertIn("Write mode accepts one statement only", multiple["message"])
        for statement in ("SELECT 1", "WITH x AS (SELECT 1) SELECT * FROM x"):
            with self.subTest(statement=statement):
                message = self.explain_write(statement)[1]["message"]
                self.assertIn("select mode", message)
                self.assertNotIn("reading only", message)
        for statement in ("TABLE t", "VALUES (1)", "SET x = 1", "WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d"):
            with self.subTest(statement=statement):
                message = self.explain_write(statement)[1]["message"]
                self.assertIn("INSERT, UPDATE, DELETE or MERGE", message)
                self.assertIn("reading only", message)
                self.assertNotIn("select mode", message)
        for statement in ("SELECT 1", "TABLE t", "INSERT INTO t SELECT set_config('a', 'b', false)", "DROP TABLE t"):
            with self.subTest(statement=statement):
                self.assertNotIn("Select mode", self.explain_write(statement)[1]["message"])

    def test_ddl_and_vacuum_are_refused_in_both_modes(self):
        for statement in ("VACUUM t", "CREATE TABLE t (a int)", "DROP TABLE t", "ALTER TABLE t ADD c int"):
            with self.subTest(statement=statement):
                self.assertEqual(self.explain(statement)[1]["reason"], "not_select")
                self.assertEqual(self.explain_write(statement)[1]["reason"], "not_write")
                self.assertEqual(self.calls(), [])

    def test_the_select_write_statement_message_names_write_mode(self):
        message = self.explain("DELETE FROM t")[1]["message"]
        self.assertIn("--mode write", message)
        self.assertNotIn("not available yet", message)

    def test_the_trailing_semicolon_and_everything_after_it_are_cut(self):
        self.explain_write("DELETE FROM t; -- x")
        for call in self.calls():
            for argument in call["argv"]:
                if argument.startswith("EXPLAIN"):
                    self.assertTrue(argument.endswith("DELETE FROM t"), argument)

    def test_a_statement_is_read_from_stdin_when_there_is_no_statement_option(self):
        done = self.run_pg("explain", "--repo", self.repo, "--service", "app-dev", "--mode", "write", stdin="DELETE FROM t42\n")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(any("DELETE FROM t42" in a for c in self.calls() for a in c["argv"]))

    def test_a_service_off_the_allowlist_gives_not_allowed_before_the_guard_runs(self):
        code, data = self.explain_write("SELECT 1", service="other")
        self.assertEqual((code, data["error"], data["reason"]), (1, "not_allowed", "service_not_listed"))
        self.assertEqual(self.calls(), [])

    def test_a_blank_that_only_unicode_treats_as_space_is_not_stripped_from_the_sent_text(self):
        # PostgreSQL reads U+00A0 as an identifier character, so the text must reach the server as written.
        statement = "DELETE FROM t WHERE a = 1  "
        self.explain_write(statement)
        sent = [a for c in self.calls() for a in c["argv"] if a.startswith("EXPLAIN")]
        self.assertTrue(sent)
        for text in sent:
            self.assertTrue(text.endswith(" "), repr(text))


def commands_of(call):
    argv = call["argv"]
    return [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]


def variable_of(call, name):
    prefix = name + "="
    return next((a[len(prefix):] for a in call["argv"] if a.startswith(prefix)), None)


class WriteRunTest(PgRunTestCase):
    """The write-mode steps, with a fake `psql` that answers by the content of its argv."""

    def kinds(self):
        """The kinds of the recorded calls, in order."""
        out = []
        for call in self.calls():
            argv = call["argv"]
            if any("SHOW server_version_num" in a for a in argv):
                out.append("probe")
            elif variable_of(call, "targets") is not None:
                out.append("catalog")
            else:
                text = next(a for a in argv if a.startswith("EXPLAIN"))
                out.append(
                    "discovery" if text.startswith("EXPLAIN (VERBOSE") else "plain" if text.startswith("EXPLAIN (FORMAT") else "analyze"
                )
        return out

    def call_of(self, kind):
        return self.calls()[self.kinds().index(kind)]

    def test_the_session_flags_and_commands_of_each_run(self):
        for version, timeouts in (("160000", "-c statement_timeout=30s -c lock_timeout=2s -c idle_in_transaction_session_timeout=10s"),
                                  ("170000", "-c statement_timeout=30s -c lock_timeout=2s -c idle_in_transaction_session_timeout=10s -c transaction_timeout=60s")):
            with self.subTest(version=version):
                self.reset_log()
                code, data = self.explain_write("UPDATE t SET a = 1", env={"FAKE_VERSION": version})
                self.assertEqual((code, data["ran"]), (0, "analyze"), data)
                self.assertEqual(self.kinds(), ["probe", "discovery", "catalog", "analyze"])
                probe = self.call_of("probe")
                self.assertIn("-c default_transaction_read_only=on", probe["argv"][-1])
                self.assertEqual(commands_of(probe), ["SHOW server_version_num"])
                for kind in ("discovery", "catalog", "analyze"):
                    call = self.call_of(kind)
                    conninfo = call["argv"][-1]
                    self.assertNotIn("default_transaction_read_only", conninfo, kind)
                    self.assertEqual(conninfo, f"service=app-dev options='-c standard_conforming_strings=on {timeouts}'")
                    self.assertIn("ON_ERROR_STOP=1", call["argv"], kind)
                for kind in ("discovery", "analyze"):
                    commands = commands_of(self.call_of(kind))
                    self.assertEqual((commands[0], commands[-1]), ("BEGIN READ WRITE", "ROLLBACK"))
                    self.assertEqual(len(commands), 3)
                self.assertEqual(commands_of(self.call_of("discovery"))[1], "EXPLAIN (VERBOSE, FORMAT JSON) UPDATE t SET a = 1")
                catalog = self.call_of("catalog")
                self.assertEqual(commands_of(catalog), [])
                self.assertTrue(catalog["stdin"].startswith("BEGIN READ ONLY;"))
                self.assertTrue(catalog["stdin"].rstrip().endswith("ROLLBACK;"))

    def test_the_analyze_text_by_version(self):
        for version, text in (("130000", "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) DELETE FROM t"),
                              ("170002", "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) DELETE FROM t"),
                              ("180000", "EXPLAIN (ANALYZE, FORMAT JSON) DELETE FROM t")):
            with self.subTest(version=version):
                self.reset_log()
                code, data = self.explain_write("DELETE FROM t", env={"FAKE_VERSION": version})
                self.assertEqual(code, 0, data)
                self.assertEqual(commands_of(self.call_of("analyze"))[1], text)

    def test_the_output_of_an_analyze_run(self):
        code, data = self.explain_write("UPDATE t SET a = 1")
        self.assertEqual(code, 0)
        self.assertEqual(
            sorted(data),
            sorted(["ok", "action", "service", "mode", "server_version_num", "ran", "reason", "timeouts", "downgrade", "warnings", "plan"]),
        )
        self.assertEqual((data["mode"], data["ran"], data["downgrade"], data["warnings"]), ("write", "analyze", [], []))
        self.assertEqual(data["reason"], "no trigger, rule or external call on the reached tables")
        self.assertIsInstance(data["plan"], list)

    def test_a_scan_name_gives_the_discovery_run_and_the_plain_run_and_no_catalog_run(self):
        names = [
            "dblink", "dblink_exec", "public.dblink", "dblink_connect", "pg_advisory_lock", "pg_advisory_unlock",
            "pg_try_advisory_lock", "pg_advisory_unlock_all", "lo_export", "setval", "query_to_xml",
            "query_to_xml_and_xmlschema", "query_to_xmlschema", "cursor_to_xml", "cursor_to_xmlschema", "ts_stat",
            "crosstab", "crosstab2", "crosstab3", "crosstab4", "connectby", '"dblink_exec"', "DBLINK_EXEC",
        ]
        for name in names:
            with self.subTest(name=name):
                self.reset_log()
                code, data = self.explain_write(f"INSERT INTO t SELECT {name}('x')")
                self.assertEqual((code, data["ran"]), (0, "explain"), data)
                self.assertEqual(self.kinds(), ["probe", "discovery", "plain"])
                bare = name.split(".")[-1].strip('"').lower()
                self.assertEqual(data["downgrade"], [{"kind": "function", "name": bare}])
                self.assertIn(bare, data["reason"])
                self.assertEqual(data["warnings"], [])
                self.assertEqual(commands_of(self.call_of("plain"))[1], f"EXPLAIN (FORMAT JSON) INSERT INTO t SELECT {name}('x')")

    def test_a_scan_name_in_a_string_or_a_comment_is_not_found_and_a_transaction_lock_is_not_a_scan_name(self):
        for statement in (
            "INSERT INTO t SELECT 'dblink_exec(x)'",
            "INSERT INTO t SELECT 1 -- lo_export\n",
            "INSERT INTO t SELECT /* setval */ 1",
            "INSERT INTO t SELECT $$pg_advisory_lock$$",
            "INSERT INTO t SELECT pg_advisory_xact_lock(1)",
            "INSERT INTO t SELECT pg_try_advisory_xact_lock_shared(1)",
            "INSERT INTO t SELECT pg_notify('c', 'p')",
        ):
            with self.subTest(statement=statement):
                self.reset_log()
                code, data = self.explain_write(statement)
                self.assertEqual((code, data["ran"]), (0, "analyze"), data)
                self.assertEqual(self.kinds(), ["probe", "discovery", "catalog", "analyze"])

    def test_the_downgrade_entries_of_functions_are_sorted_without_duplicates(self):
        code, data = self.explain_write("INSERT INTO t SELECT setval('s', 1), dblink('a', 'b'), setval('s', 2), lo_export(1, 'x')")
        self.assertEqual(
            data["downgrade"],
            [{"kind": "function", "name": n} for n in ("dblink", "lo_export", "setval")],
        )
        self.assertEqual(data["reason"], "the statement calls dblink, lo_export, setval")

    def test_the_targets_value_holds_the_verb_and_the_name_of_each_written_table(self):
        cases = [
            ("INSERT INTO t VALUES (1)", [["insert", "t"]]),
            ("INSERT INTO ONLY s.t VALUES (1)", [["insert", "s.t"]]),
            ("UPDATE t SET a = 1", [["update", "t"]]),
            ("UPDATE ONLY t SET a = 1", [["update", "t"]]),
            ("DELETE FROM s.t WHERE a = 1", [["delete", "s.t"]]),
            ("MERGE INTO t USING s ON true WHEN MATCHED THEN DELETE", [["merge", "t"]]),
            ('INSERT INTO "My ""T""".b VALUES (1)', [["insert", '"My ""T"""' + ".b"]]),
            ("INSERT INTO a.b.c VALUES (1)", [["insert", "a.b.c"]]),
            ('DELETE FROM "x y"', [["delete", '"x y"']]),
            ("WITH d AS (DELETE FROM u RETURNING *) INSERT INTO t SELECT * FROM d", [["delete", "u"], ["insert", "t"]]),
            ("INSERT INTO t VALUES (1) ON CONFLICT (a) DO UPDATE SET a = 2", [["insert", "t"], ["update", "SET"]]),
            ("INSERT INTO t SELECT 1 FROM u FOR UPDATE", [["insert", "t"]]),
            ("UPDATE t SET a = (SELECT b FROM u FOR UPDATE OF u)", [["update", "t"], ["update", "OF"]]),
            ("DELETE FROM t USING (UPDATE u SET a = 1 RETURNING *) x", [["delete", "t"], ["update", "u"]]),
        ]
        for statement, expected in cases:
            with self.subTest(statement=statement):
                self.reset_log()
                code, data = self.explain_write(statement)
                self.assertEqual(code, 0, data)
                self.assertEqual(json.loads(variable_of(self.call_of("catalog"), "targets")), expected)

    def test_the_plan_targets_value_holds_each_modify_table_relation_at_any_depth(self):
        plan = [{"Plan": {"Node Type": "ModifyTable", "Operation": "Insert", "Schema": "s", "Relation Name": "a", "Plans": [
            {"Node Type": "Result", "Plans": [{"Node Type": "ModifyTable", "Operation": "Delete", "Schema": "s", "Relation Name": "b"}]},
            {"Node Type": "ModifyTable", "Operation": "Update", "Target Tables": [
                {"Schema": "s", "Relation Name": "c"}, {"Schema": "s", "Relation Name": "d"}]},
        ]}}]
        code, data = self.explain_write("INSERT INTO s.a VALUES (1)", env={"FAKE_STDOUT_DISCOVERY": json.dumps(plan)})
        self.assertEqual(code, 0, data)
        self.assertEqual(
            sorted(json.loads(variable_of(self.call_of("catalog"), "plan_targets"))),
            sorted([["Insert", "s", "a"], ["Delete", "s", "b"], ["Update", "s", "c"], ["Update", "s", "d"]]),
        )

    def test_the_catalog_script_is_constant_and_holds_none_of_the_names(self):
        self.explain_write("UPDATE secret_t_one SET a = 1")
        script_one = self.call_of("catalog")["stdin"]
        self.reset_log()
        self.explain_write("DELETE FROM secret_t_two")
        script_two = self.call_of("catalog")["stdin"]
        self.assertEqual(script_one, script_two)
        self.assertNotIn("secret_t", script_one)
        self.assertIn(":'targets'", script_one)
        self.assertIn(":'plan_targets'", script_one)

    def test_a_trigger_or_a_rule_hit_gives_the_plain_run_and_its_reason(self):
        hits = {"hits": [{"kind": "trigger", "name": "public.t"}, {"kind": "rule", "name": "s.v"}, {"kind": "trigger", "name": "public.t"}], "sequence": True}
        code, data = self.explain_write("INSERT INTO t VALUES (1)", env={"FAKE_STDOUT_CATALOG": json.dumps(hits)})
        self.assertEqual((code, data["ran"]), (0, "explain"), data)
        self.assertEqual(self.kinds(), ["probe", "discovery", "catalog", "plain"])
        self.assertEqual(data["reason"], "a reached table has a user trigger or a rule: public.t, s.v")
        self.assertEqual(data["downgrade"], [{"kind": k, "name": n} for k, n in (("trigger", "public.t"), ("rule", "s.v"), ("trigger", "public.t"))])
        self.assertEqual(data["warnings"], [])
        self.assertEqual(commands_of(self.call_of("plain"))[1], "EXPLAIN (FORMAT JSON) INSERT INTO t VALUES (1)")

    def test_the_sequence_warning(self):
        for stdout, statement, expected in (
            ({"hits": [], "sequence": True}, "INSERT INTO t VALUES (1)", ["sequence"]),
            ({"hits": [], "sequence": False}, "INSERT INTO t VALUES (1)", []),
            ({"hits": [], "sequence": False}, "INSERT INTO t VALUES (nextval('s'))", ["sequence"]),
            ({"hits": [], "sequence": False}, 'INSERT INTO t VALUES (pg_catalog."nextval"(\'s\'))', ["sequence"]),
            ({"hits": [], "sequence": False}, "INSERT INTO t VALUES ('nextval')", []),
            ({"hits": [], "sequence": False}, "INSERT INTO t SELECT nextval FROM s", []),
            ({"hits": [], "sequence": False}, 'INSERT INTO t SELECT "nextval" FROM s', []),
            ({"hits": [], "sequence": False}, "INSERT INTO t VALUES (nextval ('s'))", ["sequence"]),
            ({"hits": [], "sequence": False}, "INSERT INTO t VALUES (pg_catalog.nextval/* c */('s'))", ["sequence"]),
        ):
            with self.subTest(statement=statement, sequence=stdout["sequence"]):
                code, data = self.explain_write(statement, env={"FAKE_STDOUT_CATALOG": json.dumps(stdout)})
                self.assertEqual((code, data["ran"], data["warnings"]), (0, "analyze", expected), data)

    def test_an_explicit_nextval_never_downgrades(self):
        code, data = self.explain_write("INSERT INTO t VALUES (nextval('s'))")
        self.assertEqual((data["ran"], data["downgrade"]), ("analyze", []))

    def test_a_discovery_output_that_is_not_usable_is_bad_output_and_no_later_psql_call_follows(self):
        node = {"Node Type": "ModifyTable", "Operation": "Update", "Schema": "s", "Relation Name": "t"}
        outputs = [
            "", "not json", "{}", json.dumps({"Plan": node}), json.dumps([]), json.dumps([1]), json.dumps([{"Plan": 1}]),
            json.dumps([{"NoPlan": node}]),
            json.dumps([{"Plan": {"Node Type": "Result"}}]),
            json.dumps([{"Plan": {**node, "Schema": None}}]),
            json.dumps([{"Plan": {**node, "Relation Name": 5}}]),
            json.dumps([{"Plan": {k: v for k, v in node.items() if k != "Schema"}}]),
            json.dumps([{"Plan": {**node, "Operation": None}}]),
            json.dumps([{"Plan": {k: v for k, v in node.items() if k != "Operation"}}]),
            json.dumps([{"Plan": {"Node Type": "ModifyTable", "Operation": "Update", "Target Tables": []}}]),
            json.dumps([{"Plan": {"Node Type": "ModifyTable", "Operation": "Update", "Target Tables": [{"Schema": "s"}]}}]),
            json.dumps([{"Plan": {"Node Type": "ModifyTable", "Operation": "Update", "Target Tables": "t"}}]),
            json.dumps([{"Plan": {"Node Type": "Result", "Plans": [{**node, "Relation Name": None}]}}]),
        ]
        for out in outputs:
            with self.subTest(out=out[:80]):
                self.reset_log()
                code, data = self.explain_write("UPDATE t SET a = 1", env={"FAKE_STDOUT_DISCOVERY": out})
                self.assertEqual((code, data["error"]), (1, "bad_output"), data)
                self.assertEqual(self.kinds(), ["probe", "discovery"])

    def test_a_malformed_catalog_output_is_bad_output_and_the_analyze_run_never_starts(self):
        outputs = [
            "", "not json", "[]", "{}", json.dumps({"hits": []}), json.dumps({"sequence": False}),
            json.dumps({"hits": {}, "sequence": False}), json.dumps({"hits": [], "sequence": "no"}),
            json.dumps({"hits": [], "sequence": 0}), json.dumps({"hits": ["x"], "sequence": False}),
            json.dumps({"hits": [{"kind": "view", "name": "t"}], "sequence": False}),
            json.dumps({"hits": [{"kind": "trigger", "name": 5}], "sequence": False}),
            json.dumps({"hits": [{"kind": "trigger"}], "sequence": False}),
            json.dumps({"hits": [], "sequence": False}) + "\nextra",
        ]
        for out in outputs:
            with self.subTest(out=out[:60]):
                self.reset_log()
                code, data = self.explain_write("UPDATE t SET a = 1", env={"FAKE_STDOUT_CATALOG": out})
                self.assertEqual((code, data["error"]), (1, "bad_output"), data)
                self.assertEqual(self.kinds(), ["probe", "discovery", "catalog"])

    def test_a_failing_run_gives_statement_failed_and_no_later_psql_call(self):
        stderr = f'ERROR:  relation "t" does not exist\nLINE 1: EXPLAIN (VERBOSE, FORMAT JSON) UPDATE t SET a = 1\n'
        for failing, expected in (
            ("discovery", ["probe", "discovery"]),
            ("catalog", ["probe", "discovery", "catalog"]),
            ("analyze", ["probe", "discovery", "catalog", "analyze"]),
        ):
            with self.subTest(failing=failing):
                self.reset_log()
                code, data = self.explain_write(
                    "UPDATE t SET a = 1", env={"FAKE_FAIL_KIND": failing, "FAKE_STDERR": stderr, "FAKE_EXIT": "1"}
                )
                self.assertEqual((code, data["error"]), (1, "statement_failed"), data)
                self.assertEqual(self.kinds(), expected)
                for call in self.calls():
                    self.assertIn("ON_ERROR_STOP=1", call["argv"])

    def test_a_failing_plain_run_gives_statement_failed(self):
        code, data = self.explain_write(
            "INSERT INTO t SELECT dblink('a', 'b')",
            env={"FAKE_FAIL_KIND": "plain", "FAKE_STDERR": "ERROR:  boom\n", "FAKE_EXIT": "1"},
        )
        self.assertEqual((code, data["error"]), (1, "statement_failed"), data)

    def test_a_to_regclass_rejection_of_a_name_is_statement_failed_and_no_analyze_run_starts(self):
        stderr = "ERROR:  cross-database references are not implemented: a.b.c.d\n"
        code, data = self.explain_write(
            "UPDATE a.b.c SET x = 1", env={"FAKE_FAIL_KIND": "catalog", "FAKE_STDERR": stderr, "FAKE_EXIT": "1"}
        )
        self.assertEqual((code, data["error"]), (1, "statement_failed"), data)
        self.assertNotIn("analyze", self.kinds())

    def test_each_connection_failure_kind_leaks_no_connection_value_in_each_write_run(self):
        for failing in ("discovery", "catalog", "analyze"):
            for name, stderr in (("auth", AUTH_STDERR), ("unreachable", UNREACHABLE_STDERR)):
                with self.subTest(failing=failing, kind=name):
                    code, data = self.explain_write(
                        "UPDATE t SET a = 1", env={"FAKE_FAIL_KIND": failing, "FAKE_STDERR": stderr, "FAKE_EXIT": "2"}
                    )
                    self.assertEqual((code, data["error"]), (1, "connection_failed"))
                    text = json.dumps(data)
                    for canary in CANARIES:
                        self.assertNotIn(canary, text)


INT_TYPES = {"23": {"name": "integer", "float": False, "equality": True, "leaf": 23}}


def types_json(a, b, **entries):
    """A canned type session: `a` and `b` are lists of oids; `entries` adds or replaces entries by oid."""
    types = {**INT_TYPES, **{str(oid): entry for oid, entry in entries.items()}}
    return json.dumps({"a": a, "b": b, "types": types})


def entry(name, equality=True, float_=False, leaf=None, oid=None):
    return {"name": name, "float": float_, "equality": equality, "leaf": leaf if leaf is not None else oid}


class DiffTestCase(PgRunTestCase):
    def diff(self, a="SELECT 1 AS id", b="SELECT 1 AS id", service="app-dev", env=None):
        done = self.run_pg("diff", "--repo", self.repo, "--service", service, f"--a={a}", f"--b={b}", env=env, stdin="")
        self.assertIn(done.returncode, (0, 1), done.stderr)
        return done.returncode, json.loads(done.stdout)

    def sessions(self):
        """The three calls of a diff run, by kind: describe, types and proof."""
        found = {}
        for call in self.calls():
            text = "\n".join(commands_of(call))
            kind = "describe" if "LIMIT 0" in text else "types" if "pg_typeof" in text else "proof"
            found[kind] = call
        return found

    def proof_text(self):
        return commands_of(self.sessions()["proof"])[1]


class DiffGuardTest(DiffTestCase):
    def test_a_statement_that_fails_the_guard_is_refused_before_any_psql_call_and_names_its_side(self):
        for a, b, side, reason in (
            ("SELECT 1", "DELETE FROM t", "b", "write_statement"),
            ("UPDATE t SET a = 1", "SELECT 1", "a", "write_statement"),
            ("SELECT 1", "SELECT ts_stat('x')", "b", "forbidden_function"),
            ("SELECT crosstab('x')", "SELECT 1", "a", "forbidden_function"),
            ("SELECT query_to_xml('x', true, true, '')", "SELECT 1", "a", "forbidden_function"),
            ("SELECT cursor_to_xml('x', 1, true, true, '')", "SELECT 1", "a", "forbidden_function"),
            ("SELECT connectby('x')", "SELECT 1", "a", "forbidden_function"),
            ("SELECT 1", "SELECT (1", "b", "unbalanced_parentheses"),
            ("SELECT 1)", "SELECT 1", "a", "unbalanced_parentheses"),
            ("SELECT 1", "SELECT 1; SELECT 2", "b", "multiple_statements"),
            ("SELECT 1", "", "b", "empty"),
            ("--x", "SELECT 1", "a", "empty"),
        ):
            with self.subTest(a=a, b=b):
                self.reset_log()
                code, data = self.diff(a, b)
                self.assertEqual(code, 1)
                self.assertEqual((data["ok"], data["error"], data["statement"], data["reason"]), (False, "refused", side, reason))
                self.assertEqual(sorted(data), ["error", "message", "ok", "reason", "statement", "static_review_only"])
                self.assertEqual(self.calls(), [])
        code, data = self.diff("SELECT 1", "VACUUM t")
        self.assertTrue(data["static_review_only"])

    def test_the_allowlist_is_checked_before_the_guard_and_no_connection_follows_not_allowed(self):
        code, data = self.diff("DELETE FROM t", "DELETE FROM t", service="other")
        self.assertEqual((code, data["error"], data["reason"]), (1, "not_allowed", "service_not_listed"))
        self.assertEqual(self.calls(), [])

    def test_the_equals_form_takes_a_statement_that_starts_with_a_comment_or_a_dash_value(self):
        code, data = self.diff("-- why\nSELECT 1 AS id", "SELECT 1 AS id")
        self.assertEqual((code, data["ok"]), (0, True), data)
        self.reset_log()
        code, data = self.diff("--x", "SELECT 1")
        self.assertEqual((code, data["error"], data["reason"]), (1, "refused", "empty"))


class DiffSessionTest(DiffTestCase):
    def test_every_call_has_x_and_w_and_the_user_text_only_in_c_arguments_and_nothing_on_stdin(self):
        marker_a, marker_b = "SELECT 7 AS id /* marker_a */", "SELECT 7 AS id /* marker_b */"
        code, data = self.diff(marker_a, marker_b, env={"FAKE_READ_STDIN": "1"})
        self.assertEqual(code, 0, data)
        calls = self.calls()
        self.assertEqual(len(calls), 3)
        for call in calls:
            self.assertIn("-X", call["argv"])
            self.assertIn("-w", call["argv"])
            self.assertEqual(call["stdin"], "")
            self.assertNotIn("-f", call["argv"])
            self.assertNotIn("marker_a", call["argv"][-1])
        text = json.dumps([c["argv"] for c in calls])
        self.assertIn("marker_a", text)
        self.assertIn("marker_b", text)

    def test_the_describe_session(self):
        self.diff("SELECT 1 AS id", "SELECT 2 AS id")
        call = self.sessions()["describe"]
        self.assertEqual(call["argv"][:5], ["-X", "-w", "--csv", "-q", "-v"])
        self.assertIn("ON_ERROR_STOP=1", call["argv"])
        self.assertEqual(
            commands_of(call),
            ["SHOW server_version_num", "BEGIN READ ONLY", "SELECT * FROM (SELECT 1 AS id\n) AS t LIMIT 0",
             "SELECT * FROM (SELECT 2 AS id\n) AS t LIMIT 0", "ROLLBACK"],
        )
        base = (
            "-c default_transaction_read_only=on -c standard_conforming_strings=on "
            "-c statement_timeout=30s -c lock_timeout=2s -c idle_in_transaction_session_timeout=10s"
        )
        self.assertEqual(call["argv"][-1], f"service=app-dev options='{base}'")

    def test_the_type_and_proof_sessions_are_read_only_and_use_the_flags_of_explain(self):
        self.diff()
        for kind in ("types", "proof"):
            call = self.sessions()[kind]
            self.assertEqual(call["argv"][:7], ["-X", "-w", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"])
            commands = commands_of(call)
            self.assertEqual((commands[0], commands[2], len(commands)), ("BEGIN READ ONLY", "ROLLBACK", 3))
            self.assertIn("-c default_transaction_read_only=on", call["argv"][-1])

    def test_the_version_gates_the_transaction_timeout_in_the_type_and_proof_sessions_only(self):
        for version, expected in (("130000", False), ("160013", False), ("170000", True), ("180000", True)):
            with self.subTest(version=version):
                self.reset_log()
                code, data = self.diff(env={"FAKE_VERSION": version})
                self.assertEqual(code, 0, data)
                sessions = self.sessions()
                self.assertNotIn("transaction_timeout", sessions["describe"]["argv"][-1])
                for kind in ("types", "proof"):
                    self.assertEqual("transaction_timeout=60s" in sessions[kind]["argv"][-1], expected)
                self.assertEqual(data["server_version_num"], int(version))
                self.assertEqual("transaction_timeout" in data["timeouts"], expected)

    def test_a_per_service_timeout_override_applies_to_every_session(self):
        self.write_allowlist(
            'services = ["app-dev", "app-test"]\n["github.com/o/r".timeouts.app-dev]\nstatement_timeout = "45s"\n'
        )
        code, data = self.diff()
        self.assertEqual(data["timeouts"]["statement_timeout"], "45s")
        for call in self.calls():
            self.assertIn("-c statement_timeout=45s", call["argv"][-1])

    def test_a_final_line_comment_cannot_swallow_the_closing_parenthesis(self):
        self.diff("SELECT 1 AS id -- last", "SELECT 1 AS id -- also last")
        sessions = self.sessions()
        describe = commands_of(sessions["describe"])
        self.assertIn("-- last\n) AS t LIMIT 0", describe[2])
        self.assertIn("-- also last\n) AS t LIMIT 0", describe[3])
        self.assertIn("-- last\n) AS x(c1) ON false", commands_of(sessions["types"])[1])
        proof = self.proof_text()
        self.assertIn("-- last\n) AS t(c1)", proof)
        self.assertIn("-- also last\n) AS t(c1)", proof)

    def test_the_proof_has_materialized_pgrun_ctes_and_an_alias_on_every_subquery_in_from(self):
        self.diff("SELECT id FROM t ORDER BY id", "SELECT id FROM t ORDER BY id")
        proof = self.proof_text()
        for name in ("ra", "rb", "a", "b", "oa", "ob", "na", "nb", "xa", "xb"):
            self.assertIn(f"pgrun_{name} AS MATERIALIZED (", proof, name)
        self.assertIn("EXCEPT ALL", proof)
        self.assertIn(") AS k)", proof)
        self.assertIn(") AS s)", proof)
        self.assertEqual(proof.count("WITH "), 1)

    def test_a_statement_with_a_trailing_semicolon_is_cut(self):
        self.diff("SELECT 1 AS id;", "SELECT 1 AS id ; -- x")
        self.assertIn("SELECT * FROM (SELECT 1 AS id\n) AS t LIMIT 0", commands_of(self.sessions()["describe"])[2])
        self.assertIn("SELECT * FROM (SELECT 1 AS id\n) AS t LIMIT 0", commands_of(self.sessions()["describe"])[3])


class DiffShapeTest(DiffTestCase):
    def test_a_column_count_or_name_mismatch_is_a_shape_result_and_only_the_describe_session_runs(self):
        for headers in ("id\nid,name\n", "id,name\nid\n", "id\nname\n", "id,name\nname,id\n", "id,id\nid,x\n"):
            with self.subTest(headers=headers):
                self.reset_log()
                code, data = self.diff(env={"FAKE_HEADERS": headers})
                self.assertEqual(code, 0, data)
                self.assertEqual(len(self.calls()), 1)
                self.assertEqual(
                    sorted(data),
                    ["action", "column_names", "equal", "ok", "reason", "server_version_num", "service", "timeouts"],
                )
                self.assertEqual((data["equal"], data["reason"]), (False, "shape"))
                a, b = headers.strip("\n").split("\n")
                self.assertEqual(data["column_names"], {"a": a.split(","), "b": b.split(",")})

    def test_a_statement_with_no_output_column_is_a_shape_result(self):
        for headers in ("\nid\n", "\n\n"):
            with self.subTest(headers=headers):
                self.reset_log()
                code, data = self.diff(env={"FAKE_HEADERS": headers})
                self.assertEqual((code, data["reason"], data["equal"]), (0, "shape", False), data)
                self.assertEqual(len(self.calls()), 1)

    def test_equal_duplicate_column_names_are_allowed(self):
        types = types_json([23, 23], [23, 23])
        code, data = self.diff(env={"FAKE_HEADERS": "id,id\nid,id\n", "FAKE_STDOUT_TYPES": types})
        self.assertEqual((code, data["equal"]), (0, True), data)

    def test_a_describe_output_with_other_than_four_records_is_bad_output(self):
        for out in ("server_version_num\n180000\nid\n", "server_version_num\n180000\nid\nid\nid\n", "x\ny\n", "",
                    "server_version_num\nabc\nid\nid\n"):
            with self.subTest(out=out):
                code, data = self.diff(env={"FAKE_STDOUT_DESCRIBE": out})
                self.assertEqual((code, data["error"]), (1, "bad_output"), data)

    def test_a_quoted_header_with_a_comma_is_one_name(self):
        code, data = self.diff(env={"FAKE_HEADERS": '"a,b"\n"a,b"\n'})
        self.assertEqual((code, data["columns"]["a"][0]["name"]), (0, "a,b"), data)


class DiffResultTest(DiffTestCase):
    def test_an_equal_result_has_exactly_the_full_result_keys(self):
        code, data = self.diff()
        self.assertEqual(code, 0)
        self.assertEqual(
            sorted(data),
            sorted(["ok", "action", "service", "server_version_num", "timeouts", "equal", "columns", "rows", "only_a",
                    "only_b", "type_mismatch", "casts", "floats", "order"]),
        )
        self.assertEqual((data["ok"], data["action"], data["service"], data["equal"]), (True, "diff", "app-dev", True))
        self.assertEqual(data["columns"], {"a": [{"name": "id", "type": "integer"}], "b": [{"name": "id", "type": "integer"}]})
        self.assertEqual(data["rows"], {"a": 0, "b": 0})
        self.assertEqual((data["only_a"], data["only_b"]), ({"count": 0, "rows": []}, {"count": 0, "rows": []}))
        self.assertEqual((data["type_mismatch"], data["casts"], data["floats"], data["order"]), ([], [], [], "not_applicable"))

    def test_a_row_only_on_one_side_gives_equal_false_with_its_count_and_samples(self):
        proof = json.dumps({"ra": 3, "rb": 2, "oa_count": 1, "ob_count": 0, "oa": [{"c1": 5}], "ob": []})
        code, data = self.diff(env={"FAKE_STDOUT_PROOF": proof})
        self.assertEqual((code, data["equal"]), (0, False))
        self.assertEqual(data["only_a"], {"count": 1, "rows": [[5]]})
        self.assertEqual(data["rows"], {"a": 3, "b": 2})

    def test_the_count_is_the_full_count_and_the_samples_are_capped_at_twenty(self):
        rows = [{"c1": i} for i in range(20)]
        proof = json.dumps({"ra": 90, "rb": 0, "oa_count": 90, "ob_count": 0, "oa": rows, "ob": []})
        code, data = self.diff(env={"FAKE_STDOUT_PROOF": proof})
        self.assertEqual((data["only_a"]["count"], len(data["only_a"]["rows"])), (90, 20))
        too_many = json.dumps({"ra": 90, "rb": 0, "oa_count": 90, "ob_count": 0, "oa": rows + [{"c1": 20}], "ob": []})
        code, data = self.diff(env={"FAKE_STDOUT_PROOF": too_many})
        self.assertEqual((code, data["error"]), (1, "bad_output"))

    def test_a_type_mismatch_casts_both_sides_to_text_and_is_not_in_casts(self):
        types = types_json([23], [1700], **{"1700": entry("numeric", oid=1700)})
        code, data = self.diff(env={"FAKE_STDOUT_TYPES": types})
        self.assertEqual((code, data["equal"]), (0, False))
        self.assertEqual(data["type_mismatch"], [{"position": 1, "name": "id"}])
        self.assertEqual(data["casts"], [])
        self.assertEqual(data["columns"]["b"], [{"name": "id", "type": "numeric"}])
        self.assertEqual(self.proof_text().count("c1::text AS c1"), 2)

    def test_a_type_mismatch_lists_each_position_so_duplicate_names_are_told_apart(self):
        types = types_json([23, 23, 23], [23, 1700, 1700], **{"1700": entry("numeric", oid=1700)})
        code, data = self.diff(env={"FAKE_HEADERS": "x,x,y\nx,x,y\n", "FAKE_STDOUT_TYPES": types})
        self.assertEqual(data["type_mismatch"], [{"position": 2, "name": "x"}, {"position": 3, "name": "y"}])

    def test_a_type_with_no_equality_is_cast_to_text_on_both_sides_and_named_in_casts(self):
        types = types_json([114], [114], **{"114": entry("json", equality=False, oid=114)})
        code, data = self.diff(env={"FAKE_STDOUT_TYPES": types})
        self.assertEqual((code, data["equal"], data["casts"], data["type_mismatch"]), (0, True, ["id"], []))
        self.assertEqual(self.proof_text().count("c1::text AS c1"), 2)

    def test_a_float_column_is_named_in_floats_and_is_compared_exactly(self):
        types = types_json([701], [701], **{"701": entry("double precision", float_=True, oid=701)})
        code, data = self.diff(env={"FAKE_STDOUT_TYPES": types})
        self.assertEqual((code, data["floats"], data["casts"]), (0, ["id"], []))
        self.assertNotIn("::text", self.proof_text())

    def test_a_float_on_either_side_is_named(self):
        types = types_json([23], [701], **{"701": entry("double precision", float_=True, oid=701)})
        code, data = self.diff(env={"FAKE_STDOUT_TYPES": types})
        self.assertEqual((data["floats"], data["equal"]), (["id"], False))

    def test_a_leaf_that_is_a_float_marks_an_array_of_floats(self):
        types = types_json([1022], [1022], **{"1022": entry("double precision[]", float_=True, leaf=701, oid=1022),
                                              "701": entry("double precision", float_=True, oid=701)})
        code, data = self.diff(env={"FAKE_STDOUT_TYPES": types})
        self.assertEqual((code, data["floats"]), (0, ["id"]))

    def test_the_rows_of_a_sample_are_arrays_in_column_order(self):
        types = types_json([23, 23], [23, 23])
        proof = json.dumps({"ra": 1, "rb": 0, "oa_count": 1, "ob_count": 0, "oa": [{"c2": 2, "c1": 1}], "ob": []})
        code, data = self.diff(env={"FAKE_HEADERS": "x,y\nx,y\n", "FAKE_STDOUT_TYPES": types, "FAKE_STDOUT_PROOF": proof})
        self.assertEqual(data["only_a"]["rows"], [[1, 2]])


class DiffOrderTest(DiffTestCase):
    ORDERED = "SELECT id FROM t ORDER BY id"

    def proof(self, **extra):
        data = {"ra": 2, "rb": 2, "oa_count": 0, "ob_count": 0, "oa": [], "ob": [], "ties": 0,
                "xa_count": 0, "xb_count": 0, "xa": [], "xb": []}
        data.update(extra)
        return json.dumps(data)

    def test_no_order_by_in_a_is_not_applicable_and_builds_no_numbered_cte(self):
        code, data = self.diff("SELECT id FROM t", "SELECT id FROM t ORDER BY id")
        self.assertEqual((data["order"], "order_mismatch" in data, "reason" in data), ("not_applicable", False, False))
        self.assertNotIn("pgrun_na", self.proof_text())

    def test_an_order_by_only_in_a_subquery_is_not_applicable(self):
        code, data = self.diff("SELECT id FROM (SELECT id FROM t ORDER BY id) AS s", "SELECT id FROM t")
        self.assertEqual(data["order"], "not_applicable")

    def test_resolved_keys_with_no_repeated_key_are_checked(self):
        code, data = self.diff(self.ORDERED, self.ORDERED, env={"FAKE_STDOUT_PROOF": self.proof()})
        self.assertEqual((code, data["order"], data["equal"]), (0, "checked", True), data)
        self.assertEqual(data["order_mismatch"], {"count_a": 0, "count_b": 0, "a": [], "b": []})
        self.assertNotIn("reason", data)
        proof = self.proof_text()
        self.assertIn("row_number() OVER (ORDER BY c1) AS rn", proof)
        self.assertIn("GROUP BY c1 HAVING count(*) > 1", proof)

    def test_the_keys_are_built_on_the_output_columns_with_their_direction_and_nulls(self):
        a = 'SELECT x, "Y z" FROM t ORDER BY 2 DESC NULLS LAST, X ASC NULLS FIRST'
        code, data = self.diff(a, a, env={
            "FAKE_HEADERS": 'x,Y z\nx,Y z\n', "FAKE_STDOUT_TYPES": types_json([23, 23], [23, 23]),
            "FAKE_STDOUT_PROOF": self.proof(),
        })
        self.assertEqual(data["order"], "checked", data)
        self.assertIn("ORDER BY c2 DESC NULLS LAST, c1 NULLS FIRST) AS rn", self.proof_text())

    def test_a_nonzero_order_mismatch_count_makes_equal_false_and_zero_counts_make_it_true(self):
        for extra, expected in (
            ({"xa_count": 1, "xa": [{"rn": 1, "c1": 1}]}, False), ({"xb_count": 2, "xb": [{"rn": 2, "c1": 1}]}, False), ({}, True),
        ):
            with self.subTest(extra=extra):
                code, data = self.diff(self.ORDERED, self.ORDERED, env={"FAKE_STDOUT_PROOF": self.proof(**extra)})
                self.assertEqual((code, data["order"], data["equal"]), (0, "checked", expected), data)
        self.assertEqual(data["only_a"]["count"], 0)

    def test_the_order_mismatch_samples_are_arrays_with_the_rank_first(self):
        proof = self.proof(xa_count=1, xa=[{"rn": 3, "c1": 9}])
        code, data = self.diff(self.ORDERED, self.ORDERED, env={"FAKE_STDOUT_PROOF": proof})
        self.assertEqual(data["order_mismatch"], {"count_a": 1, "count_b": 0, "a": [[3, 9]], "b": []})

    def test_a_repeated_key_makes_the_order_partial_with_reason_ties_and_the_numbered_diff_is_not_used(self):
        proof = self.proof(ties=2, xa_count=5, xa=[{"rn": 1, "c1": 1}])
        code, data = self.diff(self.ORDERED, self.ORDERED, env={"FAKE_STDOUT_PROOF": proof})
        self.assertEqual((data["order"], data["reason"], data["equal"]), ("partial", "ties", True), data)
        self.assertNotIn("order_mismatch", data)

    def test_keys_that_cannot_be_extracted_or_resolved_make_the_order_partial_with_reason_sort_keys(self):
        for a, headers in (
            ("SELECT id FROM t ORDER BY id + 1", "id\nid\n"),
            ("SELECT id FROM t ORDER BY t.id", "id\nid\n"),
            ("SELECT id FROM t ORDER BY 5", "id\nid\n"),
            ("SELECT id FROM t ORDER BY 0", "id\nid\n"),
            ("SELECT id AS x FROM t ORDER BY id", "x\nx\n"),
            ("SELECT id, id FROM t ORDER BY id", "id,id\nid,id\n"),
            ("SELECT id FROM t ORDER BY ID", "Id\nId\n"),
        ):
            with self.subTest(a=a):
                self.reset_log()
                env = {"FAKE_HEADERS": headers}
                if "," in headers:
                    env["FAKE_STDOUT_TYPES"] = types_json([23, 23], [23, 23])
                code, data = self.diff(a, a, env=env)
                self.assertEqual((code, data["order"], data["reason"], data["equal"]), (0, "partial", "sort_keys", True), data)
                self.assertNotIn("pgrun_na", self.proof_text())
                self.assertNotIn("order_mismatch", data)

    def test_a_sort_key_column_with_a_type_mismatch_is_partial_and_builds_no_numbered_cte(self):
        types = types_json([23], [1700], **{"1700": entry("numeric", oid=1700)})
        code, data = self.diff(self.ORDERED, self.ORDERED, env={"FAKE_STDOUT_TYPES": types})
        self.assertEqual((data["order"], data["reason"], data["equal"]), ("partial", "sort_keys", False))
        self.assertNotIn("pgrun_na", self.proof_text())

    def test_a_mismatch_in_another_column_does_not_stop_the_order_proof(self):
        types = types_json([23, 23], [23, 1700], **{"1700": entry("numeric", oid=1700)})
        env = {"FAKE_HEADERS": "id,v\nid,v\n", "FAKE_STDOUT_TYPES": types, "FAKE_STDOUT_PROOF": self.proof()}
        code, data = self.diff("SELECT id, v FROM t ORDER BY id", "SELECT id, v FROM t ORDER BY id", env=env)
        self.assertEqual((data["order"], data["equal"]), ("checked", False))
        self.assertIn("pgrun_na", self.proof_text())

    def test_a_proof_without_the_numbered_fields_is_bad_output_when_the_keys_resolved(self):
        proof = json.dumps({"ra": 0, "rb": 0, "oa_count": 0, "ob_count": 0, "oa": [], "ob": []})
        code, data = self.diff(self.ORDERED, self.ORDERED, env={"FAKE_STDOUT_PROOF": proof})
        self.assertEqual((code, data["error"]), (1, "bad_output"))


class DiffFailureTest(DiffTestCase):
    def test_each_connection_failure_kind_leaks_no_connection_value_in_each_session(self):
        for failing in ("describe", "types", "proof"):
            for name, stderr in (("auth", AUTH_STDERR), ("unreachable", UNREACHABLE_STDERR)):
                with self.subTest(failing=failing, kind=name):
                    code, data = self.diff(env={"FAKE_FAIL_KIND": failing, "FAKE_STDERR": stderr, "FAKE_EXIT": "2"})
                    self.assertEqual((code, data["error"]), (1, "connection_failed"))
                    text = json.dumps(data)
                    for canary in CANARIES:
                        self.assertNotIn(canary, text)

    def test_a_statement_error_is_statement_failed_and_no_later_session_runs(self):
        stderr = 'ERROR:  relation "nope" does not exist\nLINE 1: SELECT * FROM (SELECT * FROM nope\n'
        code, data = self.diff(env={"FAKE_FAIL_KIND": "describe", "FAKE_STDERR": stderr, "FAKE_EXIT": "1"})
        self.assertEqual((code, data["error"]), (1, "statement_failed"))
        self.assertIn('relation "nope" does not exist', data["message"])
        self.assertEqual(len(self.calls()), 1)
        self.reset_log()
        code, data = self.diff(env={"FAKE_FAIL_KIND": "types", "FAKE_STDERR": stderr, "FAKE_EXIT": "1"})
        self.assertEqual((data["error"], len(self.calls())), ("statement_failed", 2))

    def test_a_type_output_that_is_not_valid_is_bad_output_and_the_proof_never_runs(self):
        bad = [
            "not json", "[]", "{}", json.dumps({"a": [23], "b": [23]}),
            json.dumps({"a": [23, 23], "b": [23], "types": INT_TYPES}),
            json.dumps({"a": [23], "b": [99], "types": INT_TYPES}),
            json.dumps({"a": ["23"], "b": [23], "types": INT_TYPES}),
            json.dumps({"a": [23], "b": [23], "types": {"23": {"name": "integer", "float": False, "equality": True}}}),
            json.dumps({"a": [23], "b": [23], "types": {"23": {"name": "integer", "float": 0, "equality": True, "leaf": 23}}}),
            json.dumps({"a": [23], "b": [23], "types": {"23": {"name": "integer", "float": False, "equality": True, "leaf": 77}}}),
        ]
        for out in bad:
            with self.subTest(out=out):
                self.reset_log()
                code, data = self.diff(env={"FAKE_STDOUT_TYPES": out})
                self.assertEqual((code, data["error"]), (1, "bad_output"), data)
                self.assertEqual(len(self.calls()), 2)

    def test_a_proof_output_that_is_not_valid_is_bad_output(self):
        good = {"ra": 0, "rb": 0, "oa_count": 0, "ob_count": 0, "oa": [], "ob": []}
        for out in ("not json", "[]", json.dumps({**good, "ra": "0"}), json.dumps({**good, "oa_count": -1}),
                    json.dumps({**good, "oa": {}}), json.dumps({**good, "oa": [{"c1": 1, "c2": 2}]}),
                    json.dumps({**good, "oa": [[1]]}), json.dumps({**good, "ob": None})):
            with self.subTest(out=out):
                code, data = self.diff(env={"FAKE_STDOUT_PROOF": out})
                self.assertEqual((code, data["error"]), (1, "bad_output"), data)
        for name in ("ra", "rb", "oa_count", "ob_count", "oa", "ob"):
            partial = {k: v for k, v in good.items() if k != name}
            code, data = self.diff(env={"FAKE_STDOUT_PROOF": json.dumps(partial)})
            self.assertEqual(data["error"], "bad_output", name)


class SelectDowngradeTest(PgRunTestCase):
    """Select mode: a statement that calls a string-SQL function runs as a plain EXPLAIN, rolled back and read-only."""

    LISTED = (
        "query_to_xml('select 1', true, true, '')", "query_to_xml_and_xmlschema('select 1', true, true, '')",
        "query_to_xmlschema('select 1', true, true, '')", "cursor_to_xml('c'::refcursor, 1, true, true, '')",
        "cursor_to_xmlschema('c'::refcursor, true, true, '')", "ts_stat('select 1')", "crosstab('select 1')",
        "crosstab3('select 1')", "connectby('t', 'a', 'b', 'c', 1)",
    )

    def test_each_listed_function_gives_a_plain_explain_with_the_downgrade(self):
        for call in self.LISTED:
            statement = f"SELECT {call}"
            name = call.split("(")[0]
            with self.subTest(statement=statement):
                self.reset_log()
                code, data = self.explain(statement)
                self.assertEqual(code, 0, data)
                self.assertEqual((data["mode"], data["ran"]), ("select", "explain"))
                self.assertEqual(data["downgrade"], [{"kind": "function", "name": name}])
                self.assertEqual(data["reason"], f"the statement calls {name}")
                self.assertEqual(data["warnings"], [])
                self.assertIsInstance(data["plan"], list)
                run = self.explain_call()
                self.assertEqual(commands_of(run), ["BEGIN READ ONLY", f"EXPLAIN (FORMAT JSON) {statement}", "ROLLBACK"])
                self.assertIn("default_transaction_read_only=on", run["argv"][-1])

    def test_several_names_are_listed_in_scan_order(self):
        code, data = self.explain("SELECT ts_stat('a'), query_to_xml('b', true, true, ''), ts_stat('c')")
        self.assertEqual(code, 0, data)
        self.assertEqual(data["reason"], "the statement calls query_to_xml, ts_stat")
        self.assertEqual([hit["name"] for hit in data["downgrade"]], ["query_to_xml", "ts_stat"])

    def test_a_forbidden_name_in_the_text_argument_does_not_run(self):
        code, data = self.explain("SELECT query_to_xml('SELECT dblink_exec(1)', true, true, '')")
        self.assertEqual((code, data["ran"]), (0, "explain"), data)
        commands = commands_of(self.explain_call())
        self.assertEqual(commands[1], "EXPLAIN (FORMAT JSON) SELECT query_to_xml('SELECT dblink_exec(1)', true, true, '')")

    def test_a_direct_forbidden_call_is_still_refused_with_no_connection(self):
        code, data = self.explain("SELECT dblink_exec(1)")
        self.assertEqual((code, data["error"], data["reason"]), (1, "refused", "forbidden_function"))
        code, data = self.explain("SELECT query_to_xml('select 1', true, true, ''), pg_notify('c', 'p')")
        self.assertEqual((code, data["error"], data["reason"]), (1, "refused", "forbidden_function"))
        self.assertEqual(self.calls(), [])

    def test_a_normal_select_still_runs_analyze(self):
        code, data = self.explain("SELECT 1 AS one")
        self.assertEqual((code, data["ran"], data["downgrade"]), (0, "analyze", []))
        self.assertEqual(commands_of(self.explain_call())[1], "EXPLAIN (ANALYZE, FORMAT JSON) SELECT 1 AS one")

    def test_the_downgraded_run_has_the_timeouts_of_the_version(self):
        code, data = self.explain("SELECT ts_stat('select 1')", env={"FAKE_VERSION": "130005"})
        self.assertEqual((code, data["ran"]), (0, "explain"), data)
        self.assertNotIn("transaction_timeout", data["timeouts"])
        self.assertEqual(data["timeouts"]["statement_timeout"], "30s")


if __name__ == "__main__":
    unittest.main()
