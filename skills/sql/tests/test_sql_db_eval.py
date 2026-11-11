import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
DB_EVAL = os.path.join(SKILL_DIR, "evals", "db", "db_eval.py")
ALLOWLIST = os.path.join(SKILL_DIR, "scripts", "allowlist.py")
PG_RUN = os.path.join(SKILL_DIR, "scripts", "pg_run.py")
with open(os.path.join(SKILL_DIR, "evals", "db", "canaries.json"), encoding="utf-8") as handle:
    CANARIES = json.load(handle)

FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
work = os.environ["FAKE_DOCKER_DIR"]
def log(extra=None):
    entry = {"args": args}
    entry.update(extra or {})
    with open(os.path.join(work, "log.jsonl"), "a") as handle:
        handle.write(json.dumps(entry) + "\n")
def read(name, default):
    path = os.path.join(work, name)
    return open(path).read().strip() if os.path.exists(path) else default
verb = args[0] if args else ""
if verb == "run":
    count = int(read("runs", "0")) + 1
    open(os.path.join(work, "runs"), "w").write(str(count))
    log({"state_exists": os.path.exists(os.environ["FAKE_STATE_FILE"])})
    sys.exit(1 if count == int(os.environ.get("FAKE_FAIL_RUN", "0")) else 0)
log()
if verb == "info":
    sys.exit(1 if os.environ.get("FAKE_INFO_FAIL") else 0)
if verb == "port":
    print("127.0.0.1:" + ("40013" if args[1].endswith("-13") else "40018"))
elif verb == "rm":
    if os.environ.get("FAKE_RM_FAIL"):
        sys.stderr.write("Error: cannot remove")
        sys.exit(1)
elif verb == "exec":
    if "psql" in args:
        sql = args[args.index("-c") + 1]
        if "information_schema.tables" in sql:
            print("customers\norders\nevents")
        elif "md5(" in sql:
            print(read("checksum", "m1"))
        elif "pg_sequences" in sql:
            print("orders_id_seq|" + read("seq", "7"))
            print("customers_id_seq|")
'''

SLEEPER = '''#!/usr/bin/env python3
import os, sys, time
work = os.environ["FAKE_DOCKER_DIR"]
if sys.argv[1] == "exit":
    open(os.path.join(work, sys.argv[3]), "w").write(sys.argv[4]) if len(sys.argv) > 4 else None
    sys.exit(int(sys.argv[2]))
if sys.argv[1] == "wait":
    open(os.path.join(work, "started"), "w").write(os.environ.get("DBEVAL_STATE", ""))
    time.sleep(60)
'''


def slurp(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def spit(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


NEEDS_TOMLLIB = unittest.skipIf(sys.version_info < (3, 11), "allowlist.py needs tomllib (Python 3.11 or newer)")


class TempTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.work = os.path.join(self.root, "fake")
        self.bin = os.path.join(self.root, "bin")
        self.state = os.path.join(self.root, "state")
        for folder in (self.work, self.bin):
            os.makedirs(folder)
        self.add_script("docker", FAKE_DOCKER)
        self.add_script("sleeper", SLEEPER)
        self.env = {
            "PATH": self.bin + os.pathsep + os.environ["PATH"], "FAKE_DOCKER_DIR": self.work,
            "FAKE_STATE_FILE": os.path.join(self.state, "state.json"), "HOME": os.path.join(self.root, "home"),
        }
        os.makedirs(self.env["HOME"])

    def add_script(self, name, text):
        path = os.path.join(self.bin, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(path, 0o755)

    def db_eval(self, *args, env=None, cwd=None):
        proc = subprocess.run([sys.executable, "-I", DB_EVAL, *args], capture_output=True, text=True,
                              env={**self.env, **(env or {})}, cwd=cwd or self.root)
        return proc

    def log(self):
        path = os.path.join(self.work, "log.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]

    def verbs(self, verb):
        return [entry["args"] for entry in self.log() if entry["args"][0] == verb]


class SetupTest(TempTest):
    def test_setup_starts_both_versions_and_writes_the_state_before_the_first_run(self):
        proc = self.db_eval("setup", "--state", self.state)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        runs = [entry for entry in self.log() if entry["args"][0] == "run"]
        self.assertEqual([entry["state_exists"] for entry in runs], [True, True])
        images = [next(a for a in entry["args"] if a.startswith("postgres:")) for entry in runs]
        self.assertEqual(images, ["postgres:13", "postgres:18"])
        for entry, image in zip(runs, images):
            args = entry["args"]
            # The server flag follows the image name: the plan cases need a table larger than the shared buffers.
            self.assertEqual(args[args.index(image) + 1:], ["-c", "shared_buffers=2MB"])
            for flag in ("--rm", "-d", "127.0.0.1::5432"):
                self.assertIn(flag, args)
            self.assertTrue(args[args.index("--name") + 1].startswith("sqlskill-dbeval-"))
            self.assertIn(f"POSTGRES_DB={CANARIES['dbname']}", args)
            self.assertEqual(sum(1 for a in args if a == "-v"), 1)  # the seed file is the only mount

    def test_setup_writes_the_files(self):
        self.assertEqual(self.db_eval("setup", "--state", self.state).returncode, 0)
        service = slurp(os.path.join(self.state, "pg_service.conf"))
        for name in ("app-pg13", "app-pg18", "app-badpw", "app-wronghost", "other-db"):
            self.assertIn(f"[{name}]", service)
        self.assertIn("port=40013", service)
        self.assertIn("port=40018", service)
        self.assertIn("hostaddr=127.0.0.2", service)
        for key in ("host", "host_badpw", "host_down", "user", "dbname"):
            self.assertIn(CANARIES[key], service)
        pgpass_path = os.path.join(self.state, "pgpass")
        self.assertEqual(stat.S_IMODE(os.stat(pgpass_path).st_mode), 0o600)
        pgpass = slurp(pgpass_path).splitlines()
        wrong = [line for line in pgpass if CANARIES["wrong_password"] in line]
        self.assertEqual(len(wrong), 1)
        self.assertTrue(wrong[0].startswith(CANARIES["host_badpw"] + ":"))
        self.assertTrue(any(line.endswith(":" + CANARIES["password"]) for line in pgpass))
        self.assertNotIn(CANARIES["password"], service)

    @NEEDS_TOMLLIB
    def test_the_allowlist_is_read_by_the_reader_with_four_services(self):
        self.assertEqual(self.db_eval("setup", "--state", self.state).returncode, 0)
        repo = os.path.join(self.root, "repo")
        os.makedirs(repo)
        git_env = {"PATH": self.env["PATH"], "HOME": self.env["HOME"]}
        subprocess.run(["git", "init", "-q", repo], check=True, env=git_env)
        subprocess.run(["git", "-C", repo, "remote", "add", "origin", "https://example.invalid/eval/sql-db-case.git"],
                       check=True, env=git_env)
        env = {**git_env, "XDG_CONFIG_HOME": os.path.join(self.state, "xdg")}
        out = subprocess.run([sys.executable, "-I", ALLOWLIST, repo], capture_output=True, text=True, env=env)
        data = json.loads(out.stdout)
        self.assertTrue(data["access"], data)
        self.assertEqual(data["services"], ["app-pg13", "app-pg18", "app-badpw", "app-wronghost"])

    def test_a_failed_second_start_removes_the_first_container(self):
        proc = self.db_eval("setup", "--state", self.state, env={"FAKE_FAIL_RUN": "2"})
        self.assertEqual(proc.returncode, 1)
        removed = [args[-1] for args in self.verbs("rm")]
        self.assertEqual(len(removed), 2)
        self.assertTrue(all(name.startswith("sqlskill-dbeval-") for name in removed))
        self.assertFalse(os.path.exists(os.path.join(self.state, "state.json")))
        self.assertFalse(os.path.exists(os.path.join(self.state, "pgpass")))

    def test_a_daemon_that_does_not_answer_stops_with_a_message(self):
        proc = self.db_eval("setup", "--state", self.state, env={"FAKE_INFO_FAIL": "1"})
        self.assertEqual(proc.returncode, 1)
        self.assertIn("docker daemon does not answer", proc.stderr)
        self.assertEqual(self.verbs("run"), [])

    def test_a_relative_state_is_refused(self):
        for action in ("setup", "teardown"):
            with self.subTest(action=action):
                proc = self.db_eval(action, "--state", "relative/state")
                self.assertEqual(proc.returncode, 1)
                self.assertIn("absolute", proc.stderr)

    def test_missing_arguments_are_a_usage_error(self):
        for args in (["setup"], ["snapshot", "--state", self.state], ["scaffold"], ["around", "--state", self.state],
                     ["setup", "--state", self.state, "--", "echo"]):
            with self.subTest(args=args):
                self.assertEqual(self.db_eval(*args).returncode, 2)


class TeardownTest(TempTest):
    def test_teardown_removes_the_containers_and_the_files(self):
        self.db_eval("setup", "--state", self.state)
        proc = self.db_eval("teardown", "--state", self.state)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        removed = self.verbs("rm")
        self.assertEqual(len(removed), 2)
        for args in removed:
            self.assertEqual(args[:2], ["rm", "-fv"])
        self.assertFalse(os.path.exists(self.state))

    def test_teardown_twice_and_with_no_state_is_safe(self):
        self.assertEqual(self.db_eval("teardown", "--state", self.state).returncode, 0)
        self.db_eval("setup", "--state", self.state)
        self.assertEqual(self.db_eval("teardown", "--state", self.state).returncode, 0)
        self.assertEqual(self.db_eval("teardown", "--state", self.state).returncode, 0)

    def test_teardown_deletes_no_other_file_and_no_folder_with_content(self):
        self.db_eval("setup", "--state", self.state)
        extra = os.path.join(self.state, "keep.txt")
        nested = os.path.join(self.state, "xdg", "extra.txt")
        for path in (extra, nested):
            spit(path, "x")
        self.assertEqual(self.db_eval("teardown", "--state", self.state).returncode, 0)
        self.assertTrue(os.path.exists(extra))
        self.assertTrue(os.path.exists(nested))
        self.assertFalse(os.path.exists(os.path.join(self.state, "pgpass")))

    def test_a_container_that_cannot_be_removed_fails_and_keeps_the_state_for_a_retry(self):
        self.db_eval("setup", "--state", self.state)
        proc = self.db_eval("teardown", "--state", self.state, env={"FAKE_RM_FAIL": "1"})
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(os.path.exists(os.path.join(self.state, "state.json")))
        self.assertEqual(self.db_eval("teardown", "--state", self.state).returncode, 0)


class SnapshotTest(TempTest):
    def snapshot(self, version="18"):
        out = os.path.join(self.root, f"snap-{version}.json")
        proc = self.db_eval("snapshot", "--state", self.state, "--version", version, "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(out, encoding="utf-8") as handle:
            return json.load(handle)

    def test_a_snapshot_holds_the_table_checksums_and_the_sequence_values(self):
        self.db_eval("setup", "--state", self.state)
        data = self.snapshot()
        self.assertEqual(data["tables"], {"shop.customers": "m1", "shop.orders": "m1", "shop.events": "m1"})
        self.assertEqual(data["sequences"], {"shop.orders_id_seq": 7, "shop.customers_id_seq": None})
        queries = [args[args.index("-c") + 1] for args in self.verbs("exec") if "psql" in args]
        self.assertTrue(any("information_schema" in query for query in queries))
        self.assertTrue(any("pg_sequences" in query for query in queries))

    def test_the_snapshot_runs_in_the_container_of_its_version_through_the_socket(self):
        self.db_eval("setup", "--state", self.state)
        self.snapshot("13")
        names = {args[1] for args in self.verbs("exec") if "psql" in args}
        self.assertEqual(len(names), 1)
        self.assertTrue(names.pop().endswith("-13"))
        for args in self.verbs("exec"):
            if "psql" in args:
                self.assertNotIn("-h", args)

    def test_a_changed_row_changes_the_snapshot(self):
        self.db_eval("setup", "--state", self.state)
        before = self.snapshot()
        spit(os.path.join(self.work, "checksum"), "m2")
        self.assertNotEqual(before["tables"], self.snapshot()["tables"])


class ScaffoldTest(TempTest):
    def make_case(self):
        case = os.path.join(self.root, "case")
        os.makedirs(os.path.join(case, "repo", "docs", "agents"))
        spit(os.path.join(case, "repo", "docs", "agents", "sql.md"), "# rules\n")
        return case

    @NEEDS_TOMLLIB
    def test_scaffold_copies_the_repo_adds_the_origin_and_writes_the_files_under_home(self):
        case = self.make_case()
        cwd = os.path.join(self.root, "run")
        os.makedirs(cwd)
        proc = self.db_eval("scaffold", "--case", case, cwd=cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(os.path.isfile(os.path.join(cwd, "docs", "agents", "sql.md")))
        git_env = {"PATH": self.env["PATH"], "HOME": self.env["HOME"]}
        url = subprocess.run(["git", "-C", cwd, "remote", "get-url", "origin"], capture_output=True, text=True,
                             env=git_env).stdout.strip()
        self.assertEqual(url, "https://example.invalid/eval/sql-db-case.git")
        home = self.env["HOME"]
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(home, ".pgpass")).st_mode), 0o600)
        self.assertIn("[other-db]", slurp(os.path.join(home, ".pg_service.conf")))
        out = subprocess.run([sys.executable, "-I", ALLOWLIST, cwd], capture_output=True, text=True,
                             env={**git_env, "XDG_CONFIG_HOME": os.path.join(home, ".config")})
        data = json.loads(out.stdout)
        self.assertEqual((data["access"], data["services"]),
                         (True, ["app-pg13", "app-pg18", "app-badpw", "app-wronghost"]))
        self.assertEqual(self.verbs("run"), [])

    @NEEDS_TOMLLIB
    def test_pg_run_on_an_off_allowlist_service_gives_not_allowed_with_no_connection(self):
        case = self.make_case()
        cwd = os.path.join(self.root, "run")
        os.makedirs(cwd)
        self.assertEqual(self.db_eval("scaffold", "--case", case, cwd=cwd).returncode, 0)
        home = self.env["HOME"]
        # psql would be run only after the allowlist check, so a psql that records its call proves that none ran
        self.add_script("psql", "#!/bin/sh\ntouch \"$FAKE_DOCKER_DIR/psql-called\"\nexit 0\n")
        env = {"PATH": self.env["PATH"], "HOME": home, "XDG_CONFIG_HOME": os.path.join(home, ".config"),
               "FAKE_DOCKER_DIR": self.work}
        done = subprocess.run(
            [sys.executable, "-I", PG_RUN, "explain", "--repo", cwd, "--service", "other-db", "--mode", "select",
             "--statement", "SELECT 1"], capture_output=True, text=True, env=env)
        data = json.loads(done.stdout)
        self.assertEqual((done.returncode, data["ok"], data["error"]), (1, False, "not_allowed"), done.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.work, "psql-called")))

    def test_scaffold_refuses_to_run_with_no_home(self):
        case = self.make_case()
        cwd = os.path.join(self.root, "run")
        os.makedirs(cwd)
        env = {key: value for key, value in self.env.items() if key != "HOME"}
        proc = subprocess.run([sys.executable, "-I", DB_EVAL, "scaffold", "--case", case], capture_output=True,
                              text=True, env=env, cwd=cwd)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("HOME", proc.stderr)
        self.assertEqual(os.listdir(cwd), [])


class AroundTest(TempTest):
    def around(self, *command, flag=False, env=None):
        args = ["around", "--state", self.state] + (["--sequences-may-differ"] if flag else []) + ["--", *command]
        return self.db_eval(*args, env=env)

    def sleeper(self, *args):
        return [os.path.join(self.bin, "sleeper"), *args]

    def test_a_command_that_changes_nothing_gives_exit_0_and_the_teardown_runs(self):
        proc = self.around(*self.sleeper("exit", "0"))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(len(self.verbs("rm")), 2)
        self.assertEqual(proc.stdout.count("PASS"), 2)

    def test_the_exit_code_is_the_numeric_maximum_of_the_command_g_and_the_teardown(self):
        self.assertEqual(self.around(*self.sleeper("exit", "3")).returncode, 3)
        self.assertEqual(self.around(*self.sleeper("exit", "1")).returncode, 1)
        # a table change makes G exit 1, a command that exits 0 does not hide it
        proc = self.around(*self.sleeper("exit", "0", "checksum", "m2"))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("FAIL table: shop.customers changed", proc.stdout)
        # the command exit 3 outranks G exit 1
        self.assertEqual(self.around(*self.sleeper("exit", "3", "checksum", "m3")).returncode, 3)
        # a teardown that fails gives exit 1 even when the command and G pass
        self.assertEqual(self.around(*self.sleeper("exit", "0"), env={"FAKE_RM_FAIL": "1"}).returncode, 1)

    def test_the_teardown_runs_after_a_command_that_fails(self):
        self.assertEqual(self.around(*self.sleeper("exit", "1")).returncode, 1)
        self.assertEqual(len(self.verbs("rm")), 2)

    def test_g_gets_the_sequence_flag_only_when_around_got_it(self):
        self.assertEqual(self.around(*self.sleeper("exit", "0", "seq", "8")).returncode, 1)
        self.assertEqual(self.around(*self.sleeper("exit", "0", "seq", "9"), flag=True).returncode, 0)

    def test_the_command_runs_with_the_state_variable_and_the_snapshots_exist(self):
        proc = self.around(*self.sleeper("exit", "0"))
        self.assertEqual(proc.returncode, 0)
        # the teardown keeps files that setup did not write, so the four snapshots stay
        self.assertEqual(sorted(os.listdir(self.state)),
                         ["after-13.json", "after-18.json", "before-13.json", "before-18.json"])

    def test_a_sigterm_while_the_command_runs_still_runs_the_teardown(self):
        proc = subprocess.Popen(
            [sys.executable, "-I", DB_EVAL, "around", "--state", self.state, "--", *self.sleeper("wait")],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env, cwd=self.root)
        started = os.path.join(self.work, "started")
        deadline = time.monotonic() + 30
        while not os.path.exists(started) and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(os.path.exists(started))
        self.assertEqual(slurp(started), self.state)
        proc.send_signal(signal.SIGTERM)
        proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 128 + signal.SIGTERM)
        self.assertEqual(len(self.verbs("rm")), 2)


if __name__ == "__main__":
    unittest.main()
