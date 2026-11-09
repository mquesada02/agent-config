import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SCRIPT = os.path.join(SKILL, "scripts", "rules_file.py")
FENCE = "```"
ALL_SECTIONS = ["style", "formatter", "sources", "rules"]
CATALOG = (
    [f"PGJS-{n:02d}" for n in range(1, 5)]
    + [f"PG-{n:02d}" for n in range(1, 11)]
    + [f"PLAN-{n:02d}" for n in range(1, 6)]
)
FULL_BLOCK = """[style]
keyword_case = "upper"
indent = "2 spaces"
clause_per_line = true
comma = "trailing"
alias_as = true

[formatter]
tool = "prettier-plugin-embed"

[sources]
tags = ["sql", "this.sql", "tx"]

[rules]
disabled = []
"""


def doc(block, prose_before="", prose_after=""):
    return f"# SQL rules\n\n{prose_before}{FENCE}toml\n{block}{FENCE}\n\n{prose_after}"


@unittest.skipUnless(sys.version_info >= (3, 11), "the reader needs tomllib (Python 3.11 or newer)")
class RulesFileReaderTest(unittest.TestCase):
    """The rules file reader, run as a command on a temp repo folder."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = self._tmp.name

    def write(self, text, raw=False):
        folder = os.path.join(self.repo, "docs", "agents")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "sql.md")
        if raw:
            with open(path, "wb") as handle:
                handle.write(text)
        else:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)

    def run_reader(self, *args):
        args = args or (self.repo,)
        done = subprocess.run(
            [sys.executable, "-I", SCRIPT, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return done

    def read(self):
        """Run the reader on the temp repo and return (exit code, parsed JSON)."""
        done = self.run_reader()
        self.assertTrue(done.stdout.strip(), f"no JSON on stdout; stderr: {done.stderr}")
        return done.returncode, json.loads(done.stdout)

    def disabled(self, ids, prose=""):
        listed = ", ".join(json.dumps(i) for i in ids)
        self.write(doc(f"[rules]\ndisabled = [{listed}]\n", prose_after=prose))
        return self.read()

    # --- the six keys and the file cases -------------------------------

    def test_a_valid_file_gives_all_six_keys(self):
        self.write(doc(FULL_BLOCK))
        code, out = self.read()
        self.assertEqual(code, 0)
        self.assertEqual(
            set(out),
            {"found", "settings", "missing_sections", "disabled_without_reason", "unknown_ids", "error"},
        )
        self.assertIs(out["found"], True)
        self.assertEqual(out["settings"]["style"]["keyword_case"], "upper")
        self.assertEqual(out["settings"]["sources"]["tags"], ["sql", "this.sql", "tx"])
        self.assertEqual(out["settings"]["rules"], {"disabled": []})
        self.assertEqual(out["missing_sections"], [])
        self.assertEqual(out["disabled_without_reason"], [])
        self.assertEqual(out["unknown_ids"], [])
        self.assertIsNone(out["error"])

    def test_a_partial_file_names_each_missing_section_in_order(self):
        self.write(doc('[style]\nkeyword_case = "lower"\n\n[rules]\ndisabled = []\n'))
        code, out = self.read()
        self.assertEqual(code, 0)
        self.assertEqual(out["missing_sections"], ["formatter", "sources"])
        self.assertEqual(set(out["settings"]), {"style", "rules"})

    def test_no_file_means_found_false_and_every_section_missing(self):
        code, out = self.read()
        self.assertEqual(code, 0)
        self.assertIs(out["found"], False)
        self.assertEqual(out["settings"], {})
        self.assertEqual(out["missing_sections"], ALL_SECTIONS)
        self.assertEqual(out["disabled_without_reason"], [])
        self.assertEqual(out["unknown_ids"], [])
        self.assertIsNone(out["error"])

    def test_a_file_with_no_toml_block_has_every_section_missing(self):
        self.write("# SQL rules\n\n- some prose rule\n")
        code, out = self.read()
        self.assertEqual(code, 0)
        self.assertIs(out["found"], True)
        self.assertEqual(out["settings"], {})
        self.assertEqual(out["missing_sections"], ALL_SECTIONS)

    def test_a_section_that_is_not_a_table_counts_as_missing_and_is_dropped(self):
        self.write(doc('style = 3\n\n[formatter]\ntool = "none"\n'))
        code, out = self.read()
        self.assertEqual(code, 0)
        self.assertEqual(out["missing_sections"], ["style", "sources", "rules"])
        self.assertNotIn("style", out["settings"])
        self.assertEqual(out["settings"]["formatter"], {"tool": "none"})

    # --- errors --------------------------------------------------------

    def assert_error_case(self, out, line):
        self.assertIs(out["found"], True)
        self.assertEqual(out["settings"], {})
        self.assertEqual(out["missing_sections"], ALL_SECTIONS)
        self.assertEqual(out["disabled_without_reason"], [])
        self.assertEqual(out["unknown_ids"], [])
        self.assertTrue(out["error"]["message"])
        self.assertEqual(out["error"]["line"], line)

    def test_a_malformed_block_reports_the_line_of_the_markdown_file(self):
        # The fence is on file line 3, the bad line is the 2nd line in the block.
        self.write("# SQL rules\n\n" + FENCE + 'toml\n[style]\nkeyword_case = = 1\nindent = "x"\n' + FENCE + "\n")
        code, out = self.read()
        self.assertEqual(code, 1)
        self.assert_error_case(out, 5)

    def test_the_line_counts_prose_before_the_block(self):
        self.write("a\nb\nc\nd\n" + FENCE + "toml\n[style]\nkeyword_case = = 1\n" + FENCE + "\n")
        code, out = self.read()
        self.assertEqual(code, 1)
        self.assert_error_case(out, 7)

    def test_the_error_line_counts_only_newlines_as_line_ends(self):
        # A form feed is not a line end in an editor, so it must not shift the line.
        self.write("intro\n\x0c\n# h\n" + FENCE + "toml\n[style\n" + FENCE + "\n")
        code, out = self.read()
        self.assertEqual(code, 1)
        self.assert_error_case(out, 5)

    def test_the_error_line_is_right_in_a_file_with_crlf_line_ends(self):
        self.write("# h\r\n" + FENCE + "toml\r\n[style]\r\nkeyword_case = = 1\r\n" + FENCE + "\r\n")
        code, out = self.read()
        self.assertEqual(code, 1)
        self.assert_error_case(out, 4)

    def test_the_error_message_holds_no_block_relative_position(self):
        self.write("a\nb\n" + FENCE + "toml\n[style]\nkeyword_case = = 1\n" + FENCE + "\n")
        code, out = self.read()
        self.assertEqual(out["error"]["line"], 5)
        self.assertNotRegex(out["error"]["message"], r"(?i)\bline \d+|column \d+|end of document")

    def test_a_utf8_byte_order_mark_does_not_hide_the_settings_block(self):
        self.write(b"\xef\xbb\xbf" + (FENCE + 'toml\n[rules]\ndisabled = ["PG-10"]\n' + FENCE + "\n").encode(), raw=True)
        code, out = self.read()
        self.assertEqual(code, 0)
        self.assertEqual(out["settings"], {"rules": {"disabled": ["PG-10"]}})

    def test_the_output_is_strict_json_even_with_nan_in_the_settings(self):
        self.write(doc("[style]\nx = nan\n"))
        done = self.run_reader()
        self.assertTrue(done.stdout.strip())

        def refuse(token):
            raise ValueError(token)

        out = json.loads(done.stdout, parse_constant=refuse)
        self.assertEqual(done.returncode, 1)
        self.assertTrue(out["error"]["message"])
        self.assertIsNone(out["error"]["line"])

    def test_a_block_nested_too_deep_for_the_parser_is_an_error_not_a_traceback(self):
        depth = 5000
        self.write(doc("x = " + "[" * depth + "]" * depth + "\n"))
        code, out = self.read()
        self.assertEqual(code, 1)
        self.assert_error_case(out, None)

    def test_a_fence_with_an_info_string_is_the_settings_block(self):
        self.write("# h\n" + FENCE + 'toml title="x"\n[rules]\ndisabled = ["PG-10"]\n' + FENCE + "\n")
        code, out = self.read()
        self.assertEqual(code, 0)
        self.assertEqual(out["settings"], {"rules": {"disabled": ["PG-10"]}})
        self.assertEqual(out["disabled_without_reason"], ["PG-10"])

    def test_a_second_toml_block_reports_the_line_of_its_opening_fence(self):
        first = doc(FULL_BLOCK)
        second_line = first.count("\n") + 1
        for fence in (FENCE + "toml", FENCE + 'toml title="y"'):
            with self.subTest(fence=fence):
                self.write(first + f"{fence}\n[style]\n{FENCE}\n")
                code, out = self.read()
                self.assertEqual(code, 1)
                self.assert_error_case(out, second_line)

    def test_an_unclosed_block_reports_the_line_of_its_opening_fence(self):
        self.write("# SQL rules\n\n" + FENCE + 'toml\n[style]\nkeyword_case = "upper"\n')
        code, out = self.read()
        self.assertEqual(code, 1)
        self.assert_error_case(out, 3)

    def test_a_file_that_is_not_utf8_is_a_read_failure_with_a_null_line(self):
        self.write(b"\xff\xfe\x00bad", raw=True)
        code, out = self.read()
        self.assertEqual(code, 1)
        self.assert_error_case(out, None)

    @unittest.skipIf(os.geteuid() == 0, "root can read any folder")
    def test_a_folder_the_user_cannot_enter_is_a_read_failure_not_a_missing_file(self):
        self.write(doc(FULL_BLOCK))
        folder = os.path.join(self.repo, "docs", "agents")
        os.chmod(folder, 0)
        self.addCleanup(os.chmod, folder, 0o755)
        code, out = self.read()
        self.assertEqual(code, 1)
        self.assert_error_case(out, None)

    def test_a_folder_in_place_of_the_file_is_a_read_failure_with_a_null_line(self):
        os.makedirs(os.path.join(self.repo, "docs", "agents", "sql.md"))
        code, out = self.read()
        self.assertEqual(code, 1)
        self.assert_error_case(out, None)

    # --- usage errors --------------------------------------------------

    def test_usage_errors_exit_2(self):
        done = subprocess.run([sys.executable, "-I", SCRIPT], capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)
        self.assertEqual(self.run_reader(self.repo, self.repo).returncode, 2)
        self.assertEqual(self.run_reader(os.path.join(self.repo, "missing")).returncode, 2)

    # --- disabled ids and reasons --------------------------------------

    def test_a_reason_line_in_each_allowed_form_enables_the_reason(self):
        forms = [
            "- PG-10: we keep page/page_size pagination (house rule).",
            "* PG-10: we keep page/page_size pagination (house rule).",
            "PG-10: we keep page/page_size pagination (house rule).",
            "- PG-10— we keep page/page_size pagination (house rule).",
            "PG-10—x",
            "  - PG-10: indented marker",
        ]
        for form in forms:
            with self.subTest(form=form):
                code, out = self.disabled(["PG-10"], prose=form + "\n")
                self.assertEqual(code, 0)
                self.assertEqual(out["disabled_without_reason"], [])
                self.assertEqual(out["unknown_ids"], [])

    def test_a_disabled_id_with_no_reason_is_listed(self):
        code, out = self.disabled(["PG-10"])
        self.assertEqual(code, 0)
        self.assertEqual(out["disabled_without_reason"], ["PG-10"])

    def test_lines_that_are_not_a_reason_leave_the_id_without_reason(self):
        lines = [
            "see PG-10",
            "## PG-10",
            "PG-10:",
            "- PG-10:    ",
            "PG-10 : a space before the separator",
            "pg-10: wrong case",
            "- PG-1: only a prefix of the id",
            "text PG-10: not at the start",
        ]
        for line in lines:
            with self.subTest(line=line):
                code, out = self.disabled(["PG-10"], prose=line + "\n")
                self.assertEqual(code, 0)
                self.assertEqual(out["disabled_without_reason"], ["PG-10"])

    def test_a_line_inside_the_toml_block_is_not_a_reason(self):
        self.write(doc('[rules]\ndisabled = ["PG-10"]\nnote = """\nPG-10: inside the block\n"""\n'))
        code, out = self.read()
        self.assertEqual(code, 0)
        self.assertEqual(out["disabled_without_reason"], ["PG-10"])

    def test_a_reason_line_in_another_fenced_block_still_counts(self):
        # Only the TOML block is excluded from the prose lines (spec decision).
        code, out = self.disabled(["PG-10"], prose=f"{FENCE}text\nPG-10: in a text block\n{FENCE}\n")
        self.assertEqual(code, 0)
        self.assertEqual(out["disabled_without_reason"], [])

    def test_every_catalog_id_is_known(self):
        for rule_id in CATALOG:
            with self.subTest(rule_id=rule_id):
                code, out = self.disabled([rule_id])
                self.assertEqual(out["unknown_ids"], [])
                self.assertEqual(out["disabled_without_reason"], [rule_id])

    def test_an_id_outside_the_catalog_is_unknown_and_never_in_both_lists(self):
        for rule_id in ["PG-99", "PG-11", "PGJS-05", "PLAN-06", "XYZ-01"]:
            with self.subTest(rule_id=rule_id):
                code, out = self.disabled([rule_id])
                self.assertEqual(out["unknown_ids"], [rule_id])
                self.assertEqual(out["disabled_without_reason"], [])

    def test_an_unknown_id_with_a_reason_line_is_still_unknown(self):
        code, out = self.disabled(["PG-99"], prose="- PG-99: why\n")
        self.assertEqual(out["unknown_ids"], ["PG-99"])
        self.assertEqual(out["disabled_without_reason"], [])

    def test_entries_that_are_not_strings_appear_as_json_text(self):
        self.write(doc('[rules]\ndisabled = [5, true, {a = 1}, "PG-01"]\n'))
        code, out = self.read()
        self.assertEqual(code, 0)
        self.assertEqual(out["unknown_ids"], ["5", "true", '{"a": 1}'])
        self.assertEqual(out["disabled_without_reason"], ["PG-01"])

    def test_lists_keep_file_order_and_drop_duplicates(self):
        code, out = self.disabled(["PG-03", "PG-01", "PG-03", "PG-77", "PG-76", "PG-77"])
        self.assertEqual(out["disabled_without_reason"], ["PG-03", "PG-01"])
        self.assertEqual(out["unknown_ids"], ["PG-77", "PG-76"])

    def test_an_absent_disabled_key_means_no_disabled_ids(self):
        self.write(doc("[rules]\n"))
        code, out = self.read()
        self.assertEqual(code, 0)
        self.assertNotIn("rules", out["missing_sections"])
        self.assertEqual(out["disabled_without_reason"], [])
        self.assertEqual(out["unknown_ids"], [])

    def test_a_disabled_value_that_is_not_a_list_is_one_unknown_entry(self):
        self.write(doc('[rules]\ndisabled = "PG-01"\n'))
        code, out = self.read()
        self.assertEqual(code, 0)
        self.assertEqual(out["unknown_ids"], ['"PG-01"'])
        self.assertEqual(out["disabled_without_reason"], [])

    def test_a_missing_rules_section_means_no_disabled_rules(self):
        self.write(doc('[style]\nkeyword_case = "upper"\n'))
        code, out = self.read()
        self.assertEqual(code, 0)
        self.assertIn("rules", out["missing_sections"])
        self.assertEqual(out["disabled_without_reason"], [])
        self.assertEqual(out["unknown_ids"], [])


if __name__ == "__main__":
    unittest.main()
