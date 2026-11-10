import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL_DIR, "scripts")
SCRIPT = os.path.join(SCRIPTS, "setup_files.py")
sys.path.insert(0, SCRIPTS)

KEY = "example.com/acme/shop"
RULES = os.path.join("docs", "agents", "sql.md")

PROPOSAL = {
    "settings": {
        "style": {
            "keyword_case": "upper", "indent": "2 spaces", "clause_per_line": True,
            "comma": "trailing", "alias_as": True,
        },
        "formatter": {"tool": "none"},
        "sources": {"tags": ["sql"]},
        "rules": {"disabled": []},
    },
    "prose_rules": ["Name every column."],
    "services": ["app-dev"],
}

NEW_RULES = """\
# SQL rules

```toml
[style]
keyword_case = "upper"
indent = "2 spaces"
clause_per_line = true
comma = "trailing"
alias_as = true

[formatter]
tool = "none"

[sources]
tags = ["sql"]

[rules]
disabled = []
```

## Repo rules

- Name every column.
"""

NEW_ALLOWLIST = '["example.com/acme/shop"]\nservices = ["app-dev"]\n'

OLD_RULES = """\
# SQL rules

```toml
# hand-written comment
[style]
keyword_case = "lower"
indent = "4 spaces"
clause_per_line = true
comma = "trailing"
alias_as = true

[formatter]
tool = "none"

[sources]
tags = ["sql"]

[rules]
disabled = []
```

## Repo rules

- Use CTEs for any query that joins more than 3 tables.
"""


class FilesCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.repo = os.path.join(self.tmp, "repo")
        self.home = os.path.join(self.tmp, "home")
        self.xdg = os.path.join(self.tmp, "xdg")
        self.work = os.path.join(self.tmp, "work")
        for folder in (self.repo, self.home, self.xdg, self.work):
            os.makedirs(folder)
        self.env = dict(
            os.environ, HOME=self.home, XDG_CONFIG_HOME=self.xdg,
            PGSERVICEFILE=os.path.join(self.tmp, "pg_service.conf"),
            PGPASSFILE=os.path.join(self.tmp, "pgpass"),
        )
        self.allowlist = os.path.join(self.xdg, "sql-skill", "allowlist.toml")
        self.git("init", "-q")
        self.git("remote", "add", "origin", "https://example.com/acme/shop.git")
        patcher = mock.patch.dict(os.environ, self.env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def git(self, *args):
        subprocess.run(["git", "-C", self.repo, *args], check=True, capture_output=True, env=self.env)

    def path(self, *parts):
        return os.path.join(self.repo, *parts)

    def write_rules(self, text, newline=None, bom=False):
        os.makedirs(self.path("docs", "agents"), exist_ok=True)
        if newline:
            text = text.replace("\n", newline)
        with open(self.path(RULES), "wb") as handle:
            handle.write((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))

    def read_rules_bytes(self):
        with open(self.path(RULES), "rb") as handle:
            return handle.read()

    def write_allowlist(self, text):
        os.makedirs(os.path.dirname(self.allowlist), exist_ok=True)
        with open(self.allowlist, "w", encoding="utf-8") as handle:
            handle.write(text)

    def proposal(self, **changes):
        data = json.loads(json.dumps(PROPOSAL))
        for name, value in changes.items():
            if value is None:
                data.pop(name, None)
            else:
                data[name] = value
        path = os.path.join(self.work, "proposal.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        return path

    def run_script(self, *args):
        result = subprocess.run([sys.executable, "-I", SCRIPT, *args], capture_output=True, text=True, env=self.env)
        return result.returncode, result.stdout, result.stderr

    def command(self, *args, code=0):
        got, out, err = self.run_script(*args)
        self.assertEqual(got, code, (out, err))
        return json.loads(out)

    def plan(self, proposal=None, code=0):
        return self.command("plan", self.repo, "--proposal", proposal or self.proposal(), code=code)

    def write(self, digest, proposal=None, code=0):
        return self.command("write", self.repo, "--proposal", proposal or self.proposal(), "--confirm", digest, code=code)

    def snapshot(self):
        found = {}
        for folder, dirs, files in os.walk(self.tmp):
            if ".git" in dirs:
                dirs.remove(".git")
            if folder == self.tmp and "work" in dirs:
                dirs.remove("work")  # the proposal file is the input, not an output
            for name in files:
                path = os.path.join(folder, name)
                with open(path, "rb") as handle:
                    found[os.path.relpath(path, self.tmp)] = handle.read()
        return found


class NewFilesTest(FilesCase):
    def test_a_new_repo_gives_the_expected_texts(self):
        plan = self.plan()
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["rules_file"]["text"], NEW_RULES)
        self.assertFalse(plan["rules_file"]["exists"])
        self.assertTrue(plan["rules_file"]["changed"])
        self.assertEqual(plan["allowlist"]["text"], NEW_ALLOWLIST)
        self.assertEqual(plan["allowlist"]["key"], KEY)
        self.assertEqual(plan["allowlist"]["path"], self.allowlist)
        self.assertEqual(plan["conflicts"], [])
        self.assertEqual(plan["appended_rules"], ["Name every column."])
        self.assertEqual(plan["skipped_rules"], [])
        self.assertIn("+- Name every column.", plan["rules_file"]["diff"])
        self.assertIn('+services = ["app-dev"]', plan["allowlist"]["diff"])

    def test_the_digest_is_the_sha256_of_the_new_texts(self):
        plan = self.plan()
        body = json.dumps(
            {"files": [{"path": RULES, "text": NEW_RULES}, {"path": self.allowlist, "text": NEW_ALLOWLIST}]},
            sort_keys=True,
        )
        self.assertEqual(plan["digest"], hashlib.sha256(body.encode("utf-8")).hexdigest())

    def test_a_new_file_has_every_section_with_defaults(self):
        proposal = self.proposal(settings={"sources": {"tags": ["sql", "tx"]}}, services=None, prose_rules=None)
        text = self.plan(proposal)["rules_file"]["text"]
        reader = subprocess.run(
            [sys.executable, "-I", os.path.join(SCRIPTS, "rules_file.py"), self.repo], capture_output=True, text=True
        )
        self.assertIn('keyword_case = "upper"', text)
        self.assertIn('tool = "none"', text)
        self.assertIn('tags = ["sql", "tx"]', text)
        self.assertIn("disabled = []", text)
        self.assertEqual(reader.returncode, 0)
        self.write_rules(text)
        read = json.loads(
            subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "rules_file.py"), self.repo], capture_output=True, text=True).stdout
        )
        self.assertEqual(read["missing_sections"], [])
        self.assertEqual(read["settings"]["sources"]["tags"], ["sql", "tx"])

    def test_the_written_files_are_read_back_by_the_readers(self):
        plan = self.plan()
        self.assertTrue(self.write(plan["digest"])["ok"])
        rules = json.loads(subprocess.run(
            [sys.executable, "-I", os.path.join(SCRIPTS, "rules_file.py"), self.repo], capture_output=True, text=True, env=self.env
        ).stdout)
        self.assertIsNone(rules["error"])
        self.assertEqual(rules["settings"]["style"]["indent"], "2 spaces")
        allow = json.loads(subprocess.run(
            [sys.executable, "-I", os.path.join(SCRIPTS, "allowlist.py"), self.repo], capture_output=True, text=True, env=self.env
        ).stdout)
        self.assertTrue(allow["access"])
        self.assertEqual(allow["services"], ["app-dev"])
        self.assertEqual(allow["key"], KEY)

    def test_write_modes(self):
        self.write(self.plan()["digest"])
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(self.allowlist)).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(self.allowlist).st_mode), 0o600)

    def test_everything_is_written_below_the_two_temp_folders(self):
        before = self.snapshot()
        self.write(self.plan()["digest"])
        new = set(self.snapshot()) - set(before)
        self.assertEqual(
            new, {os.path.relpath(self.path(RULES), self.tmp), os.path.relpath(self.allowlist, self.tmp)}
        )
        self.assertEqual(os.listdir(self.home), [])

    def test_a_relative_xdg_config_home_counts_as_unset(self):
        self.env["XDG_CONFIG_HOME"] = "relative/dir"
        plan = self.plan()
        self.assertEqual(plan["allowlist"]["path"], os.path.join(self.home, ".config", "sql-skill", "allowlist.toml"))

    def test_no_services_key_or_an_empty_list_has_no_allowlist(self):
        for services in (None, []):
            with self.subTest(services=services):
                plan = self.plan(self.proposal(services=services))
                self.assertNotIn("allowlist", plan)
                body = json.dumps({"files": [{"path": RULES, "text": NEW_RULES}]}, sort_keys=True)
                self.assertEqual(plan["digest"], hashlib.sha256(body.encode("utf-8")).hexdigest())

    def test_a_folder_that_is_not_a_git_repo_is_ok_false_for_an_allowlist(self):
        folder = os.path.join(self.tmp, "plain")
        os.makedirs(folder)
        out = self.command("plan", folder, "--proposal", self.proposal(), code=1)
        self.assertFalse(out["ok"])


class SafetyTest(FilesCase):
    def test_plan_and_a_refused_write_change_nothing(self):
        before = self.snapshot()
        plan = self.plan()
        self.assertEqual(self.snapshot(), before)
        refused = self.write("0" * 64, code=1)
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["reason"], "stale_digest")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(plan["digest"]), 64)

    def test_write_with_the_right_digest_writes_both(self):
        out = self.write(self.plan()["digest"])
        self.assertTrue(out["ok"])
        self.assertEqual(self.read_rules_bytes().decode(), NEW_RULES)
        with open(self.allowlist, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), NEW_ALLOWLIST)

    def test_a_file_edited_after_the_plan_makes_the_digest_stale(self):
        self.write_rules(OLD_RULES)
        digest = self.plan()["digest"]
        self.write_rules(OLD_RULES + "- Added by hand.\n")
        before = self.snapshot()
        out = self.write(digest, code=1)
        self.assertEqual(out["reason"], "stale_digest")
        self.assertEqual(self.snapshot(), before)

    def test_a_failing_second_replace_puts_the_first_file_back(self):
        import setup_files

        self.write_rules(OLD_RULES)
        before = self.snapshot()
        real = os.replace
        calls = []

        def failing(source, target):
            calls.append(target)
            if len(calls) == 2:
                raise OSError("disk full")
            return real(source, target)

        proposal = self.proposal()
        plan = self.plan(proposal)
        with open(proposal, encoding="utf-8") as handle:
            data = json.load(handle)
        with mock.patch("setup_files.os.replace", failing):
            out = setup_files.write(self.repo, data, plan["digest"])
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "write_failed")
        self.assertEqual(self.snapshot(), before)

    def test_a_failing_temp_write_leaves_no_temp_file_and_no_new_folder(self):
        import setup_files

        proposal = self.proposal()
        plan = self.plan(proposal)
        with open(proposal, encoding="utf-8") as handle:
            data = json.load(handle)
        before = self.snapshot()
        real_chmod = os.chmod

        def failing_chmod(path, mode, *args, **kwargs):
            if mode == 0o600:
                raise OSError(28, "no space")
            return real_chmod(path, mode, *args, **kwargs)

        with mock.patch("setup_files.os.chmod", failing_chmod):
            self.write_rules(OLD_RULES)
            before = self.snapshot()
            plan = self.plan(proposal)
            out = setup_files.write(self.repo, data, plan["digest"])
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "write_failed")
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(os.path.exists(os.path.dirname(self.allowlist)))

    @unittest.skipIf(os.geteuid() == 0, "root ignores the folder mode")
    def test_a_read_only_folder_gives_write_failed_and_changes_nothing(self):
        self.write_rules(OLD_RULES)
        digest = self.plan()["digest"]
        before = self.snapshot()
        folder = self.path("docs", "agents")
        os.chmod(folder, 0o500)
        self.addCleanup(os.chmod, folder, 0o700)
        out = self.write(digest, code=1)
        self.assertEqual(out["reason"], "write_failed")
        self.assertTrue(out["message"])
        os.chmod(folder, 0o700)
        self.assertEqual(self.snapshot(), before)

    def test_a_malformed_rules_file_is_ok_false_and_writes_nothing(self):
        self.write_rules("# SQL rules\n\n```toml\n[style\nx = 1\n```\n")
        before = self.snapshot()
        out = self.plan(code=1)
        self.assertFalse(out["ok"])
        self.assertTrue(out["error"]["message"])
        self.write("0" * 64, code=1)
        self.assertEqual(self.snapshot(), before)

    def test_a_malformed_allowlist_is_ok_false_and_writes_nothing(self):
        self.write_allowlist("this is = = not toml\n")
        before = self.snapshot()
        out = self.plan(code=1)
        self.assertFalse(out["ok"])
        self.write("0" * 64, code=1)
        self.assertEqual(self.snapshot(), before)

    def test_usage_errors(self):
        bad = os.path.join(self.work, "bad.json")
        with open(bad, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        cases = [
            [],
            ["bogus"],
            ["plan", self.repo],
            ["plan", self.repo, "--proposal", bad],
            ["plan", self.repo, "--proposal", os.path.join(self.work, "missing.json")],
            ["plan", os.path.join(self.tmp, "none"), "--proposal", self.proposal()],
            ["write", self.repo, "--proposal", self.proposal()],
            ["services"],
            ["services", "bad name"],
            ["services", "a/b"],
        ]
        for extra in (
            {"services": ["bad name"]}, {"services": "app-dev"}, {"prose_rules": "text"},
            {"prose_rules": ["two\nlines"]}, {"settings": {"style": "x"}}, {"settings": {"other": {"a": 1}}},
            {"settings": {"style": {"a": {"b": 1}}}}, {"settings": []},
        ):
            cases.append(["plan", self.repo, "--proposal", self.proposal(**extra)])
        for args in cases:
            with self.subTest(args=args[:1] + args[2:]):
                code, out, err = self.run_script(*args)
                self.assertEqual(code, 2, (out, err))
                self.assertEqual(out, "")
                self.assertEqual(len(err.strip().splitlines()), 1)


class RerunTest(FilesCase):
    def rerun_proposal(self, **style):
        settings = json.loads(json.dumps(PROPOSAL["settings"]))
        settings["style"].update(keyword_case="lower", indent="4 spaces")
        settings["style"].update(style)
        return self.proposal(settings=settings, services=None, prose_rules=["Never build SQL with string concatenation."])

    def test_a_differing_key_is_a_conflict_and_only_it_is_replaced(self):
        self.write_rules(OLD_RULES)
        out = self.plan(self.rerun_proposal(indent="2 spaces"))
        self.assertEqual(
            out["conflicts"],
            [{"target": "rules_file", "section": "style", "key": "indent", "current": "4 spaces", "proposed": "2 spaces"}],
        )
        new = out["rules_file"]["text"]
        old_lines = OLD_RULES.splitlines()
        new_lines = new.splitlines()
        self.assertIn('indent = "2 spaces"', new_lines)
        self.assertNotIn('indent = "4 spaces"', new_lines)
        self.assertEqual([line for line in old_lines if line != 'indent = "4 spaces"'],
                         [line for line in new_lines if line not in ('indent = "2 spaces"', "- Never build SQL with string concatenation.")])
        self.assertEqual(out["appended_rules"], ["Never build SQL with string concatenation."])

    def test_a_kept_value_is_no_conflict_and_a_hand_comment_survives(self):
        self.write_rules(OLD_RULES)
        out = self.plan(self.rerun_proposal(keyword_case="lower", indent="4 spaces"))
        self.assertEqual(out["conflicts"], [])
        self.assertIn("# hand-written comment", out["rules_file"]["text"])
        self.assertEqual(out["rules_file"]["changed"], True)  # only the appended rule
        self.assertEqual(out["rules_file"]["text"].count("keyword_case"), 1)

    def test_prose_rules_are_appended_after_the_last_bullet_and_a_duplicate_is_skipped(self):
        self.write_rules(OLD_RULES + "\n## Notes\n\nSome notes.\n")
        out = self.plan(self.proposal(
            settings={"style": {"keyword_case": "lower", "indent": "4 spaces"}}, services=None,
            prose_rules=["Use CTEs for any query that joins more than 3 tables.", "New one.", "New one."],
        ))
        self.assertEqual(out["skipped_rules"], ["Use CTEs for any query that joins more than 3 tables."])
        self.assertEqual(out["appended_rules"], ["New one."])
        lines = out["rules_file"]["text"].splitlines()
        self.assertEqual(lines[lines.index("- Use CTEs for any query that joins more than 3 tables.") + 1], "- New one.")
        self.assertEqual(out["rules_file"]["text"].count("- New one."), 1)
        self.assertLess(lines.index("- New one."), lines.index("## Notes"))

    def test_a_heading_is_added_when_the_file_has_no_repo_rules_section(self):
        self.write_rules("# SQL rules\n\n```toml\n[style]\nindent = \"4 spaces\"\n```\n")
        out = self.plan(self.proposal(settings={"style": {"indent": "4 spaces"}}, services=None, prose_rules=["Rule one."]))
        self.assertTrue(out["rules_file"]["text"].endswith("\n## Repo rules\n\n- Rule one.\n"))

    def test_missing_keys_and_sections_are_added(self):
        self.write_rules("# SQL rules\n\n```toml\n[style]\nindent = \"4 spaces\"\n```\n")
        out = self.plan(self.proposal(
            settings={"style": {"indent": "4 spaces", "comma": "leading"}, "sources": {"tags": ["sql"]}},
            services=None, prose_rules=None,
        ))
        self.assertEqual(out["conflicts"], [])
        text = out["rules_file"]["text"]
        self.assertIn('indent = "4 spaces"\ncomma = "leading"\n\n[sources]\ntags = ["sql"]\n```', text)

    def test_a_hash_line_in_a_fence_or_a_comment_is_no_heading(self):
        cases = {
            "backtick fence": "```sh\n# install\nfoo\n```\n\n## Repo rules\n\n- a\n",
            "tilde fence": "~~~sh\n# install\nfoo\n~~~\n\n## Repo rules\n\n- a\n",
            "html comment": "<!--\n# hidden\n-->\n\nSome prose.\n\n## Repo rules\n\n- a\n",
        }
        for name, text in cases.items():
            with self.subTest(case=name):
                self.write_rules(text)
                out = self.plan(self.proposal(
                    settings={"style": {"keyword_case": "upper"}}, services=None, prose_rules=["no x"],
                ))
                new = out["rules_file"]["text"]
                self.assertTrue(out["ok"])
                # every old line is kept in order and the toml block sits outside the old fence or comment
                position = 0
                lines = new.split("\n")
                for line in text.split("\n"):
                    position = lines.index(line, position) + 1
                block = lines.index("```toml")
                before = lines[:block]
                self.assertEqual(sum(1 for l in before if l.startswith(("```", "~~~"))) % 2, 0)
                self.assertEqual(sum(1 for l in before if l.startswith("<!--")) - sum(1 for l in before if l.endswith("-->")), 0)
                self.assertIn("- no x", lines)

    def test_a_file_with_no_toml_block_gets_one_after_its_first_heading(self):
        self.write_rules("# SQL rules\n\nSome prose.\n")
        out = self.plan(self.proposal(services=None, prose_rules=None))
        self.assertTrue(out["rules_file"]["text"].startswith("# SQL rules\n\n```toml\n[style]\n"))
        self.assertIn("```\n\nSome prose.\n", out["rules_file"]["text"])

    def test_empty_tags_with_detected_tags_is_a_conflict(self):
        self.write_rules(OLD_RULES.replace('tags = ["sql"]', "tags = []"))
        out = self.plan(self.proposal(services=None, prose_rules=None, settings={"sources": {"tags": ["sql", "tx"]}}))
        self.assertEqual(
            out["conflicts"],
            [{"target": "rules_file", "section": "sources", "key": "tags", "current": [], "proposed": ["sql", "tx"]}],
        )

    def test_old_lines_survive_for_each_line_end_a_bom_and_a_multi_line_value(self):
        multi = OLD_RULES.replace('tags = ["sql"]', 'tags = [\n  "sql",\n  "tx",\n]')
        cases = {
            "lf": dict(text=OLD_RULES),
            "crlf": dict(text=OLD_RULES, newline="\r\n"),
            "bom": dict(text=OLD_RULES, bom=True),
            "multi-line value": dict(text=multi),
            "multi-line value crlf": dict(text=multi, newline="\r\n"),
        }
        for name, kwargs in cases.items():
            with self.subTest(case=name):
                self.write_rules(**kwargs)
                old = self.read_rules_bytes()
                proposal = self.proposal(
                    settings={"style": {"indent": "2 spaces"}, "sources": {"tags": ["sql", "db"]}},
                    services=None, prose_rules=["Added rule."],
                )
                plan = self.plan(proposal)
                self.assertTrue(self.write(plan["digest"], proposal)["ok"])
                new = self.read_rules_bytes()
                self.assertEqual(new.startswith(b"\xef\xbb\xbf"), old.startswith(b"\xef\xbb\xbf"))
                eol = b"\r\n" if kwargs.get("newline") else b"\n"
                old_lines = old.split(eol)
                new_lines = new.split(eol)
                replaced = {b'indent = "4 spaces"', b"tags = [", b'  "sql",', b'  "tx",', b"]", b'tags = ["sql"]'}
                kept = [line for line in old_lines if line not in replaced]
                position = 0
                for line in kept:
                    position = new_lines.index(line, position) + 1
                self.assertIn(b'indent = "2 spaces"', new_lines)
                self.assertIn(b'tags = ["sql", "db"]', new_lines)

    def test_a_disabled_id_with_no_reason_line_is_a_warning(self):
        self.write_rules(OLD_RULES)
        out = self.plan(self.proposal(
            settings={"style": {"keyword_case": "lower", "indent": "4 spaces"}, "rules": {"disabled": ["PG-08"]}},
            services=None, prose_rules=None,
        ))
        self.assertEqual([w for w in out["warnings"] if "PG-08" in w][:1] != [], True)
        out = self.plan(self.proposal(
            settings={"style": {"keyword_case": "lower", "indent": "4 spaces"}, "rules": {"disabled": ["PG-08"]}},
            services=None, prose_rules=["PG-08: this repo selects star on purpose."],
        ))
        self.assertEqual([w for w in out["warnings"] if "PG-08" in w], [])


class AllowlistTest(FilesCase):
    OTHER = '# keep me\n["github.com/other/repo"]\nservices = ["x"]\n'

    def test_another_key_and_a_comment_stay_byte_for_byte(self):
        self.write_allowlist(self.OTHER)
        out = self.plan()
        text = out["allowlist"]["text"]
        self.assertTrue(text.startswith(self.OTHER))
        self.assertTrue(text.endswith('["example.com/acme/shop"]\nservices = ["app-dev"]\n'))

    def test_an_existing_entry_is_replaced_and_its_timeouts_stay_for_remaining_services(self):
        self.write_allowlist(
            self.OTHER + '\n["example.com/acme/shop"]\nservices = ["app-dev", "old"]\n\n'
            '["example.com/acme/shop".timeouts."app-dev"]\nstatement_timeout = "30s"\n\n# tail comment\n["z/z"]\nservices = ["q"]\n'
        )
        out = self.plan()
        text = out["allowlist"]["text"]
        self.assertTrue(text.startswith(self.OTHER))
        self.assertIn('services = ["app-dev"]', text)
        self.assertNotIn('"old"', text)
        self.assertIn('["example.com/acme/shop".timeouts."app-dev"]\nstatement_timeout = "30s"', text)
        self.assertIn('# tail comment\n["z/z"]\nservices = ["q"]\n', text)
        self.assertEqual(
            out["conflicts"],
            [{"target": "allowlist", "section": "entry", "key": "services", "current": ["app-dev", "old"], "proposed": ["app-dev"]}],
        )

    def test_dropping_a_service_with_a_timeouts_table_is_a_conflict(self):
        self.write_allowlist(
            '["example.com/acme/shop"]\nservices = ["app-dev", "old"]\n\n'
            '["example.com/acme/shop".timeouts."old"]\nlock_timeout = "5s"\n'
        )
        out = self.plan()
        self.assertIn(
            {"target": "allowlist", "section": "timeouts", "key": "old", "current": {"lock_timeout": "5s"}, "proposed": None},
            out["conflicts"],
        )
        self.assertNotIn("lock_timeout", out["allowlist"]["text"])

    def test_comments_inside_the_entry_survive_and_same_services_change_nothing(self):
        text = '# top\n["example.com/acme/shop"]\n# note about services\nservices = ["app-dev"]  # trailing\n\n# other\n["o/r"]\nservices = ["y"]\n'
        self.write_allowlist(text)
        out = self.plan()
        self.assertFalse(out["allowlist"]["changed"])
        self.assertEqual(out["allowlist"]["text"], text)

    def test_a_changed_services_list_keeps_the_comments_of_the_entry(self):
        text = '["example.com/acme/shop"]\n# note about services\nservices = ["old"]\n\n# other\n["o/r"]\nservices = ["y"]\n'
        self.write_allowlist(text)
        new = self.plan()["allowlist"]["text"]
        self.assertEqual(new, text.replace('services = ["old"]', 'services = ["app-dev"]'))

    def test_a_dropped_timeouts_table_keeps_the_comment_of_the_next_entry(self):
        text = (
            '["example.com/acme/shop"]\nservices = ["app-dev", "y"]\n\n'
            '["example.com/acme/shop".timeouts."y"]\nstatement_timeout = "5s"\n\n'
            '# note about other repo\n["other/repo"]\nservices = ["z"]\n'
        )
        self.write_allowlist(text)
        new = self.plan()["allowlist"]["text"]
        self.assertIn("# note about other repo\n[\"other/repo\"]", new)
        self.assertNotIn("statement_timeout", new)

    def test_the_same_services_change_nothing(self):
        self.write_allowlist(NEW_ALLOWLIST)
        out = self.plan()
        self.assertFalse(out["allowlist"]["changed"])
        self.assertEqual(out["allowlist"]["text"], NEW_ALLOWLIST)
        self.assertEqual(out["conflicts"], [])

    def test_a_crlf_allowlist_keeps_its_line_end(self):
        self.write_allowlist(self.OTHER)
        with open(self.allowlist, "wb") as handle:
            handle.write(self.OTHER.replace("\n", "\r\n").encode())
        text = self.plan()["allowlist"]["text"]
        self.assertTrue(text.replace("\r\n", "").find("\n") == -1)


class ServicesTest(FilesCase):
    def test_a_typo_and_a_missing_service_file(self):
        out = self.command("services", "app-dev", "app-dv")
        self.assertEqual(out["service_check"], {"service_file": "missing", "missing": ["app-dev", "app-dv"]})
        with open(self.env["PGSERVICEFILE"], "w", encoding="utf-8") as handle:
            handle.write("[app-dev]\nhost=localhost\npassword=topsecret\n")
        out = self.command("services", "app-dev", "app-dv")
        self.assertEqual(out["service_check"], {"service_file": "found", "missing": ["app-dv"]})
        self.assertNotIn("topsecret", json.dumps(out))

    def test_the_password_file_is_never_opened(self):
        os.mkfifo(self.env["PGPASSFILE"])
        with open(self.env["PGSERVICEFILE"], "w", encoding="utf-8") as handle:
            handle.write("[app-dev]\n")
        proposal = self.proposal()
        timer = threading.Timer(20, lambda: None)
        timer.cancel()
        for args in (("services", "app-dev"), ("plan", self.repo, "--proposal", proposal)):
            with self.subTest(args=args[0]):
                try:
                    done = subprocess.run(
                        [sys.executable, "-I", SCRIPT, *args], capture_output=True, text=True, env=self.env, timeout=20
                    )
                except subprocess.TimeoutExpired:
                    self.fail("the command blocked on the password file")
                self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_proposed_service_that_the_service_file_lacks_is_a_warning(self):
        plan = self.plan()
        self.assertTrue(any("app-dev" in w for w in plan["warnings"]))
        self.assertEqual(plan["service_check"]["missing"], ["app-dev"])
        with open(self.env["PGSERVICEFILE"], "w", encoding="utf-8") as handle:
            handle.write("[app-dev]\n")
        plan = self.plan()
        self.assertEqual(plan["warnings"], [])


if __name__ == "__main__":
    unittest.main()
