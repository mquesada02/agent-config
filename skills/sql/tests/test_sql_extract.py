import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
SCRIPT = os.path.join(SKILL_DIR, "scripts", "extract.py")

KEYS = ["file", "form", "detected_tags", "factory_names", "tags", "statements", "error"]
STATEMENT_KEYS = ["tag", "start_line", "end_line", "text", "parent", "interpolations"]


class ExtractTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def write(self, name, content, binary=False):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as handle:
            handle.write(content if binary else content.encode("utf-8"))
        return path

    def run_args(self, *args):
        env = {"PATH": os.environ["PATH"], "HOME": self.dir}
        return subprocess.run(
            [sys.executable, "-I", SCRIPT, *args], capture_output=True, text=True, env=env
        )

    def extract(self, content, name="a.ts", tags=None, expect=0):
        path = self.write(name, content)
        args = [path]
        if tags is not None:
            args += ["--tags", tags]
        result = self.run_args(*args)
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def positions(self, body, tag="sql"):
        """Positions of the interpolations of the first statement of `tag`<body>."""
        data = self.extract(tag + "`" + body + "`;\n", tags=tag)
        self.assertGreaterEqual(len(data["statements"]), 1, data)
        return [i["position"] for i in data["statements"][0]["interpolations"]]

    def sql_positions(self, text):
        data = self.extract(text, name="q.sql")
        self.assertEqual(len(data["statements"]), 1, data)
        return [i["position"] for i in data["statements"][0]["interpolations"]]

    def detected(self, content, tags=None):
        return self.extract(content, tags=tags)["detected_tags"]


class ContractOutputTest(ExtractTestCase):
    def test_all_keys_for_both_forms(self):
        for name, content in (("a.ts", "const x = 1;\n"), ("a.sql", "SELECT 1;\n")):
            with self.subTest(name=name):
                data = self.extract(content, name=name)
                self.assertEqual(sorted(data), sorted(KEYS))
                self.assertIsNone(data["error"])
                self.assertEqual(data["form"], "sql" if name.endswith(".sql") else "js")
                self.assertTrue(data["file"].endswith(name))

    def test_a_template_has_its_fields(self):
        src = "const q = sql`\n  SELECT 1\n  WHERE id = ${id}\n`;\n"
        data = self.extract(src, tags="sql")
        self.assertEqual(data["tags"], ["sql"])
        statement = data["statements"][0]
        self.assertEqual(sorted(statement), sorted(STATEMENT_KEYS))
        self.assertEqual(statement["tag"], "sql")
        self.assertEqual((statement["start_line"], statement["end_line"]), (1, 4))
        self.assertEqual(statement["text"], "\n  SELECT 1\n  WHERE id = ${id}\n")
        self.assertIsNone(statement["parent"])
        self.assertEqual(
            statement["interpolations"],
            [{"line": 3, "column": 14, "expression": "id", "position": "value"}],
        )

    def test_the_expression_is_stripped(self):
        data = self.extract("sql`WHERE a = ${  id\n }`;\n", tags="sql")
        self.assertEqual(data["statements"][0]["interpolations"][0]["expression"], "id")

    def test_crlf_counts_a_line_once_and_lone_cr_is_not_a_line_end(self):
        data = self.extract("const a = 1;\r\nconst q = sql`\r\nSELECT 1\r\n`;\r\n", tags="sql")
        self.assertEqual(data["statements"][0]["start_line"], 2)
        self.assertEqual(data["statements"][0]["end_line"], 4)
        data = self.extract("const a = 1;\rconst q = sql`x`;\n", tags="sql")
        self.assertEqual(data["statements"][0]["start_line"], 1)

    def test_a_bom_is_ignored(self):
        path = self.write("b.ts", b"\xef\xbb\xbfconst q = sql`x`;\n", binary=True)
        result = self.run_args(path, "--tags", "sql")
        data = json.loads(result.stdout)
        self.assertEqual(len(data["statements"]), 1)
        self.assertEqual(data["statements"][0]["start_line"], 1)

    def test_a_column_counts_code_points(self):
        data = self.extract("const e = '\U0001F600\t'; const q = sql`a ${x}`;\n", tags="sql")
        column = data["statements"][0]["interpolations"][0]["column"]
        line = "const e = '\U0001F600\t'; const q = sql`a ${x}`;"
        self.assertEqual(column, line.index("${") + 1)


class TagListTest(ExtractTestCase):
    def test_sql_this_sql_and_tx(self):
        src = "sql`a`; this.sql`b`; tx`c`; other`d`;\n"
        data = self.extract(src, tags="sql,this.sql,tx")
        self.assertEqual([s["tag"] for s in data["statements"]], ["sql", "this.sql", "tx"])
        self.assertEqual(data["tags"], ["sql", "this.sql", "tx"])

    def test_the_whole_chain_must_match(self):
        data = self.extract("db.sql`a`; sql`b`;\n", tags="sql")
        self.assertEqual([s["text"] for s in data["statements"]], ["b"])

    def test_no_tags_uses_the_detected_tags(self):
        src = "import postgres from 'postgres';\nconst db = postgres(u);\ndb`a`; sql`b`;\n"
        data = self.extract(src)
        self.assertEqual(data["tags"], ["db"])
        self.assertEqual([s["tag"] for s in data["statements"]], ["db"])

    def test_tags_narrow_the_run_and_echo_clean(self):
        src = "import postgres from 'postgres';\nconst db = postgres(u);\ndb`a`; sql`b`;\n"
        data = self.extract(src, tags=" sql , sql,db ")
        self.assertEqual(data["tags"], ["sql", "db"])
        self.assertEqual([s["tag"] for s in data["statements"]], ["db", "sql"])
        self.assertEqual(data["detected_tags"], ["db"])

    def test_type_arguments_and_white_space_before_the_backtick(self):
        for tag_text in (
            "sql<Row[]>",
            "sql<Record<string, X[]>>",
            "sql<(a: X) => Y>",
            "sql<<T>() => X>",
            "sql\n  ",
            "sql /* c */ ",
            "sql<Row[]> /* c */ ",
        ):
            with self.subTest(tag=tag_text):
                data = self.extract("const q = " + tag_text + "`SELECT 1`;\n", tags="sql")
                self.assertEqual([s["text"] for s in data["statements"]], ["SELECT 1"])

    def test_an_unbalanced_type_argument_list_is_no_tag(self):
        data = self.extract("const q = sql<Row`SELECT 1`;\n", tags="sql")
        self.assertEqual(data["statements"], [])

    def test_a_chain_after_a_call_or_index_is_not_a_tag_chain(self):
        data = self.extract("getDb().sql`a`; list[0].sql`b`; x.getDb().sql`c`;\n", tags="sql")
        self.assertEqual(data["statements"], [])


class DetectionTest(ExtractTestCase):
    def test_variable_forms(self):
        cases = {
            "const sql = postgres(u);": ["sql"],
            "let db = postgres(u);": ["db"],
            "var q = await postgres(u);": ["q"],
            "export const sql = postgres(u);": ["sql"],
            "const sql: Sql<{}> = postgres(u);": ["sql"],
            "const sql: Sql<Record<string, number>> = postgres<{}>(u);": [],
            "let db;\ndb = postgres(u);": ["db"],
            "const a = postgres;": [],
            "const sql = other(u);": [],
        }
        for src, expected in cases.items():
            with self.subTest(src=src):
                self.assertEqual(self.detected(src + "\n"), expected)

    def test_member_forms(self):
        cases = {
            "this.sql = postgres(u);": ["this.sql"],
            "a.b.c = await postgres(u);": ["a.b.c"],
        }
        for src, expected in cases.items():
            with self.subTest(src=src):
                self.assertEqual(self.detected(src + "\n"), expected)

    def test_class_fields(self):
        for src, expected in (
            ("class A { sql = postgres(u); }", ["this.sql"]),
            ("class A { private sql = postgres(u); }", ["this.sql"]),
            ("class A { public readonly db: Sql = postgres(u); }", ["this.db"]),
            ("class A { protected db = postgres(u); }", ["this.db"]),
            ("class A { static sql = postgres(u); }", []),
            ("class A { m() { sql = postgres(u); } }", ["sql"]),
            ("class A { m() { if (x) { sql = postgres(u); } } }", ["sql"]),
            ("class A { m = () => { sql = postgres(u); }; }", ["sql"]),
            ("class A { sql = postgres(u); } sql2 = postgres(u);", ["this.sql", "sql2"]),
        ):
            with self.subTest(src=src):
                self.assertEqual(self.detected(src + "\n"), expected)

    def test_a_typed_parameter_is_not_a_tag(self):
        for src, expected in (
            ("class A { constructor(url: string) { this.db = postgres(url); } }", ["this.db"]),
            ("function f(url: string) { return g; }\nconst sql = postgres(u);", ["sql"]),
            ("function f(a: X, b: Y = 1) { const sql = postgres(u); }", ["sql"]),
        ):
            with self.subTest(src=src):
                self.assertEqual(self.detected(src + "\n"), expected)

    def test_a_brace_in_a_class_type_argument_is_not_the_class_body(self):
        src = "class A extends B<{ a: 1 }> {\n  z = postgres(u);\n}\n"
        self.assertEqual(self.detected(src), ["this.z"])

    def test_nested_type_arguments_and_arrow_types_in_a_class_header(self):
        for header in (
            "class A extends B<C<D>> {",
            "class A extends B<() => void> {",
            "class A extends B<{ f: (x: number) => { y: 1 } }> {",
        ):
            with self.subTest(header=header):
                self.assertEqual(self.detected(header + "\n  sql = postgres(u);\n}\n"), ["this.sql"])

    def test_the_word_class_that_is_not_a_class_keyword_opens_no_class_body(self):
        body = "function f() {\n  z = postgres(u);\n}\n"
        for head in (
            'const o = { class: "a" };\n',
            "x.class;\n",
            "x?.class;\n",
            "const { class } = o;\n",
            "const o = { class() {} };\n",
        ):
            with self.subTest(head=head):
                self.assertEqual(self.detected(head + body), ["z"])

    def test_a_class_with_a_call_in_its_header_still_has_a_body(self):
        src = "class A extends mix(B) {\n  z = postgres(u);\n}\nclass extends C {\n  y = postgres(u);\n}\n"
        self.assertEqual(self.detected(src), ["this.z", "this.y"])

    def test_a_brace_inside_the_class_header_is_not_the_class_body(self):
        for header in (
            "class A extends mk({ a: 1 }) {",
            "class A extends (B as { x: 1 }) {",
            "class A extends mk([{ a: 1 }]) {",
        ):
            with self.subTest(header=header):
                self.assertEqual(self.detected(header + "\n  sql = postgres(u);\n}\n"), ["this.sql"])

    def test_a_member_assignment_gives_only_the_chain(self):
        self.assertEqual(self.detected("this.sql = postgres(u);\n"), ["this.sql"])

    def test_import_forms_and_factory_names(self):
        cases = {
            "import postgres from 'postgres';": ["postgres"],
            'import pg from "postgres";': ["pg"],
            "import pg, { x } from 'postgres';": ["pg"],
            "import { default as pg } from 'postgres';": ["pg"],
            "const pg = require('postgres');": ["pg"],
            'let pg = require("postgres");': ["pg"],
            "var pg = require('postgres');": ["pg"],
            "import * as pg from 'postgres';": [],
            "const { default: pg } = require('postgres');": [],
            "import type pg from 'postgres';": [],
            "const pg = await import('postgres');": [],
            "import pg from 'other';": [],
        }
        for src, names in cases.items():
            with self.subTest(src=src):
                data = self.extract(src + "\n")
                self.assertEqual(data["factory_names"], names)

    def test_an_alias_is_a_factory_name_for_variables(self):
        src = "import pg from 'postgres';\nconst db = pg(u);\n"
        self.assertEqual(self.detected(src), ["db"])
        self.assertEqual(self.detected("const db = pg(u);\n"), [])

    def test_the_import_counts_wherever_it_sits(self):
        src = "const db = pg(u);\nimport pg from 'postgres';\n"
        self.assertEqual(self.detected(src), ["db"])

    def test_a_require_called_right_away_is_a_variable_form(self):
        data = self.extract("const sql = require('postgres')(url);\n")
        self.assertEqual(data["detected_tags"], ["sql"])
        self.assertEqual(data["factory_names"], [])

    def test_begin_callbacks(self):
        cases = {
            "sql.begin(tx => {});": ["tx"],
            "sql.begin(async tx => {});": ["tx"],
            "sql.begin(async (tx) => {});": ["tx"],
            "sql.begin((tx: TransactionSql) => {});": ["tx"],
            "sql.begin('read write', async tx => {});": ["tx"],
            "sql.begin(function (tx) {});": ["tx"],
            "sql.begin(async function named(tx) {});": ["tx"],
            "sql.begin(({ a }) => {});": [],
            "sql.begin(() => {});": [],
            "other.begin(tx => {});": [],
        }
        for call, extra in cases.items():
            with self.subTest(call=call):
                src = "const sql = postgres(u);\n" + call + "\n"
                self.assertEqual(self.detected(src), ["sql"] + extra)

    def test_a_nested_begin_on_a_detected_tag(self):
        src = "const sql = postgres(u);\nsql.begin(async tx => { await tx.begin(async t2 => {}); });\n"
        self.assertEqual(self.detected(src), ["sql", "tx", "t2"])

    def test_detected_tags_follow_the_text_position(self):
        src = (
            "const sql = postgres(u);\nconst other = postgres(u);\n"
            "sql.begin(async tx => { await tx.begin(async t2 => {}); });\n"
            "other.begin(async u => {});\n"
        )
        self.assertEqual(self.detected(src), ["sql", "other", "tx", "t2", "u"])

    def test_begin_depends_on_tags_and_a_given_tag_is_not_detected_by_itself(self):
        src = "sql.begin(tx => {});\n"
        self.assertEqual(self.detected(src), [])
        data = self.extract(src, tags="sql")
        self.assertEqual(data["detected_tags"], ["tx"])
        self.assertEqual(data["tags"], ["sql"])

    def test_forms_in_comments_strings_and_templates_are_ignored(self):
        src = (
            "// const a = postgres(u);\n/* const b = postgres(u); */\n"
            "const s = 'const c = postgres(u);';\n"
            "const t = `const d = postgres(u);`;\n"
            "const r = /const e = postgres(u);/;\n"
        )
        self.assertEqual(self.detected(src), [])
        self.assertEqual(self.extract(src)["factory_names"], [])
        src = "// import pg from 'postgres';\nconst s = \"import pg from 'postgres';\";\n"
        self.assertEqual(self.extract(src)["factory_names"], [])

    def test_the_tag_this_sql_is_usable(self):
        src = "class A { sql = postgres(u); f() { return this.sql`SELECT 1`; } }\n"
        data = self.extract(src)
        self.assertEqual([s["tag"] for s in data["statements"]], ["this.sql"])


class ExclusionTest(ExtractTestCase):
    def test_no_statement_from_comments_strings_and_regular_expressions(self):
        cases = {
            "line comment": "// sql`SELECT 1`\n",
            "block comment": "/* sql`SELECT 1` */\n",
            "single quoted": "const a = 'sql`SELECT 1`';\n",
            "double quoted": 'const a = "sql`SELECT 1`";\n',
            "regular expression": "const a = /sql`SELECT 1`/;\n",
            "class in regular expression": "const a = /[/]sql`SELECT 1`/;\n",
            "after return": "function f() { return /sql`SELECT 1`/; }\n",
            "backtick in string": "const a = '`'; const b = \"`\";\n",
        }
        for name, src in cases.items():
            with self.subTest(name=name):
                self.assertEqual(self.extract(src, tags="sql")["statements"], [])

    def test_code_after_a_comment_or_string_still_matches(self):
        src = "// sql`no`\nconst a = 'x'; sql`yes`;\n"
        data = self.extract(src, tags="sql")
        self.assertEqual([s["text"] for s in data["statements"]], ["yes"])

    def test_a_string_that_reaches_a_line_end_ends_there(self):
        data = self.extract("const a = 'open;\nsql`yes`;\n", tags="sql")
        self.assertEqual([s["text"] for s in data["statements"]], ["yes"])

    def test_a_regular_expression_that_reaches_a_line_end_ends_there(self):
        data = self.extract("const a = i++ / 2;\nsql`yes`;\n", tags="sql")
        self.assertEqual([s["text"] for s in data["statements"]], ["yes"])


class TokenizerTest(ExtractTestCase):
    def test_escaped_backtick_and_escaped_interpolation(self):
        data = self.extract("sql`a \\` b \\${x} c ${y}`;\n", tags="sql")
        statement = data["statements"][0]
        self.assertEqual(statement["text"], "a \\` b \\${x} c ${y}")
        self.assertEqual([i["expression"] for i in statement["interpolations"]], ["y"])

    def test_a_digit_like_character_that_is_not_a_digit_is_one_token(self):
        # "²" is True for str.isdigit() but is not matched by the number pattern.
        data = self.extract("select a ² from t;\n", name="q.sql")
        self.assertEqual(len(data["statements"]), 1)
        data = self.extract("const sql = postgres(u);\nsql`select a ² ${x}`;\n", tags="sql")
        self.assertEqual(data["error"], None)
        self.assertEqual(len(data["statements"]), 1)
        data = self.extract("const a = 2 ²;\nconst sql = postgres(u);\n")
        self.assertEqual(data["detected_tags"], ["sql"])

    def test_a_js_name_follows_str_isidentifier_plus_dollar(self):
        for name in ("śql", "l·l", "\U0001d49c", "$q", "a$b"):
            with self.subTest(name=name):
                self.assertTrue(name.replace("$", "_").isidentifier())
                src = "const %s = postgres(u);\n%s`select 1`;\n" % (name, name)
                self.assertEqual(self.detected(src), [name])
        data = self.extract("const sq² = postgres(u);\nsq²`select 1`;\n")
        self.assertEqual(data["detected_tags"], [])

    def test_the_js_scanner_and_the_tag_check_agree_on_what_a_name_is(self):
        for text in ("é", "a1", "$x", "a·b", "1a", "a²", "śql", "Ⅷ"):
            with self.subTest(text=text):
                src = "const %s = postgres(u);\n%s`select 1`;\n" % (text, text)
                is_name = text.replace("$", "_").isidentifier()
                self.assertEqual(self.detected(src), [text] if is_name else [])

    def test_an_escaped_quote_in_a_string(self):
        data = self.extract("const a = 'it\\'s'; sql`yes`;\n", tags="sql")
        self.assertEqual(len(data["statements"]), 1)

    def test_division_and_regular_expression_after_each_token(self):
        for token in ("return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
                      "throw", "case", "do", "else", "yield", "await"):
            with self.subTest(token=token):
                src = token + " /sql`SELECT 1`/;\nsql`yes`;\n"
                data = self.extract(src, tags="sql")
                self.assertEqual([s["text"] for s in data["statements"]], ["yes"])
        for before in ("a", "1", ")", "]", "}", "'s'", "`t`"):
            with self.subTest(before=before):
                src = "const x = " + before + " / 2; sql`yes`; /* sql`no` */\n"
                data = self.extract(src, tags="sql")
                self.assertEqual([s["text"] for s in data["statements"]], ["yes"])
        for before in ("{", ";", "(", ",", "=", "+"):
            with self.subTest(before=before):
                src = "x " + before + " /sql`no`/; sql`yes`;\n"
                data = self.extract(src, tags="sql")
                self.assertEqual([s["text"] for s in data["statements"]], ["yes"])

    def test_a_regular_expression_at_the_start_of_the_file(self):
        data = self.extract("/sql`no`/.test(x); sql`yes`;\n", tags="sql")
        self.assertEqual([s["text"] for s in data["statements"]], ["yes"])

    def test_a_comment_between_the_tag_and_the_backtick(self):
        data = self.extract("sql // c\n`SELECT 1`;\n", tags="sql")
        self.assertEqual(len(data["statements"]), 1)

    def test_a_column_after_a_non_bmp_character(self):
        data = self.extract("sql`\U0001F600${x}`;\n", tags="sql")
        self.assertEqual(data["statements"][0]["interpolations"][0]["column"], 6)

    def test_a_dollar_after_a_word_still_starts_an_interpolation(self):
        data = self.extract("sql`a${x}`;\n", tags="sql")
        self.assertEqual(len(data["statements"][0]["interpolations"]), 1)
        data = self.extract("SELECT a${x};\n", name="q.sql")
        self.assertEqual(len(data["statements"][0]["interpolations"]), 1)


class NestingTest(ExtractTestCase):
    def test_a_reported_template_inside_another_has_a_parent(self):
        src = "const q = sql`A ${c ? sql`AND b` : sql``} ORDER BY id`;\n"
        data = self.extract(src, tags="sql")
        self.assertEqual([s["text"] for s in data["statements"]], ["A ${c ? sql`AND b` : sql``} ORDER BY id", "AND b", ""])
        self.assertEqual([s["parent"] for s in data["statements"]], [None, 0, 0])
        self.assertEqual(len(data["statements"][0]["interpolations"]), 1)
        self.assertEqual(data["statements"][0]["interpolations"][0]["position"], "fragment")

    def test_the_outer_list_holds_only_its_own_interpolations(self):
        src = "sql`A ${c ? sql`AND a = ${x}` : sql``}`;\n"
        data = self.extract(src, tags="sql")
        self.assertEqual(len(data["statements"][0]["interpolations"]), 1)
        self.assertEqual([i["expression"] for i in data["statements"][1]["interpolations"]], ["x"])
        self.assertEqual(data["statements"][1]["interpolations"][0]["position"], "value")

    def test_the_nearest_reported_template_is_the_parent(self):
        src = "sql`a ${sql`b ${sql`c`}`}`;\n"
        data = self.extract(src, tags="sql")
        self.assertEqual([s["parent"] for s in data["statements"]], [None, 0, 1])

    def test_a_template_inside_an_untagged_template(self):
        src = "const t = `x ${sql`SELECT 1`} y`; other`z ${sql`q`}`;\n"
        data = self.extract(src, tags="sql")
        self.assertEqual([s["text"] for s in data["statements"]], ["SELECT 1", "q"])
        self.assertEqual([s["parent"] for s in data["statements"]], [None, None])

    def test_strings_and_braces_inside_an_interpolation(self):
        for expression in ("'}'", '"}"', "'`'", "`}`", "{ a: 1 }.a", "f({ b: { c: 1 } })", "/}/.test(x)"):
            with self.subTest(expression=expression):
                data = self.extract("sql`a ${" + expression + "} b`;\n", tags="sql")
                statement = data["statements"][0]
                self.assertEqual(statement["text"], "a ${" + expression + "} b")
                self.assertEqual(statement["interpolations"][0]["expression"], expression)

    def test_helper_calls_as_expressions(self):
        src = "sql`WHERE id IN ${sql(ids)} AND (a, b) IN ${sql(rows, 'a', 'b')}`;\n"
        data = self.extract(src, tags="sql")
        self.assertEqual(
            [(i["expression"], i["position"]) for i in data["statements"][0]["interpolations"]],
            [("sql(ids)", "value"), ("sql(rows, 'a', 'b')", "value")],
        )


class PositionTest(ExtractTestCase):
    VALUE_WORDS = [
        "SELECT", "DISTINCT", "FROM", "JOIN", "ON", "USING", "WHERE", "AND", "OR", "NOT", "IN",
        "EXISTS", "ANY", "ALL", "BY", "SET", "VALUES", "INTO", "UPDATE", "LIMIT", "OFFSET",
        "RETURNING", "CASE", "WHEN", "THEN", "ELSE", "IS", "LIKE", "BETWEEN", "AS",
    ]
    CLAUSE_STARTS = [
        "WHERE", "AND", "OR", "JOIN", "INNER", "LEFT", "RIGHT", "FULL", "CROSS", "NATURAL",
        "GROUP", "ORDER", "HAVING", "LIMIT", "OFFSET", "UNION", "RETURNING",
    ]

    def test_contract_examples(self):
        self.assertEqual(self.positions("WHERE id = ${id}"), ["value"])
        self.assertEqual(self.positions("ORDER BY ${sql(col)}"), ["value"])
        self.assertEqual(
            self.positions("WHERE a = 1 ${active ? sql`AND active` : sql``} ORDER BY id"),
            ["fragment"],
        )
        self.assertEqual(self.positions("${sel} * FROM users"), ["keyword"])
        self.assertEqual(self.positions("FROM t ${dir} BY id"), ["keyword"])

    def test_every_value_word(self):
        for word in self.VALUE_WORDS:
            for text in (word, word.lower()):
                with self.subTest(word=text):
                    self.assertEqual(self.positions("x " + text + " ${v} y"), ["value"])

    def test_operators_parenthesis_and_comma_before(self):
        for before in ("=", "<>", "||", "::", "+", "-", "<=", "~*", "->>", "@>"):
            with self.subTest(before=before):
                self.assertEqual(self.positions("a " + before + " ${v}"), ["value"])
        self.assertEqual(self.positions("f(${a}, ${b})"), ["value", "value"])
        self.assertEqual(self.positions("f(a,${b})"), ["value"])

    def test_the_star_rule(self):
        self.assertEqual(self.positions("SELECT a * ${x}"), ["value"])
        self.assertEqual(self.positions("SELECT * ${f}"), ["fragment"])
        self.assertEqual(self.positions("SELECT * ${f} FROM t"), ["keyword"])
        self.assertEqual(self.positions("SELECT a, * ${f}"), ["fragment"])
        self.assertEqual(self.positions("SELECT t.* ${f}"), ["fragment"])
        self.assertEqual(self.positions("SELECT *, ${x}"), ["value"])
        self.assertEqual(self.positions("SELECT DISTINCT * ${f}"), ["value"])
        self.assertEqual(self.positions("SELECT count(*) ${f}"), ["fragment"])

    def test_the_start_of_a_template_is_keyword(self):
        self.assertEqual(self.positions("${x} a"), ["keyword"])
        self.assertEqual(self.positions("  -- c\n ${x}"), ["keyword"])

    def test_just_before_a_closing_parenthesis(self):
        self.assertEqual(self.positions("AND (a = 1 ${f})"), ["fragment"])
        self.assertEqual(self.positions("(${x})"), ["value"])

    def test_after_end(self):
        self.assertEqual(self.positions("SELECT CASE WHEN a THEN 1 END ${f}"), ["fragment"])
        self.assertEqual(self.positions("SELECT CASE WHEN a THEN 1 END ${x} FROM t"), ["keyword"])
        self.assertEqual(self.positions("SELECT CASE WHEN a THEN 1 END ${f} ORDER BY id"), ["fragment"])

    def test_a_fragment_before_each_clause_start_and_the_end(self):
        for word in self.CLAUSE_STARTS:
            with self.subTest(word=word):
                self.assertEqual(self.positions("a = 1 ${f} " + word + " x"), ["fragment"])
        self.assertEqual(self.positions("a = 1 ${f}"), ["fragment"])
        self.assertEqual(self.positions("a = 1 ${f}   -- c\n"), ["fragment"])
        self.assertEqual(self.positions("INSERT INTO t VALUES (1) ${f} ON CONFLICT DO NOTHING"), ["fragment"])
        self.assertEqual(self.positions("a = 1 ${f} ON t.id = 1"), ["keyword"])
        self.assertEqual(self.positions("a = 1 ${f} lower(x)"), ["keyword"])

    def test_complete_tokens_before_a_fragment(self):
        for before in ("a", "t.a", '"Quoted"', "'str'", "42", "1.5", "$1", "NULL", "TRUE", ")", "$$x$$"):
            with self.subTest(before=before):
                self.assertEqual(self.positions("x " + before + " ${f} ORDER BY id"), ["fragment"])

    def test_not_complete_tokens_give_keyword(self):
        for before in ("GROUP", "ORDER", "CONFLICT", "[", ".", ";", "]"):
            with self.subTest(before=before):
                self.assertEqual(self.positions("x " + before + " ${f} ORDER BY id"), ["keyword"])
        self.assertEqual(self.positions("ARRAY[${a}, ${b}]"), ["keyword", "value"])

    def test_two_interpolations_in_a_row(self):
        self.assertEqual(self.positions("WHERE a = 1 ${f1} ${f2}"), ["keyword", "fragment"])
        self.assertEqual(self.positions("a = ${x}${y}"), ["value", "fragment"])
        self.assertEqual(self.positions("a = 1 ${f1} ${f2} ORDER BY id"), ["keyword", "fragment"])

    def test_inside_a_string_a_quoted_identifier_or_a_comment_is_keyword(self):
        for body in (
            "WHERE a = 'x ${v}'",
            "WHERE a = E'x ${v}'",
            'WHERE a = "x ${v}"',
            "WHERE a = $q$ x ${v} $q$",
            "WHERE a = 1 -- ${v}\n",
            "WHERE a = 1 /* ${v} */",
            "WHERE a = 1 /* a /* ${v} */ b */",
            "WHERE a = 'x ${v}",
            "WHERE a = 1 /* ${v}",
        ):
            with self.subTest(body=body):
                self.assertEqual(self.positions(body), ["keyword"])

    def test_a_string_with_escaped_quotes_keeps_the_scan_in_step(self):
        self.assertEqual(self.positions("WHERE a = 'it''s' AND b = ${v}"), ["value"])
        self.assertEqual(self.positions("WHERE a = E'it\\'s ' AND b = ${v}"), ["value"])
        self.assertEqual(self.positions('WHERE "a""b" = ${v}'), ["value"])
        self.assertEqual(self.positions("WHERE a = shoe'x' AND b = ${v}"), ["value"])

    def test_other_characters_give_keyword(self):
        self.assertEqual(self.positions("x { ${f}"), ["keyword"])
        self.assertEqual(self.positions("${f} }"), ["keyword"])
        self.assertEqual(self.positions("a € ${f}"), ["keyword"])

    def test_a_dollar_quote_and_a_parameter_take_the_dollar_first(self):
        self.assertEqual(self.positions("WHERE a = $1 AND b = ${v}"), ["value"])
        self.assertEqual(self.positions("WHERE a = $a$ x $a$ AND b = ${v}"), ["value"])

    def test_lower_case_clause_starts(self):
        self.assertEqual(self.positions("a = 1 ${f} order by id"), ["fragment"])


class SqlFormTest(ExtractTestCase):
    def test_a_sql_word_follows_the_name_rule(self):
        # Each name ends a complete token, so the interpolation before the end is a fragment.
        for name in ("á", "Ⅷ", "\U0001d49c", "a$b"):
            with self.subTest(name=name):
                self.assertTrue(name.replace("$", "_").isidentifier())
                self.assertEqual(self.sql_positions("select 1 from %s ${x}\n" % name), ["fragment"])
        # A character that is not a name character is a token of its own kind.
        self.assertEqual(self.sql_positions("select 1 from a² ${x}\n"), ["keyword"])

    def test_statements_and_line_ranges(self):
        text = "-- head\nSELECT 1;\n\nSELECT\n  2\n  FROM t;\n"
        data = self.extract(text, name="q.sql")
        self.assertEqual(data["form"], "sql")
        self.assertEqual([(s["start_line"], s["end_line"]) for s in data["statements"]], [(2, 2), (4, 6)])
        self.assertEqual([s["text"] for s in data["statements"]], ["SELECT 1", "SELECT\n  2\n  FROM t"])
        for statement in data["statements"]:
            self.assertIsNone(statement["tag"])
            self.assertIsNone(statement["parent"])
        for key in ("detected_tags", "factory_names", "tags"):
            self.assertEqual(data[key], [])

    def test_a_semicolon_inside_a_construct_does_not_split(self):
        for text in (
            "SELECT 'a;b';",
            "SELECT E'a\\';b';",
            "SELECT e'a\\';b';",
            "SELECT $$a;b$$;",
            "SELECT $q$a;b$q$;",
            'SELECT "a;b" FROM t;',
            "SELECT 1 -- a;b\n;",
            "SELECT 1 /* a; /* b; */ c; */;",
            "SELECT 'a''b;c';",
        ):
            with self.subTest(text=text):
                data = self.extract(text + "\n", name="q.sql")
                self.assertEqual(len(data["statements"]), 1, data)

    def test_comment_only_text_is_not_a_statement(self):
        data = self.extract("-- only\n/* more */\n;\n  ;\n", name="q.sql")
        self.assertEqual(data["statements"], [])

    def test_no_final_semicolon(self):
        data = self.extract("SELECT 1;\nSELECT 2", name="q.sql")
        self.assertEqual([s["text"] for s in data["statements"]], ["SELECT 1", "SELECT 2"])

    def test_a_comment_inside_the_range_stays_and_outside_does_not(self):
        data = self.extract("/* a */ SELECT 1 /* b */ , 2 -- c\n;\n", name="q.sql")
        self.assertEqual(data["statements"][0]["text"], "SELECT 1 /* b */ , 2")

    def test_the_last_token_may_span_lines(self):
        text = "CREATE FUNCTION f() RETURNS int AS $$\nSELECT 1;\n$$ LANGUAGE sql;\nSELECT 2;\n"
        data = self.extract(text, name="q.sql")
        self.assertEqual([(s["start_line"], s["end_line"]) for s in data["statements"]], [(1, 3), (4, 4)])
        text = "SELECT $$a\nb$$;\n"
        self.assertEqual(self.extract(text, name="q.sql")["statements"][0]["end_line"], 2)

    def test_placeholders_have_positions(self):
        text = "SELECT 1 FROM t WHERE id = ${id} ${f} ORDER BY ${ { a: 1 }.a };\n"
        data = self.extract(text, name="q.sql")
        interpolations = data["statements"][0]["interpolations"]
        self.assertEqual([i["position"] for i in interpolations], ["value", "fragment", "value"])
        self.assertEqual(interpolations[2]["expression"], "{ a: 1 }.a")
        self.assertEqual(interpolations[0]["line"], 1)

    def test_a_placeholder_in_a_string_or_comment_is_keyword(self):
        self.assertEqual(self.sql_positions("SELECT 'a ${v}';"), ["keyword"])
        self.assertEqual(self.sql_positions("SELECT 1 -- ${v}\n , 2;"), ["keyword"])
        self.assertEqual(self.sql_positions('SELECT "a${v}";'), ["keyword"])
        self.assertEqual(self.sql_positions("SELECT $$a${v}$$;"), ["keyword"])

    def test_a_placeholder_outside_every_statement_is_in_no_list(self):
        text = "-- note ${x}\nSELECT 1; /* ${y} */\nSELECT 2; -- ${z}\n"
        data = self.extract(text, name="q.sql")
        self.assertEqual([s["interpolations"] for s in data["statements"]], [[], []])

    def test_a_placeholder_in_a_line_comment_wins_over_the_line_end(self):
        text = "SELECT 1 -- a ${ {\n} } still comment\n, 2;\n"
        data = self.extract(text, name="q.sql")
        self.assertEqual(len(data["statements"]), 1)
        self.assertEqual(data["statements"][0]["text"], "SELECT 1 -- a ${ {\n} } still comment\n, 2")

    def test_an_unterminated_construct_runs_to_the_end(self):
        data = self.extract("SELECT 'a;\nSELECT 2;\n", name="q.sql")
        self.assertEqual(len(data["statements"]), 1)
        data = self.extract("SELECT 1; /* open;\nSELECT 2;", name="q.sql")
        self.assertEqual([s["text"] for s in data["statements"]], ["SELECT 1"])

    def test_the_extension_is_read_case_insensitively(self):
        self.assertEqual(self.extract("SELECT 1;", name="Q.SQL")["form"], "sql")
        self.assertEqual(self.extract("sql`a`;", name="A.TS", tags="sql")["form"], "js")


class ExtensionTest(ExtractTestCase):
    def test_every_js_extension(self):
        for ext in (".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx"):
            with self.subTest(ext=ext):
                data = self.extract("sql`a`;\n", name="f" + ext, tags="sql")
                self.assertEqual(data["form"], "js")
                self.assertEqual(len(data["statements"]), 1)


class TagsOptionTest(ExtractTestCase):
    def usage_error(self, *args):
        result = self.run_args(*args)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.strip().splitlines()), 1, result.stderr)

    def test_bad_tags_values_are_usage_errors(self):
        path = self.write("a.ts", "sql`a`;\n")
        for value in ("a,,b", "a,", ",a", "", "a-b", "1a", "a..b", ".a", "a.", "a b"):
            with self.subTest(value=value):
                self.usage_error(path, "--tags", value)

    def test_the_form_with_an_equals_sign_and_abbreviations_are_unknown_options(self):
        path = self.write("a.ts", "sql`a`;\n")
        self.usage_error(path, "--tags=sql")
        self.usage_error(path, "--tag", "sql")

    def test_tags_with_no_value_and_repeated_options(self):
        path = self.write("a.ts", "sql`a`;\n")
        self.usage_error(path, "--tags")
        self.usage_error(path, "--tags", "a", "--tags", "b")

    def test_tags_may_come_before_the_file(self):
        path = self.write("a.ts", "sql`a`;\n")
        result = self.run_args("--tags", "sql", path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)["statements"]), 1)

    def test_a_sql_file_accepts_tags_and_ignores_them(self):
        path = self.write("q.sql", "SELECT 1;\n")
        result = self.run_args(path, "--tags", "sql,this.sql")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["tags"], [])
        self.usage_error(path, "--tags", "a,,b")

    def test_a_dollar_may_start_a_name_and_this_is_a_chain_start(self):
        path = self.write("a.ts", "$q`a`; this.sql`b`;\n")
        result = self.run_args(path, "--tags", "$q,this.sql")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)["statements"]), 2)


class ErrorTest(ExtractTestCase):
    def failure(self, src, name="a.ts", tags="sql"):
        data = self.extract(src, name=name, tags=tags, expect=1)
        self.assertEqual(data["statements"], [])
        self.assertEqual(data["detected_tags"], [])
        self.assertEqual(data["factory_names"], [])
        self.assertEqual(data["tags"], [])
        self.assertTrue(data["error"]["message"])
        return data["error"]["line"]

    def test_an_unterminated_template(self):
        self.assertEqual(self.failure("const a = 1;\nconst q = sql`SELECT 1\n"), 2)

    def test_an_unterminated_interpolation(self):
        self.assertEqual(self.failure("const a = 1;\nconst q = `x\n${ a\n"), 2)

    def test_an_unterminated_block_comment(self):
        self.assertEqual(self.failure("const a = 1;\n\n/* open\n"), 3)

    def test_the_outer_construct_is_reported(self):
        self.assertEqual(self.failure("sql`select\n ${a"), 1)
        self.assertEqual(self.failure("`x ${ f(/* open\n"), 1)

    def test_an_unclosed_placeholder_in_a_sql_file(self):
        self.assertEqual(self.failure("SELECT 1;\nSELECT ${a\n", name="q.sql"), 2)
        self.assertEqual(self.failure("-- ${a\nSELECT 1;\n", name="q.sql"), 1)

    def test_a_missing_file(self):
        result = self.run_args(os.path.join(self.dir, "missing.ts"))
        self.assertEqual(result.returncode, 1)
        data = json.loads(result.stdout)
        self.assertIsNone(data["error"]["line"])
        self.assertEqual(data["statements"], [])

    def test_a_missing_file_with_an_unsupported_extension_is_a_usage_error(self):
        result = self.run_args(os.path.join(self.dir, "missing.txt"))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")

    def test_an_unreadable_file(self):
        if os.geteuid() == 0:
            self.skipTest("root can read any file")
        path = self.write("locked.ts", "sql`a`;\n")
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o600)
        result = self.run_args(path)
        self.assertEqual(result.returncode, 1)
        self.assertIsNone(json.loads(result.stdout)["error"]["line"])

    def test_invalid_utf8(self):
        path = self.write("bad.ts", b"const a = '\xff\xfe';\n", binary=True)
        result = self.run_args(path)
        self.assertEqual(result.returncode, 1)
        self.assertIsNone(json.loads(result.stdout)["error"]["line"])

    def test_usage_errors(self):
        a = self.write("a.ts", "x\n")
        b = self.write("b.ts", "x\n")
        c = self.write("c.txt", "x\n")
        for args in ((), (a, b), (a, "--unknown"), (a, "--tags", ""), (c,), (a, "--tags", "a", c)):
            with self.subTest(args=args):
                result = self.run_args(*args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_usage_checks_run_before_the_file_is_read(self):
        result = self.run_args(os.path.join(self.dir, "missing.ts"), "--tags", "a,,b")
        self.assertEqual(result.returncode, 2)

    def test_a_deeply_nested_template_does_not_crash(self):
        depth = 400
        src = "sql`" + "${sql`" * depth + "x" + "`}" * depth + "`;\n"
        result = self.run_args(self.write("deep.ts", src), "--tags", "sql")
        self.assertIn(result.returncode, (0, 1), result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(json.loads(result.stdout)["form"], "js")


if __name__ == "__main__":
    unittest.main()
