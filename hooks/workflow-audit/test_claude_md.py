# Text tests of tickets #100, #164, #166, #489 and #494: the rules in CLAUDE.md (sections 6, 7, 8, 10, 11, 13 and 14) and the test-command declaration of this repo.
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

    def test_the_ledger_is_written_through_audit_ledger_with_seven_event_kinds(self):
        self.assert_in(self.text, "~/.claude/hooks/workflow-audit/audit ledger <event> --worktree <path>", "`audit ledger`",
                       "- `round`:", "- `finding`:", "- `finding-amend`:", "- `verdict`:", "- `status`:", "- `extension`:",
                       "- `phase-commit`:")

    def test_the_finding_amend_bullet_names_the_repair_the_quote_rule_and_the_unchanged_fields(self):
        bullet = re.search(r"^- `finding-amend`:.*$", self.text, re.MULTILINE).group(0)
        self.assert_in(bullet, "`--id`", "`--reason`", "`--quote`", "`--raised`", "repairs the reason of an existing finding",
                       "the same quote rule as `finding`", "The latest amendment is in force",
                       "type, loop, phase, round, location and status never change")
        self.assertGreater(self.text.index("- `finding-amend`:"), self.text.index("- `finding`:"))
        self.assertLess(self.text.index("- `finding-amend`:"), self.text.index("- `verdict`:"))

    def test_the_round_bullet_says_reviewer_ids_are_subagents_of_the_loop_session_and_a_round_is_written_after_its_reviewers_ran(self):
        bullet = re.search(r"^- `round`:.*$", self.text, re.MULTILINE).group(0)
        self.assert_in(bullet, "reviewer agent ids", "is a subagent of the loop session", "`audit ledger` refuses another id",
                       "(exit 2, nothing written)", "write the `round` event only after its reviewers ran")

    def test_the_finding_bullet_names_quote_and_raised(self):
        bullet = re.search(r"^- `finding`:.*$", self.text, re.MULTILINE).group(0)
        self.assert_in(bullet, "`--quote`", "`--raised`", "A Blocking finding of a plan-review loop needs `--quote`")

    def test_the_extension_bullet_follows_the_phase_commit_bullet(self):
        self.assertGreater(self.text.index("- `extension`:"), self.text.index("- `phase-commit`:"))

    def test_the_session_that_got_the_approval_writes_the_extension_with_an_absolute_worktree_path(self):
        self.assert_in(self.text, "At a cap, the session that asked the user and got the approval writes the `extension` event "
                       "(for a worker, the coordinator), with `--worktree` as an absolute path (never `~` or `$HOME`) "
                       "and the owner's own words as the quote.")

    def test_the_final_phase_step_has_the_rebase_rule(self):
        step = re.search(r"^3\. \*\*Final phase\.\*\*.*$", self.text, re.MULTILINE).group(0)
        self.assert_in(step, "If the base branch moves after the quality-phase commit, rebase, record the rebased commit with a new "
                       "`phase-commit` event, and run one more final round when its patch-id differs.")

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

    def test_the_plan_review_loop_names_quote_and_raised(self):
        self.assert_in(self.text, "`--quote` (required for a plan-review Blocking finding)", "`--raised`")

    def test_the_plan_review_loop_names_finding_amend_as_the_repair_of_a_missing_quote(self):
        self.assert_in(self.text, "repairs a finding whose reason lacks its quote with `finding-amend`")

    def test_the_manual_evidence_checks_are_gone(self):
        self.assert_not_in(self.text, "checks evidence for each step", "checks the following evidence for the step 4.1 review",
                           "A worker's claim without evidence counts as not done")

    def test_the_worker_channel_to_the_user_is_unchanged(self):
        self.assert_in(self.text, "A worker has no direct channel to the user.")

    def test_a_worker_never_ends_its_turn_while_an_ask_a_test_run_or_a_ci_watch_is_open(self):
        self.assert_in(self.text, "A worker never ends its turn while an `ask`, a background test run or a CI watch is open.",
                       "It waits on them in the foreground (a blocking wait with no short timeout)",
                       "or it keeps working on parts that they do not touch")

    def test_the_coordinator_confirms_a_new_turn_after_every_reply_and_wakes_the_worker_if_not(self):
        self.assert_in(self.text, "After every `reply` to a worker, the coordinator reads the worker's terminal and confirms that a new turn started.",
                       "If not, it sends the answer or a wake prompt to the terminal", "and checks again")


class SectionsEightAndElevenTest(RuleTextCase):
    def test_every_task_in_a_git_repo_ends_with_a_pr(self):
        self.assert_in(section(read(ROOT_CLAUDE_MD), 8), "Every task in a git repo ends with a PR, opened with `gh pr create` after a passing audit",
                       "A hook blocks `gh pr create` until a passing audit record exists for the pushed commit",
                       "Only the user may override a failed audit, by running `! gh pr create` themselves")

    def test_section_eleven_names_the_open_ask_rule_for_workers(self):
        self.assert_in(section(read(ROOT_CLAUDE_MD), 11),
                       "- A worker never ends its turn while an `ask`, a background test run or a CI watch is open (section 7).")

    def test_the_pr_rule_is_the_first_line_of_section_eight(self):
        lines = section(read(ROOT_CLAUDE_MD), 8).splitlines()
        first = next(line for line in lines[1:] if line.strip())
        self.assertTrue(first.startswith("Every task in a git repo ends with a PR"), first)

    def test_the_auditor_subagent_is_an_allowed_agent_use(self):
        self.assert_in(section(read(ROOT_CLAUDE_MD), 11), "- The auditor subagent: section 6 step 5 and section 7.")


class FreshCiRuleTest(RuleTextCase):
    """Ticket #494: the section 8 fresh-CI rule, in the order that the session meets its steps."""

    def setUp(self):
        text = section(read(ROOT_CLAUDE_MD), 8)
        start = text.index("Before you give the owner the merge command")
        self.rule = text[start:text.index("After merging, run", start)]

    def test_the_rule_still_skips_a_pr_without_ci_checks(self):
        self.assert_in(self.rule, "Skip this check when the PR has no CI checks.")

    def test_the_check_is_an_ancestry_check_not_a_time_comparison(self):
        self.assert_in(self.rule, "3. Find the head that the last CI run of the PR tested. If the base tip is an ancestor of that head "
                                  "(`git merge-base --is-ancestor <base tip> <tested head>`), go to step 6.")
        self.assert_not_in(self.rule, "Compare the time")

    def test_the_base_is_fetched_before_the_check_and_the_git_merge_uses_the_fetched_base(self):
        self.assert_in(self.rule, "`git merge` of the fetched base and a push")

    def test_the_pr_head_is_fetched_with_the_base_before_the_check(self):
        self.assert_in(self.rule, "1. Fetch the base branch and the PR head: `git fetch origin <base> pull/<n>/head`.")

    def test_a_tested_head_missing_after_the_fetch_counts_as_stale(self):
        self.assert_in(self.rule, "If the tested head is not in the local clone after step 1 (for example after a force push), "
                                  "the CI result is stale: go to step 4.")

    def test_the_worktree_is_fast_forwarded_after_the_rest_update(self):
        self.assert_in(self.rule, "After the REST call, run `git pull --ff-only` in your worktree, so that it holds the new PR head.")
        steps = [line for line in self.rule.splitlines() if re.match(r"\d\. ", line)]
        self.assertIn("git pull --ff-only", steps[3])

    def test_a_pr_with_no_run_goes_to_the_wait_step(self):
        self.assert_in(self.rule, "2. If no run exists for the PR, go to step 6.")

    def test_a_merge_conflict_means_report_and_ask(self):
        self.assert_in(self.rule, "5. On a merge conflict, give no merge command: report the conflicting files to the owner and ask how to go on. "
                                  "Do not resolve them on your own.")

    def test_a_running_or_missing_run_means_a_blocking_watch_then_tell_the_owner(self):
        self.assert_in(self.rule, "with a blocking `gh pr checks --watch`, not a poll loop. "
                                  "If no run appears for the head within about 10 minutes, tell the owner and stop.")

    def test_a_red_run_means_report_with_the_link_and_ask(self):
        self.assert_in(self.rule, "7. If the run fails, give no merge command: report the failing check with its link to the owner and ask how to go on. "
                                  "Do not fix it on your own.")

    def test_the_updated_head_is_audited_again_before_the_merge_command(self):
        self.assert_in(self.rule, "8. If you merged the base in step 4, run the section 6 step 5 audit again on the new head.",
                       "9. Give the merge command only after the run is green and, when step 8 applied, the audit passed.")

    def test_the_steps_come_in_the_order_the_session_meets_them(self):
        marks = ["1. Fetch", "2. If no run exists", "3. Find the head", "4. Otherwise merge", "5. On a merge conflict", "6. Wait for the CI run",
                 "7. If the run fails", "8. If you merged", "9. Give the merge command"]
        positions = [self.rule.index(mark) for mark in marks]
        self.assertEqual(positions, sorted(positions))

    def test_the_merge_options_and_the_conflict_rule_sit_on_separate_lines(self):
        steps = [line for line in self.rule.splitlines() if re.match(r"\d\. ", line)]
        self.assertEqual(len(steps), 9)
        self.assertIn("update-branch", steps[3])
        self.assertNotIn("conflict", steps[3])
        self.assertNotIn("update-branch", steps[4])

    def test_rebase_stays_banned_without_restating_the_general_force_push_ban(self):
        self.assert_in(self.rule, "Never rebase a PR branch for this: a rebase rewrites audited commits and needs a force-push.")
        self.assert_not_in(self.rule, "Never rebase and force-push")


class ContextStopRuleTest(RuleTextCase):
    """Ticket #489: section 11 bans context as a reason to stop. One test per required line."""

    def setUp(self):
        self.text = section(read(ROOT_CLAUDE_MD), 11)

    def test_the_narrow_ban(self):
        self.assert_in(self.text, "Context size is never a reason to stop, to end a session, or to suggest a fresh session.")

    def test_only_the_context_handoff_hook_ends_a_session_for_context(self):
        self.assert_in(self.text, "Only the context-handoff hook ends a session for context. "
                                  "Main sessions (plain and coordinator) and Orca workers keep working until it blocks them.")

    def test_one_session_may_resolve_several_wayfinder_tickets_in_a_row(self):
        self.assert_in(self.text, "One session may resolve several `/mattpocock-skills:wayfinder` tickets in a row.")

    def test_charting_a_map_does_not_end_the_session(self):
        self.assert_in(self.text, "Charting a map does not end the session. The same session may go on to work the frontier.")

    def test_the_wayfinder_one_ticket_sentence_is_cancelled_with_its_research_exception(self):
        self.assert_in(self.text, "the `/mattpocock-skills:wayfinder` sentence \"never resolve more than one ticket per session\" "
                                  "(the whole sentence, with its research-ticket exception)")

    def test_the_wayfinder_charting_stop_is_cancelled(self):
        self.assert_in(self.text, "the `/mattpocock-skills:wayfinder` charting step "
                                  "\"Stop — charting is one session's work; it hand-resolves nothing\"")

    def test_the_ask_matt_fresh_thread_advice_is_cancelled(self):
        self.assert_in(self.text, "the `/mattpocock-skills:ask-matt` advice to `/handoff` and continue in a fresh thread")

    def test_a_general_clause_cancels_any_other_skill_text(self):
        self.assert_in(self.text, "any other skill text that says to stop, end a session or start a fresh session for context reasons")

    def test_to_tickets_sizing_stays_as_sizing(self):
        self.assert_in(self.text, "`/mattpocock-skills:to-tickets` sizes each slice for one fresh context window. "
                                  "That is ticket sizing, not a reason to stop.")

    def test_every_stop_that_is_not_about_context_keeps_working(self):
        self.assert_in(self.text, "Every stop that is not about context keeps working: caps, questions for the owner, a failed audit, "
                                  "confirmation before a destructive action, and any stop defined for a reason other than context.")

    def test_every_subagent_prompt_says_not_to_stop_for_context_and_to_finish_the_task(self):
        self.assert_in(self.text, "Say in the prompt of every subagent that it must not stop or suggest a fresh session for context, "
                                  "and that it must finish the task.")

    def test_the_subagent_prompt_line_sits_in_the_bullet_after_the_read_only_line(self):
        lines = self.text.splitlines()
        read_only = next(i for i, line in enumerate(lines) if "Say \"read-only\" in the prompt" in line)
        self.assertIn("must not stop or suggest a fresh session for context", lines[read_only + 1])

    def test_briefs_stay_sized_for_one_subagent(self):
        self.assert_in(self.text, "Size each brief for one subagent: one review axis, one finding to verify, or one audit.")

    def test_headless_sessions_are_covered_with_auto_compact_as_the_backstop(self):
        self.assert_in(self.text, "Headless sessions are covered too. The hook skips them; auto-compact is their backstop.")


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
