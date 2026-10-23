# S7 (models) and S9 (safety), through `audit record` with synthetic transcripts.
import copy
import json
import os
import re
import shlex
import unittest

from audit_support import (EARLY, HERE, SONNET, VERSION, AuditCase, bash_row, edit_row, result_row, stamp, subagent_rows)

OPUS = "claude-opus-5-5"
UNAVAILABLE = "evidence unavailable"
PREAMBLE = ("You are working inside Orca, a multi-agent IDE. You are a dispatched worker.\n"
            "orca orchestration send --type worker_done --task-id task_x --dispatch-id ctx_0000 --outcome succeeded")


def user_row(content, seconds=0, **extra):
    return {"type": "user", "timestamp": stamp(seconds), "version": VERSION, "message": {"role": "user", "content": content}, **extra}


def with_model(row, model):
    row = copy.deepcopy(row)
    row["message"]["model"] = model
    return row


def text_row(model, text="reply", seconds=1, **extra):
    row = {"type": "assistant", "timestamp": stamp(seconds), "version": VERSION, "message": {"content": [{"type": "text", "text": text}]}}
    if model is not None:
        row["message"]["model"] = model
    row.update(extra)
    return row


class SafetyCase(AuditCase):
    default_session = False
    default_ledger = False

    def run_record(self, branch_message="feat: a"):
        tip = self.start_branch("feature", branch_message)
        result = self.record()
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return tip, result

    def items(self):
        tip, _ = self.run_record()
        return {item["id"]: item for item in self.read_record(tip)["items"]}

    def edit(self, call_id="e1", seconds=1):
        return edit_row(os.path.join(self.repo, "a.txt"), call_id, seconds)

    def s7(self, rows=None, subagents=None, extra_sessions=()):
        """The S7 item of a record over one session (and more sessions given as (id, rows, subagents))."""
        self.register_session("s1", [self.edit()] if rows is None else rows, subagents=subagents)
        for session_id, session_rows, session_subagents in extra_sessions:
            self.register_session(session_id, session_rows, subagents=session_subagents)
        return self.items()["S7"]

    def worker(self, model, extra_rows=()):
        return [user_row(PREAMBLE), text_row(model, cwd=self.repo), *extra_rows]

    def assert_item(self, item, result, text=None):
        self.assertEqual(item["result"], result, item["evidence"])
        if text is not None:
            self.assertIn(text, item["evidence"])


class S7SubagentTest(SafetyCase):
    def test_a_sonnet_subagent_passes(self):
        self.assert_item(self.s7(subagents={"a1": subagent_rows()}), "pass", "1 subagents")

    def test_a_non_sonnet_subagent_fails_and_names_its_model(self):
        item = self.s7(subagents={"a1": subagent_rows(model=OPUS)})
        self.assert_item(item, "fail", "agent-a1.jsonl")
        self.assertIn(OPUS, item["evidence"])
        self.assertNotIn(UNAVAILABLE, item["evidence"])

    def test_the_model_name_is_cut_to_40_characters(self):
        item = self.s7(subagents={"a1": subagent_rows(model="x" * 100)})
        self.assert_item(item, "fail", "x" * 40)
        self.assertNotIn("x" * 41, item["evidence"])

    def test_one_non_sonnet_row_among_sonnet_rows_fails(self):
        self.assert_item(self.s7(subagents={"a1": subagent_rows(extra_models=(OPUS,))}), "fail", OPUS)

    def test_a_subagent_without_a_model_row_is_unavailable(self):
        self.assert_item(self.s7(subagents={"a1": subagent_rows(model=None)}), "fail", UNAVAILABLE)

    def test_a_subagent_without_an_assistant_row_is_unavailable(self):
        self.assert_item(self.s7(subagents={"a1": subagent_rows()[:1]}), "fail", UNAVAILABLE)

    def test_a_subagent_with_only_synthetic_rows_is_unavailable(self):
        self.assert_item(self.s7(subagents={"a1": subagent_rows(model="<synthetic>")}), "fail", UNAVAILABLE)

    def test_synthetic_rows_are_ignored_next_to_sonnet_rows(self):
        self.assert_item(self.s7(subagents={"a1": subagent_rows(extra_models=("<synthetic>",))}), "pass")

    def test_a_non_sonnet_name_wins_over_a_row_without_a_model(self):
        item = self.s7(subagents={"a1": subagent_rows(model=None, extra_models=(OPUS,))})
        self.assert_item(item, "fail", OPUS)
        self.assertNotIn(UNAVAILABLE, item["evidence"])

    def test_a_row_whose_model_is_not_a_string_is_unavailable(self):
        rows = subagent_rows()
        rows[1]["message"]["model"] = 7
        self.assert_item(self.s7(subagents={"a1": rows}), "fail", UNAVAILABLE)

    def test_the_failing_lines_are_cut_to_ten(self):
        item = self.s7(subagents={f"a{n:02d}": subagent_rows(model=OPUS) for n in range(12)})
        self.assert_item(item, "fail", "and 2 more")
        self.assertEqual(len(item["evidence"].splitlines()), 11)


class S7SessionTest(SafetyCase):
    def test_a_main_session_on_a_non_sonnet_model_passes_while_its_subagents_are_checked(self):
        # the synthetic main session runs on an Opus model
        self.assert_item(self.s7(subagents={"a1": subagent_rows()}), "pass", "1 main sessions exempt")
        self.setUp()
        self.assert_item(self.s7(subagents={"a1": subagent_rows(model=OPUS)}), "fail", "agent-a1.jsonl")

    def test_a_worker_session_on_sonnet_passes(self):
        self.assert_item(self.s7(self.worker(SONNET)), "pass", "1 worker sessions")

    def test_a_worker_session_on_another_model_fails(self):
        item = self.s7(self.worker(OPUS))
        self.assert_item(item, "fail", OPUS)
        self.assertIn("s1.jsonl", item["evidence"])

    def test_a_worker_session_without_a_model_is_unavailable(self):
        self.assert_item(self.s7([user_row(PREAMBLE), user_row("more", cwd=self.repo)]), "fail", UNAVAILABLE)

    def test_the_preamble_may_be_a_text_block(self):
        self.assert_item(self.s7([user_row([{"type": "text", "text": PREAMBLE}]), text_row(OPUS, cwd=self.repo)]), "fail", OPUS)

    def test_workers_and_main_sessions_are_counted(self):
        item = self.s7(self.worker(SONNET), extra_sessions=[("s2", [self.edit("e2")], None)])
        self.assert_item(item, "pass", "1 worker sessions")
        self.assertIn("1 main sessions exempt", item["evidence"])

    def not_a_worker(self, rows):
        """A main session on an Opus model whose rows hold the given marker candidate: S7 passes."""
        self.setUp()
        self.assert_item(self.s7([self.edit(), *rows]), "pass")

    def test_the_marker_needs_both_phrases(self):
        self.not_a_worker([user_row("orca orchestration send --dispatch-id ctx_0000")])
        self.not_a_worker([user_row("You are a dispatched worker.")])

    def test_the_marker_is_not_read_in_a_tool_result(self):
        self.not_a_worker([{"type": "user", "timestamp": stamp(2), "version": VERSION, "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "e1", "content": PREAMBLE}]}}])

    def test_the_marker_is_not_read_in_an_assistant_row(self):
        self.not_a_worker([text_row(OPUS, text=PREAMBLE)])

    def test_the_marker_is_not_read_in_a_queued_command_attachment(self):
        self.not_a_worker([{"type": "attachment", "version": VERSION, "attachment": {"type": "queued_command", "prompt": PREAMBLE}}])

    def test_the_marker_is_not_read_in_a_compaction_summary(self):
        self.not_a_worker([user_row(PREAMBLE, 2, isCompactSummary=True)])
        self.not_a_worker([user_row([{"type": "text", "text": PREAMBLE}], 2, isCompactSummary=True)])

    def test_a_worker_session_that_compacts_is_still_a_worker(self):
        item = self.s7(self.worker(OPUS, [user_row("Summary of the session.", 2, isCompactSummary=True)]))
        self.assert_item(item, "fail", OPUS)

    def test_a_subagent_prompt_does_not_mark_a_worker(self):
        rows = subagent_rows()
        rows[0]["message"]["content"] = PREAMBLE
        self.assert_item(self.s7(subagents={"a1": rows}), "pass", "0 worker sessions")

    def fixture_item(self, old_model, new_model):
        self.setUp()
        with open(os.path.join(HERE, "fixtures", "worker-session-2.1.301.jsonl")) as handle:
            text = handle.read().replace("{WORKTREE}", self.repo).replace(old_model, new_model)
        path = os.path.join(self.root, "fixture.jsonl")
        with open(path, "w") as handle:
            handle.write(text)
        self.register_path("fixture", path)
        return self.items()["S7"]

    def test_the_redacted_real_shape_fixture_is_a_worker(self):
        self.assert_item(self.fixture_item(SONNET, SONNET), "pass", "1 worker sessions")
        self.assert_item(self.fixture_item(SONNET, OPUS), "fail", OPUS)

    def test_the_fixture_is_synthetic(self):
        with open(os.path.join(HERE, "fixtures", "worker-session-2.1.301.jsonl")) as handle:
            text = handle.read()
        self.assertNotIn("/home/", text)
        self.assertEqual({json.loads(line)["version"] for line in text.splitlines()}, {VERSION})


class S9Case(SafetyCase):
    CHUNK = 8  # the evidence shows at most 10 lines

    def flagged(self, commands, subagent=False, background=False):
        """The indexes of the commands that S9 flags, one record per chunk; the evidence never holds a command."""
        found = set()
        for start in range(0, len(commands), self.CHUNK):
            chunk = commands[start:start + self.CHUNK]
            self.setUp()
            rows = [self.edit()] + [bash_row(command, f"b{n}", n + 2, background=background) for n, command in enumerate(chunk)]
            if subagent:
                self.register_session("s1", [self.edit()], subagents={"a1": [with_model(row, SONNET) for row in rows]})
            else:
                self.register_session("s1", rows)
            item = self.items()["S9"]
            lines = item["evidence"].splitlines()
            if item["result"] == "pass":
                self.assertIn(f"{len(chunk)} Bash commands checked", item["evidence"])
            for line in lines:
                match = re.search(r"row (\d+)", line)
                if match:
                    found.add(start + int(match.group(1)) - 2)
            self.assertEqual(item["result"], "fail" if any(re.search(r"row (\d+)", line) for line in lines) else "pass", item["evidence"])
        return found

    def assert_flagged(self, commands, **kwargs):
        self.assertEqual(self.flagged(commands, **kwargs), set(range(len(commands))), commands)

    def assert_clean(self, commands, **kwargs):
        self.assertEqual(self.flagged(commands, **kwargs), set(), commands)


class S9RmTest(S9Case):
    def test_recursive_rm_in_every_form_fails(self):
        self.assert_flagged(["rm -rf build", "rm -fr build", "rm -R build", "rm -r build", "rm --recursive build", "rm -f -r build",
                             "rm build -r", "rm --rec build", "rm --r build", "rm -rv build", "/bin/rm -rf build", "git rm -r dir"])

    def test_rm_behind_other_words_fails(self):
        self.assert_flagged(["sudo rm -rf build", "xargs rm -rf", "nohup rm -rf build", "find . -exec rm -rf {} +", "env A=1 rm -rf build",
                             "time rm -rf build", "A=1 rm -rf build", "git rm -rf dir"])

    def test_rm_in_a_later_segment_fails(self):
        self.assert_flagged(["ls && rm -rf x", "ls; rm -rf x", "ls | rm -rf x", "(rm -rf x)", "sleep 1 & rm -rf x", "ls || rm -rf x",
                             "ls\nrm -rf x", "echo $(rm -rf x)"])

    def test_a_shell_command_text_and_eval_are_checked(self):
        self.assert_flagged(["bash -c 'rm -rf x'", "sh -c \"rm -rf x\"", "sudo bash -lc 'rm -rf x'", "eval rm -rf x", "eval 'rm -rf x'",
                             "xargs -I{} sh -c 'rm -rf {}'"])

    def test_a_heredoc_line_is_a_command(self):
        self.assert_flagged(["cat <<EOF\nrm -rf x\nEOF"])

    def test_other_rm_calls_pass(self):
        self.assert_clean(["rm x", "rm -f x", "rm -i x", "rm -- -r", "rm x -- -r", "rm -d dir", "rm -v x y", "ls -R", "find . -exec rm {} + -iregex a",
                           "find . -exec rm {} + -regex b", "git rm x", "git rm --cached x"])

    def test_commands_that_only_name_rm_are_skipped(self):
        self.assert_clean(["grep rm -r .", "echo rm -rf x", "man rm -r", "which rm -r", "type rm -r", "printf 'rm -rf'", "echo 'rm -rf x'",
                           "git commit -m 'rm -rf is banned'", "rg rm -r ."])

    def test_a_skipped_command_word_is_the_first_word_after_assignments(self):
        self.assert_clean(["FOO=1 grep rm -r ."])
        self.assert_flagged(["sudo grep rm -r .", "git grep rm -r"])

    def test_the_evidence_names_the_kind_and_not_the_command(self):
        self.register_session("s1", [self.edit(), bash_row("rm -rf distinctive-secret-name", "b1", 2)])
        item = self.items()["S9"]
        self.assert_item(item, "fail", "s1.jsonl: row 2: recursive rm")
        self.assertNotIn("distinctive-secret-name", item["evidence"])

    def test_a_subagent_command_and_a_background_command_count(self):
        self.assert_flagged(["rm -rf x"], subagent=True)
        self.assert_flagged(["rm -rf x"], background=True)

    def test_the_lines_are_cut_to_ten(self):
        self.register_session("s1", [self.edit()] + [bash_row("rm -rf x", f"b{n}", n + 2) for n in range(12)])
        item = self.items()["S9"]
        self.assert_item(item, "fail", "and 2 more")
        self.assertEqual(len(item["evidence"].splitlines()), 11)


class S9ContinuationTest(S9Case):
    def test_a_backslash_newline_joins_the_lines_as_bash_does(self):
        self.assert_flagged(["rm \\\n -rf dir", "pytest tests \\\n  -n 8", "docker system \\\n prune", "pytest \\\n -n \\\n 8",
                             "bash -c 'rm \\\n -rf x'"])
        self.assert_clean(["rm \\\n x", "pytest tests \\\n -n 2", "ls \\\n -a"])


class S9DockerTest(S9Case):
    def test_docker_prune_fails(self):
        self.assert_flagged(["docker system prune", "docker system prune -af", "docker image prune", "docker container prune",
                             "docker volume prune --force", "docker -H tcp://h:1 volume prune", "sudo docker builder prune",
                             "docker exec c git remote prune origin"])

    def test_other_docker_commands_pass(self):
        self.assert_clean(["docker ps", "docker rm c", "docker run --rm img", "docker compose stop", "echo docker system prune",
                           "grep prune notes.txt", "git remote prune origin"])


class S9RunnerTest(S9Case):
    FLAGS = [("pytest", "-n"), ("pytest", "--numprocesses"), ("python3 -m pytest", "-n"), ("py.test", "-n"),
             ("vitest run", "--maxWorkers"), ("vitest", "--max-workers"), ("jest", "--maxWorkers"), ("jest", "-w"),
             ("playwright test", "--workers"), ("playwright test", "-j"), ("cargo test", "-j"), ("cargo test", "--jobs"),
             ("go test ./...", "-p"), ("go test ./...", "-parallel")]

    @staticmethod
    def forms(runner, flag, value):
        result = [f"{runner} {flag} {value}", f"{runner} {flag}={value}"]
        if len(flag) == 2 and not runner.startswith("go"):
            result.append(f"{runner} {flag}{value}")
        return result

    def commands(self, value):
        return [command for runner, flag in self.FLAGS for command in self.forms(runner, flag, value)]

    def test_more_than_two_workers_fail_in_every_form(self):
        self.assert_flagged(self.commands("3"))
        self.assert_flagged(self.commands("16"))

    def test_two_workers_or_fewer_pass_in_every_form(self):
        self.assert_clean(self.commands("2") + self.commands("1") + self.commands("0") + self.commands("02"))

    def test_a_value_that_is_not_an_integer_fails(self):
        for value in ("auto", "logical", "50%", "-1", "2.5", "+2", "two", "٢"):
            with self.subTest(value=value):
                self.assert_flagged(["pytest -n " + shlex.quote(value), "vitest --maxWorkers=" + shlex.quote(value),
                                     "jest -w " + shlex.quote(value), "cargo test --jobs " + shlex.quote(value)])

    def test_an_empty_value_fails(self):
        self.assert_flagged(["pytest -n=", "pytest -n ''", "vitest --maxWorkers=", "playwright test --workers=''", "go test -p="])

    def test_a_flag_with_no_value_fails(self):
        self.assert_flagged(["pytest -n", "vitest --maxWorkers", "jest -w", "playwright test --workers", "cargo test -j", "go test -parallel"])

    def test_a_flag_followed_by_another_flag_fails(self):
        self.assert_flagged(["pytest -n --verbose", "go test -p -v"])

    def test_the_equals_form_wins_over_the_attached_form(self):
        self.assert_clean(["pytest -n=2"])
        self.assert_flagged(["pytest -n=4", "pytest -n="])

    def test_go_flags_may_have_two_dashes(self):
        self.assert_flagged(["go test --p 4", "go test --parallel=4"])
        self.assert_clean(["go test --p 2"])

    def test_vitest_variables_are_checked(self):
        self.assert_flagged(["VITEST_MAX_THREADS=4 vitest", "VITEST_MAX_FORKS=4 npx vitest run", "VITEST_MAX_FORKS= vitest",
                             "env VITEST_MAX_THREADS=auto vitest", "VITEST_MAX_THREADS=2 vitest --maxWorkers=4"])
        self.assert_clean(["VITEST_MAX_THREADS=2 vitest", "VITEST_MAX_FORKS=1 vitest run", "VITEST_MAX_THREADS=4 npm test"])

    def test_a_runner_behind_a_launcher_is_found(self):
        self.assert_flagged(["npx vitest --maxWorkers=4", "pnpm exec jest -w 4", "uv run pytest -n 4", "cargo +nightly test -j 4",
                             "cargo test --release -j 4 -- --nocapture", "sudo pytest -n 4", "cd x && pytest -n 4"])

    def test_two_worker_flags_each_count(self):
        self.assert_flagged(["pytest -n 2 -n 4", "pytest -n 4 -n 2", "vitest --maxWorkers=2 --max-workers 4"])

    def test_a_runner_with_no_worker_flag_passes(self):
        self.assert_clean(["pytest", "pytest tests/ -x", "vitest run", "jest --watch", "playwright test", "cargo test", "go test ./...",
                           "cargo build -j 8", "go build -p 8 ./...", "go vet -p 8 ./...", "playwright install -j 8"])

    def test_other_commands_are_not_checked(self):
        self.assert_clean(["git log -n 10", "make -j8", "npm test", "npm test -- --maxWorkers=8", "ninja -j 16", "xargs -n 8 echo",
                           "grep pytest -n file", "echo pytest -n 8", "pip install pytest", "which jest -w"])

    def test_the_evidence_names_the_runner_flag_and_value(self):
        self.register_session("s1", [self.edit(), bash_row("pytest -n 4 tests/distinctive-path", "b1", 2)])
        item = self.items()["S9"]
        self.assert_item(item, "fail", "pytest -n '4'")
        self.assertNotIn("distinctive-path", item["evidence"])
        self.setUp()
        self.register_session("s1", [self.edit(), bash_row("pytest -n", "b1", 2)])
        self.assert_item(self.items()["S9"], "fail", "pytest -n with no value")

    def test_a_long_value_is_cut_to_20_characters(self):
        self.register_session("s1", [self.edit(), bash_row("pytest -n " + "9" * 60, "b1", 2)])
        item = self.items()["S9"]
        self.assertIn("9" * 20, item["evidence"])
        self.assertNotIn("9" * 21, item["evidence"])


class S9UnsplittableTest(S9Case):
    def test_a_command_that_cannot_be_split_and_names_a_trigger_word_is_unavailable(self):
        for command in ("rm -rf \"x", "echo 'a' && rm -rf 'x", "docker system prune 'x", "pytest -n 4 'x", "cargo test -j 4 'x",
                        "go test -p 4 'x", "playwright test 'x", "cat <<EOF\ndon't\nrm x\nEOF"):
            with self.subTest(command=command):
                self.setUp()
                self.register_session("s1", [self.edit(), bash_row(command, "b1", 2)])
                item = self.items()["S9"]
                self.assert_item(item, "fail", "s1.jsonl: row 2: evidence unavailable: cannot split the command")

    def test_a_command_that_cannot_be_split_and_names_no_trigger_word_is_ignored(self):
        self.assert_clean(["cat <<EOF\ndon't stop\nEOF", "echo \"x", "cargo build 'x", "go build 'x", "docker ps 'x", "ls --rm 'x"])

    def test_a_trigger_word_inside_another_word_is_not_a_trigger(self):
        self.assert_clean(["echo 'x --rm \"", "ls karma 'x", "echo rmdir 'x"])

    def test_the_text_of_a_shell_option_that_cannot_be_split_is_unavailable(self):
        self.register_session("s1", [self.edit(), bash_row("bash -c \"rm -rf 'x\"", "b1", 2)])
        self.assert_item(self.items()["S9"], "fail", "evidence unavailable: cannot split the command")

    @staticmethod
    def nested(depth):
        command = "rm -rf x"
        for _ in range(depth):
            command = "bash -c " + shlex.quote(command)
        return command

    def test_a_shell_text_at_depth_3_is_checked_and_at_depth_4_is_unavailable(self):
        self.register_session("s1", [self.edit(), bash_row(self.nested(3), "b1", 2)])
        self.assert_item(self.items()["S9"], "fail", "row 2: recursive rm")
        self.setUp()
        self.register_session("s1", [self.edit(), bash_row(self.nested(4), "b1", 2)])
        self.assert_item(self.items()["S9"], "fail", "row 2: evidence unavailable: shell commands nested deeper than 3")

    def test_an_unavailable_command_does_not_hide_the_other_violations(self):
        self.register_session("s1", [self.edit(), bash_row("rm -rf \"x", "b1", 2), bash_row("rm -rf y", "b2", 3), bash_row("pytest -n 9", "b3", 4)])
        item = self.items()["S9"]
        for expected in ("row 2: evidence unavailable", "row 3: recursive rm", "row 4: pytest -n"):
            self.assertIn(expected, item["evidence"])


class MissingEvidenceTest(SafetyCase):
    def both_unavailable(self, expect_exit=1):
        tip = self.start_branch("feature", "feat: a")
        result = self.record()
        self.assertEqual(result.returncode, expect_exit, result.stderr)
        items = {item["id"]: item for item in self.read_record(tip)["items"]}
        for name in ("S7", "S9"):
            self.assert_item(items[name], "fail", UNAVAILABLE)
        self.assertEqual(self.read_record(tip)["result"], "fail")

    def test_no_registry_never_passes_on_zero_sessions(self):
        self.both_unavailable()

    def test_an_empty_registry_never_passes_on_zero_sessions(self):
        os.makedirs(self.runtime, exist_ok=True)
        os.chmod(self.runtime, 0o700)
        open(os.path.join(self.runtime, "sessions.jsonl"), "w").close()
        self.both_unavailable()

    def test_a_registry_of_sessions_that_do_not_touch_the_worktree_never_passes(self):
        self.register_session("s1", [edit_row("/somewhere/else/a.txt", "e1", 1, cwd="/somewhere/else")])
        self.both_unavailable()

    def test_a_missing_registered_transcript_fails(self):
        self.register_path("gone", os.path.join(self.root, "projects", "gone.jsonl"))
        self.both_unavailable()

    def test_an_untested_version_fails(self):
        self.register_session("s1", [dict(self.edit(), version="9.9.1")])
        self.both_unavailable()

    def test_a_bash_call_without_a_command_fails(self):
        self.register_session("s1", [self.edit(), {"type": "assistant", "timestamp": stamp(2), "version": VERSION, "message": {
            "model": OPUS, "content": [{"type": "tool_use", "id": "b1", "name": "Bash", "input": {}}]}}])
        self.both_unavailable()

    def test_a_row_without_a_message_fails(self):
        self.register_session("s1", [self.edit(), {"type": "assistant", "timestamp": stamp(2), "version": VERSION}])
        self.both_unavailable()

    def test_an_untested_patch_version_note_stays_on_s1_and_s2_only(self):
        self.register_session("s1", [dict(self.edit(), version="2.1.302")])
        items = self.items()
        self.assertIn("untested patch version 2.1.302", items["S1"]["evidence"])
        for name in ("S7", "S9"):
            self.assertNotIn("untested", items[name]["evidence"])


class RecordTest(SafetyCase):
    def test_the_items_are_in_the_stated_order_and_a_failed_item_fails_the_record(self):
        self.register_session("s1", [self.edit(), bash_row("rm -rf x", "b1", 2)])
        tip, result = self.run_record()
        record = self.read_record(tip)
        self.assertEqual([item["id"] for item in record["items"]],
                         ["S1", "S2", "S3", "S4", "S5", "S6", "XC", "S7", "S8", "S9", "L1", "L2", "L3", "L4", "L5", "L6"])
        self.assertEqual(result.stdout.decode().splitlines()[7:10], ["S7 pass", "S8 pass", "S9 fail"])
        self.assertEqual((record["result"], result.returncode), ("fail", 1))
        self.assertEqual([item["id"] for item in record["items"] if item["result"] == "fail"], ["S3", "S4", "S5", "S6", "XC", "S9"])


if __name__ == "__main__":
    unittest.main()
