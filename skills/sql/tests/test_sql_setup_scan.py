import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
SCRIPT = os.path.join(SKILL_DIR, "scripts", "setup_scan.py")

TAGGED = """\
import postgres from "postgres";
const sql = postgres(url);
class Repo {
  sql = postgres(url);
  list(ids) {
    return this.sql`select id from t where id in ${ids}`;
  }
  tx() {
    return sql.begin(async (tx) => tx`select id from u where name like '%abc'`);
  }
  clean() {
    return sql`select id, name from t where id = ${1}`;
  }
}
"""


def run(*args, env=None):
    result = subprocess.run([sys.executable, "-I", SCRIPT, *args], capture_output=True, text=True, env=env)
    return result.returncode, result.stdout, result.stderr


class ScanCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = tmp.name

    def write(self, name, text):
        path = os.path.join(self.repo, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def scan(self, *extra):
        code, out, err = run(self.repo, *extra)
        self.assertEqual(code, 0, (out, err))
        self.assertEqual(err, "")
        return json.loads(out)

    def template(self, body):
        """A one-file repo with one template statement whose text is `body`."""
        self.write("a.ts", "const sql = postgres();\nconst q = sql`" + body + "`;\n")
        return self.scan()

    def candidate(self, out, rule_id):
        found = [c for c in out["candidates"] if c["id"] == rule_id]
        return found[0] if found else None


class OutputTest(ScanCase):
    def test_files_statements_forms_tags_and_clean_candidates(self):
        self.write("src/repo.ts", TAGGED)
        self.write("db/q.sql", "select id, name from t;\n")
        out = self.scan()
        self.assertTrue(out["ok"])
        self.assertEqual(out["files_with_sql"], ["db/q.sql", "src/repo.ts"])
        self.assertEqual(out["forms"], {"template": 3, "sql": 1})
        self.assertEqual(out["statements"], 4)
        self.assertEqual(out["detected_tags"], ["sql", "this.sql", "tx"])
        self.assertEqual(out["errors"], [])
        self.assertFalse(out["truncated"])

    def test_a_repo_with_no_sql(self):
        self.write("README.md", "hello\n")
        self.write("src/a.ts", "export const a = 1;\n")
        out = self.scan()
        self.assertEqual(out["files_with_sql"], [])
        self.assertEqual(out["statements"], 0)
        self.assertEqual(out["forms"], {"template": 0, "sql": 0})
        self.assertEqual(out["detected_tags"], [])
        self.assertEqual(out["candidates"], [])

    def test_skipped_folders(self):
        for folder in ("node_modules/x", "dist", "build", "coverage", ".git", ".hidden", "src/.cache"):
            self.write(folder + "/a.sql", "select * from t;\n")
        self.write("src/ok.sql", "select id from t;\n")
        self.assertEqual(self.scan()["files_with_sql"], ["src/ok.sql"])

    def test_a_file_the_extractor_cannot_read_is_in_errors(self):
        self.write("bad.ts", "const sql = postgres();\nconst q = sql`select 1\n")
        self.write("good.sql", "select id from t;\n")
        out = self.scan()
        self.assertEqual(out["files_with_sql"], ["good.sql"])
        self.assertEqual([e["file"] for e in out["errors"]], ["bad.ts"])
        self.assertTrue(out["errors"][0]["message"])

    def test_tags_option_runs_the_extractor_with_the_list(self):
        self.write("a.ts", "const q = ctx.db`select id from t`;\n")
        self.assertEqual(self.scan("--tags", "ctx.db")["files_with_sql"], ["a.ts"])
        self.assertEqual(self.scan("--tags", "other")["files_with_sql"], [])

    def test_usage_errors(self):
        for args in ([], [self.repo, "--tags", ""], [self.repo, "--bogus"], [os.path.join(self.repo, "none")]):
            with self.subTest(args=args):
                code, out, err = run(*args)
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertEqual(len(err.strip().splitlines()), 1)

    def test_the_cap_is_1000_files_with_sql(self):
        for index in range(1001):
            self.write("f/%04d.sql" % index, "select 1;\n")
        out = self.scan()
        self.assertEqual(len(out["files_with_sql"]), 1000)
        self.assertTrue(out["truncated"])

    def test_exactly_1000_files_is_not_truncated(self):
        for index in range(1000):
            self.write("f/%04d.sql" % index, "select 1;\n")
        out = self.scan()
        self.assertEqual(len(out["files_with_sql"]), 1000)
        self.assertFalse(out["truncated"])


class CandidateTest(ScanCase):
    def test_every_pitfall_has_its_file_and_line(self):
        self.write("src/repo.ts", TAGGED)
        self.write("src/more.ts", "const sql = postgres();\nconst q = sql`\n  select * from t\n`;\n")
        out = self.scan()
        ids = [c["id"] for c in out["candidates"]]
        self.assertEqual(ids, ["PGJS-01", "PG-06", "PG-08"])
        self.assertEqual(self.candidate(out, "PGJS-01")["evidence"], [{"file": "src/repo.ts", "line": 6}])
        self.assertEqual(self.candidate(out, "PG-06")["evidence"], [{"file": "src/repo.ts", "line": 9}])
        self.assertEqual(self.candidate(out, "PG-08")["evidence"], [{"file": "src/more.ts", "line": 3}])
        for entry in out["candidates"]:
            self.assertEqual(entry["count"], 1)
            self.assertTrue(entry["text"])
            self.assertFalse(entry["text"].startswith(entry["id"]))

    def test_the_candidates_are_in_catalog_order(self):
        self.write(
            "a.ts",
            "const sql = postgres();\n"
            "const a = sql`select * from t where x like '%a' offset 2000`;\n"
            "const b = sql`select id from t where id in ${ids}`;\n"
            "const c = sql.unsafe('select ' + cols);\n",
        )
        ids = [c["id"] for c in self.scan()["candidates"]]
        self.assertEqual(ids, ["PGJS-01", "PGJS-04", "PG-06", "PG-08", "PG-10"])

    def test_evidence_is_capped_at_five_and_count_is_total(self):
        body = "".join("const q%d = sql`select id from t where x like '%%a'`;\n" % n for n in range(7))
        self.write("a.ts", "const sql = postgres();\n" + body)
        entry = self.candidate(self.scan(), "PG-06")
        self.assertEqual(entry["count"], 7)
        self.assertEqual(len(entry["evidence"]), 5)

    def test_pgjs_01(self):
        hit = self.template("select id from t where id in ${ids}")
        self.assertIsNotNone(self.candidate(hit, "PGJS-01"))
        hit = self.template("select id from t where id in (${sql(ids)})")
        self.assertIsNotNone(self.candidate(hit, "PGJS-01"))
        clean = self.template("select id from t where id in ${sql(ids)}")
        self.assertIsNone(self.candidate(clean, "PGJS-01"))
        spaced = self.template("select id from t where id in ${ sql(ids) }")
        self.assertIsNone(self.candidate(spaced, "PGJS-01"))
        spaced_bare = self.template("select id from t where id in ${ ids }")
        self.assertIsNotNone(self.candidate(spaced_bare, "PGJS-01"))

    def test_pgjs_01_tag_is_a_detected_tag_with_a_dot(self):
        self.write(
            "a.ts",
            "class A {\n  sql = postgres(u);\n  f(ids) {\n    return this.sql`select id from t where id in ${this.sql(ids)}`;\n  }\n}\n",
        )
        out = self.scan()
        self.assertEqual(out["detected_tags"], ["this.sql"])
        self.assertEqual(out["statements"], 1)
        self.assertIsNone(self.candidate(out, "PGJS-01"))

    def test_pgjs_01_tag_from_the_tags_option(self):
        self.write("a.ts", "const q = ctx.db`select id from t where id in ${ctx.db(ids)}`;\n")
        self.assertIsNone(self.candidate(self.scan("--tags", "ctx.db"), "PGJS-01"))

    def test_pg_06(self):
        self.assertIsNotNone(self.candidate(self.template("select id from t where n like '%abc'"), "PG-06"))
        self.assertIsNone(self.candidate(self.template("select id from t where n like 'abc%'"), "PG-06"))

    def test_pg_08(self):
        self.assertIsNotNone(self.candidate(self.template("select * from t"), "PG-08"))
        self.assertIsNotNone(self.candidate(self.template("select distinct * from t"), "PG-08"))
        self.assertIsNone(self.candidate(self.template("select count(*) from t"), "PG-08"))
        self.assertIsNone(
            self.candidate(self.template("select id from t where exists (select * from u)"), "PG-08")
        )

    def test_pg_08_does_not_fire_in_a_sql_file(self):
        self.write("q.sql", "select * from t;\n")
        self.assertIsNone(self.candidate(self.scan(), "PG-08"))

    def test_pg_10(self):
        self.assertIsNone(self.candidate(self.template("select id from t offset 1000"), "PG-10"))
        self.assertIsNotNone(self.candidate(self.template("select id from t offset 1001"), "PG-10"))

    def test_a_nested_template_is_not_scanned_twice(self):
        out = self.template("select id from t where 1 = 1 ${on ? sql`and n like '%a'` : sql``}")
        self.assertEqual(self.candidate(out, "PG-06")["count"], 1)

    def test_a_clean_statement_has_no_candidate(self):
        self.assertEqual(self.template("select id, name from t where id = ${1}")["candidates"], [])


class UnsafeTest(ScanCase):
    def unsafe(self, call):
        self.write("a.ts", "const sql = postgres();\nconst q = " + call + ";\n")
        return self.candidate(self.scan(), "PGJS-04")

    def test_a_constant_is_no_hit(self):
        self.assertIsNone(self.unsafe("sql.unsafe('select 1')"))
        self.assertIsNone(self.unsafe('sql.unsafe("select 1", [])'))
        self.assertIsNone(self.unsafe("sql.unsafe(`select 1`)"))

    def test_a_template_with_interpolation_a_concatenation_and_a_variable_are_hits(self):
        for call in ("sql.unsafe(`select ${cols}`)", "sql.unsafe('select ' + cols)", "sql.unsafe(query)"):
            with self.subTest(call=call):
                entry = self.unsafe(call)
                self.assertEqual(entry["evidence"], [{"file": "a.ts", "line": 2}])

    def test_the_tag_is_any_identifier_chain(self):
        self.assertIsNotNone(self.unsafe("this.sql.unsafe(query)"))
        self.assertIsNotNone(self.unsafe("tx.unsafe(query)"))

    def test_a_file_with_no_statement_is_still_read(self):
        self.write("a.ts", "export function f(db, q) {\n  return db.unsafe(q);\n}\n")
        out = self.scan()
        self.assertEqual(out["files_with_sql"], [])
        self.assertEqual(self.candidate(out, "PGJS-04")["evidence"], [{"file": "a.ts", "line": 2}])

    def test_a_sql_file_is_not_read_for_unsafe(self):
        self.write("a.sql", "select 1; -- db.unsafe(q)\n")
        self.assertIsNone(self.candidate(self.scan(), "PGJS-04"))

    def test_a_file_the_extractor_cannot_read_is_not_read_for_unsafe(self):
        self.write("bad.ts", "const sql = postgres();\nconst q = sql`select 1\nsql.unsafe(x);\n")
        out = self.scan()
        self.assertEqual([e["file"] for e in out["errors"]], ["bad.ts"])
        self.assertIsNone(self.candidate(out, "PGJS-04"))


if __name__ == "__main__":
    unittest.main()
