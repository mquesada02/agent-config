import importlib.machinery
import importlib.util
import itertools
import json
import os
import subprocess
import sys
import unittest

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "block_subagent_writes.py")

BLOCKED = (
    "gh api -X PUT repos/o/r/environments/prod",
    "gh api --method=DELETE repos/o/r/environments/prod",
    "gh api -XPATCH repos/o/r",
    "gh api repos/o/r/rulesets -X POST -f name=x",
    "gh api repos/o/r/issues -f title=x",
    "gh api repos/o/r/issues -F title=x",
    "gh api repos/o/r/issues --field title=x",
    "gh api repos/o/r/issues --raw-field=title=x",
    "gh api repos/o/r/issues --input body.json",
    "gh -R o/r pr merge 5",
    "gh pr create --title t",
    "gh pr new --fill",
    "gh -R o/r pr new",
    "gh pr -R o/r new",
    "gh alias set mg 'pr merge'",
    "gh alias set --shell mg '!gh pr merge 5'",
    "gh alias set pv 'pr view'",
    "gh -R o/r alias set mg 'pr merge'",
    "gh alias import aliases.yml",
    "gh alias import -",
    "gh alias delete mg",
    "gh pr edit 5 --add-label x",
    "gh pr comment 5 --body x",
    "gh pr review 5 --approve",
    "gh issue create --title t",
    "gh issue close 5",
    "gh repo edit --visibility private",
    "gh repo delete o/r --yes",
    "gh release create v1",
    "gh secret set NAME",
    "gh variable delete NAME",
    "gh label create bug",
    "git push",
    "git push origin HEAD:main",
    "git -C /tmp/x push --force",
    "git-push origin main",
    "terraform apply",
    "terraform -chdir=infra apply -auto-approve",
    "terraform destroy",
    "terraform import aws_s3_bucket.b name",
    "terraform state rm aws_s3_bucket.b",
    "terraform state mv a b",
    "terraform state push x.tfstate",
    "terraform force-unlock 1234",
    "aws s3 rb s3://bucket",
    "aws --profile p ec2 terminate-instances --instance-ids i-1",
    "aws iam create-user --user-name x",
    "aws s3api put-object --bucket b --key k",
    "aws ssm put-parameter --name n --value v",
)

WRAPPED = (
    "bash -c 'gh api -X PUT repos/o/r/environments/prod'",
    "sh -lc \"git push origin main\"",
    "eval 'terraform apply'",
    "bash -c \"bash -c 'gh pr merge 5'\"",
    "git diff && git push",
    "git status; terraform apply",
    "gh pr view 5 | gh pr merge 5",
    "bash -c 'gh pr new --fill'",
    "echo $(gh alias set mg 'pr merge')",
    "eval 'gh alias import aliases.yml'",
    "true && gh alias delete mg",
    "echo $(gh pr merge 5)",
    "echo \"$(git push)\"",
    "echo `git push`",
    "FOO=1 gh pr merge 5",
    "sudo git push",
    "timeout 30 terraform apply",
    "xargs -n1 gh pr merge",
    "find . -exec gh issue close {} ;",
    "true\ngit push",
    "git push \\\n  origin main",
)

UNRESOLVABLE = (
    "gh 'unterminated",
    "$GH api -X PUT repos/o/r",
    "$(which gh) pr merge 5",
    "gh $SUB create",
    "gh pr $VERB 5",
    "git $SUB origin",
    "terraform $SUB",
    "aws s3 $OPERATION",
    "bash -c \"$CMD\"",
    "eval \"$CMD\"",
    "echo $(",
)

ALLOWED = (
    "gh api repos/o/r/issues",
    "gh api -X GET repos/o/r/issues",
    "gh api --method GET repos/o/r/issues --jq '.[].title'",
    "gh api repos/o/r/issues -q '.[] | .title'",
    "gh pr view 5",
    "gh alias list",
    "gh pr list --state open",
    "gh pr diff 5",
    "gh pr checks 5",
    "gh issue view 5 --comments",
    "gh issue list",
    "gh repo view o/r",
    "gh release view v1",
    "gh run view 5",
    "git diff",
    "git log --oneline -5",
    "git show HEAD",
    "git status",
    "git commit -m 'push the change'",
    "git -C /tmp/x log",
    "terraform fmt -check",
    "terraform validate",
    "terraform show",
    "terraform plan",
    "terraform state list",
    "terraform -chdir=infra plan -out=p",
    "aws sts get-caller-identity",
    "aws --profile p ec2 describe-instances",
    "aws s3api head-object --bucket b --key k",
    "aws iam list-users",
    "aws --version",
    "python3 -m unittest discover",
    "npm test",
    "ls -la && cat README.md",
    "grep -r 'git push' docs",
    "echo gh pr merge 5",
    "cat <<'EOF'\ngit push\nEOF",
    "bash -c 'git diff'",
    "bash script.sh arg",
    "echo $(git rev-parse HEAD)",
    "$HOME/.claude/hooks/tool arg",
    "[ -f x ] && echo ok",
)


class HookTest(unittest.TestCase):
    def run_hook(self, command, subagent=True, **extra):
        data = {"tool_name": "Bash", "tool_input": {"command": command}, **extra}
        if subagent:
            data.update(agent_id="agent-1", agent_type="general-purpose")
        result = subprocess.run([sys.executable, "-I", HOOK], input=json.dumps(data).encode(), capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else None

    def assert_denied(self, command):
        output = self.run_hook(command)
        self.assertIsNotNone(output, command)
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("Report the need as a finding", output["permissionDecisionReason"])

    def test_each_remote_write_form_is_denied_for_a_subagent(self):
        for command in BLOCKED:
            with self.subTest(command=command):
                self.assert_denied(command)

    def test_wrapped_forms_are_denied_for_a_subagent(self):
        for command in WRAPPED:
            with self.subTest(command=command):
                self.assert_denied(command)

    def test_a_command_that_cannot_be_resolved_is_denied_for_a_subagent(self):
        for command in UNRESOLVABLE:
            with self.subTest(command=command):
                self.assert_denied(command)

    def test_nesting_deeper_than_the_limit_is_denied(self):
        self.assert_denied("bash -c \"bash -c \\\"bash -c \\\\\\\"bash -c 'git diff'\\\\\\\"\\\"\"")

    def reason_of(self, command):
        output = self.run_hook(command)
        self.assertIsNotNone(output, command)
        self.assertEqual(output["permissionDecision"], "deny")
        return output["permissionDecisionReason"]

    def test_a_backtick_form_that_holds_a_gated_command_is_denied_with_a_reason_that_names_it(self):
        for command, named in (
            ("echo `git push`", "git push changes the remote"),
            ("echo `git push", "git push changes the remote"),
            ("echo \"`gh pr merge 5`\"", "gh pr merge changes GitHub"),
            ("x=`gh api -X PUT repos/o/r/environments/prod` && ls", "gh api with the method 'PUT' changes GitHub"),
            ("ls `echo hi` `terraform apply`", "terraform apply changes remote state"),
            ("echo `bash -c 'git push'`", "git push changes the remote"),
            ("echo `echo \\`git push\\``", "git push changes the remote"),
        ):
            with self.subTest(command=command):
                reason = self.reason_of(command)
                self.assertIn(f"{named}, inside a backtick form", reason)
                self.assertNotIn("cannot be read", reason)

    def test_a_backtick_form_with_no_gated_command_is_still_denied_as_unreadable(self):
        for command in ("echo `ls`", "echo `", "echo `git status` `git diff`", "echo `$CMD`", "echo \"`ls`\""):
            with self.subTest(command=command):
                reason = self.reason_of(command)
                self.assertIn("the command cannot be read (ValueError)", reason)
                self.assertNotIn("inside a backtick form", reason)

    def test_the_reason_of_a_form_with_no_backtick_is_unchanged(self):
        self.assertIn("gh pr merge changes GitHub. A subagent", self.reason_of("echo $(gh pr merge 5)"))
        self.assertIn("a gh subcommand that a variable, a substitution or a pattern builds. A subagent", self.reason_of("gh $SUB create"))

    def test_read_only_forms_pass_for_a_subagent(self):
        for command in ALLOWED:
            with self.subTest(command=command):
                self.assertIsNone(self.run_hook(command))

    def test_every_command_passes_without_an_agent_id(self):
        for command in BLOCKED + WRAPPED + UNRESOLVABLE:
            with self.subTest(command=command):
                self.assertIsNone(self.run_hook(command, subagent=False))

    def test_an_empty_agent_id_counts_as_a_main_session(self):
        self.assertIsNone(self.run_hook("git push", subagent=False, agent_id=""))

    def test_a_tool_other_than_bash_passes(self):
        data = {"tool_name": "Read", "agent_id": "a", "tool_input": {"file_path": "/x"}}
        result = subprocess.run([sys.executable, "-I", HOOK], input=json.dumps(data).encode(), capture_output=True, check=False)
        self.assertEqual((result.returncode, result.stdout), (0, b""))

    def test_a_subagent_call_with_no_command_text_is_denied(self):
        data = {"tool_name": "Bash", "agent_id": "a", "tool_input": {}}
        result = subprocess.run([sys.executable, "-I", HOOK], input=json.dumps(data).encode(), capture_output=True, check=False)
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_input_that_is_not_json_passes(self):
        result = subprocess.run([sys.executable, "-I", HOOK], input=b"not json", capture_output=True, check=False)
        self.assertEqual((result.returncode, result.stdout), (0, b""))


def _hook_module():
    """The hook as a module, read as data (no `.pyc` is written)."""
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        loader = importlib.machinery.SourceFileLoader("block_subagent_writes_for_test", HOOK)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = previous


hook = _hook_module()
RULES = hook.DenyRules(hook.load_reader())


class NamedReasonTest(unittest.TestCase):
    """Whether a reason names a gated command is the type of the reason, not its text."""

    def test_an_unnamed_reason_is_flagged_by_its_type(self):
        self.assertFalse(hook.names_gated_command(hook.UnnamedReason("anything")))

    def test_the_text_of_a_reason_decides_nothing(self):
        for text in ("a gh subcommand that a variable, a substitution or a pattern builds", "the command cannot be read (ValueError)",
                     "shell commands nested deeper than 3", "git push changes the remote"):
            with self.subTest(text=text):
                self.assertTrue(hook.names_gated_command(text))
                self.assertFalse(hook.names_gated_command(hook.UnnamedReason(text)))

    def test_a_reason_that_names_no_gated_command_is_flagged_and_a_gated_one_is_not(self):
        deep = "bash -c \"bash -c \\\"bash -c \\\\\\\"bash -c 'git diff'\\\\\\\"\\\"\""
        for command in ("gh $SUB create", "git $SUB", "$CMD x", "terraform $SUB", "aws s3 $OP", "echo `ls`", "echo `", deep):
            with self.subTest(command=command):
                reason = RULES.command_reason(command)
                self.assertTrue(reason)
                self.assertFalse(hook.names_gated_command(reason))
        for command in ("git push", "gh pr merge 5", "echo $(git push)", "echo `git push`", "echo `echo \\`git push\\``"):
            with self.subTest(command=command):
                self.assertTrue(hook.names_gated_command(RULES.command_reason(command)))

    def test_the_reason_texts(self):
        self.assertEqual(RULES.command_reason("gh $SUB create"), "a gh subcommand that a variable, a substitution or a pattern builds")
        self.assertEqual(RULES.command_reason("echo `ls`"), "the command cannot be read (ValueError)")
        self.assertEqual(RULES.command_reason("echo `git push`"), "git push changes the remote, inside a backtick form")


class BacktickReasonTest(unittest.TestCase):
    """Each path of `backtick_reason`; none of them raises, so the method needs no `try/except` around its loop."""

    def reason(self, command, depth=0):
        return RULES.backtick_reason(command, depth)

    def test_the_nesting_limit_returns_none(self):
        self.assertIsNone(self.reason("echo `git push`", RULES.audit.MAX_SHELL_DEPTH + 1))
        self.assertIsNotNone(self.reason("echo `git push`", RULES.audit.MAX_SHELL_DEPTH))

    def test_a_text_with_no_backtick_returns_none(self):
        self.assertIsNone(self.reason("git push"))

    def test_a_closed_form_with_a_gated_command_is_named(self):
        self.assertEqual(self.reason("echo `git push`"), "git push changes the remote, inside a backtick form")

    def test_an_unclosed_form_runs_to_the_end_of_the_text(self):
        self.assertEqual(self.reason("echo `gh pr merge 5"), "gh pr merge changes GitHub, inside a backtick form")

    def test_a_form_with_no_gated_command_returns_none(self):
        for command in ("echo `ls`", "echo `", "echo `$CMD`", "echo `git status` `git diff`"):
            with self.subTest(command=command):
                self.assertIsNone(self.reason(command))

    def test_a_later_form_is_searched_after_an_earlier_one(self):
        self.assertEqual(self.reason("ls `echo hi` `terraform apply`"), "terraform apply changes remote state, inside a backtick form")

    def test_a_body_that_cannot_be_read_is_searched_in_turn(self):
        self.assertEqual(self.reason("echo `echo \\`git push\\``"),
                         "git push changes the remote, inside a backtick form, inside a backtick form")

    def test_no_text_makes_it_raise(self):
        pieces = ("`", "\\", "'", '"', "$(", ")", "git push", " ", "<<")
        for count in range(1, 5):
            for combination in itertools.product(pieces, repeat=count):
                text = "".join(combination)
                try:
                    self.reason(text)
                except Exception as error:
                    self.fail(f"{text!r} raised {error!r}")


if __name__ == "__main__":
    unittest.main()
