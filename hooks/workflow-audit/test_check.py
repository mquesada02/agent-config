import os
import re
import unittest

from audit_support import VERSION, AuditCase, bash_row, call_row, edit_row, finding_event, round_event, stamp, subagent_rows

DIGEST_MARKER = "--- digest ---"
S_LINE = re.compile(r"(S[1-9]|XC) (pass|fail)")
LIMIT = 51200  # 50 KB, written out here on purpose: the test checks the number in the spec, not the code's own constant


def prompt_row(text, seconds=0):
    return {"type": "user", "timestamp": stamp(seconds), "version": VERSION, "message": {"role": "user", "content": text}}


class CheckCase(AuditCase):
    def check(self, worktree=None, *extra):
        return self.audit("check", "--worktree", worktree or self.repo, *extra)

    def parts(self, result):
        """(the lines before the digest marker, the size line, the digest text)."""
        self.assertEqual(result.returncode, 0, result.stderr)
        text = result.stdout.decode()
        head, marker, digest = text.partition("\n" + DIGEST_MARKER + "\n")
        self.assertTrue(marker, text[:300])
        size = head.splitlines()[-1]
        return head.splitlines()[:-1], size, digest.removesuffix("\n")

    def runtime_files(self):
        return sorted(os.listdir(self.runtime)) if os.path.isdir(self.runtime) else []


class OutputTest(CheckCase):
    def test_prints_every_item_in_the_record_order_and_the_result(self):
        self.start_branch("feature", "feat: a")
        lines, _, _ = self.parts(self.check())
        ids = [S_LINE.fullmatch(line).group(1) for line in lines if S_LINE.fullmatch(line)]
        self.assertEqual(ids, ["S1", "S2", "S3", "S4", "S5", "S6", "XC", "S7", "S8", "S9"])
        self.assertTrue(all(S_LINE.fullmatch(line).group(2) == "pass" for line in lines if S_LINE.fullmatch(line)))
        self.assertEqual(lines[-1], "result pass")

    def test_evidence_follows_its_item_indented(self):
        self.start_branch("feature", "feat: a")
        lines, _, _ = self.parts(self.check())
        index = lines.index("S8 pass")
        self.assertTrue(lines[index + 1].startswith("  "), lines[index:index + 2])

    def test_a_failed_item_is_output_not_an_error(self):
        self.start_branch("feature", "not a conventional header")
        lines, _, _ = self.parts(self.check())
        self.assertIn("S8 fail", lines)
        self.assertEqual(lines[-1], "result fail")

    def test_the_size_line_is_the_size_of_the_digest(self):
        self.start_branch("feature", "feat: a")
        _, size, digest = self.parts(self.check())
        self.assertEqual(size, f"digest {len(digest.encode('utf-8'))} bytes")

    def test_writes_no_file(self):
        self.start_branch("feature", "feat: a")
        before = self.runtime_files()
        self.check()
        self.assertEqual(self.runtime_files(), before)

    def test_works_before_the_push(self):
        self.git("checkout", "-b", "feature")
        self.commit("feat: a")
        lines, _, _ = self.parts(self.check())
        self.assertIn("S8 pass", lines)


class RefusalTest(CheckCase):
    def refused(self, result):
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertEqual(result.stdout, b"")
        self.assertTrue(result.stderr)

    def test_a_path_that_is_not_a_worktree(self):
        self.refused(self.check(self.root))

    def test_a_detached_head(self):
        self.start_branch("feature", "feat: a")
        self.git("checkout", "--detach")
        self.refused(self.check())

    def test_no_origin_url(self):
        self.start_branch("feature", "feat: a")
        self.git("remote", "remove", "origin")
        self.refused(self.check())

    def test_the_argument_form_is_strict(self):
        self.start_branch("feature", "feat: a")
        for args in (("check",), ("check", "--worktree"), ("check", "--worktree", self.repo, "--llm", self.llm_path),
                     ("check", "--llm", self.llm_path), ("check", "--worktree", self.repo, "extra")):
            with self.subTest(args):
                self.refused(self.audit(*args))

    def test_an_unsafe_runtime_folder(self):
        self.start_branch("feature", "feat: a")
        os.chmod(self.runtime, 0o755)
        self.refused(self.check())


class DigestTest(CheckCase):
    default_session = False

    def session(self, rows, subagents=None, name="main-session"):
        subagents = {"rev1": subagent_rows()} if subagents is None else subagents  # the reviewer of the default ledger
        return self.register_session(name, [edit_row(os.path.join(self.repo, "edited.txt"), "e1", 2)] + rows, subagents=subagents)

    def test_holds_the_ledger_the_commits_and_the_session(self):
        self.default_ledger = False
        self.session([
            prompt_row("Invented prompt: change the sample.", 1),
            bash_row("make test", "b1", 5),
            call_row("Agent", {"description": "Invented review", "subagent_type": "general-purpose", "model": "sonnet"}, "a1", 6),
            call_row("Skill", {"skill": "invented-skill"}, "k1", 7),
        ], subagents={"rev1": subagent_rows()})
        self.start_branch("feature", "feat: first change")
        self.write_ledger("feature", [round_event()])
        _, _, digest = self.parts(self.check())
        for needle in ("code-review", "feat: first change", "Invented prompt: change the sample.", "2026-10-15T12:00:05Z make test",
                       "edited.txt", "Invented review", "general-purpose", "sonnet", "invented-skill", "agent-rev1.jsonl", "claude-sonnet-5-5"):
            with self.subTest(needle):
                self.assertIn(needle, digest)

    def test_the_first_prompt_skips_a_task_notification(self):
        self.session([prompt_row("<task-notification>x</task-notification>", 1), prompt_row("Invented real prompt", 2)])
        self.start_branch("feature", "feat: a")
        _, _, digest = self.parts(self.check())
        self.assertIn("Invented real prompt", digest)

    def test_a_session_with_no_prompt_shows_none(self):
        self.session([])
        self.start_branch("feature", "feat: a")
        _, _, digest = self.parts(self.check())
        self.assertIn("(none)", digest)

    def test_a_launch_with_missing_fields_fails_no_item(self):
        self.session([call_row("Agent", {}, "a1", 3), call_row("Skill", {}, "k1", 4)])
        self.start_branch("feature", "feat: a")
        lines, _, digest = self.parts(self.check())
        self.assertEqual(lines[-1], "result pass")
        self.assertIn("?", digest)

    def test_a_launch_with_a_bad_id_still_fails_the_audit(self):
        self.session([call_row("Agent", {}, 7, 3)])
        self.start_branch("feature", "feat: a")
        lines, _, digest = self.parts(self.check())
        self.assertEqual(lines[-1], "result fail")
        self.assertIn("digest unavailable:", digest)

    def test_a_lone_surrogate_in_the_text_does_not_stop_check(self):
        self.session([prompt_row("x\udc80 prompt", 1), bash_row("echo \ud800", "b1", 3)])
        self.start_branch("feature", "feat: a")
        lines, size, digest = self.parts(self.check())
        self.assertEqual(lines[-1], "result pass")
        self.assertIn("prompt", digest)
        self.assertEqual(size, f"digest {len(digest.encode('utf-8'))} bytes")

    def test_a_long_session_is_cut_to_the_limit_and_says_so(self):
        rows = [bash_row("echo " + "ä€" * 100 + str(n), f"b{n}", 3) for n in range(3000)]
        rows += [call_row("Agent", {"description": "x" * 500, "subagent_type": "y" * 500, "model": "z" * 500}, f"a{n}", 4) for n in range(500)]
        self.session(rows)
        self.start_branch("feature", "feat: a")
        _, size, digest = self.parts(self.check())
        self.assertLessEqual(len(digest.encode("utf-8")), LIMIT)
        self.assertEqual(size, f"digest {len(digest.encode('utf-8'))} bytes")
        self.assertRegex(digest, r"\[\d+ more lines omitted\]")
        digest.encode("utf-8")  # still valid text

    def test_a_long_ledger_and_a_long_commit_list_are_cut_too(self):
        self.default_ledger = False
        self.session([])
        self.git("checkout", "-b", "feature")
        for n in range(400):
            self.commit(f"feat: change number {n} " + "w" * 100)
        self.git("push", "-u", "origin", "feature")
        events = [round_event()] + [
            finding_event(f"F{n}", kind="Minor") for n in range(400)]
        self.write_ledger("feature", events)
        _, _, digest = self.parts(self.check())
        self.assertLessEqual(len(digest.encode("utf-8")), LIMIT)
        self.assertGreaterEqual(len(re.findall(r"\[\d+ more lines omitted\]", digest)), 2)

    def test_unreadable_transcripts_give_one_line_and_failed_items(self):
        self.start_branch("feature", "feat: a")
        self.register_path("gone", os.path.join(self.root, "missing.jsonl"))
        lines, _, digest = self.parts(self.check())
        self.assertIn("S1 fail", lines)
        self.assertIn("digest unavailable: evidence unavailable", digest)
        self.assertIn("feat: a", digest)

    def test_a_missing_ledger_is_named(self):
        self.default_ledger = False
        self.session([])
        self.start_branch("feature", "feat: a")
        _, _, digest = self.parts(self.check())
        self.assertIn("ledger unavailable: evidence unavailable: no ledger for feature", digest)

    def test_no_default_branch_gives_commits_unavailable(self):
        self.session([])
        self.start_branch("feature", "feat: a")
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        lines, _, digest = self.parts(self.check())
        self.assertIn("S8 fail", lines)
        self.assertIn("commits unavailable: evidence unavailable: none of origin/HEAD, origin/main and origin/master exists", digest)


if __name__ == "__main__":
    unittest.main()
