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

SINGLE_STACK = ("general-review-go-gitlab", "general-review-rust-github")
GENERAL_REVIEW = (*SINGLE_STACK, "general-review-mixed-node-rust")
CLASH = "general-clash-rust-node"
CREATE = "general-create-python-empty"
ALL_CASES = (*GENERAL_REVIEW, CLASH, CREATE)
CREATE_GRADERS = {"general-line-1.md": ("^General guidance:", "m"),
                  "general-stage.md": (r"^\s*\d+\.\s.*\bGEN-\d\d\b", "m"),
                  "general-last-line.md": (r"The skill edits no file in general mode\.\s*$", None)}
GEN_IDS = {rule_id for _, rule_id, _ in general_rules()}
SKILL_MD = read(os.path.join(SKILL, "SKILL.md"))
REVIEW_MD = read(os.path.join(SKILL, "review.md"))
GENERAL_MD = read(os.path.join(RULES, "general.md"))
CREATE_MD = read(os.path.join(SKILL, "create.md"))
ANY_PATHS = (".gitlab-ci.yml", "Jenkinsfile", "Cargo.toml", ".github/workflows/ci.yml", "src/main.rs")
SHELL_WRITES = ("sed -i s/a/b/ {p}", "echo x > {p}", "tee {p}", "mv a {p}", "cp a {p}", "printf x >> {p}")
SHELL_READS = ("cat {p}", "ls {p} 2>&1", "grep a {p} > /dev/null")
GEN_ROW = r"^\|\s*{rule}\s*\|"
DESCRIPTION = ("cicd-pipelines creates or reviews CI/CD: full rules for GitHub Actions in Node/TypeScript repos "
               "(deploy, release, rollback, npm publish, branch protection, rulesets, environments), general advice "
               "for other stacks. Use it to create, review, deploy, release or publish, to answer its question "
               "(yes, no, approval), and before you write or edit CI files (.github/workflows, .gitlab-ci.yml, "
               "Jenkinsfile).")
TRIGGER_CI_FILE = "trigger-general-ci-file"
TRIGGER_UNRELATED = "trigger-general-unrelated"
TRIGGER_CASES = (TRIGGER_CI_FILE, TRIGGER_UNRELATED)
CI_FILE_GRADERS = {"skill-fired.md", "general-line-1.md", "general-bullet.md", "general-last-line.md"}
UNRELATED_GRADERS = {"no-cicd-reply.md", "no-skill-call.md"}
TRIGGER_GRADER_FILES = ("general-line-1.md", "general-bullet.md", "general-last-line.md", "no-cicd-reply.md",
                        "no-skill-call.md")
INTAKE_LINE = ("The recorded intake output for this repo is in `intake.json`: use it as the repo facts and do not "
               "run the intake script.")
GO_GITLAB = "general-review-go-gitlab"


def topic_of(rule_id):
    """The `## ` heading of general.md that holds the rule."""
    heading = None
    for line in GENERAL_MD.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
        elif line.strip() == f"### {rule_id}":
            return heading
    raise AssertionError(rule_id)


def graders(name):
    return os.path.join(case_dir(name), "graders")


class GeneralCaseList(unittest.TestCase):
    def test_the_general_cases_are_exactly_these(self):
        self.assertEqual({n for n in case_names() if n.startswith("general-")}, set(ALL_CASES))

    def test_the_two_single_stack_cases_expect_3_or_4_gen_ids_from_2_topics_and_forbid_nothing(self):
        for name in SINGLE_STACK:
            expect, forbid = expect_lists(name)
            self.assertIn(len(expect), (3, 4), name)
            self.assertEqual(len(set(expect)), len(expect), name)
            self.assertTrue(set(expect) <= GEN_IDS, name)
            self.assertGreaterEqual(len({topic_of(r) for r in expect}), 2, name)
            self.assertEqual(forbid, [], name)

    def test_the_mixed_case_expects_gen_ids_and_normal_ids(self):
        expect, forbid = expect_lists("general-review-mixed-node-rust")
        self.assertTrue(set(expect) & GEN_IDS)
        self.assertTrue([r for r in expect if r not in GEN_IDS])
        self.assertEqual(len(set(expect)), len(expect))
        self.assertEqual(forbid, [])

    def test_the_clash_case_expects_and_forbids_nothing(self):
        self.assertEqual(expect_lists(CLASH), ([], []))

    def test_the_create_case_expects_and_forbids_nothing(self):
        self.assertEqual(expect_lists(CREATE), ([], []))


class GeneralCaseFiles(unittest.TestCase):
    def test_each_case_has_its_files(self):
        for name in ALL_CASES:
            for part in ("case.yaml", "scaffold.sh", "prompt.md", "expect.json", "repo"):
                self.assertTrue(os.path.exists(os.path.join(case_dir(name), part)), f"{name}/{part}")

    def test_each_case_has_a_recorded_intake_with_the_29_facts_and_the_stack_fact_of_its_repo(self):
        for name in ALL_CASES:
            with open(os.path.join(case_dir(name), "repo", "intake.json"), encoding="utf-8") as handle:
                intake = json.load(handle)
            self.assertEqual(sorted(intake), sorted(FACT_NAMES), name)
            for fact, value in intake.items():
                self.assertEqual(sorted(value), ["source", "status", "value"], f"{name} {fact}")
            if name == CREATE:
                self.assertEqual(intake["stack"]["status"], "unknown", name)
                self.assertEqual(intake["stack"]["value"], {"languages": [], "ci_systems": []}, name)
            else:
                self.assertEqual(intake["stack"]["status"], "detected", name)

    def test_the_create_repo_holds_only_the_recorded_intake(self):
        self.assertEqual(os.listdir(os.path.join(case_dir(CREATE), "repo")), ["intake.json"])

    def test_the_create_prompt_asks_for_a_python_pipeline_and_allows_writes_so_that_a_write_shows(self):
        prompt = os.path.join(case_dir(CREATE), "prompt.md")
        self.assertIn("Create a CI pipeline for our Python project.", read(prompt))
        meta = frontmatter(prompt)
        self.assertEqual(meta["max_turns"], "40")
        self.assertEqual(meta["allowed_tools"], "[Read, Glob, Grep, Skill, Bash, Write, Edit]")

    def test_the_prompt_points_to_the_intake_and_names_neither_the_skill_nor_a_rule(self):
        for name in ALL_CASES:
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
        for name in ALL_CASES:
            for file, tool in NO_EDIT_GRADERS.items():
                meta = frontmatter(os.path.join(graders(name), file))
                self.assertEqual((meta["type"], meta["tool"], meta["min"], meta["max"]), ("tool_used", tool, "0", "0"))
                pattern = re.compile(meta["input_match"])
                if tool == "Bash":
                    for path in ANY_PATHS:
                        for command in SHELL_WRITES:
                            self.assertTrue(pattern.search(command.format(p=path)), f"{name} {file} {command}")
                    for command in SHELL_READS:
                        self.assertFalse(pattern.search(command.format(p=ANY_PATHS[0])), f"{name} {file} {command}")
                else:
                    for path in ANY_PATHS:
                        self.assertTrue(pattern.search(json.dumps({"file_path": path})), f"{name} {file} {path}")

    def test_the_review_cases_have_the_marker_grader_and_one_expect_grader_for_each_id(self):
        for name in GENERAL_REVIEW:
            marker = frontmatter(os.path.join(graders(name), "general-report.md"))
            self.assertEqual((marker["type"], marker["pattern"], marker["flags"]), ("regex", "^General guidance:", "m"))
            expect, _ = expect_lists(name)
            for rule in expect:
                meta = frontmatter(os.path.join(graders(name), f"expect-{rule}.md"))
                want = GEN_ROW.format(rule=rule) if rule in GEN_IDS else row_pattern(rule)
                self.assertEqual((meta["type"], meta["pattern"], meta["flags"]), ("regex", want, "m"), f"{name} {rule}")
                self.assertNotIn("match", meta)

    def test_the_grader_sets(self):
        base = set(NO_EDIT_GRADERS)
        reply = base | {"general-report.md"}
        for name in SINGLE_STACK:
            expect, _ = expect_lists(name)
            self.assertEqual(grader_files(name), reply | {f"expect-{r}.md" for r in expect}, name)
        expect, _ = expect_lists("general-review-mixed-node-rust")
        self.assertEqual(grader_files("general-review-mixed-node-rust"),
                         reply | {f"{s}.md" for s in SECTION_GRADERS} | {f"expect-{r}.md" for r in expect})
        self.assertEqual(grader_files(CLASH), base | {"no-fallback.md", "one-question.md"})
        self.assertEqual(grader_files(CREATE), base | set(CREATE_GRADERS))

    def test_the_create_graders_are_regex_graders_with_the_spec_patterns(self):
        for file, (pattern, flags) in CREATE_GRADERS.items():
            meta = frontmatter(os.path.join(graders(CREATE), file))
            self.assertEqual((meta["type"], meta["pattern"], meta.get("flags")), ("regex", pattern, flags), file)
            self.assertNotIn("match", meta)

    def test_the_create_graders_accept_a_correct_plan_and_refuse_a_wrong_one(self):
        line1, stage, last = (re.compile(p, re.M if f else 0) for p, f in CREATE_GRADERS.values())
        good = ("General guidance: this repo uses Python with no CI system yet, which the skill does not cover. "
                "The advice comes from the cited sources, with no rule check.\n\n1. Checkout: get the code. Follows GEN-05.\n"
                "2. Test: run pytest. Follows GEN-05, GEN-17.\n\nThe skill edits no file in general mode.\n")
        self.assertTrue(line1.search(good))
        self.assertTrue(stage.search(good))
        self.assertTrue(last.search(good))
        self.assertIsNone(stage.search("1. Checkout: get the code.\n"))
        self.assertIsNone(line1.search("Here is a plan. General guidance: x"))
        self.assertIsNone(last.search(good + "Then the normal flow follows.\n"))

    def test_the_create_case_has_no_marker_so_the_eval_results_script_skips_it(self):
        self.assertFalse({"general-report.md", "section-summary.md"} & grader_files(CREATE))

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


def lowered_slice(text, start, end=None):
    low = text.lower()
    begin = low.index(start)
    return low[begin:low.index(end, begin + 1) if end else None]


GENERAL_SECTION = lowered_slice(REVIEW_MD, "## general mode", "## intake facts")
PICK_SECTION = lowered_slice(SKILL_MD, "## pick the branch", "## loading by need")


class ModeChoiceText(unittest.TestCase):
    def test_pick_the_branch_has_the_mode_choice_before_the_review_bullet(self):
        section = PICK_SECTION
        self.assertLess(section.index("general mode"), section.index("**review**"))
        for words in ("uncovered", "mixed repo", "clash", "fills", "the covered-part test", "one question",
                      "names one detected part", "limits the reply", "`unknown`", "which language and which ci system"):
            self.assertIn(words, section)
        self.assertLess(section.index("only the covered stack"), section.index("**review**"))

    def test_the_mode_choice_does_not_hold_the_bold_bullet_labels(self):
        section = SKILL_MD[SKILL_MD.index("## Pick the branch"):SKILL_MD.index("- **Review**")]
        self.assertNotIn("**Another edit**", section)
        self.assertNotIn("**Create**", section)

    def test_the_create_bullet_keeps_its_first_sentence_and_ends_with_the_general_mode_sentence(self):
        self.assertIn("- **Create** (the user asks for a new CI workflow, CD workflows or both): follow [create.md](create.md).",
                      SKILL_MD)
        bullet = [l for l in SKILL_MD.splitlines() if l.startswith("- **Create**")][0]
        self.assertTrue(bullet.endswith(
            'For an uncovered part, follow "General mode" in [create.md](create.md) and ask no CD question.'), bullet)

    def test_the_mode_choice_applies_general_mode_to_a_create_request(self):
        self.assertIn("general mode applies to a review, to a create request and to another edit.", PICK_SECTION)
        self.assertNotIn("a create request keeps the create text below", PICK_SECTION)
        self.assertIn('follow "general mode" in [create.md](create.md)', PICK_SECTION)

    def test_the_modules_entry_of_create_md_names_the_general_mode_section(self):
        entry = [l for l in SKILL_MD.splitlines() if l.startswith("- [create.md]")][0]
        self.assertIn("the general-mode section", entry)

    def test_another_edit_has_the_general_mode_rule(self):
        bullet = lowered_slice(SKILL_MD, "- **another edit**", "## loading by need")
        for words in ("general mode", "line 1", "`- gen-nn:", "makes no edit", "runs no rule check", "mixed repo"):
            self.assertIn(words, bullet)

    def test_loading_by_need_loads_only_the_gen_file_for_a_repo_with_no_covered_part(self):
        section = lowered_slice(SKILL_MD, "## loading by need", "## modules")
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

    def test_the_description_is_the_text_of_the_general_spec(self):
        description = frontmatter(os.path.join(SKILL, "SKILL.md"))["description"]
        self.assertEqual(description, DESCRIPTION)
        self.assertEqual(len(description), 399)


class GeneralModeSection(unittest.TestCase):
    def test_the_section_sits_between_steps_and_intake_facts(self):
        low = REVIEW_MD.lower()
        self.assertLess(low.index("## steps"), low.index("## general mode"))
        self.assertLess(low.index("## general mode"), low.index("## intake facts"))

    def test_the_section_holds_the_reply_contract_in_order(self):
        section = GENERAL_SECTION
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
        step = lowered_slice(REVIEW_MD, "1. load the rule files by need", "2. read the intake json")
        self.assertIn("no covered part", step)
        self.assertIn("load no covered rule file", step)

    def test_the_approval_steps_apply_to_the_normal_part_only(self):
        section = GENERAL_SECTION
        self.assertIn("normal part only", section)

    def test_the_new_text_avoids_the_words_that_the_review_tests_ban(self):
        section = GENERAL_SECTION + lowered_slice(SKILL_MD, "## pick the branch", "## modules")
        for word in ("interim", "command -v", "temporary", "load every rule file", "branch protection change needed"):
            self.assertNotIn(word, section)


CREATE_SECTION = lowered_slice(CREATE_MD, "## general mode", "## fill table")


class CreateGeneralModeSection(unittest.TestCase):
    def test_the_section_sits_between_steps_and_fill_table(self):
        low = CREATE_MD.lower()
        self.assertLess(low.index("## steps"), low.index("## general mode"))
        self.assertLess(low.index("## general mode"), low.index("## fill table"))

    def test_the_section_holds_the_reply_contract_in_order(self):
        order = ["line 1 of the general review", "a numbered plan", "follows gen-nn.", "one or more gen ids",
                 "the last line of the general part", "the skill edits no file in general mode."]
        positions = [CREATE_SECTION.index(item) for item in order]
        self.assertEqual(positions, sorted(positions))

    def test_the_section_says_what_it_does_not_do(self):
        for words in ("write no file", "ask no ci, cd or both question", "no deploy target question",
                      "no template", "no actionlint", "no `## approve`", "no table"):
            self.assertIn(words, CREATE_SECTION)

    def test_the_section_loads_the_general_rule_file_and_no_other_rule_file_for_a_repo_with_no_covered_part(self):
        for words in ("[rules/general.md](rules/general.md)", "no covered part", "load no other rule file",
                      "a mixed repo", "covered part loads its own rule files"):
            self.assertIn(words, CREATE_SECTION)

    def test_the_section_orders_a_mixed_repo_and_limits_a_request_that_names_one_part(self):
        for words in ("general plan first", "normal create flow follows in full", "limits the reply to that part",
                      "only when the named part is uncovered", "only when the named part is covered"):
            self.assertIn(words, CREATE_SECTION)

    def test_the_section_says_when_the_unknown_stack_question_is_skipped(self):
        self.assertIn("names the language", CREATE_SECTION)
        self.assertIn("skip the unknown-stack question", CREATE_SECTION)

    def test_the_section_avoids_the_words_that_the_tests_ban(self):
        for word in ("interim", "command -v", "temporary", "load every rule file", "uses:"):
            self.assertNotIn(word, CREATE_SECTION)

    def test_the_seven_numbered_steps_stay_in_the_steps_section(self):
        steps = lowered_slice(CREATE_MD, "## steps", "## general mode")
        self.assertEqual(len(re.findall(r"(?m)^\d+\. ", steps)), 7)


def repo_files(name):
    base = os.path.join(case_dir(name), "repo")
    return sorted(os.path.relpath(os.path.join(root, f), base)
                  for root, _, files in os.walk(base) for f in files)


def prompt_lines(name):
    return read(os.path.join(case_dir(name), "prompt.md")).splitlines()


class TriggerGeneralCases(unittest.TestCase):
    """The two trigger cases of the general mode: the skill must fire for a CI file of another CI system, and not for
    an unrelated ask."""

    def test_the_cases_are_exactly_these_two(self):
        self.assertEqual({n for n in case_names() if n.startswith("trigger-general-")}, set(TRIGGER_CASES))

    def test_each_case_has_its_files_and_the_empty_expect_lists(self):
        for name in TRIGGER_CASES:
            for part in ("prompt.md", "case.yaml", "expect.json", "scaffold.sh", "repo", "graders"):
                self.assertTrue(os.path.exists(os.path.join(case_dir(name), part)), f"{name} has no {part}")
            self.assertEqual(expect_lists(name), ([], []), name)
            self.assertEqual(read(os.path.join(case_dir(name), "scaffold.sh")),
                             read(os.path.join(case_dir("trigger-edit-workflow"), "scaffold.sh")), name)

    def test_the_prompts_name_neither_the_skill_nor_a_rule_and_use_the_front_matter_of_the_edit_trigger(self):
        for name in TRIGGER_CASES:
            prompt = read(os.path.join(case_dir(name), "prompt.md"))
            self.assertNotIn("cicd-pipelines", prompt, name)
            self.assertNotRegex(prompt, r"\b[A-Z]+-\d\d\b", name)
            self.assertEqual(frontmatter(os.path.join(case_dir(name), "prompt.md")),
                             frontmatter(os.path.join(case_dir("trigger-edit-workflow"), "prompt.md")), name)

    def test_the_ci_file_case_asks_for_a_gitlab_file_edit_and_points_to_the_recorded_intake(self):
        lines = prompt_lines(TRIGGER_CI_FILE)
        self.assertIn(".gitlab-ci.yml", lines[-2])
        self.assertEqual(lines[-1], INTAKE_LINE)
        self.assertEqual(lines[-1], prompt_lines(GO_GITLAB)[-1])

    def test_the_ci_file_repo_is_the_go_gitlab_repo_with_no_github_folder(self):
        self.assertEqual(repo_files(TRIGGER_CI_FILE),
                         [".gitlab-ci.yml", "cmd/app/main.go", "go.mod", "intake.json"])
        self.assertEqual(repo_files(TRIGGER_CI_FILE), repo_files(GO_GITLAB))
        for file in repo_files(TRIGGER_CI_FILE):
            self.assertEqual(read(os.path.join(case_dir(TRIGGER_CI_FILE), "repo", file)),
                             read(os.path.join(case_dir(GO_GITLAB), "repo", file)), file)

    def test_the_unrelated_repo_holds_one_sql_file_and_the_prompt_is_an_unrelated_ask(self):
        self.assertEqual(repo_files(TRIGGER_UNRELATED), [os.path.join("queries", "orders.sql")])
        self.assertEqual(prompt_lines(TRIGGER_UNRELATED)[-1],
                         "Fix the query in queries/orders.sql: it counts each order twice.")

    def test_the_grader_sets(self):
        self.assertEqual(grader_files(TRIGGER_CI_FILE), CI_FILE_GRADERS)
        self.assertEqual(grader_files(TRIGGER_UNRELATED), UNRELATED_GRADERS)
        for name in TRIGGER_CASES:
            self.assertFalse({"general-report.md", "section-summary.md"} & grader_files(name), name)

    def test_skill_fired_is_the_file_of_the_edit_trigger_and_sets_no_call_count(self):
        template = read(os.path.join(case_dir("trigger-edit-workflow"), "graders", "skill-fired.md"))
        self.assertEqual(read(os.path.join(graders(TRIGGER_CI_FILE), "skill-fired.md")), template)
        meta = frontmatter(os.path.join(graders(TRIGGER_CI_FILE), "skill-fired.md"))
        self.assertNotIn("min", meta)
        self.assertNotIn("max", meta)

    def test_the_ci_file_regex_graders_have_the_spec_patterns(self):
        want = {"general-line-1.md": ("^General guidance:", "m"),
                "general-bullet.md": (r"^\s*[-*]\s.*\bGEN-\d\d\b", "m"),
                "general-last-line.md": (r"The skill edits no file in general mode\.\s*$", None)}
        for file, (pattern, flags) in want.items():
            meta = frontmatter(os.path.join(graders(TRIGGER_CI_FILE), file))
            self.assertEqual((meta["type"], meta["pattern"], meta.get("flags")), ("regex", pattern, flags), file)
            self.assertNotIn("match", meta)

    def test_the_ci_file_graders_accept_a_correct_reply_and_refuse_a_wrong_one(self):
        line1, bullet, last = (re.compile(p, re.M if f else 0) for p, f in (
            ("^General guidance:", "m"), (r"^\s*[-*]\s.*\bGEN-\d\d\b", "m"),
            (r"The skill edits no file in general mode\.\s*$", None)))
        good = ("General guidance: this repo uses Go and GitLab CI, which the skill does not cover. The advice comes "
                "from the cited sources, with no rule check.\n\n- GEN-05: run the lint stage on every change.\n\n"
                "The skill edits no file in general mode.\n")
        self.assertTrue(line1.search(good) and bullet.search(good) and last.search(good))
        self.assertIsNone(line1.search("I will add the job.\n"))
        self.assertIsNone(bullet.search("1. GEN-05: run the lint stage.\n"))
        self.assertIsNone(bullet.search("- Run the lint stage.\n"))
        self.assertIsNone(last.search(good + "Done.\n"))

    def test_the_unrelated_graders(self):
        reply = frontmatter(os.path.join(graders(TRIGGER_UNRELATED), "no-cicd-reply.md"))
        self.assertEqual((reply["type"], reply["pattern"], reply["flags"], reply["match"]),
                         ("regex", "^# cicd-pipelines|General guidance:", "m", "not_contains"))
        found = re.compile(reply["pattern"], re.M)
        self.assertTrue(found.search("# cicd-pipelines general review: repo\n"))
        self.assertTrue(found.search("General guidance: this repo\n"))
        self.assertIsNone(found.search("The join repeats each order. Use a distinct count.\n"))
        call = frontmatter(os.path.join(graders(TRIGGER_UNRELATED), "no-skill-call.md"))
        fired = frontmatter(os.path.join(graders(TRIGGER_CI_FILE), "skill-fired.md"))
        self.assertEqual((call["type"], call["tool"], call["arm"], call["min"], call["max"]),
                         ("tool_used", "Skill", "with-only", "0", "0"))
        self.assertEqual(call["input_match"], fired["input_match"])
        self.assertTrue(re.search(call["input_match"], '{"skill": "cicd-pipelines"}'))
        self.assertTrue(re.search(call["input_match"], '{"skill": "plugin:cicd-pipelines"}'))
        self.assertFalse(re.search(call["input_match"], '{"skill": "other-skill"}'))

    def test_the_readme_names_each_new_case_of_the_effort_and_each_new_trigger_grader(self):
        text = read(os.path.join(SKILL, "evals", "README.md"))
        for name in (*ALL_CASES, *TRIGGER_CASES):
            self.assertIn(f"`{name}`", text, name)
        for file in ("no-fallback.md", *TRIGGER_GRADER_FILES):
            self.assertIn(f"`{file}`", text, file)
        self.assertRegex(text, r"(?m)^\| General triggers \| `trigger-general-\*` \|")


if __name__ == "__main__":
    unittest.main()
