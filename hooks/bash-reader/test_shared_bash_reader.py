import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS = os.path.dirname(HERE)
SHARED = os.path.join(HERE, "bash_reader.py")
AUDIT = os.path.join(HOOKS, "workflow-audit", "audit")
BRANCH_HOOK = os.path.join(HOOKS, "worktree-branch", "check_branch_name.py")
SUBAGENT_HOOK = os.path.join(HOOKS, "subagent-readonly", "block_subagent_writes.py")
PUSH = "git " + "push"


def load_shared():
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec = importlib.util.spec_from_file_location("bash_reader_for_test", SHARED)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = previous


shared = load_shared()
audit = shared.load_audit(AUDIT, "audit_for_shared_reader_test")


class WordRules:
    """A minimal hook: it denies the word `bad`, and it records what the walk gives it."""

    def __init__(self, unreadable=None):
        self.walk = shared.Walk(audit, self)
        self.unreadable = unreadable
        self.calls = []

    def first_word_reason(self, words):
        return "first word" if words[0] == "badfirst" else None

    def word_reason(self, words, index, items, position, depth):
        self.calls.append((words[index], position, depth))
        return "bad word" if words[index] == "bad" else None

    def depth_reason(self):
        return "too deep"

    def unreadable_reason(self, command, depth, error):
        return f"unreadable: {type(error).__name__}"

    def substitution_bodies(self, word):
        return shared.substitution_bodies(audit, word)

    def command_reason(self, command, depth=0):
        return self.walk.command_reason(command, depth)


class SubstitutionBodiesTest(unittest.TestCase):
    def bodies(self, word):
        return shared.substitution_bodies(audit, word)

    def test_a_word_with_no_substitution_has_no_body(self):
        self.assertEqual(self.bodies("plain"), [])

    def test_a_dollar_paren_body(self):
        self.assertEqual(self.bodies("a$(echo x)b"), ["echo x"])

    def test_nested_dollar_paren_is_one_body(self):
        self.assertEqual(self.bodies("$(echo $(ls))"), ["echo $(ls)"])

    def test_several_bodies(self):
        self.assertEqual(self.bodies("$(a)-$(b)"), ["a", "b"])

    def test_a_quoted_dollar_paren_does_not_raise(self):
        self.assertEqual(self.bodies("$(echo '$(')"), ["echo '$('"])

    def test_a_backtick_body_is_read(self):
        self.assertEqual(self.bodies("x`ls`y"), ["ls"])

    def test_an_unclosed_form_raises(self):
        for word in ("$(ls", "`ls"):
            with self.subTest(word=word):
                with self.assertRaises(ValueError):
                    self.bodies(word)


class CommandScriptTest(unittest.TestCase):
    def test_the_word_after_the_c_option(self):
        self.assertEqual(shared.command_script(audit, ["-c", "ls"]), "ls")
        self.assertEqual(shared.command_script(audit, ["-lc", "ls", "arg"]), "ls")

    def test_a_shell_without_a_c_option_has_no_script(self):
        for words in ([], ["script.sh"], ["-s"], ["-c"]):
            with self.subTest(words=words):
                self.assertIsNone(shared.command_script(audit, words))


class WalkTest(unittest.TestCase):
    def test_a_denied_word_is_found_in_every_wrapped_form(self):
        rules = WordRules()
        for command in ("bad", "ls && bad", "echo a | bad", "bash -c 'bad'", "eval bad", "echo $(bad)", "echo `bad`", "x=\"$(bad)\"",
                        "bash -c 'eval \"bad\"'"):
            with self.subTest(command=command):
                self.assertEqual(rules.command_reason(command), "bad word")

    def test_a_clean_command_has_no_reason(self):
        self.assertIsNone(WordRules().command_reason("ls -l && echo hi | cat"))

    def test_the_first_word_rule_runs_before_the_naming_only_skip(self):
        rules = WordRules()
        self.assertEqual(rules.command_reason("badfirst"), "first word")
        self.assertIsNone(rules.command_reason("echo bad"))

    def test_the_naming_only_skip_runs_before_the_word_loop(self):
        rules = WordRules()
        rules.command_reason("echo bad")
        self.assertEqual(rules.calls, [])

    def test_the_word_rule_gets_the_position_of_the_segment_and_the_depth(self):
        rules = WordRules()
        rules.command_reason("ls && bash -c 'cat'")
        self.assertIn(("ls", 0, 0), rules.calls)
        self.assertIn(("cat", 0, 1), rules.calls)
        positions = {position for word, position, depth in rules.calls if word == "bash"}
        self.assertEqual(len(positions), 1)
        self.assertGreater(positions.pop(), 0)

    def test_the_depth_guard(self):
        rules = WordRules()
        self.assertEqual(rules.command_reason("bad", audit.MAX_SHELL_DEPTH + 1), "too deep")
        self.assertEqual(rules.command_reason("bad", audit.MAX_SHELL_DEPTH), "bad word")

    def test_a_shell_without_a_c_option_is_not_read(self):
        self.assertIsNone(WordRules().command_reason("bash script.sh"))

    def test_the_wrapped_form_gives_the_hook_failure_reason(self):
        self.assertEqual(WordRules().command_reason("echo 'unclosed"), "unreadable: ValueError")

    def test_the_raising_form_raises(self):
        with self.assertRaises(ValueError):
            WordRules().walk.read_reason("echo 'unclosed", 0)


class LoadAuditTest(unittest.TestCase):
    def test_the_module_gets_the_name_of_the_caller_and_no_bytecode_is_written(self):
        before = sys.dont_write_bytecode
        module = shared.load_audit(AUDIT, "audit_with_another_name")
        self.assertEqual(module.__name__, "audit_with_another_name")
        self.assertEqual(sys.dont_write_bytecode, before)
        self.assertTrue(hasattr(module, "split_command"))

    def test_the_audit_helpers_keep_their_arguments_and_results(self):
        self.assertEqual(audit._paren_end("abc) d", 0), 4)
        self.assertEqual(audit._join_as_bash("ls \\\n  -l"), "ls   -l")


class HookSourceTest(unittest.TestCase):
    """Story 4: the reader code lives in the shared module only."""

    NAMES = ("SourceFileLoader", "SHELL_COMMAND_OPTION", "strip_data_heredocs", "split_command")

    def read(self, path):
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def test_neither_hook_holds_the_reader_code(self):
        for hook in (BRANCH_HOOK, SUBAGENT_HOOK):
            source = self.read(hook)
            for name in self.NAMES:
                with self.subTest(hook=os.path.basename(hook), name=name):
                    self.assertNotIn(name, source)

    def test_the_shared_module_holds_it(self):
        source = self.read(SHARED)
        for name in self.NAMES:
            with self.subTest(name=name):
                self.assertIn(name, source)


class LoadFailureTest(unittest.TestCase):
    """A hook that cannot load the shared module denies. The test runs the hooks from a copy, never in the checkout."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        for folder, name in (("worktree-branch", "check_branch_name.py"), ("subagent-readonly", "block_subagent_writes.py"),
                             ("workflow-audit", "audit")):
            os.makedirs(os.path.join(self.root, "hooks", folder))
            shutil.copy(os.path.join(HOOKS, folder, name), os.path.join(self.root, "hooks", folder, name))
        os.makedirs(os.path.join(self.root, "hooks", "bash-reader"))  # the shared file is missing

    def run_hook(self, folder, name, command, **extra):
        data = {"tool_name": "Bash", "tool_input": {"command": command}, **extra}
        result = subprocess.run([sys.executable, "-I", os.path.join(self.root, "hooks", folder, name)], input=json.dumps(data),
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else None

    def test_the_branch_hook_denies_a_command_that_names_a_gated_command(self):
        output = self.run_hook("worktree-branch", "check_branch_name.py", "orca worktree create --name x --branch fix/a")
        self.assertEqual(output["permissionDecision"], "deny")

    def test_the_branch_hook_passes_a_command_that_names_none(self):
        self.assertIsNone(self.run_hook("worktree-branch", "check_branch_name.py", "ls -l"))

    def test_the_subagent_hook_denies_every_subagent_command(self):
        for command in ("ls -l", PUSH):
            with self.subTest(command=command):
                output = self.run_hook("subagent-readonly", "block_subagent_writes.py", command, agent_id="a1")
                self.assertEqual(output["permissionDecision"], "deny")

    def test_the_subagent_hook_passes_a_call_with_no_agent_id(self):
        self.assertIsNone(self.run_hook("subagent-readonly", "block_subagent_writes.py", "ls -l"))


if __name__ == "__main__":
    unittest.main()
