"""Tests of the create eval cases (evals/create-*): files, graders, recorded intake and synthetic fixtures."""
import glob
import json
import os
import re
import subprocess
import sys
import unittest

from skill_files import EVALS, SKILL, all_rules, frontmatter, level, read
from test_create_steps import fenced_blocks, fill_pnpm, section, single_pnpm

SCRIPT = os.path.join(SKILL, "scripts", "check_workflow.py")
CI, DEP, SEC = ".github/workflows/ci.yml", ".github/dependabot.yml", ".github/workflows/security-audit.yml"
WRITING = ["create-npm-app", "create-pnpm-library", "create-pnpm-turbo-monorepo", "create-playwright-app"]
CASES = WRITING + ["create-no-lockfile"]
FACTS = ["default_branch", "package_manager", "node_version_app", "engines", "scripts", "package_kind", "os_claims",
         "test_runners", "monorepo", "visibility", "runner_labels", "required_checks", "run_history",
         "existing_workflows", "installed_tools", "supported_node_majors"]
SECTIONS = ["approve", "checks", "graph", "intake", "summary", "tools"]


def case_dir(name):
    return os.path.join(EVALS, name)


def load(name, *parts):
    with open(os.path.join(case_dir(name), *parts), encoding="utf-8") as handle:
        return json.load(handle)


def grader_files(name):
    return {os.path.basename(p) for p in glob.glob(os.path.join(case_dir(name), "graders", "*.md"))}


def meta(name, grader):
    return frontmatter(os.path.join(case_dir(name), "graders", grader + ".md"))


def check(text, *asserts):
    done = subprocess.run([sys.executable, "-I", SCRIPT, "-", "--assert", *asserts], input=text,
                          capture_output=True, text=True)
    return done.returncode, done.stdout.splitlines()


def clean_forbid():
    return load("clean", "expect.json")["forbid"]


def filled(case):
    """The workflow that the create steps give for a case, made from a template by the fill table values."""
    template = read(os.path.join(SKILL, "templates", "monorepo.yml" if "monorepo" in case else "single-package.yml"))
    if case == "create-pnpm-library":
        return single_pnpm().replace("        node: [26]\n", "        node: [22, 24, 26]\n")
    if case == "create-pnpm-turbo-monorepo":
        return fill_pnpm(os.path.join(SKILL, "templates", "monorepo.yml")).replace(
            "        node: [26]\n", "        node: [22, 24, 26]\n")
    if case == "create-playwright-app":
        block = fenced_blocks(section(read(os.path.join(SKILL, "create.md")), "### Playwright steps"))[0]
        return template.replace("        run: npm run test\n", "        run: npm run test\n" + block)
    return template


class Files(unittest.TestCase):
    def test_the_create_cases_are_exactly_these_five(self):
        found = sorted(os.path.basename(p) for p in glob.glob(os.path.join(EVALS, "create-*")))
        self.assertEqual(found, sorted(CASES))

    def test_the_prompt_asks_for_ci_and_points_to_the_recorded_intake(self):
        for name in CASES:
            text = read(os.path.join(case_dir(name), "prompt.md"))
            self.assertIn("Create CI for this repo.", text, name)
            self.assertIn("`intake.json`", text, name)
            self.assertIn("do not run the intake script", text, name)
            tools = frontmatter(os.path.join(case_dir(name), "prompt.md"))["allowed_tools"]
            for tool in ("Read", "Glob", "Grep", "Skill", "Bash", "Write", "Edit"):
                self.assertIn(tool, tools, name)
            self.assertNotIn("ci-pipelines", text.lower(), name)

    def test_the_scaffold_only_copies_the_fixture(self):
        for name in CASES:
            text = read(os.path.join(case_dir(name), "scaffold.sh"))
            self.assertIn('cp -r "$here/repo/." .', text, name)
            self.assertNotIn("git", text, name)

    def test_no_fixture_holds_a_ci_workflow(self):
        for name in CASES:
            self.assertFalse(os.path.exists(os.path.join(case_dir(name), "repo", CI)), name)


class RecordedIntake(unittest.TestCase):
    def test_the_file_holds_the_16_facts_in_order_with_their_three_keys(self):
        for name in CASES:
            intake = load(name, "repo", "intake.json")
            self.assertEqual(list(intake), FACTS, name)
            for fact, body in intake.items():
                self.assertEqual(sorted(body), ["source", "status", "value"], f"{name} {fact}")

    def test_the_recorded_intake_says_that_actionlint_is_installed(self):
        for name in CASES:
            tools = load(name, "repo", "intake.json")["installed_tools"]["value"]
            self.assertTrue(tools["actionlint"]["installed"], name)
            self.assertTrue(tools["actionlint"]["version"], name)

    def test_the_offline_node_list_names_tools_md(self):
        for name in CASES:
            source = load(name, "repo", "intake.json")["supported_node_majors"]["source"]
            self.assertIn("tools.md", source, name)

    def test_the_lockfile_is_null_only_in_the_no_lockfile_case(self):
        for name in CASES:
            lockfile = load(name, "repo", "intake.json")["package_manager"]["value"]["lockfile"]
            self.assertEqual(lockfile is None, name == "create-no-lockfile", name)

    def test_the_scripts_fact_lists_the_four_script_names_of_each_package(self):
        for name in CASES:
            entries = load(name, "repo", "intake.json")["scripts"]["value"]
            self.assertTrue(entries, name)
            for entry in entries:
                self.assertEqual(entry["value"], ["build", "lint", "test", "typecheck"], name)

    def test_each_case_records_the_facts_that_its_asserts_rest_on(self):
        facts = {name: load(name, "repo", "intake.json") for name in CASES}
        self.assertEqual(facts["create-npm-app"]["node_version_app"]["value"], "26")
        self.assertEqual(facts["create-npm-app"]["package_manager"]["value"]["manager"], "npm")
        self.assertEqual(facts["create-pnpm-library"]["engines"]["value"][0]["value"], ">=22")
        self.assertEqual(facts["create-pnpm-library"]["package_manager"]["value"]["manager"], "pnpm")
        monorepo = facts["create-pnpm-turbo-monorepo"]
        self.assertEqual(monorepo["monorepo"]["value"], {"monorepo": True, "tool": "turbo"})
        published = {e["path"]: e["value"] for e in monorepo["package_kind"]["value"]}
        self.assertEqual(sorted(path for path, kind in published.items() if kind == "published"),
                         ["packages/example-core", "packages/example-utils"])
        engines = {e["path"]: e["value"] for e in monorepo["engines"]["value"]}
        self.assertEqual((engines["packages/example-core"], engines["packages/example-utils"]), (">=22", ">=24"))
        self.assertEqual(monorepo["existing_workflows"]["value"], [SEC])
        self.assertEqual(facts["create-playwright-app"]["test_runners"]["value"], ["@playwright/test"])
        for name in ("create-npm-app", "create-pnpm-library", "create-playwright-app", "create-no-lockfile"):
            self.assertEqual(facts[name]["existing_workflows"]["value"], [], name)


class ExpectFiles(unittest.TestCase):
    def test_the_writing_cases_forbid_the_clean_list_and_expect_nothing(self):
        wanted = [rule_id for _, rule_id, fields in all_rules() if level(fields) in ("critical", "required")]
        self.assertEqual(sorted(clean_forbid()), sorted(wanted))
        for name in WRITING:
            data = load(name, "expect.json")
            self.assertEqual((data["expect"], data["forbid"]), ([], clean_forbid()), name)

    def test_the_no_lockfile_case_has_empty_lists_and_no_asserts(self):
        self.assertEqual(load("create-no-lockfile", "expect.json"), {"expect": [], "forbid": []})

    def test_the_asserts_are_the_spec_values(self):
        asserts = {name: load(name, "expect.json")["asserts"] for name in WRITING}
        self.assertEqual(set(asserts["create-npm-app"]), {CI, DEP, SEC})
        self.assertIn("matrix-node=26", asserts["create-npm-app"][CI])
        self.assertIn("install=npm ci", asserts["create-npm-app"][CI])
        self.assertEqual(asserts["create-npm-app"][DEP], ["dependabot"])
        self.assertEqual(asserts["create-npm-app"][SEC], ["security-audit"])
        self.assertIn("matrix-node=22,24,26", asserts["create-pnpm-library"][CI])
        self.assertIn("install=pnpm install --frozen-lockfile", asserts["create-pnpm-library"][CI])
        self.assertEqual(set(asserts["create-pnpm-turbo-monorepo"]), {CI})
        for needed in ("affected-run=turbo", "matrix-node=22,24,26", "install=pnpm install --frozen-lockfile"):
            self.assertIn(needed, asserts["create-pnpm-turbo-monorepo"][CI])
        for needed in ("text=playwright install", "workers=1", "no-text=ms-playwright"):
            self.assertIn(needed, asserts["create-playwright-app"][CI])
        self.assertNotIn("workers=1", asserts["create-npm-app"][CI])
        self.assertNotIn("affected-run=turbo", asserts["create-npm-app"][CI])

    def test_every_writing_case_expects_each_create_timeout_and_a_wrong_one_fails(self):
        values = ["changes:5", "ci-passed:5", "lint:10", "typecheck:10", "build:10", "audit:10", "test:15"]
        for name in WRITING:
            asserts = load(name, "expect.json")["asserts"][CI]
            for value in values:
                self.assertIn(f"timeout={value}", asserts, name)
            slow = re.sub(r"(  audit:\n(?:    .*\n)*?    timeout-minutes: )10", r"\g<1>30", filled(name))
            self.assertNotEqual(slow, filled(name), name)
            code, lines = check(slow, *asserts)
            self.assertEqual(code, 1, name)
            self.assertTrue(any(line.startswith("FAIL timeout") for line in lines), (name, lines))

    def test_every_case_assertion_is_known_to_the_script(self):
        for name in WRITING:
            for path, names in load(name, "expect.json")["asserts"].items():
                code, _ = check("name: CI\n", *names)
                self.assertNotEqual(code, 2, f"{name} {path}")

    def test_every_rule_that_create_mode_claims_has_an_assertion_in_the_npm_case(self):
        names = {a.split("=")[0] for a in load("create-npm-app", "expect.json")["asserts"][CI]}
        for needed in ("name", "job", "job-names", "matrix-name", "named-run-steps", "gate", "no-needs-between",
                       "matrix-only-test", "matrix-node", "fail-fast", "no-shards", "triggers", "changes",
                       "concurrency", "timeouts", "timeout", "install", "no-text", "pinned-runners",
                       "checkout-depth", "pinned-uses", "permissions", "no-run-expr", "persist-credentials",
                       "no-privileged-trigger", "audit-job", "short-run-blocks", "short-comments"):
            self.assertIn(needed, names)

    def test_the_templates_filled_for_each_case_pass_the_asserts_of_that_case(self):
        for name in WRITING:
            code, lines = check(filled(name), *load(name, "expect.json")["asserts"][CI])
            self.assertEqual((code, lines), (0, ["PASS"]), name)

    def test_the_support_blocks_of_the_create_steps_pass_the_support_asserts(self):
        create = read(os.path.join(SKILL, "create.md"))
        dependabot = fenced_blocks(section(create, "### Dependabot block"))[0]
        audit = fenced_blocks(section(create, "### Security audit block"))[0]
        for name in ("create-npm-app", "create-pnpm-library", "create-playwright-app"):
            asserts = load(name, "expect.json")["asserts"]
            self.assertEqual(check(dependabot, *asserts[DEP]), (0, ["PASS"]), name)
            self.assertEqual(check(audit, *asserts[SEC]), (0, ["PASS"]), name)

    def test_the_existing_support_files_of_the_monorepo_pass_the_support_asserts(self):
        repo = os.path.join(case_dir("create-pnpm-turbo-monorepo"), "repo")
        self.assertEqual(check(read(os.path.join(repo, DEP)), "dependabot"), (0, ["PASS"]))
        self.assertEqual(check(read(os.path.join(repo, SEC)), "security-audit"), (0, ["PASS"]))


class Graders(unittest.TestCase):
    def expected_files(self, name, extra):
        return ({f"forbid-{rule}.md" for rule in clean_forbid()} | {f"section-{s}.md" for s in SECTIONS}
                | {"wrote-ci.md", "actionlint-after-write.md", "actionlint-ran.md", "gh-api-no-write.md"} | extra)

    def test_the_writing_cases_have_their_grader_sets(self):
        support = {"wrote-dependabot.md", "wrote-security-audit.md"}
        unchanged = {f"{prefix}-{stem}.md" for prefix in ("no-write", "no-edit") for stem in ("dependabot", "security-audit")}
        unchanged |= {"unchanged-dependabot.md", "unchanged-security-audit.md"}
        for name in WRITING:
            extra = unchanged if name == "create-pnpm-turbo-monorepo" else support
            self.assertEqual(grader_files(name), self.expected_files(name, extra), name)

    def test_the_no_lockfile_case_has_only_its_two_graders(self):
        self.assertEqual(grader_files("create-no-lockfile"), {"no-write-github.md", "names-COST-05.md"})
        write = meta("create-no-lockfile", "no-write-github")
        self.assertEqual((write["type"], write["tool"], write["input_match"], write["min"], write["max"]),
                         ("tool_used", "Write", r"\.github/", "0", "0"))
        cost = meta("create-no-lockfile", "names-COST-05")
        self.assertEqual((cost["type"], cost["pattern"]), ("regex", "COST-05"))

    def test_the_forbid_graders_are_the_clean_ones(self):
        for name in WRITING:
            for rule in clean_forbid():
                self.assertEqual(read(os.path.join(case_dir(name), "graders", f"forbid-{rule}.md")),
                                 read(os.path.join(case_dir("clean"), "graders", f"forbid-{rule}.md")), (name, rule))
            for section_name in SECTIONS:
                self.assertEqual(read(os.path.join(case_dir(name), "graders", f"section-{section_name}.md")),
                                 read(os.path.join(case_dir("clean"), "graders", f"section-{section_name}.md")))

    def test_the_write_graders_need_one_write_of_each_file_that_the_case_must_write(self):
        for name in WRITING:
            self.assertEqual(int(meta(name, "wrote-ci")["min"]), 1, name)
        for name in ("create-npm-app", "create-pnpm-library", "create-playwright-app"):
            self.assertEqual(int(meta(name, "wrote-dependabot")["min"]), 1, name)
            self.assertEqual(int(meta(name, "wrote-security-audit")["min"]), 1, name)

    def test_the_monorepo_case_allows_no_write_and_no_edit_of_its_two_support_files(self):
        name = "create-pnpm-turbo-monorepo"
        for stem in ("dependabot", "security-audit"):
            for tool in ("write", "edit"):
                grader = meta(name, f"no-{tool}-{stem}")
                self.assertEqual((grader["type"], grader["tool"], grader["min"], grader["max"]),
                                 ("tool_used", tool.capitalize(), "0", "0"))
            said = meta(name, f"unchanged-{stem}")
            self.assertEqual((said["type"], said["flags"]), ("regex", "m"))
        self.assertTrue(re.search(meta(name, "unchanged-dependabot")["pattern"],
                                  "- `.github/dependabot.yml` unchanged", re.M))
        self.assertFalse(re.search(meta(name, "unchanged-dependabot")["pattern"],
                                   "- `.github/dependabot.yml` written", re.M))

    def test_the_actionlint_graders_match_a_sample_call_and_a_sample_write(self):
        ran = meta("create-npm-app", "actionlint-ran")
        self.assertEqual((ran["type"], ran["tool"], int(ran["min"])), ("tool_used", "Bash", 1))
        self.assertTrue(re.search(ran["input_match"], "actionlint -format '{{json .}}'"))
        self.assertFalse(re.search(ran["input_match"], "npm run lint"))
        order = read(os.path.join(case_dir("create-npm-app"), "graders", "actionlint-after-write.md"))
        self.assertIn("type: tool_order", order)
        self.assertIn("before: Write", order)
        self.assertIn("after: { tool: Bash, input_match: actionlint }", order)
        wrote = meta("create-npm-app", "wrote-ci")
        self.assertEqual((wrote["type"], wrote["tool"]), ("tool_used", "Write"))
        self.assertTrue(re.search(wrote["input_match"], '{"file_path": "/work/.github/workflows/ci.yml"}'))
        self.assertFalse(re.search(wrote["input_match"], '{"file_path": "/work/.github/workflows/security-audit.yml"}'))
        self.assertFalse(re.search(wrote["input_match"], '{"file_path": "/work/.github/dependabot.yml"}'))
        no_write = meta("create-no-lockfile", "no-write-github")
        self.assertTrue(re.search(no_write["input_match"], '{"file_path": "/work/.github/dependabot.yml"}'))


class Readme(unittest.TestCase):
    def test_the_readme_documents_the_create_run_and_the_operator_actionlint_step(self):
        text = read(os.path.join(EVALS, "README.md"))
        create = text[text.index("## Create cases"):text.index("## Graders")]
        for needed in ("--case 'create-*'", '--allow-tools Write Edit "Bash(actionlint*)"', "grade_eval_results.py",
                       "grade_create_results.py", "NOT RUN actionlint: not on PATH", "Real actionlint",
                       "issue 362"):
            self.assertIn(needed, create)
        for name in CASES:
            self.assertIn(f"`{name}`", create)


class SyntheticFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.texts = {}
        for name in CASES:
            for path in glob.glob(os.path.join(case_dir(name), "repo", "**", "*"), recursive=True) + \
                    glob.glob(os.path.join(case_dir(name), "repo", ".github", "**", "*"), recursive=True):
                if os.path.isfile(path):
                    cls.texts[path] = read(path)

    def test_no_fixture_holds_a_token_literal(self):
        for path, text in self.texts.items():
            self.assertNotRegex(text, r"ghp_|gho_|github_pat_|AKIA|xox[bp]-", path)

    def test_every_secret_name_starts_with_example(self):
        for path, text in self.texts.items():
            for secret in re.findall(r"secrets\.([A-Za-z0-9_]+)", text):
                self.assertTrue(secret.startswith("EXAMPLE_"), (path, secret))

    def test_every_package_name_starts_with_example(self):
        for path, text in self.texts.items():
            if os.path.basename(path) in ("package.json", "package-lock.json") and "/intake.json" not in path:
                self.assertTrue(json.loads(text)["name"].startswith("example"), path)

    def test_no_fixture_names_an_org_or_repo_but_example_ones_and_no_other_url(self):
        for path, text in self.texts.items():
            self.assertNotRegex(re.sub(r"https://github\.com/example[\w-]*/example[\w-]*", "", text), r"https?://", path)

    def test_every_uses_owner_is_actions_or_pnpm(self):
        for path, text in self.texts.items():
            for owner in re.findall(r"uses:\s*([A-Za-z][^/\s@]*)/", text):
                self.assertIn(owner, ("actions", "pnpm"), path)


if __name__ == "__main__":
    unittest.main()
