import json
import os
import shlex
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SETTINGS = os.path.join(REPO, "settings.json")
POST_COMMAND = "python3 -I ~/.claude/hooks/redact-secrets/redact_post.py"
PRE_COMMAND = "python3 -I ~/.claude/hooks/redact-secrets/redact_pre.py"


def repo_path(command):
    """Map the script token of a command (the last word) from ~/.claude/ to the repository root."""
    token = shlex.split(command)[-1]
    prefix = "~/.claude/"
    assert token.startswith(prefix), token
    return os.path.join(REPO, token[len(prefix):])


class RedactPostRegistrationTest(unittest.TestCase):
    def test_post_tool_use_has_one_redaction_group(self):
        with open(SETTINGS, encoding="utf-8") as handle:
            settings = json.load(handle)
        self.assertIn("PostToolUse", settings["hooks"], "settings.json has no hooks.PostToolUse key")
        groups = [
            group
            for group in settings["hooks"]["PostToolUse"]
            if any(entry.get("command") == POST_COMMAND for entry in group["hooks"])
        ]
        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(group["matcher"], "Bash|Read|Grep")
        self.assertEqual(len(group["hooks"]), 1)
        entry = group["hooks"][0]
        self.assertEqual(entry["type"], "command")
        self.assertEqual(entry["timeout"], 10)
        self.assertTrue(os.path.isfile(repo_path(entry["command"])))


class RedactPreRegistrationTest(unittest.TestCase):
    def test_pre_tool_use_has_one_rewrite_group(self):
        with open(SETTINGS, encoding="utf-8") as handle:
            settings = json.load(handle)
        groups = [
            group
            for group in settings["hooks"]["PreToolUse"]
            if any(entry.get("command") == PRE_COMMAND for entry in group["hooks"])
        ]
        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(group["matcher"], "Bash|Monitor")
        self.assertEqual(len(group["hooks"]), 1)
        entry = group["hooks"][0]
        self.assertEqual(entry["type"], "command")
        self.assertEqual(entry["timeout"], 10)
        self.assertEqual(entry["onFailure"], "block")
        self.assertTrue(os.path.isfile(repo_path(entry["command"])))


if __name__ == "__main__":
    unittest.main()
