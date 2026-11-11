import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
SCRIPT = os.path.join(SKILL_DIR, "scripts", "formatter_install.py")

PACKAGES = ["prettier", "prettier-plugin-embed", "prettier-plugin-sql"]
PLACEHOLDER = "<chosen by the package manager>"

FAKE_MANAGER = """#!{python}
import json, os, sys
log = os.environ["FAKE_LOG"]
with open(log, "a", encoding="utf-8") as handle:
    handle.write(json.dumps({{"argv": sys.argv[1:], "node_env": os.environ.get("NODE_ENV"), "cwd": os.getcwd()}}) + "\\n")
if os.environ.get("FAKE_FAIL"):
    sys.stderr.write("boom one\\nboom two\\n")
    sys.exit(1)
package = json.load(open("package.json", encoding="utf-8"))
dev = package.setdefault("devDependencies", {{}})
for name in sys.argv[1:]:
    if not name.startswith("-"):
        dev[name] = "^1.0.0"
json.dump(package, open("package.json", "w", encoding="utf-8"), indent=2)
"""


def run(*args, env=None):
    result = subprocess.run([sys.executable, "-I", SCRIPT, *args], capture_output=True, text=True, env=env)
    return result.returncode, result.stdout, result.stderr


class InstallCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = os.path.join(tmp.name, "repo")
        self.bin = os.path.join(tmp.name, "bin")
        self.log = os.path.join(tmp.name, "fake.log")
        os.makedirs(self.repo)
        os.makedirs(self.bin)
        self.env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"], FAKE_LOG=self.log)
        self.env.pop("FAKE_FAIL", None)
        self.env["NODE_ENV"] = "production"

    def write(self, name, text):
        path = os.path.join(self.repo, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def read(self, name):
        with open(os.path.join(self.repo, name), encoding="utf-8") as handle:
            return handle.read()

    def package(self, dev=(), extra=None):
        data = {"name": "x", "devDependencies": {name: "1.0.0" for name in dev}}
        data.update(extra or {})
        self.write("package.json", json.dumps(data, indent=2) + "\n")

    def fake(self, name):
        path = os.path.join(self.bin, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(FAKE_MANAGER.format(python=sys.executable))
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def command(self, *args, code=0):
        got, out, err = run(*args, env=self.env)
        self.assertEqual(got, code, (out, err))
        return json.loads(out)

    def offer(self, *extra):
        return self.command("offer", self.repo, *extra)

    def snapshot(self):
        found = {}
        for folder, _, files in os.walk(self.repo):
            for name in files:
                path = os.path.join(folder, name)
                with open(path, "rb") as handle:
                    found[os.path.relpath(path, self.repo)] = handle.read()
        return found


class OfferTest(InstallCase):
    def test_each_lockfile_gives_its_command(self):
        cases = {
            "package-lock.json": ("npm", ["npm", "install", "--save-dev", "--include=dev", "--ignore-scripts"]),
            "npm-shrinkwrap.json": ("npm", ["npm", "install", "--save-dev", "--include=dev", "--ignore-scripts"]),
            "yarn.lock": ("yarn", ["yarn", "add", "--dev", "--ignore-scripts"]),
            "pnpm-lock.yaml": ("pnpm", ["pnpm", "add", "--save-dev", "--ignore-scripts"]),
            "bun.lock": ("bun", ["bun", "add", "--dev", "--ignore-scripts"]),
            "bun.lockb": ("bun", ["bun", "add", "--dev", "--ignore-scripts"]),
        }
        for lockfile, (manager, argv) in cases.items():
            with self.subTest(lockfile=lockfile):
                self.package()
                for name in os.listdir(self.repo):
                    if name != "package.json":
                        os.remove(os.path.join(self.repo, name))
                self.write(lockfile, "")
                out = self.offer()
                self.assertTrue(out["ok"])
                self.assertTrue(out["offer"])
                self.assertEqual(out["package_manager"], manager)
                self.assertEqual(out["command"], argv + PACKAGES)
                self.assertEqual(out["packages"], PACKAGES)

    def test_the_offer_writes_nothing(self):
        self.package()
        self.write("yarn.lock", "")
        before = self.snapshot()
        self.assertTrue(self.offer()["offer"])
        self.assertEqual(self.snapshot(), before)

    def test_a_new_config_and_the_diffs(self):
        self.package()
        self.write("package-lock.json", "{}")
        out = self.offer("--tags", "sql,this.sql,tx")
        self.assertEqual(out["config"]["file"], ".prettierrc.json")
        self.assertEqual(out["config"]["action"], "create")
        self.assertIn('+  "language": "postgresql"', out["config"]["diff"])
        self.assertIn('"embeddedSqlTags"', out["config"]["diff"])
        for name in PACKAGES:
            self.assertIn(name, out["package_json_diff"])
        self.assertIn(PLACEHOLDER, out["package_json_diff"])
        new = {
            "plugins": ["prettier-plugin-embed", "prettier-plugin-sql"],
            "language": "postgresql",
            "embeddedSqlTags": ["sql", "this.sql", "tx"],
        }
        text = json.dumps(new, indent=2) + "\n"
        digest = hashlib.sha256(
            json.dumps(
                {"config_file": ".prettierrc.json", "config_text": text, "command": out["command"]},
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(out["digest"], digest)

    def test_a_config_that_lacks_one_plugin_installs_only_the_missing_packages(self):
        self.package(dev=["prettier", "prettier-plugin-embed"])
        self.write("package-lock.json", "{}")
        self.write(".prettierrc.json", json.dumps({"semi": False, "plugins": ["prettier-plugin-embed"]}))
        out = self.offer()
        self.assertEqual(out["packages"], ["prettier-plugin-sql"])
        self.assertEqual(out["config"]["action"], "edit")
        self.assertEqual(out["command"][-1], "prettier-plugin-sql")

    def test_the_tag_option_is_extended_only_when_a_tag_is_missing(self):
        self.package()
        self.write("package-lock.json", "{}")
        self.write(".prettierrc.json", json.dumps({"embeddedSqlTags": ["sql", "db"]}, indent=2) + "\n")
        self.assertIn("this.sql", self.offer("--tags", "sql,this.sql")["config"]["diff"])
        out = self.offer("--tags", "sql,db")
        self.assertNotIn("embeddedSqlTags", "\n".join(line for line in out["config"]["diff"].splitlines() if line.startswith("+")))

    def test_a_prettier_key_in_package_json(self):
        self.package(extra={"prettier": {"semi": False}})
        self.write("package-lock.json", "{}")
        out = self.offer()
        self.assertEqual(out["config"]["file"], "package.json")
        self.assertEqual(out["config"]["action"], "edit")

    def test_no_offer_cases(self):
        def clean():
            for name in os.listdir(self.repo):
                os.remove(os.path.join(self.repo, name))

        def no_package():
            pass

        def no_lockfile():
            self.package()

        def two_lockfiles():
            self.package()
            self.write("yarn.lock", "")
            self.write("package-lock.json", "{}")

        def other_language():
            self.package()
            self.write("yarn.lock", "")
            self.write(".prettierrc.json", json.dumps({"language": "mysql"}))

        def yaml_config():
            self.package()
            self.write("yarn.lock", "")
            self.write(".prettierrc.yaml", "semi: false\n")

        def an_earlier_non_json_source_wins_over_a_json_config():
            self.package()
            self.write("yarn.lock", "")
            self.write("package.yaml", "prettier:\n  semi: false\n")
            self.write(".prettierrc.json", "{}")

        def package_key_not_an_object():
            self.package(extra={"prettier": "shared-config"})
            self.write("yarn.lock", "")

        def broken_package():
            self.write("package.json", "{not json")
            self.write("yarn.lock", "")

        def safe_tool():
            self.package(dev=PACKAGES)
            self.write("yarn.lock", "")
            self.write(
                ".prettierrc.json",
                json.dumps({"plugins": ["prettier-plugin-embed", "prettier-plugin-sql"], "language": "postgresql"}),
            )

        for case in (
            no_package, no_lockfile, two_lockfiles, other_language, yaml_config,
            an_earlier_non_json_source_wins_over_a_json_config, package_key_not_an_object, broken_package, safe_tool,
        ):
            with self.subTest(case=case.__name__):
                clean()
                case()
                out = self.offer()
                self.assertTrue(out["ok"])
                self.assertFalse(out["offer"])
                self.assertTrue(out["reason"])
                self.assertEqual(sorted(out), ["offer", "ok", "reason"])

    def test_all_packages_present_needs_no_lockfile_and_no_command(self):
        self.package(dev=PACKAGES)
        out = self.offer()
        self.assertTrue(out["offer"])
        self.assertEqual(out["packages"], [])
        self.assertIsNone(out["command"])
        self.assertIsNone(out["package_manager"])
        self.assertIsNone(out["package_json_diff"])
        self.assertEqual(out["config"]["file"], ".prettierrc.json")

    def test_usage_errors(self):
        for args in ([], ["offer"], ["bogus", self.repo], ["offer", self.repo, "--tags", ""], ["apply", self.repo],
                     ["offer", os.path.join(self.repo, "none")]):
            with self.subTest(args=args):
                code, out, err = run(*args, env=self.env)
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertEqual(len(err.strip().splitlines()), 1)


class LineEndTest(InstallCase):
    def test_a_crlf_config_keeps_its_line_ends(self):
        self.package()
        self.write("package-lock.json", "{}")
        with open(os.path.join(self.repo, ".prettierrc.json"), "wb") as handle:
            handle.write(b'{\r\n  "semi": false\r\n}\r\n')
        self.fake("npm")
        offer = self.offer()
        self.command("apply", self.repo, "--confirm", offer["digest"])
        with open(os.path.join(self.repo, ".prettierrc.json"), "rb") as handle:
            raw = handle.read()
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertIn(b"\r\n", raw)

    def test_a_crlf_package_json_with_a_prettier_key_keeps_its_line_ends(self):
        with open(os.path.join(self.repo, "package.json"), "wb") as handle:
            handle.write(b'{\r\n  "name": "x",\r\n  "prettier": {"semi": false}\r\n}\r\n')
        self.write("package-lock.json", "{}")
        path = os.path.join(self.bin, "npm")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\nexit 0\n")
        os.chmod(path, 0o755)
        offer = self.offer()
        self.assertEqual(offer["config"]["file"], "package.json")
        self.assertIn("\r\n", offer["config"]["diff"])
        self.command("apply", self.repo, "--confirm", offer["digest"], code=1)
        with open(os.path.join(self.repo, "package.json"), "rb") as handle:
            raw = handle.read()
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))


class ApplyTest(InstallCase):
    def apply(self, digest, *extra, code=0):
        return self.command("apply", self.repo, "--confirm", digest, *extra, code=code)

    def test_apply_runs_the_manager_without_node_env_and_the_detector_then_chooses(self):
        self.package()
        self.write("package-lock.json", "{}")
        self.fake("npm")
        offer = self.offer("--tags", "sql")
        out = self.apply(offer["digest"], "--tags", "sql")
        self.assertTrue(out["ok"])
        self.assertEqual(out["chosen"], "prettier-plugin-embed")
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertIn("--ignore-scripts", calls[0]["argv"])
        self.assertIsNone(calls[0]["node_env"])
        self.assertEqual(os.path.realpath(calls[0]["cwd"]), os.path.realpath(self.repo))
        config = json.loads(self.read(".prettierrc.json"))
        self.assertEqual(config["language"], "postgresql")

    def test_a_failing_manager_puts_the_config_back_byte_for_byte(self):
        self.package()
        self.write("yarn.lock", "")
        self.write(".prettierrc.json", '{ "semi": false }\n')
        self.fake("yarn")
        self.env["FAKE_FAIL"] = "1"
        offer = self.offer()
        before = self.snapshot()
        out = self.apply(offer["digest"], code=1)
        self.assertFalse(out["ok"])
        self.assertIn("boom two", out["message"])
        self.assertEqual(self.snapshot(), before)

    def test_a_failing_manager_removes_a_created_config(self):
        self.package()
        self.write("yarn.lock", "")
        self.fake("yarn")
        self.env["FAKE_FAIL"] = "1"
        offer = self.offer()
        before = self.snapshot()
        self.apply(offer["digest"], code=1)
        self.assertEqual(self.snapshot(), before)

    def test_a_wrong_digest_runs_nothing(self):
        self.package()
        self.write("package-lock.json", "{}")
        self.fake("npm")
        before = self.snapshot()
        out = self.apply("0" * 64, code=1)
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "stale_digest")
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.snapshot(), before)

    def test_a_stale_digest_after_a_config_edit_runs_nothing(self):
        self.package()
        self.write("package-lock.json", "{}")
        self.fake("npm")
        offer = self.offer()
        self.write(".prettierrc.json", '{"semi": true}\n')
        out = self.apply(offer["digest"], code=1)
        self.assertEqual(out["reason"], "stale_digest")
        self.assertEqual(self.calls(), [])

    def test_all_packages_present_apply_writes_the_config_and_runs_no_command(self):
        self.package(dev=PACKAGES)
        self.fake("npm")
        offer = self.offer()
        out = self.apply(offer["digest"])
        self.assertTrue(out["ok"])
        self.assertEqual(out["chosen"], "prettier-plugin-embed")
        self.assertEqual(self.calls(), [])
        self.assertTrue(os.path.exists(os.path.join(self.repo, ".prettierrc.json")))

    def test_a_detector_that_still_says_none_is_ok_false_and_the_config_stays(self):
        self.package()
        self.write("package-lock.json", "{}")
        self.fake("npm")
        # the fake adds only some packages: a manager that installs nothing leaves the detector at none
        path = os.path.join(self.bin, "npm")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\nexit 0\n")
        offer = self.offer()
        out = self.apply(offer["digest"], code=1)
        self.assertFalse(out["ok"])
        self.assertTrue(out["reason"])
        self.assertTrue(os.path.exists(os.path.join(self.repo, ".prettierrc.json")))

    @unittest.skipIf(os.geteuid() == 0, "root ignores the file mode")
    def test_a_config_that_cannot_be_written_is_ok_false_with_a_message(self):
        self.package(dev=PACKAGES)
        self.write(".prettierrc.json", "{}")
        path = os.path.join(self.repo, ".prettierrc.json")
        os.chmod(path, 0o444)
        self.addCleanup(os.chmod, path, 0o644)
        offer = self.offer()
        out = self.apply(offer["digest"], code=1)
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "write_failed")
        self.assertTrue(out["message"])
        self.assertEqual(self.read(".prettierrc.json"), "{}")

    def test_apply_with_no_offer_is_ok_false(self):
        out = self.apply("0" * 64, code=1)
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "no_offer")


class RoundThreeInstallTest(InstallCase):
    def test_the_dump_follows_the_first_line_end_of_the_old_text(self):
        sys.path.insert(0, os.path.dirname(SCRIPT))
        import formatter_install

        mixed = formatter_install.dump({"a": 1, "b": 2}, '{\n  "a": 1,\r\n  "b": 2\n}\n')
        self.assertNotIn("\r", mixed)
        crlf = formatter_install.dump({"a": 1, "b": 2}, '{\r\n  "a": 1,\n  "b": 2\r\n}\r\n')
        self.assertTrue(crlf.startswith("{\r\n"))
        self.assertNotIn("\n", crlf.replace("\r\n", ""))

    def test_a_put_back_that_fails_after_a_failed_install_is_ok_false_and_names_the_file(self):
        from unittest import mock

        sys.path.insert(0, os.path.dirname(SCRIPT))
        import formatter_install

        self.package()
        self.write("yarn.lock", "")
        self.write(".prettierrc.json", '{ "semi": false }\n')
        self.fake("yarn")
        self.env["FAKE_FAIL"] = "1"
        offer = self.offer()
        with mock.patch.dict(os.environ, self.env), mock.patch.object(formatter_install, "put_back", side_effect=OSError("denied")):
            out = formatter_install.apply(self.repo, offer["digest"], None)
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "install_failed")
        self.assertIn(".prettierrc.json", out["message"])
        self.assertIn("denied", out["message"])


if __name__ == "__main__":
    unittest.main()
