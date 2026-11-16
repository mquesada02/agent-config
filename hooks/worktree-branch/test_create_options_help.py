import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
sys.path.insert(0, HOOK_DIR)
import check_branch_name as hook  # noqa: E402

# The value options of `orca worktree create` that the installed Orca help shows (issue #715). The branch hook keeps them as a literal
# list (CREATE_VALUE_OPTIONS); this test finds a new value option of Orca before a wrong branch read does.
NAME = r"(--[a-z0-9][a-z0-9-]*)"
# A value placeholder: `<...>` with no space inside, or an enumeration of two or more words joined by `|`. A single word is no placeholder.
PLACEHOLDER = r"(?:<[^<>\s]*>|[a-z0-9]+(?:\|[a-z0-9]+)+)"
USAGE_OPTION = re.compile(NAME + r"[ \t]+" + PLACEHOLDER)
OPTIONS_LINE = re.compile(r"^[ \t]*" + NAME + r"[ \t]+" + PLACEHOLDER)


class HelpParseError(Exception):
    """The help of `orca worktree create` cannot be run or cannot be parsed."""


def parse_value_options(help_text):
    """The value options of the help text, each with its two leading dashes: the union of the first usage line and the lines of the
    `Options:` section (up to its blank line). `Notes:` and `Examples:` are not read."""
    lines = help_text.splitlines()
    usage_lines = [line for line in lines if line.startswith("Usage:")]
    if not usage_lines:
        raise HelpParseError("the help has no usage line")
    found = set(USAGE_OPTION.findall(usage_lines[0]))
    in_options = False
    for line in lines:
        if in_options:
            if not line.strip():
                break
            match = OPTIONS_LINE.match(line)
            if match:
                found.add(match.group(1))
        elif line.strip() == "Options:":
            in_options = True
    if not found:
        raise HelpParseError("the help shows no value option")
    return found


def installed_value_options(search_path=None, timeout=30):
    """The value options of the installed `orca worktree create --help`. `search_path` is a string of directories joined with
    os.pathsep (the current path when None). It raises a skip when there is no `orca` on the path."""
    program = shutil.which("orca", path=search_path)
    if program is None:
        raise unittest.SkipTest("orca is not on the path")
    environment = dict(os.environ)
    if search_path is not None:
        environment["PATH"] = search_path
    try:
        result = subprocess.run([program, "worktree", "create", "--help"], env=environment, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise HelpParseError(f"the help cannot be run: {error}") from error
    if result.returncode != 0:
        raise HelpParseError(f"the help exited with code {result.returncode}")
    return parse_value_options(result.stdout)


def compare_value_options(derived, literal):
    """Return when both collections hold the same names; otherwise raise with the names that are on one side only."""
    derived, literal = set(derived), set(literal)
    if derived != literal:
        raise AssertionError(f"only in the help: {sorted(derived - literal)}; only in the literal list: {sorted(literal - derived)}")


VALID_HELP = """Usage: stub [--alpha <x>] [--mode a|b] [--one <x>|--beta <y>] [--list <z>...] [--verbose] [--usageonly <u>]

Options:
  --help         Show
  --alpha <x>    Alpha
  --verbose      quiet
  --optonly <o>  Only here
  --flagtwo      <two words> text
  --note         mentions --gamma <z> in text

Notes:
  --notesonly <n>  not read
"""


class CreateOptionsHelpTest(unittest.TestCase):
    def stub_path(self, script, help_text=None):
        """A search path whose first directory holds a stub `orca` that runs the shell `script`; the system directories follow, so that
        a stub can run `cat` or `sleep`. The real `orca` is never found first."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        if help_text is not None:
            help_file = os.path.join(directory.name, "help.txt")
            with open(help_file, "w") as handle:
                handle.write(help_text)
            script = f"cat '{help_file}'"
        stub = os.path.join(directory.name, "orca")
        with open(stub, "w") as handle:
            handle.write(f"#!/bin/sh\n{script}\n")
        os.chmod(stub, 0o755)
        return os.pathsep.join((directory.name, "/usr/bin", "/bin"))

    def test_installed_help_matches_the_literal_list(self):
        compare_value_options(installed_value_options(), hook.CREATE_VALUE_OPTIONS)

    def test_no_orca_on_the_path_skips(self):
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(unittest.SkipTest):
                installed_value_options(search_path=empty)

    def test_help_without_a_usage_line_fails(self):
        with self.assertRaises(HelpParseError):
            installed_value_options(self.stub_path("", "Options:\n  --a <x>  A\n"))

    def test_help_without_a_value_option_fails(self):
        with self.assertRaises(HelpParseError):
            installed_value_options(self.stub_path("", "Usage: stub [--verbose]\n\nOptions:\n  --verbose  quiet\n"))

    def test_valid_help_gives_the_expected_set(self):
        derived = installed_value_options(self.stub_path("", VALID_HELP))
        self.assertEqual(derived, {"--alpha", "--mode", "--one", "--beta", "--list", "--usageonly", "--optonly"})

    def test_non_zero_exit_fails(self):
        with self.assertRaises(HelpParseError):
            installed_value_options(self.stub_path("exit 3"))

    def test_timeout_fails(self):
        with self.assertRaises(HelpParseError):
            installed_value_options(self.stub_path("exec sleep 10"), timeout=1)

    def test_stub_that_cannot_start_fails(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        stub = os.path.join(directory.name, "orca")
        with open(stub, "w") as handle:
            handle.write("#!/nonexistent/interpreter\n")
        os.chmod(stub, 0o755)
        with self.assertRaises(HelpParseError):
            installed_value_options(directory.name)

    def test_failure_message_names_the_options_on_one_side_only(self):
        with self.assertRaises(AssertionError) as caught:
            compare_value_options({"--aa", "--bb"}, ("--bb", "--cc"))
        message = str(caught.exception)
        self.assertIn("--aa", message)
        self.assertIn("--cc", message)
        self.assertNotIn("--bb", message)


if __name__ == "__main__":
    unittest.main()
