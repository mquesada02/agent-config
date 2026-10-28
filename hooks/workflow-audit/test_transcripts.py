# S1 and S2: the transcript reader, through `audit record` with synthetic transcripts.
import json
import os
import re
import unittest

from audit_support import (HERE, VERSION, AuditCase, bash_row, call_row, declaration, edit_row, notification_attachment_row,
                           notification_text, notification_user_row, result_row)

UNAVAILABLE = "evidence unavailable"


class TranscriptCase(AuditCase):
    default_session = False
    test_command = "make test"

    def setUp(self):
        super().setUp()
        self.wt = self.repo

    def branch(self, files=None):
        """Branch `feature` off main with a pushed commit; `files` maps a path to its text (None removes it)."""
        files = {"CLAUDE.md": declaration(self.test_command), **(files or {})}
        self.git("checkout", "-b", "feature")
        for path, text in files.items():
            full = os.path.join(self.repo, path)
            if text is None:
                self.git("rm", "-q", path)
                continue
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as handle:
                handle.write(text)
            self.git("add", path)
        self.git("commit", "--allow-empty", "-m", "feat: declare tests")
        self.git("push", "-u", "origin", "feature")
        return self.git("rev-parse", "HEAD")

    def items(self, files=None, worktree=None):
        tip = self.branch(files) if worktree is None else worktree[1]
        result = self.record(worktree=worktree[0] if worktree else None)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return {item["id"]: item for item in self.read_record(tip)["items"]}

    def assert_item(self, items, item_id, result, text=None):
        self.assertEqual(items[item_id]["result"], result, items[item_id]["evidence"])
        if text is not None:
            self.assertIn(text, items[item_id]["evidence"])

    def unavailable(self, items):
        for name in ("S1", "S2"):
            self.assert_item(items, name, "fail", UNAVAILABLE)

    def own_edit(self, call_id="e1", seconds=10, **extra):
        return edit_row(os.path.join(self.wt, "a.txt"), call_id, seconds, **extra)


class DiscoveryTest(TranscriptCase):
    def test_each_edit_tool_selects_a_session(self):
        for tool in ("Edit", "Write", "NotebookEdit"):
            with self.subTest(tool=tool):
                self.setUp()
                self.register_session("s1", [edit_row(os.path.join(self.wt, "a.txt"), "e1", 1, tool=tool)])
                self.assert_item(self.items(), "S1", "pass", "1 sessions audited")

    def test_a_bash_command_that_names_the_worktree_selects_a_session(self):
        self.register_session("s1", [bash_row(f"ls {self.wt}/src", "b1", 1)])
        self.assert_item(self.items(), "S1", "pass", "1 sessions audited")

    def test_a_cwd_inside_the_worktree_selects_a_session(self):
        self.register_session("s1", [bash_row("ls", "b1", 1, cwd=os.path.join(self.wt, "sub"))])
        self.assert_item(self.items(), "S1", "pass", "1 sessions audited")

    def test_a_session_that_touches_another_path_is_not_audited(self):
        self.register_session("s1", [self.own_edit()])
        self.register_session("s2", [edit_row("/somewhere/else/a.txt", "e2", 1, cwd="/somewhere/else")])
        self.assert_item(self.items(), "S1", "pass", "1 sessions audited")

    def test_a_longer_path_that_starts_like_the_worktree_is_another_directory(self):
        self.register_session("s1", [bash_row(f"ls {self.wt}-2/src", "b1", 1, cwd="/elsewhere")])
        self.unavailable(self.items())

    def test_a_subagent_transcript_selects_its_session_and_its_edits_count(self):
        main_file = os.path.join(self.main, "m.txt")
        self.register_session("s1", [bash_row("echo hi", "b1", 1, cwd="/elsewhere")],
                              subagents={"a1": [edit_row(main_file, "e1", 2, cwd="/elsewhere"), bash_row(f"ls {self.wt}", "b2", 3)]})
        items = self.items()
        self.assert_item(items, "S1", "fail", "agent-a1.jsonl")
        self.assert_item(items, "S1", "fail", main_file)

    def test_a_relative_path_resolves_against_the_row_cwd(self):
        self.register_session("s1", [edit_row("sub/a.txt", "e1", 1, cwd=self.wt)])
        self.assert_item(self.items(), "S1", "pass", "1 sessions audited")

    def test_a_handoff_predecessor_and_successor_are_both_audited(self):
        self.register_session("s1", [self.own_edit("e1", 1)])
        self.register_session("s2", [self.own_edit("e2", 2)])
        self.assert_item(self.items(), "S1", "pass", "2 sessions audited")

    def test_a_session_registered_twice_is_read_once(self):
        self.register_session("s1", [self.own_edit()])
        later = self.register_session("s1-later", [edit_row(os.path.join(self.main, "x.txt"), "e2", 2)])
        self.register_path("s1", later)  # the first line for an id counts, so this one is ignored
        self.assert_item(self.items(), "S1", "pass", "1 sessions audited")


class MissingEvidenceTest(TranscriptCase):
    def test_no_registry_file(self):
        self.unavailable(self.items())

    def test_an_empty_registry(self):
        self.register_path("x", "/nonexistent")
        open(os.path.join(self.runtime, "sessions.jsonl"), "w").close()
        self.unavailable(self.items())

    def test_a_bad_registry_line(self):
        lines = ("not json", "[]", json.dumps({"session_id": "a/b", "transcript_path": "/x", "started_at": "t"}),
                 json.dumps({"session_id": "ok", "transcript_path": "", "started_at": "t"}),
                 json.dumps({"session_id": "ok", "transcript_path": 5, "started_at": "t"}),
                 json.dumps({"session_id": "ok", "transcript_path": "/x"}))
        for line in lines:
            with self.subTest(line=line):
                self.setUp()  # a fresh registry for each case, so no earlier line decides
                self.register_session("s1", [self.own_edit()])
                with open(os.path.join(self.runtime, "sessions.jsonl"), "a") as handle:
                    handle.write(line + "\n")
                items = self.items()
                self.unavailable(items)
                self.assertIn("unreadable registry line 2", items["S1"]["evidence"])

    def test_a_registry_that_is_a_symlink(self):
        os.makedirs(self.runtime, exist_ok=True)
        os.chmod(self.runtime, 0o700)
        target = os.path.join(self.root, "elsewhere.jsonl")
        open(target, "w").close()
        os.symlink(target, os.path.join(self.runtime, "sessions.jsonl"))
        items = self.items()
        self.unavailable(items)
        self.assertIn("unreadable registry", items["S1"]["evidence"])

    def test_a_registered_session_with_no_transcript_file_is_skipped(self):
        path = self.register_session("s1", [self.own_edit()])
        self.register_path("s2", os.path.join(os.path.dirname(path), "gone.jsonl"))
        items = self.items()
        self.assert_item(items, "S1", "pass", "1 sessions audited")
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(path), "gone.jsonl")))
        with open(os.path.join(self.runtime, "sessions.jsonl")) as handle:
            self.assertEqual(len(handle.read().splitlines()), 2)  # the audit does not prune the registry

    def test_a_session_with_no_transcript_file_is_skipped_even_when_it_has_subagent_files(self):
        path = self.register_session("s1", [self.own_edit()])
        gone = os.path.join(os.path.dirname(path), "gone.jsonl")
        sub_folder = os.path.join(os.path.dirname(path), "gone", "subagents")
        os.makedirs(sub_folder)
        self.write_rows(os.path.join(sub_folder, "agent-x.jsonl"), [self.own_edit("e9")])
        self.register_path("gone", gone)
        self.assert_item(self.items(), "S1", "pass", "1 sessions audited")

    def test_every_registered_session_with_no_transcript_file_is_unavailable(self):
        self.register_path("s1", os.path.join(self.root, "projects", "gone.jsonl"))
        items = self.items()
        self.unavailable(items)
        self.assertIn("no registered session touches", items["S1"]["evidence"])

    def test_a_transcript_that_cannot_be_read_for_another_reason_is_unavailable(self):
        path = self.register_session("s1", [self.own_edit()])
        os.mkdir(os.path.join(os.path.dirname(path), "dir.jsonl"))
        self.register_path("s2", os.path.join(os.path.dirname(path), "dir.jsonl"))
        items = self.items()
        self.unavailable(items)
        self.assertIn("cannot read transcript dir.jsonl", items["S1"]["evidence"])

    def test_a_subagent_file_that_is_listed_and_then_missing_is_skipped(self):
        path = self.register_session("s1", [self.own_edit()], subagents={"rev1": []})
        sub_folder = os.path.join(os.path.dirname(path), "s1", "subagents")
        os.symlink(os.path.join(sub_folder, "nowhere"), os.path.join(sub_folder, "agent-gone.jsonl"))  # listed, ENOENT on open
        self.assert_item(self.items(), "S1", "pass", "1 sessions audited")

    def test_a_subagent_file_that_cannot_be_read_for_another_reason_is_unavailable(self):
        path = self.register_session("s1", [self.own_edit()], subagents={"rev1": []})
        os.mkdir(os.path.join(os.path.dirname(path), "s1", "subagents", "agent-dir.jsonl"))
        self.unavailable(self.items())

    def test_no_session_touches_the_worktree_even_when_none_is_declared(self):
        self.test_command = "none"
        self.register_session("s1", [edit_row("/else/a.txt", "e1", 1, cwd="/else")])
        items = self.items()
        self.unavailable(items)
        self.assertIn("no registered session touches", items["S1"]["evidence"])


class VersionTest(TranscriptCase):
    def with_row(self, **changes):
        row = self.own_edit()
        row.update(changes)
        return row

    def test_an_unlisted_major_minor_or_a_bad_version_is_unavailable(self):
        for version in ("2.2.0", "3.1.301", "1.1.301", "2.1", "latest", 2.1, None):
            with self.subTest(version=version):
                self.setUp()
                self.register_session("s1", [self.with_row(version=version)])
                self.unavailable(self.items())

    def test_a_bad_version_text_is_not_copied_into_the_evidence(self):
        for version in ("SECRET-VERSION-TEXT", {"k": "SECRET-VERSION-TEXT"}):
            with self.subTest(version=version):
                self.setUp()
                self.register_session("s1", [self.with_row(version=version)])
                items = self.items()
                self.unavailable(items)
                self.assertNotIn("SECRET", items["S1"]["evidence"])

    def test_a_missing_version_is_unavailable(self):
        row = self.own_edit()
        del row["version"]
        self.register_session("s1", [row])
        self.unavailable(self.items())

    def test_every_read_kind_needs_a_version(self):
        for kind in ("user", "system", "attachment"):
            with self.subTest(kind=kind):
                self.setUp()
                self.register_session("s1", [self.own_edit(), {"type": kind, "message": {"content": "x"}}])
                self.unavailable(self.items())

    def test_an_untested_patch_passes_with_a_note_once_per_version(self):
        run = bash_row("make test", "b1", 20, version="2.1.300")
        self.register_session("s1", [self.with_row(version="2.1.300"), self.own_edit("e2", 11, version="2.1.300"), run, result_row("b1", 21)])
        items = self.items()
        for name in ("S1", "S2"):
            self.assert_item(items, name, "pass", "untested patch version 2.1.300")
            self.assertEqual(items[name]["evidence"].count("untested patch version"), 1)

    def test_other_row_kinds_are_skipped_even_with_a_bad_version(self):
        rows = [self.own_edit(), {"type": "queue-operation", "version": "9.9.9", "content": "x"},
                {"type": "progress", "data": {}}, {"type": "worktree-state", "version": "0.0"}]
        self.register_session("s1", rows)
        self.assert_item(self.items(), "S1", "pass")

    def test_the_check_applies_to_subagent_transcripts(self):
        bad = edit_row(os.path.join(self.wt, "b.txt"), "e2", 2, version="2.9.0")
        self.register_session("s1", [self.own_edit()], subagents={"a1": [bad]})
        self.unavailable(self.items())

    def test_a_session_that_never_names_the_worktree_is_not_version_checked(self):
        self.register_session("s1", [self.own_edit()])
        self.register_session("s2", [edit_row("/else/a.txt", "e2", 1, cwd="/else", version="9.9.9")])
        self.assert_item(self.items(), "S1", "pass", "1 sessions audited")


class FieldsTest(TranscriptCase):
    def test_a_row_without_a_needed_field_is_unavailable(self):
        def no_timestamp(row):
            del row["timestamp"]

        def drop_input_key(row):
            row["message"]["content"][0]["input"].pop("file_path")

        def string_command(row):
            row["message"]["content"][0] = {"type": "tool_use", "id": "b9", "name": "Bash", "input": {"command": 5}}

        def without_block_key(key):
            row = bash_row("ls", "b1", 3)
            del row["message"]["content"][0][key]
            return row

        def drop_timestamp(row):
            del row["timestamp"]
            return row

        cases = {
            "not json": "{broken",
            "not an object": "[1, 2]",
            "no type": json.dumps({"version": VERSION}),
            "no timestamp": no_timestamp,
            "no file_path": drop_input_key,
            "command is not a string": string_command,
            "no tool_use_id": result_row("e1", 3),
            "is_error is not a boolean": result_row("e1", 3, is_error="yes"),
            "content is a number": call_row("Bash", {"command": "x"}, "b1", 3, message={"content": 5}),
            "user row without message": {"type": "user", "version": VERSION},
            "assistant row with string content": call_row("Bash", {"command": "x"}, "b1", 3, message={"content": "text"}),
            "relative path without cwd": edit_row("rel.txt", "e3", 4),
            "tool_use without id": without_block_key("id"),
            "tool_use without name": without_block_key("name"),
            "tool_use without input": without_block_key("input"),
            "content block without type": call_row("Bash", {"command": "x"}, "b1", 3, message={"content": [{"text": "no type"}]}),
            "NotebookEdit without a path": call_row("NotebookEdit", {"new_source": "x"}, "n1", 3),
            "Bash row without timestamp": drop_timestamp(bash_row("ls", "b2", 3)),
            "timestamp that is not ISO 8601": bash_row("ls", "b3", 3, timestamp="yesterday"),
        }
        cases["no tool_use_id"]["message"]["content"][0].pop("tool_use_id")
        for name, case in cases.items():
            with self.subTest(case=name):
                self.setUp()
                bad = self.own_edit("e2", 5)
                if callable(case):
                    case(bad)
                else:
                    bad = case
                self.register_session("s1", [self.own_edit(), bad])
                self.unavailable(self.items())

    def test_a_line_separator_character_inside_a_row_does_not_split_it(self):
        text = {"type": "user", "version": VERSION, "message": {"role": "user", "content": "a\u2028b\u2029c\x85d\x0be"}}
        self.register_session("s1", [self.own_edit(), json.dumps(text, ensure_ascii=False)])
        self.assert_item(self.items(), "S1", "pass")

    def test_blank_lines_are_skipped(self):
        self.register_session("s1", [self.own_edit(), "", "   "])
        self.assert_item(self.items(), "S1", "pass")


class DeclarationTest(TranscriptCase):
    def setUp(self):
        super().setUp()
        self.register_session("s1", [self.own_edit("e1", 1), bash_row("make test", "b1", 2), result_row("b1", 3)])

    def declared(self, files):
        return self.items(files)

    def test_a_missing_declaration_fails_s2(self):
        self.assert_item(self.declared({"CLAUDE.md": None}), "S2", "fail", "found 0")

    def test_two_sections_in_one_file_fail_s2(self):
        section = "### Test command\n\n```\nmake test\n```\n"
        self.assert_item(self.declared({"CLAUDE.md": section + "\n" + section}), "S2", "fail", "found 2")

    def test_two_sections_in_two_files_fail_s2(self):
        section = "### Test command\n\n```\nmake test\n```\n"
        items = self.declared({"CLAUDE.md": section, ".claude/CLAUDE.md": section})
        self.assert_item(items, "S2", "fail", "found 2")

    def test_the_section_in_dot_claude_is_read(self):
        items = self.declared({"CLAUDE.md": "# no section\n", ".claude/CLAUDE.md": declaration("make test")})
        self.assert_item(items, "S2", "pass")

    def test_two_blocks_and_an_empty_block_fail_s2(self):
        two = "### Test command\n\n```\nmake test\n```\n\n```\nmake other\n```\n"
        self.assert_item(self.declared({"CLAUDE.md": two}), "S2", "fail", "found 2")
        self.setUp()
        empty = "### Test command\n\n```\n\n```\n"
        self.assert_item(self.declared({"CLAUDE.md": empty}), "S2", "fail", "found 1")

    def test_a_heading_inside_a_fenced_block_is_not_a_section(self):
        text = "```\n### Test command\n```\n\n" + declaration("make test")
        self.assert_item(self.declared({"CLAUDE.md": text}), "S2", "pass")

    def test_a_later_heading_ends_the_section(self):
        text = "### Test command\n\n## Other\n\n```\nmake test\n```\n"
        self.assert_item(self.declared({"CLAUDE.md": text}), "S2", "fail", "found 0")

    def test_a_fence_that_is_never_closed_runs_to_the_end_of_the_file(self):
        self.assert_item(self.declared({"CLAUDE.md": "### Test command\n\n```\nmake test\n"}), "S2", "pass")

    def test_a_line_that_starts_with_the_fence_closes_it(self):
        self.assert_item(self.declared({"CLAUDE.md": "### Test command\n\n```\nmake test\n```bash\n"}), "S2", "pass")

    def link_branch(self, links, files):
        """Branch `feature` where CLAUDE.md is removed, `files` are regular files and `links` map a path to a symlink target."""
        self.git("checkout", "-b", "feature")
        self.git("rm", "-q", "CLAUDE.md")
        for path, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(self.repo, path)), exist_ok=True)
            with open(os.path.join(self.repo, path), "w") as handle:
                handle.write(text)
            self.git("add", path)
        for path, target in links.items():
            os.makedirs(os.path.dirname(os.path.join(self.repo, path)), exist_ok=True)
            os.symlink(target, os.path.join(self.repo, path))
            self.git("add", path)
        self.git("commit", "-m", "feat: declare tests")
        self.git("push", "-u", "origin", "feature")
        return self.git("rev-parse", "HEAD")

    def linked(self, links, files):
        tip = self.link_branch(links, files)
        self.assertEqual(self.record().returncode in (0, 1), True)
        return {item["id"]: item for item in self.read_record(tip)["items"]}

    def test_a_symlink_to_a_file_in_the_repository_is_followed(self):
        items = self.linked({"CLAUDE.md": "AGENTS.md"}, {"AGENTS.md": declaration("make test")})
        self.assert_item(items, "S2", "pass")

    def test_a_symlink_chain_and_a_relative_target_in_a_folder_are_followed(self):
        items = self.linked({"CLAUDE.md": "docs/b.md", "docs/b.md": "../a.md"}, {"a.md": declaration("make test")})
        self.assert_item(items, "S2", "pass")

    def test_a_symlink_that_leaves_the_repository_fails_s2(self):
        for target in ("../outside.md", "/etc/hostname"):
            with self.subTest(target=target):
                self.setUp()
                items = self.linked({"CLAUDE.md": target}, {})
                self.assert_item(items, "S2", "fail", "leaves the repository")

    def test_a_symlink_loop_fails_s2(self):
        items = self.linked({"CLAUDE.md": "a.md", "a.md": "CLAUDE.md"}, {})
        self.assert_item(items, "S2", "fail", "loops")

    def test_a_symlink_to_a_missing_file_fails_s2(self):
        items = self.linked({"CLAUDE.md": "gone.md"}, {})
        self.assert_item(items, "S2", "fail", "not in HEAD")

    def test_a_symlink_to_the_root_does_not_read_another_file(self):
        for target in (".", "docs/.."):
            with self.subTest(target=target):
                self.setUp()
                items = self.linked({"CLAUDE.md": target}, {"A.md": declaration("make test"), "docs/x.md": "text"})
                self.assert_item(items, "S2", "fail", "not in HEAD")

    def test_a_symlink_to_a_folder_fails_s2(self):
        items = self.linked({"CLAUDE.md": "docs"}, {"docs/x.md": "text"})
        self.assert_item(items, "S2", "fail", "not a regular file")

    def test_none_passes_with_a_note(self):
        self.assert_item(self.declared({"CLAUDE.md": declaration("none")}), "S2", "pass", "none")


class S2Test(TranscriptCase):
    def run_rows(self, *rows, subagents=None, extra=()):
        self.register_session("s1", [self.own_edit("e1", 10), *rows], subagents=subagents)
        for index, more in enumerate(extra):
            self.register_session(f"x{index}", more)
        return self.items()

    def test_the_declared_command_after_the_last_edit_passes(self):
        self.assert_item(self.run_rows(bash_row("make test", "b1", 20), result_row("b1", 21)), "S2", "pass")

    def test_no_run_fails(self):
        self.assert_item(self.run_rows(), "S2", "fail", "did not run")

    def test_a_run_before_the_last_edit_in_the_same_file_fails(self):
        rows = [bash_row("make test", "b0", 5), result_row("b0", 6), self.own_edit("e2", 30), bash_row("ls", "b1", 31)]
        self.register_session("s1", [self.own_edit("e1", 1), *rows])
        self.assert_item(self.items(), "S2", "fail", "only before the last edit")

    def test_equal_timestamps_in_one_file_follow_file_order(self):
        items = self.run_rows(bash_row("make test", "b1", 10), result_row("b1", 11))
        self.assert_item(items, "S2", "pass")

    def test_equal_timestamps_across_files_are_not_after(self):
        self.register_session("s1", [bash_row("make test", "b1", 10), result_row("b1", 11)],
                              subagents={"a1": [self.own_edit("e2", 10)]})
        self.assert_item(self.items(), "S2", "fail", "only before the last edit")

    def test_a_run_in_another_session_after_the_edit_passes_by_timestamp(self):
        self.register_session("s1", [self.own_edit("e1", 10)])
        self.register_session("s2", [bash_row(f"cd {self.wt} && make test", "b1", 20), result_row("b1", 21)])
        self.assert_item(self.items(), "S2", "pass")

    def test_a_run_in_a_subagent_after_the_edit_passes(self):
        self.register_session("s1", [self.own_edit("e1", 10)],
                              subagents={"a1": [bash_row("make test", "b1", 20), result_row("b1", 21)]})
        self.assert_item(self.items(), "S2", "pass")

    def test_a_run_with_is_error_fails(self):
        self.assert_item(self.run_rows(bash_row("make test", "b1", 20), result_row("b1", 21, is_error=True)), "S2", "fail", "failed")

    def test_a_call_with_no_result_did_not_finish(self):
        self.assert_item(self.run_rows(bash_row("make test", "b1", 20)), "S2", "fail")

    def test_a_filtered_or_piped_run_is_not_the_declared_command(self):
        for command in ("make test | tail -4", "make test -k one", "make test 2>&1", "cd /other && make test", "echo make test"):
            with self.subTest(command=command):
                self.setUp()
                self.assert_item(self.run_rows(bash_row(command, "b1", 20), result_row("b1", 21)), "S2", "fail", "did not run")

    def test_outer_spaces_and_a_leading_cd_to_the_worktree_match(self):
        for template in ("  make test  ", "cd {wt} && make test", "cd '{wt}'&&  make test ", 'cd "{wt}" && make test'):
            with self.subTest(command=template):
                self.setUp()
                command = template.format(wt=self.wt)
                self.assert_item(self.run_rows(bash_row(command, "b1", 20), result_row("b1", 21)), "S2", "pass")

    def test_a_relative_cd_resolves_against_the_row_cwd_not_the_audit_cwd(self):
        for elsewhere, expected in ((True, "fail"), (False, "pass")):
            with self.subTest(elsewhere=elsewhere):
                self.setUp()
                row_cwd = "/elsewhere" if elsewhere else self.wt
                self.register_session("s1", [self.own_edit("e1", 10), bash_row("cd . && make test", "b1", 20, cwd=row_cwd), result_row("b1", 21)])
                tip = self.branch()
                result = self.audit("record", "--worktree", self.wt, "--llm", self.llm_path, cwd=self.wt)
                self.assertIn(result.returncode, (0, 1), result.stderr)
                self.assertEqual(self.item(tip, "S2")["result"], expected)

    def background(self, notice_rows, **kwargs):
        return self.run_rows(bash_row("make test", "b1", 20, background=True), result_row("b1", 21), *notice_rows, **kwargs)

    def test_a_background_run_uses_the_exit_code_of_its_notification(self):
        for name, row in (("user row", notification_user_row("b1")), ("attachment row", notification_attachment_row("b1"))):
            with self.subTest(row=name):
                self.setUp()
                self.assert_item(self.background([row]), "S2", "pass")

    def test_a_background_run_that_failed_or_never_reported_fails(self):
        cases = {"exit 1": [notification_user_row("b1", status="failed", code=1)], "no notification": [],
                 "other id": [notification_user_row("b9")],
                 "queue-operation only": [{"type": "queue-operation", "operation": "enqueue", "content": notification_text("b1")}],
                 "one of two failed": [notification_user_row("b1"), notification_user_row("b1", status="failed", code=2)]}
        for name, rows in cases.items():
            with self.subTest(case=name):
                self.setUp()
                self.assert_item(self.background(rows), "S2", "fail")

    def test_a_notification_quoted_in_an_assistant_row_is_not_a_notification(self):
        quote = call_row("Bash", {"command": "echo"}, "q1", 22, message={"content": [{"type": "text", "text": notification_text("b1")}]})
        self.assert_item(self.background([quote]), "S2", "fail")

    def test_the_call_id_is_not_copied_into_the_evidence(self):
        row = notification_user_row("SECRET-CALL-ID")
        row["message"]["content"] = row["message"]["content"].replace("<status>completed</status>", "")
        self.register_session("s1", [self.own_edit("e1", 10), bash_row("make test", "SECRET-CALL-ID", 20, background=True),
                                     result_row("SECRET-CALL-ID", 21), row])
        items = self.items()
        self.assert_item(items, "S2", "fail", UNAVAILABLE)
        self.assertNotIn("SECRET", items["S2"]["evidence"])

    def test_a_notification_for_the_call_without_a_status_is_unavailable(self):
        row = notification_user_row("b1")
        row["message"]["content"] = row["message"]["content"].replace("<status>completed</status>", "")
        self.assert_item(self.background([row]), "S2", "fail", UNAVAILABLE)

    def test_a_subagent_background_run_is_reported_in_the_main_transcript(self):
        self.register_session("s1", [self.own_edit("e1", 10), notification_user_row("b1")],
                              subagents={"a1": [bash_row("make test", "b1", 20, background=True), result_row("b1", 21)]})
        self.assert_item(self.items(), "S2", "pass")

    def test_without_any_edit_a_run_is_needed(self):
        self.register_session("s1", [bash_row("ls", "b0", 1, cwd=self.wt)])
        self.assert_item(self.items(), "S2", "fail", "did not run")
        self.setUp()
        self.register_session("s1", [bash_row("make test", "b1", 2, cwd=self.wt), result_row("b1", 3)])
        self.assert_item(self.items(), "S2", "pass")


class S1Test(TranscriptCase):
    def test_an_edit_in_the_main_checkout_fails(self):
        path = os.path.join(self.main, "x.txt")
        self.register_session("s1", [self.own_edit(), edit_row(path, "e2", 11)])
        items = self.items()
        self.assert_item(items, "S1", "fail", path)

    def test_an_edit_in_the_worktree_passes(self):
        self.register_session("s1", [self.own_edit()])
        self.assert_item(self.items(), "S1", "pass", "no edit in the main checkout")

    def test_an_edit_in_another_worktree_of_the_repo_passes(self):
        other = os.path.join(self.root, "other-worktree")
        self.git("worktree", "add", "-b", "other", other, cwd=self.main)
        self.register_session("s1", [self.own_edit(), edit_row(os.path.join(other, "x.txt"), "e2", 11)])
        self.assert_item(self.items(), "S1", "pass")

    def test_a_bash_edit_is_not_an_edit(self):
        self.register_session("s1", [self.own_edit(), bash_row(f"sed -i s/a/b/ {self.main}/x.txt", "b1", 11)])
        self.assert_item(self.items(), "S1", "pass")

    def test_more_than_ten_findings_are_counted(self):
        rows = [edit_row(os.path.join(self.main, f"x{n}.txt"), f"m{n}", 20 + n) for n in range(12)]
        self.register_session("s1", [self.own_edit(), *rows])
        evidence = self.items()["S1"]["evidence"].split("\n")
        self.assertEqual(len(evidence), 11)
        self.assertTrue(all(re.fullmatch(r"s1\.jsonl: .*x\d+\.txt", line) for line in evidence[:10]), evidence)
        self.assertEqual(evidence[10], "and 2 more")

    def test_the_audited_worktree_being_the_main_checkout_fails(self):
        self.git("checkout", "-b", "solo", cwd=self.main)
        self.commit("feat: solo", cwd=self.main)
        self.git("push", "-u", "origin", "solo", cwd=self.main)
        tip = self.git("rev-parse", "HEAD", cwd=self.main)
        self.register_session("s1", [edit_row(os.path.join(self.main, "x.txt"), "e1", 1)])
        items = self.items(worktree=(self.main, tip))
        self.assert_item(items, "S1", "fail", "is the main checkout")


class RecordTest(TranscriptCase):
    def test_a_failed_s1_gives_a_failed_record_with_items_in_order(self):
        self.register_session("s1", [self.own_edit(), edit_row(os.path.join(self.main, "x.txt"), "e2", 11)])
        tip = self.branch()
        result = self.record()
        self.assertEqual(result.returncode, 1)
        self.assertEqual([item["id"] for item in self.read_record(tip)["items"]], ["S1", "S2", "S3", "S4", "S5", "S6", "XC", "S7", "S8", "S9", "L1", "L2", "L3", "L4", "L5", "L6"])

    def test_a_failed_s2_gives_a_failed_record_and_exit_1(self):
        self.register_session("s1", [self.own_edit()])
        tip = self.branch()
        self.assertEqual(self.record().returncode, 1)
        self.assertEqual(self.item(tip, "S2")["result"], "fail")
        self.assertEqual(self.read_record(tip)["result"], "fail")

    def test_the_untested_patch_note_survives_a_long_evidence(self):
        main_files = [edit_row(os.path.join(self.main, "x" * 260 + f"{n}.txt"), f"m{n}", 20 + n, version="2.1.300") for n in range(10)]
        self.register_session("s1", [self.own_edit(version="2.1.300"), *main_files])
        evidence = self.items()["S1"]["evidence"]
        self.assertGreater(len(evidence), 2000)
        self.assertTrue(evidence.endswith("...; untested patch version 2.1.300"), evidence[-80:])

    def test_evidence_never_holds_a_raw_row(self):
        secret = "SECRET-PROMPT-TEXT"
        rows = [self.own_edit(), {"type": "user", "version": VERSION, "message": {"role": "user", "content": secret}},
                bash_row(f"echo {secret} {self.wt}", "b1", 20), result_row("b1", 21)]
        self.register_session("s1", rows)
        tip = self.branch()
        self.record()
        with open(os.path.join(self.runtime, f"{tip}.json")) as handle:
            self.assertNotIn(secret, handle.read())


class FixtureTest(TranscriptCase):
    def tested_versions(self):
        with open(os.path.join(HERE, "audit")) as handle:
            match = re.search(r"^TESTED_VERSIONS = \((.*)\)$", handle.read(), re.MULTILINE)
        return re.findall(r'"([^"]+)"', match.group(1))

    def test_every_tested_version_has_a_fixture_that_passes_s1_and_s2(self):
        versions = self.tested_versions()
        self.assertTrue(versions)
        for version in versions:
            with self.subTest(version=version):
                self.setUp()
                with open(os.path.join(HERE, "fixtures", f"session-{version}.jsonl")) as handle:
                    text = handle.read().replace("{WORKTREE}", self.wt)
                path = os.path.join(self.root, "fixture.jsonl")
                with open(path, "w") as handle:
                    handle.write(text)
                self.register_path("fixture", path)
                items = self.items()
                self.assert_item(items, "S1", "pass", "1 sessions audited")
                self.assert_item(items, "S2", "pass")
                self.assertNotIn("untested patch", items["S1"]["evidence"])


if __name__ == "__main__":
    unittest.main()
