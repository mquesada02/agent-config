import glob
import os
import re
import unittest

from skill_files import EVALS, frontmatter, read

PATHS = sorted(glob.glob(os.path.join(EVALS, "*", "graders", "fix-quality.md")))


def criterion(path):
    return re.sub(r"^---\n.*?\n---\n", "", read(path), count=1, flags=re.S)


class FixQualityGrader(unittest.TestCase):
    """The judge is one text, copied into every case (plugin eval reads graders only from the case folder)."""

    def test_every_copy_is_the_same_file(self):
        self.assertGreater(len(PATHS), 50)
        first = read(PATHS[0])
        for path in PATHS:
            self.assertEqual(read(path), first, f"{path} differs from {PATHS[0]}")

    def test_the_judge_is_reported_and_not_scored(self):
        meta = frontmatter(PATHS[0])
        self.assertEqual((meta["type"], meta["arm"]), ("llm", "with-only"))
        self.assertNotIn("weight", meta)
        self.assertNotIn("focus", meta)

    def test_the_criterion_judges_one_row_at_a_time(self):
        text = criterion(PATHS[0])
        self.assertIn("one row at a time", text)
        self.assertNotIn("every finding", text)

    def test_the_criterion_names_what_a_concrete_fix_is(self):
        text = criterion(PATHS[0])
        self.assertIn("Fix cell", text)
        self.assertIn("vague", text)

    def test_a_flag_row_passes_when_the_fix_names_the_edit_and_the_admin_steps_are_in_the_flag_section(self):
        text = criterion(PATHS[0])
        self.assertIn("⚑", text)
        self.assertIn("admin steps", text)
        self.assertIn("⚑ section", text)

    def test_a_name_09_row_passes_when_the_flag_section_names_the_old_and_new_check_names(self):
        line = next(l for l in criterion(PATHS[0]).splitlines() if "NAME-09" in l)
        self.assertIn("cannot be read", line)
        self.assertIn("⚑ section names the exact old and new check names", line)

    def test_a_name_09_fix_never_needs_a_workflow_edit(self):
        for path in PATHS:
            line = next(l for l in criterion(path).splitlines() if l.startswith("A NAME-09 Fix"))
            self.assertIn("never needs a workflow edit", line, path)
            self.assertIn("rename or split comes from another finding", line, path)
            self.assertIn("a NAME-09 row is exempt from the workflow edit rule for flag rows below", line, path)

    def test_the_criterion_does_not_ask_for_files_the_judge_cannot_see(self):
        text = criterion(PATHS[0])
        self.assertIn("not the workflow files", text)
        self.assertNotIn("would remove the problem", text)


if __name__ == "__main__":
    unittest.main()
