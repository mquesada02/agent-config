import os
import shlex
import unittest

from test_dispatch_gate import WS, UNCHECKED_DISPATCH, DispatchGateCase


class ResearchWorktreeCase(DispatchGateCase):
    def worktree(self, branch, name=None):
        """A linked worktree on a new branch, off the main checkout. Returns its path."""
        path = os.path.join(self.root, name or branch.replace("/", "-"))
        self.git("worktree", "add", "-b", branch, path, "main", cwd=self.main)
        return path

    def start(self, path, flag="--worktree path:"):
        return f"{WS} {flag}{path}"

    def assert_no_record(self, command):
        self.assert_denied(self.gate(command), "no pre-dispatch record")


class ResearchExemptionTest(ResearchWorktreeCase):
    def test_a_research_worktree_is_allowed_with_no_record(self):
        path = self.worktree("research/x")
        for command in (self.start(path), self.start(path, "--worktree=path:"), f"{WS} --worktree path:{path} --task t2",
                        f"{WS} --comment c --worktree path:{path}", f"{self.start(path)} # c"):
            with self.subTest(command=command):
                result = self.gate(command)
                self.assert_allowed(result)
                self.assertEqual(result.stderr, b"")

    def test_the_local_options_of_a_dispatch_are_allowed_next_to_a_research_worktree(self):
        path = self.worktree("research/x")
        for options in ("--spec s", "--spec-file f", "--task-title t", "--deps d", "--model m", "--effort high", "--terminal t", "--display-name n",
                        "--setup run", "--name n", "--timeout-ms 1000", "--keep-open", "--json", "--comment c --model m"):
            with self.subTest(options=options):
                self.assert_allowed(self.gate(f"{WS} {options} --worktree path:{path}"))

    def test_a_research_worktree_is_allowed_in_an_unsafe_runtime_folder_and_with_no_session_id(self):
        path = self.worktree("research/x")
        os.makedirs(self.runtime, 0o700, exist_ok=True)
        os.chmod(self.runtime, 0o755)
        self.assert_allowed(self.gate(self.start(path)))
        self.assert_allowed(self.hook(tool_input={"command": self.start(path)}, cwd=self.repo))

    def test_a_dotted_research_name_is_allowed(self):
        self.assert_allowed(self.gate(self.start(self.worktree("research/agent-v1.2"))))

    def test_a_worktree_on_another_branch_is_denied(self):
        for branch in ("feat/x", "fix/research", "research-x", "researchx/y", "research/a/b", "research/Bad"):
            with self.subTest(branch=branch):
                self.assert_no_record(self.start(self.worktree(branch)))

    def test_a_research_worktree_with_a_passing_record_is_still_allowed(self):
        self.pd_record()
        self.assert_allowed(self.gate(self.start(self.worktree("research/x"))))


class ResearchFailClosedTest(ResearchWorktreeCase):
    def test_a_path_whose_branch_cannot_be_read_is_denied(self):
        detached = self.worktree("research/x")
        self.git("checkout", "--detach", cwd=detached)
        for path in (detached, os.path.join(self.root, "missing"), self.root):
            with self.subTest(path=path):
                self.assert_no_record(self.start(path))

    def test_a_folder_inside_a_research_worktree_is_denied(self):
        path = self.worktree("research/x")
        os.mkdir(os.path.join(path, "sub"))
        self.assert_no_record(self.start(os.path.join(path, "sub")))

    def test_a_link_to_a_research_worktree_is_denied_unless_it_is_the_top_folder(self):
        path = self.worktree("research/x")
        link = os.path.join(self.root, "link")
        os.symlink(path, link)
        self.assert_allowed(self.gate(self.start(link)))  # the same folder: realpath equal
        os.mkdir(os.path.join(path, "sub"))
        os.symlink(os.path.join(path, "sub"), os.path.join(self.root, "link-sub"))
        self.assert_no_record(self.start(os.path.join(self.root, "link-sub")))

    def test_a_relative_or_expanded_path_is_denied(self):
        path = self.worktree("research/x")
        relative = os.path.relpath(path, self.repo)
        for flag_value in (relative, "~/x", "$HOME/x", f"{path}$X", "`pwd`", "", "/"):
            with self.subTest(path=flag_value):
                self.assert_no_record(f"{WS} --worktree path:{flag_value}")

    def test_a_worktree_selector_that_is_no_path_is_denied(self):
        path = self.worktree("research/x")
        for command in (f"{WS} --worktree {path}", f"{WS} --worktree id:{path}", f"{WS} --worktree new-child", f"{WS} --worktree",
                        f"{WS} --worktree=", WS, f"{WS} --Worktree path:{path}", f"{WS} --worktree-x path:{path}"):
            with self.subTest(command=command):
                self.assert_no_record(command)

    def test_two_worktree_options_are_denied(self):
        research, other = self.worktree("research/x"), self.worktree("feat/x")
        for command in (f"{WS} --worktree path:{research} --worktree path:{other}", f"{WS} --worktree path:{other} --worktree path:{research}",
                        f"{WS} --worktree path:{research} --worktree=path:{research}"):
            with self.subTest(command=command):
                self.assert_no_record(command)

    def test_a_worktree_option_that_is_the_value_of_another_option_is_denied(self):
        path = self.worktree("research/x")
        self.assert_no_record(f"{WS} --comment --worktree path:{path}")
        self.assert_no_record(f"{WS} --task --worktree path:{path}")

    def test_a_form_with_an_option_before_the_command_is_denied(self):
        path = self.worktree("research/x")
        for command in (f"orca --json orchestration worker-start --worktree path:{path}",
                        f"orca orchestration --json worker-start --worktree path:{path}"):
            with self.subTest(command=command):
                self.assert_no_record(command)

    def test_a_research_dispatch_next_to_another_dispatch_is_denied(self):
        path, other = self.worktree("research/x"), self.worktree("feat/x")
        self.assert_no_record(f"{self.start(path)} && {self.start(other)}")
        self.assert_no_record(f"{self.start(other)} ; {self.start(path)}")
        self.assert_no_record(f"{self.start(path)} && {WS}")

    def test_a_command_that_can_change_the_branch_after_the_check_is_denied(self):
        path = self.worktree("research/x")
        switch = f"git -C {path} switch -q -c feat/y"
        for command in (f'{self.start(path)} --task "$({switch})"', f"{self.start(path)} --task `{switch}`", f"{self.start(path)} --task $X",
                        f"X=$({switch}) {self.start(path)}", f"{switch} && {self.start(path)}", f"{switch}; {self.start(path)}",
                        f"{self.start(path)} && {switch}", f"{self.start(path)} <(true)"):
            with self.subTest(command=command):
                self.assert_no_record(command)

    def test_an_option_that_can_change_where_the_worker_runs_is_denied(self):
        # the local branch of the path says nothing about a remote host or another repo, run or parent
        path = self.worktree("research/x")
        for option in ("--on srv", "--on=srv", "--repo path:/x", "--environment e", "--pairing-code c", "--run r", "--parent t0",
                       "--from t0", "--base-branch main", "--unknown", "--unknown v", "--spec-x v", "-x", "--task=t", "--retry-request"):
            for command in (f"{WS} {option} --worktree path:{path}", f"{WS} --worktree path:{path} {option}"):
                with self.subTest(command=command):
                    self.assert_no_record(command)

    def test_a_path_that_the_shell_can_expand_is_denied(self):
        # shlex.quote keeps the word literal, so only the character check can deny it: a bash expansion of the unquoted word would differ
        for number, name in enumerate(("w{a,b}", "w*", "w?", "w[ab]", "w'x'", 'w"x"', "w\\x", "w x", "w~x")):
            with self.subTest(name=name):
                path = self.worktree(f"research/x{number}", name)
                self.assert_no_record(f"{WS} --worktree {shlex.quote('path:' + path)}")
        path = self.worktree("research/y", "plain-name_1.2")
        self.assert_allowed(self.gate(f"{WS} --worktree {shlex.quote('path:' + path)}"))

    def test_an_env_prefix_before_the_dispatch_is_denied(self):
        path = self.worktree("research/x")
        for prefix in ("FOO=1", "GIT_DIR=/nowhere", "env", "env FOO=1"):
            with self.subTest(prefix=prefix):
                self.assert_no_record(f"{prefix} {self.start(path)}")

    def test_a_worktree_option_after_the_end_of_the_options_is_denied(self):
        path = self.worktree("research/x")
        for command in (f"{WS} -- --worktree path:{path}", f"{WS} --worktree path:{path} -- --task t", f"{WS} --task t -- --worktree=path:{path}"):
            with self.subTest(command=command):
                self.assert_no_record(command)

    def test_a_wrapped_form_is_denied(self):
        path = self.worktree("research/x")
        command = self.start(path)
        for wrapped in (f'bash -c "{command}"', f"bash -c '{command}'", f'eval "{command}"', f'sh -c "{command}"'):
            with self.subTest(command=wrapped):
                self.assert_denied(self.gate(wrapped), UNCHECKED_DISPATCH)

    def test_a_wrapped_form_next_to_a_research_dispatch_is_denied(self):
        path = self.worktree("research/x")
        self.assert_no_record(f'{self.start(path)}; bash -c "{self.start(path)}"')

    def test_an_unparsable_command_is_denied(self):
        path = self.worktree("research/x")
        self.assert_denied(self.gate(f'{self.start(path)} --task "unbalanced'), "no pre-dispatch record")


if __name__ == "__main__":
    unittest.main()
