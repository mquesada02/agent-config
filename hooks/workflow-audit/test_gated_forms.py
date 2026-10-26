import importlib.machinery
import importlib.util
import os
import sys
import unittest

from test_gate import GateTestCase

AUDIT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit")


def _gated_forms():
    """The list of gated forms, read as data from the audit script. The script has no `.py` extension and its `__main__` guard makes the
    load safe. No `.pyc` is written."""
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        loader = importlib.machinery.SourceFileLoader("audit_for_gated_forms", AUDIT)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module.GATED_FORMS
    finally:
        sys.dont_write_bytecode = previous


class GatedFormsTest(GateTestCase):
    def test_the_list_holds_the_pr_gate_and_the_dispatch_gate(self):
        self.assertEqual([form.count_text for form in _gated_forms()], ["gh pr create", "orchestration worker-start"])

    def test_every_raw_text_is_inside_its_count_text_and_survives_the_normalisation(self):
        for form in _gated_forms():
            with self.subTest(form=form.count_text):
                self.assertIn(form.raw_text, form.count_text)
                for text in (form.count_text, form.raw_text):
                    self.assertEqual(" ".join(text.split()), text)
                    self.assertNotIn('"', text)
                    self.assertNotIn("'", text)

    def test_every_listed_form_is_denied_as_a_wrapped_form(self):
        for form in _gated_forms():
            with self.subTest(form=form.count_text):
                self.assert_denied(self.gate(f'bash -c "{form.count_text}"'), f"unchecked command form: run {form.count_text} as a plain command")

    def test_every_listed_form_is_denied_as_an_unparsable_command(self):
        for form in _gated_forms():
            with self.subTest(form=form.count_text):
                self.assert_denied(self.gate(f'echo "{form.count_text}'), form.unparsable_reason)

    def test_every_listed_form_is_denied_when_the_hook_input_is_not_json(self):
        for form in _gated_forms():
            with self.subTest(form=form.count_text):
                self.assert_denied(self.audit("hook", "pre-tool-use", stdin=f"not json: {form.count_text}"),
                                   "hook input unreadable: the hook input is not JSON")


if __name__ == "__main__":
    unittest.main()
