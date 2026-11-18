import ast
import os
import re
import sys
import unittest

import helper_testing_rules as helper

SKILL_MD = os.path.join(helper.SKILL, "SKILL.md")
LINK = re.compile(r"\]\(([^)\s]+)\)")
ID = re.compile(r"^(ASSERT|RUN|PAR|DBL|GRP|RS|TS)-\d{2}$")
SEVERITIES = ("critical", "required", "suggestion")
TEST_FILE_NAMES = re.compile(r"^(test_testing_|helper_testing_|grade_testing_).+\.py$")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def catalog_node():
    """The `CATALOG` dict literal of intake.py, read from its source (the script is never imported)."""
    tree = ast.parse(read(helper.SCRIPT))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "CATALOG" for target in node.targets
        ):
            return node.value
    raise AssertionError("intake.py has no CATALOG constant")


class SkillFilesTest(unittest.TestCase):
    def test_skill_md_names_the_skill(self):
        self.assertIn("\nname: testing\n", read(SKILL_MD).split("\n---\n", 1)[0] + "\n")

    def test_skill_md_names_the_detected_keys_and_the_file_arguments(self):
        text = read(SKILL_MD)
        for key in ("languages", "entries", "facts"):
            with self.subTest(key):
                self.assertIn(f"`{key}`", text)
        self.assertIn("intake.py <repo root> [file ...]", text)

    def test_every_file_the_router_links_exists(self):
        links = [link for link in LINK.findall(read(SKILL_MD)) if not re.match(r"^[a-z]+:", link)]
        self.assertIn("scripts/intake.py", links)
        for link in links:
            with self.subTest(link):
                self.assertTrue(os.path.exists(os.path.join(helper.SKILL, link.split("#")[0])))

    def test_every_test_module_follows_the_naming_rule(self):
        names = [n for n in os.listdir(helper.HERE) if n.endswith(".py") and n != "__init__.py"]
        self.assertTrue(names)
        for name in names:
            with self.subTest(name):
                self.assertRegex(name, TEST_FILE_NAMES)

    def test_test_folder_is_in_the_declared_test_command(self):
        text = read(os.path.join(helper.REPO, ".claude", "CLAUDE.md"))
        self.assertIn("'skills/testing/tests'", text)


class CatalogTest(unittest.TestCase):
    def test_catalog_is_a_literal_with_the_seed_ids_and_severities(self):
        node = catalog_node()
        self.assertIsInstance(node, ast.Dict)
        keys = [key.value for key in node.keys]
        self.assertEqual(len(keys), len(set(keys)), "a rule id is listed twice")
        self.assertEqual(ast.literal_eval(node), helper.SEEDS)

    def test_every_catalog_id_is_well_formed_with_a_known_severity(self):
        for rule_id, severity in ast.literal_eval(catalog_node()).items():
            with self.subTest(rule_id):
                self.assertRegex(rule_id, ID)
                self.assertIn(severity, SEVERITIES)


@unittest.skipUnless(sys.version_info >= (3, 11), "the script needs tomllib (Python 3.11 or newer)")
class CatalogUseTest(unittest.TestCase):
    def test_every_seed_id_is_known_to_unknown_ids(self):
        repo = helper.Repo()
        self.addCleanup(repo.close)
        listed = ", ".join(f'"{rule_id}"' for rule_id in helper.SEEDS)
        prose = "".join(f"- {rule_id}: reason\n" for rule_id in helper.SEEDS)
        text = helper.block(replace={"rules": f"[rules]\ndisabled = [{listed}]\n"})
        repo.write(helper.doc(text, prose_after=prose))
        rules, _, code = helper.run_json(repo.root)
        self.assertEqual(code, 0)
        self.assertEqual(rules["unknown_ids"], [])
        self.assertEqual(rules["disabled_without_reason"], [])


if __name__ == "__main__":
    unittest.main()
