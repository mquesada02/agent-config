"""Tests of issue 789: an unquoted YAML value that is plain prose (three or more words, each shorter than 20
characters of letters, digits and common punctuation) is not masked. Everything else keeps its mask. The names are
joined from parts, so this file holds no secret-shaped text of its own.

Seam 1 is `redact(text)` through the test kit (the PostToolUse hook). Seam 2 is the Monitor filter script.
"""
import unittest

from redact_testkit import filt, redact

PASS = "Pass" + "word"
TOKENS = "Tok" + "ens"
VENDOR = "gh" + "p_abc123DEF456"
LONG_WORD = "abc123def456" + "ghi789jkl"


class ProseValueTest(unittest.TestCase):
    KEPT = (
        "- " + TOKENS + ": about 3 KB for the index at start.\n",
        PASS + ": see the shared vault entry\n",
        PASS.lower() + ": see the shared vault entry\nnext: 1\n",
        "  - token: ask the on call engineer (see the wiki)\n",
        PASS + ": a b see\n",
        PASS + ": see the vault, ok\n",
        "  nested:\n    " + PASS.lower() + ": see the shared vault entry\n",
    )
    MASKED = (
        (PASS + ": hunter2\n", PASS + ": ***\n"),
        (TOKENS + ": " + LONG_WORD + "\n", TOKENS + ": ***\n"),
        ("Token: " + VENDOR + "\n", "Token: ***\n"),
        (PASS + ": hunter two\n", PASS + ": ***\n"),
        (PASS + ": a b c\n", PASS + ": ***\n"),
        (PASS + ": see the " + LONG_WORD + " vault\n", PASS + ": ***\n"),
        (PASS + ": see the my_pass_word vault\n", PASS + ": ***\n"),
        (PASS + ": see the x@y vault\n", PASS + ": ***\n"),
        (PASS + ": see  the\tvault\n", PASS + ": ***\n"),
        (PASS + ": see the vault # note\n", PASS + ": ***\n"),
        ("Token: use " + VENDOR + " now\n", "Token: ***\n"),
        ("TOKEN=see the shared vault\n", "TOKEN=***\n"),
        (PASS + ': "see the shared vault"\n', PASS + ': "***"\n'),
        ('{"' + PASS.lower() + '": "see the shared vault"}', '{"' + PASS.lower() + '": "***"}'),
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
