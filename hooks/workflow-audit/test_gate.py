import json
import os
import stat
import unittest

from audit_support import PASSING_LLM, AuditCase

PR = "gh pr create --title t --body b"


class GateTestCase(AuditCase):
    def audited_branch(self, name="feature", message="feat: a"):
        """A pushed branch with a passing record. Leaves the branch checked out."""
        tip = self.start_branch(name, message)
        self.assertEqual(self.record().returncode, 0)
        return tip

    def assert_denied(self, result, phrase):
        reason = self.denial(result)
        self.assertIsNotNone(reason, "the command was allowed")
        self.assertTrue(reason.startswith(phrase), reason)
        return reason

    def assert_allowed(self, result):
        self.assertIsNone(self.denial(result))
        self.assertEqual(result.stdout, b"")


class DenialReasonTest(GateTestCase):
    def test_a_passing_record_for_the_pushed_tip_allows(self):
        self.audited_branch()
        result = self.gate(PR)
        self.assert_allowed(result)
        self.assertEqual(result.stderr, b"")

    def test_push_first(self):
        self.git("checkout", "-b", "unpushed")
        self.commit("feat: a")
        reason = self.assert_denied(self.gate(PR), "push first")
        self.assertIn("unpushed", reason)

    def test_no_record(self):
        self.start_branch("feature", "feat: a")
        self.assert_denied(self.gate(PR), "no record")

    def test_stale_record(self):
        self.audited_branch()
        self.commit("feat: more")
        self.git("push", "origin", "feature")
        self.assert_denied(self.gate(PR), "stale record")

    def test_a_record_of_another_branch_is_not_stale(self):
        self.audited_branch("one")
        self.start_branch("two", "feat: b")
        self.assert_denied(self.gate(PR), "no record")

    def test_failed_record(self):
        self.start_branch("feature", "bad message")
        self.assertEqual(self.record().returncode, 1)
        self.assert_denied(self.gate(PR), "failed record")

    def test_remote_mismatch(self):
        self.audited_branch()
        self.git("remote", "set-url", "origin", self.origin + "-other")
        self.assert_denied(self.gate(PR), "remote mismatch")

    def test_a_local_commit_that_is_not_pushed_does_not_change_the_pushed_tip(self):
        self.audited_branch()
        self.commit("local only")
        self.assert_allowed(self.gate(PR))

    def test_unrelated_and_broken_records_in_the_folder_do_not_decide(self):
        self.start_branch("feature", "feat: a")
        os.mkdir(self.runtime, 0o700)
        with open(os.path.join(self.runtime, "a" * 40 + ".json"), "w") as handle:
            handle.write("{broken")
        with open(os.path.join(self.runtime, "b" * 40 + ".json"), "w") as handle:  # sha field differs from the file name
            json.dump({"sha": "c" * 40, "remote_url": self.origin, "branch": "feature", "result": "pass"}, handle)
        with open(os.path.join(self.runtime, "sessions.jsonl"), "w") as handle:
            handle.write("{}\n")
        self.assert_denied(self.gate(PR), "no record")

    def test_a_broken_record_for_the_tip_is_a_hook_error(self):
        tip = self.audited_branch()
        with open(os.path.join(self.runtime, f"{tip}.json"), "w") as handle:
            handle.write('{"sha": "%s"}' % tip)
        self.assert_denied(self.gate(PR), "hook error")

    def test_the_deny_output_is_one_json_object_and_exit_0(self):
        self.start_branch("feature", "feat: a")
        result = self.gate(PR)
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        self.assertEqual(list(output), ["hookSpecificOutput"])
        self.assertEqual(set(output["hookSpecificOutput"]), {"hookEventName", "permissionDecision", "permissionDecisionReason"})


class MatchingTest(GateTestCase):
    def setUp(self):
        super().setUp()
        self.start_branch("feature", "feat: a")  # no record: every match is denied with "no record"

    def test_commands_that_run_gh_pr_create_are_denied(self):
        for command in (
            "gh pr create",
            "gh  pr   create",
            "gh\tpr\tcreate --fill",
            f"cd {self.repo} && gh pr create",
            "echo hi; gh pr create --title t",
            "true || gh pr create",
            "true | gh pr create",
            "true & gh pr create",
            "echo hi\ngh pr create",
            "(gh pr create)",
            "x;(gh pr create)",
            "x&&(gh pr create)",
            "FOO=1 BAR=2 gh pr create",
            "/usr/bin/gh pr create",
            "echo $(gh pr create)",
            "# a comment line\ngh pr create",
            "gh pr create --title C#1",
            "echo \"two\nlines\" && gh pr create",
            "if true; then gh pr create; fi",
            "if gh pr create; then echo ok; fi",
            "while true; do gh pr create; done",
            "{ gh pr create; }",
            "! gh pr create",
            "time gh pr create",
            "env gh pr create",
            "env FOO=1 gh pr create",
            "command gh pr create",
            "exec gh pr create",
            "true && ! FOO=1 time gh pr create",
        ):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command, cwd=self.repo), "no record")

    def test_gh_pr_create_inside_a_command_substitution_is_denied(self):
        # Bodies of substitutions are not parsed: more occurrences of the text than matching segments, plus a substitution marker, fails closed.
        for command in ("echo `gh pr create`", "x=`gh pr create`", 'echo "`gh pr create`"', 'echo "$(gh pr create)"', 'echo "$(gh  pr   create)"',
                        'echo "a $(true) b" "$(gh pr create)"', "echo '`gh pr create`'"):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), "no branch to check")
        self.assert_denied(self.gate("echo $(gh pr create)"), "no record")  # an unquoted substitution is parsed and checked as a command

    def test_substitutions_without_the_text_are_allowed(self):
        for command in ("echo $(date)", 'echo "$(date)"', "echo `date`", "git commit -m \"$(cat <<'EOF'\nfeat: x\nEOF\n)\"", 'echo "gh pr create"'):
            with self.subTest(command=command):
                self.assert_allowed(self.gate(command))

    def test_commands_that_do_not_run_it_are_allowed(self):
        for command in (
            "gh pr view 1",
            "gh issue create",
            "gh pr list",
            "echo gh pr create",
            "git commit -m 'gh pr create'",
            "echo \"gh pr create\"",
            "ls",
            "",
            "# gh pr create",
            "gh pr",
            "echo then gh pr create",
            "if true; then echo gh pr create; fi",
            "env FOO=1 ls",
            "time ls",
        ):
            with self.subTest(command=command):
                self.assert_allowed(self.gate(command))

    def test_a_command_that_cannot_be_parsed_is_matched_on_normalised_raw_text(self):
        for command in ('gh pr create --title "unbalanced', "gh   pr \t create 'x", 'echo "a" && gh  pr  create "b'):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), "no branch to check")
        for command in ('echo "unbalanced', "gh pr view 'x"):
            with self.subTest(command=command):
                self.assert_allowed(self.gate(command))

    def test_cd_before_the_match_moves_the_working_directory(self):
        other = os.path.join(self.root, "other")
        os.mkdir(other)  # not a git repository
        self.assert_denied(self.gate(f"cd {other} && {PR}", cwd=self.repo), "no branch to check")
        self.assert_denied(self.gate(f"cd {other} || {PR}", cwd=self.repo), "no branch to check")
        self.assert_denied(self.gate(f"cd {other}; cd {self.repo} && {PR}", cwd=self.root), "no record")
        self.assert_denied(self.gate(f"cd repo && {PR}", cwd=self.root), "no record")
        self.assert_denied(self.gate(f"cd ../repo && {PR}", cwd=other), "no record")
        self.assert_denied(self.gate(f"cd {self.repo}\n{PR}", cwd=other), "no record")

    def test_a_cd_that_cannot_be_resolved_denies_a_match(self):
        for cd in ("cd", "cd -", "cd -P .", "cd $HOME", "cd `pwd`", "cd *", "cd a b", "cd '$x'"):
            with self.subTest(cd=cd):
                self.assert_denied(self.gate(f"{cd} && {PR}"), "no branch to check")
        self.assert_allowed(self.gate("cd - && ls"))

    def test_a_tilde_cd_expands_the_home_folder(self):
        self.assert_denied(self.gate(f"cd ~ && {PR}"), "no branch to check")  # HOME is not a repo


class CdScopeTest(GateTestCase):
    """A cd changes the working directory of the commands after it only as bash does: not in a subshell, not in a pipeline, not in the background."""

    def setUp(self):
        super().setUp()
        self.audited_branch()  # self.repo: allowed
        self.other = os.path.join(self.root, "other")
        os.mkdir(self.other)  # not a git repository: "no branch to check"

    def test_a_cd_that_persists_moves_the_check(self):
        for command in (f"cd {self.repo} && {PR}", f"cd {self.repo}; {PR}", f"false || cd {self.repo} && {PR}", f"(cd {self.repo} && {PR})",
                        f"cd {self.other} && cd {self.repo} && {PR}", f"sleep 1 & cd {self.repo} && {PR}"):
            with self.subTest(command=command):
                self.assert_allowed(self.gate(command, cwd=self.other))

    def test_a_cd_that_does_not_persist_leaves_the_check_in_the_starting_directory(self):
        for command in (f"(cd {self.repo}); {PR}", f"(cd {self.repo} && true) && {PR}", f"cd {self.repo} | {PR}", f"cd {self.repo} & {PR}",
                        f"true | cd {self.repo} && {PR}", f"cd {self.repo} |& {PR}", f"((cd {self.repo})); {PR}",
                        f"cd {self.repo} &\n{PR}", f"cd {self.repo} |\n{PR}", f"cd {self.repo} &({PR})", f"cd {self.repo} |\n\n{PR}",
                        f"true |\ncd {self.repo} && {PR}"):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command, cwd=self.other), "no branch to check")
                self.assert_allowed(self.gate(command.replace(self.repo, self.other), cwd=self.repo))

    def test_a_nested_subshell_restores_the_directory_of_each_level(self):
        self.assert_allowed(self.gate(f"(cd {self.other}; (cd {self.repo}); cd {self.repo}; {PR})", cwd=self.other))
        self.assert_denied(self.gate(f"cd {self.repo}; (cd {self.other}; true); {PR} && cd {self.other}; {PR}", cwd=self.repo), "no branch to check")


class HeadBranchTest(GateTestCase):
    def setUp(self):
        super().setUp()
        self.audited_branch("feature")
        self.start_branch("other", "feat: other")  # checked out; has no record

    def test_the_current_branch_is_used_without_head(self):
        self.assert_denied(self.gate(PR), "no record")

    def test_head_names_the_branch_in_every_form(self):
        for option in ("--head feature", "--head=feature", "-H feature", "-H=feature", "-Hfeature", "--head other --head feature"):
            with self.subTest(option=option):
                self.assert_allowed(self.gate(f"{PR} {option}"))
                self.assert_allowed(self.gate(f"gh pr create {option} --fill"))

    def test_the_owner_prefix_is_dropped_before_the_branch_is_resolved(self):
        # origin/owner:feature does not exist, so an allow is only possible when the prefix is dropped
        for option in ("--head owner:feature", "--head=owner:feature", "-H owner:feature", "-H=owner:feature"):
            with self.subTest(option=option):
                self.assert_allowed(self.gate(f"{PR} {option}"))

    def test_head_beats_the_current_branch_in_both_directions(self):
        self.git("checkout", "feature")
        self.assert_denied(self.gate(f"{PR} --head owner:other"), "no record")
        self.assert_denied(self.gate(f"{PR} --head owner:missing"), "push first")
        self.assert_allowed(self.gate(f"{PR} --head feature"))

    def test_an_empty_or_missing_head_value_has_no_branch_to_check(self):
        for option in ("--head=", "--head", "-H=", "--head owner:"):
            with self.subTest(option=option):
                self.assert_denied(self.gate(f"gh pr create {option}"), "no branch to check")

    def test_a_hidden_second_gh_pr_create_is_not_covered_by_an_allowed_first(self):
        self.assert_allowed(self.gate('gh pr create --head feature; echo ok'))
        self.assert_denied(self.gate('gh pr create --head feature; echo "$(gh pr create)"'), "no branch to check")

    def test_every_gh_pr_create_in_a_command_is_checked(self):
        self.assert_denied(self.gate(f"gh pr create --head feature; gh pr create --head other"), "no record")
        self.assert_allowed(self.gate(f"gh pr create --head feature && gh pr create --head owner:feature"))


class NoBranchTest(GateTestCase):
    def test_a_detached_head_without_head_has_no_branch_to_check(self):
        self.git("checkout", "--detach")
        self.assert_denied(self.gate(PR), "no branch to check")

    def test_a_detached_head_with_head_is_checked_on_the_named_branch(self):
        self.audited_branch("feature")
        self.git("checkout", "--detach")
        self.assert_allowed(self.gate(f"{PR} --head feature"))

    def test_a_working_directory_outside_git_has_no_branch_to_check(self):
        self.assert_denied(self.gate(PR, cwd=self.root), "no branch to check")

    def test_a_working_directory_that_does_not_exist_has_no_branch_to_check(self):
        self.assert_denied(self.gate(PR, cwd=os.path.join(self.root, "gone")), "no branch to check")


class InternalErrorTest(GateTestCase):
    def raw(self, text):
        return self.audit("hook", "pre-tool-use", stdin=text)

    def test_unreadable_stdin_denies_a_matching_command_and_allows_the_rest(self):
        self.assert_denied(self.raw("not json: gh  pr create"), "hook input unreadable")
        self.assert_denied(self.raw('["gh pr create"]'), "hook input unreadable")
        self.assert_allowed(self.raw("not json at all"))
        self.assert_allowed(self.raw(""))
        self.assert_allowed(self.raw("[]"))
        self.assert_allowed(self.raw("\xff\xfe"))

    def test_a_missing_field_allows_a_command_that_does_not_match(self):
        for data in ({}, {"cwd": self.repo}, {"tool_input": {}}, {"tool_input": []}, {"tool_input": {"command": 5}},
                     {"tool_input": {"command": None}}, {"tool_name": "Bash", "tool_input": {"command": ["gh", "pr", "create"]}}):
            with self.subTest(data=data):
                self.assert_allowed(self.audit("hook", "pre-tool-use", stdin=json.dumps(data)))

    def test_a_matching_command_with_a_missing_or_bad_cwd_is_denied(self):
        command = {"tool_input": {"command": PR}}
        for data in (command, dict(command, cwd=None), dict(command, cwd=5), dict(command, cwd="")):
            with self.subTest(data=data):
                self.assert_denied(self.audit("hook", "pre-tool-use", stdin=json.dumps(data)), "hook input unreadable")

    def test_a_missing_tool_name_is_treated_as_bash_and_another_tool_is_ignored(self):
        data = {"tool_input": {"command": PR}, "cwd": self.repo}
        self.assert_denied(self.audit("hook", "pre-tool-use", stdin=json.dumps(data)), "no ")
        self.assert_allowed(self.audit("hook", "pre-tool-use", stdin=json.dumps(dict(data, tool_name="Edit"))))

    def fake_git(self, status):
        fake = os.path.join(self.root, f"fake{status}")
        os.mkdir(fake)
        with open(os.path.join(fake, "git"), "w") as handle:
            handle.write(f"#!/bin/sh\nexit {status}\n")
        os.chmod(os.path.join(fake, "git"), 0o755)
        return {"PATH": fake + os.pathsep + os.environ["PATH"]}

    def test_a_git_call_with_an_unexpected_status_denies_a_match_and_does_not_touch_other_commands(self):
        self.audited_branch()
        env = self.fake_git(3)
        data = lambda command: json.dumps({"tool_input": {"command": command}, "cwd": self.repo})
        self.assert_denied(self.audit("hook", "pre-tool-use", stdin=data(PR), env=env), "hook error")
        self.assert_denied(self.audit("hook", "pre-tool-use", stdin=data(PR + " --head feature"), env=env), "hook error")
        self.assert_allowed(self.audit("hook", "pre-tool-use", stdin=data("ls"), env=env))

    def test_the_statuses_that_git_uses_for_no_result_are_not_errors(self):
        self.audited_branch()
        data = json.dumps({"tool_input": {"command": PR}, "cwd": self.repo})
        for status in (1, 128):
            with self.subTest(status=status):
                self.assert_denied(self.audit("hook", "pre-tool-use", stdin=data, env=self.fake_git(status)), "no branch to check")

    def test_a_git_call_that_cannot_run_is_a_hook_error(self):
        self.audited_branch()
        data = json.dumps({"tool_input": {"command": PR + " --head feature"}, "cwd": self.repo})
        self.assert_denied(self.audit("hook", "pre-tool-use", stdin=data, env={"PATH": "/nonexistent"}), "hook error")
        self.assert_allowed(self.audit("hook", "pre-tool-use", stdin=json.dumps({"tool_input": {"command": "ls"}}), env={"PATH": "/nonexistent"}))

    def test_an_unsafe_runtime_folder_denies_a_match_and_allows_the_rest(self):
        self.audited_branch()
        for name, make in (("wrong mode", lambda: os.chmod(self.runtime, 0o755)),
                           ("symlink", lambda: (os.rename(self.runtime, self.runtime + ".real"), os.symlink(self.runtime + ".real", self.runtime)))):
            with self.subTest(name):
                make()
                self.assert_denied(self.gate(PR), "unsafe runtime folder")
                self.assert_denied(self.gate(f"cd {self.repo} && {PR} --head feature"), "unsafe runtime folder")
                self.assert_allowed(self.gate("ls"))
                self.assert_allowed(self.gate("gh pr view 1"))
                if os.path.islink(self.runtime):
                    os.unlink(self.runtime)
                    os.rename(self.runtime + ".real", self.runtime)
                os.chmod(self.runtime, 0o700)
                self.assert_allowed(self.gate(PR))

    def test_the_gate_allows_by_staying_silent_so_other_hooks_keep_their_say(self):
        self.audited_branch()
        result = self.gate(PR)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        self.assertNotIn(b"allow", result.stdout)

    def test_a_denied_gate_creates_no_record(self):
        self.start_branch("feature", "feat: a")
        self.gate(PR)
        self.assertEqual(self.record_files(), [])


if __name__ == "__main__":
    unittest.main()
