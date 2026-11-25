"""Tests of issue 789: an unquoted YAML value that is plain prose (three or more words, each shorter than 20
characters of letters, digits and common punctuation) is not masked, but only under the key `tokens` (a count or a
cost, any case, no other word in the key). Under any other secret key a prose value stays masked. The names are joined from
parts, so this file holds no secret-shaped text of its own.

Seam 1 is `redact(text)` through the test kit (the PostToolUse hook). Seam 2 is the Monitor filter script.
"""
import unittest

from redact_testkit import filt, redact

PASS = "Pass" + "word"
TOKENS = "Tok" + "ens"
VENDOR = "gh" + "p_abc123DEF456"
LONG_WORD = "abc123def456" + "ghi789jkl"
PROSE = "see the shared vault entry"
PASSPHRASE = "correct horse battery staple"


class ProseValueTest(unittest.TestCase):
    KEPT = (
        "- " + TOKENS + ": about 3 KB for the index at start.\n",
        TOKENS.upper() + ": about 3 KB for the index at start.\nnext: 1\n",
        "  - " + TOKENS.lower() + ": ask the on call engineer (see the wiki)\n",
        TOKENS + ": a b see\n",
        TOKENS + ": see the vault, ok\n",
        "  nested:\n    " + TOKENS.lower() + ": " + PROSE + "\n",
    )
    MASKED = (
        # a prose value under a secret key stays masked
        (PASS + ": " + PROSE + "\n", PASS + ": ***\n"),
        (PASS + ": " + PASSPHRASE + "\n", PASS + ": ***\n"),
        ("Token: " + PROSE + "\n", "Token: ***\n"),
        ("api_key: " + PROSE + "\n", "api_key: ***\n"),
        ("secret: " + PROSE + "\n", "secret: ***\n"),
        (PASS.lower() + "_" + TOKENS.lower() + ": " + PROSE + "\n", PASS.lower() + "_" + TOKENS.lower() + ": ***\n"),
        ("secre" + TOKENS.lower() + ": " + PROSE + "\n", "secre" + TOKENS.lower() + ": ***\n"),
        ("api_" + TOKENS.lower() + ": " + PASSPHRASE + "\n", "api_" + TOKENS.lower() + ": ***\n"),
        ("auth_" + TOKENS.lower() + ": " + PROSE + "\n", "auth_" + TOKENS.lower() + ": ***\n"),
        ("max_" + TOKENS.lower() + ": " + PROSE + "\n", "max_" + TOKENS.lower() + ": ***\n"),
        # a value that is no prose under the `tokens` key stays masked
        (PASS + ": hunter2\n", PASS + ": ***\n"),
        (TOKENS + ": " + LONG_WORD + "\n", TOKENS + ": ***\n"),
        (TOKENS + ": two words\n", TOKENS + ": ***\n"),
        (TOKENS + ": a b c\n", TOKENS + ": ***\n"),
        (TOKENS + ": see the " + LONG_WORD + " vault\n", TOKENS + ": ***\n"),
        (TOKENS + ": see the my_pass_word vault\n", TOKENS + ": ***\n"),
        (TOKENS + ": see the x@y vault\n", TOKENS + ": ***\n"),
        (TOKENS + ": see  the\tvault\n", TOKENS + ": ***\n"),
        (TOKENS + ": see the vault # note\n", TOKENS + ": ***\n"),
        (TOKENS + ": use " + VENDOR + " now\n", TOKENS + ": ***\n"),
        ("Token: " + VENDOR + "\n", "Token: ***\n"),
        # only an unquoted YAML value can be prose
        (TOKENS.upper() + "=" + PROSE + "\n", TOKENS.upper() + "=***\n"),
        (TOKENS + ': "' + PROSE + '"\n', TOKENS + ': "***"\n'),
        ('{"' + TOKENS.lower() + '": "' + PROSE + '"}', '{"' + TOKENS.lower() + '": "***"}'),
    )

    def test_prose_value_stays(self):
        for text in self.KEPT:
            with self.subTest(text=text):
                self.assertEqual(redact(text), text)
                self.assertEqual(filt(text), text)

    def test_other_values_stay_masked(self):
        for text, expected in self.MASKED:
            with self.subTest(text=text):
                self.assertEqual(redact(text), expected)
                self.assertEqual(filt(text), expected)


if __name__ == "__main__":
    unittest.main()
