import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from audit_support import HERE, AuditCase, round_event

BRIEF = os.path.join(HERE, "auditor-brief.md")
GITIGNORE = os.path.join(HERE, "..", "..", ".gitignore")
AUDIT_PATH = "~/.claude/hooks/workflow-audit/audit"


def read_brief():
    with open(BRIEF, encoding="utf-8") as handle:
        return handle.read()


class BriefTextTest(unittest.TestCase):
    def setUp(self):
        self.text = read_brief()

    def test_defines_the_six_items(self):
        for name in ("L1", "L2", "L3", "L4", "L5", "L6"):
            with self.subTest(name):
                self.assertRegex(self.text, rf"\*\*{name}\.\*\* ")

    def test_l1_quotes_the_section_6_evidence_rules(self):
        for phrase in ("section 6 of `~/.claude/CLAUDE.md`", "A spec mismatch needs the quoted spec line", "always Blocking",
                       "the quoted code and the section 0 rule", "an input or state and the wrong result", "A finding without its evidence is Minor"):
            with self.subTest(phrase):
                self.assertIn(phrase, self.text)

    def test_names_the_three_inputs_including_the_done_report(self):
        self.assertIn("The path of the session's draft done report", self.text)
        self.assertIn("The worktree path", self.text)
        self.assertIn("The path where you write the verdict file", self.text)

    def test_gives_the_literal_command_lines(self):
        self.assertIn(f"python3 -I {AUDIT_PATH} check --worktree <worktree>", self.text)
        self.assertIn(f"python3 -I {AUDIT_PATH} record --worktree <worktree> --llm <verdict file>", self.text)

    def test_both_variants_read_the_ledger_with_ledger_show_into_a_file_page_by_page(self):
        command = f"python3 -I {AUDIT_PATH} ledger show --worktree <worktree> > <verdict file>.ledger.txt"
        full, variant = self.text.split("## Pre-dispatch variant", 1)[0], self.text.split("## Pre-dispatch variant", 1)[1]
        for name, part in (("full", full), ("pre-dispatch", variant)):
            for phrase in (command, "exit status", "page by page", "last line"):
                with self.subTest(variant=name, phrase=phrase):
                    self.assertIn(phrase, part)

    def test_both_variants_fail_closed_on_an_unexpected_exit_status_or_a_bad_first_line(self):
        for name, part in (("full", self.text.split("## Pre-dispatch variant", 1)[0]), ("pre-dispatch", self.text.split("## Pre-dispatch variant", 1)[1])):
            for phrase in ("other than 0 or 2", "does not start with a line that is exactly `ledger` or `ledger unavailable: <why>`",
                           "evidence unavailable", "names the exit status and the stderr text", "you have not read"):
                with self.subTest(variant=name, phrase=phrase):
                    self.assertIn(phrase, part)

    def test_the_full_variant_says_ledger_show_is_the_only_source_of_the_ledger_events(self):
        full = self.text.split("## Pre-dispatch variant", 1)[0]
        self.assertIn("only source for the ledger events", full)
        self.assertIn("ledger lines of `ledger show` hold each finding's type and reason", full)
        self.assertIn("`ledger show` output", full.split("## The six items", 1)[1].split("- **L1.**", 1)[0])
        self.assertIn("`ledger unavailable` output makes each item that needs the ledger `fail` with \"evidence unavailable\"", full)

    def test_the_digest_no_longer_holds_the_ledger_events_in_the_brief(self):
        full = self.text.split("## Pre-dispatch variant", 1)[0]
        self.assertNotIn("It holds the ledger events", full)
        self.assertNotIn("The ledger lines in the digest", full)
        self.assertNotIn("ledger lines of the digest", self.text)
        self.assertIn("It holds the ledger event count, the commits of the branch and one block per audited session", full)

    def test_the_ledger_show_step_comes_right_after_the_check_step_and_before_the_done_report(self):
        steps = self.text.split("## Steps", 1)[1].split("## The six items", 1)[0]
        numbered = [line for line in steps.splitlines() if re.match(r"\d+\. ", line)]
        index = next(i for i, line in enumerate(numbered) if "ledger show" in line)
        self.assertIn(" check --worktree", numbered[index - 1])
        self.assertIn("draft done report", numbered[index + 1])

    def test_the_pre_dispatch_variant_reads_the_plan_review_events_from_ledger_show(self):
        variant = self.text.split("## Pre-dispatch variant", 1)[1]
        steps = variant.split("Steps:", 1)[1].split("**L1, pre-dispatch.**", 1)[0]
        first = steps.strip().splitlines()[0]
        self.assertIn(" check --worktree", first)
        self.assertIn("ledger show", first)
        self.assertIn("events of the loops `plan-review-3` and `plan-review-4.1` in the `ledger show` output", first)
        paragraph = variant.split("**L1, pre-dispatch.**", 1)[1]
        self.assertIn("ledger lines of `ledger show` hold each finding's type and reason", paragraph)
        self.assertIn("`ledger unavailable`", paragraph)
        self.assertIn("evidence unavailable", paragraph)

    def test_the_first_step_is_the_push_check(self):
        steps = self.text.split("## Steps", 1)[1].split("## The six items", 1)[0]
        first = steps.strip().splitlines()[0]
        self.assertIn("pushed", first)
        self.assertIn("push first", first)

    def test_bans_fixing_and_s_input(self):
        self.assertIn("You never fix anything", self.text)
        self.assertIn("you do not write S results", self.text)
        self.assertIn("It never takes S results from you", self.text)

    def test_describes_the_format_and_missing_evidence(self):
        for phrase in ("exactly the keys `L1` to `L6`", "`result` (`pass` or `fail`)", "at most 4000 characters", "evidence unavailable"):
            with self.subTest(phrase):
                self.assertIn(phrase, self.text)

    def test_describes_the_pre_dispatch_variant(self):
        variant = self.text.split("## Pre-dispatch variant", 1)[1]
        for phrase in ("The map issue number", "The worktree path", "The path where you write the verdict file", "exactly the key `L1`",
                       f"python3 -I {AUDIT_PATH} check --worktree <worktree>",
                       f"python3 -I {AUDIT_PATH} record --pre-dispatch --worktree <worktree> --map <issue> --llm <verdict file>",
                       "plan-review-3", "plan-review-4.1", "quotes the line it rests on", "there is no push check",
                       "you never fix anything", "never write S results", "never takes S results from you", "evidence unavailable"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, variant)

    def test_the_variant_comes_after_the_existing_sections(self):
        order = [self.text.index(heading) for heading in ("## Inputs", "## Steps", "## The six items", "## The verdict file", "## Pre-dispatch variant")]
        self.assertEqual(order, sorted(order))

    def test_is_not_ignored_by_the_allow_list(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        shutil.copy(GITIGNORE, os.path.join(root, ".gitignore"))
        env = {"PATH": os.environ["PATH"], "HOME": root}
        subprocess.run(["git", "init", "-q", root], check=True, env=env)
        result = subprocess.run(["git", "-C", root, "check-ignore", "-q", "hooks/workflow-audit/auditor-brief.md"], env=env)
        self.assertEqual(result.returncode, 1)


class BriefExampleTest(AuditCase):
    def test_the_example_verdict_is_accepted_by_record(self):
        blocks = re.findall(r"```json\n(.*?)\n```", read_brief(), re.DOTALL)
        self.assertTrue(blocks)
        json.loads(blocks[0])
        self.write_llm(blocks[0])
        self.start_branch("feature", "feat: a")
        result = self.record()
        self.assertEqual(result.returncode, 0, result.stderr)


class PreDispatchExampleTest(AuditCase):
    def test_the_variant_example_is_accepted_by_record_pre_dispatch(self):
        blocks = re.findall(r"```json\n(.*?)\n```", read_brief(), re.DOTALL)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(list(json.loads(blocks[1])), ["L1"])
        self.write_llm(blocks[1])
        self.git("checkout", "-b", "feature")
        self.commit("feat: a")
        self.write_ledger("feature", [round_event(loop="plan-review-3"), round_event(loop="plan-review-4.1")])
        result = self.audit("record", "--pre-dispatch", "--worktree", self.repo, "--map", "82", "--llm", self.llm_path,
                            env={"CLAUDE_CODE_SESSION_ID": "main-1"})
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
