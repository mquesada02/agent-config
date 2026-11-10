import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
SCRIPT = os.path.join(SKILL_DIR, "scripts", "measure_style.py")
FIXTURES = os.path.join(HERE, "fixtures", "style")

DEFAULT = {
    "keyword_case": "upper",
    "indent": "2 spaces",
    "clause_per_line": True,
    "comma": "trailing",
    "alias_as": True,
}


def fixture(name):
    return os.path.join(FIXTURES, name)


def run(*args):
    result = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def measure(*args):
    code, out, err = run(*args)
    assert code == 0, (code, out, err)
    return json.loads(out)


class MeasureCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name

    def write(self, name, text):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def props(self, path, *extra):
        return measure(*extra, path)["properties"]


class MajorityTest(MeasureCase):
    def test_a_known_majority_for_every_property(self):
        out = measure(fixture("majority.sql"))
        self.assertEqual(out["files"], [fixture("majority.sql")])
        self.assertEqual(out["errors"], [])
        self.assertEqual(out["statements"], 3)
        self.assertEqual(out["style"], DEFAULT)
        props = out["properties"]
        self.assertEqual(props["keyword_case"]["counts"], {"upper": 3, "lower": 0})
        self.assertEqual(props["indent"]["counts"], {"2 spaces": 3})
        self.assertEqual(props["clause_per_line"]["counts"], {"true": 3, "false": 0})
        self.assertEqual(props["comma"]["counts"], {"trailing": 2, "leading": 0})
        self.assertEqual(props["alias_as"]["counts"], {"true": 3, "false": 0})
        for key, prop in props.items():
            with self.subTest(key=key):
                self.assertEqual(prop["source"], "majority")
                self.assertIsNone(prop["reason"])
                self.assertEqual(prop["value"], prop["majority"])

    def test_a_non_default_majority_is_used(self):
        out = measure(fixture("indent.ts"))
        self.assertEqual(out["statements"], 3)
        self.assertEqual(out["style"]["keyword_case"], "lower")
        self.assertEqual(out["style"]["indent"], "4 spaces")
        self.assertEqual(out["properties"]["indent"]["counts"], {"4 spaces": 3})
        self.assertEqual(out["properties"]["keyword_case"]["source"], "majority")

    def test_a_tie_gives_the_default_value(self):
        out = measure(fixture("tie.sql"))
        prop = out["properties"]["keyword_case"]
        self.assertEqual(prop["counts"], {"upper": 2, "lower": 2})
        self.assertIsNone(prop["majority"])
        self.assertEqual(prop["value"], "upper")
        self.assertEqual(prop["source"], "default")
        self.assertEqual(prop["reason"], "tie")

    def test_no_vote_gives_the_default_value(self):
        out = measure(fixture("tie.sql"))
        indent = out["properties"]["indent"]
        self.assertEqual(indent["counts"], {})
        self.assertIsNone(indent["majority"])
        self.assertEqual(indent["value"], "2 spaces")
        self.assertEqual(indent["source"], "default")
        self.assertEqual(indent["reason"], "no_votes")
        comma = out["properties"]["comma"]
        self.assertEqual(comma["counts"], {"trailing": 0, "leading": 0})
        self.assertEqual(comma["reason"], "no_votes")
        self.assertEqual(out["properties"]["alias_as"]["reason"], "no_votes")
        self.assertEqual(out["properties"]["clause_per_line"]["counts"], {"true": 0, "false": 4})
        self.assertEqual(out["properties"]["clause_per_line"]["value"], False)

    def test_fewer_than_three_statements_gives_the_defaults(self):
        out = measure(fixture("few.sql"))
        self.assertEqual(out["statements"], 2)
        self.assertEqual(out["style"], DEFAULT)
        prop = out["properties"]["keyword_case"]
        self.assertEqual(prop["counts"], {"upper": 0, "lower": 2})
        self.assertEqual(prop["majority"], "lower")
        self.assertEqual(prop["value"], "upper")
        self.assertEqual(prop["source"], "default")
        self.assertEqual(prop["reason"], "few_statements")
        for prop in out["properties"].values():
            self.assertEqual(prop["reason"], "few_statements")

    def test_statements_are_counted_over_all_files(self):
        out = measure(fixture("tie.sql"), fixture("few.sql"))
        self.assertEqual(out["statements"], 6)
        self.assertEqual(out["files"], [fixture("tie.sql"), fixture("few.sql")])
        self.assertEqual(out["properties"]["keyword_case"]["counts"], {"upper": 2, "lower": 4})
        self.assertEqual(out["style"]["keyword_case"], "lower")


class PropertyVoteTest(MeasureCase):
    def one(self, text, key):
        return self.props(self.write("a.sql", text))[key]

    def test_mixed_case_keywords_count_for_neither(self):
        self.assertEqual(self.one("Select a From t", "keyword_case")["counts"], {"upper": 0, "lower": 0})

    def test_a_word_after_a_dot_is_not_a_keyword(self):
        self.assertEqual(self.one("select t.FROM, t.AND, t.OR from t", "keyword_case")["counts"], {"upper": 0, "lower": 1})

    def test_names_and_functions_are_not_keywords(self):
        self.assertEqual(self.one("select ID, NAME, TOTAL from t", "keyword_case")["counts"], {"upper": 0, "lower": 1})

    def test_a_tab_indent_votes_tab(self):
        counts = self.one("SELECT a\n\tFROM t", "indent")["counts"]
        self.assertEqual(counts, {"tab": 1})

    def test_the_smallest_indent_step_is_the_vote(self):
        counts = self.one("SELECT a,\n    b,\n      c\nFROM t", "indent")["counts"]
        self.assertEqual(counts, {"4 spaces": 1})

    def test_a_one_line_statement_has_no_indent_vote(self):
        self.assertEqual(self.one("SELECT a FROM t", "indent")["counts"], {})

    def test_a_sql_statement_with_a_blank_first_line_keeps_it(self):
        counts = self.one("   \nSELECT a\n  FROM t", "indent")["counts"]
        self.assertEqual(counts, {"2 spaces": 1})

    def test_the_js_base_is_the_first_body_line_not_the_opening_line(self):
        path = self.write(
            "a.ts",
            "import postgres from 'postgres'\nconst sql = postgres('x')\n"
            "export const q = sql`\n      SELECT a\n        FROM t\n    `\n",
        )
        self.assertEqual(self.props(path)["indent"]["counts"], {"2 spaces": 1})

    def test_the_js_base_with_text_on_the_opening_line(self):
        path = self.write(
            "a.ts",
            "import postgres from 'postgres'\nconst sql = postgres('x')\n"
            "export const q = sql`SELECT a\n      FROM t\n        WHERE b`\n",
        )
        self.assertEqual(self.props(path)["indent"]["counts"], {"2 spaces": 1})

    def test_comma_leading_wins_over_trailing(self):
        counts = self.one("SELECT a\n  , b\n  , c\nFROM t", "comma")["counts"]
        self.assertEqual(counts, {"trailing": 0, "leading": 1})

    def test_comma_tie_gives_no_vote(self):
        prop = self.one("SELECT a,\n  b\n  , c\nFROM t", "comma")
        self.assertIsNone(prop["majority"])
        self.assertEqual(prop["counts"], {"trailing": 0, "leading": 0})

    def test_clause_words_alone_on_their_lines_vote_true(self):
        self.assertEqual(self.one("SELECT\n  a\nFROM t", "clause_per_line")["counts"], {"true": 1, "false": 0})

    def test_a_clause_word_that_shares_its_line_votes_false(self):
        self.assertEqual(self.one("SELECT a\nFROM t WHERE b", "clause_per_line")["counts"], {"true": 0, "false": 1})

    def test_one_clause_word_is_no_vote(self):
        self.assertEqual(self.one("SELECT a", "clause_per_line")["counts"], {"true": 0, "false": 0})

    def test_clause_words_inside_parentheses_do_not_count(self):
        text = "SELECT a\nFROM t\nWHERE b IN (SELECT c FROM u)"
        self.assertEqual(self.one(text, "clause_per_line")["counts"], {"true": 1, "false": 0})

    def test_from_after_delete_and_distinct_is_not_a_clause_word(self):
        self.assertEqual(self.one("DELETE FROM t\nWHERE a", "clause_per_line")["counts"], {"true": 1, "false": 0})
        text = "SELECT DISTINCT a\nFROM t"
        self.assertEqual(self.one(text, "clause_per_line")["counts"], {"true": 1, "false": 0})
        text = "SELECT a IS DISTINCT FROM b\nFROM t"
        self.assertEqual(self.one(text, "clause_per_line")["counts"], {"true": 1, "false": 0})

    def test_update_after_do_and_for_is_not_a_clause_word(self):
        text = "INSERT INTO t (a)\nVALUES (1)\nON CONFLICT (a) DO UPDATE\nSET a = 2"
        self.assertEqual(self.one(text, "clause_per_line")["counts"], {"true": 1, "false": 0})

    def test_alias_with_and_without_as(self):
        text = "SELECT 1 FROM a AS x JOIN b y ON y.id = x.id JOIN public.c AS z ON true"
        self.assertEqual(self.one(text, "alias_as")["counts"], {"true": 1, "false": 0})
        text = "SELECT 1 FROM a x JOIN b y ON y.id = x.id JOIN c AS z ON true"
        self.assertEqual(self.one(text, "alias_as")["counts"], {"true": 0, "false": 1})

    def test_a_clause_word_after_a_table_is_not_an_alias(self):
        text = "SELECT 1 FROM a\nWHERE b"
        self.assertEqual(self.one(text, "alias_as")["counts"], {"true": 0, "false": 0})
        text = "SELECT 1 FROM a JOIN b ON true LEFT JOIN c ON true GROUP BY 1"
        self.assertEqual(self.one(text, "alias_as")["counts"], {"true": 0, "false": 0})

    def test_a_tie_of_alias_votes_gives_no_vote(self):
        text = "SELECT 1 FROM a AS x JOIN b y ON true"
        self.assertEqual(self.one(text, "alias_as")["counts"], {"true": 0, "false": 0})
        self.assertIsNone(self.one(text, "alias_as")["majority"])


class MaskingTest(MeasureCase):
    def test_a_keyword_in_a_string_or_a_comment_does_not_count(self):
        out = measure(fixture("masking.sql"))
        self.assertEqual(out["properties"]["keyword_case"]["counts"], {"upper": 0, "lower": 1})
        self.assertEqual(out["properties"]["clause_per_line"]["counts"], {"true": 1, "false": 0})

    def test_a_keyword_in_a_block_comment_a_quoted_name_or_a_dollar_string_does_not_count(self):
        text = (
            "select /* FROM nested /* WHERE */ SELECT */ \"FROM\" as a,\n"
            "  $$ FROM WHERE $$, $tag$ AND OR $tag$, E'it\\'s FROM'\n"
            "from t"
        )
        path = self.write("a.sql", text)
        counts = self.props(path)["keyword_case"]["counts"]
        self.assertEqual(counts, {"upper": 0, "lower": 1})

    def test_an_escaped_quote_does_not_end_a_string(self):
        path = self.write("a.sql", "select 'it''s FROM WHERE AND here' from t")
        self.assertEqual(self.props(path)["keyword_case"]["counts"], {"upper": 0, "lower": 1})

    def test_a_fragment_interpolation_does_not_make_an_alias(self):
        out = measure(fixture("fragment.ts"))
        self.assertEqual(out["statements"], 1)
        self.assertEqual(out["properties"]["alias_as"]["counts"], {"true": 0, "false": 0})
        self.assertEqual(out["properties"]["keyword_case"]["counts"], {"upper": 1, "lower": 0})

    def test_a_value_interpolation_is_a_plain_word(self):
        path = self.write(
            "a.ts",
            "import postgres from 'postgres'\nconst sql = postgres('x')\n"
            "export const q = (id: number) => sql`\n  SELECT a\n  FROM t\n  WHERE id = ${id}\n`\n",
        )
        out = measure(path)
        self.assertEqual(out["statements"], 1)
        self.assertEqual(out["properties"]["keyword_case"]["counts"], {"upper": 1, "lower": 0})

    def test_a_statement_without_a_command_word_is_not_counted(self):
        path = self.write("a.sql", "create table t (a int)")
        self.assertEqual(measure(path)["statements"], 0)

    def test_the_tags_option_reaches_the_extractor(self):
        path = self.write(
            "a.ts",
            "const db = (x: string) => x\nexport const q = db`select a from t`\n",
        )
        self.assertEqual(measure(path)["statements"], 0)
        self.assertEqual(measure("--tags", "db", path)["statements"], 1)


class ErrorsTest(MeasureCase):
    def test_a_missing_file_goes_in_errors_with_the_extractor_message(self):
        missing = os.path.join(self.tmp, "missing.sql")
        out = measure(fixture("majority.sql"), missing)
        self.assertEqual(out["statements"], 3)
        self.assertEqual(len(out["errors"]), 1)
        error = out["errors"][0]
        self.assertEqual(sorted(error), ["file", "message"])
        self.assertEqual(error["file"], missing)
        self.assertIn("cannot read the file", error["message"])

    def test_an_unsupported_extension_uses_the_first_stderr_line(self):
        path = self.write("a.txt", "select 1")
        out = measure(path)
        self.assertEqual(out["errors"], [{"file": path, "message": "unsupported file form: .txt"}])
        self.assertEqual(out["statements"], 0)
        self.assertEqual(out["properties"]["keyword_case"]["reason"], "few_statements")

    def test_a_template_that_does_not_close_is_an_error(self):
        path = self.write(
            "a.ts",
            "import postgres from 'postgres'\nconst sql = postgres('x')\nexport const q = sql`select 1\n",
        )
        out = measure(path)
        self.assertEqual(len(out["errors"]), 1)
        self.assertEqual(out["errors"][0]["file"], path)
        self.assertNotIn("line", out["errors"][0])


class UsageTest(MeasureCase):
    def assertUsage(self, *args):
        code, out, err = run(*args)
        self.assertEqual(code, 2, args)
        self.assertEqual(out, "")
        self.assertEqual(len(err.strip().splitlines()), 1, err)

    def test_no_file(self):
        self.assertUsage()
        self.assertUsage("--tags", "db")

    def test_an_unknown_option(self):
        self.assertUsage("--nope", fixture("majority.sql"))

    def test_a_repeated_tags_option(self):
        self.assertUsage("--tags", "a", "--tags", "b", fixture("majority.sql"))

    def test_a_tags_option_without_a_value(self):
        self.assertUsage(fixture("majority.sql"), "--tags")
        self.assertUsage("--tags", "--tags", fixture("majority.sql"))
        self.assertUsage("--tags", "-x", fixture("majority.sql"))


if __name__ == "__main__":
    unittest.main()
