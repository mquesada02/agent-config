import unittest

from test_sql_extract_pg import PgCase


class FormsCase(PgCase):
    # two lines: the first statement of a test starts on line 3
    HEAD = "import { Pool } from 'pg';\nconst pool = new Pool();\n"

    def forms(self, source, **options):
        return self.pg(self.HEAD + source + "\n", **options)

    def stmts(self, source, **options):
        return [s for s in self.forms(source, **options)["statements"] if s["source"] == "pg"]

    def not_followed(self, source, **options):
        return self.forms(source, **options)["not_followed"]

    def assertNotFollowed(self, source, lines=(3,), **options):
        data = self.forms(source, **options)
        self.assertEqual([s for s in data["statements"] if s["source"] == "pg"], [], source)
        self.assertEqual(data["not_followed"], [{"line": line} for line in lines], source)


class ConfigObjectTest(FormsCase):
    def test_the_text_of_a_config_object_is_a_statement(self):
        statement = self.stmts("pool.query({ text: 'SELECT $1', values: [1] });")[0]
        self.assertEqual(statement["text"], "SELECT $1")
        call = statement["pg"]["calls"][0]
        self.assertEqual(call["call"], "config")
        self.assertEqual((call["values_length"], call["values_present"]), (1, True))
        self.assertEqual((call["name"], call["rows"], call["query_mode"]), (None, None, None))
        self.assertEqual(statement["pg"]["const_name"], None)

    def test_name_rows_and_query_mode_come_from_the_config(self):
        source = "pool.query({ text: 'SELECT 1', name: 'q1', rows: 5, queryMode: 'array' });"
        call = self.stmts(source)[0]["pg"]["calls"][0]
        self.assertEqual((call["name"], call["rows"], call["query_mode"]), ("q1", 5, "array"))

    def test_a_non_literal_name_rows_or_query_mode_is_an_expression(self):
        source = "pool.query({ text: 'SELECT 1', name, rows: n + 1, queryMode: `a${b}` });"
        call = self.stmts(source)[0]["pg"]["calls"][0]
        self.assertEqual(call["name"], {"expression": "name"})
        self.assertEqual(call["rows"], {"expression": "n + 1"})
        self.assertEqual(call["query_mode"], {"expression": "`a${b}`"})

    def test_a_template_name_and_a_quoted_key(self):
        source = "pool.query({ 'text': 'SELECT 1', name: `q`, rows: '7' });"
        call = self.stmts(source)[0]["pg"]["calls"][0]
        self.assertEqual((call["name"], call["rows"]), ("q", "7"))

    def test_a_hex_rows_value_is_an_expression(self):
        call = self.stmts("pool.query({ text: 'SELECT 1', rows: 0x10 });")[0]["pg"]["calls"][0]
        self.assertEqual(call["rows"], {"expression": "0x10"})

    def test_values_of_a_config_object(self):
        cases = [
            ("{ text: 'SELECT 1' }", 0, False),
            ("{ text: 'SELECT 1', values: [] }", 0, True),
            ("{ text: 'SELECT 1', values: [1, 2] }", 2, True),
            ("{ text: 'SELECT 1', values: [1, 2] as const }", 2, True),
            ("{ text: 'SELECT 1', values: ids }", None, True),
            ("{ text: 'SELECT 1', values: [...ids] }", None, True),
        ]
        for config, length, present in cases:
            with self.subTest(config):
                call = self.stmts("pool.query(" + config + ");")[0]["pg"]["calls"][0]
                self.assertEqual((call["values_length"], call["values_present"]), (length, present))

    def test_the_last_property_counts(self):
        statement = self.stmts("pool.query({ text: 'SELECT 1', text: 'SELECT 2', name: 'a', name: 'b' });")[0]
        self.assertEqual(statement["text"], "SELECT 2")
        self.assertEqual(statement["pg"]["calls"][0]["name"], "b")

    def test_a_type_clause_after_the_config_is_ignored(self):
        for tail in (" as QueryConfig", " satisfies QueryConfig", " as QueryConfig<A, B>"):
            with self.subTest(tail):
                statement = self.stmts("pool.query({ text: 'SELECT 1' }" + tail + ");")[0]
                self.assertEqual(statement["pg"]["calls"][0]["call"], "config")

    def test_the_text_may_be_a_template_a_chain_or_a_name(self):
        statement = self.stmts("pool.query({ text: `SELECT 1` });")[0]
        self.assertEqual(statement["pg"]["kind"], "template")
        statement = self.stmts("pool.query({ text: 'SELECT ' + '1' });")[0]
        self.assertEqual((statement["pg"]["kind"], statement["text"]), ("chain", "SELECT 1"))
        statement = self.stmts("const q = 'SELECT 1';\npool.query({ text: q });")[0]
        self.assertEqual(statement["pg"]["const_name"], "q")
        self.assertEqual(statement["pg"]["calls"][0]["call"], "config")
        statement = self.stmts("const text = 'SELECT 1';\npool.query({ text });")[0]
        self.assertEqual(statement["pg"]["const_name"], "text")

    def test_configs_that_give_no_text_are_not_followed(self):
        cases = [
            "pool.query({ values: [1] });",
            "pool.query({ text: build() });",
            "pool.query({ text: a.b });",
            "pool.query({ ...base, text: 'SELECT 1' });",
            "pool.query({ ['text']: 'SELECT 1' });",
            "pool.query({ text() { return 'SELECT 1'; } });",
            "pool.query({});",
            "pool.query({ text: 'SELECT 1' }.x);",
        ]
        for source in cases:
            with self.subTest(source):
                self.assertNotFollowed(source)

    def test_the_config_text_name_of_a_submittable_const_is_not_followed(self):
        head = "import { Query } from 'pg';\nconst cur = new Query('SELECT 1');\n"
        data = self.pg(self.HEAD + head + "pool.query({ text: cur });\n")
        self.assertEqual(data["not_followed"], [{"line": 5}])


class SubmittableTest(FormsCase):
    def call_of(self, head, source, **options):
        data = self.pg(self.HEAD + head + source + "\n", **options)
        found = [s for s in data["statements"] if s["source"] == "pg"]
        return found, data

    def test_each_import_form_of_query(self):
        heads = [
            "import { Query } from 'pg';\n",
            "import { Query as Q } from 'pg';\n",
            "import pg from 'pg';\n",
            "import * as pg from 'pg';\n",
            "const { Query } = require('pg');\n",
            "const Query = require('pg').Query;\n",
            "const pg = require('pg');\n",
            "const pg = require('pg').native;\n",
        ]
        usage = {
            "import { Query as Q } from 'pg';\n": "Q",
            "import pg from 'pg';\n": "pg.Query",
            "import * as pg from 'pg';\n": "pg.Query",
            "const pg = require('pg');\n": "pg.Query",
            "const pg = require('pg').native;\n": "pg.Query",
        }
        for head in heads:
            with self.subTest(head):
                name = usage.get(head, "Query")
                found, _ = self.call_of(head, "pool.query(new " + name + "('SELECT 1', [1]));")
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0]["text"], "SELECT 1")
                call = found[0]["pg"]["calls"][0]
                self.assertEqual(call["call"], "submittable")
                self.assertEqual((call["values_length"], call["values_present"]), (1, True))

    def test_pg_native_query(self):
        found, _ = self.call_of(
            "import pg from 'pg';\n", "pool.query(new pg.native.Query('SELECT 1'));"
        )
        self.assertEqual(found[0]["text"], "SELECT 1")

    def test_cursor_and_query_stream_imports(self):
        heads = {
            "Cursor": [
                "import Cursor from 'pg-cursor';\n",
                "import * as Cursor from 'pg-cursor';\n",
                "import Cursor = require('pg-cursor');\n",
                "const Cursor = require('pg-cursor');\n",
            ],
            "QueryStream": [
                "import QueryStream from 'pg-query-stream';\n",
                "import * as QueryStream from 'pg-query-stream';\n",
                "import QueryStream = require('pg-query-stream');\n",
                "const QueryStream = require('pg-query-stream');\n",
            ],
        }
        for name, forms in heads.items():
            for head in forms:
                with self.subTest(head):
                    found, _ = self.call_of(head, "pool.query(new " + name + "('SELECT 1', [1, 2]));")
                    self.assertEqual(len(found), 1)
                    call = found[0]["pg"]["calls"][0]
                    self.assertEqual(call["call"], "submittable")
                    self.assertEqual((call["values_length"], call["values_present"]), (2, True))
                    self.assertEqual((call["name"], call["rows"], call["query_mode"]), (None, None, None))

    def test_type_arguments_after_the_class_name(self):
        found, _ = self.call_of(
            "import Cursor from 'pg-cursor';\n", "pool.query(new Cursor<Row>('SELECT 1'));"
        )
        self.assertEqual(found[0]["text"], "SELECT 1")

    def test_a_class_that_does_not_come_from_the_module_is_not_a_submittable(self):
        for head in (
            "import { Query } from 'other';\n",
            "import Cursor from 'other';\n",
            "import type Query from 'pg';\n",
            "import type { Query } from 'pg';\n",
            "const Query = class {};\n",
        ):
            with self.subTest(head):
                name = "Cursor" if "Cursor" in head else "Query"
                found, data = self.call_of(head, "pool.query(new " + name + "('SELECT 1'));")
                self.assertEqual(found, [])
                self.assertEqual(data["not_followed"], [{"line": 4}])

    def test_a_submittable_class_is_never_a_receiver(self):
        _, data = self.call_of(
            "import { Query } from 'pg';\n", "const q = new Query('SELECT 1');\nq.query('SELECT 2');"
        )
        self.assertEqual(data["detected_receivers"], ["pool"])
        self.assertEqual([s for s in data["statements"] if s["source"] == "pg"], [])

    def test_a_config_object_for_query_gives_name_rows_and_query_mode(self):
        source = "pool.query(new Query({ text: 'SELECT 1', values: [1], name: 'n', rows: 2, queryMode: 'array' }));"
        found, _ = self.call_of("import { Query } from 'pg';\n", source)
        call = found[0]["pg"]["calls"][0]
        self.assertEqual(call["call"], "submittable")
        self.assertEqual((call["values_length"], call["values_present"]), (1, True))
        self.assertEqual((call["name"], call["rows"], call["query_mode"]), ("n", 2, "array"))

    def test_the_text_name_of_a_query_config_is_a_submittable_call(self):
        source = "const q = 'SELECT 1';\npool.query(new Query({ text: q }));"
        found, _ = self.call_of("import { Query } from 'pg';\n", source)
        self.assertEqual(found[0]["pg"]["const_name"], "q")
        self.assertEqual(found[0]["pg"]["calls"][0]["call"], "submittable")

    def test_submittables_that_give_no_text_are_not_followed(self):
        head = "import { Query } from 'pg';\nimport Cursor from 'pg-cursor';\nimport QueryStream from 'pg-query-stream';\n"
        cases = [
            "pool.query(new Cursor());",
            "pool.query(new Cursor(build()));",
            "pool.query(new Cursor({ text: 'SELECT 1' }));",
            "pool.query(new QueryStream({ text: 'SELECT 1' }));",
            "pool.query(new Query({ values: [1] }));",
            "pool.query(new Query(config));",
            "pool.query(new Other('SELECT 1'));",
            "pool.query(new Cursor('SELECT 1').x);",
        ]
        for source in cases:
            with self.subTest(source):
                data = self.pg(self.HEAD + head + source + "\n")
                self.assertEqual([s for s in data["statements"] if s["source"] == "pg"], [])
                self.assertEqual(data["not_followed"], [{"line": 6}])

    def test_a_name_that_holds_a_submittable_is_followed_to_its_text(self):
        head = "import Cursor from 'pg-cursor';\nconst cur = new Cursor('SELECT 1', [1]);\n"
        source = "pool.query(cur);\npool.query(cur);"
        found, _ = self.call_of(head, source)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["pg"]["const_name"], None)
        calls = found[0]["pg"]["calls"]
        self.assertEqual([c["call"] for c in calls], ["submittable", "submittable"])
        self.assertEqual([c["line"] for c in calls], [5, 6])
        self.assertEqual((calls[0]["values_length"], calls[0]["values_present"]), (1, True))
        self.assertEqual((found[0]["start_line"], found[0]["end_line"]), (4, 4))

    def test_a_submittable_const_with_a_name_argument_gives_the_const_name_of_that_name(self):
        head = "import Cursor from 'pg-cursor';\nconst text = 'SELECT 1';\nconst cur = new Cursor(text);\n"
        found, _ = self.call_of(head, "pool.query(cur);")
        self.assertEqual(found[0]["pg"]["const_name"], "text")
        self.assertEqual(found[0]["pg"]["calls"][0]["call"], "submittable")

    def test_a_submittable_const_that_no_call_uses_gives_no_statement(self):
        found, data = self.call_of(
            "import Cursor from 'pg-cursor';\n", "const cur = new Cursor('SELECT 1');"
        )
        self.assertEqual(found, [])
        self.assertEqual(data["not_followed"], [])


class ConstTest(FormsCase):
    def test_a_const_string_template_and_chain_are_followed(self):
        cases = [
            ("const q = 'SELECT 1';", "literal", "SELECT 1"),
            ("const q = `SELECT 1`;", "template", "SELECT 1"),
            ("const q = 'SELECT ' + '1';", "chain", "SELECT 1"),
            ("const q: string = 'SELECT 1';", "literal", "SELECT 1"),
            ("const q = 'SELECT 1'\n", "literal", "SELECT 1"),
            ("const a = 1, q = 'SELECT 1';", "literal", "SELECT 1"),
            ("const q = 'SELECT 1', b = 2;", "literal", "SELECT 1"),
            ("export const q = 'SELECT 1';", "literal", "SELECT 1"),
        ]
        for definition, kind, text in cases:
            with self.subTest(definition):
                statement = self.stmts(definition + "\npool.query(q);")[0]
                self.assertEqual((statement["pg"]["kind"], statement["text"]), (kind, text))
                self.assertEqual(statement["pg"]["const_name"], "q")
                self.assertEqual(statement["pg"]["calls"][0]["call"], "direct")

    def test_the_lines_of_a_const_are_those_of_the_value(self):
        statement = self.stmts("const q =\n  `SELECT 1\n  FROM t`;\npool.query(q);")[0]
        self.assertEqual((statement["start_line"], statement["end_line"]), (4, 5))
        self.assertEqual(statement["pg"]["calls"][0]["line"], 6)

    def test_one_const_used_twice_is_one_statement_with_two_calls(self):
        statement = self.stmts("const q = 'SELECT 1';\npool.query(q);\npool.query(q, [1]);")[0]
        calls = statement["pg"]["calls"]
        self.assertEqual([c["line"] for c in calls], [4, 5])
        self.assertEqual([(c["values_length"], c["values_present"]) for c in calls], [(0, False), (1, True)])
        self.assertEqual(len(self.stmts("const q = 'SELECT 1';\npool.query(q);\npool.query(q, [1]);")), 1)

    def test_the_call_value_follows_the_outer_form(self):
        source = "const q = 'SELECT 1';\npool.query(q);\npool.query({ text: q });"
        calls = self.stmts(source)[0]["pg"]["calls"]
        self.assertEqual([c["call"] for c in calls], ["direct", "config"])

    def test_the_statement_is_at_the_definition_in_source_order(self):
        source = "pool.query('SELECT 0');\nconst q = 'SELECT 1';\npool.query('SELECT 2');\npool.query(q);"
        self.assertEqual([s["text"] for s in self.stmts(source)], ["SELECT 0", "SELECT 1", "SELECT 2"])

    def test_a_const_that_no_call_uses_gives_no_statement(self):
        data = self.forms("const q = 'SELECT 1';")
        self.assertEqual([s for s in data["statements"] if s["source"] == "pg"], [])
        self.assertEqual(data["not_followed"], [])

    def test_a_const_used_only_by_calls_that_are_not_followed_gives_no_statement(self):
        data = self.forms("const q = 'SELECT 1';\npool.query({ ...o, text: q });")
        self.assertEqual([s for s in data["statements"] if s["source"] == "pg"], [])
        self.assertEqual(data["not_followed"], [{"line": 4}])

    def test_other_values_and_other_declarations_are_not_followed(self):
        cases = [
            "let q = 'SELECT 1';",
            "var q = 'SELECT 1';",
            "const q = 'SELECT 1'.trim();",
            "const q = 'SELECT 1' as const;",
            "const q = 'SELECT 1' as string;",
            "const q = 'SELECT 1' satisfies string;",
            "const q = 'SELECT 1' ?? 'x';",
            "const q = ok ? 'a' : 'b';",
            "const q = build();",
            "const q = other;",
            "const q = 5;",
            "const q = { text: 'SELECT 1' };",
            "const q = 'SELECT ' + id;",
            "const q = 'SELECT ' + `a${b}`;",
            "const q = 'a' + b.c();",
            "const { q } = obj;",
            "const [q] = list;",
            "function q() {}",
            "class q {}",
            "enum q {}",
        ]
        for definition in cases:
            with self.subTest(definition):
                data = self.forms(definition + "\npool.query(q);")
                self.assertEqual([s for s in data["statements"] if s["source"] == "pg"], [])
                self.assertEqual(data["not_followed"], [{"line": 4}])

    def test_an_import_a_parameter_and_an_unknown_name_are_not_followed(self):
        for head, tail in (
            ("import { q } from './q';\n", "pool.query(q);"),
            ("import q from './q';\n", "pool.query(q);"),
            ("import * as q from './q';\n", "pool.query(q);"),
            ("import { x as q } from './q';\n", "pool.query(q);"),
            ("", "function f(q: string) { pool.query(q); }"),
            ("", "const f = (q) => pool.query(q);"),
            ("", "const f = async q => pool.query(q);"),
            ("", "function f({ q }) { pool.query(q); }"),
            ("", "try { go(); } catch (q) { pool.query(q); }"),
            ("", "pool.query(q);"),
        ):
            with self.subTest(head + tail):
                data = self.pg(self.HEAD + head + tail + "\n")
                self.assertEqual([s for s in data["statements"] if s["source"] == "pg"], [])
                self.assertEqual(len(data["not_followed"]), 1)

    def test_a_const_with_a_template_with_interpolation_is_dynamic(self):
        statement = self.stmts("const q = `SELECT ${id}`;\npool.query(q);")[0]
        self.assertTrue(statement["pg"]["dynamic"])
        self.assertEqual(statement["pg"]["const_name"], "q")
        self.assertEqual(statement["pg"]["kind"], "template")

    def test_a_const_that_holds_a_tagged_template(self):
        self.assertNotFollowed("const q = sql`SELECT 1`;\npool.query(q);", lines=(4,), tags="other")
        data = self.forms("const q = sql`SELECT 1`;\npool.query(q);", tags="sql")
        self.assertEqual([s for s in data["statements"] if s["source"] == "pg"], [])
        self.assertEqual(data["not_followed"], [])

    def test_a_call_before_the_const_is_not_followed(self):
        self.assertNotFollowed("pool.query(q);\nconst q = 'SELECT 1';")
        self.assertNotFollowed("function f() { pool.query(q); }\nconst q = 'SELECT 1';")

    def test_a_call_in_a_nested_scope_follows_an_outer_const(self):
        statement = self.stmts("const q = 'SELECT 1';\nfunction f() { if (x) { pool.query(q); } }")[0]
        self.assertEqual(statement["text"], "SELECT 1")

    def test_the_innermost_declaration_wins(self):
        source = "const q = 'SELECT 1';\nfunction f() {\n  const q = 'SELECT 2';\n  pool.query(q);\n}\npool.query(q);"
        found = self.stmts(source)
        self.assertEqual([(s["text"], [c["line"] for c in s["pg"]["calls"]]) for s in found],
                         [("SELECT 1", [8]), ("SELECT 2", [6])])

    def test_a_shadowing_declaration_that_is_not_a_const_makes_the_call_not_followed(self):
        cases = [
            "function f(q) { pool.query(q); }",
            "function f(a, q = 1) { pool.query(q); }",
            "function f(a: Map<string, number>, q) { pool.query(q); }",
            "const f = (q) => { pool.query(q); };",
            "const f = (q): void => { pool.query(q); };",
            "const f = async (q) => { pool.query(q); };",
            "const f = q => pool.query(q);",
            "class C { m(q) { pool.query(q); } }",
            "class C { constructor(private q: string) { pool.query(q); } }",
            "{ let q = 1; pool.query(q); }",
            "{ var q; pool.query(q); }",
            "{ enum q {} pool.query(q); }",
            "try { go(); } catch ({ q }) { pool.query(q); }",
            "for (const q of list) { pool.query(q); }",
            "for (const q of list) pool.query(q);",
        ]
        for source in cases:
            with self.subTest(source):
                data = self.pg(self.HEAD + "const q = 'SELECT 1';\n" + source + "\n")
                self.assertEqual([s for s in data["statements"] if s["source"] == "pg"], [])
                self.assertEqual(len(data["not_followed"]), 1, data)

    def test_every_declarator_of_a_statement_is_a_declaration(self):
        source = "const q = 'SELECT 1';\n{ const a = 1, q = 'SELECT 2'; pool.query(q); }"
        found = self.stmts(source)
        self.assertEqual([s["text"] for s in found], ["SELECT 2"])

    def test_a_parameter_does_not_shadow_outside_its_function(self):
        source = "const q = 'SELECT 1';\nfunction f(q) { return q; }\npool.query(q);"
        self.assertEqual(self.stmts(source)[0]["text"], "SELECT 1")

    def test_an_if_condition_is_not_a_parameter_list(self):
        source = "const q = 'SELECT 1';\nif (q) { pool.query(q); }\nwhile (q) { pool.query(q); }"
        statement = self.stmts(source)[0]
        self.assertEqual(len(statement["pg"]["calls"]), 2)

    def test_a_ternary_group_is_not_a_parameter_list(self):
        source = "const q = 'SELECT 1';\nconst v = ok ? (q) : 2;\npool.query(q);"
        self.assertEqual(self.stmts(source)[0]["text"], "SELECT 1")

    def test_a_method_with_a_computed_quoted_or_numeric_key_binds_its_parameters(self):
        cases = [
            "class A { static [k](q) { return pool.query(q); } }",
            "class A { 'quoted'(q) { return pool.query(q); } }",
            "class A { 123(q) { return pool.query(q); } }",
            "const o = { [key](q) { return pool.query(q); } };",
            "const o = { 'a-b'(q) { return pool.query(q); } };",
            "class A { async *[Symbol.asyncIterator](q) { return pool.query(q); } }",
        ]
        for source in cases:
            with self.subTest(source):
                data = self.pg(self.HEAD + "const q = 'SELECT 1';\n" + source + "\n")
                self.assertEqual([s for s in data["statements"] if s["source"] == "pg"], [])
                self.assertEqual(len(data["not_followed"]), 1, data)

    def test_a_return_type_with_an_object_type_does_not_end_the_parameter_scope(self):
        source = (
            "const q = 'SELECT 1';\n"
            "function g(q: string): { id: number } { return pool.query(q); }\n"
            "pool.query(q);"
        )
        data = self.pg(self.HEAD + source + "\n")
        found = [s for s in data["statements"] if s["source"] == "pg"]
        self.assertEqual([[c["line"] for c in s["pg"]["calls"]] for s in found], [[5]])
        self.assertEqual(data["not_followed"], [{"line": 4}])

    def test_a_void_return_type_does_not_end_the_parameter_scope(self):
        source = (
            "const q = 'SELECT 1';\n"
            "function f(q): void { return pool.query(q); }\n"
            "class A { m(q): void { pool.query(q); } 'z'(q): void { pool.query(q); } }\n"
            "pool.query(q);"
        )
        data = self.pg(self.HEAD + source + "\n")
        found = [s for s in data["statements"] if s["source"] == "pg"]
        self.assertEqual([[c["line"] for c in s["pg"]["calls"]] for s in found], [[6]])
        self.assertEqual(data["not_followed"], [{"line": 4}, {"line": 5}, {"line": 5}])

    def test_a_return_type_with_an_object_type_after_a_type_keyword_does_not_end_the_parameter_scope(self):
        for kind in (
            "asserts q is { a: 1 }",
            "keyof { a: 1 }",
            "typeof x extends { a: 1 } ? 1 : 2",
        ):
            with self.subTest(kind=kind):
                source = (
                    "const q = 'SELECT 1';\n"
                    "function g(q: any): %s { pool.query(q); }\n"
                    "class D { m(q: any): %s { pool.query(q); } }\n"
                    "pool.query(q);"
                ) % (kind, kind)
                data = self.pg(self.HEAD + source + "\n")
                found = [s for s in data["statements"] if s["source"] == "pg"]
                self.assertEqual([[c["line"] for c in s["pg"]["calls"]] for s in found], [[6]])
                self.assertEqual(data["not_followed"], [{"line": 4}, {"line": 5}])

    def test_an_optional_method_parameter_does_not_end_the_parameter_scope(self):
        source = (
            "const q = 'SELECT 1';\n"
            "class C { n?(q) { pool.query(q); } }\n"
            "pool.query(q);"
        )
        data = self.pg(self.HEAD + source + "\n")
        found = [s for s in data["statements"] if s["source"] == "pg"]
        self.assertEqual([[c["line"] for c in s["pg"]["calls"]] for s in found], [[5]])
        self.assertEqual(data["not_followed"], [{"line": 4}])

    def test_a_scope_that_has_no_semicolon_ends_at_the_next_statement(self):
        source = (
            "const q = 'SELECT 1'\n"
            "const f = (q) => q + 1\n"
            "pool.query(q)\n"
            "const g = q => q * 2\n"
            "pool.query(q)\n"
            "for (const q of list) go(q)\n"
            "pool.query(q)\n"
            "type T = (q: string) => void\n"
            "pool.query(q)\n"
        )
        found = self.stmts(source)
        self.assertEqual([[c["line"] for c in s["pg"]["calls"]] for s in found], [[5, 7, 9, 11]])

    def test_many_lines_without_semicolons_run_in_linear_time(self):
        lines = ["const q = 'SELECT 1'"]
        lines += ["export const f%d = (a) => a + %d" % (i, i) for i in range(3000)]
        lines += ["for (const x of y) go(x)"] * 1000
        lines += ["pool.query(q)"]
        path = self.write("big.ts", self.HEAD + "\n".join(lines) + "\n")
        result = self.run_args(path, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_two_declarations_in_the_same_scope_are_not_followed(self):
        data = self.forms("const q = 'SELECT 1';\nvar q = 'SELECT 2';\npool.query(q);")
        self.assertEqual([s for s in data["statements"] if s["source"] == "pg"], [])
        self.assertEqual(data["not_followed"], [{"line": 5}])


class ChainAndDynamicTest(FormsCase):
    def test_an_all_literal_chain_is_one_statement(self):
        statement = self.stmts("pool.query(\n  'SELECT 1 ' +\n  `FROM t`\n);")[0]
        self.assertEqual(statement["text"], "SELECT 1 FROM t")
        self.assertEqual(statement["pg"]["kind"], "chain")
        self.assertFalse(statement["pg"]["dynamic"])
        self.assertEqual(statement["pg"]["statement_count"], 1)
        self.assertEqual((statement["start_line"], statement["end_line"]), (4, 5))
        self.assertEqual(statement["interpolations"], [])

    def test_the_line_starts_of_a_chain_follow_the_pieces(self):
        statement = self.stmts("pool.query('SELECT 1\\n' +\n  'FROM t\\n' +\n  'WHERE x');")[0]
        self.assertEqual(statement["text"], "SELECT 1\nFROM t\nWHERE x")
        self.assertEqual(statement["pg"]["line_starts"], [3, 4, 5])

    def test_each_piece_of_a_chain_is_decoded_alone(self):
        statement = self.stmts("pool.query('\\ud83d' + '\\ude00');")[0]
        self.assertEqual(statement["text"], "��")

    def test_a_chain_with_a_non_literal_piece_is_dynamic(self):
        statement = self.stmts("pool.query('SELECT * FROM ' + table + ' WHERE x');")[0]
        pg = statement["pg"]
        self.assertTrue(pg["dynamic"])
        self.assertIsNone(pg["statement_count"])
        self.assertEqual(pg["kind"], "chain")
        self.assertEqual(statement["text"], "'SELECT * FROM ' + table + ' WHERE x'")
        self.assertEqual(statement["interpolations"], [])
        self.assertEqual((statement["start_line"], statement["end_line"]), (3, 3))

    def test_a_dynamic_chain_keeps_its_raw_text_and_line_starts(self):
        statement = self.stmts("pool.query('a\\n' +\n  f(x));")[0]
        self.assertEqual(statement["text"], "'a\\n' +\n  f(x)")
        self.assertEqual(statement["pg"]["line_starts"], [3, 4])
        self.assertEqual((statement["start_line"], statement["end_line"]), (3, 4))

    def test_parentheses_make_an_operand_non_literal(self):
        statement = self.stmts("pool.query(('a' + 'b') + 'c');")[0]
        self.assertTrue(statement["pg"]["dynamic"])
        self.assertEqual(statement["text"], "('a' + 'b') + 'c'")

    def test_operands_that_are_names_members_calls_and_numbers(self):
        for operand in ("a", "a.b", "a?.b", "f(1, 2)", "a[0]", "7", "null", "this.x", "{}", "sql`x`"):
            with self.subTest(operand):
                statement = self.stmts("pool.query('SELECT ' + " + operand + ");")[0]
                self.assertTrue(statement["pg"]["dynamic"])

    def test_arguments_that_are_not_a_chain_are_not_followed(self):
        cases = [
            "a + b",
            "count + 1",
            "'a' ? 'b' : 'c'",
            "'a' + b ? c : d",
            "'a' - 1",
            "'a' + +b",
            "+ 'a'",
            "'a' + b || c",
            "'a' + ...b",
            "a ?? 'b'",
            "sql`a` + b",
            "'unterminated",
            "'SELECT 1' + 'unterminated",
        ]
        for argument in cases:
            with self.subTest(argument):
                self.assertNotFollowed("pool.query(" + argument + ");")

    def test_a_template_with_interpolation_is_dynamic(self):
        statement = self.stmts("pool.query(`SELECT ${a} FROM ${b}\n  WHERE x`);")[0]
        pg = statement["pg"]
        self.assertTrue(pg["dynamic"])
        self.assertEqual((pg["kind"], pg["statement_count"]), ("template", None))
        self.assertEqual(statement["text"], "SELECT ${a} FROM ${b}\n  WHERE x")
        self.assertEqual(pg["line_starts"], [3, 4])
        first, second = statement["interpolations"]
        self.assertEqual((first["expression"], first["position"]), ("a", "value"))
        self.assertEqual((first["start"], first["end"]), (7, 11))
        self.assertEqual(statement["text"][first["start"] : first["end"]], "${a}")
        self.assertEqual(statement["text"][second["start"] : second["end"]], "${b}")
        self.assertEqual((first["line"], first["column"]), (3, 20))
        self.assertEqual((statement["start_line"], statement["end_line"]), (3, 4))

    def test_the_interpolation_position_is_that_of_a_postgres_js_template(self):
        statement = self.stmts("pool.query(`SELECT * FROM t WHERE a = ${x} AND b = ${y}`);")[0]
        self.assertEqual([i["position"] for i in statement["interpolations"]], ["value", "value"])

    def test_a_dynamic_template_is_not_decoded(self):
        statement = self.stmts("pool.query(`a\\n${x}`);")[0]
        self.assertEqual(statement["text"], "a\\n${x}")

    def test_a_pg_statement_is_not_counted_with_the_dynamic_flag_off(self):
        statement = self.stmts("pool.query('SELECT 1');")[0]
        self.assertFalse(statement["pg"]["dynamic"])


class TypeArgumentsInArgumentTest(FormsCase):
    def test_a_comma_inside_type_arguments_does_not_end_the_argument(self):
        data = self.forms("pool.query(sql<Record<string, unknown>>`SELECT 1`);", tags="sql")
        self.assertEqual([s for s in data["statements"] if s["source"] == "pg"], [])
        self.assertEqual(data["not_followed"], [])
        statement = self.stmts("pool.query({ text: 'SELECT 1' } as QueryConfig<A, B>);")[0]
        self.assertEqual(statement["pg"]["calls"][0]["call"], "config")
        statement = self.stmts("pool.query('SELECT ' + sql<Map<K, V>>`x`);", tags="sql")[0]
        self.assertTrue(statement["pg"]["dynamic"])

    def test_a_tagged_template_with_type_arguments_in_a_chain_is_one_operand(self):
        statement = self.stmts("pool.query('a' + sql<Row>`b`);", tags="sql")[0]
        self.assertTrue(statement["pg"]["dynamic"])


class TaggedTemplateTest(FormsCase):
    def test_a_tagged_template_of_the_tag_list_gives_nothing_here(self):
        data = self.forms("pool.query(sql`SELECT 1`);", tags="sql")
        self.assertEqual([s["source"] for s in data["statements"]], ["template"])
        self.assertEqual(data["not_followed"], [])

    def test_a_tagged_template_of_another_tag_is_not_followed(self):
        self.assertNotFollowed("pool.query(String.raw`SELECT 1`);", tags="sql")
        self.assertNotFollowed("pool.query(sql`SELECT 1`);", tags="other")

    def test_the_same_holds_in_a_config_text_and_a_constructor(self):
        data = self.forms("pool.query({ text: sql`SELECT 1` });", tags="sql")
        self.assertEqual(data["not_followed"], [])
        self.assertEqual([s["source"] for s in data["statements"]], ["template"])
        self.assertNotFollowed("pool.query({ text: sql`SELECT 1` });", tags="other")


class NotFollowedTest(FormsCase):
    def test_each_argument_that_is_not_followed_has_the_line_of_the_query_name(self):
        source = "pool.query(a.b);\npool\n  .query(f());\npool.query(...x);"
        self.assertNotFollowed(source, lines=(3, 5, 6))

    def test_a_call_with_no_argument_gives_nothing(self):
        self.assertEqual(self.forms("pool.query();")["not_followed"], [])

    def test_the_query_call_forms_are_the_same_as_for_a_direct_call(self):
        self.assertNotFollowed("pool?.query(a.b);")
        self.assertNotFollowed("pool.query<Row>(a.b);")

    def test_a_call_of_a_non_receiver_is_not_listed(self):
        self.assertEqual(self.forms("other.query(a.b);")["not_followed"], [])

    def test_a_call_that_gives_a_statement_is_not_listed(self):
        self.assertEqual(self.forms("pool.query('SELECT 1');")["not_followed"], [])

    def test_a_sql_file_and_an_error_give_an_empty_list(self):
        data = self.pg("SELECT 1;\n", name="a.sql")
        self.assertEqual(data["not_followed"], [])
        data = self.pg("const a = `x${\n", expect=1)
        self.assertEqual(data["not_followed"], [])
        self.assertIsNotNone(data["error"])

    def test_the_key_is_present_for_a_file_without_calls(self):
        self.assertEqual(self.pg("const x = 1;\n")["not_followed"], [])

    def test_statements_are_in_the_one_list_in_source_order(self):
        source = "pool.query('SELECT 1');\nconst a = sql`SELECT 2`;\npool.query(`SELECT ${x}`);"
        data = self.forms(source, tags="sql")
        self.assertEqual([s["source"] for s in data["statements"]], ["pg", "template", "pg"])


class StatementCountTest(FormsCase):
    def test_statement_count_follows_the_sql_guard_tokenizer(self):
        cases = [
            ("SELECT 1;", 1),
            (";SELECT 1", 1),
            ("SELECT 1;;", 1),
            ("SELECT ';'", 1),
            ('SELECT "a;b"', 1),
            ("SELECT 1 -- a;b", 1),
            ("SELECT /* ; */ 1", 1),
            ("SELECT $$a;b$$", 1),
            ("SELECT 1; SELECT 2", 2),
            ("", 0),
            ("-- only a comment", 0),
        ]
        for sql, count in cases:
            with self.subTest(sql):
                statement = self.stmts("pool.query({ text: `" + sql + "` });")[0]
                self.assertEqual(statement["pg"]["statement_count"], count)

    def test_statement_count_is_null_for_a_dynamic_statement(self):
        statement = self.stmts("pool.query(`SELECT ${x}`);")[0]
        self.assertIsNone(statement["pg"]["statement_count"])
        statement = self.stmts("pool.query('SELECT ' + x);")[0]
        self.assertIsNone(statement["pg"]["statement_count"])


if __name__ == "__main__":
    unittest.main()
