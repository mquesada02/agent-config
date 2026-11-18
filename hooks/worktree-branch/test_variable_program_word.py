"""The branch hook reads a variable program word before a create command and the value of the worktree option of a dispatch (issue 718)."""
import json
import os
import subprocess
import sys
import unittest

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "check_branch_name.py")
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(HOOK))
import check_branch_name as hook  # noqa: E402

RULES = hook.BranchRules(hook.load_reader())
CREATE = "worktree create --name x"
GOOD = f"{CREATE} --branch fix/a"
BAD_NAME = f"{CREATE} --branch Bad/Name"
START_WORDS = "orchestration " + "-".join(("worker", "start"))
START = f"orca {START_WORDS} --task t --agent claude"
WRAPPERS = ("bash -c '{}'", "eval '{}'", "echo $({})", 'echo "`{}`"', "true && {}", "echo a | {}")


def reason(command):
    return RULES.command_reason(command)


def run_hook(command):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    result = subprocess.run([sys.executable, "-I", HOOK], input=json.dumps(payload), capture_output=True, text=True, check=True)
    return json.loads(result.stdout) if result.stdout else None


class VariableProgramWordTest(unittest.TestCase):
    PROGRAMS = ("$X", "${X}", '"$X"', "'$X'", "env $X", "sudo $X", "FOO=1 $X", "$X --repo r", "$X --environment e", "$ORCA_CLI_COMMAND",
                "${ORCA_CLI_COMMAND}", "2>/dev/null $X", "time $X", "$HOME/bin/x")

    def test_missing_branch_is_denied(self):
        for program in self.PROGRAMS:
            with self.subTest(program=program):
                self.assertIn("no --branch", reason(f"{program} {CREATE}") or "")

    def test_bad_name_is_denied(self):
        for program in self.PROGRAMS:
            with self.subTest(program=program):
                self.assertIn("Conventional Branch", reason(f"{program} {BAD_NAME}") or "")

    def test_valid_name_is_allowed(self):
        for program in self.PROGRAMS:
            with self.subTest(program=program):
                self.assertIsNone(reason(f"{program} {GOOD}"))

    def test_help_only_is_allowed(self):
        for program in self.PROGRAMS:
            with self.subTest(program=program):
                self.assertIsNone(reason(f"{program} worktree create --help"))

    def test_options_between_the_words(self):
        self.assertIsNotNone(reason("$X worktree --repo r create --name x"))
        self.assertIsNone(reason("$X worktree --repo r create --name x --branch fix/a"))
        self.assertIsNone(reason("$X --repo r worktree create --name x --branch fix/a"))

    def test_other_commands_after_a_variable_word_are_allowed(self):
        for command in ("$X worktree list --json", "$X terminal send --text 'worktree create'", "$X", "echo $X worktree create", "ls"):
            with self.subTest(command=command):
                self.assertIsNone(reason(command))

    def test_naming_only_command_is_skipped(self):
        self.assertIsNone(reason(f"grep $X {CREATE}"))

    def test_any_segment_with_a_variable_word_before_create_is_denied(self):
        self.assertIsNotNone(reason(f"ls $X {CREATE}"))

    def test_variable_word_before_dispatch_is_not_covered(self):
        self.assertIsNone(reason(f"$X {START_WORDS} --worktree new-child"))

    def test_unreadable_text_after_a_variable_word_is_denied(self):
        self.assertIsNotNone(reason(f"$X {CREATE} 'unclosed"))

    def test_wrapped_forms(self):
        for wrapper in WRAPPERS:
            with self.subTest(wrapper=wrapper, case="missing"):
                self.assertIsNotNone(reason(wrapper.format(f"$X {CREATE}")))
            with self.subTest(wrapper=wrapper, case="bad"):
                self.assertIsNotNone(reason(wrapper.format(f"$X {BAD_NAME}")))
            with self.subTest(wrapper=wrapper, case="valid"):
                self.assertIsNone(reason(wrapper.format(f"$X {GOOD}")))

    def test_hook_run(self):
        deny = run_hook(f"$X {CREATE}")
        self.assertEqual(deny["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("--branch", deny["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIsNone(run_hook(f"$X {GOOD}"))


class WorktreeValueTest(unittest.TestCase):
    BUILT = ("$X", "${X}", '"$X"', "'$X'", "$(echo new-child)", "`echo new-child`", "new-*", "new-chil?", "new-[c]hild", "new-{child}",
             "new-{child,x}", "path:$WT", "path:/tmp/a[1]", "path:/tmp/a*", "branch:$B", "*")
    LITERAL = ("path:/w/x", "current", "branch:fix/a", "~/x", "path:~/x", "")

    def test_built_value_is_denied(self):
        for value in self.BUILT:
            for form in (f"--worktree {value!r}", f"--worktree={value!r}"):
                with self.subTest(form=form):
                    self.assertIn("worker-start", reason(f"{START} {form}") or "")

    def test_built_value_before_the_subcommand_is_denied(self):
        for value in self.BUILT:
            for form in (f"--worktree {value!r}", f"--worktree={value!r}"):
                with self.subTest(form=form):
                    self.assertIn("worker-start", reason(f"orca {form} {START_WORDS} --task t") or "")
                    self.assertIn("worker-start", reason(f"orca --repo r {form} {START_WORDS} --task t") or "")

    def test_reason_tells_to_write_the_literal_path(self):
        self.assertIn("literal", reason(f"{START} --worktree $X"))

    def test_literal_value_is_allowed(self):
        for value in self.LITERAL:
            for form in (f"--worktree {value!r}", f"--worktree={value!r}"):
                with self.subTest(form=form):
                    self.assertIsNone(reason(f"{START} {form}"))
                    self.assertIsNone(reason(f"orca {form} {START_WORDS} --task t"))

    def test_absent_and_valueless_option_is_allowed(self):
        self.assertIsNone(reason(START))
        self.assertIsNone(reason(f"{START} --worktree"))

    def test_new_worktrees_stay_denied(self):
        for value in ("new-child", "new-top-level"):
            for command in (f"{START} --worktree {value}", f"{START} --worktree={value}", f"orca --worktree {value} {START_WORDS} --task t"):
                with self.subTest(command=command):
                    self.assertIn("worker-start", reason(command) or "")

    def test_a_value_of_another_option_is_no_worktree_value(self):
        self.assertIsNone(reason(f"{START} --name '--worktree $X'"))
        self.assertIsNone(reason(f"{START} --worktree path:/w/x --comment $X"))

    def test_redirection_word_before_the_program(self):
        self.assertIsNotNone(reason(f"2>/dev/null {START} --worktree $X"))

    def test_cli_variable_gets_the_full_rule(self):
        self.assertIsNotNone(reason(f"$ORCA_CLI_COMMAND {START_WORDS} --worktree $X"))
        self.assertIsNone(reason(f"$ORCA_CLI_COMMAND {START_WORDS} --worktree path:/w/x"))

    def test_wrapped_forms(self):
        for wrapper in WRAPPERS:
            with self.subTest(wrapper=wrapper, case="built"):
                self.assertIsNotNone(reason(wrapper.format(f"{START} --worktree $X")))
            with self.subTest(wrapper=wrapper, case="literal"):
                self.assertIsNone(reason(wrapper.format(f"{START} --worktree path:/w/x")))

    def test_hook_run(self):
        deny = run_hook(f"{START} --worktree $X")
        self.assertEqual(deny["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIsNone(run_hook(f"{START} --worktree path:/w/x"))


if __name__ == "__main__":
    unittest.main()
