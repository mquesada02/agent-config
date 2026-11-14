import json
import unittest

from test_sql_extract import ExtractTestCase


class PgCase(ExtractTestCase):
    def pg(self, content, receivers=None, tags=None, name="a.ts", expect=0):
        path = self.write(name, content)
        args = [path]
        if tags is not None:
            args += ["--tags", tags]
        if receivers is not None:
            args += ["--receivers", receivers]
        result = self.run_args(*args)
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def pg_statements(self, content, **options):
        data = self.pg(content, **options)
        return [s for s in data["statements"] if s["source"] == "pg"]

    def one(self, content, **options):
        found = self.pg_statements(content, **options)
        self.assertEqual(len(found), 1, found)
        return found[0]


class ReceiverFormsTest(PgCase):
    """Each receiver form, from each import form, gives one pg statement."""

    IMPORT_FORMS = [
        ("require destructure", "const { Pool } = require('pg');\nconst pool = new Pool();\n"),
        ("require double quotes", 'const { Pool } = require("pg");\nconst pool = new Pool();\n'),
        ("require rename", "const { Pool: P } = require('pg');\nconst pool = new P();\n"),
        ("require member", "const Pool = require('pg').Pool;\nconst pool = new Pool();\n"),
        ("require object", "const pg = require('pg');\nconst pool = new pg.Pool();\n"),
        ("require native", "const pg = require('pg').native;\nconst pool = new pg.Pool();\n"),
        ("object native", "const pg = require('pg');\nconst pool = new pg.native.Pool();\n"),
        ("native alias", "const pg = require('pg');\nconst native = pg.native;\nconst pool = new native.Pool();\n"),
        ("native destructure", "const { native } = require('pg');\nconst pool = new native.Pool();\n"),
        ("destructure from native", "const pg = require('pg');\nconst { Pool } = pg.native;\nconst pool = new Pool();\n"),
        ("destructure from object", "import pg from 'pg';\nconst { Pool } = pg;\nconst pool = new Pool();\n"),
        ("import default", "import pg from 'pg';\nconst pool = new pg.Pool();\n"),
        ("import namespace", 'import * as pg from "pg";\nconst pool = new pg.Pool();\n'),
        ("import named", "import { Pool } from 'pg';\nconst pool = new Pool();\n"),
        ("import named rename", "import { Pool as P } from 'pg';\nconst pool = new P();\n"),
        ("import default and named", "import pg, { Pool } from 'pg';\nconst pool = new Pool();\n"),
        ("import equals", "import pg = require('pg');\nconst pool = new pg.Pool();\n"),
    ]

    def test_each_import_form_gives_a_pool_receiver(self):
        for label, head in self.IMPORT_FORMS:
            with self.subTest(label):
                data = self.pg(head + "pool.query('SELECT 1');\n")
                self.assertEqual(data["detected_receivers"], ["pool"])
                self.assertEqual(data["receivers"], ["pool"])
                self.assertEqual([s["text"] for s in data["statements"]], ["SELECT 1"])

    def test_a_client_is_a_receiver_too(self):
        for head in (
            "import { Client } from 'pg';\nconst db = new Client();\n",
            "const pg = require('pg');\nconst db = new pg.Client({ a: 1 });\n",
            "const pg = require('pg');\nconst db = new pg.native.Client();\n",
        ):
            with self.subTest(head):
                data = self.pg(head + "db.query('SELECT 1');\n")
                self.assertEqual(data["detected_receivers"], ["db"])
                self.assertEqual(len(data["statements"]), 1)

    def test_a_constructor_that_does_not_come_from_pg_is_not_a_receiver(self):
        data = self.pg("import { Pool } from 'other';\nconst pool = new Pool();\npool.query('SELECT 1');\n")
        self.assertEqual(data["detected_receivers"], [])
        self.assertEqual(data["statements"], [])

    def test_a_pool_without_any_pg_import_is_not_a_receiver(self):
        data = self.pg("const pool = new Pool();\npool.query('SELECT 1');\n")
        self.assertEqual(data["detected_receivers"], [])
        self.assertEqual(data["statements"], [])

    def test_a_typed_declaration(self):
        head = "import { Pool } from 'pg';\nconst pool: Pool = new Pool();\n"
        data = self.pg(head + "pool.query('SELECT 1');\n")
        self.assertEqual(data["detected_receivers"], ["pool"])

    def test_a_plain_assignment(self):
        head = "import { Pool } from 'pg';\nlet pool;\npool = new Pool();\n"
        self.assertEqual(self.pg(head + "pool.query('SELECT 1');\n")["detected_receivers"], ["pool"])

    def test_member_forms_and_class_fields(self):
        head = "import { Pool } from 'pg';\n"
        cases = [
            ("this member", head + "class A {\n  constructor() { this.pool = new Pool(); }\n  run() { this.pool.query('SELECT 1'); }\n}\n", "this.pool"),
            ("class field", head + "class A {\n  private pool = new Pool();\n  run() { this.pool.query('SELECT 1'); }\n}\n", "this.pool"),
            ("typed class field", head + "class A {\n  pool: Pool = new Pool();\n  run() { this.pool.query('SELECT 1'); }\n}\n", "this.pool"),
            ("object member", head + "const db = {};\ndb.pool = new Pool();\ndb.pool.query('SELECT 1');\n", "db.pool"),
        ]
        for label, content, receiver in cases:
            with self.subTest(label):
                data = self.pg(content)
                self.assertEqual(data["detected_receivers"], [receiver])
                self.assertEqual([s["text"] for s in data["statements"]], ["SELECT 1"])

    def test_a_static_field_and_an_object_key_are_not_receivers(self):
        head = "import { Pool } from 'pg';\n"
        for label, content in (
            ("static", head + "class A {\n  static pool = new Pool();\n  run() { this.pool.query('SELECT 1'); }\n}\n"),
            ("object key", head + "const o = { pool: new Pool() };\npool.query('SELECT 1');\n"),
        ):
            with self.subTest(label):
                data = self.pg(content)
                self.assertEqual(data["detected_receivers"], [])
                self.assertEqual(data["statements"], [])

    def test_a_client_from_await_connect(self):
        head = "import { Pool } from 'pg';\nconst pool = new Pool();\n"
        data = self.pg(head + "async function f() {\n  const client = await pool.connect();\n  await client.query('SELECT 1');\n}\n")
        self.assertEqual(data["detected_receivers"], ["pool", "client"])
        self.assertEqual([s["text"] for s in data["statements"]], ["SELECT 1"])

    def test_connect_without_await_is_not_a_client(self):
        head = "import { Pool } from 'pg';\nconst pool = new Pool();\n"
        data = self.pg(head + "const p = pool.connect();\np.query('SELECT 1');\n")
        self.assertEqual(data["detected_receivers"], ["pool"])
        self.assertEqual(data["statements"], [])

    def test_the_parameter_of_the_connect_then_callback(self):
        head = "import { Pool } from 'pg';\nconst pool = new Pool();\n"
        for callback in (
            "client => client.query('SELECT 1')",
            "(client) => client.query('SELECT 1')",
            "async (client) => { await client.query('SELECT 1'); }",
            "function (client) { client.query('SELECT 1'); }",
            "(client: PoolClient): void => { client.query('SELECT 1'); }",
        ):
            with self.subTest(callback):
                data = self.pg(head + "pool.connect().then(" + callback + ");\n")
                self.assertEqual(data["detected_receivers"], ["pool", "client"])
                self.assertEqual(len(data["statements"]), 1)

    def test_the_second_parameter_of_the_connect_callback(self):
        head = "import { Pool } from 'pg';\nconst pool = new Pool();\n"
        for callback in (
            "(err, client, release) => { client.query('SELECT 1'); }",
            "function (err, client, done) { client.query('SELECT 1'); }",
            "async (err, client) => { client.query('SELECT 1'); }",
            "(err: Error, client: PoolClient, done: () => void) => { client.query('SELECT 1'); }",
        ):
            with self.subTest(callback):
                data = self.pg(head + "pool.connect(" + callback + ");\n")
                self.assertEqual(data["detected_receivers"], ["pool", "client"])
                self.assertEqual(len(data["statements"]), 1)

    def test_a_callback_with_too_few_parameters_gives_no_receiver(self):
        head = "import { Pool } from 'pg';\nconst pool = new Pool();\n"
        data = self.pg(head + "pool.connect((err) => { err.query('SELECT 1'); });\n")
        self.assertEqual(data["detected_receivers"], ["pool"])
        self.assertEqual(data["statements"], [])

    def test_a_client_from_a_member_pool(self):
        content = (
            "import { Pool } from 'pg';\nclass A {\n  pool = new Pool();\n  async f() {\n"
            "    this.client = await this.pool.connect();\n    this.client.query('SELECT 1');\n  }\n}\n"
        )
        data = self.pg(content)
        self.assertEqual(data["detected_receivers"], ["this.pool", "this.client"])
        self.assertEqual(len(data["statements"]), 1)

    def test_detected_receivers_are_in_the_order_of_their_binding(self):
        content = "import { Pool, Client } from 'pg';\nconst b = new Pool();\nconst a = new Client();\nconst b2 = new Pool();\n"
        self.assertEqual(self.pg(content)["detected_receivers"], ["b", "a", "b2"])

    def test_a_receiver_bound_twice_is_listed_once(self):
        content = "import { Pool } from 'pg';\nlet pool = new Pool();\npool = new Pool();\n"
        self.assertEqual(self.pg(content)["detected_receivers"], ["pool"])


class OnlyReceiverQueryTest(PgCase):
    HEAD = "import { Pool } from 'pg';\nconst pool = new Pool();\n"

    def test_query_on_another_object_gives_no_statement(self):
        data = self.pg(self.HEAD + "search.query('SELECT 1');\nthis.graphql.query('SELECT 1');\na.pool.query('SELECT 1');\n")
        self.assertEqual(data["statements"], [])

    def test_another_method_of_the_receiver_gives_no_statement(self):
        data = self.pg(self.HEAD + "pool.end('SELECT 1');\npool.execute('SELECT 1');\n")
        self.assertEqual(data["statements"], [])

    def test_optional_chaining_and_type_arguments(self):
        data = self.pg(self.HEAD + "pool?.query('SELECT 1');\npool.query<Row>('SELECT 2');\npool.query<Array<Row>>('SELECT 3');\n")
        self.assertEqual([s["text"] for s in data["statements"]], ["SELECT 1", "SELECT 2", "SELECT 3"])

    def test_optional_chaining_on_a_member_receiver(self):
        content = "import { Pool } from 'pg';\nclass A {\n  pool = new Pool();\n  f() { this.pool?.query('SELECT 1'); }\n}\n"
        self.assertEqual(len(self.pg(content)["statements"]), 1)

    def test_a_call_with_no_argument_gives_no_statement(self):
        self.assertEqual(self.pg(self.HEAD + "pool.query();\n")["statements"], [])

    def test_a_postgres_js_tag_named_like_the_receiver_is_not_a_receiver(self):
        data = self.pg("const sql = postgres();\nsql.query('SELECT 1');\n")
        self.assertEqual(data["statements"], [])


class ReceiversOptionTest(PgCase):
    HEAD = "import { Pool } from 'pg';\nconst pool = new Pool();\n"

    def test_the_given_list_adds_to_the_detected_receivers(self):
        data = self.pg(self.HEAD + "pool.query('SELECT 1');\ndb.query('SELECT 2');\n", receivers="db")
        self.assertEqual(data["detected_receivers"], ["pool"])
        self.assertEqual(data["receivers"], ["pool", "db"])
        self.assertEqual([s["text"] for s in data["statements"]], ["SELECT 1", "SELECT 2"])

    def test_the_given_list_never_drops_a_detected_receiver(self):
        data = self.pg(self.HEAD + "pool.query('SELECT 1');\n", receivers="other")
        self.assertEqual(data["receivers"], ["pool", "other"])
        self.assertEqual(len(data["statements"]), 1)

    def test_a_given_receiver_that_is_detected_is_listed_once(self):
        data = self.pg(self.HEAD + "pool.query('SELECT 1');\n", receivers="pool")
        self.assertEqual(data["receivers"], ["pool"])

    def test_without_the_option_receivers_are_the_detected_ones(self):
        data = self.pg(self.HEAD)
        self.assertEqual(data["receivers"], data["detected_receivers"])

    def test_a_member_form_is_matched_exactly(self):
        data = self.pg("this.db.query('SELECT 1');\nthat.db.query('SELECT 2');\n", receivers="this.db")
        self.assertEqual([s["text"] for s in data["statements"]], ["SELECT 1"])

    def test_a_given_receiver_seeds_the_derived_ones(self):
        content = "const c = await db.connect();\nc.query('SELECT 1');\n"
        data = self.pg(content, receivers="db")
        self.assertEqual(data["detected_receivers"], ["c"])
        self.assertEqual(data["receivers"], ["c", "db"])
        self.assertEqual(len(data["statements"]), 1)

    def test_a_sql_file_gives_empty_lists_and_ignores_the_option(self):
        data = self.pg("SELECT 1;\n", name="a.sql", receivers="pool")
        self.assertEqual((data["detected_receivers"], data["receivers"]), ([], []))

    def test_usage_errors(self):
        path = self.write("a.ts", "const x = 1;\n")
        for args in (
            ["--receivers", ""],
            ["--receivers", "a,,b"],
            ["--receivers", "a b"],
            ["--receivers", "1x"],
            ["--receivers", "this."],
            ["--receivers", "a", "--receivers", "b"],
            ["--receivers"],
        ):
            with self.subTest(args):
                result = self.run_args(path, *args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertEqual(len(result.stderr.strip().splitlines()), 1)

    def test_the_tags_option_and_the_receivers_option_work_together(self):
        content = self.HEAD + "pool.query('SELECT 1');\nconst q = sql`SELECT 2`;\n"
        data = self.pg(content, tags="sql", receivers="db")
        self.assertEqual([s["source"] for s in data["statements"]], ["pg", "template"])
        self.assertEqual(data["tags"], ["sql"])


class DirectStringShapeTest(PgCase):
    HEAD = "import { Pool } from 'pg';\nconst pool = new Pool();\n"

    def test_a_string_literal_statement(self):
        statement = self.one(self.HEAD + "pool.query('SELECT 1', [7]);\n")
        self.assertEqual(
            statement,
            {
                "source": "pg",
                "tag": None,
                "start_line": 3,
                "end_line": 3,
                "text": "SELECT 1",
                "parent": None,
                "interpolations": [],
                "pg": {
                    "kind": "literal",
                    "const_name": None,
                    "line_starts": [3],
                    "dynamic": False,
                    "statement_count": 1,
                    "calls": [
                        {
                            "line": 3,
                            "call": "direct",
                            "values_length": 1,
                            "values_present": True,
                            "name": None,
                            "rows": None,
                            "query_mode": None,
                        }
                    ],
                },
            },
        )

    def test_a_double_quoted_string(self):
        self.assertEqual(self.one(self.HEAD + 'pool.query("SELECT 1");\n')["text"], "SELECT 1")

    def test_an_untagged_template_statement(self):
        statement = self.one(self.HEAD + "pool.query(`\n  SELECT 1\n  FROM t\n`);\n")
        self.assertEqual(statement["text"], "\n  SELECT 1\n  FROM t\n")
        self.assertEqual((statement["start_line"], statement["end_line"]), (3, 6))
        self.assertEqual(statement["pg"]["kind"], "template")
        self.assertEqual(statement["pg"]["line_starts"], [3, 4, 5, 6])
        self.assertEqual(statement["pg"]["calls"][0]["line"], 3)

    def test_the_call_line_is_the_line_of_the_query_name(self):
        statement = self.one(self.HEAD + "pool\n  .query('SELECT 1');\n")
        self.assertEqual(statement["pg"]["calls"][0]["line"], 4)
        self.assertEqual(statement["start_line"], 4)

    def test_values_of_the_second_argument(self):
        cases = [
            ("pool.query('SELECT 1');", 0, False),
            ("pool.query('SELECT 1', []);", 0, True),
            ("pool.query('SELECT 1', [1, 2, 3]);", 3, True),
            ("pool.query('SELECT 1', [1, 2,]);", 2, True),
            ("pool.query('SELECT 1', [1,, 2]);", 3, True),
            ("pool.query('SELECT 1', [a(1, 2), [3, 4], {x: 1, y: 2}]);", 3, True),
            ("pool.query('SELECT 1', [`a,b`, \"c,d\"]);", 2, True),
            ("pool.query('SELECT 1', [...ids, 1]);", None, True),
            ("pool.query('SELECT 1', params);", None, True),
            ("pool.query('SELECT 1', getParams());", None, True),
            ("pool.query('SELECT 1', (err, res) => {});", 0, False),
            ("pool.query('SELECT 1', async (err, res) => {});", 0, False),
            ("pool.query('SELECT 1', function (err, res) {});", 0, False),
            ("pool.query('SELECT 1', cb => cb());", 0, False),
            ("pool.query('SELECT 1', [1] as const);", 1, True),
            ("pool.query('SELECT 1', [1], (err, res) => {});", 1, True),
        ]
        for source, length, present in cases:
            with self.subTest(source):
                call = self.one(self.HEAD + source + "\n")["pg"]["calls"][0]
                self.assertEqual((call["values_length"], call["values_present"]), (length, present))
                self.assertEqual((call["name"], call["rows"], call["query_mode"]), (None, None, None))

    def test_statement_count(self):
        cases = [
            ("SELECT 1", 1),
            ("SELECT 1;", 1),
            (";SELECT 1", 1),
            ("SELECT 1;;", 1),
            ("SELECT 1; SELECT 2", 2),
            ("SELECT ';'", 1),
            ("SELECT 1; -- c; d", 1),
            ("SELECT $$a;b$$", 1),
            ("SELECT 'a", 1),
            ("/* a", 0),
        ]
        for sql, count in cases:
            with self.subTest(sql):
                statement = self.one(self.HEAD + "pool.query(`" + sql + "`);\n")
                self.assertEqual(statement["pg"]["statement_count"], count)

    def test_the_escapes_of_a_string_are_decoded(self):
        cases = [
            (r"'a\nb'", "a\nb"),
            (r"'a\tb\rc'", "a\tb\rc"),
            (r"'it\'s'", "it's"),
            (r"'a\\b'", "a\\b"),
            (r"'\x41B\u{43}'", "ABC"),
            (r"'\0'", "\0"),
            (r"'\012'", "\n"),
            (r"'\400'", " 0"),
            (r"'\q'", "q"),
            (r"'\u'", "u"),
            (r"'\xZ'", "xZ"),
            (r"'\8\9'", "89"),
            (r"'\b\f\v'", "\b\f\v"),
            ("'a\\\nb'", "ab"),
            ("'a\\\r\nb'", "ab"),
        ]
        for literal, value in cases:
            with self.subTest(literal):
                self.assertEqual(self.one(self.HEAD + "pool.query(" + literal + ");\n")["text"], value)

    def test_the_escapes_of_a_template_are_decoded(self):
        cases = [
            (r"`a\`b`", "a`b"),
            (r"`a\${b}`", "a${b}"),
            (r"`a\\b`", "a\\b"),
            (r"`a\nb`", "a\nb"),
            ("`a\r\nb`", "a\nb"),
            ("`a\rb`", "a\nb"),
        ]
        for literal, value in cases:
            with self.subTest(literal):
                self.assertEqual(self.one(self.HEAD + "pool.query(" + literal + ");\n")["text"], value)

    def test_surrogates(self):
        data = self.pg(self.HEAD + r"pool.query('😀');" + "\n")
        self.assertEqual(data["statements"][0]["text"], "\U0001F600")
        data = self.pg(self.HEAD + r"pool.query('\ud800');" + "\n")
        self.assertEqual(data["statements"][0]["text"], "�")
        data = self.pg(self.HEAD + "pool.query('\U0001F600');\n")
        self.assertEqual(data["statements"][0]["text"], "\U0001F600")

    def test_line_starts_follow_the_source_lines_not_the_escapes(self):
        statement = self.one(self.HEAD + r"pool.query('SELECT 1\nFROM t');" + "\n")
        self.assertEqual(statement["pg"]["line_starts"], [3, 3])
        statement = self.one(self.HEAD + "pool.query('SELECT 1\\n\\\nFROM t\\n');\n")
        self.assertEqual(statement["text"], "SELECT 1\nFROM t\n")
        self.assertEqual(statement["pg"]["line_starts"], [3, 4, 4])
        statement = self.one(self.HEAD + "pool.query(`a\n\nb\n`);\n")
        self.assertEqual(statement["pg"]["line_starts"], [3, 4, 5, 6])

    def test_a_crlf_line_continuation_is_one_statement(self):
        statement = self.one(self.HEAD + "pool.query('SELECT 1 \\\r\nFROM t');\n")
        self.assertEqual(statement["text"], "SELECT 1 FROM t")
        self.assertEqual((statement["start_line"], statement["end_line"]), (3, 4))

    def test_a_lone_cr_in_a_template_repeats_the_source_line(self):
        statement = self.one(self.HEAD + "pool.query(`a\rb`);\n")
        self.assertEqual(statement["text"], "a\nb")
        self.assertEqual(statement["pg"]["line_starts"], [3, 3])

    def test_the_output_is_valid_utf8_json(self):
        path = self.write("a.ts", self.HEAD + r"pool.query('𐀀 \udc00 é');" + "\n")
        result = self.run_args(path)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["statements"][0]["text"], "\U00010000 � é")

    def test_arguments_that_give_no_statement(self):
        cases = [
            "pool.query(sql);",
            "pool.query('SELECT ' + id);",
            "pool.query('SELECT ' + 'a');",
            "pool.query(`SELECT ${id}`);",
            "pool.query({ text: 'SELECT 1' });",
            "pool.query(build());",
            "pool.query(queries.users);",
            "pool.query(sql`SELECT 1`);",
            "pool.query(...args);",
        ]
        for source in cases:
            with self.subTest(source):
                data = self.pg(self.HEAD + source + "\n", tags="sql")
                self.assertEqual([s for s in data["statements"] if s["source"] == "pg"], [])

    def test_an_unterminated_string_gives_no_statement(self):
        for source in ("pool.query('\n);\n", "pool.query('a\\'\n);\n"):
            with self.subTest(source):
                data = self.pg(self.HEAD + source)
                self.assertEqual(data["statements"], [])

    def test_a_terminated_empty_or_escaped_string_is_a_statement(self):
        for literal, value in (("''", ""), (r"'\''", "'"), (r"'\\'", "\\")):
            with self.subTest(literal):
                self.assertEqual(self.one(self.HEAD + "pool.query(" + literal + ");\n")["text"], value)

    def test_two_calls_are_two_statements_in_source_order(self):
        data = self.pg(self.HEAD + "pool.query('SELECT 1');\npool.query('SELECT 2');\n")
        self.assertEqual([s["text"] for s in data["statements"]], ["SELECT 1", "SELECT 2"])


class SourceKeyTest(PgCase):
    HEAD = "import { Pool } from 'pg';\nconst pool = new Pool();\n"

    def test_sql_statements_have_source_sql(self):
        data = self.pg("SELECT 1;\nSELECT 2;\n", name="a.sql")
        self.assertEqual([s["source"] for s in data["statements"]], ["sql", "sql"])

    def test_template_statements_keep_their_fields_and_gain_source(self):
        src = "const q = sql`\n  SELECT 1\n  WHERE id = ${id}\n`;\n"
        statement = self.pg(src, tags="sql")["statements"][0]
        self.assertEqual(
            statement,
            {
                "source": "template",
                "tag": "sql",
                "start_line": 1,
                "end_line": 4,
                "text": "\n  SELECT 1\n  WHERE id = ${id}\n",
                "parent": None,
                "interpolations": [{"line": 3, "column": 14, "expression": "id", "position": "value"}],
            },
        )

    def test_a_mixed_file_is_in_source_order_with_reindexed_parents(self):
        content = (
            self.HEAD
            + "pool.query('SELECT 1');\n"
            + "const a = sql`SELECT ${sql`SELECT 2`}`;\n"
            + "pool.query('SELECT 3');\n"
        )
        data = self.pg(content, tags="sql")
        self.assertEqual(
            [(s["source"], s["parent"]) for s in data["statements"]],
            [("pg", None), ("template", None), ("template", 1), ("pg", None)],
        )
        self.assertEqual([s["start_line"] for s in data["statements"]], [3, 4, 4, 5])

    def test_a_pg_statement_inside_a_template_interpolation_has_no_parent(self):
        content = self.HEAD + "const a = sql`SELECT ${pool.query('SELECT 2')}`;\n"
        data = self.pg(content, tags="sql")
        self.assertEqual([(s["source"], s["parent"]) for s in data["statements"]], [("template", None), ("pg", None)])


if __name__ == "__main__":
    unittest.main()
