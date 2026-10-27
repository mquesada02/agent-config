import os
import pathlib
import re
import unittest

from audit_support import VERSION, AuditCase, bash_row, call_row, edit_row, finding_event, round_event, stamp, subagent_rows

DIGEST_MARKER = "--- digest ---"
S_LINE = re.compile(r"(S[1-9]|XC) (pass|fail)")
OLD_SESSIONS_BUDGET = 30720  # the digest budget before the sessions moved to `audit sessions show`
LIMIT = 28672  # 28 KB, written out here on purpose: the test checks the number in the spec, not the code's own constant


def prompt_row(text, seconds=0):
    return {"type": "user", "timestamp": stamp(seconds), "version": VERSION, "message": {"role": "user", "content": text}}


def long_rows():
    """Synthetic rows that fill far more than the old 30 KB sessions budget: 3000 Bash calls and 500 launches."""
    rows = [bash_row("echo " + "ä€" * 100 + str(n), f"b{n}", 3) for n in range(3000)]
    rows += [call_row("Agent", {"description": "x" * 500, "subagent_type": "y" * 500, "model": "z" * 500}, f"a{n}", 4) for n in range(500)]
    return rows


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


class SessionCase(CheckCase):
    default_session = False

    def session(self, rows, subagents=None, name="main-session"):
        subagents = {"rev1": subagent_rows()} if subagents is None else subagents  # the reviewer of the default ledger
        return self.register_session(name, [edit_row(os.path.join(self.repo, "edited.txt"), "e1", 2)] + rows, subagents=subagents)

    def show(self, worktree=None, *extra):
        return self.audit("sessions", "show", "--worktree", worktree or self.repo, *extra)


class DigestTest(SessionCase):
    def shown(self):
        """The text of `audit sessions show` for the same worktree."""
        result = self.show()
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.decode()

    def test_holds_the_ledger_and_the_commits_and_the_sessions_pointer_not_the_blocks(self):
        self.default_ledger = False
        self.session([
            prompt_row("Invented prompt: change the sample.", 1),
            bash_row("make test", "b1", 5),
            call_row("Agent", {"description": "Invented review", "subagent_type": "general-purpose", "model": "sonnet"}, "a1", 6),
        ], subagents={"rev1": subagent_rows()})
        self.start_branch("feature", "feat: first change")
        self.write_ledger("feature", [round_event()])
        _, _, digest = self.parts(self.check())
        self.assertIn("feat: first change", digest)
        self.assertIn("ledger: 1 events;", digest)
        for text in ("Invented prompt", "make test", "Invented review", "agent-rev1.jsonl", "session main-session"):
            with self.subTest(text):
                self.assertNotIn(text, digest)

    def test_the_sessions_section_is_one_pointer_line_with_the_count_and_the_worktree(self):
        self.session([bash_row("make test", "b1", 5)])
        self.session([bash_row("make other", "b2", 5)], name="second-session")
        self.start_branch("feature", "feat: a")
        _, _, digest = self.parts(self.check())
        pointer = ("sessions: 2 audited; read them with: python3 -I ~/.claude/hooks/workflow-audit/audit sessions show "
                   f"--worktree {self.repo}")
        self.assertEqual(digest.splitlines()[-1], pointer)
        self.assertEqual(len([line for line in digest.splitlines() if line.startswith("sessions")]), 1)
        self.assertNotIn("  bash ", digest)
        self.assertNotIn("subagent", digest)

    def test_the_first_prompt_skips_a_compaction_summary(self):
        self.session([{**prompt_row("Invented summary", 1), "isCompactSummary": True}, prompt_row("Invented real prompt", 2)])
        self.start_branch("feature", "feat: a")
        shown = self.shown()
        self.assertIn("Invented real prompt", shown)
        self.assertNotIn("Invented summary", shown)

    def test_the_first_prompt_skips_a_task_notification(self):
        self.session([prompt_row("<task-notification>x</task-notification>", 1), prompt_row("Invented real prompt", 2)])
        self.start_branch("feature", "feat: a")
        self.assertIn("Invented real prompt", self.shown())

    def test_a_session_with_no_prompt_shows_none(self):
        self.session([])
        self.start_branch("feature", "feat: a")
        self.assertIn("(none)", self.shown())

    def test_a_launch_with_missing_fields_fails_no_item(self):
        self.session([call_row("Agent", {}, "a1", 3), call_row("Skill", {}, "k1", 4)])
        self.start_branch("feature", "feat: a")
        lines, _, _ = self.parts(self.check())
        self.assertEqual(lines[-1], "result pass")
        self.assertIn("  agent: ? | ? | ?", self.shown())

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
        self.assertIn("sessions: 1 audited;", digest)
        self.assertEqual(size, f"digest {len(digest.encode('utf-8'))} bytes")

    def test_a_long_session_adds_no_omitted_lines_marker_to_the_digest(self):
        self.session(long_rows())
        self.start_branch("feature", "feat: a")
        _, size, digest = self.parts(self.check())
        self.assertLessEqual(len(digest.encode("utf-8")), LIMIT)
        self.assertEqual(size, f"digest {len(digest.encode('utf-8'))} bytes")
        self.assertNotIn("more lines omitted", digest)
        self.assertIn("sessions: 1 audited;", digest)

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
        self.assertEqual(len(re.findall(r"\[\d+ more lines omitted\]", digest)), 1)  # the commits section; the ledger section is one line
        self.assertNotIn("ledger unavailable", digest)

    def test_the_ledger_section_is_one_pointer_line_with_the_count_and_no_events(self):
        self.default_ledger = False
        self.session([])
        self.start_branch("feature", "feat: a")
        self.write_ledger("feature", [round_event(), {**finding_event(), "reason": "Invented reason text"}, finding_event("I2", kind="Minor")])
        _, _, digest = self.parts(self.check())
        pointer = ("ledger: 3 events; read them with: python3 -I ~/.claude/hooks/workflow-audit/audit ledger show "
                   f"--worktree {self.repo}")
        self.assertEqual(digest.splitlines()[0], pointer)
        self.assertEqual(len([line for line in digest.splitlines() if line.startswith("ledger")]), 1)
        for text in ("Invented reason text", '"kind"', "code-review"):
            self.assertNotIn(text, digest)

    def test_a_long_ledger_adds_no_omitted_lines_marker_to_the_digest(self):
        self.default_ledger = False
        self.session([])
        self.start_branch("feature", "feat: a")
        self.write_ledger("feature", [round_event()] + [{**finding_event(f"F{n}", kind="Minor"), "reason": "r" * 500} for n in range(100)])
        _, _, digest = self.parts(self.check())
        self.assertIn("ledger: 101 events;", digest)
        self.assertNotIn("more lines omitted", digest)

    def test_the_s_results_do_not_depend_on_the_pointer_line(self):
        self.default_ledger = False
        self.session([])
        self.start_branch("feature", "feat: a")
        self.write_ledger("feature", [round_event(), finding_event("I1", kind="Minor")] + [finding_event(f"F{n}", kind="Minor") for n in range(400)])
        lines, _, _ = self.parts(self.check())
        self.assertIn("  401 findings have no status", lines)  # S3 reads the whole ledger

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


class SessionsShowTest(SessionCase):
    def lines(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b"")
        return result.stdout.decode().splitlines()

    def digest_why(self):
        """The text after `digest unavailable: ` in the digest of `audit check` for the same worktree."""
        _, _, digest = self.parts(self.check())
        return next(line for line in digest.splitlines() if line.startswith("digest unavailable: ")).removeprefix("digest unavailable: ")

    def refused_like_ledger_show(self, worktree=None):
        result, ledger = self.show(worktree), self.audit("ledger", "show", "--worktree", worktree or self.repo)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertTrue(ledger.stderr)
        self.assertEqual(result.stderr, ledger.stderr)

    def test_prints_the_header_then_every_block_in_registry_order(self):
        self.session([prompt_row("Invented prompt: change the sample.", 1), bash_row("make test", "b1", 5),
                      call_row("Agent", {"description": "Invented review", "subagent_type": "general-purpose", "model": "sonnet"}, "a1", 6),
                      call_row("Skill", {"skill": "invented-skill"}, "k1", 7)])
        self.session([bash_row("make other", "b2", 5)], name="second-session", subagents={})
        self.start_branch("feature", "feat: a")
        lines = self.lines(self.show())
        self.assertEqual(lines[0], "sessions")
        self.assertEqual([line for line in lines if line.startswith("session ")], ["session main-session.jsonl", "session second-session.jsonl"])
        text = "\n".join(lines)
        for needle in ("  prompt: Invented prompt: change the sample.", "  edits: 1", "  edited: " + os.path.join(self.repo, "edited.txt"),
                       "  bash 2026-10-15T12:00:05Z make test", "  agent: Invented review | general-purpose | sonnet", "  skill: invented-skill",
                       "  subagent agent-rev1.jsonl first row 2000-01-01T00:00:00Z models: claude-sonnet-5-5"):
            with self.subTest(needle):
                self.assertIn(needle, text)
        self.assertLess(text.index("make test"), text.index("make other"))

    def test_a_first_session_over_the_old_budget_does_not_hide_the_second(self):
        self.session(long_rows())
        self.session([bash_row("make second", "b9", 5)], name="second-session", subagents={})
        self.start_branch("feature", "feat: a")
        result = self.show()
        lines = self.lines(result)
        self.assertGreater(len(result.stdout), OLD_SESSIONS_BUDGET)
        self.assertIn("session second-session.jsonl", lines)
        self.assertEqual(lines[-1], "  bash 2026-10-15T12:00:05Z make second")
        self.assertNotIn(b"more lines omitted", result.stdout)

    def test_a_very_large_input_is_printed_in_full(self):
        self.session(long_rows())
        self.start_branch("feature", "feat: a")
        lines = self.lines(self.show())
        self.assertEqual(len([line for line in lines if line.startswith("  bash ")]), 3000)
        self.assertEqual(len([line for line in lines if line.startswith("  agent: ")]), 500)
        self.assertIn("agent-rev1.jsonl", lines[-1])
        self.assertNotIn("more lines omitted", "\n".join(lines))

    def test_non_ascii_text_is_printed_as_is_and_a_lone_surrogate_does_not_stop_it(self):
        self.session([prompt_row("x\udc80 prompt ä€ é", 1), bash_row("echo ä€ \ud800", "b1", 3)])
        self.start_branch("feature", "feat: a")
        text = self.show().stdout.decode()
        self.assertTrue(text.startswith("sessions\n"))
        self.assertIn("prompt ä€ é", text)
        self.assertIn("echo ä€ ", text)

    def test_leaves_the_runtime_folder_unchanged_and_creates_no_lock_file(self):
        self.session([bash_row("make test", "b1", 5)])
        self.start_branch("feature", "feat: a")
        names = self.runtime_files()
        contents = {name: pathlib.Path(self.runtime, name).read_bytes() for name in names}
        self.assertEqual(self.show().returncode, 0)
        self.assertEqual(self.runtime_files(), names)
        self.assertEqual({name: pathlib.Path(self.runtime, name).read_bytes() for name in names}, contents)
        self.assertEqual([name for name in names if name.endswith(".lock")], [])

    def test_with_no_runtime_folder_it_creates_only_that_folder(self):
        self.git("checkout", "-b", "feature")
        self.assertFalse(os.path.exists(self.runtime))
        self.assertEqual(self.show().returncode, 2)
        self.assertEqual(os.listdir(self.runtime), [])
        self.assertEqual(os.stat(self.runtime).st_mode & 0o777, 0o700)

    def test_no_audited_session_prints_one_unavailable_line_with_the_why_of_the_digest(self):
        self.git("checkout", "-b", "feature")
        cases = {
            "no registered session": lambda: None,
            "a session that does not touch the worktree": lambda: self.register_session("other", [bash_row("echo hi", "b1", 1)]),
            "an unreadable transcript": lambda: self.register_path("bad", self.root),
        }
        for name, setup in cases.items():
            with self.subTest(name):
                if os.path.exists(os.path.join(self.runtime, "sessions.jsonl")):
                    os.unlink(os.path.join(self.runtime, "sessions.jsonl"))
                setup()
                result = self.show()
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stderr, b"")
                self.assertEqual(result.stdout.decode().splitlines(), [f"sessions unavailable: {self.digest_why()}"])

    def test_a_refusal_has_the_texts_of_ledger_show_and_wins_over_unavailable(self):
        self.refused_like_ledger_show(self.root)  # not a git worktree
        self.assertFalse(os.path.exists(self.runtime))
        self.git("checkout", "-b", "feature")
        self.git("checkout", "--detach")
        self.refused_like_ledger_show()
        self.git("checkout", "feature")
        self.git("remote", "remove", "origin")
        self.refused_like_ledger_show()
        self.assertFalse(os.path.exists(self.runtime))
        self.git("remote", "add", "origin", self.origin)
        os.makedirs(self.runtime)
        os.chmod(self.runtime, 0o755)
        self.refused_like_ledger_show()

    def test_the_checks_run_in_the_order_of_ledger_show(self):
        self.git("checkout", "-b", "feature")
        os.makedirs(self.runtime)
        os.chmod(self.runtime, 0o755)
        self.git("remote", "remove", "origin")
        self.refused_like_ledger_show()
        self.assertIn(b"no remote URL for origin", self.show().stderr)

    def test_a_bad_command_line_prints_the_usage_text(self):
        self.start_branch("feature", "feat: a")
        usage = self.audit("bogus").stderr
        self.assertIn(b"audit sessions show --worktree <path>", usage)
        for args in (("sessions",), ("sessions", "show"), ("sessions", "show", "--worktree"),
                     ("sessions", "show", "--worktree", self.repo, "--worktree", self.repo),
                     ("sessions", "show", "--worktree", self.repo, "extra"), ("sessions", "list", "--worktree", self.repo)):
            with self.subTest(args):
                result = self.audit(*args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(result.stderr, usage)


if __name__ == "__main__":
    unittest.main()
