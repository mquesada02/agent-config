import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GRADERS = os.path.join(os.path.dirname(HERE), "graders")

HEAD = "import postgres from 'postgres'\nconst sql = postgres('postgres://localhost/example')\n"

DEFAULT_STYLE = {
    "keyword_case": "upper",
    "indent": "2 spaces",
    "clause_per_line": True,
    "comma": "trailing",
    "alias_as": True,
}


def run(name, *args):
    result = subprocess.run(
        [sys.executable, os.path.join(GRADERS, name), *args], capture_output=True, text=True
    )
    return result.returncode, result.stdout, result.stderr


class GraderCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name

    def write(self, name, text):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        return path

    def grade(self, name, letter, *args, expect):
        code, out, err = run(name, *args)
        self.assertEqual(err, "", err)
        report = json.loads(out)
        self.assertEqual(report["grader"], letter)
        self.assertEqual(report["pass"], expect, report)
        self.assertEqual(code, 0 if expect else 1)
        self.assertEqual(bool(report["failures"]), not expect)
        return report

    def assertUsage(self, name, *args):
        code, out, err = run(name, *args)
        self.assertEqual(code, 2, args)
        self.assertEqual(out, "")
        self.assertEqual(len(err.strip().splitlines()), 1, err)


def template(body):
    return HEAD + "export const q = (x: number, cond: boolean) => sql`" + body + "`\n"


BEFORE = template(
    "\n  select a\n  from t\n  where b = ${x}\n  ${cond ? sql`and c = 1` : sql``}\n"
)


class InterpolationsSameTest(GraderCase):
    def test_a_reformat_that_keeps_every_interpolation_passes(self):
        before = self.write("before.ts", BEFORE)
        after = self.write(
            "after.ts",
            template("\n    SELECT a\n    FROM t\n    WHERE b = ${x}\n    ${cond ? sql`and c = 1` : sql``}\n"),
        )
        self.grade("interpolations_same.py", "A", before, after, expect=True)

    def test_a_changed_expression_fails(self):
        before = self.write("before.ts", BEFORE)
        after = self.write("after.ts", BEFORE.replace("b = ${x}", "b = ${y}"))
        report = self.grade("interpolations_same.py", "A", before, after, expect=False)
        self.assertIn("y", report["failures"][0])

    def test_a_moved_clause_fails(self):
        before = self.write("before.ts", BEFORE)
        after = self.write(
            "after.ts",
            template("\n  select a\n  from t ${x}\n  where b = 1\n  ${cond ? sql`and c = 1` : sql``}\n"),
        )
        self.grade("interpolations_same.py", "A", before, after, expect=False)

    def test_a_missing_interpolation_fails(self):
        before = self.write("before.ts", BEFORE)
        after = self.write("after.ts", BEFORE.replace("b = ${x}", "b = 1"))
        self.grade("interpolations_same.py", "A", before, after, expect=False)

    def test_a_different_statement_count_fails(self):
        before = self.write("before.ts", BEFORE)
        after = self.write("after.ts", BEFORE + "export const r = sql`select 1`\n")
        report = self.grade("interpolations_same.py", "A", before, after, expect=False)
        self.assertIn("statement", report["failures"][0])

    def test_a_different_tag_fails(self):
        text = HEAD + "const db = postgres('x')\nexport const q = %s`select 1`\n"
        before = self.write("before.ts", text % "sql")
        after = self.write("after.ts", text % "db")
        self.grade("interpolations_same.py", "A", before, after, expect=False)

    def test_sql_files_pass_and_fail(self):
        before = self.write("before.sql", "select a from t where b = 1")
        after = self.write("after.sql", "SELECT a\nFROM t\nWHERE b = 1")
        self.grade("interpolations_same.py", "A", before, after, expect=True)
        other = self.write("other.sql", "SELECT a\nFROM t")
        self.grade("interpolations_same.py", "A", before, other, expect=True)
        self.grade("interpolations_same.py", "A", before, self.write("two.sql", "select 1;\nselect 2"), expect=False)

    def test_an_unreadable_file_is_a_failure_not_a_usage_error(self):
        before = self.write("before.ts", BEFORE)
        report = self.grade("interpolations_same.py", "A", before, os.path.join(self.tmp, "none.ts"), expect=False)
        self.assertIn("cannot read", report["failures"][0])

    def test_the_tags_option_is_passed_on(self):
        text = "const db = (x: string) => x\nexport const q = db`select a from t where b = ${1}`\n"
        before = self.write("before.ts", text)
        after = self.write("after.ts", text.replace("${1}", "${2}"))
        self.grade("interpolations_same.py", "A", before, after, expect=True)
        self.grade("interpolations_same.py", "A", before, after, "--tags", "db", expect=False)

    def test_usage_errors(self):
        before = self.write("before.ts", BEFORE)
        self.assertUsage("interpolations_same.py")
        self.assertUsage("interpolations_same.py", before)
        self.assertUsage("interpolations_same.py", before, before, before)
        self.assertUsage("interpolations_same.py", before, before, "--nope")
        self.assertUsage("interpolations_same.py", before, before, "--tags")
        self.assertUsage("interpolations_same.py", before, before, "--tags", "a", "--tags", "b")


LINES = "".join("line %d\n" % n for n in range(1, 11))


def replace_lines(start, end, new):
    lines = LINES.splitlines(keepends=True)
    return "".join(lines[: start - 1]) + new + "".join(lines[end:])


class OnlyTargetChangesTest(GraderCase):
    def check(self, after_text, *targets, expect):
        before = self.write("before.txt", LINES)
        after = self.write("after.txt", after_text)
        args = [arg for target in targets for arg in ("--target", target)]
        return self.grade("only_target_changes.py", "B", before, after, *args, expect=expect)

    def test_the_same_file_passes(self):
        self.check(LINES, "3-5", expect=True)

    def test_a_change_inside_the_target_passes(self):
        self.check(replace_lines(3, 5, "new a\nnew b\n"), "3-5", expect=True)

    def test_a_target_that_grows_or_vanishes_passes(self):
        self.check(replace_lines(3, 5, "x\n" * 7), "3-5", expect=True)
        self.check(replace_lines(3, 5, ""), "3-5", expect=True)

    def test_a_change_outside_the_target_fails(self):
        self.check(replace_lines(7, 7, "changed\n"), "3-5", expect=False)
        self.check(replace_lines(1, 1, "changed\n") , "3-5", expect=False)

    def test_a_line_ending_change_outside_the_target_fails(self):
        self.check(LINES.replace("line 8\n", "line 8\r\n"), "3-5", expect=False)

    def test_a_deleted_tail_fails(self):
        self.check("".join(LINES.splitlines(keepends=True)[:9]), "3-5", expect=False)

    def test_two_targets(self):
        after = replace_lines(2, 3, "a\n").replace("line 7\n", "b\nc\n")
        self.check(after, "2-3", "7-7", expect=True)
        self.check(after.replace("line 5\n", "five\n"), "2-3", "7-7", expect=False)

    def test_adjacent_targets_are_valid(self):
        self.check(replace_lines(1, 6, "new\n"), "1-3", "4-6", expect=True)
        self.check(replace_lines(1, 6, "new\n") + "extra\n", "1-3", "4-6", expect=False)

    def test_a_target_at_the_start_and_one_at_the_end(self):
        self.check(replace_lines(1, 2, "x\n"), "1-2", expect=True)
        self.check(replace_lines(9, 10, "x\n"), "9-10", expect=True)

    def test_the_first_and_last_segment_must_not_overlap(self):
        before = "a\nb\nc\n"
        after = "a\n"
        before_path = self.write("b.txt", before)
        after_path = self.write("a.txt", after)
        self.grade("only_target_changes.py", "B", before_path, after_path, "--target", "2-2", expect=False)

    def test_a_middle_segment_is_matched_in_order(self):
        after = replace_lines(2, 2, "x\n").replace("line 5\n", "line 5\n")
        self.check(after, "2-2", "4-4", expect=True)
        swapped = "line 1\nline 5\nx\nline 3\ny\nline 6\n"
        self.check(swapped, "2-2", "4-4", expect=False)

    def test_usage_errors(self):
        before = self.write("before.txt", LINES)
        for targets in (
            ["3-5", "5-7"],
            ["3-5", "3-5"],
            ["7-8", "3-5"],
            ["5-3"],
            ["0-3"],
            ["1-11"],
            ["abc"],
            ["3"],
            ["1.5-3"],
            ["-3-5"],
        ):
            with self.subTest(targets=targets):
                args = [arg for target in targets for arg in ("--target", target)]
                self.assertUsage("only_target_changes.py", before, before, *args)
        self.assertUsage("only_target_changes.py", before, before)
        self.assertUsage("only_target_changes.py", before, "--target", "1-2")
        self.assertUsage("only_target_changes.py", before, before, before, "--target", "1-2")
        self.assertUsage("only_target_changes.py", before, before, "--target")
        self.assertUsage("only_target_changes.py", before, before, "--nope", "--target", "1-2")

    def test_an_unreadable_file_is_a_failure(self):
        before = self.write("before.txt", LINES)
        self.grade(
            "only_target_changes.py", "B", before, os.path.join(self.tmp, "none.txt"), "--target", "1-2", expect=False
        )


FIRST = "SELECT a,\n  b\nFROM t AS x\nWHERE c;\n\nSELECT d\nFROM u AS y;\n"
SECOND_IN_LOWER = FIRST.replace("SELECT d\nFROM u AS y", "select d\nfrom u as y")


class StyleMatchesTest(GraderCase):
    def style(self, **change):
        return self.write("style.json", json.dumps({**DEFAULT_STYLE, **change}))

    def check(self, first_text, *extra, second_text=None, expect, **change):
        first = self.write("first.sql", first_text)
        second = self.write("second.sql", first_text if second_text is None else second_text)
        return self.grade(
            "style_matches.py", "C", first, second, "--style", self.style(**change), *extra, expect=expect
        )

    def test_a_file_in_the_style_passes(self):
        self.check(FIRST, expect=True)

    def test_a_second_run_that_differs_fails(self):
        report = self.check(FIRST, second_text=FIRST + "\n", expect=False)
        self.assertIn("second", report["failures"][0])

    def test_a_keyword_case_that_differs_fails(self):
        self.check(SECOND_IN_LOWER, expect=False)
        self.check(FIRST, expect=False, keyword_case="lower")

    def test_two_statements_that_vote_differently_fail_the_expected_value(self):
        self.check(SECOND_IN_LOWER, expect=False, keyword_case="lower")

    def test_an_indent_that_differs_fails(self):
        self.check(FIRST, expect=False, indent="4 spaces")
        self.check(FIRST, expect=False, indent="tab")

    def test_a_clause_layout_that_differs_fails(self):
        self.check("SELECT a FROM t;\n", expect=False)
        self.check(FIRST, expect=False, clause_per_line=False)

    def test_a_comma_that_differs_fails(self):
        self.check("SELECT a\n  , b\nFROM t;\n", expect=False)
        self.check(FIRST, expect=False, comma="leading")

    def test_the_comma_is_not_checked_when_clause_per_line_is_false(self):
        text = "SELECT a, b FROM t AS x;\n"
        self.check(text, expect=True, clause_per_line=False)
        self.check(text, expect=True, clause_per_line=False, comma="leading")

    def test_an_alias_that_differs_fails(self):
        self.check("SELECT a\nFROM t x;\n", expect=False)
        self.check(FIRST, expect=False, alias_as=False)

    def test_a_property_with_no_vote_passes(self):
        self.check("SELECT 1;\n", expect=True)

    def test_a_nested_fragment_statement_is_not_voted(self):
        text = HEAD + "export const q = (c: boolean) => sql`\n  SELECT a\n  FROM t ${c ? sql`where b` : sql``}\n`\n"
        first = self.write("first.ts", text)
        second = self.write("second.ts", text)
        self.grade("style_matches.py", "C", first, second, "--style", self.style(), expect=True)

    def test_the_target_limits_the_statements_that_are_voted(self):
        text = SECOND_IN_LOWER
        self.check(text, "--target", "1-4", expect=True)
        self.check(text, "--target", "6-7", expect=False)

    def test_a_statement_outside_the_target_is_not_counted(self):
        self.check(FIRST, "--target", "2-4", expect=False)

    def test_a_target_with_no_statement_fails(self):
        report = self.check(FIRST, "--target", "5-5", expect=False)
        self.assertIn("no statement", report["failures"][0])

    def test_the_tags_option_is_passed_on(self):
        text = "const db = (x: string) => x\nexport const q = db`\nSELECT a\nFROM t\n`\n"
        first = self.write("first.ts", text)
        self.grade("style_matches.py", "C", first, first, "--style", self.style(), expect=False)
        self.grade("style_matches.py", "C", first, first, "--style", self.style(), "--tags", "db", expect=True)

    def test_usage_errors(self):
        first = self.write("first.sql", FIRST)
        style = self.style()
        bad_json = self.write("bad.json", "{")
        missing_key = self.write("missing.json", json.dumps({"keyword_case": "upper"}))
        wrong_type = self.write("wrong.json", json.dumps({**DEFAULT_STYLE, "alias_as": "yes"}))
        for args in (
            [],
            [first],
            [first, first],
            [first, first, "--style"],
            [first, first, "--style", style, "extra"],
            [first, first, "--style", style, "--style", style],
            [first, first, "--style", style, "--nope"],
            [first, first, "--style", bad_json],
            [first, first, "--style", missing_key],
            [first, first, "--style", wrong_type],
            [first, first, "--style", os.path.join(self.tmp, "none.json")],
            [first, first, "--style", style, "--target", "3-2"],
            [first, first, "--style", style, "--target", "1-99"],
            [first, first, "--style", style, "--target", "x"],
            [first, first, "--style", style, "--target", "1-2", "--target", "3-4"],
            [first, first, "--style", style, "--tags"],
        ):
            with self.subTest(args=args):
                self.assertUsage("style_matches.py", *args)


if __name__ == "__main__":
    unittest.main()
