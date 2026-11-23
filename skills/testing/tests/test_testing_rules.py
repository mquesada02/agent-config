import os
import sys
import unittest

import helper_testing_rules as helper
from helper_testing_rules import FENCE, SECTIONS, block, doc

NOT_READ = "the settings cannot be read as JSON (nan, inf or nesting too deep)"


@unittest.skipUnless(sys.version_info >= (3, 11), "the script needs tomllib (Python 3.11 or newer)")
class RulesPartTest(unittest.TestCase):
    """The `rules` part of intake.py, run as a command on a temp repo folder."""

    def setUp(self):
        self.repo = helper.Repo()
        self.addCleanup(self.repo.close)

    def check(self, text, raw=False):
        self.repo.write(text, raw=raw)
        return helper.run_json(self.repo.root)

    def missing(self, **kwargs):
        rules, _, code = self.check(doc(block(**kwargs)))
        self.assertEqual(code, 0)
        self.assertIsNone(rules["error"])
        return rules["missing_sections"]

    def assert_error(self, rules, code, line, message_start):
        self.assertEqual(code, 1)
        self.assertTrue(rules["found"])
        self.assertEqual(rules["settings"], {})
        self.assertEqual(rules["missing_sections"], SECTIONS)
        self.assertEqual(rules["disabled_without_reason"], [])
        self.assertEqual(rules["unknown_ids"], [])
        self.assertEqual(rules["error"]["line"], line)
        self.assertTrue(rules["error"]["message"].startswith(message_start), rules["error"]["message"])

    def test_complete_file_has_nothing_missing(self):
        rules, detected, code = self.check(doc(helper.FULL_BLOCK))
        self.assertEqual(code, 0)
        self.assertEqual(
            detected["languages"],
            [
                {"name": "rust", "root": ".", "manifest": None},
                {"name": "typescript", "root": "web", "manifest": None},
            ],
        )
        self.assertEqual(detected["entries"], {})
        self.assertEqual(sorted(detected["facts"]), ["rust", "typescript"])
        self.assertTrue(rules["found"])
        self.assertEqual(rules["missing_sections"], [])
        self.assertEqual(rules["disabled_without_reason"], [])
        self.assertEqual(rules["unknown_ids"], [])
        self.assertIsNone(rules["error"])
        self.assertEqual(rules["settings"]["limits"], {"small_ms": 100})
        self.assertEqual([entry["name"] for entry in rules["settings"]["languages"]], ["rust", "typescript"])
        self.assertEqual(len(rules["settings"]["groups"]), 2)

    def test_absent_file(self):
        rules, detected, code = helper.run_json(self.repo.root)
        self.assertEqual(code, 0)
        self.assertEqual(detected, {"languages": [], "entries": {}, "facts": {}})
        self.assertEqual(
            rules,
            {
                "found": False,
                "settings": {},
                "missing_sections": SECTIONS,
                "disabled_without_reason": [],
                "unknown_ids": [],
                "error": None,
            },
        )

    def test_file_with_no_toml_block(self):
        rules, _, code = self.check("# Test rules\n\nOnly prose.\n")
        self.assertEqual(code, 0)
        self.assertTrue(rules["found"])
        self.assertEqual(rules["settings"], {})
        self.assertEqual(rules["missing_sections"], SECTIONS)
        self.assertIsNone(rules["error"])

    def test_each_required_section_absent_is_reported_once_by_name(self):
        drops = {
            "languages": ("languages",),
            "commands": ("commands.rust", "commands.typescript"),
            "groups": ("groups",),
            "runner": ("runner.rust", "runner.typescript"),
            "layout": ("layout.rust", "layout.typescript"),
            "libraries": ("libraries.rust", "libraries.typescript"),
        }
        for name, parts in drops.items():
            with self.subTest(name):
                self.assertEqual(self.missing(drop=parts), [name])

    def test_optional_sections_absent_are_not_missing(self):
        self.assertEqual(self.missing(drop=("limits", "rules")), [])

    def test_wrong_type_sections_are_reported_by_name_and_dropped(self):
        cases = {
            "commands": block(drop=("commands.rust", "commands.typescript"), top='commands = "x"\n'),
            "groups": block(replace={"groups": '[groups]\nname = "unit"\n'}),
            "languages": block(replace={"languages": '[languages]\nname = "rust"\n'}),
            "runner": block(drop=("runner.rust", "runner.typescript"), top="runner = 3\n"),
        }
        for name, text in cases.items():
            with self.subTest(name):
                rules, _, code = self.check(doc(text))
                self.assertEqual(code, 0)
                self.assertEqual(rules["missing_sections"], [name])
                self.assertNotIn(name, rules["settings"])

    def test_array_with_a_non_table_element_is_the_wrong_type(self):
        text = block(drop=("languages",), top='languages = [{ name = "rust" }, "x"]\n')
        rules, _, _ = self.check(doc(text))
        self.assertEqual(rules["missing_sections"], ["languages"])
        self.assertNotIn("languages", rules["settings"])

    def test_wrong_type_languages_counts_no_language(self):
        text = block(drop=("languages", "commands.rust"), top='languages = [{ name = "rust" }, "x"]\n')
        rules, _, _ = self.check(doc(text))
        self.assertEqual(rules["missing_sections"], ["languages"])

    def test_empty_languages_array_is_present(self):
        text = block(drop=("languages",), top="languages = []\n")
        self.assertEqual(self.check(doc(text))[0]["missing_sections"], [])

    def test_missing_per_language_key(self):
        for section in ("commands", "runner", "layout", "libraries"):
            with self.subTest(section):
                self.assertEqual(
                    self.missing(drop=(f"{section}.typescript",)), [f"{section}.typescript"]
                )

    def test_missing_sections_order(self):
        order = self.missing(drop=("commands.typescript", "groups", "libraries.rust"))
        self.assertEqual(order, ["commands.typescript", "groups", "libraries.rust"])
        self.assertEqual(self.missing(drop=("runner.rust", "groups")), ["groups", "runner.rust"])

    def test_per_language_section_with_a_gap_stays_in_settings(self):
        rules, _, _ = self.check(doc(block(drop=("commands.typescript",))))
        self.assertIn("commands", rules["settings"])

    def test_language_that_is_not_counted_is_ignored(self):
        only_rust = '[[languages]]\nname = "rust"\nroot = "."\n'
        self.assertEqual(self.missing(replace={"languages": only_rust}, drop=("commands.typescript",)), [])
        with_go = only_rust + '\n[[languages]]\nname = "go"\nroot = "go"\n'
        self.assertEqual(self.missing(replace={"languages": with_go}), [])

    def test_no_counted_language_without_languages_section(self):
        self.assertEqual(self.missing(drop=("languages", "commands.rust")), ["languages"])

    def test_commands_without_a_usable_test_key(self):
        cases = {
            "no test key": '[commands.rust]\nworker_flag = "-j2"\n',
            "empty test": '[commands.rust]\ntest = ""\n',
            "blank test": '[commands.rust]\ntest = "  "\n',
            "test not a string": "[commands.rust]\ntest = 5\n",
        }
        for label, text in cases.items():
            with self.subTest(label):
                self.assertEqual(self.missing(replace={"commands.rust": text}), ["commands.rust"])

    def test_language_entry_that_is_not_a_table(self):
        text = '[commands]\nrust = "cargo test"\n'
        found = self.missing(replace={"commands.rust": text, "commands.typescript": ""})
        self.assertEqual(found, ["commands.rust", "commands.typescript"])

    def test_absent_optional_key_is_not_missing(self):
        self.assertEqual(self.missing(replace={"runner.rust": "[runner.rust]\n"}), [])

    def test_malformed_toml(self):
        rules, _, code = self.check(doc("a = 1\nb = \n"))
        self.assert_error(rules, code, 5, "toml parse error: ")

    def test_no_closing_fence(self):
        rules, _, code = self.check("# Rules\n\n```toml\n[commands]\n")
        self.assert_error(rules, code, 3, "a toml block has no closing fence")

    def test_two_toml_blocks(self):
        text = doc(helper.FULL_BLOCK) + f"\n{FENCE}toml\n[x]\n{FENCE}\n"
        second = text.split("\n").index(f"{FENCE}toml", 3) + 1
        rules, _, code = self.check(text)
        self.assert_error(rules, code, second, "more than one toml block")

    def test_unclosed_second_block_is_a_second_block(self):
        text = doc(helper.FULL_BLOCK) + f"\n{FENCE}toml\n[x]\n"
        rules, _, code = self.check(text)
        self.assert_error(rules, code, text.split("\n").index(f"{FENCE}toml", 3) + 1, "more than one toml block")

    def test_unreadable_file(self):
        os.makedirs(os.path.join(self.repo.root, "docs", "agents", "testing.md"))
        rules, _, code = helper.run_json(self.repo.root)
        self.assert_error(rules, code, None, "cannot read docs/agents/testing.md")

    def test_dangling_symlink(self):
        path = os.path.join(self.repo.root, "docs", "agents", "testing.md")
        os.makedirs(os.path.dirname(path))
        os.symlink(os.path.join(self.repo.root, "no-such-target.md"), path)
        rules, _, code = helper.run_json(self.repo.root)
        self.assert_error(rules, code, None, "cannot read docs/agents/testing.md")
        self.assertTrue(rules["found"])
        self.assertEqual(rules["missing_sections"], helper.SECTIONS)

    def test_non_utf8_file(self):
        rules, _, code = self.check(b"\xff\xfe\x00 not utf-8", raw=True)
        self.assert_error(rules, code, None, "cannot read docs/agents/testing.md")

    def test_unwritable_settings_are_an_output_error(self):
        rules, detected, code = self.check(doc(block(top="bad = nan\n")))
        self.assert_error(rules, code, None, NOT_READ)
        self.assertEqual(detected, {"languages": [], "entries": {}, "facts": {}})

    def test_bom_and_crlf_are_read_as_normal(self):
        text = doc(helper.FULL_BLOCK)
        for label, raw in (
            ("bom", ("﻿" + text).encode("utf-8")),
            ("crlf", text.replace("\n", "\r\n").encode("utf-8")),
        ):
            with self.subTest(label):
                rules, _, code = self.check(raw, raw=True)
                self.assertEqual(code, 0)
                self.assertEqual(rules["missing_sections"], [])
                self.assertIsNone(rules["error"])

    def disabled(self, ids, prose_after="", inside=""):
        listed = ", ".join(f'"{item}"' for item in ids)
        text = block(replace={"rules": f"[rules]\ndisabled = [{listed}]\n{inside}"})
        rules, _, code = self.check(doc(text, prose_after=prose_after))
        self.assertEqual(code, 0)
        return rules

    def test_disabled_id_without_a_reason(self):
        rules = self.disabled(["RUN-02"])
        self.assertEqual(rules["disabled_without_reason"], ["RUN-02"])
        self.assertEqual(rules["unknown_ids"], [])

    def test_reason_line_forms(self):
        for line in (
            "- RUN-02: too slow here",
            "* RUN-02: too slow here",
            "RUN-02: too slow here",
            "  - RUN-02: too slow here",
            "- RUN-02— too slow here",
            "- RUN-02:too slow here",
        ):
            with self.subTest(line):
                self.assertEqual(self.disabled(["RUN-02"], prose_after=line + "\n")["disabled_without_reason"], [])

    def test_lines_that_are_not_a_reason(self):
        for line in (
            "- RUN-02:",
            "- RUN-02:   ",
            "- RUN-02 - too slow here",
            "- RUN-02 – too slow here",
            "RUN-02 too slow here",
            "see - RUN-02: too slow here",
        ):
            with self.subTest(line):
                found = self.disabled(["RUN-02"], prose_after=line + "\n")["disabled_without_reason"]
                self.assertEqual(found, ["RUN-02"])

    def test_reason_inside_the_toml_block_does_not_count(self):
        rules = self.disabled(["RUN-02"], inside="# RUN-02: too slow here\n")
        self.assertEqual(rules["disabled_without_reason"], ["RUN-02"])

    def test_reason_in_another_fenced_block_counts(self):
        prose = f"{FENCE}text\n- RUN-02: too slow here\n{FENCE}\n"
        self.assertEqual(self.disabled(["RUN-02"], prose_after=prose)["disabled_without_reason"], [])

    def test_unknown_id_is_not_also_without_reason(self):
        rules = self.disabled(["NOPE-01", "RUN-02"], prose_after="- RUN-02: ok\n")
        self.assertEqual(rules["unknown_ids"], ["NOPE-01"])
        self.assertEqual(rules["disabled_without_reason"], [])

    def test_disabled_ids_are_listed_once_in_file_order(self):
        rules = self.disabled(["RUN-02", "PAR-01", "RUN-02", "NOPE-01", "NOPE-01"])
        self.assertEqual(rules["disabled_without_reason"], ["RUN-02", "PAR-01"])
        self.assertEqual(rules["unknown_ids"], ["NOPE-01"])

    def test_disabled_that_is_not_a_list(self):
        text = block(replace={"rules": '[rules]\ndisabled = "RUN-02"\n'})
        rules, _, code = self.check(doc(text))
        self.assertEqual(code, 0)
        self.assertEqual(rules["unknown_ids"], ['"RUN-02"'])
        self.assertEqual(rules["disabled_without_reason"], [])

    def test_disabled_entry_that_is_not_a_string(self):
        text = block(replace={"rules": "[rules]\ndisabled = [1]\n"})
        rules, _, _ = self.check(doc(text))
        self.assertEqual(rules["unknown_ids"], ["1"])

    def test_rules_section_that_is_not_a_table_is_ignored(self):
        text = block(drop=("rules",), top='rules = "x"\n')
        rules, _, code = self.check(doc(text))
        self.assertEqual(code, 0)
        self.assertEqual(rules["unknown_ids"], [])
        self.assertEqual(rules["disabled_without_reason"], [])


@unittest.skipUnless(sys.version_info >= (3, 11), "the script needs tomllib (Python 3.11 or newer)")
class UsageTest(unittest.TestCase):
    def test_no_argument(self):
        done = helper.run_script()
        self.assertEqual(done.returncode, 2)
        self.assertEqual(done.stdout, "")
        self.assertIn("usage", done.stderr)

    def test_argument_that_is_not_a_folder(self):
        repo = helper.Repo()
        self.addCleanup(repo.close)
        done = helper.run_script(os.path.join(repo.root, "missing"))
        self.assertEqual(done.returncode, 2)
        self.assertEqual(done.stdout, "")
        self.assertIn("usage", done.stderr)

    def test_extra_file_arguments_do_not_change_the_rules_part(self):
        repo = helper.Repo()
        self.addCleanup(repo.close)
        repo.write(doc(helper.FULL_BLOCK))
        plain_rules, plain_detected, _ = helper.run_json(repo.root)
        extra_rules, extra_detected, code = helper.run_json(repo.root, "src/lib.rs", "web/app.ts")
        self.assertEqual(extra_rules, plain_rules)
        self.assertEqual(extra_detected["entries"], {"src/lib.rs": "rust", "web/app.ts": "typescript"})
        self.assertEqual(extra_detected["languages"], plain_detected["languages"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
