# Text tests of tickets #100, #164 and #166: the rules in CLAUDE.md (sections 6, 7, 8, 10, 11, 13 and 14) and the test-command declaration of this repo.
import os
import re
import shutil
import unittest

from audit_support import HERE, AuditCase

REPO = os.path.dirname(os.path.dirname(HERE))
ROOT_CLAUDE_MD = os.path.join(REPO, "CLAUDE.md")
PROJECT_CLAUDE_MD = os.path.join(REPO, ".claude", "CLAUDE.md")
DOCKER_MD = os.path.join(REPO, "docs", "agents", "docker.md")
DECLARATION_ERRORS = ("expected exactly one '### Test command' section",
                      "the '### Test command' section needs exactly one non-empty fenced block")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def section(text, number):
    """The text of `## <number>. <title>`, up to the next `## ` heading."""
    match = re.search(r"^## %d\. .*?(?=^## |\Z)" % number, text, re.DOTALL | re.MULTILINE)
    assert match, f"CLAUDE.md has no section {number}"
    return match.group(0)


def declared_commands(text):
    """The fenced blocks of the `### Test command` sections of a CLAUDE.md."""
    blocks = []
    for body in re.findall(r"^### Test command\n(.*?)(?=^#{1,3} |\Z)", text, re.DOTALL | re.MULTILINE):
        blocks.append(re.findall(r"^```[^\n]*\n(.*?)^```", body, re.DOTALL | re.MULTILINE))
    return blocks


class RuleTextCase(unittest.TestCase):
    def assert_in(self, text, *phrases):
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def assert_not_in(self, text, *phrases):
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, text)


class SectionSixTest(RuleTextCase):
    def setUp(self):
        self.text = section(read(ROOT_CLAUDE_MD), 6)

    def test_the_ledger_is_written_through_audit_ledger_with_six_event_kinds(self):
        self.assert_in(self.text, "~/.claude/hooks/workflow-audit/audit ledger <event> --worktree <path>", "`audit ledger`",
                       "- `round`:", "- `finding`:", "- `verdict`:", "- `status`:", "- `extension`:", "- `phase-commit`:")

    def test_the_round_bullet_says_reviewer_ids_are_subagents_of_the_loop_session_and_a_round_is_written_after_its_reviewers_ran(self):
        bullet = re.search(r"^- `round`:.*$", self.text, re.MULTILINE).group(0)
        self.assert_in(bullet, "reviewer agent ids", "is a subagent of the loop session", "`audit ledger` refuses another id",
                       "(exit 2, nothing written)", "write the `round` event only after its reviewers ran")

    def test_the_extension_bullet_follows_the_phase_commit_bullet(self):
        self.assertGreater(self.text.index("- `extension`:"), self.text.index("- `phase-commit`:"))

    def test_the_session_that_got_the_approval_writes_the_extension_with_an_absolute_worktree_path(self):
        self.assert_in(self.text, "At a cap, the session that asked the user and got the approval writes the `extension` event "
                       "(for a worker, the coordinator), with `--worktree` as an absolute path (never `~` or `$HOME`) "
                       "and the owner's own words as the quote.")

    def test_the_audit_step_sits_between_the_report_and_the_caps(self):
        steps = re.findall(r"^(\d)\. (?:\*\*([^*]+)\.\*\*)?", self.text, re.MULTILINE)
        self.assertEqual([number for number, _ in steps], list("1234567"))
        self.assertEqual({number: name for number, name in steps if name}, {
            "1": "Correctness phase", "2": "Quality phase (once)", "3": "Final phase", "4": "Report", "5": "Audit"})

    def test_the_audit_step_names_the_brief_the_push_the_pr_and_the_fail_rule(self):
        self.assert_in(self.text, "Before you tell the user that the task is done", "write the draft done report to your scratchpad",
                       "Push the branch", "~/.claude/hooks/workflow-audit/auditor-brief.md",
                       "Give it the worktree path, the path of the draft done report, the path of the verdict file and the PR target "
                       "(the base branch of the PR).",
                       "`audit check`", "`audit record`", "open the PR with `gh pr create`",
                       "On a fail, report each failed item with its evidence and ask the user", "Do not fix the failed items yourself",
                       "`! gh pr create`", "the coordinator audits it")


class SectionSevenTest(RuleTextCase):
    def setUp(self):
        self.text = section(read(ROOT_CLAUDE_MD), 7)

    def test_the_worker_pushes_and_reports_the_branch_and_the_worktree(self):
        self.assert_in(self.text, "5.6. Push the branch.", "the branch name and the worktree path in the `worker_done` report",
                       "Do not open the PR")

    def test_the_coordinator_audits_on_worker_done_and_opens_the_pr_after_a_pass(self):
        self.assert_in(self.text, "When a `worker_done` arrives, the coordinator audits the ticket as in section 6 step 5",
                       "This replaces the manual evidence check", "After a pass, the coordinator opens the PR with `gh pr create`")

    def test_the_main_session_runs_the_pre_dispatch_audit_before_the_first_dispatch(self):
        self.assert_in(self.text, "Before the first dispatch, the main section 7 session runs the pre-dispatch audit",
                       "`audit record --pre-dispatch --worktree <path> --map <issue> --llm <file>`",
                       "It gives it the PR target (the base branch of the PR) with the worktree path and the map issue.",
                       "This replaces the manual step 4.1 evidence check", "A hook blocks `orchestration worker-start` until this audit passes",
                       "a plain `worker-start --retry-of` for a worker handover is exempt",
                       "A context-handoff successor of the main session runs the audit again before its next dispatch")

    def test_the_plan_review_loops_use_their_loop_names_in_the_ledger(self):
        self.assert_in(self.text, "`plan-review-3`, `plan-review-4.1` or `plan-review-5.3`")

    def test_the_manual_evidence_checks_are_gone(self):
        self.assert_not_in(self.text, "checks evidence for each step", "checks the following evidence for the step 4.1 review",
                           "A worker's claim without evidence counts as not done")

    def test_the_worker_channel_to_the_user_is_unchanged(self):
        self.assert_in(self.text, "A worker has no direct channel to the user.")


class SectionsEightAndElevenTest(RuleTextCase):
    def test_every_task_in_a_git_repo_ends_with_a_pr(self):
        self.assert_in(section(read(ROOT_CLAUDE_MD), 8), "Every task in a git repo ends with a PR, opened with `gh pr create` after a passing audit",
                       "A hook blocks `gh pr create` until a passing audit record exists for the pushed commit",
                       "Only the user may override a failed audit, by running `! gh pr create` themselves")

    def test_the_pr_rule_is_the_first_line_of_section_eight(self):
        lines = section(read(ROOT_CLAUDE_MD), 8).splitlines()
        first = next(line for line in lines[1:] if line.strip())
        self.assertTrue(first.startswith("Every task in a git repo ends with a PR"), first)

    def test_the_auditor_subagent_is_an_allowed_agent_use(self):
        self.assert_in(section(read(ROOT_CLAUDE_MD), 11), "- The auditor subagent: section 6 step 5 and section 7.")


class WorktreeCleanupRuleTest(RuleTextCase):
    """Ticket #166: sections 8, 10 and 13 name the cleanup command as the only cleanup path."""

    COMMAND = "~/.claude/hooks/worktree-cleanup/cleanup"
    FINISH_FIRST = "finish the report and the memory update first"

    def test_sections_eight_ten_and_thirteen_name_the_command(self):
        for number in (8, 10, 13):
            with self.subTest(section=number):
                self.assertIn(self.COMMAND, section(read(ROOT_CLAUDE_MD), number))

    def test_section_eight_makes_the_command_the_only_path_and_states_the_refusal_rule(self):
        text = section(read(ROOT_CLAUDE_MD), 8)
        self.assert_in(text, "is the only cleanup path", "On a refusal, fix the cause or ask the user")
        self.assert_not_in(text, "delete the remote branch, remove the worktree (section 10)")

    def test_section_eight_says_to_finish_the_report_and_memory_update_after_the_command_in_its_paragraph(self):
        paragraph = next(part for part in section(read(ROOT_CLAUDE_MD), 8).split("\n\n") if self.COMMAND in part)
        self.assertIn(self.FINISH_FIRST, paragraph)
        self.assertGreater(paragraph.index(self.FINISH_FIRST), paragraph.index(self.COMMAND))

    def test_section_thirteen_names_the_command_as_the_only_exception_and_keeps_the_user_overrides_out(self):
        self.assert_in(section(read(ROOT_CLAUDE_MD), 13), "the only exception",
                       "the user's `!` overrides are user actions, not session exceptions")


class DockerCleanupRuleTest(RuleTextCase):
    """Ticket #164: section 14 and docs/agents/docker.md say that the cleanup command refuses on a stack in the target worktree."""

    COMMAND = "~/.claude/hooks/worktree-cleanup/cleanup"

    def test_section_fourteen_states_the_refusal_and_the_removal_by_hand(self):
        self.assert_in(section(read(ROOT_CLAUDE_MD), 14), self.COMMAND, "refuses", "by hand")

    def test_docker_md_states_the_refusal_the_removal_by_hand_and_ask_first(self):
        self.assert_in(read(DOCKER_MD), self.COMMAND, "refuses", "by hand", "ask first")


class TestCommandDeclarationTest(unittest.TestCase):
    def test_only_the_project_claude_md_holds_one_declaration_with_one_block(self):
        self.assertEqual(declared_commands(read(ROOT_CLAUDE_MD)), [])
        blocks = declared_commands(read(PROJECT_CLAUDE_MD))
        self.assertEqual(len(blocks), 1)
        self.assertEqual(len(blocks[0]), 1)

    def command(self):
        return declared_commands(read(PROJECT_CLAUDE_MD))[0][0].strip()

    def test_one_sentence_comes_before_the_fence(self):
        body = re.search(r"^### Test command\n(.*?)^```", read(PROJECT_CLAUDE_MD), re.DOTALL | re.MULTILINE).group(1).strip()
        self.assertEqual(len(re.findall(r"[.!?](?:\s|$)", body)), 1, body)

    def test_the_command_is_one_unittest_run_in_one_process(self):
        command = self.command()
        self.assertEqual(command.count("\n"), 0)
        self.assertTrue(command.startswith("python3 -c "))
        self.assertEqual(command.count("unittest.TextTestRunner()"), 1)
        self.assertNotIn("|", command.replace("||", ""))  # no pipe: a piped run does not count

    def test_the_command_covers_every_folder_that_holds_a_test_file(self):
        folders = set()
        for top in ("hooks", "skills"):
            for folder, _, names in os.walk(os.path.join(REPO, top)):
                if any(re.fullmatch(r"test_.*\.py", name) for name in names):
                    folders.add(os.path.relpath(folder, REPO))
        self.assertTrue(folders)
        listed = set(re.findall(r"'([^']+)'", self.command()))
        self.assertEqual(listed, folders)


class AuditReadsTheDeclarationTest(AuditCase):
    """`audit check` reads this repo's declaration without a declaration error."""

    def declaration_errors(self, remove_root_declaration):
        self.start_branch("feature", "feat(audit): add a thing")
        if remove_root_declaration:
            self.git("rm", "-q", "CLAUDE.md")
        os.mkdir(os.path.join(self.repo, ".claude"))
        shutil.copy(PROJECT_CLAUDE_MD, os.path.join(self.repo, ".claude", "CLAUDE.md"))
        self.git("add", ".claude/CLAUDE.md")
        self.git("commit", "-q", "-m", "docs: declare the test command")
        self.git("push", "-q", "origin", "feature")
        checked = self.audit("check", "--worktree", self.repo, "--base", "main")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        lines = checked.stdout.decode().splitlines()
        start = next(index for index, line in enumerate(lines) if line.startswith("S2 "))
        evidence = []
        for line in lines[start + 1:]:
            if not line.startswith("  "):
                break
            evidence.append(line.strip())
        return [line for line in evidence if line.startswith(DECLARATION_ERRORS)]

    def test_this_repos_declaration_is_accepted(self):
        self.assertEqual(self.declaration_errors(remove_root_declaration=True), [])

    def test_the_check_would_notice_a_second_declaration(self):
        self.assertEqual(len(self.declaration_errors(remove_root_declaration=False)), 1)


if __name__ == "__main__":
    unittest.main()
