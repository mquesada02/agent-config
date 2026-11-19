"""Structure tests of rules/general.md (the neutral GEN rules) and of the helpers that read it."""
import os
import re
import tempfile
import unittest

from skill_files import LEVELS, RULES, all_rules, general_rules, level, read, rule_entries, rule_files

GENERAL = os.path.join(RULES, "general.md")
TOPICS = ["Pipeline stages", "Triggers per event", "Caching", "Secrets and permissions", "Pinning",
          "Release and deploy safety"]
FIELDS = ["Severity", "Rule", "Check", "Fix", "Source", "From"]
EXCLUDED = {"MONO-02", "PROTECT-06", "NAME-09"}
LEANING = ("OpenSSF Scorecard", "OpenSSF SCM Best Practices")
SKILL_SOURCE_TOPICS = ("Caching", "Triggers per event", "Pinning")
RANK = {"critical": 2, "required": 1, "suggestion": 0}
ACTIONS_KEYS = ("needs:", "run:", "if:", "uses:", "runs-on:", "with:", "permissions:", "environment:", "concurrency:")
NODE_TOOLS = ("npm", "pnpm", "yarn", "npx", "Changesets", "Vitest", "Jest", "tsc")
WRITE_PHRASES = ("write a file", "write the file", "create a file", "create the file", "edit the file",
                 "write a workflow file", "create a workflow file", "edit a workflow file")


def sections():
    """The `## ` sections of general.md: a list of (heading, body text)."""
    parts = re.split(r"^## ", read(GENERAL), flags=re.M)[1:]
    return [(part.partition("\n")[0].strip(), part.partition("\n")[2]) for part in parts]


def topic_rules():
    """Map of topic heading to the GEN ids under it, in file order."""
    return {heading: re.findall(r"^### (GEN-\d\d)\b", body, re.M) for heading, body in sections()}


def sources():
    """The `## Sources` items as a list of (name, URL)."""
    body = dict(sections())["Sources"]
    return re.findall(r"^- (.+?): (https://\S+)$", body, re.M)


def source_names():
    return [name for name, _ in sources()]


def source_items(value):
    """The items of a Source value, each as a (listed name, section id) pair."""
    items = []
    for item in value.split("; "):
        matches = [n for n in source_names() if item == n or item.startswith(n + " ")]
        items.append((max(matches, key=len) if matches else None, item))
    return items


class GeneralRuleFileForm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = general_rules()
        cls.known = {rule_id: fields for _, rule_id, fields in all_rules()}

    def test_the_topic_headings_and_the_source_list_are_in_order(self):
        self.assertEqual([heading for heading, _ in sections()], TOPICS + ["Sources"])

    def test_every_topic_has_at_least_one_rule(self):
        for topic, ids in topic_rules().items():
            if topic != "Sources":
                self.assertTrue(ids, f"no GEN rule under {topic}")

    def test_the_gen_ids_are_unique_and_run_from_one_in_file_order_with_no_gap(self):
        ids = [rule_id for _, rule_id, _ in self.entries]
        self.assertEqual(ids, [f"GEN-{n:02d}" for n in range(1, len(ids) + 1)])

    def test_every_rule_has_its_six_fields_in_order(self):
        text = read(GENERAL)
        for _, rule_id, fields in self.entries:
            for field in FIELDS:
                self.assertTrue(fields.get(field), f"{rule_id} has no {field}")
            block = re.search(rf"^### {rule_id}\n(.*?)(?=^### |^## |\Z)", text, re.S | re.M).group(1)
            self.assertEqual(re.findall(r"^- \*\*(\w+):\*\*", block, re.M), FIELDS, rule_id)

    def test_the_check_of_every_rule_is_judgement(self):
        for _, rule_id, fields in self.entries:
            self.assertEqual(fields["Check"], "judgement", rule_id)

    def test_the_severity_is_the_most_severe_level_of_the_from_rules(self):
        for _, rule_id, fields in self.entries:
            self.assertIn(level(fields), LEVELS, rule_id)
            wanted = max((level(self.known[i]) for i in self.from_ids(fields)), key=RANK.get)
            self.assertEqual(level(fields), wanted, rule_id)

    @staticmethod
    def from_ids(fields):
        return [i.strip() for i in fields["From"].split(",")]

    def test_every_from_id_exists_and_the_from_ids_cover_every_rule_but_the_three_specific_ones(self):
        used = set()
        for _, rule_id, fields in self.entries:
            for from_id in self.from_ids(fields):
                self.assertIn(from_id, self.known, f"{rule_id} names {from_id}")
                used.add(from_id)
        self.assertEqual(used, set(self.known) - EXCLUDED)

    def test_the_gap_topics_use_skill_rule_as_their_source(self):
        topics = topic_rules()
        by_id = {rule_id: fields for _, rule_id, fields in self.entries}
        for topic in SKILL_SOURCE_TOPICS:
            for rule_id in topics[topic]:
                self.assertEqual(by_id[rule_id]["Source"], "skill rule", rule_id)

    def test_every_source_value_is_skill_rule_or_a_list_of_listed_names(self):
        used = set()
        for _, rule_id, fields in self.entries:
            value = fields["Source"]
            if value == "skill rule":
                continue
            items = source_items(value)
            for name, item in items:
                self.assertIsNotNone(name, f"{rule_id}: {item}")
                used.add(name)
            self.assertNotIn(items[0][0], LEANING, f"{rule_id} cites a GitHub-leaning source first")
        self.assertEqual(used, set(source_names()), "a listed source is unused")

    def test_the_source_list_has_one_item_for_each_name_and_each_url_once(self):
        names, urls = source_names(), [url for _, url in sources()]
        self.assertTrue(names)
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(urls), len(set(urls)))

    def test_no_rule_or_fix_text_names_an_actions_key_a_node_tool_or_an_action_reference(self):
        key = re.compile(r"(?<![\w-])(" + "|".join(re.escape(k) for k in ACTIONS_KEYS) + ")")
        tool = re.compile(r"\b(" + "|".join(NODE_TOOLS) + r")\b", re.I)
        for _, rule_id, fields in self.entries:
            for field in ("Rule", "Fix"):
                text = fields[field]
                self.assertIsNone(key.search(text), f"{rule_id} {field}")
                self.assertIsNone(tool.search(text), f"{rule_id} {field}")
                self.assertIsNone(re.search(r"[\w.-]+/[\w.-]+@", text), f"{rule_id} {field}")
                self.assertNotIn("gh api", text, f"{rule_id} {field}")

    def test_no_fix_text_tells_the_skill_to_write_a_file(self):
        for _, rule_id, fields in self.entries:
            for phrase in WRITE_PHRASES:
                self.assertNotIn(phrase, fields["Fix"].lower(), rule_id)


class GeneralRuleHelpers(unittest.TestCase):
    def test_the_general_file_has_the_gen_prefix_and_all_rules_skips_it(self):
        from skill_files import PREFIXES
        self.assertEqual(PREFIXES["general"], "GEN")
        self.assertIn("general", rule_files())
        self.assertFalse([i for _, i, _ in all_rules() if i.startswith("GEN-")])
        self.assertTrue(all(name != "general" for name, _, _ in all_rules()))

    def test_general_rules_lists_only_the_gen_entries_of_the_file(self):
        entries = general_rules()
        self.assertTrue(entries)
        self.assertEqual([name for name, _, _ in entries], ["general"] * len(entries))
        self.assertEqual([i for _, i, _ in entries], [i for i, _ in rule_entries(GENERAL)])
        self.assertTrue(all(re.fullmatch(r"GEN-\d\d", i) for _, i, _ in entries))

    def test_the_parser_stops_a_field_at_a_second_level_heading(self):
        text = "### X-01\n- **Severity:** required\n- **Fix:** do it\n\n## Sources\n\n- A: https://example.com/a\n"
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "x.md")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            (rule_id, fields), = rule_entries(path)
        self.assertEqual(rule_id, "X-01")
        self.assertEqual(fields["Fix"], "do it")


if __name__ == "__main__":
    unittest.main()
