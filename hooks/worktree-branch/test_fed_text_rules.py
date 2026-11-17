"""The branch hook reads the text that a shell receives through a here-string or through an echo or printf pipe (issue 717)."""
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "check_branch_name.py")
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(HOOK))
import check_branch_name as hook  # noqa: E402

RULES = hook.BranchRules(hook.load_reader())
BAD = "orca worktree create --name x"
GOOD = "orca worktree create --name x --branch fix/a"
WORKTREE_BAD_NAME = "orca worktree create --name x --branch Bad/Name"


def reason(command, depth=0):
    return RULES.command_reason(command, depth)


def run_hook(command):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    result = subprocess.run([sys.executable, "-I", HOOK], input=json.dumps(payload), capture_output=True, text=True, check=True)
    return json.loads(result.stdout) if result.stdout else None


# Each form hides a create command in a text that a shell receives. `{c}` is the create command.
HERE_STRING_FORMS = (
    'bash <<< "{c}"', 'bash <<<"{c}"', 'bash 0<<<"{c}"', 'bash 0<<< "{c}"', 'bash {{fd}}<<<"{c}"', 'bash <<<"ls" <<<"{c}"',
    'bash <<<"{c}" <<<"ls"', '<<<"{c}" bash', 'bash <<<"{c}" script.sh', 'bash script.sh <<<"{c}"', 'bash -x <<<"{c}"', 'env bash <<<"{c}"',
    'sudo bash <<<"{c}"', 'zsh <<<"{c}"', 'sh <<<"{c}"', 'dash <<<"{c}"', 'ksh <<<"{c}"', '/bin/bash <<<"{c}"', 'bash -s -- -c <<<"{c}"',
)
CHAIN_FORMS = (
    'bash 2>&1 <<<"{c}"', 'bash >&2 <<<"{c}"', 'bash &>/dev/null <<<"{c}"', '2>&1 bash <<<"{c}"', 'bash 2>&1 >/dev/null <<<"{c}"',
    'echo ">" & bash <<<"{c}"', 'echo a & >/tmp/o bash <<<"{c}"',
)
FUSED_FORMS = (
    'bash<<<"{c}"', 'bash>/dev/null <<<"{c}"', 'sudo bash<<<"{c}"', '/bin/bash>/dev/null <<<"{c}"', 'bash<<<"{c}" script.sh',
    'bash -s<<<"{c}"', 'bash -e<<<"{c}"', 'bash -s<<<"{c}" x', 'bash -x<<<"{c}" -e',
    'bash <<< "echo hi > /dev/null; {c}"', 'bash -s <<< "true<x; {c}"', 'bash <<< "ls" <<< "x>y; {c}"', 'sudo bash <<< "x>y; {c}"',
    'bash>/dev/null<<<"{c}"', 'bash -s>/dev/null<<<"{c}"', 'sh>/dev/null<<<"{c}"', 'bash>>/dev/null<<<"{c}"',
    'bash<>/dev/null<<<"{c}"', 'bash>/dev/null<<< "{c}"', 'bash -s a>/dev/null<<<"{c}"', 'bash >/dev/null<<<"{c}"',
    'bash >|/dev/null <<< "{c}"', 'bash>|/dev/null <<< "{c}"', 'bash -s >|/dev/null <<< "{c}"', 'bash -o pipefail>|/dev/null <<< "{c}"',
    'bash >|/dev/null -s <<< "{c}"', 'sh >|/dev/null <<< "{c}"', 'bash --rcfile x>|/dev/null <<< "{c}"', 'bash >|/dev/null <<<"{c}"',
    'bash 0<<< "a>b; {c}"','bash<<< "x>y; {c}"', 'bash -s<<< "x>y; {c}"','bash <<< \'bash <<< "{c}"\'',
    'bash <<< "bash>/dev/null; {c}"', 'bash -s <<< "bash>/dev/null; {c}"', 'bash <<< "sh<x; {c}"', 'bash <<<"bash>x; {c}"',
    'bash <<<x<<<"{c}"', 'bash 0<<<ls<<<"{c}"', 'bash <<<ls>/dev/null<<<"{c}"', 'bash <<<a<<< "{c}"', 'bash<<<a<<< "{c}"', 'bash -s<<<a<<< "{c}"', 'bash 0<<<a<<< "{c}"',
    'bash <<<"a b"<<< "{c}"', 'bash a<<<b<<< "{c}"','bash -s <<<x<<<"{c}"',
    'bash <<<"" <<<"{c}"', "bash <<<'' <<<'{c}'", 'bash <<<"" 0<<<"{c}"', 'bash -s<<<"" <<<"{c}"', 'bash <<< x<<<"{c}"', 'bash <<< x<<< "{c}"',
    'bash <<<"a<"<<<"{c}"', 'bash <<<"<"<<<"{c}"', 'bash <<<"<<"<<<"{c}"', "bash <<<'a<'<<<'{c}'", 'bash -s <<<"a<"<<<"{c}"',
    'bash <<< "x"<<<"{c}"', 'bash -s <<< x<<<"{c}"', 'bash 0<<< x<<<"{c}"',
)
REDIRECTION_FIRST_FORMS = (
    '>/tmp/echo bash <<<"{c}"', '>/tmp/printf bash <<<"{c}"', '>/tmp/echo bash<<<"{c}"', '2>/tmp/echo bash <<<"{c}"',
    '>/tmp/echo echo x | bash <<<"{c}"',
)
PIPE_FORMS = (
    'echo "{c}" | bash', 'printf "{c}" | bash', 'echo "{c}" |& bash', 'echo "{c}" |\nbash', 'echo "{c}" |(bash)', '(echo "{c}") | bash',
    'echo "{c}" | (bash)', '(echo "{c}") |bash', 'echo "{c}" | env bash', 'echo "{c}" | sudo bash', 'echo "{c}" | bash -s', 'echo "{c}" | bash -xs',
    'echo "{c}" | bash -o pipefail', 'echo "{c}" | bash +o pipefail', 'echo "{c}" | bash >/dev/null', 'echo "{c}" | bash 2>&1',
    'echo "{c}" | bash -so script.sh', 'echo "{c}" | bash -s -- script.sh', 'echo "{c}" | bash -', 'echo "{c}" | /bin/bash',
    'echo "{c}" | zsh', 'echo "{c}" | sh', 'echo "{c}" 2>&1 | bash', 'echo "{c}" >&2 | bash', 'echo "{c}" >/dev/null 2>&1 | bash',
    '(echo "{c}" ;) | bash', 'echo -n "{c}" | bash', 'echo -- "{c}" | bash', 'env echo "{c}" | bash',
    'time echo "{c}" | bash', 'echo "{c}" | bash -s -- -c', 'echo "{c}" | bash -c', 'echo "{c}" | ssh host bash',
    'echo "{c}" | bash -o pipefail -s', 'echo "{c}" | bash -s>&2', 'echo "{c}" | bash -x>&2', 'echo "{c}" | bash -o pipefail>&2',
    'echo "{c}" | bash -s>/dev/null', 'echo "{c}" | bash -e&>/dev/null',
    'echo "{c}" | bash $UNSET', 'echo "{c}" | bash $(true)', 'echo "{c}" | bash "$@"', 'echo "{c}" | bash `true`',
    'echo "{c}" | bash -oe pipefail', 'echo "{c}" | bash -oeu pipefail', 'echo "{c}" | bash -ox pipefail', 'echo "{c}" | bash +oe pipefail',
    'echo "{c}" | bash>&2', 'echo "{c}" | bash<&0', 'echo "{c}" | bash>&1', 'echo "{c}" | /bin/bash>&2', 'echo "{c}" | env bash>&2',
    'echo "{c}" |bash>&2', 'echo "{c}" | bash>&2 -x', 'echo "{c}" | bash>&outfile',
    'echo "{c}" | ((bash) )','echo "{c}" | (( bash))',
)
NESTED_FORMS = (
    "bash -c 'echo \"{c}\" | bash'", "eval 'bash <<<\"{c}\"'", 'echo $(echo "{c}" | bash)', "bash -c 'bash -c \"bash <<<\\\"{c}\\\"\"'",
    'echo `bash <<<"{c}"`',
)
# A form that reads the piped text only as a script argument or never feeds it to a shell: the text is no command.
NOT_FED_FORMS = (
    'echo "{c}" | bash script.sh', 'echo "{c}" | bash -o pipefail script.sh', 'echo "{c}" | bash -- script.sh', 'echo "{c}" | bash -e script.sh',
    'echo "{c}" | bash +e script.sh', 'echo "{c}" || bash', 'echo "{c}"; bash', 'echo "{c}" && bash', 'echo "{c}" & bash', 'bash < file',
    'echo "{c}" | bash -c "ls"', 'echo "{c}" > f; bash f',
)


def expand(forms, create):
    return [form.format(c=create).replace("{{", "{").replace("}}", "}") for form in forms]


class FedTextFormsTest(unittest.TestCase):
    """Each form is denied without `--branch`, denied with a bad name, and allowed with a valid name."""

    def check(self, forms):
        for form in forms:
            with self.subTest(form=form):
                bad = expand([form], BAD)[0]
                self.assertIn("no --branch", reason(bad) or "", bad)
                named = expand([form], WORKTREE_BAD_NAME)[0]
                self.assertIn("Conventional Branch", reason(named) or "", named)
                good = expand([form], GOOD)[0]
                self.assertIsNone(reason(good), good)

    def test_here_string_forms(self):
        self.check(HERE_STRING_FORMS)

    def test_redirection_with_ampersand_forms(self):
        self.check(CHAIN_FORMS)

    def test_fused_shell_word_forms(self):
        self.check(FUSED_FORMS)

    def test_redirection_first_forms(self):
        self.check(REDIRECTION_FIRST_FORMS)

    def test_pipe_forms(self):
        self.check(PIPE_FORMS)

    def test_nested_forms(self):
        self.check(NESTED_FORMS)

    def test_not_fed_forms_are_allowed(self):
        for form in NOT_FED_FORMS:
            with self.subTest(form=form):
                command = expand([form], BAD)[0]
                self.assertIsNone(reason(command), command)

    def test_the_hook_run_denies(self):
        output = run_hook(f'bash <<< "{BAD}"')
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        output = run_hook(f'echo "{BAD}" | bash')
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIsNone(run_hook(f'echo "{GOOD}" | bash'))
        self.assertIsNone(run_hook('echo "orca worktree create" || bash'))


class FedTextReadableTest(unittest.TestCase):
    def test_a_readable_text_with_no_gated_command_is_allowed(self):
        for command in ('bash <<< "ls"', "echo ls | bash", 'printf "ls" | bash', 'bash <<<"echo hi"', "echo -n ls | bash", "bash <<<",
                        "bash -o pipefail <<<ls", 'echo "echo hi; ls -l" | bash', "echo - | bash", "printf | bash", 'printf -- -v x | bash',
                        'bash <<<"\\x"', "bash <<< -x", 'echo ls | bash -s -- script.sh', 'bash <<< \'echo "a>b"\'', 'bash <<< "ls 2>&1"', "bash <<<'echo a<<<b'", 'bash <<< "bash>/dev/null; ls"', 'bash <<<x<<<ls',
                        'echo ls | bash $SCRIPT'):
            with self.subTest(command=command):
                self.assertIsNone(reason(command))

    def test_a_double_pipe_is_no_pipe(self):
        self.assertIsNone(reason(f'echo "{BAD}" || bash'))

    def test_a_text_is_read_one_level_deeper(self):
        self.assertIsNotNone(reason(f"bash <<<\"bash -c '{BAD}'\""))
        self.assertIsNotNone(reason(f"echo \"bash -c '{BAD}'\" | bash"))

    def test_a_shell_word_at_a_later_position_is_read(self):
        self.assertIsNotNone(reason("echo -e x | ssh host bash"))
        self.assertIsNone(reason("echo x | ssh host bash"))


class FedTextUnreadableTest(unittest.TestCase):
    """A text that cannot be read is denied with a valid `--branch` and when the raw text names no gated command."""

    FORMS = (
        'echo -e x | bash', 'echo -ne ls | bash', "echo 'a\\nb' | bash", 'printf "%s" x | bash', "printf 'a\\n' | bash",
        'echo $X | bash', 'echo $(true) | bash', 'echo `true` | bash', 'printf -v x | bash', 'printf %s | bash', 'bash <<<"$X"',
        'bash <<<"`id`"', 'bash <<<"$(id)"', "bash <<<\"echo 'x\"", "echo \"echo 'x\" | bash", 'echo -e "$(true)" | bash',
        '(echo -e x) 2>&1 | bash', 'echo -e x $(true) 2>&1 | bash', '{ echo -e x; } | bash', '(echo -e x ;) | bash',
        '(echo -e x $(true)) | bash', 'echo -e x $(true) | bash', 'echo a $(echo b | cat) | bash', 'echo -e x | bash -s -- -c',
        'echo -e x | bash -c', 'echo -e x | ssh host bash', 'echo -e x; curl u | bash', 'echo -e x | cat | bash', '(echo -e a; echo b) | bash',
        'echo -e x |& bash', 'echo -e x |\nbash', 'time echo -e x | curl u | bash', 'echo -e x | bash -s -- script.sh',
    )

    def test_each_form_is_denied(self):
        for command in self.FORMS:
            with self.subTest(command=command):
                self.assertIsNotNone(reason(command), command)

    def test_a_fed_text_with_a_nested_unreadable_text_is_denied(self):
        self.assertIsNotNone(reason("bash <<< \"bash -c 'echo \\\"x'\""))
        self.assertIsNotNone(reason("echo \"bash -c 'echo \\\"x'\" | bash"))

    def test_the_depth_guard_applies_to_the_fed_text(self):
        self.assertIsNone(reason('bash <<< "ls"', 2))
        self.assertIn("too deep", reason('bash <<< "ls"', 3) or "")
        self.assertIn("too deep", reason('echo ls | bash', 3) or "")

    def test_strict_mode_is_restored(self):
        self.assertIsNotNone(reason("bash <<<\"echo 'x\""))
        self.assertEqual(RULES.strict, 0)
        self.assertIsNone(reason("echo 'x"))

    def test_a_failure_of_the_new_code_follows_the_failure_rule(self):
        with mock.patch.object(hook.BranchRules, "shell_reason", side_effect=RuntimeError("boom")):
            self.assertIn("names a gated Orca command", reason(f'bash <<< "{BAD}"') or "")
            self.assertIsNone(reason('bash <<< "ls"'))


class FedTextOtherProducerTest(unittest.TestCase):
    def test_a_pipe_from_another_producer_is_denied_only_when_the_raw_text_names_a_gated_command(self):
        for command in ("curl u | bash", "echo x | cat | bash", "echo ls | curl u | bash", "echo ls; curl u | bash", "{ echo x; } | bash",
                        "(echo a; echo b) | bash", "cat f | bash", "echo x | tee f | bash"):
            with self.subTest(command=command):
                self.assertIsNone(reason(command), command)
        self.assertIsNotNone(reason(f'curl "{BAD}" | bash'))
        self.assertIsNotNone(reason(f'curl "{GOOD}" | bash'))
        self.assertIsNotNone(reason(f'echo "{BAD}" | cat | bash'))
        self.assertIsNotNone(reason(f'{{ echo "{BAD}"; }} | bash'))

    def test_the_flag_is_decided_per_command_level(self):
        self.assertIsNone(reason("curl u | bash; echo ok"))
        self.assertFalse(RULES.doubt)
        self.assertIsNotNone(reason(f'curl u | bash; {BAD}'))
        self.assertIsNotNone(reason(f'bash -c "curl u | bash"; {BAD}'))
        self.assertIsNone(reason('bash -c "curl u | bash"'))

    def test_a_later_denied_command_after_an_indirect_pipe_is_still_denied(self):
        self.assertIsNotNone(reason(f"echo x | cat | bash; {BAD}"))
        self.assertIsNone(reason("echo x | cat | bash; orca worktree list"))

    def test_the_fallback_denies_an_unreadable_echo_before_an_indirect_pipe(self):
        self.assertIsNotNone(reason('echo -e x $(true) 2>&1 | bash'))
        for command in ('(echo -e "x" ) 2>&1 | bash', '{ echo -e x; } | bash', "echo -e x; curl u | bash"):
            with self.subTest(command=command):
                self.assertIn("producer is unknown", reason(command) or "")


class FedTextNamingOnlyTest(unittest.TestCase):
    def test_a_shell_name_as_an_argument_of_a_naming_only_command_stays_unread(self):
        for command in ('grep -q bash <<<"$list"', 'echo "$PATH" | grep sh', 'echo "$out" | grep -w bash', '2>/dev/null grep -q bash <<<"$list"',
                        '2>&1 grep -w bash <<<"$x"', '>&2 grep -q bash <<<"$x"', 'rg bash <<<"$x"', 'man bash <<<"$x"', 'which bash <<<"$x"',
                        'time grep -q bash <<<"$x"', 'env X=1 grep bash <<<"$x"', '>/tmp/echo bash <<<"ls"'):
            with self.subTest(command=command):
                self.assertIsNone(reason(command), command)

    def test_an_over_linked_chain_does_not_hide_a_shell(self):
        for command in (f'echo ">" & bash <<<"{BAD}"', f'echo a & >/tmp/o bash <<<"{BAD}"', f'echo a >&2 bash <<<"{BAD}"'):
            with self.subTest(command=command):
                self.assertIn("no --branch", reason(command) or "")

    def test_the_existing_heads_keep_their_behavior(self):
        self.assertIn("no --branch", reason(BAD) or "")
        self.assertIsNone(reason(GOOD))
        self.assertIsNone(reason(f'echo "{BAD}"'))
        self.assertIn("no --branch", reason(f'bash -c "{BAD}"') or "")
        self.assertIsNone(reason("ls | wc -l"))


class FedTextSyntaxTest(unittest.TestCase):
    def test_an_unreadable_command_with_no_gated_text_is_allowed(self):
        self.assertIsNone(reason("echo 'x"))
        self.assertIsNone(reason("echo x | bash <<<'y"))

    def test_the_spec_examples_of_option_words(self):
        self.assertIsNotNone(reason(f'echo "{BAD}" | bash -s -- script.sh'))
        self.assertIsNone(reason(f'echo "{BAD}" | bash -- script.sh'))
        self.assertIsNotNone(reason(f'echo -e x | bash -so script.sh'))
        self.assertIsNone(reason(f'echo -e x | bash -o pipefail script.sh'))
        self.assertIsNotNone(reason(f'echo -e x | bash -o pipefail'))

    def test_printf_and_echo_text_rules(self):
        self.assertIsNone(reason("printf ls | bash"))
        self.assertIsNotNone(reason("printf -v x | bash"))
        self.assertIsNone(reason("printf -- -v x | bash"))
        self.assertIsNotNone(reason("echo -ne ls | bash"))
        self.assertIsNone(reason("echo -n ls | bash"))
        self.assertIsNone(reason("echo -nn ls | bash"))


if __name__ == "__main__":
    unittest.main()
