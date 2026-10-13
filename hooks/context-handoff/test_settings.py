import json
import os
import shlex
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SETTINGS = os.path.join(REPO, "settings.json")
HOOK_COMMAND = "python3 -I ~/.claude/hooks/context-handoff/hook.py"
STATUSLINE_COMMAND = "python3 -I ~/.claude/hooks/context-handoff/statusline.py"


def repo_path(command):
    """Map the script token of a command (the last word) from ~/.claude/ to the repository root."""
    token = shlex.split(command)[-1]
    prefix = "~/.claude/"
    assert token.startswith(prefix), token
    return os.path.join(REPO, token[len(prefix):])


class ContextHookRegistrationTest(unittest.TestCase):
    def setUp(self):
        with open(SETTINGS, encoding="utf-8") as handle:
            self.settings = json.load(handle)

    def only_entry(self, event):
        self.assertIn(event, self.settings["hooks"], f"settings.json has no hooks.{event} key")
        groups = [
            group
            for group in self.settings["hooks"][event]
            if any(entry.get("command") == HOOK_COMMAND for entry in group["hooks"])
        ]
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["hooks"]), 1)
        entry = groups[0]["hooks"][0]
        self.assertEqual(entry["type"], "command")
        self.assertEqual(entry["timeout"], 10)
        return groups[0]

    def test_stop_has_one_context_hook_without_matcher(self):
        self.assertNotIn("matcher", self.only_entry("Stop"))

    def test_post_tool_use_has_one_context_hook_on_every_tool(self):
        self.assertEqual(self.only_entry("PostToolUse")["matcher"], "*")

    def test_a_missing_event_key_fails_with_a_message_that_names_the_key(self):
        with self.assertRaises(AssertionError) as caught:
            self.only_entry("NoSuchEvent")
        self.assertIn("hooks.NoSuchEvent", str(caught.exception))

    def test_the_hook_script_exists(self):
        self.assertTrue(os.path.isfile(repo_path(HOOK_COMMAND)))

    def test_the_status_line_still_runs_the_wrapper(self):
        self.assertEqual(self.settings["statusLine"]["command"], STATUSLINE_COMMAND)
        self.assertTrue(os.path.isfile(repo_path(STATUSLINE_COMMAND)))


if __name__ == "__main__":
    unittest.main()
