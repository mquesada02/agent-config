"""Tests of the file-path rule of redact_rules (config issue 1030).

Two seams: `redact` runs the whole PostToolUse hook on a Bash output (end to end), and `redact_text` calls the
rules module directly (faster, and it shows the rule on its own).
"""
import unittest

from redact_rules import redact as redact_text
from redact_testkit import redact

FAKE = "FAKE_SECRET_123"


class FilePathRuleTest(unittest.TestCase):
    """The file-path rule (config issue 1030): a path value of a `_FILE` env or YAML key stays."""

    def test_env_path_in_a_command_stays(self):
        text = "tool add demo -e EXAMPLE_API_TOKEN_FILE=/home/u/.config/demo.token -- node x.js\n"
        self.assertEqual(redact(text), text)

    def test_every_path_start_stays(self):
        for path in ("/a/b.token", "~/a/b.token", "./b.token", "../b.token", "C:\\a\\b.token", "C:/a/b.token"):
            with self.subTest(path=path):
                text = "API_TOKEN_FILE=" + path + "\n"
                self.assertEqual(redact_text(text), text)

    def test_quoted_path_with_a_space_stays(self):
        for quote in ('"', "'"):
            with self.subTest(quote=quote):
                text = f"API_TOKEN_FILE={quote}/my dir/b.token{quote} next\n"
                self.assertEqual(redact_text(text), text)

    def test_yaml_path_stays(self):
        text = "api_token_file: /run/secrets/token\nname: web\n"
        self.assertEqual(redact_text(text), text)

    def test_dash_file_flag_stays(self):
        text = "run --token-file=/a/b.token --verbose\n"
        self.assertEqual(redact_text(text), text)

    def test_later_secret_key_on_the_line_is_still_masked(self):
        text = "A_TOKEN_FILE=/a/b.token B_TOKEN=" + FAKE + "\n"
        self.assertEqual(redact_text(text), "A_TOKEN_FILE=/a/b.token B_TOKEN=***\n")

    def test_value_that_is_no_path_is_masked(self):
        self.assertEqual(redact_text("A_TOKEN_FILE=" + FAKE + "\n"), "A_TOKEN_FILE=***\n")

    def test_path_glued_to_a_quote_is_masked(self):
        self.assertEqual(redact_text("A_TOKEN_FILE=/a/b'" + FAKE + "\n"), "A_TOKEN_FILE=***\n")

    def test_unclosed_quote_is_masked(self):
        self.assertEqual(redact_text('A_TOKEN_FILE="/a/' + FAKE + "\n"), 'A_TOKEN_FILE="***"\n')

    def test_empty_quotes_are_kept_by_the_value_guard(self):
        self.assertEqual(redact_text('A_TOKEN_FILE="" B_TOKEN=' + FAKE + "\n"), 'A_TOKEN_FILE="" B_TOKEN=***\n')

    def test_key_without_the_file_suffix_is_masked(self):
        for key in ("API_TOKEN", "TOKEN_FILE_X", "API_TOKENFILE"):
            with self.subTest(key=key):
                self.assertEqual(redact_text(key + "=/a/b.token\n"), key + "=***\n")

    def test_json_key_does_not_take_the_rule(self):
        self.assertEqual(redact_text('{"A_TOKEN_FILE": "/a/b.token"}'), '{"A_TOKEN_FILE": "***"}')


if __name__ == "__main__":
    unittest.main()
