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
CREATE = "orca worktree create --name x"
START_WORDS = "orca orchestration " + "-".join(("worker", "start"))
START = f"{START_WORDS} --task t --agent claude"


def reason(command):
    return RULES.command_reason(command)


def run_hook(payload):
    result = subprocess.run([sys.executable, "-I", HOOK], input=json.dumps(payload), capture_output=True, text=True, check=True)
    return json.loads(result.stdout) if result.stdout else None


class BranchNameTest(unittest.TestCase):
    def test_valid_names_pass(self):
        for name in ("fix/successor-terminal-close", "feat/a", "feature/x1", "bugfix/a-b-2", "hotfix/v1.2.3", "release/v1.0.0",
                     "chore/docs", "research/ci-notes", "fix/branch-probe-573-2"):
            with self.subTest(name=name):
                self.assertIsNone(reason(f"{CREATE} --branch {name}"))

    def test_invalid_names_are_denied(self):
        for name in ("Fix/a", "fix/A", "fix/a_b", "573", "fix/573/x", "fix/a/b", "fix/a-", "fix/-a", "fix/a--b", "fix/a.", "fix/.a",
                     "fix/a..b", "fix/a.-b", "fix", "fix/", "/a", "feat-a", "ai/x", "claude/x", "mquesada02/fix", "fix/a b", "fix/a$X"):
            with self.subTest(name=name):
                self.assertIn("Conventional Branch", reason(f"{CREATE} --branch '{name}'") or "")

    def test_trailing_newline_is_no_name(self):
        self.assertIsNotNone(reason(f"{CREATE} --branch $'fix/a\\n'"))

    def test_missing_branch_is_denied(self):
        for command in (CREATE, f"{CREATE} --repo id:r --json", f"{CREATE} --branch", f"{CREATE} --comment --branch"):
            with self.subTest(command=command):
                self.assertIsNotNone(reason(command))
        self.assertIn("no --branch", reason(CREATE))

    def test_every_branch_is_checked(self):
        self.assertIsNotNone(reason(f"{CREATE} --branch fix/a --branch Bad"))
        self.assertIsNone(reason(f"{CREATE} --branch fix/a --branch chore/b"))

    def test_branch_forms(self):
        self.assertIsNone(reason(f"{CREATE} --branch=fix/a"))
        self.assertIsNotNone(reason(f"{CREATE} --branch=Fix/a"))
        self.assertIsNone(reason("orca worktree create --branch fix/a --name x --prompt '--branch Bad'"))
        self.assertIsNone(reason("orca --environment e worktree create --name x --branch fix/a"))

    def test_every_cli_form(self):
        for program in ("orca", "orca-ide", "orca-dev", "/home/u/.config/orca/linux-orca-cli-shim/orca", "$ORCA_CLI_COMMAND",
                        '"$ORCA_CLI_COMMAND"', "${ORCA_CLI_COMMAND}", "ORCA_X=1 orca", "env orca"):
            with self.subTest(program=program):
                self.assertIsNotNone(reason(f"{program} worktree create --name x"))
                self.assertIsNone(reason(f"{program} worktree create --name x --branch fix/a"))

    def test_other_orca_commands_pass(self):
        for command in ("orca worktree list --json", "orca worktree rm --worktree path:/x", "orca worktree create --help",
                        "orca terminal send --text 'worktree create'", "echo orca worktree create", "ls", ""):
            with self.subTest(command=command):
                self.assertIsNone(reason(command))

    def test_new_worktree_start_is_denied(self):
        for selector in ("new-child", "new-top-level"):
            for form in (f"--worktree {selector}", f"--worktree={selector}"):
                with self.subTest(form=form):
                    self.assertIn("worker-start", reason(f"{START} {form} --name fix/a"))

    def test_existing_worktree_start_passes(self):
        for form in ("--worktree path:/w/x", "--worktree current", "--worktree=branch:fix/a", ""):
            with self.subTest(form=form):
                self.assertIsNone(reason(f"{START} {form}"))
        self.assertIsNone(reason(f"{START_WORDS} --help"))

    def test_wrapped_commands(self):
        for wrapper in ("bash -c '{}'", "sh -c \"{}\"", "eval '{}'", "echo a | {}", "true && {}", "echo $({})", "x=`{}`", "bash -c 'eval \"{}\"'",
                        "echo \"$({})\"", "echo \"`{}`\"", "echo \"$(echo `{}`)\""):
            for command, name in ((CREATE, "missing"), (f"{CREATE} --branch Bad", "bad"), (f"{START} --worktree new-child", "start")):
                with self.subTest(wrapper=wrapper, name=name):
                    self.assertIsNotNone(reason(wrapper.format(command)))
            with self.subTest(wrapper=wrapper, name="valid"):
                self.assertIsNone(reason(wrapper.format(f"{CREATE} --branch fix/a")))

    def test_unreadable_text_is_denied_only_when_it_names_a_gated_command(self):
        self.assertIsNotNone(reason(f"{CREATE} 'unclosed"))
        self.assertIsNone(reason("echo 'unclosed"))

    def test_hook_output(self):
        deny = run_hook({"tool_name": "Bash", "tool_input": {"command": CREATE}})
        self.assertEqual(deny["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("--branch", deny["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIsNone(run_hook({"tool_name": "Bash", "tool_input": {"command": f"{CREATE} --branch fix/a"}}))

    def test_hook_covers_every_session(self):
        for extra in ({}, {"agent_id": "a1"}):
            payload = {"tool_name": "Bash", "tool_input": {"command": CREATE}, **extra}
            self.assertEqual(run_hook(payload)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_hook_ignores_other_input(self):
        for payload in ({"tool_name": "Read", "tool_input": {"command": CREATE}}, {"tool_name": "Bash", "tool_input": {}}, [], "x"):
            with self.subTest(payload=payload):
                self.assertIsNone(run_hook(payload))
        result = subprocess.run([sys.executable, "-I", HOOK], input="not json", capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
