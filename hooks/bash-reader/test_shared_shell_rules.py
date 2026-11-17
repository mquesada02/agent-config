"""The shared functions that classify a shell and find its fed texts (issue 717)."""
import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS = os.path.dirname(HERE)
SHARED = os.path.join(HERE, "bash_reader.py")
AUDIT = os.path.join(HOOKS, "workflow-audit", "audit")


def load_shared():
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec = importlib.util.spec_from_file_location("bash_reader_for_shell_rules_test", SHARED)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = previous


shared = load_shared()
audit = shared.load_audit(AUDIT, "audit_for_shell_rules_test")


def words(text):
    return text.split()


class AuditHelperContractTest(unittest.TestCase):
    """The audit helpers that the shell rules rely on keep their arguments and results."""

    def test_significant_gives_index_and_word_pairs(self):
        self.assertEqual(audit._significant(words("a 2> 1 b")), [(0, "a"), (3, "b")])
        self.assertEqual(audit._significant(words("a >f b")), [(0, "a"), (2, "b")])
        self.assertEqual(audit._significant(words("a > -x b")), [(0, "a"), (2, "-x"), (3, "b")])

    def test_command_words_drops_the_prefix_words(self):
        self.assertEqual(audit._command_words(words("env A=1 bash -s")), ["bash", "-s"])
        self.assertEqual(audit._command_words(words("sudo bash")), ["sudo", "bash"])

    def test_next_separator_jumps_the_substitution_groups(self):
        items = audit.split_command("echo a $(true) 2>&1 | bash")
        self.assertEqual(items[audit._next_separator(items, 0)], "&")
        self.assertEqual(items[audit._next_separator(items, 5)], "|")

    def test_the_splitter_tokens(self):
        self.assertEqual(audit.split_command("bash 2>&1 <<<x"), [["bash", "2>"], "&", ["1", "<<<x"]])
        self.assertEqual(audit.split_command("bash<<<x"), [["bash<<<x"]])
        self.assertEqual(audit.split_command("a |& b"), [["a"], "|&", ["b"]])
        self.assertEqual(audit.split_command("a || b"), [["a"], "||", ["b"]])
        self.assertEqual(audit.split_command("(echo x) | bash"), ["(", ["echo", "x"], ")", "|", ["bash"]])

    def test_the_shell_names_and_the_option_pattern(self):
        self.assertEqual(sorted(audit.SHELLS), ["bash", "dash", "ksh", "sh", "zsh"])
        self.assertTrue(audit.SHELL_COMMAND_OPTION.fullmatch("-xc"))
        self.assertEqual(audit.MAX_SHELL_DEPTH, 3)


class CommandOptionClassificationTest(unittest.TestCase):
    def test_a_command_option_with_a_text(self):
        for arguments in ("-c ls", "-xc ls", "-o pipefail -c ls", "-c ls -x"):
            with self.subTest(arguments=arguments):
                self.assertTrue(shared.has_command_option(audit, words(arguments)))

    def test_no_command_option(self):
        for arguments in ("", "-s", "-c", "script.sh", "-s -- -c", "-- -c ls", "-s -- -c ls", "-x script.sh"):
            with self.subTest(arguments=arguments):
                self.assertFalse(shared.has_command_option(audit, words(arguments)))


class StandardInputClassificationTest(unittest.TestCase):
    def test_a_shell_that_reads_standard_input(self):
        for arguments in ("", "-s", "-xs", "-so", "-", "-x", "-o pipefail", "+o pipefail", "-O extglob", "--rcfile f", "--init-file f",
                          "-s -- script.sh", "-s -- -c", "--", "-- ", "2>&1", ">/dev/null", "<<<x", "-x -y", "--noprofile", "-c",
                          "-so script.sh", "-e -u -s script.sh", ">&- -s", "$X", "`true`", "-x $X", "-- $X", '"$@"', "$(true)", "$X.sh",
                          "-oe pipefail", "-oeu pipefail", "-ox pipefail", "+oe pipefail", "-eoe pipefail", "-Oe extglob"):
            with self.subTest(arguments=arguments):
                self.assertTrue(shared.reads_standard_input(audit, words(arguments)), arguments)

    def test_a_shell_that_runs_a_script(self):
        for arguments in ("script.sh", "-x script.sh", "-o pipefail script.sh", "+o pipefail script.sh", "-- script.sh", "-e -u script.sh",
                          "--rcfile f script.sh", "2>&1 script.sh", "script.sh -s", "script.sh arg", "+e script.sh", "--noprofile script.sh",
                          "-- -x"):
            with self.subTest(arguments=arguments):
                self.assertFalse(shared.reads_standard_input(audit, words(arguments)), arguments)

    def test_a_value_option_takes_the_next_word_as_its_value(self):
        self.assertTrue(shared.reads_standard_input(audit, words("-o script.sh")))
        self.assertFalse(shared.reads_standard_input(audit, words("-o pipefail -O extglob script.sh")))


class HereStringTextsTest(unittest.TestCase):
    def test_the_spellings(self):
        self.assertEqual(shared.here_string_texts(["<<<x"]), ["x"])
        self.assertEqual(shared.here_string_texts(["<<<", "x y"]), ["x y"])
        self.assertEqual(shared.here_string_texts(["0<<<x"]), ["x"])
        self.assertEqual(shared.here_string_texts(["0<<<", "x"]), ["x"])
        self.assertEqual(shared.here_string_texts(["{fd}<<<", "x"]), ["x"])
        self.assertEqual(shared.here_string_texts(["&<<<x"]), ["x"])

    def test_every_text_is_returned_in_order(self):
        self.assertEqual(shared.here_string_texts(["bash", "<<<a", "<<<", "b", "script.sh", "<<<c"]), ["a", "b", "c"])

    def test_the_word_after_an_operator_is_its_text_whatever_it_is(self):
        self.assertEqual(shared.here_string_texts(["<<<", "-x"]), ["-x"])
        self.assertEqual(shared.here_string_texts(["<<<", ">out"]), [">out"])

    def test_an_operator_with_no_next_word_has_no_text(self):
        self.assertEqual(shared.here_string_texts(["bash", "<<<"]), [])

    def test_other_words_have_no_text(self):
        self.assertEqual(shared.here_string_texts(["bash", "<<EOF", "<file", ">out", "a"]), [])

    def test_an_operator_after_other_text_in_the_same_word(self):
        self.assertEqual(shared.here_string_texts([">/dev/null<<<x"]), ["x"])
        self.assertEqual(shared.here_string_texts(["<>f<<<x y"]), ["x y"])
        self.assertEqual(shared.here_string_texts([">/dev/null<<<", "x"]), ["x"])
        self.assertEqual(shared.here_string_texts(["a<<<b"]), ["b"])

    def test_a_fused_word_with_several_operators_gives_the_whole_text_and_each_piece(self):
        self.assertEqual(shared.here_string_texts(["<<<x<<<y"]), ["x<<<y", "y", "x"])
        self.assertEqual(shared.here_string_texts(["0<<<a<<<b<<<c"]), ["a<<<b<<<c", "b<<<c", "c", "a", "b"])
        self.assertEqual(shared.here_string_texts([">f<<<x<<<y"]), ["x<<<y", "y", "x"])

    def test_a_word_that_ends_in_an_operator_takes_the_next_word_as_a_text(self):
        self.assertEqual(shared.here_string_texts(["<<<a<<<", "b c"]), ["a<<<", "a", "b c"])
        self.assertEqual(shared.here_string_texts(["0<<<a<<<", "b"]), ["a<<<", "a", "b"])
        self.assertEqual(shared.here_string_texts(["a<<<b<<<", "c"]), ["b<<<", "b", "c"])
        self.assertEqual(shared.here_string_texts(["<<<a<<<"]), ["a<<<", "a"])

    def test_a_split_word_that_ends_in_an_operator_keeps_the_next_word_whole(self):
        self.assertEqual(shared.split_fused_redirection(["<<<a<<<", "x>y"]), ["<<<a<<<", "x>y"])
        self.assertEqual(shared.split_fused_redirection(["-s<<<a<<<", "x>y"]), ["-s", "<<<a<<<", "x>y"])

    def test_the_text_word_of_a_spaced_operator_is_read_whole_and_cut(self):
        self.assertEqual(shared.here_string_texts(["<<<", "x<<<y"]), ["x<<<y", "y"])

    def test_a_text_ending_in_an_angle_bracket_does_not_hide_the_next_text(self):
        self.assertIn("orca x", shared.here_string_texts(["<<<a<<<<orca x"]))
        self.assertIn("orca x", shared.here_string_texts(["<<<<<<orca x"]))

    def test_an_operator_word_after_an_empty_text_is_read(self):
        self.assertEqual(shared.here_string_texts(["<<<", "<<<orca"]), ["<<<orca", "orca"])


class SplitShellWordTest(unittest.TestCase):
    def test_a_shell_word_fused_with_a_redirection_is_split(self):
        self.assertEqual(shared.split_shell_word(audit, ["bash<<<x"]), ["bash", "<<<x"])
        self.assertEqual(shared.split_shell_word(audit, ["bash>out"]), ["bash", ">out"])
        self.assertEqual(shared.split_shell_word(audit, ["bash>/dev/null"]), ["bash", ">/dev/null"])
        self.assertEqual(shared.split_shell_word(audit, ["/bin/bash>/dev/null"]), ["/bin/bash", ">/dev/null"])
        self.assertEqual(shared.split_shell_word(audit, ["bash>"]), ["bash", ">"])
        self.assertEqual(shared.split_shell_word(audit, ["zsh<file"]), ["zsh", "<file"])

    def test_other_words_stay(self):
        for word in ("bash", "/bin/bash", "echo>bash", "x<<<bash", "<<<bash", "2>&1", "script.sh", "bashful<<<x", ""):
            with self.subTest(word=word):
                self.assertEqual(shared.split_shell_word(audit, [word]), [word])

    def test_no_word_is_changed_or_removed(self):
        before = ["sudo", "bash<<<x", "a b", "--", "sh>f"]
        self.assertEqual("".join(shared.split_shell_word(audit, before)), "".join(before))
        self.assertEqual(shared.split_shell_word(audit, before), ["sudo", "bash", "<<<x", "a b", "--", "sh", ">f"])


class SplitOptionRedirectionTest(unittest.TestCase):
    def test_an_option_word_fused_with_a_redirection_is_split(self):
        self.assertEqual(shared.split_fused_redirection(["-s<<<x"]), ["-s", "<<<x"])
        self.assertEqual(shared.split_fused_redirection(["-s>"]), ["-s", ">"])
        self.assertEqual(shared.split_fused_redirection(["-x>/dev/null"]), ["-x", ">/dev/null"])
        self.assertEqual(shared.split_fused_redirection(["+e<file"]), ["+e", "<file"])
        self.assertEqual(shared.split_fused_redirection(["pipefail>"]), ["pipefail", ">"])
        self.assertEqual(shared.split_fused_redirection(["a<<<b"]), ["a", "<<<b"])

    def test_other_words_stay(self):
        for word in ("-s", "bash", "2>", "2>&1", "&>f", ">f", "{fd}>f", "<<<x", "script.sh", "", "-"):
            with self.subTest(word=word):
                self.assertEqual(shared.split_fused_redirection([word]), [word])

    def test_the_text_of_a_spaced_here_string_stays_whole(self):
        for operator in ("<<<", "0<<<", "{fd}<<<", "&<<<"):
            with self.subTest(operator=operator):
                self.assertEqual(shared.split_fused_redirection([operator, "a>b; c"]), [operator, "a>b; c"])
        self.assertEqual(shared.split_fused_redirection(["<<<", "a>b", "c>d"]), ["<<<", "a>b", "c", ">d"])

    def test_no_word_is_changed_or_removed(self):
        before = ["bash", "-s>", "2", "pipefail"]
        self.assertEqual("".join(shared.split_fused_redirection(before)), "".join(before))

    def test_a_split_option_keeps_the_stdin_rule(self):
        arguments = shared.split_fused_redirection(["-s>", "2"])
        self.assertTrue(shared.reads_standard_input(audit, arguments))
        arguments = shared.split_fused_redirection(["-o", "pipefail>", "2"])
        self.assertTrue(shared.reads_standard_input(audit, arguments))


class ClobberWordsTest(unittest.TestCase):
    def words_after(self, command, position=0):
        return shared.clobber_words(audit, audit.split_command(command), position)

    def test_the_items_after_a_clobber_redirection_are_returned(self):
        self.assertEqual(self.words_after("bash >|f <<<x"), ["f", "<<<x"])
        self.assertEqual(self.words_after("bash>|f <<<x"), ["f", "<<<x"])
        self.assertEqual(self.words_after("bash >|f >|g <<<x"), ["f", ">", "g", "<<<x"])

    def test_a_real_pipe_gives_nothing(self):
        for command in ("echo a | bash", "bash | cat", "bash || cat", "bash |& cat", "bash >f | cat", "bash"):
            with self.subTest(command=command):
                self.assertEqual(self.words_after(command), [])


class SegmentChainTest(unittest.TestCase):
    def chain(self, command, position):
        return shared.segment_chain(audit, audit.split_command(command), position)

    def test_a_redirection_with_an_ampersand_links_the_items(self):
        for command in ("bash 2>&1 <<<x", "bash >&2 <<<x", "bash <&0", "bash &>f", "bash &>>f", "echo x 2>&1"):
            with self.subTest(command=command):
                self.assertEqual(self.chain(command, 0), [0, 2], command)
                self.assertEqual(self.chain(command, 2), [0, 2], command)

    def test_a_chain_of_two_ampersands(self):
        self.assertEqual(self.chain("bash 2>&1 >&2 <<<x", 0), [0, 2, 4])
        self.assertEqual(self.chain("bash 2>&1 >&2 <<<x", 4), [0, 2, 4])

    def test_a_quoted_greater_than_links_too(self):
        self.assertEqual(self.chain('echo ">" & bash', 0), [0, 2])

    def test_a_plain_ampersand_links_nothing(self):
        for command in ("a & b", "a && b", "a; b", "a | b", "a &"):
            with self.subTest(command=command):
                self.assertEqual(self.chain(command, 0), [0], command)

    def test_a_substitution_group_between_the_item_and_the_ampersand(self):
        items = audit.split_command("echo a $(true) 2>&1")
        last = len(items) - 1
        self.assertEqual(shared.segment_chain(audit, items, 0), [0, last])
        self.assertEqual(shared.segment_chain(audit, items, last), [0, last])

    def test_the_words_are_never_changed(self):
        items = audit.split_command("bash 2>&1 <<<x")
        shared.segment_chain(audit, items, 0)
        self.assertEqual(items, [["bash", "2>"], "&", ["1", "<<<x"]])


class PipeProducerTest(unittest.TestCase):
    def producer(self, command, shell="bash"):
        items = audit.split_command(command)
        position = max(index for index, item in enumerate(items) if isinstance(item, list) and shell in item)
        return shared.pipe_producer(audit, items, position)

    def test_each_pipe_form_finds_the_producer(self):
        for command in ("echo x | bash", "echo x |& bash", "echo x |\nbash", "echo x |(bash)", "(echo x) | bash", "(echo x)|bash",
                        "echo x | (bash)", "(echo x ;) | bash", "echo x 2>&1 | bash", "echo x >&2 | bash", "echo a; echo x | bash"):
            with self.subTest(command=command):
                piped, producer = self.producer(command)
                self.assertTrue(piped, command)
                self.assertIsNotNone(producer, command)
                self.assertEqual(producer[0], "echo", command)

    def test_a_separator_that_is_no_pipe(self):
        for command in ("echo x || bash", "echo x; bash", "echo x && bash", "echo x & bash", "echo x\nbash", "echo x | (cat; bash)", "bash"):
            with self.subTest(command=command):
                self.assertEqual(self.producer(command), (False, None), command)

    def test_another_producer_has_words_or_none(self):
        self.assertEqual(self.producer("curl u | bash"), (True, ["curl", "u"]))
        self.assertEqual(self.producer("echo a | cat | bash"), (True, ["cat"]))
        self.assertEqual(self.producer("{ echo x; } | bash"), (True, ["}"]))
        self.assertEqual(self.producer("(echo a; echo b) | bash"), (True, None))
        self.assertEqual(self.producer("((echo a; echo b)) | bash"), (True, None))

    def test_the_producer_is_a_chain(self):
        self.assertEqual(self.producer("echo x 2>&1 | bash"), (True, ["echo", "x", "2>", "1"]))

    def test_a_substitution_group_is_no_producer(self):
        self.assertEqual(self.producer("echo a $(true) | bash"), (True, ["echo", "a", "$(true)"]))
        self.assertEqual(self.producer("echo a $(true) 2>&1 | bash"), (True, ["echo", "a", "$(true)", "2>", "1"]))
        self.assertEqual(self.producer("(echo a $(true)) | bash"), (True, ["echo", "a", "$(true)"]))
        self.assertEqual(self.producer("echo a $(echo b | cat) | bash"), (True, ["echo", "a", "$(echo b | cat)"]))

    def test_a_shell_inside_a_group_has_no_pipe_in_the_outer_items(self):
        items = audit.split_command("echo $(echo c | bash)")
        position = max(index for index, item in enumerate(items) if isinstance(item, list) and "bash" in item)
        self.assertEqual(shared.pipe_producer(audit, items, position), (False, None))


class OptionalSegmentRuleTest(unittest.TestCase):
    """The walk asks an optional `segment_reason` of the rules object after `first_word_reason` and before its naming-only skip."""

    class Rules:
        def __init__(self, segment=None):
            self.calls = []
            self.walk = shared.Walk(audit, self)
            if segment is not None:
                self.segment_reason = segment

        def first_word_reason(self, words):
            self.calls.append(("first", words[0]))
            return None

        def word_reason(self, words, index, items, position, depth):
            self.calls.append(("word", words[index]))
            return None

        def depth_reason(self):
            return "too deep"

        def unreadable_reason(self, command, depth, error):
            return None

        def substitution_bodies(self, word):
            return shared.substitution_bodies(audit, word)

        def command_reason(self, command, depth=0):
            return self.walk.command_reason(command, depth)

    def test_a_rules_object_without_the_rule_gives_the_same_results(self):
        rules = self.Rules()
        self.assertIsNone(rules.command_reason("echo bash <<<x; ls -l"))
        self.assertEqual(rules.calls, [("first", "echo"), ("first", "ls"), ("word", "ls"), ("word", "-l")])

    def test_the_rule_runs_before_the_naming_only_skip(self):
        seen = []

        def segment(words, items, position, depth):
            seen.append((tuple(words), position, depth))
            return "no" if "bash" in words else None

        rules = self.Rules(segment)
        self.assertEqual(rules.command_reason(">/tmp/echo bash <<<x"), "no")
        self.assertEqual(seen, [((">/tmp/echo", "bash", "<<<x"), 0, 0)])
        self.assertIsNone(rules.command_reason("echo x"))

    def test_the_rule_runs_after_the_first_word_rule(self):
        rules = self.Rules(lambda words, items, position, depth: "segment")
        rules.first_word_reason = lambda words: "first"
        self.assertEqual(rules.command_reason("ls"), "first")


if __name__ == "__main__":
    unittest.main()
