import json
import time
import unittest

from test_gate import GateTestCase

CLEANUP = "~/.claude/hooks/worktree-cleanup/cleanup"
UNCHECKED = "unchecked command form: run %s as a plain command, or use " + CLEANUP

GIT_PREFIXES = ("git", "/usr/bin/git", "git -C /x", "git -c k=v", "git --git-dir=x", "git --work-tree=x", "git --no-pager -C /x",
                "git --attr-source HEAD", "git -C 'my dir'", "VAR=1 git", "! git")
FORCE_DELETES = ("branch -D x", "branch -Df x", "branch -fD x", "branch -d -f x", "branch -df x", "branch --delete --force x",
                 "branch --del --forc x", "branch -d --force x", "branch --force -d x", "branch -dD x", "branch -D -- x")
PUSH_DELETES = ("push origin --delete x", "push origin -d x", "push origin :x", "push origin +:x", "push --prune origin",
                "push --mirror origin", "push origin --dele x", "push -fd origin x", "push origin -- :x", "push origin x :y")


class DeniedFormsTest(GateTestCase):
    def assert_pointer(self, command, phrase):
        reason = self.assert_denied(self.gate(command), phrase)
        self.assertIn(CLEANUP, reason)
        return reason

    def test_every_force_delete_spelling_is_denied_with_and_without_git_global_options(self):
        for prefix in GIT_PREFIXES:
            for tail in FORCE_DELETES:
                command = f"{prefix} {tail}"
                with self.subTest(command=command):
                    reason = self.assert_pointer(command, "force delete of a branch")
                    self.assertIn("! git branch -D", reason)

    def test_every_deleting_push_is_denied_with_and_without_git_global_options(self):
        for prefix in GIT_PREFIXES:
            for tail in PUSH_DELETES:
                command = f"{prefix} {tail}"
                with self.subTest(command=command):
                    self.assert_pointer(command, "deleting a remote ref")

    def test_every_git_worktree_remove_is_denied(self):
        for prefix in GIT_PREFIXES:
            for tail in ("worktree remove x", "worktree remove --force x"):
                command = f"{prefix} {tail}"
                with self.subTest(command=command):
                    self.assert_pointer(command, "git worktree remove")

    def test_every_orca_worktree_rm_is_denied(self):
        for program in ("orca", "orca-ide", "orca-dev", "/usr/bin/orca"):
            for tail in ("worktree rm x", "worktree rm --worktree path:/x --force --json"):
                command = f"{program} {tail}"
                with self.subTest(command=command):
                    self.assert_pointer(command, "orca worktree rm")

    def test_the_dashed_git_programs_are_denied(self):
        for command, phrase in (("/usr/lib/git-core/git-branch -D x", "force delete of a branch"),
                                ("git-push origin --delete x", "deleting a remote ref"), ("git-worktree remove x", "git worktree remove")):
            with self.subTest(command=command):
                self.assert_pointer(command, phrase)

    def test_skip_ownership_is_denied_for_the_agent(self):
        for command in ("cleanup --skip-ownership /w", "~/.claude/hooks/worktree-cleanup/cleanup --skip-ownership /w",
                        "cleanup /w --skip-ownership", "python3 /x/cleanup --skip-ownership /w", "python /x/cleanup /w --skip-ownership",
                        "python3 -u /x/cleanup --skip-ownership /w", "VAR=1 cleanup --skip-ownership /w"):
            with self.subTest(command=command):
                reason = self.assert_pointer(command, "--skip-ownership")
                self.assertIn("only the user", reason)

    def test_a_denied_form_in_a_later_segment_is_denied(self):
        for command, phrase in (("echo a && git branch -D x", "force delete of a branch"), ("cd /x; git push origin --delete y", "deleting a remote ref"),
                                ("echo a | orca worktree rm x", "orca worktree rm")):
            with self.subTest(command=command):
                self.assert_pointer(command, phrase)

    def test_the_first_denied_segment_decides_the_reason(self):
        self.assert_pointer("git push origin --delete x; git branch -D y", "deleting a remote ref")
        self.assert_pointer("git branch -D y; git push origin --delete x", "force delete of a branch")

    def test_a_denied_form_beats_a_pr_create_in_the_same_command(self):
        self.assert_pointer("gh pr create --title t && git branch -D x", "force delete of a branch")


class AllowedFormsTest(GateTestCase):
    ALLOWED = (
        "git branch -d x", "git branch", "git branch --list", "git branch -a", "git branch --show-current", "git branch -m old new",
        "git -C /x branch -d x", "git worktree prune", "git worktree add ../w", "git worktree list", "git -C /x worktree list",
        "git push origin x", "git push -u origin x", "git push --force-with-lease origin x", "git push",
        "cleanup /w", "~/.claude/hooks/worktree-cleanup/cleanup /w", "python3 /x/cleanup /w", "cleanup --help",
        "orca worktree list", "orca worktree show --worktree path:/x", "orca worktree rm --help", "orca-ide worktree rm -h",
        "git worktree remove --help", "git worktree remove -h", "git -C /x worktree remove --help", "git-worktree remove --help",
        "git commit -F f", "git add docs/git-push.py", "git status", "git branch -d x; git push origin y",
        "x=$(git branch --show-current)", "echo $(git branch -d x)", "git push origin x 2>&1", "git branch -d x > out",
        "git 2> /dev/null branch -d y", "git branch -d x 2>/dev/null", "! git branch -d x", "VAR=1 git push origin x",
        "git branch -d -- -f", "git push origin HEAD:refs/heads/x", "git log --oneline",
    )

    def test_every_allowed_form_passes(self):
        for command in self.ALLOWED:
            with self.subTest(command=command):
                self.assert_allowed(self.gate(command))

    def test_the_known_limit_of_a_spaced_redirection_target_is_allowed_in_a_wrapped_form(self):
        # Known limit, owner-approved: issue #192 tracks the fix. The pin changes on purpose when #192 lands.
        self.assert_allowed(self.gate('bash -c \'git >"my f" branch -D x\''))

    def test_an_unparsable_command_without_a_gated_form_is_allowed(self):
        self.assert_allowed(self.gate('echo "unbalanced'))


class WrappedFormsTest(GateTestCase):
    def test_a_wrapped_form_is_denied_with_the_unchecked_reason(self):
        cases = (
            ('bash -c "git branch -D x"', "git branch"), ("eval 'git branch -D x'", "git branch"),
            ('echo "$(git push origin --delete x)"', "git push"), ('sh -c "git -C /x push origin :y"', "git push"),
            ('bash -c "git worktree remove x"', "worktree remove"), ('echo "$(orca worktree rm x)"', "worktree rm"),
            ('bash -c "orca-ide worktree rm x"', "worktree rm"), ('bash -c "cleanup --skip-ownership /x"', "--skip-ownership"),
            ('bash -c "git-branch -D x"', "git branch"), ('bash -c "/usr/bin/git branch -D x"', "git branch"),
            ('bash -c "git 2>/dev/null branch -D x"', "git branch"), ('bash -c "git worktree 2>/dev/null remove x"', "worktree remove"),
            ('bash -c "orca >/dev/null worktree rm x"', "worktree rm"),
        )
        for command, form in cases:
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), UNCHECKED % form)

    def test_a_wrapped_help_is_denied(self):
        self.assert_denied(self.gate('bash -c "git worktree remove --help"'), UNCHECKED % "worktree remove")

    def test_plain_commands_pass_the_count_rule(self):
        for command in ("git branch -d x", "git push origin x", "git -C /x branch -d x", "git branch -d x; git branch -d y"):
            with self.subTest(command=command):
                self.assert_allowed(self.gate(command))

    def test_text_hidden_in_a_segment_does_not_cancel_a_plain_form_in_another(self):
        for command, form in (
            ('git -C "my dir" branch -d y; bash -c "git branch -D x"', "git branch"),
            ('git branch -d y; bash -c "git branch -D x"', "git branch"),
            ('git push origin a; echo "git push origin --delete b"', "git push"),
            ('cleanup /x; bash -c "cleanup --skip-ownership /y"', "--skip-ownership"),
            ('git worktree remove --help; bash -c "git worktree remove x"', "worktree remove"),
        ):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), UNCHECKED % form)

    def test_text_hidden_in_the_same_segment_is_denied(self):
        for command, form in (
            ('git -C "$(git branch -D x)" branch -d y', "git branch"),
            ('git -C "my dir" branch -d y "$(git branch -D x)"', "git branch"),
            ('git -c "a b=c" branch -d y "$(git branch -D x)"', "git branch"),
            ('git -C "my dir" push origin x "$(git push --delete origin y)"', "git push"),
            ('git branch -d "$(git branch -D x)"', "git branch"),
        ):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), UNCHECKED % form)

    def test_quoted_and_backtick_substitutions_are_counted(self):
        for command in ('x="$(git branch -D y)"', 'git push origin "$(git branch --show-current)"'):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), UNCHECKED % "git branch")
        # An unquoted body is a checked segment of its own: the safe -d is allowed, the -D is denied by its segment.
        self.assert_allowed(self.gate("echo `git branch -d x`"))
        self.assert_denied(self.gate("echo `git branch -D x`"), "force delete of a branch")

    def test_the_python_flag_before_the_script_is_denied_by_the_count_rule(self):
        self.assert_denied(self.gate("python3 --skip-ownership /x/cleanup /y"), UNCHECKED % "--skip-ownership")

    def test_an_orca_global_option_before_worktree_is_denied_by_the_count_rule(self):
        self.assert_denied(self.gate("orca --json worktree rm x"), UNCHECKED % "worktree rm")

    def test_a_git_word_at_the_end_of_a_name_is_a_known_cost(self):
        self.assert_denied(self.gate("git push origin fix/git-push"), UNCHECKED % "git push")
        self.assert_allowed(self.gate("echo digit branch"))
        self.assert_allowed(self.gate("echo my-git branch"))


class RedirectionTest(GateTestCase):
    def test_a_redirection_between_the_words_does_not_hide_a_denied_form(self):
        for command, phrase in (
            ("git 2>/dev/null branch -D x", "force delete of a branch"), ("git 2> /dev/null branch -D x", "force delete of a branch"),
            ("git {fd}>f branch -D x", "force delete of a branch"), ("git > out branch -D x", "force delete of a branch"),
            ("git -C d 2> e branch -D x", "force delete of a branch"), ("git branch '>' -D x", "force delete of a branch"),
            ("git < f push origin --delete x", "deleting a remote ref"), ("git worktree 2>/dev/null remove x", "git worktree remove"),
            ("git worktree 2> /dev/null remove x", "git worktree remove"), ("orca >/dev/null worktree rm x", "orca worktree rm"),
            ("orca worktree >/dev/null rm x", "orca worktree rm"), ("cleanup 2>/dev/null --skip-ownership /w", "--skip-ownership"),
        ):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), phrase)

    def test_a_redirection_cut_by_the_splitter_is_denied_by_the_whole_text_count(self):
        for command, form in (("git 2>&1 branch -D x", "git branch"), ("git &>f push origin --delete x", "git push"),
                              ("git 2>&1 branch -d y", "git branch")):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), UNCHECKED % form)


class PatternCostTest(GateTestCase):
    def test_a_long_run_of_option_words_does_not_make_the_gate_slow(self):
        for command in ("git " + "-C " * 200 + "x", "git " + "-c -C " * 100 + "branch", "git " + "2> " * 200 + "x", "git " + "-p " * 300 + "x",
                        "git " + "-C 2> " * 40 + "branchx", "git " + "-C > " * 40 + "branchx", "git " + "-c < " * 40 + "x",
                        "git " + "--git-dir {a}> " * 40 + "x", "git " + "-C 2> -c > " * 30 + "x", "git " + "-C 2> " * 40 + "branch -D x'q"):
            with self.subTest(command=command[:20]):
                started = time.monotonic()
                self.gate(command)
                self.assertLess(time.monotonic() - started, 5)


class GateOrderTest(GateTestCase):
    def hook(self, **data):
        return self.audit("hook", "pre-tool-use", stdin=json.dumps(data))

    def test_the_new_deny_needs_no_session_id_working_directory_or_runtime_folder(self):
        for command in ("git branch -D x", "cleanup --skip-ownership /w"):
            with self.subTest(command=command):
                result = self.hook(tool_input={"command": command})
                self.assertIsNotNone(self.denial(result))

    def test_the_deny_reasons_of_the_existing_gates_do_not_change(self):
        self.assert_denied(self.gate("gh pr create --title t --body b"), "no record")


if __name__ == "__main__":
    unittest.main()
