# The go-live registration of ticket #100: the two audit hooks in settings.json, and a gate decision that does not depend on hook order.
import itertools
import json
import os
import re
import shlex
import subprocess
import sys
import unittest

from audit_support import HERE, AuditCase

REPO = os.path.dirname(os.path.dirname(HERE))
SETTINGS = os.path.join(REPO, "settings.json")
GATE_COMMAND = "python3 -I ~/.claude/hooks/workflow-audit/audit hook pre-tool-use"
SESSION_COMMAND = "python3 -I ~/.claude/hooks/workflow-audit/audit hook session-start"
HOME_PREFIX = "~/.claude/"
WORKER_START = "orca-ide orchestration worker-start --task t1 --agent claude"


def load_settings():
    with open(SETTINGS, encoding="utf-8") as handle:
        return json.load(handle)


def repo_argv(command):
    """The argv of a hook command, with its first `~/.claude/` word mapped to the repo root.

    None when the command has no such word, does not parse, or names a file that is not in the repo.
    """
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    for index, word in enumerate(words):
        if word.startswith(HOME_PREFIX):
            path = os.path.join(REPO, word[len(HOME_PREFIX):])
            if not os.path.isfile(path):
                return None
            words[index] = path
            return [sys.executable if words[0] == "python3" else words[0]] + words[1:]
    return None


def matches_bash(group):
    matcher = group.get("matcher", "*")
    return matcher in ("", "*") or re.fullmatch(matcher, "Bash") is not None


def groups_with(settings, event, command):
    return [group for group in settings["hooks"][event]
            if any(entry.get("command") == command for entry in group["hooks"])]


class RegistrationTest(unittest.TestCase):
    def setUp(self):
        self.settings = load_settings()

    def only_group(self, event, command):
        groups = groups_with(self.settings, event, command)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["hooks"]), 1)
        self.assertEqual(groups[0]["hooks"][0]["type"], "command")
        return groups[0]

    def test_pre_tool_use_has_one_audit_group_on_bash(self):
        group = self.only_group("PreToolUse", GATE_COMMAND)
        self.assertEqual(group["matcher"], "Bash")
        self.assertEqual(group["hooks"][0]["timeout"], 60)

    def test_session_start_has_one_audit_group_without_matcher(self):
        group = self.only_group("SessionStart", SESSION_COMMAND)
        self.assertNotIn("matcher", group)
        self.assertEqual(group["hooks"][0]["timeout"], 10)

    def test_the_audit_script_exists(self):
        for command in (GATE_COMMAND, SESSION_COMMAND):
            with self.subTest(command=command):
                argv = repo_argv(command)
                self.assertIsNotNone(argv)
                self.assertTrue(os.path.isfile(argv[2]))

    def test_the_audit_commands_are_not_registered_under_any_other_event(self):
        for event, groups in self.settings["hooks"].items():
            for group in groups:
                for entry in group["hooks"]:
                    if "workflow-audit" in entry.get("command", ""):
                        self.assertIn((event, entry["command"]), (("PreToolUse", GATE_COMMAND), ("SessionStart", SESSION_COMMAND)))


class HookOrderTest(AuditCase):
    """The decision of all the Bash PreToolUse hooks is the same in every order of the groups of settings.json.

    Hooks outside the repo (the Orca hook is an inline shell snippet that needs the Orca app) are not run.
    """

    def bash_groups(self):
        return [group for group in load_settings()["hooks"]["PreToolUse"] if matches_bash(group)]

    def run_hook(self, argv, stdin):
        return subprocess.run(argv, input=stdin.encode(), env=self.env, cwd=self.root, capture_output=True, timeout=60)

    def verdict(self, result):
        """(denied, reason) of one hook: exit status 2 with the reason on stderr, or a deny decision on stdout."""
        if result.returncode == 2:
            return True, result.stderr.decode()
        self.assertEqual(result.returncode, 0, result.stderr)
        if result.stdout:
            output = json.loads(result.stdout)["hookSpecificOutput"]
            if output["permissionDecision"] == "deny":
                return True, output["permissionDecisionReason"]
        return False, ""

    def combined(self, groups, command):
        stdin = json.dumps({"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "Bash",
                            "tool_input": {"command": command}, "cwd": self.repo})
        verdicts = []
        for group in groups:
            for entry in group["hooks"]:
                argv = repo_argv(entry["command"])
                if argv is not None:
                    verdicts.append(self.verdict(self.run_hook(argv, stdin)))
        reasons = sorted(reason for denied, reason in verdicts if denied)
        return bool(reasons), reasons

    def assert_same_in_every_order(self, command, denied, prefix):
        groups = self.bash_groups()
        self.assertGreaterEqual(len(groups), 3)  # the audit group, the aws guard and the Orca hook
        for order in itertools.permutations(groups):
            with self.subTest(order=[group.get("matcher") for group in order]):
                got_denied, reasons = self.combined(order, command)
                self.assertEqual(got_denied, denied)
                self.assertEqual(len(reasons), 1 if denied else 0, reasons)
                if denied:
                    self.assertTrue(reasons[0].startswith(prefix), reasons[0])

    def test_a_pr_without_a_record_is_denied_in_every_order(self):
        self.start_branch("feature", "feat(audit): add a thing")
        self.assert_same_in_every_order("gh pr create --title t --body b", True, "no record")

    def test_a_pr_with_a_passing_record_is_allowed_in_every_order(self):
        self.start_branch("feature", "feat(audit): add a thing")
        self.assertEqual(self.record().returncode, 0)
        self.assert_same_in_every_order("gh pr create --title t --body b", False, "")

    def test_a_dispatch_without_a_record_is_denied_in_every_order(self):
        self.assert_same_in_every_order(WORKER_START, True, "no pre-dispatch record")

    def test_a_dispatch_with_a_passing_record_is_allowed_in_every_order(self):
        os.makedirs(self.runtime, 0o700, exist_ok=True)
        with open(os.path.join(self.runtime, "pre-dispatch-s1.json"), "w") as handle:
            json.dump({"session_id": "s1", "map": 82, "remote_url": self.origin, "branch": "feature",
                       "time": "2026-10-16T00:00:00+00:00", "items": [], "result": "pass"}, handle)
        self.assert_same_in_every_order(WORKER_START, False, "")

    def test_a_plain_command_is_allowed_in_every_order(self):
        self.assert_same_in_every_order("ls", False, "")

    def test_the_hooks_that_the_order_test_runs_include_the_audit_gate_and_the_aws_guard(self):
        scripts = sorted(os.path.basename(word)
                         for group in self.bash_groups() for entry in group["hooks"] if repo_argv(entry["command"])
                         for word in repo_argv(entry["command"]) if word.startswith(REPO))
        self.assertEqual(scripts, ["audit", "block-aws-credentials.py"])


if __name__ == "__main__":
    unittest.main()
