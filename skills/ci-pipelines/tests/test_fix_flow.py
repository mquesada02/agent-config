"""Tests of the fix-on-approval text of the router and the review steps, and the no-write scan.

The review steps are text that the model reads, so the tests check the key phrases of each rule.
"""
import glob
import os
import re
import unittest

from skill_files import EVALS, SKILL, read

ADMIN_HEADING = "## Branch protection steps for the admin"
BODY_FLAGS = ("--field", "--raw-field", "--input")


def code_spans(text):
    """The code of a Markdown text: each fenced line, and each inline code span outside the fences."""
    spans, fenced = [], False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
        elif fenced:
            spans.append(line.strip())
        else:
            spans += [span.strip() for span in re.findall(r"`([^`]+)`", line)]
    return spans


def writes_protection(command):
    """True when a `gh api` command names a branch protection or ruleset path and writes to it.

    A write is a method other than GET (-X or --method) or a body flag (-f, -F, --field, --raw-field, --input)."""
    command = re.sub(r"^\$\s*", "", command.strip())
    if not re.match(r"gh api\s+\S", command):
        return False
    tokens = command.split()
    if not any(("branches/" in t and "/protection" in t) or "rulesets" in t for t in tokens):
        return False
    for number, token in enumerate(tokens):
        following = tokens[number + 1] if number + 1 < len(tokens) else ""
        if token == "-X" and following.upper() != "GET":
            return True
        if token.startswith("-X") and token != "-X" and token[2:].upper() != "GET":
            return True
        if token == "--method" and following.upper() != "GET":
            return True
        if token.startswith("--method=") and token[len("--method="):].upper() != "GET":
            return True
        if token.startswith(("-f", "-F")) or token.split("=")[0] in BODY_FLAGS:
            return True
    return False


def markdown_writes(text):
    return [span for span in code_spans(text) if writes_protection(span)]


def script_flag_literals(text):
    return re.findall(r"""["'](-X|--method|-f|-F|--field|--raw-field|--input)["']""", text)


def section(text, heading):
    start = text.index(heading)
    end = text.find("\n## ", start + 1)
    return text[start:] if end == -1 else text[start:end]


class Scan(unittest.TestCase):
    def test_a_write_flag_on_a_protection_path_is_found(self):
        for command in (
            "gh api -X PUT repos/o/r/branches/main/protection",
            "gh api repos/o/r/branches/main/protection -XPUT",
            "gh api --method POST repos/o/r/rulesets",
            "gh api --method=PATCH repos/o/r/rulesets/5",
            "gh api repos/o/r/branches/main/protection -f required=1",
            "gh api repos/o/r/rulesets -F body=@x.json",
            "gh api repos/o/r/rulesets --input body.json",
            "$ gh api repos/o/r/branches/main/protection --field a=b",
        ):
            self.assertTrue(writes_protection(command), command)

    def test_a_read_or_another_path_is_not_found(self):
        for command in (
            "gh api repos/o/r/branches/main/protection",
            "gh api -X GET repos/o/r/rulesets",
            "gh api --method get repos/o/r/rules/branches/main",
            "gh api -X PATCH repos/o/r/issues/1",
            "gh api",
            "gh api call",
            "git diff -- ci.yml",
        ):
            self.assertFalse(writes_protection(command), command)

    def test_the_bare_prose_span_is_not_a_command(self):
        text = "No step makes a `gh api` call with `-X PUT` on `.../branches/<b>/protection`."
        self.assertEqual(markdown_writes(text), [])

    def test_a_command_in_a_fence_or_a_span_is_scanned(self):
        fence = "```\ngh api -X PUT repos/o/r/rulesets\n```"
        self.assertEqual(len(markdown_writes(fence)), 1)
        self.assertEqual(len(markdown_writes("Run `gh api --method POST repos/o/r/rulesets` now.")), 1)

    def test_the_skill_markdown_files_hold_no_such_command(self):
        paths = [os.path.join(SKILL, name) for name in ("SKILL.md", "review.md", "tools.md")]
        paths += glob.glob(os.path.join(SKILL, "rules", "*.md"))
        for path in paths:
            self.assertEqual(markdown_writes(read(path)), [], path)

    def test_the_eval_prompts_hold_no_such_command(self):
        for path in glob.glob(os.path.join(EVALS, "*", "prompt.md")):
            self.assertEqual(markdown_writes(read(path)), [], path)

    def test_the_intake_script_holds_no_method_or_body_flag_literal(self):
        self.assertEqual(script_flag_literals(read(os.path.join(SKILL, "scripts", "intake.py"))), [])

    def test_the_literal_scan_finds_a_flag(self):
        self.assertEqual(script_flag_literals('run(["gh", "api", "-X", "PUT", path])'), ["-X"])


class Router(unittest.TestCase):
    def setUp(self):
        self.text = read(os.path.join(SKILL, "SKILL.md"))

    def test_the_review_bullet_points_to_the_fix_section_for_a_reply(self):
        bullet = [line for line in self.text.splitlines() if line.startswith("- **Review**")][0]
        self.assertIn("Fix on approval", bullet)
        self.assertIn("review.md", bullet)
        for reply in ("`all`", "`none`", "a list", "a range"):
            self.assertIn(reply, bullet)

    def test_the_intake_paragraph_exempts_the_reply_turn(self):
        intake = section(self.text, "## Intake")
        self.assertIn("reuse the intake facts", intake)
        self.assertIn("run the intake script again only when none are in the conversation", intake)


class FixSection(unittest.TestCase):
    def setUp(self):
        self.full = read(os.path.join(SKILL, "review.md"))
        self.text = section(self.full, "## Fix on approval").lower()

    def test_the_old_no_fix_text_is_gone(self):
        low = self.full.lower()
        for gone in ("no fix flow", "fixes are not built yet", "edits nothing", "not built yet"):
            self.assertNotIn(gone, low)

    def test_step_8_keeps_its_no_write_sentence_and_the_no_edit_before_approval_rule(self):
        steps = section(self.full, "## Steps").lower()
        self.assertIn("never edit branch protection or rulesets", steps)
        self.assertIn("make no edit", steps)
        self.assertIn("fix on approval", steps)

    def test_the_reply_grammar(self):
        for phrase in ("`all`", "`none`", "a selection", "comma-separated list", "a range `a-b`",
                       "`1,3-5,9`", "counts once", "`3 - 5`"):
            self.assertIn(phrase, self.text)

    def test_the_invalid_reply_rule(self):
        for phrase in ("descending range", "unknown word", "empty reply",
                       "edit nothing, name the invalid part, restate the grammar and wait"):
            self.assertIn(phrase, self.text)

    def test_the_reply_refers_to_the_latest_report_and_a_missing_report_is_said(self):
        self.assertIn("latest report in the conversation", self.text)
        self.assertIn("offer a new review", self.text)

    def test_all_against_no_rows_edits_nothing(self):
        self.assertIn("no rows", self.text)
        self.assertIn("nothing to fix", self.text)

    def test_none_edits_no_file_and_runs_no_shell_command(self):
        self.assertIn("edit no file", self.text)
        self.assertIn("run no shell command", self.text)

    def test_the_edit_rule(self):
        for phrase in ("with the edit tool", "change nothing else", "no formatting",
                       "use no shell command to write a file", "skip it"):
            self.assertIn(phrase, self.text)

    def test_the_zero_edit_case(self):
        self.assertIn("no file was edited", self.text)
        self.assertIn("skip actionlint", self.text)

    def test_the_actionlint_rule_has_the_hint_and_never_installs(self):
        for phrase in ("`installed: true`", "[tools.md](tools.md)", "not on path",
                       "brew install actionlint", "never install a tool"):
            self.assertIn(phrase, self.text)

    def test_actionlint_and_git_diff_are_each_their_own_call(self):
        self.assertEqual(self.text.count("its own call, never chained with another command"), 2)

    def test_the_diff_rule(self):
        for phrase in ("fenced `diff` block", "git diff -- <files>", "by hand"):
            self.assertIn(phrase, self.text)

    def test_the_check_again_step_reuses_the_facts_and_the_actionlint_result(self):
        for phrase in ("check the edited workflows against the same rules",
                       "reuse the intake facts", "do not run it twice"):
            self.assertIn(phrase, self.text)

    def test_the_final_message_order_and_the_post_fix_report(self):
        for phrase in ("## applied", "bulleted list, never a table", "## diff",
                       "(after fixes)", "renumbers from 1", "`## approve`",
                       "there is nothing to approve"):
            self.assertIn(phrase, self.text)
        self.assertLess(self.text.index("## applied"), self.text.index("## diff"))
        self.assertLess(self.text.index("## diff"), self.text.index("(after fixes)"))

    def test_the_admin_steps(self):
        for phrase in (ADMIN_HEADING.lower(), "settings, branches, edit the rule for",
                       "settings, rules, rulesets, edit the ruleset", "require status checks to pass",
                       "remove `<removed names>`, add `<added names>`", "one removed name and several added names",
                       "always gives both places", "after the merge", "does not make the change",
                       "a skipped ⚑ row gets no admin steps"):
            self.assertIn(phrase, self.text)

    def test_the_admin_heading_does_not_start_with_the_flag_section_heading(self):
        self.assertFalse(ADMIN_HEADING.startswith("## ⚑"))
        self.assertIn(ADMIN_HEADING, self.full)

    def test_the_no_write_rule_names_the_methods_and_the_body_flags(self):
        for phrase in ("method other than `get`", "`-f`", "`-F`", "`--field`", "`--raw-field`", "`--input`",
                       "branch protection path", "ruleset path"):
            self.assertIn(phrase.lower(), self.text)

    def test_the_spec_decisions_are_named_as_safety_rules_not_in_the_section(self):
        # the section is a set of steps: it holds no ticket or spec number
        self.assertNotRegex(self.text, r"#\d{3}")


class ReadmeApprovalRun(unittest.TestCase):
    def setUp(self):
        self.text = read(os.path.join(EVALS, "README.md"))
        self.section = section(self.text, "## Approval cases")

    def test_the_run_has_the_flags(self):
        for flag in ("--case 'approve-*'", "--ablation none", "--scaffold", "--allow-tools Edit",
                     "Bash(actionlint*)", "Bash(git diff*)",
                     "-j 2", "--runs 1"):
            self.assertIn(flag, self.section)

    def test_it_documents_the_recorded_conversation_and_the_recorded_intake(self):
        for phrase in ("history.jsonl", "context.history_file", "intake.json", "next user turn"):
            self.assertIn(phrase, self.section)

    def test_it_names_option_a_and_the_trade_off(self):
        self.assertIn("actionlint on PATH", self.section)
        self.assertIn("proves the attempt and the order", self.section)

    def test_the_stale_review_notes_say_they_are_for_the_review_cases(self):
        self.assertIn("(review cases)", self.text)


if __name__ == "__main__":
    unittest.main()
