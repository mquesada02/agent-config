"""Structure tests of the general-mode review cases, the no-fallback grader of `clean`, and the mode-choice text."""
import json
import os
import re
import unittest

from skill_files import RULES, SKILL, frontmatter, general_rules, read
from test_eval_cases import (NO_EDIT_GRADERS, SECTION_GRADERS, case_dir, case_names, expect_lists, extra_graders,
                             grader_files, row_pattern)

FACT_NAMES = ("default_branch", "package_manager", "node_version_app", "engines", "scripts", "package_kind",
              "os_claims", "test_runners", "monorepo", "visibility", "runner_labels", "required_checks",
              "run_history", "existing_workflows", "installed_tools", "supported_node_majors", "environments",
              "plan", "rulesets", "classic_protection", "deploy_targets", "iac_tools", "aws_variables",
              "release_tool", "publish_target", "release_tag_pattern", "provenance", "deploy_history", "stack")

GENERAL_REVIEW = ("general-review-go-gitlab", "general-review-mixed-node-rust", "general-review-rust-github")
CLASH = "general-clash-rust-node"
ANY_PATHS = (".gitlab-ci.yml", "Jenkinsfile", "Cargo.toml", ".github/workflows/ci.yml", "src/main.rs")
SHELL_WRITES = ("sed -i s/a/b/ {p}", "echo x > {p}", "tee {p}", "mv a {p}", "cp a {p}", "printf x >> {p}")
SHELL_READS = ("cat {p}", "ls {p} 2>&1", "grep a {p} > /dev/null")
GEN_ROW = r"^\|\s*{rule}\s*\|"


def topic_of(rule_id):
    """The `## ` heading of general.md that holds the rule."""
    heading = None
    for line in read(os.path.join(RULES, "general.md")).splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
        elif line.strip() == f"### {rule_id}":
            return heading
    raise AssertionError(rule_id)


def graders(name):
    return os.path.join(case_dir(name), "graders")


class GeneralCaseList(unittest.TestCase):
    def test_the_general_cases_are_exactly_these(self):
        self.assertEqual({n for n in case_names() if n.startswith("general-")}, {*GENERAL_REVIEW, CLASH})

    def test_the_two_single_stack_cases_expect_3_or_4_gen_ids_from_2_topics_and_forbid_nothing(self):
        ids = {r for _, r, _ in general_rules()}
        for name in ("general-review-go-gitlab", "general-review-rust-github"):
            expect, forbid = expect_lists(name)
            self.assertIn(len(expect), (3, 4), name)
            self.assertEqual(len(set(expect)), len(expect), name)
            self.assertTrue(set(expect) <= ids, name)
            self.assertGreaterEqual(len({topic_of(r) for r in expect}), 2, name)
            self.assertEqual(forbid, [], name)

    def test_the_mixed_case_expects_gen_ids_and_normal_ids(self):
        expect, forbid = expect_lists("general-review-mixed-node-rust")
        ids = {r for _, r, _ in general_rules()}
        self.assertTrue(set(expect) & ids)
        self.assertTrue([r for r in expect if r not in ids])
        self.assertEqual(len(set(expect)), len(expect))
        self.assertEqual(forbid, [])

    def test_the_clash_case_expects_and_forbids_nothing(self):
        self.assertEqual(expect_lists(CLASH), ([], []))


class GeneralCaseFiles(unittest.TestCase):
    def test_each_case_has_its_files(self):
        for name in (*GENERAL_REVIEW, CLASH):
            for part in ("case.yaml", "scaffold.sh", "prompt.md", "expect.json", "repo"):
                self.assertTrue(os.path.exists(os.path.join(case_dir(name), part)), f"{name}/{part}")

    def test_each_case_has_a_recorded_intake_with_the_29_facts_and_a_detected_stack(self):
        for name in (*GENERAL_REVIEW, CLASH):
            with open(os.path.join(case_dir(name), "repo", "intake.json"), encoding="utf-8") as handle:
                intake = json.load(handle)
            self.assertEqual(sorted(intake), sorted(FACT_NAMES), name)
            for fact, value in intake.items():
                self.assertEqual(sorted(value), ["source", "status", "value"], f"{name} {fact}")
            self.assertEqual(intake["stack"]["status"], "detected", name)

    def test_the_prompt_points_to_the_intake_and_names_neither_the_skill_nor_a_rule(self):
        for name in (*GENERAL_REVIEW, CLASH):
            prompt = read(os.path.join(case_dir(name), "prompt.md"))
            self.assertIn("intake.json", prompt, name)
            self.assertIn("do not run the intake script", prompt, name)
            self.assertNotIn("cicd-pipelines", prompt.lower(), name)
            self.assertIsNone(re.search(r"\b[A-Za-z]+-\d\d\b", prompt), name)

    def test_the_clash_repo_holds_a_cargo_manifest_and_the_prompt_asks_for_a_node_pipeline(self):
        self.assertTrue(os.path.exists(os.path.join(case_dir(CLASH), "repo", "Cargo.toml")))
        self.assertIn("Node", read(os.path.join(case_dir(CLASH), "prompt.md")))

    def test_the_go_case_has_a_gitlab_file_and_no_workflow_and_the_mixed_case_has_a_nested_cargo_manifest(self):
        go = os.path.join(case_dir("general-review-go-gitlab"), "repo")
        self.assertTrue(os.path.exists(os.path.join(go, ".gitlab-ci.yml")))
        self.assertTrue(os.path.exists(os.path.join(go, "go.mod")))
        self.assertFalse(os.path.exists(os.path.join(go, ".github")))
        mixed = os.path.join(case_dir("general-review-mixed-node-rust"), "repo")
        self.assertTrue(os.path.exists(os.path.join(mixed, "package.json")))
        self.assertTrue(os.path.exists(os.path.join(mixed, "crates", "engine", "Cargo.toml")))


class GeneralFixtureFaults(unittest.TestCase):
    """A listed GEN id must be a fault that the fixture clearly holds, so a correct reply flags it."""

    def test_the_go_case_builds_script_text_from_an_untrusted_value_for_the_untrusted_value_rule(self):
        text = read(os.path.join(case_dir("general-review-go-gitlab"), "repo", ".gitlab-ci.yml"))
        self.assertIn("GEN-20", expect_lists("general-review-go-gitlab")[0])
        self.assertRegex(text, r'(?m)^\s*- eval ".*\$CI_COMMIT_MESSAGE')


class GeneralCaseGraders(unittest.TestCase):
    def test_the_no_edit_graders_match_any_path(self):
        for name in (*GENERAL_REVIEW, CLASH):
            for file, tool in NO_EDIT_GRADERS.items():
                meta = frontmatter(os.path.join(graders(name), file))
                self.assertEqual((meta["type"], meta["tool"], meta["min"], meta["max"]), ("tool_used", tool, "0", "0"))
                pattern = re.compile(meta["input_match"])
                for path in ANY_PATHS:
                    if tool == "Bash":
                        for command in SHELL_WRITES:
                            self.assertTrue(pattern.search(command.format(p=path)), f"{name} {file} {command}")
                    else:
                        self.assertTrue(pattern.search(json.dumps({"file_path": path})), f"{name} {file} {path}")
                if tool == "Bash":
                    for command in SHELL_READS:
                        self.assertFalse(pattern.search(command.format(p=ANY_PATHS[0])), f"{name} {file} {command}")

    def test_the_review_cases_have_the_marker_grader_and_one_expect_grader_for_each_id(self):
        ids = {r for _, r, _ in general_rules()}
        for name in GENERAL_REVIEW:
            marker = frontmatter(os.path.join(graders(name), "general-report.md"))
            self.assertEqual((marker["type"], marker["pattern"], marker["flags"]), ("regex", "^General guidance:", "m"))
            expect, _ = expect_lists(name)
            for rule in expect:
                meta = frontmatter(os.path.join(graders(name), f"expect-{rule}.md"))
                want = GEN_ROW.format(rule=rule) if rule in ids else row_pattern(rule)
                self.assertEqual((meta["type"], meta["pattern"], meta["flags"]), ("regex", want, "m"), f"{name} {rule}")
                self.assertNotIn("match", meta)

    def test_the_grader_sets(self):
        base = set(NO_EDIT_GRADERS)
        for name in ("general-review-go-gitlab", "general-review-rust-github"):
            expect, _ = expect_lists(name)
            self.assertEqual(grader_files(name), base | {"general-report.md"} | {f"expect-{r}.md" for r in expect}, name)
        expect, _ = expect_lists("general-review-mixed-node-rust")
        self.assertEqual(grader_files("general-review-mixed-node-rust"),
                         base | {"general-report.md"} | {f"{s}.md" for s in SECTION_GRADERS}
                         | {f"expect-{r}.md" for r in expect})
        self.assertEqual(grader_files(CLASH), base | {"no-fallback.md", "one-question.md"})

    def test_the_mixed_case_section_graders_are_regex_graders(self):
        for section in SECTION_GRADERS:
            meta = frontmatter(os.path.join(graders("general-review-mixed-node-rust"), f"{section}.md"))
            self.assertEqual((meta["type"], meta["flags"]), ("regex", "m"))

    def test_the_clash_case_forbids_the_fallback_line_and_has_a_judge_for_one_question(self):
        meta = frontmatter(os.path.join(graders(CLASH), "no-fallback.md"))
        self.assertEqual((meta["type"], meta["pattern"], meta["match"]), ("regex", "General guidance:", "not_contains"))
        judge = frontmatter(os.path.join(graders(CLASH), "one-question.md"))
        self.assertEqual(judge["type"], "llm")
        text = read(os.path.join(graders(CLASH), "one-question.md"))
        self.assertIn("one question", text)

    def test_clean_forbids_the_fallback_line(self):
        meta = frontmatter(os.path.join(graders("clean"), "no-fallback.md"))
        self.assertEqual((meta["type"], meta["pattern"], meta["match"]), ("regex", "General guidance:", "not_contains"))
        self.assertEqual(extra_graders("clean"), {"no-fallback.md"})


SKILL_MD = read(os.path.join(SKILL, "SKILL.md"))
REVIEW_MD = read(os.path.join(SKILL, "review.md"))
GENERAL_MD = read(os.path.join(RULES, "general.md"))


def part(text, start, end=None):
    low = text.lower()
    begin = low.index(start)
    return low[begin:low.index(end, begin + 1) if end else None]


class ModeChoiceText(unittest.TestCase):
    def test_pick_the_branch_has_the_mode_choice_before_the_review_bullet(self):
        section = part(SKILL_MD, "## pick the branch", "## loading by need")
        self.assertLess(section.index("general mode"), section.index("**review**"))
        for words in ("uncovered", "mixed repo", "clash", "fills", "the covered-part test", "one question",
                      "names one detected part", "limits the reply", "`unknown`", "which language and which ci system"):
            self.assertIn(words, section)
        self.assertLess(section.index("only the covered stack"), section.index("**review**"))

    def test_the_mode_choice_does_not_hold_the_bold_bullet_labels(self):
        section = SKILL_MD[SKILL_MD.index("## Pick the branch"):SKILL_MD.index("- **Review**")]
        self.assertNotIn("**Another edit**", section)
        self.assertNotIn("**Create**", section)

    def test_the_create_bullet_is_unchanged(self):
        self.assertIn("- **Create** (the user asks for a new CI workflow, CD workflows or both): follow [create.md](create.md).",
                      SKILL_MD)

    def test_another_edit_has_the_general_mode_rule(self):
        bullet = part(SKILL_MD, "- **another edit**", "## loading by need")
        for words in ("general mode", "line 1", "`- gen-nn:", "makes no edit", "runs no rule check", "mixed repo"):
            self.assertIn(words, bullet)

    def test_loading_by_need_loads_only_the_gen_file_for_a_repo_with_no_covered_part(self):
        section = part(SKILL_MD, "## loading by need", "## modules")
        for words in ("[rules/general.md](rules/general.md)", "no covered part", "no other rule file",
                      "mixed repo", "uncovered"):
            self.assertIn(words, section)

    def test_the_modules_entry_says_that_general_mode_loads_the_file(self):
        entry = [l for l in SKILL_MD.splitlines() if l.startswith("- [rules/general.md]")][0]
        self.assertNotIn("No mode loads", entry)
        self.assertIn("General mode loads it", entry)

    def test_the_general_rule_file_names_the_load_and_no_longer_says_that_no_mode_loads_it(self):
        self.assertNotIn("No mode loads", GENERAL_MD)
        self.assertIn("- General mode loads this file (see SKILL.md, \"Loading by need\").", GENERAL_MD)

    def test_the_description_is_unchanged(self):
        self.assertIn("description: cicd-pipelines creates or reviews GitHub Actions CI and CD for Node/TypeScript repos",
                      SKILL_MD)


class GeneralModeSection(unittest.TestCase):
    def test_the_section_sits_between_steps_and_intake_facts(self):
        low = REVIEW_MD.lower()
        self.assertLess(low.index("## steps"), low.index("## general mode"))
        self.assertLess(low.index("## general mode"), low.index("## intake facts"))

    def test_the_section_holds_the_reply_contract_in_order(self):
        section = part(REVIEW_MD, "## general mode", "## intake facts")
        order = ["general guidance:", "# cicd-pipelines general review: <scope>", "**result: n critical",
                 "`intake:` line", "`defaults:`", "`## critical`", "`| rule | where | problem | fix |`",
                 "`repo`", "the skill edits no file in general mode."]
        positions = [section.index(item) for item in order]
        self.assertEqual(positions, sorted(positions))
        for words in ("no required checks line", "no `## approve`", "no tools part", "no admin steps", "no job graph",
                      "two or more uncovered parts", "no ci system yet", "general part first", "their own result line",
                      "that has a finding"):
            self.assertIn(words, section)

    def test_step_1_loads_no_covered_rule_file_for_a_repo_with_no_covered_part(self):
        step = part(REVIEW_MD, "1. load the rule files by need", "2. read the intake json")
        self.assertIn("no covered part", step)
        self.assertIn("load no covered rule file", step)

    def test_the_approval_steps_apply_to_the_normal_part_only(self):
        section = part(REVIEW_MD, "## general mode", "## intake facts")
        self.assertIn("normal part only", section)

    def test_the_new_text_avoids_the_words_that_the_review_tests_ban(self):
        section = part(REVIEW_MD, "## general mode", "## intake facts") + part(SKILL_MD, "## pick the branch", "## modules")
        for word in ("interim", "command -v", "temporary", "load every rule file", "branch protection change needed"):
            self.assertNotIn(word, section)


if __name__ == "__main__":
    unittest.main()
