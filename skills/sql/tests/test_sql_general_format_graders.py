"""Tests for the format reply grader of the general fallback (graders/grade_format_general.py)."""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GRADER = os.path.join(os.path.dirname(HERE), "graders", "grade_format_general.py")
FALLBACK = ("General guidance: this repo uses MySQL, which the skill does not cover. "
            "The advice is general, with no database and no rule script.")
TITLE = "# sql format (general): src/reports.ts"
BULLET = "- src/reports.ts:6: keyword_case upper: write select as SELECT"
LAST = "The skill edits no file in general mode."
PG_REPORT = [
    "Style: keyword_case upper (rules file)",
    "src/profile.ts:6-8 (written style)",
    "Formatter: none (no safe tool)",
    "Other tools found: none",
]


def run(text, *args):
    proc = subprocess.run([sys.executable, "-I", GRADER, "-", *args], input=text, capture_output=True, text=True)
    return proc.returncode, proc.stdout.splitlines(), proc.stderr


def general(lines=(BULLET,), first=FALLBACK, title=TITLE, last=LAST):
    out = [first, title, *lines]
    if last is not None:
        out.append(last)
    return "\n".join(out) + "\n"


def mixed(general_text=None, pg=PG_REPORT):
    return (general_text if general_text is not None else general()) + "\n".join(pg) + "\n"


class FailsMixin:
    MODE = None

    def assert_fails(self, text, check):
        code, out, _ = run(text, self.MODE)
        self.assertEqual(code, 1, out)
        self.assertEqual(out[-1], "FAIL")
        self.assertTrue(any(line.startswith(f"FAIL {check}:") for line in out), out)


class GeneralPartTest(FailsMixin, unittest.TestCase):
    MODE = "--general"

    def test_a_good_general_part_passes(self):
        code, out, _ = run(general(), "--general")
        self.assertEqual((code, out), (0, ["PASS"]))

    def test_a_part_with_notes_and_no_bullet_passes(self):
        code, out, _ = run(general(["Note: no rules file. Run `/sql setup` once."]), "--general")
        self.assertEqual((code, out), (0, ["PASS"]))

    def test_blank_lines_are_ignored(self):
        text = general().replace(TITLE + "\n", TITLE + "\n\n")
        self.assertEqual(run(text, "--general")[0], 0)

    def test_no_fallback_sentence_fails(self):
        self.assert_fails(general(first="Here is the format advice."), "sentence")

    def test_a_wrong_title_fails(self):
        self.assert_fails(general(title="# sql format: src/reports.ts"), "title")
        self.assert_fails(general(title="# sql optimize (general): src/reports.ts"), "title")

    def test_a_bad_bullet_fails(self):
        self.assert_fails(general(["- src/reports.ts: no line number"]), "bullet")
        self.assert_fails(general(["- src/reports.ts:0: line zero"]), "bullet")

    def test_a_stray_line_fails(self):
        self.assert_fails(general(["Here are the style points.", BULLET]), "stray")

    def test_a_missing_last_line_fails(self):
        self.assert_fails(general(last=None), "last-line")

    def test_a_last_line_with_other_text_fails(self):
        self.assert_fails(general(last=LAST + " Done."), "last-line")

    def test_an_empty_reply_fails(self):
        code, out, _ = run("", "--general")
        self.assertEqual(code, 1)
        self.assertTrue(any(line.startswith("FAIL sentence:") for line in out))


class MixedReplyTest(FailsMixin, unittest.TestCase):
    MODE = "--mixed"

    def test_a_good_mixed_reply_passes(self):
        code, out, _ = run(mixed(), "--mixed")
        self.assertEqual((code, out), (0, ["PASS"]))

    def test_the_split_is_after_the_first_general_last_line(self):
        code, out, _ = run(mixed(pg=PG_REPORT + [LAST]), "--mixed")
        self.assertEqual((code, out), (0, ["PASS"]))

    def test_no_general_last_line_fails(self):
        self.assert_fails("\n".join(PG_REPORT) + "\n", "mixed")

    def test_an_empty_postgresql_part_fails(self):
        self.assert_fails(general(), "postgres-part")

    def test_a_postgresql_title_fails(self):
        self.assert_fails(mixed(pg=["# sql format: src/profile.ts"] + PG_REPORT), "postgres-title")

    def test_a_result_line_fails(self):
        self.assert_fails(mixed(pg=PG_REPORT + ["**Result: 0 critical, 0 required, 0 suggestions.**"]),
                          "postgres-result")

    def test_a_postgresql_part_with_no_formatter_line_fails(self):
        self.assert_fails(mixed(pg=["src/profile.ts:6-8 (written style)"]), "postgres-report")

    def test_a_broken_general_part_fails_in_a_mixed_reply(self):
        self.assert_fails(mixed(general(first="Advice.")), "sentence")


class UsageTest(unittest.TestCase):
    def test_a_mode_flag_is_required(self):
        proc = subprocess.run([sys.executable, "-I", GRADER, "-"], input="", capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)

    def test_an_unreadable_reply_gives_exit_code_2(self):
        proc = subprocess.run([sys.executable, "-I", GRADER, "/nonexistent/reply.txt", "--general"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot read the reply", proc.stderr)


if __name__ == "__main__":
    unittest.main()
