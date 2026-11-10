import json
import os
import stat
import unittest

from cleanup_support import CleanupCase, HANDLE


class LineageCase(CleanupCase):
    """No other proof holds: the anchor is another worktree and the creator is the terminal `term_a`."""

    def setUp(self):
        super().setUp()
        self.tmp = os.path.join(self.root, "tmp")
        self.folder = os.path.join(self.tmp, "claude-context-handoff")
        os.makedirs(self.folder, mode=0o700)
        self.env["TMPDIR"] = self.tmp
        self.stub_show(caller="term_a")

    def write_lineage(self, *links, raw=None):
        text = raw if raw is not None else "".join(
            json.dumps({"successor": s, "predecessor": p, "time": 1.0, "predecessor_session": "x", "successor_session": "y"}) + "\n"
            for s, p in links)
        with open(os.path.join(self.folder, "lineage.jsonl"), "w", encoding="utf-8") as handle:
            handle.write(text)

    def assert_refused(self, result):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(len(self.starts(result, "Ownership")), 1)
        self.assertIn(f"! ~/.claude/hooks/worktree-cleanup/cleanup --skip-ownership {self.wt}", self.lines(result))
        self.assert_unchanged()

    def assert_passes(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(os.path.exists(self.wt))


class ChainTest(LineageCase):
    def test_the_predecessor_created_it(self):
        self.write_lineage((HANDLE, "term_a"))
        self.assert_passes(self.run_cleanup(self.wt))

    def test_the_grandpredecessor_created_it(self):
        self.write_lineage(("term_b", "term_a"), (HANDLE, "term_b"))
        self.assert_passes(self.run_cleanup(self.wt))

    def test_a_terminal_outside_the_chain_is_refused(self):
        self.write_lineage(("term_x", "term_a"))
        self.assert_refused(self.run_cleanup(self.wt))

    def test_a_successor_of_the_creator_in_another_branch_is_refused(self):
        self.write_lineage(("term_b", "term_a"), (HANDLE, "term_other"))
        self.assert_refused(self.run_cleanup(self.wt))

    def test_a_link_with_no_line_stops_the_chain(self):
        self.write_lineage((HANDLE, "term_b"))
        self.assert_refused(self.run_cleanup(self.wt))

    def test_the_chain_stops_after_20_steps(self):
        names = [HANDLE] + [f"term_{i}" for i in range(1, 20)] + ["term_a"]
        self.write_lineage(*zip(names, names[1:]))  # term_a is the 20th predecessor
        self.assert_passes(self.run_cleanup(self.wt))

    def test_a_chain_of_21_steps_is_refused(self):
        names = [HANDLE] + [f"term_{i}" for i in range(1, 21)] + ["term_a"]
        self.write_lineage(*zip(names, names[1:]))
        self.assert_refused(self.run_cleanup(self.wt))

    def test_a_cycle_is_refused(self):
        self.write_lineage((HANDLE, "term_b"), ("term_b", HANDLE))
        self.assert_refused(self.run_cleanup(self.wt))

    def test_an_empty_handle_is_refused(self):
        self.write_lineage(("", "term_a"))
        self.assert_refused(self.run_cleanup(self.wt, handle=""))


class FailClosedTest(LineageCase):
    def test_a_missing_file_is_refused(self):
        self.assert_refused(self.run_cleanup(self.wt))

    def test_a_malformed_line_is_refused_even_after_a_good_link(self):
        good = json.dumps({"successor": HANDLE, "predecessor": "term_a"}) + "\n"
        for bad in ("not json\n", "[1]\n", json.dumps({"successor": HANDLE}) + "\n",
                    json.dumps({"successor": 1, "predecessor": "term_a"}) + "\n"):
            with self.subTest(bad=bad):
                self.write_lineage(raw=good + bad)
                self.assert_refused(self.run_cleanup(self.wt))

    def test_two_lines_for_one_successor_are_refused(self):
        self.write_lineage((HANDLE, "term_a"), (HANDLE, "term_b"))
        self.assert_refused(self.run_cleanup(self.wt))

    def test_a_symlink_is_refused(self):
        real = os.path.join(self.tmp, "real.jsonl")
        with open(real, "w") as handle:
            handle.write(json.dumps({"successor": HANDLE, "predecessor": "term_a"}) + "\n")
        os.symlink(real, os.path.join(self.folder, "lineage.jsonl"))
        self.assert_refused(self.run_cleanup(self.wt))

    def test_a_folder_that_is_not_private_is_refused(self):
        self.write_lineage((HANDLE, "term_a"))
        os.chmod(self.folder, 0o755)
        self.assert_refused(self.run_cleanup(self.wt))

    def test_a_file_over_the_limit_is_refused(self):
        self.write_lineage((HANDLE, "term_a"), raw=None)
        with open(os.path.join(self.folder, "lineage.jsonl"), "a") as handle:
            handle.write(" " * (4 * 1024 * 1024))
        self.assert_refused(self.run_cleanup(self.wt))

    def test_a_fifo_is_refused(self):
        os.mkfifo(os.path.join(self.folder, "lineage.jsonl"))
        self.assertTrue(stat.S_ISFIFO(os.lstat(os.path.join(self.folder, "lineage.jsonl")).st_mode))
        self.assert_refused(self.run_cleanup(self.wt))


if __name__ == "__main__":
    unittest.main()
