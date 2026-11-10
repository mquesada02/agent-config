"""Tests of the four approval eval cases: their fixture, recorded conversation, recorded intake and graders.

Each case gives a reply to a recorded review report. The graders are frontmatter files that plugin eval runs, so
the tests check each file, and they run each grader pattern with Python's `re` on sample text.
"""
import difflib
import fnmatch
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from report_fixtures import make_report, row, run_script
from skill_files import EVALS, SKILL, frontmatter, read
from test_eval_cases import SECTION_GRADERS, checkout_blocks, job_text, row_pattern

CASES = {
    # name: (reply, approved rule ids)
    "approve-1-3": ("1,3", ["SEC-03", "COST-04"]),
    "approve-2-4": ("2-4", ["SEC-05", "COST-04", "COST-07"]),
    "approve-all": ("all", ["SEC-03", "SEC-05", "COST-04", "COST-07", "COST-08"]),
    "approve-none": ("none", []),
}
ROWS = ["SEC-03", "SEC-05", "COST-04", "COST-07", "COST-08"]
EDITING = [name for name in CASES if name != "approve-none"]
FACTS = ("default_branch", "package_manager", "node_version_app", "engines", "package_kind", "os_claims",
         "test_runners", "monorepo", "visibility", "runner_labels", "required_checks", "run_history",
         "existing_workflows", "installed_tools", "supported_node_majors")
CLEAN = os.path.join(EVALS, "clean", "repo")
WORKFLOW = os.path.join(".github", "workflows", "ci.yml")


def case_path(name, *parts):
    return os.path.join(EVALS, name, *parts)


def select(reply, count):
    """The row numbers that a reply approves (the grammar of the review steps), for a report of `count` rows."""
    reply = reply.strip().lower()
    if reply == "all":
        return list(range(1, count + 1))
    if reply == "none":
        return []
    numbers = []
    for item in reply.replace(" ", "").split(","):
        low, _, high = item.partition("-")
        numbers += range(int(low), int(high or low) + 1)
    return sorted(set(numbers))


def expect_lists(name):
    return json.loads(read(case_path(name, "expect.json")))


def final_message(rows_after):
    """A final message of a fix run: the three sections, then a post-fix report with the given rows."""
    report = make_report(required=[row(rule) for rule in rows_after]).replace(
        "# ci-pipelines review: all workflows", "# ci-pipelines review: all workflows (after fixes)")
    return "\n".join(["## Applied", "", "- 1 SEC-03: added the permissions block", "",
                      "## Diff", "", "```diff", "--- a/ci.yml", "+++ b/ci.yml", "@@ -1,3 +1,5 @@", "+permissions:",
                      "```", "", report])


class Layout(unittest.TestCase):
    def test_the_four_cases_exist(self):
        for name in CASES:
            self.assertTrue(os.path.isdir(case_path(name)), name)

    def test_each_case_has_its_files(self):
        for name in CASES:
            for part in ("prompt.md", "case.yaml", "expect.json", "scaffold.sh", "repo", "graders", "history.jsonl"):
                self.assertTrue(os.path.exists(case_path(name, part)), f"{name} has no {part}")

    def test_case_yaml_names_the_case_the_scaffold_and_the_history(self):
        for name in CASES:
            text = read(case_path(name, "case.yaml"))
            self.assertRegex(text, rf"(?m)^name:\s*{re.escape(name)}\s*$")
            self.assertRegex(text, r"(?m)^\s*scaffold_script:\s*scaffold\.sh\s*$")
            self.assertRegex(text, r"(?m)^\s*history_file:\s*history\.jsonl\s*$")

    def test_the_prompt_frontmatter_allows_edit_and_30_turns(self):
        for name in CASES:
            meta = frontmatter(case_path(name, "prompt.md"))
            self.assertEqual(meta["max_turns"], "30", name)
            self.assertEqual(meta["allowed_tools"], "[Read, Glob, Grep, Skill, Bash, Edit]", name)

    def test_the_prompt_is_the_reply_and_the_recorded_intake_line(self):
        for name, (reply, _) in CASES.items():
            body = read(case_path(name, "prompt.md")).split("\n---\n", 1)[1].strip().splitlines()
            self.assertEqual(body[0], reply, name)
            self.assertEqual(len(body), 2, name)
            self.assertIn("`intake.json`", body[1])
            self.assertIn("do not run the intake script", body[1])

    def test_the_prompt_does_not_name_the_skill_or_a_rule(self):
        for name in CASES:
            prompt = read(case_path(name, "prompt.md")).lower()
            self.assertNotIn("ci-pipelines", prompt)
            self.assertIsNone(re.search(r"\b(name|graph|maint|cost|mono|sec)-\d\d", prompt), name)

    def test_the_repo_holds_the_fixture_files_and_no_git_folder(self):
        for name in CASES:
            repo = case_path(name, "repo")
            for part in (WORKFLOW, os.path.join(".github", "workflows", "security-audit.yml"),
                         os.path.join(".github", "dependabot.yml"), "package.json", "pnpm-lock.yaml", ".nvmrc",
                         "intake.json"):
                self.assertTrue(os.path.exists(os.path.join(repo, part)), f"{name} has no {part}")
            self.assertFalse(os.path.exists(os.path.join(repo, ".git")), name)

    def test_the_session_transcript_that_a_run_writes_is_ignored_by_git(self):
        ignore = os.path.join(os.path.dirname(case_path("approve-all")), ".gitignore")
        self.assertTrue(os.path.exists(ignore))
        transcript = "approve-1-3/00000000-0000-4000-8000-000000000001.jsonl"
        pattern = read(ignore).strip().splitlines()[0]
        self.assertTrue(fnmatch.fnmatch(transcript, pattern))
        self.assertFalse(fnmatch.fnmatch("approve-1-3/history.jsonl", pattern))

    def test_the_four_cases_share_one_fixture_and_one_history(self):
        for part in (WORKFLOW, "intake.json"):
            texts = {read(case_path(name, "repo", part)) for name in CASES}
            self.assertEqual(len(texts), 1, part)
        self.assertEqual(len({read(case_path(name, "history.jsonl")) for name in CASES}), 1)

    def test_no_fixture_file_holds_a_test_file_or_a_url_or_a_private_name(self):
        for name in CASES:
            for path in glob.glob(case_path(name, "repo", "**", "*"), recursive=True):
                if os.path.isfile(path):
                    self.assertFalse(os.path.basename(path).startswith("test_"), path)
                    self.assertNotRegex(read(path), r"https?://", path)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.text = read(case_path("approve-1-3", "repo", WORKFLOW))

    def test_the_other_files_are_the_clean_fixture(self):
        for part in (os.path.join(".github", "workflows", "security-audit.yml"),
                     os.path.join(".github", "dependabot.yml"), "package.json", "pnpm-lock.yaml", ".nvmrc"):
            self.assertEqual(read(case_path("approve-1-3", "repo", part)), read(os.path.join(CLEAN, part)), part)

    def test_sec_03_the_top_level_permissions_block_is_missing(self):
        self.assertIsNone(re.search(r"(?m)^permissions:", self.text))

    def test_sec_05_only_the_typecheck_checkout_keeps_its_credentials(self):
        blocks = {job: checkout_blocks(job_text(self.text, job)) for job in
                  ("changes", "lint", "typecheck", "test", "build", "audit")}
        self.assertNotIn("persist-credentials", blocks["typecheck"][0])
        for job, found in blocks.items():
            if job != "typecheck":
                self.assertIn("persist-credentials: false", found[0], job)

    def test_cost_04_only_the_lint_job_has_no_timeout(self):
        for job in ("changes", "lint", "typecheck", "test", "build", "audit", "ci-passed"):
            has = "timeout-minutes:" in job_text(self.text, job)
            self.assertEqual(has, job != "lint", job)

    def test_cost_07_only_the_build_job_runs_on_a_floating_label(self):
        for job in ("changes", "lint", "typecheck", "test", "build", "audit", "ci-passed"):
            label = re.search(r"runs-on:\s*(\S+)", job_text(self.text, job)).group(1)
            self.assertEqual(label, "ubuntu-latest" if job == "build" else "ubuntu-24.04", job)

    def test_cost_08_only_the_test_checkout_has_full_history(self):
        self.assertEqual(self.text.count("fetch-depth: 0"), 1)
        self.assertIn("fetch-depth: 0", checkout_blocks(job_text(self.text, "test"))[0])
        self.assertNotIn("fetch-depth", job_text(self.text, "changes"))

    def test_repairing_the_five_defects_gives_the_clean_workflow(self):
        fixed = self.text
        fixed = fixed.replace("jobs:\n", "permissions:\n  contents: read\njobs:\n", 1)
        typecheck = job_text(fixed, "typecheck")
        fixed = fixed.replace(typecheck, typecheck.replace(
            "      - uses: actions/checkout@0123456789abcdef0123456789abcdef01234567 # v4.2.2\n",
            "      - uses: actions/checkout@0123456789abcdef0123456789abcdef01234567 # v4.2.2\n"
            "        with:\n          persist-credentials: false\n", 1))
        lint = job_text(fixed, "lint")
        fixed = fixed.replace(lint, lint.replace("    runs-on: ubuntu-24.04\n",
                                                 "    runs-on: ubuntu-24.04\n    timeout-minutes: 10\n", 1))
        build = job_text(fixed, "build")
        fixed = fixed.replace(build, build.replace("ubuntu-latest", "ubuntu-24.04", 1))
        fixed = fixed.replace("          persist-credentials: false\n          fetch-depth: 0\n",
                              "          persist-credentials: false\n")
        clean = read(os.path.join(CLEAN, WORKFLOW))
        diff = "".join(difflib.unified_diff(clean.splitlines(True), fixed.splitlines(True)))
        self.assertEqual(diff, "")


class History(unittest.TestCase):
    def setUp(self):
        with open(case_path("approve-1-3", "history.jsonl"), encoding="utf-8") as handle:
            self.lines = [json.loads(line) for line in handle.read().splitlines()]

    def test_it_is_one_user_turn_and_one_assistant_turn(self):
        self.assertEqual([line["type"] for line in self.lines], ["user", "assistant"])
        self.assertEqual(self.lines[1]["parentUuid"], self.lines[0]["uuid"])
        self.assertEqual(self.lines[0]["message"]["role"], "user")
        self.assertEqual(self.lines[1]["message"]["role"], "assistant")
        self.assertEqual(self.lines[0]["message"]["content"], "Review our CI setup in this repo.")

    def report(self):
        (block,) = self.lines[1]["message"]["content"]
        self.assertEqual(block["type"], "text")
        return block["text"]

    def test_the_report_passes_the_report_structure_grader(self):
        code, out, _ = run_script("grade_report.py", ["-"], stdin=self.report())
        self.assertEqual((code, out.strip()), (0, "PASS"), out)

    def test_the_report_has_the_five_required_rows_in_order(self):
        rows = re.findall(r"(?m)^\|\s*(\d+)\s*\|\s*([A-Z]+-\d\d)\s*\|", self.report())
        self.assertEqual(rows, [(str(n), rule) for n, rule in enumerate(ROWS, start=1)])
        self.assertIn("**Result: 0 critical, 5 required, 0 suggestions.**", self.report())
        self.assertNotIn("⚑", self.report())

    def test_each_row_names_its_place_in_the_fixture(self):
        text = read(case_path("approve-1-3", "repo", WORKFLOW)).splitlines()
        places = {}
        for line in self.report().splitlines():
            found = re.match(r"^\|\s*\d+\s*\|\s*([A-Z]+-\d\d)\s*\|\s*([^|]+?)\s*\|", line)
            if found:
                places[found.group(1)] = re.findall(r"ci\.yml:(\d+)", found.group(2))
        self.assertEqual(sorted(places), sorted(ROWS))
        probe = {"SEC-03": "jobs:", "SEC-05": "uses: actions/checkout", "COST-04": "lint:",
                 "COST-07": "runs-on: ubuntu-latest", "COST-08": "fetch-depth: 0"}
        for rule, lines in places.items():
            self.assertTrue(lines, rule)
            self.assertTrue(any(probe[rule] in text[int(n) - 1] or probe[rule] in "\n".join(text[int(n) - 1:int(n) + 3])
                                for n in lines), f"{rule} {lines}")

    def test_the_tools_section_says_actionlint_is_on_path(self):
        self.assertRegex(self.report(), r"(?m)^- actionlint: on PATH \(\d+\.\d+\.\d+\)$")
        self.assertRegex(self.report(), r"(?m)^- zizmor: not on PATH\. Install it with")


class RecordedIntake(unittest.TestCase):
    def setUp(self):
        with open(case_path("approve-1-3", "repo", "intake.json"), encoding="utf-8") as handle:
            self.intake = json.load(handle)

    def test_it_holds_the_15_facts_with_their_three_keys(self):
        self.assertEqual(sorted(self.intake), sorted(FACTS))
        for name, fact in self.intake.items():
            self.assertEqual(sorted(fact), ["source", "status", "value"], name)

    def test_actionlint_is_on_path_and_the_other_tools_are_not(self):
        tools = self.intake["installed_tools"]["value"]
        self.assertTrue(tools["actionlint"]["installed"])
        self.assertRegex(tools["actionlint"]["version"], r"^\d+\.\d+\.\d+$")
        self.assertFalse(tools["zizmor"]["installed"])
        self.assertFalse(tools["pinact"]["installed"])

    def test_the_required_checks_and_the_run_history_are_unknown(self):
        self.assertEqual(self.intake["required_checks"]["status"], "unknown")
        self.assertEqual(self.intake["run_history"]["status"], "unknown")

    def test_the_offline_node_list_names_tools_md(self):
        self.assertIn("tools.md", self.intake["supported_node_majors"]["source"])

    def test_the_other_facts_are_what_the_intake_script_finds_in_the_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            shutil.copytree(case_path("approve-1-3", "repo"), repo)
            env = dict(os.environ, CI_PIPELINES_OFFLINE="1")
            proc = subprocess.run(["python3", "-I", os.path.join(SKILL, "scripts", "intake.py"), repo],
                                  capture_output=True, text=True, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
        found = json.loads(proc.stdout)
        for name in FACTS:
            if name != "installed_tools":
                self.assertEqual(found[name], self.intake[name], name)


class Scaffold(unittest.TestCase):
    def test_the_scaffold_copies_the_repo_and_makes_a_git_repo_with_one_commit(self):
        for name in CASES:
            with tempfile.TemporaryDirectory() as tmp:
                env = dict(os.environ, HOME=tmp, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
                proc = subprocess.run(["bash", case_path(name, "scaffold.sh")], cwd=tmp, env=env,
                                      capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertTrue(os.path.isfile(os.path.join(tmp, WORKFLOW)))
                self.assertTrue(os.path.isfile(os.path.join(tmp, "intake.json")))
                log = subprocess.run(["git", "log", "--oneline"], cwd=tmp, env=env, capture_output=True, text=True)
                self.assertEqual(len(log.stdout.strip().splitlines()), 1, name)
                status = subprocess.run(["git", "status", "--porcelain"], cwd=tmp, env=env,
                                        capture_output=True, text=True)
                self.assertEqual(status.stdout.strip(), "", name)


class ExpectAndGraders(unittest.TestCase):
    def test_expect_and_forbid_follow_the_reply_and_the_report_rows(self):
        for name, (reply, approved) in CASES.items():
            numbers = select(reply, len(ROWS))
            self.assertEqual([ROWS[n - 1] for n in numbers], approved, name)
            lists = expect_lists(name)
            if name == "approve-none":
                self.assertEqual(lists, {"expect": [], "forbid": []})
            else:
                self.assertEqual(lists["forbid"], approved, name)
                self.assertEqual(lists["expect"], [rule for rule in ROWS if rule not in approved], name)

    def test_the_grader_files_of_each_case(self):
        base = {"gh-api-no-write.md"}
        for name in CASES:
            lists = expect_lists(name)
            found = {os.path.basename(p) for p in glob.glob(case_path(name, "graders", "*.md"))}
            if name == "approve-none":
                wanted = base | {"no-edit.md", "no-write.md", "no-shell-write.md", "no-actionlint.md"}
            else:
                wanted = (base | {f"expect-{r}.md" for r in lists["expect"]} | {f"forbid-{r}.md" for r in lists["forbid"]}
                          | {f"{s}.md" for s in SECTION_GRADERS}
                          | {"actionlint-ran.md", "actionlint-after-edit.md", "diff-in-message.md",
                             "fix-quality.md", "diff-scope.md"})
            self.assertEqual(found, wanted, name)

    def test_the_expect_and_forbid_graders_match_the_rule_cell_only(self):
        for name in EDITING:
            lists = expect_lists(name)
            for rule in lists["expect"]:
                meta = frontmatter(case_path(name, "graders", f"expect-{rule}.md"))
                self.assertEqual((meta["type"], meta["pattern"], meta["flags"]), ("regex", row_pattern(rule), "m"))
            for rule in lists["forbid"]:
                meta = frontmatter(case_path(name, "graders", f"forbid-{rule}.md"))
                self.assertEqual((meta["type"], meta["pattern"], meta["flags"], meta["match"]),
                                 ("regex", row_pattern(rule), "m", "not_contains"))

    def test_the_section_graders_are_regex_graders(self):
        for name in EDITING:
            for section in SECTION_GRADERS:
                meta = frontmatter(case_path(name, "graders", f"{section}.md"))
                self.assertEqual((meta["type"], meta["flags"]), ("regex", "m"))

    def test_the_actionlint_graders(self):
        for name in EDITING:
            ran = frontmatter(case_path(name, "graders", "actionlint-ran.md"))
            self.assertEqual((ran["type"], ran["tool"], ran["input_match"], ran["min"]),
                             ("tool_used", "Bash", "actionlint", "1"))
            order = frontmatter(case_path(name, "graders", "actionlint-after-edit.md"))
            self.assertEqual((order["type"], order["before"], order["after"]),
                             ("tool_order", "Edit", "{ tool: Bash, input_match: actionlint }"))
        none = frontmatter(case_path("approve-none", "graders", "no-actionlint.md"))
        self.assertEqual((none["type"], none["tool"], none["input_match"], none["min"], none["max"]),
                         ("tool_used", "Bash", "actionlint", "0", "0"))

    def test_the_none_case_has_the_three_no_edit_graders(self):
        for file, tool in {"no-edit.md": "Edit", "no-write.md": "Write", "no-shell-write.md": "Bash"}.items():
            meta = frontmatter(case_path("approve-none", "graders", file))
            self.assertEqual((meta["type"], meta["tool"], meta["min"], meta["max"]), ("tool_used", tool, "0", "0"))
            self.assertTrue(meta["input_match"])

    def test_the_judges_are_reported_and_not_scored(self):
        for name in EDITING:
            for file in ("fix-quality.md", "diff-scope.md"):
                meta = frontmatter(case_path(name, "graders", file))
                self.assertEqual((meta["type"], meta["arm"]), ("llm", "with-only"))
                self.assertNotIn("weight", meta)

    def test_the_diff_grader_finds_a_fenced_diff_with_a_hunk_header(self):
        meta = frontmatter(case_path("approve-1-3", "graders", "diff-in-message.md"))
        self.assertEqual((meta["type"], meta["flags"]), ("regex", "m"))
        pattern = re.compile(meta["pattern"], re.M)
        self.assertTrue(pattern.search(final_message(["SEC-05"])))
        self.assertFalse(pattern.search("```diff\nno hunk here\n```"))
        self.assertFalse(pattern.search("@@ -1 +1 @@\n a diff with no fence"))

    def test_the_gh_api_grader_file_is_the_same_in_the_four_cases(self):
        self.assertEqual(len({read(case_path(n, "graders", "gh-api-no-write.md")) for n in CASES}), 1)

    def test_the_gh_api_grader_matches_a_write_and_not_a_read(self):
        meta = frontmatter(case_path("approve-1-3", "graders", "gh-api-no-write.md"))
        self.assertEqual((meta["type"], meta["tool"], meta["min"], meta["max"]), ("tool_used", "Bash", "0", "0"))
        self.assertNotIn("flags", meta)  # the tool_used grader has no flags option: the pattern is case-blind by hand
        pattern = re.compile(meta["input_match"])

        def encoded(command):
            return json.dumps({"command": command, "description": "run it"})

        for command in (
            "gh api -X PUT repos/o/r/branches/main/protection",
            "gh api repos/o/r/branches/main/protection -XPUT",
            "gh api --method POST repos/o/r/rulesets",
            "gh api --method=PATCH repos/o/r/rulesets/5",
            "gh api repos/o/r/branches/main/protection -f required_status_checks=x",
            "gh api repos/o/r/rulesets -F name=ci",
            "gh api repos/o/r/rulesets --field name=ci",
            "gh api repos/o/r/rulesets --raw-field name=ci",
            "gh api repos/o/r/branches/main/protection --input body.json",
            "gh api -X delete repos/o/r/rulesets/5",
        ):
            self.assertTrue(pattern.search(encoded(command)), command)
        for command in (
            "gh api repos/o/r/branches/main/protection",
            "gh api -X GET repos/o/r/branches/main/protection",
            "gh api -X get repos/o/r/rulesets",
            "gh api --method GET repos/o/r/rulesets",
            "gh api repos/o/r/rules/branches/main",
            "gh api -X PATCH repos/o/r/issues/1",
            "gh api repos/o/r/issues -f title=x",
            "git diff -- .github/workflows/ci.yml",
            "actionlint -format '{{json .}}'",
        ):
            self.assertFalse(pattern.search(encoded(command)), command)

    def test_the_patterns_use_only_syntax_that_javascript_and_python_share(self):
        for path in glob.glob(case_path("approve-*", "graders", "*.md")):
            meta = frontmatter(path)
            for key in ("pattern", "input_match"):
                if key in meta:
                    self.assertNotRegex(meta[key], r"\(\?[PiscxmU]|\\A|\\Z|\(\?<[a-z]", path)


class GradeEvalResultsOnApprovalCases(unittest.TestCase):
    """grade_eval_results.py grades the editing cases from their expect.json and skips the none case."""

    def grade(self, case, message):
        with tempfile.TemporaryDirectory() as tmp:
            trace = os.path.join(tmp, "trace.jsonl")
            with open(trace, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"type": "result", "result": message}) + "\n")
            names = [os.path.basename(p)[:-3] for p in glob.glob(case_path(case, "graders", "*.md"))]
            result = {"schemaVersion": 1, "cases": [{"name": case, "graders": [{"name": n} for n in names],
                                                      "arms": {"with": [{"tracePath": trace}]}}]}
            path = os.path.join(tmp, "result.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(result, handle)
            return run_script("grade_eval_results.py", [path])

    def test_a_post_fix_report_with_the_unapproved_rows_only_passes(self):
        code, out, _ = self.grade("approve-1-3", final_message(["SEC-05", "COST-07", "COST-08"]))
        self.assertEqual((code, out.strip().splitlines()[-1]), (0, "PASS"), out)

    def test_a_post_fix_report_that_still_has_an_approved_row_or_lacks_an_unapproved_one_fails(self):
        code, out, _ = self.grade("approve-1-3", final_message(["SEC-03", "SEC-05", "COST-07", "COST-08"]))
        self.assertEqual(code, 1)
        self.assertIn("forbid:SEC-03", out)
        code, out, _ = self.grade("approve-1-3", final_message(["SEC-05", "COST-07"]))
        self.assertEqual(code, 1)
        self.assertIn("expect:COST-08", out)

    def test_the_all_case_passes_with_no_finding_left(self):
        code, out, _ = self.grade("approve-all", final_message([]))
        self.assertEqual((code, out.strip().splitlines()[-1]), (0, "PASS"), out)

    def test_the_none_case_has_no_report_grader_and_nothing_to_grade(self):
        code, _, err = self.grade("approve-none", "No fix was applied.")
        self.assertEqual(code, 2)
        self.assertIn("nothing to grade", err)


class FixMessageAndTheReportGrader(unittest.TestCase):
    """The unchanged report-structure grader accepts the final message of a fix run."""

    def test_sections_before_the_title_and_an_after_fixes_title_pass(self):
        code, out, _ = run_script("grade_report.py", ["-"], stdin=final_message(["SEC-05"]))
        self.assertEqual((code, out.strip()), (0, "PASS"), out)

    def test_the_same_message_with_no_finding_left_passes(self):
        code, out, _ = run_script("grade_report.py", ["-"], stdin=final_message([]))
        self.assertEqual((code, out.strip()), (0, "PASS"), out)

    def test_the_admin_section_does_not_count_as_the_flag_section(self):
        message = final_message(["SEC-05"]).replace(
            "## Diff", "## Branch protection steps for the admin\n\n- Remove `Old`, add `New`.\n\n## Diff")
        code, out, _ = run_script("grade_report.py", ["-"], stdin=message)
        self.assertEqual((code, out.strip()), (0, "PASS"), out)


if __name__ == "__main__":
    unittest.main()
