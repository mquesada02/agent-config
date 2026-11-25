import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

FOLDER = os.path.dirname(os.path.abspath(__file__))
HOOKS = os.path.dirname(FOLDER)
HOOK = os.path.join(FOLDER, "deny_recursive_delete.py")
S9_TESTS = os.path.join(HOOKS, "workflow-audit", "test_s7_s9.py")
sys.path.insert(0, FOLDER)
sys.dont_write_bytecode = True
import deny_recursive_delete as hook  # noqa: E402

# Every recursive-delete form that S9 reports, each with its own wrapper or quoting.
DENIED = (
    "rm -rf x", "rm -r x", "rm -R x", "rm --recursive x", "rm --recurs x", "rm -fr x", "rm -r -- x", "/bin/rm -rf x", "\\rm -rf x",
    "sudo rm -rf x", "xargs rm -rf", "timeout 5 rm -rf x", "nohup rm -rf x", "env rm -rf x", "command rm -rf x",
    "bash -c \"rm -rf x\"", "sh -c 'rm -rf x'", "eval 'rm -rf x'",
    "find . -name t -exec rm -rf {} +",
    "echo \"$(rm -rf x)\"", "echo $(rm -rf x)", "echo `rm -rf x`", "echo \"`rm -rf x`\"",
    "cd x && rm -rf y", "ls | xargs rm -r",
    "git rm -rf x", "git rm -r -f x", "git rm -r --force x",
    "find . -name t -delete", "find . -name t -delete 2>/dev/null", "find . -name t 2>/dev/null -delete", "find . -delete > out.txt",
    "find . -type f -name '*.tmp' -print -delete", "find x -exec chmod 644 {} \\; -delete", "find . \\( -name a -o -name b \\) -delete",
    "cd x && find . -delete",
    "rm -{r,f} d", "rm -r{,f} d", "$X -rf d", "git $X -r -f d", "rm a\\$b", "git rm -r $F d", "sh -c \"$(printf rm) -rf x\"",
)
ALLOWED = (
    "ls -la", "rm file", "rm -f file", "git rm -r dir", "git rm -r --cached dir", "git rm file", "find . -print", "find . -name t -print",
    "echo \"$(ls)\"", "$PY script.py", "git $X status", "rm 'a{b}'", "python3 scripts/run-tests.py", "sudo $X -rf d",
    "python3 -c 'import shutil; shutil.rmtree(\"x\")'", "~/.claude/hooks/worktree-cleanup/cleanup /tmp/x", "echo rm -rf x",
    "git commit -m 'rm -rf is not allowed'",
)
# Commands that the reader cannot split: the hook allows them (S9 reports "evidence unavailable" later).
UNSPLITTABLE = ("find . -delete\necho \"oops", "rm -rf x\necho 'oops", "find . -delete \"oops")
# The kinds of S9 that are a recursive delete, written out here as the oracle of the "same verdict" test.
S9_DELETE_KINDS = {"recursive rm", "rm with a shell expansion in a word", "expanded command word with a recursive option", "find -delete"}


def run_hook(stdin_text, path=HOOK):
    result = subprocess.run([sys.executable, "-I", path], input=stdin_text, capture_output=True, text=True, check=False)
    return result


def call(command, **extra):
    return run_hook(json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, **extra}))


class VerdictTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = hook.load_audit()

    def test_every_recursive_delete_form_is_denied(self):
        for command in DENIED:
            with self.subTest(command=command):
                self.assertTrue(self.audit.recursive_delete_problems(command))

    def test_ordinary_commands_are_allowed(self):
        for command in ALLOWED:
            with self.subTest(command=command):
                self.assertEqual(self.audit.recursive_delete_problems(command), [])

    def test_a_command_that_the_reader_cannot_split_is_allowed(self):
        for command in UNSPLITTABLE:
            with self.subTest(command=command):
                self.assertEqual(self.audit.recursive_delete_problems(command), [])

    def test_the_hook_and_s9_give_the_same_verdict_on_every_case(self):
        for command in DENIED + ALLOWED + UNSPLITTABLE:
            with self.subTest(command=command):
                s9_found = any(kind in S9_DELETE_KINDS for kind in self.audit._command_problems(command))
                self.assertEqual(bool(self.audit.recursive_delete_problems(command)), s9_found)

    def test_the_hook_and_s9_give_the_same_verdict_on_every_string_of_the_s9_tests(self):
        with open(S9_TESTS, encoding="utf-8") as handle:
            commands = sorted({node.value for node in ast.walk(ast.parse(handle.read())) if isinstance(node, ast.Constant) and isinstance(node.value, str)})
        self.assertGreater(len(commands), 100)  # the S9 test file has hundreds of inputs: a smaller count means that the walk found none
        for command in commands:
            with self.subTest(command=command):
                s9_found = any(kind in S9_DELETE_KINDS for kind in self.audit._command_problems(command))
                self.assertEqual(bool(self.audit.recursive_delete_problems(command)), s9_found)

    def test_the_other_s9_kinds_are_not_a_recursive_delete(self):
        self.assertEqual(self.audit.recursive_delete_problems("docker system prune"), [])
        self.assertEqual(self.audit.recursive_delete_problems("pytest -n 8"), [])


class ProcessTest(unittest.TestCase):
    def test_a_recursive_delete_is_denied_with_the_reason_text(self):
        for extra in ({}, {"agent_id": "a1"}):
            with self.subTest(extra=extra):
                result = call("rm -rf x", **extra)
                self.assertEqual(result.returncode, 0, result.stderr)
                output = json.loads(result.stdout)["hookSpecificOutput"]
                self.assertEqual(output["permissionDecision"], "deny")
                self.assertIn("recursive deletes are not allowed (CLAUDE.md section 13): move the folder to /tmp or use a new folder for the next probe",
                              output["permissionDecisionReason"])

    def test_an_ordinary_command_is_allowed_with_no_output(self):
        result = call("git rm -r dir")
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_input_that_the_hook_cannot_read_is_allowed(self):
        for text in ("", "not json", "[]", "{}", json.dumps({"tool_name": "Bash"}), json.dumps({"tool_name": "Bash", "tool_input": {"command": 5}}),
                     json.dumps({"tool_name": "Read", "tool_input": {"command": "rm -rf x"}})):
            with self.subTest(text=text):
                result = run_hook(text)
                self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_a_hook_that_cannot_load_the_reader_allows_the_call(self):
        root = self.enterContext(tempfile.TemporaryDirectory())
        os.makedirs(os.path.join(root, "hooks", "deny-recursive-delete"))  # the audit script and the shared reader are missing
        copy = os.path.join(root, "hooks", "deny-recursive-delete", "deny_recursive_delete.py")
        shutil.copy(HOOK, copy)
        result = run_hook(json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm -rf x"}}), copy)
        self.assertEqual((result.returncode, result.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
