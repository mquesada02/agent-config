"""Tests of the `passphrase` and `pin` secret key words (issue 1038): `pin` matches only as a whole key part."""
import unittest

from redact_testkit import filt, redact

MASKED_KEYS = ("Passphrase", "passphrase", "PIN", "pin", "pin_code", "userPin", "card-pin", "card.pin", "PIN_CODE", "pin2")
PLAIN_KEYS = ("pinned", "spinner", "mapping", "shipping", "opinion", "Pinterest", "pinning")


class PinPassphraseTest(unittest.TestCase):
    def test_masked_yaml_keys(self):
        for key in MASKED_KEYS:
            with self.subTest(key=key):
                self.assertEqual(redact("%s: abcXYZ123qq\n" % key), "%s: ***\n" % key)

    def test_masked_env_and_json_keys(self):
        for key in MASKED_KEYS:
            with self.subTest(key=key):
                self.assertEqual(redact("%s=abcXYZ123qq\n" % key), "%s=***\n" % key)
                self.assertEqual(redact('{"%s": "abcXYZ123qq"}' % key), '{"%s": "***"}' % key)

    def test_pin_masks_numbers_in_every_form(self):
        for key in ("PIN", "pin_code", "userPin", "card-pin"):
            with self.subTest(key=key):
                self.assertEqual(redact("%s: 4821\n" % key), "%s: ***\n" % key)
                self.assertEqual(redact("%s=4821\n" % key), "%s=***\n" % key)
                self.assertEqual(redact('%s: "4821"\n' % key), '%s: "***"\n' % key)
                self.assertEqual(redact('{"%s": "4821"}' % key), '{"%s": "***"}' % key)
                self.assertEqual(redact('{"%s": 4821}' % key), '{"%s": "***"}' % key)
                self.assertEqual(redact('{"%s":\n "4821"}' % key), '{"%s":\n "***"}' % key)
                self.assertEqual(filt('{"%s":\n "4821"}\n' % key), '{"%s":\n "***"}\n' % key)

    def test_pin_keeps_true_false_null(self):
        for value in ("true", "false", "null"):
            self.assertEqual(redact("pin: %s\n" % value), "pin: %s\n" % value)

    def test_number_under_other_keys_stays(self):
        self.assertEqual(redact("passphrase: 4821\n"), "passphrase: 4821\n")
        self.assertEqual(redact("pinned: 4821\n"), "pinned: 4821\n")

    def test_masked_block_scalar_and_json_object(self):
        self.assertEqual(redact("pin: |\n  4821\n  9\nname: web\n"), "pin: ***\nname: web\n")
        self.assertEqual(redact('{"userPin": {"a": "b",\n "c": "d"}}'), '{"userPin": "***"}')

    def test_plain_keys_stay(self):
        for key in PLAIN_KEYS:
            with self.subTest(key=key):
                self.assertEqual(redact("%s: abcXYZ123qq\n" % key), "%s: abcXYZ123qq\n" % key)
                self.assertEqual(redact("%s=abcXYZ123qq\n" % key), "%s=abcXYZ123qq\n" % key)
                self.assertEqual(redact('{"%s": "abcXYZ123qq"}' % key), '{"%s": "abcXYZ123qq"}' % key)

    def test_issue_examples_stay(self):
        for text in ("pinned: true\n", "spinner: dots\n", "mapping: a.b\n", "shipping: fast\n"):
            self.assertEqual(redact(text), text)

    def test_monitor_filter_masks(self):
        self.assertEqual(filt("Passphrase: abcXYZ123qq\n"), "Passphrase: ***\n")
        self.assertEqual(filt("PIN: 4821x\n"), "PIN: ***\n")
        self.assertEqual(filt("pin: |\n  4821x\nname: web\n"), "pin: ***\nname: web\n")
        self.assertEqual(filt("spinner: dots\n"), "spinner: dots\n")

    def test_tokens_prose_rule_unchanged(self):
        self.assertEqual(redact("tokens: about three thousand\n"), "tokens: about three thousand\n")
        self.assertEqual(redact("max_tokens: about three thousand\n"), "max_tokens: ***\n")
        self.assertEqual(redact("pin: about three thousand\n"), "pin: ***\n")


if __name__ == "__main__":
    unittest.main()
