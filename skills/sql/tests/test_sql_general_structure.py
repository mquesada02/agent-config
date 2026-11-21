import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
GENERAL = os.path.join(SKILL_DIR, "dialects", "general.md")
POSTGRES = os.path.join(SKILL_DIR, "dialects", "postgres.md")
READER = os.path.join(SKILL_DIR, "scripts", "rules_file.py")

FIELDS = ["Title", "Severity", "Detects", "Why it matters", "Fix", "Example", "Source", "From"]
LEVELS = ["suggestion", "required", "critical"]
TOKENS = ["::", "ILIKE", "jsonb", "pg_", "$1"]
ENGINES = ["PostgreSQL", "MySQL", "MariaDB", "SQLite", "SQL Server", "Oracle", "Db2"]
ENGINE_NAME = re.compile(r"\b(?:" + "|".join(re.escape(name) for name in ENGINES) + r")\b", re.I)
SKILL_RULE = "skill rule"


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def section(text, heading):
    match = re.search(rf"^## {re.escape(heading)}$", text, re.M)
    assert match, f"no section {heading}"
    return text[match.end():].split("\n## ", 1)[0]


def parse_rules(body):
    """The rule entries of a body: id -> list of (field, text) in order, and the heading ids in order."""
    result, order = {}, []
    for block in re.split(r"(?m)^### ", body)[1:]:
        rule_id, _, rest = block.partition("\n")
        rule_id = rule_id.strip()
        order.append(rule_id)
        fields = []
        for part in re.split(r"(?m)^(?=- \*\*[^*]+:\*\*)", rest):
            match = re.match(r"- \*\*([^*]+):\*\* ?(.*)", part, re.S)
            if match:
                fields.append((match.group(1), match.group(2).strip()))
        result[rule_id] = fields
    return result, order


def general_rules():
    return parse_rules(section(read(GENERAL), "Rules"))


def field(rule, name):
    return dict(rule)[name]


def pg_severities():
    """Severity of every PG-* and PLAN-* rule of the PostgreSQL module."""
    text = read(POSTGRES)
    result = {}
    for block in re.split(r"(?m)^### ", text)[1:]:
        rule_id, _, rest = block.partition("\n")
        match = re.search(r"(?m)^- \*\*Severity:\*\* (\w+)", rest)
        if match and re.match(r"(?:PG|PLAN)-\d+$", rule_id.strip()):
            result[rule_id.strip()] = match.group(1)
    return result


def sources():
    """Name -> URL of each entry of the `## Sources` section."""
    result = {}
    for line in section(read(GENERAL), "Sources").splitlines():
        if line.startswith("- "):
            match = re.match(r"- \*\*([^*]+):\*\* (https?://\S+?)\.\s", line)
            result[match.group(1) if match else line] = match.group(2) if match else None
    return result


def from_ids(rule):
    value = field(rule, "From").strip()
    return [] if value == "none" else re.findall(r"(?:PG|PLAN)-\d+", value)


def reader_disabled_without_reason(candidates, with_reason=False):
    entries = ", ".join(f'"{c}"' for c in candidates)
    toml = "[rules]\ndisabled = [" + entries + "]\n"
    reasons = "".join(f"\n- {c}: not needed here\n" for c in candidates) if with_reason else ""
    with tempfile.TemporaryDirectory() as repo:
        os.makedirs(os.path.join(repo, "docs", "agents"))
        with open(os.path.join(repo, "docs", "agents", "sql.md"), "w", encoding="utf-8") as handle:
            handle.write("# SQL rules\n\n```toml\n" + toml + "```\n" + reasons)
        proc = subprocess.run([sys.executable, READER, repo], capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


class ModuleShapeTest(unittest.TestCase):
    def test_the_module_says_it_is_the_single_source_of_truth(self):
        self.assertIn("single source of truth for the GEN rules", read(GENERAL))

    def test_the_ids_run_from_gen_01_with_no_gap(self):
        _, order = general_rules()
        self.assertEqual(order, [f"GEN-{n:02d}" for n in range(1, len(order) + 1)])
        self.assertGreaterEqual(len(order), 1)

    def test_each_rule_has_the_eight_fields_in_order_with_text(self):
        rules, _ = general_rules()
        for rule_id, rule in rules.items():
            self.assertEqual([name for name, _ in rule], FIELDS, rule_id)
            for name, text in rule:
                self.assertTrue(text, f"{rule_id} {name}")

    def test_each_severity_is_a_known_level(self):
        rules, _ = general_rules()
        for rule_id, rule in rules.items():
            self.assertIn(field(rule, "Severity"), LEVELS, rule_id)

    def test_each_example_has_a_bad_and_a_good_sql_block(self):
        rules, _ = general_rules()
        for rule_id, rule in rules.items():
            self.assertGreaterEqual(len(re.findall(r"```sql\n", field(rule, "Example"))), 2, rule_id)


class SourcesTest(unittest.TestCase):
    def test_each_source_entry_has_a_name_and_a_url(self):
        entries = sources()
        self.assertTrue(entries)
        for name, url in entries.items():
            self.assertIsNotNone(url, name)

    def test_each_source_is_an_entry_or_skill_rule(self):
        rules, _ = general_rules()
        entries = sources()
        for rule_id, rule in rules.items():
            value = field(rule, "Source")
            self.assertTrue(value == SKILL_RULE or value in entries, f"{rule_id}: {value}")

    def test_each_entry_is_the_source_of_a_rule(self):
        rules, _ = general_rules()
        used = {field(rule, "Source") for rule in rules.values()}
        for name in sources():
            self.assertIn(name, used)


class FromAndSeverityTest(unittest.TestCase):
    def test_each_from_id_exists_in_the_postgres_module(self):
        rules, _ = general_rules()
        known = pg_severities()
        for rule_id, rule in rules.items():
            value = field(rule, "From").strip()
            ids = from_ids(rule)
            self.assertTrue(value == "none" or ids, f"{rule_id}: {value}")
            for pg_id in ids:
                self.assertIn(pg_id, known, rule_id)

    def test_the_severity_follows_the_from_rule(self):
        rules, _ = general_rules()
        levels = pg_severities()
        for rule_id, rule in rules.items():
            ids = from_ids(rule)
            if ids:
                expected = max((levels[i] for i in ids), key=LEVELS.index)
            elif "parameters" in field(rule, "Title").lower():
                expected = "critical"
            else:
                expected = "required"
            self.assertEqual(field(rule, "Severity"), expected, rule_id)

    def test_the_only_plan_id_in_a_from_field_is_plan_02(self):
        rules, _ = general_rules()
        for rule in rules.values():
            for pg_id in from_ids(rule):
                if pg_id.startswith("PLAN-"):
                    self.assertEqual(pg_id, "PLAN-02")


class TopicTest(unittest.TestCase):
    def test_every_topic_of_the_spec_has_a_rule(self):
        rules, _ = general_rules()
        all_from = {i for rule in rules.values() for i in from_ids(rule)}
        for n in range(1, 11):
            self.assertIn(f"PG-{n:02d}", all_from)
        titles = {rule_id: field(rule, "Title").lower() for rule_id, rule in rules.items()}
        self.assertTrue(any("parameters" in t and not from_ids(rules[i]) for i, t in titles.items()))
        self.assertTrue(any(from_ids(rule) == ["PLAN-02"] for rule in rules.values()))
        self.assertTrue(any("migrations" in t for t in titles.values()))


class ContentTest(unittest.TestCase):
    def rule_with_from(self, pg_id):
        rules, _ = general_rules()
        found = [rule for rule in rules.values() if pg_id in from_ids(rule)]
        self.assertEqual(len(found), 1, pg_id)
        return found[0]

    def test_pg_02_idea_has_no_facts_or_catalog_and_uses_not_exists(self):
        rule = self.rule_with_from("PG-02")
        for name in ("Detects", "Why it matters", "Fix"):
            text = field(rule, name).lower()
            self.assertNotIn("facts", text)
            self.assertNotIn("catalog", text)
        self.assertIn("NOT EXISTS", field(rule, "Fix"))
        self.assertIn("nullable", field(rule, "Detects"))

    def test_the_select_star_rule_keeps_its_exclusions(self):
        detects = field(self.rule_with_from("PG-08"), "Detects")
        self.assertIn("count(*)", detects)
        self.assertIn("EXISTS", detects)

    def test_the_type_mismatch_fix_uses_cast_and_no_double_colon(self):
        fix = field(self.rule_with_from("PG-03"), "Fix")
        self.assertIn("CAST", fix)
        self.assertNotIn("::", fix)

    def test_the_like_rule_names_no_ilike_and_no_trigram(self):
        rule = self.rule_with_from("PG-06")
        for name in ("Detects", "Fix"):
            self.assertNotIn("ILIKE", field(rule, name))
            self.assertNotIn("trigram", field(rule, name).lower())

    def test_the_index_rule_checks_the_schema(self):
        self.assertIn("schema", field(self.rule_with_from("PLAN-02"), "Detects"))

    def test_the_migration_rule_covers_its_points_and_names_no_engine(self):
        rules, _ = general_rules()
        rule = [r for r in rules.values() if "migrations" in field(r, "Title").lower()][0]
        text = "\n".join(value for _, value in rule).lower()
        for word in ("down step", "batch", "lock"):
            self.assertIn(word, text)
        self.assertIsNone(ENGINE_NAME.search(text))


class TokenTest(unittest.TestCase):
    def test_detects_and_fix_hold_no_postgres_only_token(self):
        rules, _ = general_rules()
        for rule_id, rule in rules.items():
            for name in ("Detects", "Fix"):
                for token in TOKENS:
                    self.assertNotIn(token, field(rule, name), f"{rule_id} {name}")

    def test_an_example_with_a_token_names_its_engine(self):
        rules, _ = general_rules()
        for rule_id, rule in rules.items():
            example = field(rule, "Example")
            if any(token in example for token in TOKENS):
                self.assertIsNotNone(ENGINE_NAME.search(example), rule_id)


class CatalogueTest(unittest.TestCase):
    def test_the_reader_catalogue_equals_the_gen_ids_of_the_module(self):
        _, order = general_rules()
        candidates = [f"GEN-{n:02d}" for n in range(100)]
        data = reader_disabled_without_reason(candidates)
        self.assertEqual(sorted(data["disabled_without_reason"]), sorted(order))

    def test_a_disabled_gen_id_with_a_reason_is_not_unknown(self):
        data = reader_disabled_without_reason(["GEN-01"], with_reason=True)
        self.assertEqual(data["unknown_ids"], [])
        self.assertEqual(data["disabled_without_reason"], [])
        self.assertIsNone(data["error"])


if __name__ == "__main__":
    unittest.main()
