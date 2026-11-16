import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL_DIR, "scripts")

sys.path.insert(0, SCRIPTS)

import sql_text  # noqa: E402

# A stand-in for `extract.py`: it prints its own argument list, in the JSON shape of a good run.
ARGV_ECHO = """import json, sys
print(json.dumps({"form": "js", "statements": [], "argv": sys.argv[1:], "error": None}))
"""


class RunExtractorCommandTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.stub = os.path.join(self.tmp, "extract_stub.py")
        with open(self.stub, "w", encoding="utf-8") as handle:
            handle.write(ARGV_ECHO)
        original = sql_text.EXTRACTOR
        sql_text.EXTRACTOR = self.stub
        self.addCleanup(setattr, sql_text, "EXTRACTOR", original)

    def argv(self, *args, **kwargs):
        data, message = sql_text.run_extractor("a.ts", *args, **kwargs)
        self.assertIsNone(message)
        return data["argv"]

    def test_no_options_gives_the_path_alone(self):
        self.assertEqual(self.argv(), ["a.ts"])

    def test_the_tags_alone_are_passed_as_before(self):
        self.assertEqual(self.argv("sql,tx"), ["a.ts", "--tags", "sql,tx"])

    def test_the_receivers_alone_are_passed_with_the_option(self):
        self.assertEqual(self.argv(receivers="pool,this.db"), ["a.ts", "--receivers", "pool,this.db"])

    def test_tags_and_receivers_are_both_passed(self):
        self.assertEqual(self.argv("sql", "pool"), ["a.ts", "--tags", "sql", "--receivers", "pool"])

    def test_none_for_the_receivers_passes_no_option(self):
        self.assertEqual(self.argv("sql", None), ["a.ts", "--tags", "sql"])


class RunExtractorRealTest(unittest.TestCase):
    """The real extractor: a receiver that the file cannot show matches only when it is given."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "a.ts")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("import { db } from './db';\ndb.query('select 1');\n")

    def test_an_imported_receiver_is_matched_only_with_the_receiver_list(self):
        data, message = sql_text.run_extractor(self.path)
        self.assertIsNone(message)
        self.assertEqual(data["statements"], [])
        data, message = sql_text.run_extractor(self.path, receivers="db")
        self.assertIsNone(message)
        self.assertEqual([s["source"] for s in data["statements"]], ["pg"])
        self.assertEqual(data["receivers"], ["db"])
        self.assertEqual(data["detected_receivers"], [])


if __name__ == "__main__":
    unittest.main()
