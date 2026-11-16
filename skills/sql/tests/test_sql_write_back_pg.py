import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
SCRIPT = os.path.join(SKILL_DIR, "scripts", "write_back_pg.py")
EXTRACTOR = os.path.join(SKILL_DIR, "scripts", "extract.py")

HEAD = "import pg from 'pg'\nconst pool = new pg.Pool()\n"
OK_KEYS = [
    "became_template", "changed", "check", "const_name", "end_line", "file", "from_kind", "index", "ok",
    "output", "reason", "start_line", "text", "to_kind",
]


def js_string(text, quote):
    """A JavaScript quoted string for `text` (an encoder that is independent of the script)."""
    body = text.replace("\\", "\\\\").replace(quote, "\\" + quote)
    body = body.replace("\n", "\\n").replace("\r", "\\r").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return quote + body + quote


def js_template(text):
    body = text.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${").replace("\r", "\\r")
    return "`" + body + "`"


class WriteBackTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name
        self.counter = 0

    def path(self, name):
        return os.path.join(self.dir, name)

    def write(self, name, data):
        mode = "wb" if isinstance(data, bytes) else "w"
        kwargs = {} if mode == "wb" else {"encoding": "utf-8", "newline": ""}
        with open(self.path(name), mode, **kwargs) as handle:
            handle.write(data)
        return self.path(name)

    def read(self, path):
        with open(path, "rb") as handle:
            return handle.read().decode("utf-8")

    def run_script(self, source, index, sql, extra=(), name="a.ts", output=None, raw=None):
        """Run the script. Returns (code, report or None, stdout, stderr, output text or None, source path)."""
        self.counter += 1
        file_path = self.write(name, source)
        sql_path = self.write("sql-%d.txt" % self.counter, sql)
        output = output or self.path("out-%d.ts" % self.counter)
        command = [sys.executable, SCRIPT, file_path] if raw is None else [sys.executable, SCRIPT] + raw
        if raw is None:
            command += ["--index", str(index), "--sql-file", sql_path, "--output", output]
        command += list(extra)
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)
        report = json.loads(result.stdout) if result.stdout.strip() else None
        text = self.read(output) if os.path.exists(output) else None
        return result.returncode, report, result.stdout, result.stderr, text, file_path

    def extract(self, path, extra=()):
        result = subprocess.run(
            [sys.executable, EXTRACTOR, path] + list(extra), capture_output=True, text=True, encoding="utf-8"
        )
        return json.loads(result.stdout)

    def assert_refused(self, source, index, sql, check, extra=(), name="a.ts"):
        code, report, _, _, text, file_path = self.run_script(source, index, sql, extra, name)
        self.assertEqual(code, 1, report)
        self.assertFalse(report["ok"])
        self.assertEqual(report["check"], check, report)
        self.assertTrue(report["reason"])
        self.assertIsNone(report["output"])
        self.assertFalse(report["changed"])
        self.assertIsNone(text)
        self.assertEqual(self.read(file_path), source)
        return report

    def assert_ok(self, source, index, sql, extra=(), name="a.ts"):
        code, report, _, _, text, file_path = self.run_script(source, index, sql, extra, name)
        self.assertEqual(code, 0, report)
        self.assertTrue(report["ok"], report)
        self.assertEqual(sorted(report), OK_KEYS)
        self.assertIsNone(report["check"])
        self.assertIsNone(report["reason"])
        self.assertEqual(self.read(file_path), source)
        return report, text


class RewriteFormsTest(WriteBackTestCase):
    def test_a_quoted_string_with_a_line_break_becomes_a_template(self):
        source = HEAD + "export const a = () => pool.query('select id from t where x = 1')\n"
        report, text = self.assert_ok(source, 0, "\n  select id\n  from t\n  where x = 1\n")
        self.assertEqual(
            text, HEAD + "export const a = () => pool.query(`\n  select id\n  from t\n  where x = 1\n`)\n"
        )
        self.assertEqual(report["from_kind"], "literal")
        self.assertEqual(report["to_kind"], "template")
        self.assertTrue(report["became_template"])
        self.assertTrue(report["changed"])
        self.assertEqual((report["start_line"], report["end_line"]), (3, 3))
        self.assertIsNone(report["const_name"])
        self.assertEqual(report["index"], 0)
        self.assertEqual(report["output"], self.path("out-1.ts"))
        self.assertEqual(report["file"], self.path("a.ts"))

    def test_a_quoted_string_with_no_line_break_keeps_its_quote(self):
        for quote in ("'", '"'):
            with self.subTest(quote=quote):
                source = HEAD + "export const a = () => pool.query(%s)\n" % js_string("select  id from t", quote)
                report, text = self.assert_ok(source, 0, "select id from t")
                self.assertEqual(text, HEAD + "export const a = () => pool.query(%s)\n" % js_string("select id from t", quote))
                self.assertEqual(report["to_kind"], "literal")
                self.assertFalse(report["became_template"])

    def test_a_chain_becomes_one_template_with_or_without_a_line_break(self):
        source = HEAD + "export const a = () => pool.query('select id ' +\n  'from t ' +\n  'where x = 1', [1])\n"
        report, text = self.assert_ok(source, 0, "\n  select id\n  from t\n  where x = 1\n")
        self.assertEqual(text, HEAD + "export const a = () => pool.query(`\n  select id\n  from t\n  where x = 1\n`, [1])\n")
        self.assertEqual((report["from_kind"], report["to_kind"], report["became_template"]), ("chain", "template", True))
        self.assertEqual((report["start_line"], report["end_line"]), (3, 5))
        report, text = self.assert_ok(source, 0, "select id from t where x = 1")
        self.assertEqual(text, HEAD + "export const a = () => pool.query(`select id from t where x = 1`, [1])\n")
        self.assertEqual(report["to_kind"], "template")

    def test_a_chain_with_a_template_piece_and_no_comment_is_rewritten(self):
        source = HEAD + "export const a = () => pool.query('select id ' + `from t`)\n"
        report, text = self.assert_ok(source, 0, "select id\nfrom t")
        self.assertEqual(text, HEAD + "export const a = () => pool.query(`select id\nfrom t`)\n")

    def test_an_untagged_template_keeps_its_kind(self):
        source = HEAD + "export const a = () => pool.query(`select id from t`)\n"
        report, text = self.assert_ok(source, 0, "select id from t")
        self.assertEqual(text, source)
        self.assertEqual((report["from_kind"], report["to_kind"], report["became_template"]), ("template", "template", False))
        self.assertFalse(report["changed"])
        report, text = self.assert_ok(source, 0, "\n  select id\n  from t\n")
        self.assertEqual(text, HEAD + "export const a = () => pool.query(`\n  select id\n  from t\n`)\n")
        self.assertTrue(report["changed"])

    def test_a_const_is_rewritten_once_at_its_definition_and_no_call_changes(self):
        source = HEAD + "const q = 'select id from t'\nexport const a = () => pool.query(q)\nexport const b = () => pool.query(q, [])\n"
        report, text = self.assert_ok(source, 0, "\n  select id\n  from t\n")
        self.assertEqual(
            text,
            HEAD + "const q = `\n  select id\n  from t\n`\nexport const a = () => pool.query(q)\nexport const b = () => pool.query(q, [])\n",
        )
        self.assertEqual(report["const_name"], "q")
        self.assertEqual((report["start_line"], report["end_line"]), (3, 3))

    def test_the_text_of_a_config_object_and_a_submittable_argument(self):
        source = (
            HEAD
            + "import Cursor from 'pg-cursor'\n"
            + "export const a = () => pool.query({ text: 'select id from t', values: [] })\n"
            + "export const b = () => pool.query(new Cursor('select 2'))\n"
            + "const cur = new Cursor('select 3')\n"
            + "export const c = () => pool.query(cur)\n"
        )
        statements = self.extract(self.write("a.ts", source))["statements"]
        self.assertEqual([s["pg"]["calls"][0]["call"] for s in statements], ["config", "submittable", "submittable"])
        _, text = self.assert_ok(source, 0, "select\n  id from t")
        self.assertIn("{ text: `select\n  id from t`, values: [] }", text)
        _, text = self.assert_ok(source, 1, "select  2")
        self.assertIn("new Cursor('select  2')", text)
        report, text = self.assert_ok(source, 2, "select\n3")
        self.assertIn("const cur = new Cursor(`select\n3`)", text)
        self.assertIsNone(report["const_name"])
        self.assertEqual(report["from_kind"], "literal")

    def test_nothing_outside_the_replaced_span_changes(self):
        source = HEAD + "// keep\nexport const a = () => pool.query('select 1', [1]) // tail\nexport const z = 'select 2'\n"
        _, text = self.assert_ok(source, 0, "select\n 1")
        self.assertEqual(text, HEAD + "// keep\nexport const a = () => pool.query(`select\n 1`, [1]) // tail\nexport const z = 'select 2'\n")

    def test_the_statement_index_counts_every_statement_of_the_file(self):
        source = HEAD + "export const a = () => pool.query('select 1')\nexport const b = () => pool.query('select 2')\n"
        _, text = self.assert_ok(source, 1, "select\n2")
        self.assertIn("pool.query('select 1')", text)
        self.assertIn("pool.query(`select\n2`)", text)

    def test_the_tags_and_receivers_are_passed_to_the_extractor(self):
        source = "export const a = () => db.query('select 1')\nexport const b = () => sql`select 2`\n"
        self.assert_refused(source, 0, "select 1", "not_pg", extra=["--tags", "sql"])
        self.assert_refused(source, 1, "select 1", "index", extra=["--tags", "sql"])
        report, text = self.assert_ok(source, 0, "select\n1", extra=["--receivers", "db"])
        self.assertIn("db.query(`select\n1`)", text)
        self.assert_refused(source, 1, "select 2", "not_pg", extra=["--receivers", "db", "--tags", "sql"])
        report, text = self.assert_ok(source, 0, "select\n1", extra=["--receivers", "db", "--tags", "sql"])
        self.assertIn("db.query(`select\n1`)", text)


class EscapeRoundTripTest(WriteBackTestCase):
    def check_template(self, old_sql, new_sql):
        for old in (js_string(old_sql, "'"), js_template(old_sql)):
            with self.subTest(old=old):
                source = HEAD + "export const a = () => pool.query(%s)\n" % old
                report, text = self.assert_ok(source, 0, new_sql)
                self.assertEqual(report["to_kind"], "template")
                path = self.write("rt.ts", text)
                statements = self.extract(path)["statements"]
                self.assertEqual(len(statements), 1)
                self.assertEqual(statements[0]["text"], new_sql)
                self.assertEqual(statements[0]["pg"]["kind"], "template")

    def test_a_template_escapes_a_backslash_a_backtick_and_a_dollar_brace(self):
        old = "select 'a\\b`c${x}d' from t"
        self.check_template(old, "\n  select 'a\\b`c${x}d'\n  from t\n")

    def test_a_template_writes_a_carriage_return_as_an_escape(self):
        old = "select 'a\rb' from t"
        self.check_template(old, "select\r\n  'a\rb' from t\n")

    def test_a_template_keeps_both_quotes_and_unicode_line_separators(self):
        old = "select 'it''s', \"c\", 'x\u2028y\u2029z' from t"
        self.check_template(old, "select\n  'it''s', \"c\", 'x\u2028y\u2029z'\nfrom t")

    def test_a_kept_quoted_string_escapes_its_quote_a_backslash_and_the_line_separators(self):
        old = "select 'a\\b', \"c\", 'x\u2028y\u2029z' from t"
        new = "select  'a\\b', \"c\", 'x\u2028y\u2029z' from t"
        for quote in ("'", '"'):
            with self.subTest(quote=quote):
                source = HEAD + "export const a = () => pool.query(%s)\n" % js_string(old, quote)
                report, text = self.assert_ok(source, 0, new)
                self.assertEqual(report["to_kind"], "literal")
                self.assertTrue(text.startswith(HEAD + "export const a = () => pool.query(" + quote))
                statements = self.extract(self.write("rt.ts", text))["statements"]
                self.assertEqual(statements[0]["text"], new)
                self.assertEqual(statements[0]["pg"]["kind"], "literal")
                self.assertEqual(text, HEAD + "export const a = () => pool.query(%s)\n" % js_string(new, quote))


class RefusalTest(WriteBackTestCase):
    def test_a_dynamic_statement_is_refused(self):
        source = HEAD + "export const a = (x: string) => pool.query(`select ${x} from t`)\nexport const b = (x: string) => pool.query('select ' + x)\n"
        for index in (0, 1):
            with self.subTest(index=index):
                self.assert_refused(source, index, "select 1", "dynamic")

    def test_a_statement_that_is_not_a_pg_statement_is_refused(self):
        source = HEAD + "export const a = () => pool.query('select 1')\nexport const b = () => sql`select 2`\n"
        self.assert_refused(source, 1, "select 2", "not_pg", extra=["--tags", "sql"])

    def test_an_index_out_of_range_is_refused(self):
        source = HEAD + "export const a = () => pool.query('select 1')\n"
        self.assert_refused(source, 1, "select 1", "index")
        self.assert_refused(source, 99, "select 1", "index")

    def test_a_chain_with_a_comment_between_its_pieces_is_refused(self):
        for glue in ("// why\n  ", "/* why */ "):
            with self.subTest(glue=glue):
                source = HEAD + "export const a = () => pool.query('select 1 ' +\n  " + glue + "'from t')\n"
                report = self.assert_refused(source, 0, "select 1\nfrom t", "chain_comment")
                self.assertEqual(report["from_kind"], "chain")
                self.assertEqual((report["start_line"], report["end_line"]), (3, 4 + glue.count("\n")))
        source = HEAD + "export const a = () => pool.query('select 1 ' + `from t` + // c\n 'where x = 1')\n"
        self.assert_refused(source, 0, "select 1 from t where x = 1", "chain_comment")

    def test_a_value_change_outside_whitespace_and_keyword_case_is_refused(self):
        old = "select id, name from t where a = 'x  y' and \"Col\" = 1 -- note  here\n"
        source = HEAD + "export const a = () => pool.query(%s)\n" % js_string(old, "'")
        changes = {
            "an identifier": old.replace("name", "nam"),
            "a function case": "select count(id) from t",
            "a non-keyword case": old.replace("name", "NAME"),
            "a string": old.replace("x  y", "x y"),
            "a quoted name": old.replace('"Col"', '"col"'),
            "a comment": old.replace("note  here", "note here"),
            "a number": old.replace("= 1", "= 2"),
            "an added AS": "select id, name as n from t where a = 'x  y' and \"Col\" = 1 -- note  here\n",
            "a dropped word": old.replace("and ", ""),
            "glued words": old.replace("select id", "selectid"),
        }
        source_op = HEAD + "export const a = () => pool.query(%s)\n" % js_string(
            "select a from t where a <= 1 and b >= 2", "'"
        )
        for label, new in changes.items():
            with self.subTest(change=label):
                report = self.assert_refused(source, 0, new, "value_changed")
                self.assertEqual(report["from_kind"], "literal")
        self.assert_refused(source_op, 0, "select a from t where a < = 1 and b >= 2", "value_changed")

    def test_only_an_ascii_fold_of_a_listed_keyword_is_allowed(self):
        source = HEAD + "export const a = () => pool.query('select id from t')\n"
        self.assert_refused(source, 0, "\u017felect id from t", "value_changed")
        report, text = self.assert_ok(source, 0, "SELECT id\nFROM t")
        self.assertIn("`SELECT id\nFROM t`", text)

    def test_a_case_change_of_a_keyword_and_whitespace_changes_are_allowed(self):
        old = "SELECT id FROM t WHERE a = 'x  y' AND b IS NULL -- c  d\nORDER BY id"
        source = HEAD + "export const a = () => pool.query(%s)\n" % js_string(old, "'")
        new = "select id\nfrom t\nwhere a = 'x  y'\n  and b is null -- c  d\norder by id"
        report, text = self.assert_ok(source, 0, new)
        self.assertTrue(report["became_template"])

    def test_adjacent_strings_keep_their_line_break_and_glued_prefixes_stay_glued(self):
        old = "select 'a'\n'b' from t"
        source = HEAD + "export const a = () => pool.query(%s)\n" % js_string(old, "'")
        self.assert_refused(source, 0, "select 'a' 'b' from t", "value_changed")
        self.assert_ok(source, 0, "select 'a'\n  'b'\nfrom t")
        source = HEAD + "export const a = () => pool.query('select b\\'1\\' from t')\n"
        self.assert_refused(source, 0, "select b '1' from t", "value_changed")
        old = "select 'a' 'b' from t"
        source = HEAD + "export const a = () => pool.query(%s)\n" % js_string(old, "'")
        self.assert_refused(source, 0, "select 'a'\n'b' from t", "value_changed")

    def test_white_space_inside_a_number_or_next_to_one_is_a_value_change(self):
        for old, new in (
            ("select .5 from t", "select . 5 from t"),
            ("select 1 a from t", "select 1a from t"),
            ("select 1a from t", "select 1 a from t"),
            ("select 1.5 from t", "select 1. 5 from t"),
            ("select $1 a from t", "select $1a from t"),
        ):
            with self.subTest(old=old, new=new):
                source = HEAD + "export const a = () => pool.query(%s)\n" % js_string(old, "'")
                self.assert_refused(source, 0, new, "value_changed")

    def test_the_unicode_escape_prefix_stays_glued_to_its_string_or_quoted_name(self):
        for old, new in (
            ('select U&"x" from t', 'select U & "x" from t'),
            ("select U&'a' from t", "select U &'a' from t"),
            ("select U&'a' from t", "select U& 'a' from t"),
            ('select U&"x" from t', 'select U&\n"x" from t'),
        ):
            with self.subTest(old=old, new=new):
                source = HEAD + "export const a = () => pool.query(%s)\n" % js_string(old, "'")
                self.assert_refused(source, 0, new, "value_changed")
        source = HEAD + "export const a = () => pool.query('select a & b, U&\\'a\\' from t')\n"
        self.assert_ok(source, 0, "select a&b,\n  U&'a'\nfrom t")

    def test_a_line_break_or_other_white_space_next_to_a_number_is_allowed(self):
        old = "select 1 + 2, x from t limit 10 offset 5"
        source = HEAD + "export const a = () => pool.query(%s)\n" % js_string(old, "'")
        self.assert_ok(source, 0, "select 1+2, x from t limit 10\noffset 5")

    def test_a_character_that_is_not_a_blank_is_a_value_change(self):
        source = HEAD + "export const a = () => pool.query('select 1')\n"
        self.assert_refused(source, 0, "select 1\u0000", "value_changed")


class UsageErrorTest(WriteBackTestCase):
    def usage(self, raw, extra_files=()):
        code, report, stdout, stderr, text, _ = self.run_script("", 0, "", raw=raw)
        self.assertEqual(code, 2, (stdout, stderr))
        self.assertEqual(stdout, "")
        self.assertEqual(len(stderr.strip().splitlines()), 1)

    def base(self, **changes):
        source = self.write("u.ts", HEAD + "export const a = () => pool.query('select 1')\n")
        sql = self.write("u.sql.txt", "select 1")
        values = {"file": source, "--index": "0", "--sql-file": sql, "--output": self.path("u-out.ts")}
        values.update(changes)
        raw = []
        if values["file"] is not None:
            raw.append(values["file"])
        for key in ("--index", "--sql-file", "--output"):
            if values[key] is not None:
                raw += [key, values[key]]
        return raw

    def test_each_usage_error_exits_with_code_two_and_prints_one_line_on_stderr(self):
        self.write("exists.ts", "x")
        self.write("bad.txt", b"\xff\xfe\x00")
        self.write("u.sql", "select 1;")
        cases = {
            "missing index": self.base(**{"--index": None}),
            "missing sql file": self.base(**{"--sql-file": None}),
            "missing output": self.base(**{"--output": None}),
            "no file": self.base(file=None),
            "extra positional": self.base() + ["more.ts"],
            "unknown option": self.base() + ["--nope", "1"],
            "repeated option": self.base() + ["--index", "1"],
            "non-integer index": self.base(**{"--index": "a"}),
            "negative index": self.base(**{"--index": "-1"}),
            "huge index": self.base(**{"--index": "1" * 5000}),
            "sql file extension": self.base(file=self.path("u.sql")),
            "not a file": self.base(file=self.path("nope.ts")),
            "output exists": self.base(**{"--output": self.path("exists.ts")}),
            "output is the file": self.base(**{"--output": self.path("u.ts")}),
            "missing sql file path": self.base(**{"--sql-file": self.path("nope.txt")}),
            "sql file not utf-8": self.base(**{"--sql-file": self.path("bad.txt")}),
            "empty tags": self.base() + ["--tags", ""],
            "empty receivers": self.base() + ["--receivers", ""],
            "bad tag name": self.base() + ["--tags", "a,"],
            "bad receiver name": self.base() + ["--receivers", "a b"],
        }
        for label, raw in cases.items():
            with self.subTest(case=label):
                self.usage(raw)
        for path in ("u-out.ts",):
            self.assertFalse(os.path.exists(self.path(path)))

    def test_an_uppercase_extension_is_accepted(self):
        source = HEAD + "export const a = () => pool.query('select 1')\n"
        self.assert_ok(source, 0, "select 1", name="A.TS")

    def test_an_unreadable_source_is_an_extract_refusal(self):
        self.assert_refused("import pg from 'pg'\nconst a = `select\n", 0, "select 1", "extract")


class FileTextTest(WriteBackTestCase):
    def test_a_bom_and_crlf_line_ends_stay_outside_the_replaced_span(self):
        source = "\ufeff" + HEAD.replace("\n", "\r\n") + "export const a = () => pool.query('select 1')\r\nexport const z = 1\r\n"
        _, text = self.assert_ok(source, 0, "select\n1")
        self.assertEqual(
            text, "\ufeff" + HEAD.replace("\n", "\r\n") + "export const a = () => pool.query(`select\n1`)\r\nexport const z = 1\r\n"
        )
        statements = self.extract(self.write("crlf.ts", text))["statements"]
        self.assertEqual(statements[0]["text"], "select\n1")

    def test_a_multibyte_file_keeps_its_other_text(self):
        source = HEAD + "// caf\u00e9 \U0001f600\nexport const a = () => pool.query('select 1')\n// \u00fcber\n"
        _, text = self.assert_ok(source, 0, "select\n1")
        self.assertEqual(text, HEAD + "// caf\u00e9 \U0001f600\nexport const a = () => pool.query(`select\n1`)\n// \u00fcber\n")


class TailRuleTest(WriteBackTestCase):
    """The Write tool strips trailing spaces, so the script adds the indent of the opening line."""

    def test_a_quoted_string_gets_the_indent_of_its_line(self):
        source = HEAD + "export const a = () =>\n  pool.query('select id from t where x = 1')\n"
        report, text = self.assert_ok(source, 0, "\n    select id\n    from t\n    where x = 1\n")
        self.assertEqual(
            text, HEAD + "export const a = () =>\n  pool.query(`\n    select id\n    from t\n    where x = 1\n  `)\n"
        )
        self.assertEqual(self.extract(self.write("o.ts", text))["statements"][0]["text"], "\n    select id\n    from t\n    where x = 1\n  ")

    def test_a_chain_gets_the_indent_of_the_line_of_its_first_piece(self):
        source = HEAD + "export const a = () =>\n  pool.query(\n    'select id ' +\n      'from t',\n    [1],\n  )\n"
        _, text = self.assert_ok(source, 0, "\n        select id\n        from t\n")
        self.assertEqual(
            text,
            HEAD + "export const a = () =>\n  pool.query(\n    `\n        select id\n        from t\n    `,\n    [1],\n  )\n",
        )

    def test_a_const_at_column_zero_gets_no_indent_and_a_const_uses_its_definition_line(self):
        source = HEAD + "const q = 'select id from t'\nexport const a = () => pool.query(q)\n"
        _, text = self.assert_ok(source, 0, "\n  select id\n  from t\n")
        self.assertEqual(text, HEAD + "const q = `\n  select id\n  from t\n`\nexport const a = () => pool.query(q)\n")
        indented = HEAD + "function f() {\n\tconst q = 'select id from t'\n\treturn pool.query(q)\n}\n"
        _, text = self.assert_ok(indented, 0, "\n\tselect id\n\tfrom t\n")
        self.assertIn("\tconst q = `\n\tselect id\n\tfrom t\n\t`\n", text)

    def test_a_wrong_indent_after_the_last_line_feed_is_replaced(self):
        source = HEAD + "export const a = () =>\n  pool.query('select id')\n"
        _, text = self.assert_ok(source, 0, "\n    select id\n            ")
        self.assertIn("select id\n  `)", text)

    def test_a_template_that_is_already_laid_out_is_not_changed(self):
        source = HEAD + "export const a = () =>\n  pool.query(`\n    select 1\n  `)\n"
        report, text = self.assert_ok(source, 0, "\n    select 1\n")
        self.assertFalse(report["changed"])
        self.assertEqual(text, source)

    def test_a_value_with_no_line_feed_and_a_kept_quoted_string_get_no_indent(self):
        source = HEAD + "export const a = () =>\n  pool.query('select id ' + 'from t')\n"
        _, text = self.assert_ok(source, 0, "select id from t")
        self.assertIn("pool.query(`select id from t`)", text)
        source = HEAD + "export const a = () =>\n  pool.query('select id from t')\n"
        _, text = self.assert_ok(source, 0, "select id from t")
        self.assertIn("pool.query('select id from t')", text)

    def test_a_value_with_only_carriage_returns_gets_no_indent(self):
        source = HEAD + "export const a = () =>\n  pool.query('select 1')\n"
        report, text = self.assert_ok(source, 0, "select\r1  ")
        self.assertIn("pool.query(`select\\r1  `)", text)
        self.assertEqual(report["to_kind"], "template")

    def test_a_crlf_file_gets_an_indent_with_no_carriage_return(self):
        source = HEAD.replace("\n", "\r\n") + "export const a = () =>\r\n  pool.query('select id')\r\nexport const z = 1\r\n"
        _, text = self.assert_ok(source, 0, "\nselect id\n")
        self.assertIn("pool.query(`\nselect id\n  `)\r\nexport const z = 1\r\n", text)

    def test_the_tail_rule_does_not_hide_a_value_change(self):
        self.assert_refused(HEAD + "export const a = () =>\n  pool.query('select id')\n", 0, "\n  select name\n", "value_changed")


class StdoutTest(WriteBackTestCase):
    SOURCE = HEAD + "export const a = () =>\n  pool.query('select id from t')\n"
    SQL = "\n    select id\n    from t\n"

    def run_stdout(self, source, sql, position="last", name="s.ts", extra=()):
        file_path = self.write(name, source)
        sql_path = self.write("s.sql.txt", sql)
        options = ["--index", "0", "--sql-file", sql_path]
        if position == "last":
            raw = [file_path] + options + list(extra) + ["--stdout"]
        elif position == "first":
            raw = ["--stdout", file_path] + options + list(extra)
        else:
            raw = [file_path, "--stdout"] + options + list(extra)
        result = subprocess.run(
            [sys.executable, SCRIPT] + raw, capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL
        )
        return result, file_path

    def test_the_json_holds_the_file_text_and_no_file_is_written(self):
        _, with_output = self.assert_ok(self.SOURCE, 0, self.SQL)
        for position in ("last", "first", "middle"):
            with self.subTest(position=position):
                result, file_path = self.run_stdout(self.SOURCE, self.SQL, position)
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(sorted(report), OK_KEYS)
                self.assertTrue(report["ok"])
                self.assertIsNone(report["output"])
                self.assertTrue(report["changed"])
                self.assertEqual(report["text"], with_output)
                self.assertEqual(self.read(file_path), self.SOURCE)
                self.assertEqual(sorted(os.listdir(self.dir)).count("s.ts"), 1)

    def test_the_text_is_given_when_nothing_changes_and_keeps_a_bom_and_crlf(self):
        source = "﻿" + HEAD.replace("\n", "\r\n") + "export const a = () => pool.query('select 1')\r\n"
        result, _ = self.run_stdout(source, "select 1")
        report = json.loads(result.stdout)
        self.assertFalse(report["changed"])
        self.assertEqual(report["text"], source)

    def test_the_text_is_null_with_output_and_for_a_refusal(self):
        report, _ = self.assert_ok(self.SOURCE, 0, self.SQL)
        self.assertIsNone(report["text"])
        result, _ = self.run_stdout(self.SOURCE, "\n  select name\n")
        self.assertEqual(result.returncode, 1)
        refusal = json.loads(result.stdout)
        self.assertEqual(refusal["check"], "value_changed")
        self.assertIsNone(refusal["text"])
        self.assertIsNone(refusal["output"])

    def test_a_repeated_stdout_and_a_missing_or_double_destination_are_usage_errors(self):
        file_path = self.write("u.ts", self.SOURCE)
        sql_path = self.write("u.sql.txt", self.SQL)
        base = [file_path, "--index", "0", "--sql-file", sql_path]
        cases = {
            "stdout twice": base + ["--stdout", "--stdout"],
            "stdout and output": base + ["--stdout", "--output", self.path("u-out.ts")],
            "neither": base,
            "output without value": base + ["--output", "--stdout"],
        }
        for label, raw in cases.items():
            with self.subTest(case=label):
                result = subprocess.run(
                    [sys.executable, SCRIPT] + raw, capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL
                )
                self.assertEqual(result.returncode, 2, (result.stdout, result.stderr))
                self.assertEqual(result.stdout, "")
                self.assertEqual(len(result.stderr.strip().splitlines()), 1)
        self.assertFalse(os.path.exists(self.path("u-out.ts")))

    def test_an_output_that_cannot_be_written_gives_exit_two_and_the_fixed_text(self):
        code, report, stdout, stderr, text, file_path = self.run_script(
            self.SOURCE, 0, self.SQL, output=os.path.join(self.path("no-such-folder"), "out.ts")
        )
        self.assertEqual(code, 2, (stdout, stderr))
        self.assertEqual(stdout, "")
        self.assertTrue(stderr.startswith("cannot write output file:"), stderr)
        self.assertEqual(len(stderr.strip().splitlines()), 1)
        self.assertEqual(self.read(file_path), self.SOURCE)

    def test_the_json_is_utf_8_whatever_the_locale(self):
        source = HEAD + "export const a = () =>\n  pool.query('select é from t')\n"
        file_path = self.write("l.ts", source)
        sql_path = self.write("l.sql.txt", "\nselect\n  é\nfrom t\n")
        env = {"PATH": os.environ["PATH"], "LC_ALL": "C", "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0"}
        result = subprocess.run(
            [sys.executable, SCRIPT, file_path, "--index", "0", "--sql-file", sql_path, "--stdout"],
            capture_output=True, env=env, stdin=subprocess.DEVNULL,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout.decode("utf-8"))
        self.assertIn("select\n  é\nfrom t", report["text"])

    def test_an_output_that_is_a_dangling_symlink_is_a_usage_error(self):
        file_path = self.write("d.ts", self.SOURCE)
        sql_path = self.write("d.sql.txt", self.SQL)
        link = self.path("dangling.ts")
        os.symlink(self.path("target.ts"), link)
        result = subprocess.run(
            [sys.executable, SCRIPT, file_path, "--index", "0", "--sql-file", sql_path, "--output", link],
            capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL,
        )
        self.assertEqual(result.returncode, 2, (result.stdout, result.stderr))
        self.assertEqual(result.stdout, "")
        self.assertFalse(os.path.exists(self.path("target.ts")))

    def test_a_failed_write_leaves_no_partial_output_file(self):
        import resource
        import signal

        def limit():
            signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
            resource.setrlimit(resource.RLIMIT_FSIZE, (10, 10))

        file_path = self.write("w.ts", self.SOURCE)
        sql_path = self.write("w.sql.txt", self.SQL)
        output = self.path("w-out.ts")
        result = subprocess.run(
            [sys.executable, SCRIPT, file_path, "--index", "0", "--sql-file", sql_path, "--output", output],
            capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL, preexec_fn=limit,
        )
        self.assertEqual(result.returncode, 2, (result.stdout, result.stderr))
        self.assertTrue(result.stderr.startswith("cannot write output file:"), result.stderr)
        self.assertFalse(os.path.lexists(output))

    def test_a_refusal_comes_before_the_write_failure(self):
        code, report, stdout, stderr, _, _ = self.run_script(
            self.SOURCE, 0, "\n  select name\n", output=os.path.join(self.path("no-such-folder"), "out.ts")
        )
        self.assertEqual(code, 1)
        self.assertEqual(report["check"], "value_changed")


class GroupedAndAsConstTest(WriteBackTestCase):
    def test_a_grouped_string_template_and_chain_keep_their_parentheses(self):
        cases = [
            ("('select  id from t')", "(`select id from t`)", "select id from t", "literal"),
            ("(('select  id from t'))", "((`select id from t`))", "select id from t", "literal"),
            ("(`select  id from t`)", "(`select id from t`)", "select id from t", "template"),
            ("('select  id ' + 'from t')", "(`select id from t`)", "select id from t", "chain"),
            ("((('select ' + 'id')))", "(((`select id`)))", "select id", "chain"),
        ]
        for old, new, sql, kind in cases:
            with self.subTest(old=old):
                source = HEAD + "export const a = () => pool.query(%s)\n" % old
                if kind == "literal":
                    new = new.replace("`", "'")
                report, text = self.assert_ok(source, 0, sql)
                self.assertEqual(text, HEAD + "export const a = () => pool.query(%s)\n" % new)
                self.assertEqual(report["from_kind"], kind)

    def test_a_grouped_string_with_a_line_break_becomes_a_template_inside_the_group(self):
        source = HEAD + "export const a = () => pool.query(('select id from t'), [1])\n"
        report, text = self.assert_ok(source, 0, "\nselect id\nfrom t\n")
        self.assertEqual(text, HEAD + "export const a = () => pool.query((`\nselect id\nfrom t\n`), [1])\n")
        self.assertTrue(report["became_template"])
        self.assertEqual(self.extract(self.write("o.ts", text))["statements"][0]["text"], "\nselect id\nfrom t\n")

    def test_a_multi_line_group_gets_the_indent_of_the_line_of_the_inner_value(self):
        source = HEAD + "export const a = () =>\n  pool.query((\n    'select id ' +\n    'from t'\n  ))\n"
        _, text = self.assert_ok(source, 0, "\n      select id\n      from t\n")
        self.assertEqual(
            text,
            HEAD + "export const a = () =>\n  pool.query((\n    `\n      select id\n      from t\n    `\n  ))\n",
        )
        self.assertEqual(
            self.extract(self.write("o.ts", text))["statements"][0]["text"], "\n      select id\n      from t\n    "
        )

    def test_a_const_with_an_as_const_tail_is_rewritten_with_its_tail_and_annotation(self):
        for definition, new in (
            ("const q = 'select  id from t' as const", "const q = 'select id from t' as const"),
            ("const q: string = 'select  id from t' as const", "const q: string = 'select id from t' as const"),
            ("const q: string = `select  id` as const", "const q: string = `select id` as const"),
            ("const q = 'select ' + 'id' as const", "const q = `select id` as const"),
        ):
            with self.subTest(definition):
                source = HEAD + definition + "\nexport const a = () => pool.query(q)\n"
                sql = "select id from t" if "from t" in definition else "select id"
                report, text = self.assert_ok(source, 0, sql)
                self.assertEqual(text, HEAD + new + "\nexport const a = () => pool.query(q)\n")
                self.assertEqual(report["const_name"], "q")

    def test_an_as_const_const_with_a_line_break_keeps_its_tail(self):
        source = HEAD + "const q: string = 'select id from t' as const\nexport const a = () => pool.query(q)\n"
        _, text = self.assert_ok(source, 0, "\n  select id\n  from t\n")
        self.assertEqual(
            text,
            HEAD + "const q: string = `\n  select id\n  from t\n` as const\nexport const a = () => pool.query(q)\n",
        )

    def test_a_dynamic_grouped_form_is_refused_and_writes_no_file(self):
        source = (
            HEAD
            + "export const a = (x: string) => pool.query(('select ' + x))\n"
            + "export const b = (x: string) => pool.query((`select ${x}`))\n"
        )
        for index in (0, 1):
            with self.subTest(index=index):
                self.assert_refused(source, index, "select 1", "dynamic")

    def test_a_value_change_in_a_grouped_form_is_refused_and_writes_no_file(self):
        source = (
            HEAD
            + "export const a = () => pool.query(('select id from t'))\n"
            + "const q = 'select 1' as const\npool.query(q)\n"
        )
        self.assert_refused(source, 0, "select name from t", "value_changed")
        self.assert_refused(source, 1, "select 2", "value_changed")

    def test_a_grouped_chain_with_a_comment_is_refused(self):
        source = HEAD + "export const a = () => pool.query(('select id ' + /* c */ 'from t'))\n"
        self.assert_refused(source, 0, "select id from t", "chain_comment")


if __name__ == "__main__":
    unittest.main()
