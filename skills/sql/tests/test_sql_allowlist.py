import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SCRIPT = os.path.join(SKILL, "scripts", "allowlist.py")

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


@unittest.skipUnless(sys.version_info >= (3, 11), "the reader needs tomllib (Python 3.11 or newer)")
class AllowlistReaderTest(unittest.TestCase):
    """The allowlist reader, run as a command. Home and XDG folders are temp folders."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.home = os.path.join(self.root, "home")
        self.xdg = os.path.join(self.root, "xdg")
        self.repo = os.path.join(self.root, "repo")
        for folder in (self.home, self.xdg, self.repo):
            os.makedirs(folder)
        self.env = {"PATH": os.environ["PATH"], "HOME": self.home, "XDG_CONFIG_HOME": self.xdg, **GIT_ENV}
        self.git("init", "-q")

    def git(self, *args, cwd=None):
        done = subprocess.run(
            ["git", *args], cwd=cwd or self.repo, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def origin(self, url):
        self.git("remote", "add", "origin", url)

    def write_allowlist(self, text, folder=None):
        folder = folder or os.path.join(self.xdg, "sql-skill")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "allowlist.toml")
        with open(path, "wb" if isinstance(text, bytes) else "w") as handle:
            handle.write(text)
        return path

    def run_reader(self, *args, env=None, timeout=20):
        done = subprocess.run(
            [sys.executable, "-I", SCRIPT, *(args or (self.repo,))],
            capture_output=True, text=True, env=env or self.env, timeout=timeout,
        )
        return done

    def read(self, *args, env=None):
        done = self.run_reader(*args, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def entry(self, key, body='services = ["app-dev"]\n'):
        return f'["{key}"]\n{body}'

    # --- key normalization ------------------------------------------------

    def key_of(self, url):
        if self.has_origin():
            self.git("remote", "set-url", "origin", url)
        else:
            self.origin(url)
        self.write_allowlist("")
        return self.read()["key"]

    def has_origin(self):
        return "origin" in self.git("remote").split()

    def test_ssh_and_https_remotes_map_to_one_key(self):
        urls = [
            "git@github.com:Owner/Repo.git",
            "https://GitHub.com/Owner/Repo.git",
            "ssh://git@github.com:22/Owner/Repo.git",
            "https://user:secret@GITHUB.COM:8443/Owner/Repo/",
            "https://github.com/Owner/Repo",
            "github.com:Owner/Repo",
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.key_of(url), "github.com/Owner/Repo")

    def test_the_path_keeps_its_case_and_the_host_is_lowercased(self):
        self.assertEqual(self.key_of("https://EXAMPLE.org/Team/Repo.git"), "example.org/Team/Repo")

    def test_an_ipv6_host_keeps_its_brackets(self):
        self.assertEqual(self.key_of("ssh://git@[::1]:2222/o/r.git"), "[::1]/o/r")

    def test_a_trailing_slash_and_dot_git_are_dropped_until_stable(self):
        self.assertEqual(self.key_of("https://h.example/o/r.git/"), "h.example/o/r")

    def test_a_local_path_keeps_its_path_with_a_leading_slash(self):
        self.assertEqual(self.key_of("/srv/git/Repo.git"), "/srv/git/Repo")
        self.assertEqual(self.key_of("file:///srv/git/Repo.git"), "/srv/git/Repo")

    def test_the_url_is_read_with_the_insteadof_rewrite(self):
        self.origin("https://h.example/o/r.git")
        self.git("config", "url.ssh://git@mirror.example/.insteadOf", "https://h.example/")
        self.write_allowlist("")
        self.assertEqual(self.read()["key"], "mirror.example/o/r")

    def test_a_repo_with_no_remote_uses_the_git_common_dir_as_git_prints_it(self):
        self.write_allowlist("")
        expected = self.git("rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        self.assertEqual(self.read()["key"], expected)
        self.assertTrue(expected.endswith("/.git"))

    def test_a_linked_worktree_gets_the_key_of_the_main_checkout(self):
        self.git("commit", "-q", "--allow-empty", "-m", "x")
        wt = os.path.join(self.root, "wt")
        self.git("worktree", "add", "-q", wt)
        self.write_allowlist("")
        self.assertEqual(self.read(wt)["key"], self.read(self.repo)["key"])

    def test_a_repo_path_with_a_byte_that_is_not_utf8_still_gives_one_json_result(self):
        odd = os.path.join(os.fsencode(self.root), b"repo-\xff")
        os.mkdir(odd)
        self.git("init", "-q", cwd=odd)
        done = self.run_reader(os.fsdecode(odd))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["access"], False)

    def test_no_git_on_path_gives_no_repo(self):
        empty = os.path.join(self.root, "empty-bin")
        os.makedirs(empty)
        data = self.read(env={"PATH": empty})
        self.assertEqual((data["access"], data["key"], data["reason"]), (False, None, "no_repo"))

    def test_a_folder_that_is_not_a_git_repo_gives_no_repo(self):
        plain = os.path.join(self.root, "plain")
        os.makedirs(plain)
        data = self.read(plain)
        self.assertEqual(
            (data["access"], data["key"], data["services"], data["timeouts"], data["reason"]),
            (False, None, [], {}, "no_repo"),
        )

    # --- the file ---------------------------------------------------------

    def test_an_entry_gives_access_with_its_services(self):
        self.origin("git@github.com:o/r.git")
        self.write_allowlist(self.entry("github.com/o/r", 'services = ["app-dev", "app-test"]\n'))
        data = self.read()
        self.assertEqual(
            data, {"access": True, "key": "github.com/o/r", "services": ["app-dev", "app-test"], "timeouts": {}}
        )

    def test_a_missing_file_gives_missing_file(self):
        self.origin("git@github.com:o/r.git")
        data = self.read()
        self.assertEqual((data["access"], data["reason"], data["services"]), (False, "missing_file", []))
        self.assertNotIn("detail", data)

    def test_a_directory_in_place_of_the_file_gives_unreadable_file(self):
        self.origin("git@github.com:o/r.git")
        os.makedirs(os.path.join(self.xdg, "sql-skill", "allowlist.toml"))
        data = self.read()
        self.assertEqual((data["access"], data["reason"]), (False, "unreadable_file"))

    def test_malformed_toml_gives_malformed_file_with_detail(self):
        self.origin("git@github.com:o/r.git")
        self.write_allowlist('["github.com/o/r"\nservices = [')
        data = self.read()
        self.assertEqual((data["access"], data["reason"]), (False, "malformed_file"))
        self.assertTrue(data["detail"])

    def test_a_file_that_is_not_utf8_gives_malformed_file(self):
        self.origin("git@github.com:o/r.git")
        self.write_allowlist(b'["github.com/o/r"]\nservices = ["\xff\xfe"]\n')
        self.assertEqual(self.read()["reason"], "malformed_file")

    def test_a_deeply_nested_file_gives_malformed_file(self):
        self.origin("git@github.com:o/r.git")
        for body in ("a = " + "[" * 5000 + "]" * 5000 + "\n", "a = " + "{a=" * 3000 + "1" + "}" * 3000 + "\n"):
            with self.subTest(body=body[:12]):
                self.write_allowlist(body)
                self.assertEqual(self.read()["reason"], "malformed_file")

    def test_an_empty_file_gives_no_entry(self):
        self.origin("git@github.com:o/r.git")
        self.write_allowlist("")
        data = self.read()
        self.assertEqual((data["access"], data["reason"]), (False, "no_entry"))

    def test_no_entry_for_the_key_gives_no_entry(self):
        self.origin("git@github.com:o/r.git")
        self.write_allowlist(self.entry("github.com/other/repo"))
        self.assertEqual(self.read()["reason"], "no_entry")

    def test_an_empty_services_list_gives_access_with_no_service(self):
        self.origin("git@github.com:o/r.git")
        self.write_allowlist(self.entry("github.com/o/r", "services = []\n"))
        data = self.read()
        self.assertEqual((data["access"], data["services"]), (True, []))

    def test_a_bad_entry_of_another_repo_key_does_not_change_this_repo(self):
        self.origin("git@github.com:o/r.git")
        self.write_allowlist(
            self.entry("github.com/o/r")
            + '\n["github.com/x/y"]\nservices = "oops"\n'
        )
        self.assertTrue(self.read()["access"])

    # --- shape ------------------------------------------------------------

    def malformed(self, body):
        if not self.has_origin():
            self.origin("git@github.com:o/r.git")
        self.write_allowlist(self.entry("github.com/o/r", body))
        data = self.read()
        self.assertEqual((data["access"], data["reason"]), (False, "malformed_file"), body)
        self.assertTrue(data["detail"])

    def test_each_bad_shape_is_malformed(self):
        cases = [
            'services = "app-dev"\n',
            "services = [1]\n",
            'services = ["a b"]\n',
            'services = ["a=b"]\n',
            'services = ["a\'b"]\n',
            'services = ["a"]\ntimeouts = "x"\n',
            'services = ["a"]\n[\"github.com/o/r\".timeouts]\na = "1s"\n',
            'services = ["a"]\n[\"github.com/o/r\".timeouts.a]\nbogus_timeout = "1s"\n',
            'services = ["a"]\n[\"github.com/o/r\".timeouts.a]\nstatement_timeout = 5\n',
            'services = ["a"]\n[\"github.com/o/r\".timeouts.a]\nstatement_timeout = "5 s"\n',
            'services = ["a"]\n[\"github.com/o/r\".timeouts.a]\nstatement_timeout = "5s; drop"\n',
            'services = ["a"]\n[\"github.com/o/r\".timeouts.a]\nstatement_timeout = "٥s"\n',
            'services = ["a"]\n[\"github.com/o/r\".timeouts.a]\nstatement_timeout = "0"\n',
            'services = ["a"]\n[\"github.com/o/r\".timeouts.a]\nstatement_timeout = "0s"\n',
            'services = ["a"]\n[\"github.com/o/r\".timeouts.a]\nstatement_timeout = "-1s"\n',
            'services = ["a"]\n[\"github.com/o/r\".timeouts.a]\nstatement_timeout = ""\n',
            'services = ["a"]\n[\"github.com/o/r\".timeouts.unlisted]\nstatement_timeout = "bad"\n',
            'services = ["a"]\nfoo = 1\n',
            'services = ["a"]\ntimeout = "1s"\n',
        ]
        for body in cases:
            with self.subTest(body=body):
                self.malformed(body)

    def test_an_entry_with_no_services_key_is_malformed(self):
        self.origin("git@github.com:o/r.git")
        self.write_allowlist('["github.com/o/r"]\n')
        self.assertEqual(self.read()["reason"], "malformed_file")

    def test_a_timeout_with_thousands_of_digits_still_gives_a_json_result(self):
        self.origin("git@github.com:o/r.git")
        self.write_allowlist(
            '["github.com/o/r"]\nservices = ["a"]\n["github.com/o/r".timeouts.a]\n'
            f'statement_timeout = "{"1" * 5000}s"\n'
        )
        data = self.read()
        self.assertTrue(data["access"])
        self.write_allowlist(
            '["github.com/o/r"]\nservices = ["a"]\n["github.com/o/r".timeouts.a]\n'
            f'statement_timeout = "{"0" * 5000}s"\n'
        )
        self.assertEqual(self.read()["reason"], "malformed_file")

    def test_a_valid_timeout_override_is_returned_for_its_service_only(self):
        self.origin("git@github.com:o/r.git")
        body = (
            'services = ["app-dev", "app-test"]\n'
            '["github.com/o/r".timeouts.app-dev]\n'
            'statement_timeout = "60s"\n'
            'lock_timeout = "500ms"\n'
            'idle_in_transaction_session_timeout = "1min"\n'
            'transaction_timeout = "2h"\n'
            '["github.com/o/r".timeouts.unlisted]\n'
            'statement_timeout = "9d"\n'
        )
        self.write_allowlist(f'["github.com/o/r"]\n{body}')
        data = self.read()
        self.assertTrue(data["access"])
        self.assertEqual(
            data["timeouts"],
            {"app-dev": {
                "statement_timeout": "60s", "lock_timeout": "500ms",
                "idle_in_transaction_session_timeout": "1min", "transaction_timeout": "2h",
            }},
        )

    # --- the file location ------------------------------------------------

    def test_xdg_config_home_unset_empty_and_relative_use_the_home_default(self):
        self.origin("git@github.com:o/r.git")
        default = os.path.join(self.home, ".config", "sql-skill")
        self.write_allowlist(self.entry("github.com/o/r"), folder=default)
        for value in (None, "", "relative/dir"):
            with self.subTest(xdg=value):
                env = {k: v for k, v in self.env.items() if k != "XDG_CONFIG_HOME"}
                if value is not None:
                    env["XDG_CONFIG_HOME"] = value
                self.assertTrue(self.read(env=env)["access"])

    def test_an_absolute_xdg_config_home_wins_over_the_home_default(self):
        self.origin("git@github.com:o/r.git")
        self.write_allowlist(self.entry("github.com/o/r", "services = []\n"), folder=os.path.join(self.home, ".config", "sql-skill"))
        self.write_allowlist(self.entry("github.com/o/r", 'services = ["from-xdg"]\n'))
        self.assertEqual(self.read()["services"], ["from-xdg"])

    # --- the service check ------------------------------------------------

    def write_service_file(self, text, name="pg_service.conf"):
        path = os.path.join(self.root, name)
        with open(path, "w") as handle:
            handle.write(text)
        return path

    def check(self, service_file_text=None, as_directory=False, services=("app-dev", "app-test")):
        self.origin("git@github.com:o/r.git")
        listed = ", ".join(f'"{s}"' for s in services)
        self.write_allowlist(self.entry("github.com/o/r", f"services = [{listed}]\n"))
        env = dict(self.env)
        path = os.path.join(self.root, "pg_service.conf")
        if as_directory:
            os.makedirs(path)
        elif service_file_text is not None:
            self.write_service_file(service_file_text)
        env["PGSERVICEFILE"] = path
        # a named pipe: opening it for reading would block, so a read of the password file fails the test
        fifo = os.path.join(self.root, "pgpass-pipe")
        os.mkfifo(fifo)
        env["PGPASSFILE"] = fifo
        done = self.run_reader(self.repo, "--check-services", env=env, timeout=10)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_the_service_check_finds_headers_and_reports_the_missing_ones(self):
        text = "[app-dev]\nhost=db.example.invalid\npassword=canary-secret\n\n  [other]  \nport=1\n"
        data = self.check(text)
        self.assertEqual(data["service_check"], {"service_file": "found", "missing": ["app-test"]})
        self.assertNotIn("canary-secret", json.dumps(data))
        self.assertNotIn("db.example.invalid", json.dumps(data))

    def test_a_header_with_blanks_around_it_counts(self):
        data = self.check("  [app-dev]  \n\t[app-test]\t\n")
        self.assertEqual(data["service_check"]["missing"], [])

    def test_a_missing_service_file_reports_every_service(self):
        data = self.check(None)
        self.assertEqual(data["service_check"], {"service_file": "missing", "missing": ["app-dev", "app-test"]})

    def test_a_directory_in_place_of_the_service_file_is_unreadable(self):
        data = self.check(as_directory=True)
        self.assertEqual(data["service_check"], {"service_file": "unreadable", "missing": ["app-dev", "app-test"]})

    def test_the_service_check_of_a_no_access_result_has_nothing_missing(self):
        self.origin("git@github.com:o/r.git")
        env = dict(self.env, PGSERVICEFILE=os.path.join(self.root, "nothing.conf"))
        done = self.run_reader(self.repo, "--check-services", env=env)
        data = json.loads(done.stdout)
        self.assertFalse(data["access"])
        self.assertEqual(data["service_check"], {"service_file": "missing", "missing": []})

    def test_the_service_file_defaults_to_the_home_file(self):
        self.origin("git@github.com:o/r.git")
        self.write_allowlist(self.entry("github.com/o/r"))
        with open(os.path.join(self.home, ".pg_service.conf"), "w") as handle:
            handle.write("[app-dev]\n")
        done = self.run_reader(self.repo, "--check-services")
        self.assertEqual(json.loads(done.stdout)["service_check"], {"service_file": "found", "missing": []})

    def test_without_the_flag_there_is_no_service_check(self):
        self.origin("git@github.com:o/r.git")
        self.write_allowlist(self.entry("github.com/o/r"))
        self.assertNotIn("service_check", self.read())

    # --- usage ------------------------------------------------------------

    def test_a_missing_repo_argument_is_a_usage_error(self):
        done = subprocess.run([sys.executable, "-I", SCRIPT], capture_output=True, text=True, env=self.env)
        self.assertEqual(done.returncode, 2)
        self.assertEqual(done.stdout, "")
        self.assertTrue(done.stderr.strip())

    def test_an_unknown_option_is_a_usage_error(self):
        done = self.run_reader(self.repo, "--bogus")
        self.assertEqual(done.returncode, 2)


if __name__ == "__main__":
    unittest.main()
