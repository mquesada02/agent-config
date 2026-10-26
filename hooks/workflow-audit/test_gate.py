import json
import os
import unittest

from audit_support import AuditCase

PR = "gh pr create --title t --body b"
UNCHECKED = "unchecked command form: run gh pr create as a plain command"


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
        os.makedirs(self.runtime, 0o700, exist_ok=True)
        with open(os.path.join(self.runtime, "a" * 40 + ".json"), "w") as handle:
            handle.write("{broken")
        with open(os.path.join(self.runtime, "b" * 40 + ".json"), "w") as handle:  # sha field differs from the file name
            json.dump({"sha": "c" * 40, "remote_url": self.origin, "branch": "feature", "result": "pass"}, handle)
        with open(os.path.join(self.runtime, "sessions.jsonl"), "a") as handle:
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
            "if false; then true; elif gh pr create; then true; fi",
            "until gh pr create; do true; done",
            "if false; then true; else gh pr create; fi",
            "while true; do gh pr create; done",
        ):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command, cwd=self.repo), "no record")

    def test_gh_pr_create_inside_a_command_substitution_is_denied(self):
        # Bodies of quoted substitutions are not parsed: more occurrences of the text than matching segments, plus a substitution marker, fails closed.
        for command in ('echo "`gh pr create`"', 'echo "$(gh pr create)"', 'echo "$(gh  pr   create)"',
                        'echo "a $(true) b" "$(gh pr create)"', "echo '`gh pr create`'"):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), "no branch to check")
        for command in ("echo $(gh pr create)", "echo `gh pr create`", "x=`gh pr create`"):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), "no record")  # an unquoted substitution is parsed and checked as a command

    def test_substitutions_without_the_text_are_allowed(self):
        for command in ("echo $(date)", 'echo "$(date)"', "echo `date`", "git commit -m \"$(cat <<'EOF'\nfeat: x\nEOF\n)\""):
            with self.subTest(command=command):
                self.assert_allowed(self.gate(command))

    def test_commands_that_do_not_run_it_are_allowed(self):
        for command in (
            "gh pr view 1",
            "gh issue create",
            "gh pr list",
            "ls",
            "",
            "gh pr",
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
        for cd in ("cd", "cd -", "cd -P .", "cd $HOME", "cd `pwd`", "cd *", "cd ?", "cd [a]", "cd a b", "cd '$x'"):
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

    def test_a_cd_after_assignments_with_substitutions_stays_in_its_pipeline_subshell(self):
        for separator in ("|", "&"):
            for assignments in ("X=$(true)", "X=$(true) Y=$(true)", "X=`true`"):
                command = f"{assignments} cd {self.repo} {separator} {PR}"
                with self.subTest(command=command):
                    self.assert_denied(self.gate(command, cwd=self.other), "no branch to check")
                    self.assert_allowed(self.gate(command.replace(self.repo, self.other), cwd=self.repo))

    def test_a_substitution_body_runs_before_the_cd_of_its_own_segment(self):
        # bash expands the assignment before the cd runs, so the body is checked where the command started
        self.assert_denied(self.gate(f"X=$(gh pr create) cd {self.repo}", cwd=self.other), "no branch to check: not in a git repository")
        self.assert_allowed(self.gate(f"X=$(gh pr create) cd {self.other}", cwd=self.repo))
        self.assert_allowed(self.gate(f"X=$(true) cd {self.repo} && {PR}", cwd=self.other))

    def test_a_cd_inside_the_body_does_not_replace_the_cd_of_the_outer_segment(self):
        self.assert_denied(self.gate(f"X=$(cd /tmp; true) cd {self.other} && {PR}", cwd=self.repo), "no branch to check")
        self.assert_allowed(self.gate(f"X=$(cd /tmp; true) cd {self.repo} && {PR}", cwd=self.other))
        self.assert_allowed(self.gate(f"X=`cd /tmp; true` cd {self.repo} && {PR}", cwd=self.other))

    def test_a_cd_in_a_substitution_body_does_not_move_the_outer_directory(self):
        self.assert_allowed(self.gate(f"echo $(cd {self.other}; true) && {PR}", cwd=self.repo))
        self.assert_allowed(self.gate(f"echo `cd {self.other}; true` && {PR}", cwd=self.repo))
        self.assert_denied(self.gate(f"echo $(cd {self.repo}; true) && {PR}", cwd=self.other), "no branch to check")

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


class UncheckedFormTest(GateTestCase):
    def test_a_form_that_the_parser_cannot_resolve_is_denied_even_with_a_passing_record(self):
        self.audited_branch()
        for command in ('bash -c "gh pr create"', "sh -c 'gh pr create'", "eval gh pr create", "sudo gh pr create", "nohup gh pr create",
                        "timeout 60 gh pr create", "nice gh pr create", "echo x | xargs gh pr create"):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), UNCHECKED)

    def test_a_plain_command_is_still_allowed_with_a_passing_record(self):
        self.audited_branch()
        self.assert_allowed(self.gate(PR))
        self.assert_allowed(self.gate(f"cd {self.repo} && {PR}"))
        self.assert_allowed(self.gate("ls"))

    def test_a_parsed_match_does_not_hide_a_second_unresolved_occurrence(self):
        self.audited_branch()
        for command in ('gh pr create; bash -c "gh pr create"', 'bash -c "gh pr create"; gh pr create', "gh pr create --title 'gh pr create'"):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), UNCHECKED)

    def test_a_command_that_only_mentions_the_text_is_denied(self):
        # An accepted false positive: the gate cannot tell a mention from a run.
        self.audited_branch()
        for command in ('echo "gh pr create"', "echo gh pr create", "git commit -m 'gh pr create'", "# gh pr create", "echo then gh pr create",
                        "if true; then echo gh pr create; fi"):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), UNCHECKED)

    def test_a_newline_inside_the_text_is_denied(self):
        self.audited_branch()
        self.assert_denied(self.gate("gh pr\ncreate"), UNCHECKED)

    def test_the_forms_are_denied_without_a_record_too(self):
        self.start_branch("feature", "feat: a")
        self.assert_denied(self.gate('bash -c "gh pr create"'), UNCHECKED)

    def test_a_command_that_an_existing_check_denies_keeps_its_reason(self):
        self.audited_branch()
        for command in ('echo "$(gh pr create)"', 'gh pr create --title "unbalanced', 'bash -c "gh pr create" "unbalanced'):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), "no branch to check")

    def test_a_continued_line_is_seen_when_the_command_cannot_be_parsed(self):
        self.audited_branch()
        self.assert_denied(self.gate('gh pr \\\ncreate "unbalanced'), "no branch to check: the command cannot be parsed")

    def test_a_record_check_denial_keeps_its_reason_before_the_new_check(self):
        self.start_branch("feature", "feat: a")  # no record
        self.assert_denied(self.gate('gh pr create; bash -c "gh pr create"'), "no record")

    def test_an_unsafe_runtime_folder_keeps_its_reason_only_for_a_command_with_a_record_check(self):
        self.audited_branch()
        os.chmod(self.runtime, 0o755)
        self.assert_denied(self.gate('gh pr create; bash -c "gh pr create"'), "unsafe runtime folder")
        self.assert_denied(self.gate('bash -c "gh pr create"'), UNCHECKED)
        self.assert_denied(self.gate('echo "gh pr create"'), UNCHECKED)


class HelpTest(GateTestCase):
    def test_a_help_only_pr_create_is_allowed_without_a_record(self):
        self.start_branch("feature", "feat: a")  # no record
        for command in ("gh pr create --help", "gh pr create -h", f"cd {self.repo} && gh pr create --help",
                        "gh pr create --help; echo $(date)"):
            with self.subTest(command=command):
                self.assert_allowed(self.gate(command))

    def test_help_with_another_option_is_denied(self):
        self.start_branch("feature", "feat: a")
        for command in ("gh pr create --help --title t", "gh pr create --title t --help", "gh pr create --help=x"):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), "no record")

    def test_a_help_next_to_a_pr_create_is_denied(self):
        self.start_branch("feature", "feat: a")
        self.assert_denied(self.gate("gh pr create --help && gh pr create"), "no record")

    def test_a_wrapped_help_is_denied(self):
        self.start_branch("feature", "feat: a")
        self.assert_denied(self.gate('bash -c "gh pr create --help"'), UNCHECKED)
        self.assert_denied(self.gate('echo "$(gh pr create --help)"'), "no branch to check")


class ContinuedLineTest(GateTestCase):
    def two_branches(self):
        """`one` has a passing record, `two` is pushed without one; `one` is checked out."""
        self.audited_branch("one")
        self.start_branch("two", "feat: b")
        self.git("checkout", "one")

    def test_a_head_flag_on_a_continued_line_is_read(self):
        self.two_branches()
        self.assert_denied(self.gate("gh pr create \\\n --head two"), "no record")
        self.git("checkout", "two")
        self.assert_allowed(self.gate("gh pr create \\\n --head one"))

    def test_a_hash_right_after_a_substitution_is_a_word_part_so_the_line_joins(self):
        self.two_branches()
        self.git("checkout", "two")  # joined: --head one is read and allows; not joined: checked on two, no record
        for command in ("gh pr create $(true)# \\\n --head one", "gh pr create `true`# \\\n --head one"):
            with self.subTest(command=command):
                self.assert_allowed(self.gate(command))

    def test_a_hash_right_after_an_opening_backtick_starts_a_comment(self):
        self.two_branches()
        self.git("checkout", "two")  # the --head is inside the backtick body, so the outer command is checked on two
        self.assert_denied(self.gate("gh pr create `# x \\\n --head one`"), "no record")

    def test_a_plain_continued_command_with_a_passing_record_is_allowed(self):
        self.audited_branch()
        self.assert_allowed(self.gate("gh pr create --title t \\\n --body b"))
        self.assert_allowed(self.gate("gh pr create \\\n --title t \\\n --body b"))
        self.assert_allowed(self.gate(f"cd {self.repo} \\\n && {PR}"))

    def test_a_continued_gated_text_is_checked_as_the_plain_command(self):
        self.start_branch("feature", "feat: a")
        self.assert_denied(self.gate("gh pr \\\ncreate"), "no record")
        self.assertEqual(self.record().returncode, 0)
        self.assert_allowed(self.gate("gh pr \\\ncreate"))

    def test_continuations_at_the_start_and_in_a_row_are_joined(self):
        self.two_branches()
        self.git("checkout", "two")
        self.assert_allowed(self.gate("\\\ngh pr create \\\n\\\n --head one"))
        self.assert_allowed(self.gate("gh pr create \\\\\\\n --head one"))  # three backslashes: one joins, two stay

    def test_a_continuation_in_a_comment_is_not_joined(self):
        # bash ends a comment at the newline, so `--head one` is another command and the PR goes to `two`.
        self.two_branches()
        self.assert_denied(self.gate("gh pr create --head two # \\\n --head one"), "no record")

    def test_a_comment_after_a_joined_continuation_is_not_joined(self):
        self.two_branches()
        self.assert_denied(self.gate("gh pr create --head two \\\n# \\\n --head one"), "no record")

    def test_a_continuation_in_double_quotes_is_joined(self):
        self.two_branches()
        self.git("checkout", "two")
        self.assert_allowed(self.gate('gh pr create --title "a \\\n b" --head one'))

    def test_a_continuation_in_single_quotes_still_counts_for_a_nested_shell(self):
        self.audited_branch()
        self.assert_denied(self.gate("bash -c 'gh pr \\\ncreate'"), UNCHECKED)

    def test_an_escaped_backslash_before_the_newline_is_not_joined(self):
        self.two_branches()
        self.assert_allowed(self.gate("gh pr create \\\\\n --head two"))  # bash runs `gh pr create \` on `one`, then `--head two` as another command


class QuotedTextTest(GateTestCase):
    def test_a_quoted_gated_command_does_not_offset_an_unresolved_one(self):
        self.audited_branch()
        for command in ('gh pr "create"; bash -c "gh pr create"', "gh 'pr' create; bash -c 'gh pr create'", 'bash -c "gh pr create"; gh p"r" create'):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), UNCHECKED)

    def test_separate_quoted_words_that_spell_the_text_are_denied(self):
        # Fails closed: removing the quotes makes `gh pr create` out of words that the parser does not match.
        self.audited_branch()
        self.assert_denied(self.gate('echo "gh" "pr" create'), UNCHECKED)

    def test_a_lone_quoted_gated_command_is_checked_as_a_plain_command(self):
        self.audited_branch()
        self.assert_allowed(self.gate('gh pr "create" --title t'))
        self.assert_allowed(self.gate('gh pr create; gh pr "create"'))


class SubstitutionHeadTest(GateTestCase):
    """A substitution stays in its word, so the words after it are in the same segment and the last --head decides."""

    def setUp(self):
        super().setUp()
        self.start_branch("one", "feat: a")  # pushed, no record
        self.audited_branch("two")  # pushed, a passing record, checked out

    def test_the_last_head_after_a_substitution_decides(self):
        for substitution in ("$(true)", "`true`", "$((1+2))"):
            with self.subTest(substitution=substitution):
                self.assert_allowed(self.gate(f"gh pr create --head one {substitution} --head two"))
                self.assert_denied(self.gate(f"gh pr create --head two {substitution} --head one"), "no record")

    def test_a_head_value_that_holds_a_substitution_or_a_variable_has_no_branch_to_check(self):
        for option in ("--head $(echo two)", "--head `echo two`", "--head $B", "--head=$B", "-H $B", "--head '$B'", "-H$B", "-H=$B", "--head=x$(true)"):
            with self.subTest(option=option):
                self.assert_denied(self.gate(f"gh pr create {option}"), "no branch to check")

    def test_an_earlier_head_with_a_variable_is_ignored(self):
        self.assert_allowed(self.gate("gh pr create --head $B --head two"))
        self.assert_denied(self.gate("gh pr create --head two --head $B"), "no branch to check")


class NestedCommandTest(GateTestCase):
    """The body of an unquoted substitution is read as a command."""

    def test_a_gated_command_in_an_unquoted_substitution_is_checked(self):
        self.start_branch("feature", "feat: a")  # no record
        for command in ("echo $(gh pr create)", "echo `gh pr create`", "x=`gh pr create`", "echo $(true) $(gh pr create)", "echo `true` `gh pr create`",
                        "echo $(echo $(gh pr create))", "echo `echo \\`gh pr create\\``", "echo $((gh pr create))",
                        "echo <(true) && gh pr create"):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), "no record")

    def test_a_gated_command_in_a_quoted_substitution_cannot_be_followed(self):
        self.start_branch("feature", "feat: a")
        for command in ('echo "$(gh pr create)"', 'echo "`gh pr create`"'):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), "no branch to check: gh pr create inside a command substitution cannot be followed")

    def test_a_checked_nested_command_is_allowed_with_a_record(self):
        self.audited_branch()
        self.assert_allowed(self.gate("echo `gh pr create`"))
        self.assert_allowed(self.gate("echo $(gh pr create)"))

    def test_arithmetic_is_read_like_a_substitution(self):
        self.audited_branch()
        self.assert_allowed(self.gate("echo $((1+2))"))
        self.assert_allowed(self.gate("echo `echo \\`true\\``"))

    def test_an_unbalanced_substitution_with_gated_text_is_denied(self):
        self.audited_branch()
        for command in ("gh pr create $(true", "gh pr create `unclosed", "echo $(gh pr create", "gh pr create $(echo \"x)"):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), "no branch to check: the command cannot be parsed")

    def test_an_unbalanced_substitution_without_gated_text_is_allowed(self):
        self.assert_allowed(self.gate("echo $(true"))
        self.assert_allowed(self.gate("echo `unclosed"))

    def test_a_substitution_in_single_quotes_is_text(self):
        self.audited_branch()
        self.assert_allowed(self.gate("echo '$(true' && gh pr create --title t"))


if __name__ == "__main__":
    unittest.main()
