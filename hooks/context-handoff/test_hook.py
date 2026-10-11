import fcntl
import json
import os
import re
import resource
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "hook.py")
SESSION = "11111111-2222-3333-4444-555555555555"
WINDOW = 100000  # a window file with this size puts the 80% line at 80000 tokens
GOOD_STATE = {"events": 0, "triggered": False, "reblocks": 0, "calls_since_block": 0, "done": False, "command": "", "handoff": ""}
TRIGGERED_STATE = {**GOOD_STATE, "events": 4, "triggered": True, "command": "python3 -I x ROLE_SLOT", "handoff": "/h"}


def assistant(tokens=0, model="claude-sonnet-5-5", **extra):
    entry = {"type": "assistant", "message": {"model": model, "usage": {"input_tokens": tokens, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}}
    entry.update(extra)
    return json.dumps(entry)


def filler(size, text="x"):
    return json.dumps({"type": "user", "message": {"content": text * size}})


class HookTestCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.tmp = os.path.join(self.root, "tmp")
        os.mkdir(self.tmp)
        self.folder = os.path.join(self.tmp, "claude-context-handoff")
        self.transcript = os.path.join(self.root, "transcript.jsonl")
        self.write_transcript([assistant(10)])

    def write_transcript(self, lines, path=None):
        with open(path or self.transcript, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")

    def make_folder(self):
        if not os.path.isdir(self.folder):
            os.mkdir(self.folder, 0o700)

    def seed(self, name, content, session=SESSION):
        self.make_folder()
        with open(os.path.join(self.folder, session + "." + name), "w", encoding="utf-8") as handle:
            handle.write(content if isinstance(content, str) else json.dumps(content))

    def seed_window(self, size=WINDOW, model_id="claude-sonnet-5-5[1m]", session=SESSION):
        self.seed("window", {"context_window_size": size, "model_id": model_id}, session)

    def state(self, session=SESSION):
        path = os.path.join(self.folder, session + ".state")
        if not os.path.exists(path):
            return None
        with open(path) as handle:
            return json.load(handle)

    def hook_input(self, event="Stop", session=SESSION, **fields):
        data = {
            "session_id": session,
            "transcript_path": self.transcript,
            "cwd": "/work/repo",
            "permission_mode": "auto",
            "effort": {"level": "medium"},
            "hook_event_name": event,
        }
        if event == "PostToolUse":
            data.update(tool_name="Read", tool_input={}, tool_response="")
        data.update(fields)
        return data

    def env(self, **extra):
        env = {"PATH": "/usr/bin:/bin", "TMPDIR": self.tmp}
        env.update(extra)
        return {key: value for key, value in env.items() if value is not None}

    def run_hook(self, event="Stop", stdin=None, script=HOOK, preexec_fn=None, env=None, run_cwd=None, **fields):
        data = stdin if stdin is not None else json.dumps(self.hook_input(event, **fields)).encode()
        result = subprocess.run([sys.executable, "-I", script], input=data, env=env or self.env(), capture_output=True, timeout=30, preexec_fn=preexec_fn, cwd=run_cwd)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b"")
        return json.loads(result.stdout) if result.stdout else None

    def assert_block(self, output):
        self.assertEqual(set(output), {"decision", "reason"})
        self.assertEqual(output["decision"], "block")

    def assert_halt(self, output):
        self.assertEqual(set(output), {"continue", "stopReason"})
        self.assertIs(output["continue"], False)

    def command_line(self, output):
        return next(line for line in output["reason"].splitlines() if line.startswith("python3 -I "))

    def command_args(self, output):
        return shlex.split(self.command_line(output))

    def seed_over_threshold(self):
        self.seed_window()
        self.write_transcript([assistant(90000)])


class ThresholdTest(HookTestCase):
    def test_below_80_percent_gives_no_output_but_counts_the_event(self):
        self.seed_window()
        self.write_transcript([assistant(79999)])
        self.assertIsNone(self.run_hook())
        self.assertEqual(self.state()["events"], 1)
        self.assertFalse(self.state()["triggered"])

    def test_exactly_80_percent_blocks_with_the_instruction(self):
        self.seed_window()
        self.write_transcript([assistant(80000)])
        output = self.run_hook()
        self.assert_block(output)
        reason = output["reason"]
        handoff = os.path.join(self.folder, SESSION + ".handoff.md")
        self.assertIn("only allowed Orca CLI call is the coordinator's `ack`", reason)
        self.assertIn("only other allowed command is the launcher", reason)
        self.assertIn("ack only the deliveries that you fully handled", reason)
        self.assertIn("/mattpocock-skills:handoff", reason)
        self.assertIn(f"exactly this path: {handoff} ", reason)
        self.assertIn("Put the State section first", reason)
        self.assertIn("timeout of 120000 ms", reason)
        self.assertEqual(len(reason.splitlines()), 6)  # intro, four steps, command: the empty slots add no text
        state = self.state()
        self.assertTrue(state["triggered"])
        self.assertEqual(state["handoff"], handoff)

    def test_usage_adds_input_and_both_cache_counts(self):
        self.seed_window()
        entry = {"type": "assistant", "message": {"model": "claude-sonnet-5-5", "usage": {"input_tokens": 1000, "cache_read_input_tokens": 70000, "cache_creation_input_tokens": 9000}}}
        self.write_transcript([json.dumps(entry)])
        self.assert_block(self.run_hook())

    def test_measure_uses_the_last_qualifying_line(self):
        skipped = {
            "sidechain": assistant(10, isSidechain=True),
            "synthetic": assistant(0, model="<synthetic>"),
            "api error": assistant(0, isApiErrorMessage=True),
            "no token field": json.dumps({"type": "assistant", "message": {"model": "claude-sonnet-5-5", "usage": {}}}),
            "boolean count": json.dumps({"type": "assistant", "message": {"model": "claude-sonnet-5-5", "usage": {"input_tokens": True}}}),
            "negative count": assistant(-5),
            "no model": json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 1}}}),
            "empty model": json.dumps({"type": "assistant", "message": {"model": "", "usage": {"input_tokens": 1}}}),
            "unparsable last line": '{"type": "assistant", "message": {"usage": ',
            "user line with usage": json.dumps({"type": "user", "message": {"model": "claude-sonnet-5-5", "usage": {"input_tokens": 10}}}),
            "string count": json.dumps({"type": "assistant", "message": {"model": "claude-sonnet-5-5", "usage": {"input_tokens": "10"}}}),
            "usage not an object": json.dumps({"type": "assistant", "message": {"model": "claude-sonnet-5-5", "usage": [10]}}),
            "message not an object": json.dumps({"type": "assistant", "message": "usage"}),
            "line not an object": '["usage"]',
        }
        for name, line in skipped.items():
            with self.subTest(name=name):
                session = "s-" + name.replace(" ", "-")
                self.seed_window(session=session)
                self.write_transcript([assistant(90000), line])
                self.assert_block(self.run_hook(session=session))
        self.write_transcript([json.dumps({"type": "user"})])
        self.seed_window(session="no-assistant")
        self.assertIsNone(self.run_hook(session="no-assistant"))

    def test_a_sidechain_line_is_not_counted(self):
        self.seed_window()  # without the skip, the 95000 line would trigger at 100000
        self.write_transcript([assistant(10), assistant(95000, isSidechain=True)])
        self.assertIsNone(self.run_hook())

    def test_events_with_no_measure_still_count(self):
        self.seed_window()
        os.remove(self.transcript)
        self.assertIsNone(self.run_hook())
        self.assertEqual(self.state()["events"], 1)


class WindowTest(HookTestCase):
    def test_window_file_comes_before_the_table_and_keeps_the_model_suffix(self):
        self.seed_window(size=100000, model_id="claude-sonnet-5-5[1m]")
        self.write_transcript([assistant(80000, model="claude-sonnet-5-5")])
        self.assertEqual(self.command_args(self.run_hook())[6], "claude-sonnet-5-5[1m]")

    def test_table_is_used_without_a_window_file_and_gives_the_transcript_model(self):
        self.write_transcript([assistant(799999, model="claude-sonnet-5-5-20260101")])
        self.assertIsNone(self.run_hook())
        self.write_transcript([assistant(800000, model="claude-sonnet-5-5-20260101")])
        self.assertEqual(self.command_args(self.run_hook())[6], "claude-sonnet-5-5-20260101")

    def test_table_prefix_boundaries(self):
        cases = {"claude-sonnet-5-5-20260101": True, "claude-fable-5-1": True, "claude-opus-5-5": True, "claude-opus-4-7": True, "claude-haiku-5-5": True,
                 "claude-sonnet-50": False, "claude-opus-4-6": False, "claude-sonnet-4-6[1m]": False, "claude-haiku-4-5": False, "claude-sonnet-5x": False}
        for model, expected in cases.items():
            with self.subTest(model=model):
                session = "m-" + re.sub(r"[^A-Za-z0-9_-]", "_", model)  # the session id must be a plain token
                self.write_transcript([assistant(900000, model=model)])
                output = self.run_hook(session=session)
                self.assertEqual(output is not None, expected)

    def test_unknown_window_skips_the_check_but_counts_the_event(self):
        self.write_transcript([assistant(900000, model="claude-mystery-1")])
        self.assertIsNone(self.run_hook())
        self.assertEqual(self.state()["events"], 1)
        self.assertIsNone(self.run_hook())
        self.assertEqual(self.state()["events"], 2)

    def test_invalid_window_files_count_as_absent(self):
        # Each file would trigger at 50000 tokens if it were accepted; the table gives 1M, so there is no output.
        self.write_transcript([assistant(50000, model="claude-sonnet-5-5")])
        bad = {
            "bad json": "{nope",
            "list": "[1]",
            "boolean size": json.dumps({"context_window_size": True, "model_id": "m"}),
            "fractional size": json.dumps({"context_window_size": 1.5, "model_id": "m"}),
            "zero size": json.dumps({"context_window_size": 0, "model_id": "m"}),
            "string size": json.dumps({"context_window_size": "10000", "model_id": "m"}),
            "missing model": json.dumps({"context_window_size": 10000}),
            "empty model": json.dumps({"context_window_size": 10000, "model_id": ""}),
        }
        for name, text in bad.items():
            with self.subTest(name=name):
                session = "w-" + name.replace(" ", "-")
                self.seed("window", text, session)
                self.assertIsNone(self.run_hook(session=session))
                self.assertEqual(self.state(session)["events"], 1)  # the event was handled, not lost to an error
        with self.subTest(name="not utf-8"):
            self.make_folder()
            with open(os.path.join(self.folder, "w-utf.window"), "wb") as handle:
                handle.write(b"\xff\xfe")
            self.assertIsNone(self.run_hook(session="w-utf"))
        with self.subTest(name="oversize"):
            self.seed("window", json.dumps({"context_window_size": 10000, "model_id": "m" * 70000}), "w-big")
            self.assertIsNone(self.run_hook(session="w-big"))
        with self.subTest(name="fifo"):
            os.mkfifo(os.path.join(self.folder, "w-fifo.window"))
            self.assertIsNone(self.run_hook(session="w-fifo"))

    def test_a_size_above_2_to_the_53_counts_as_absent(self):
        # With a model that is not in the table: an accepted window would trigger, a rejected one leaves the window unknown.
        self.seed("window", json.dumps({"context_window_size": 2**54, "model_id": "m"}))
        self.write_transcript([assistant(2**55, model="claude-mystery-1")])
        self.assertIsNone(self.run_hook())
        self.seed("window", json.dumps({"context_window_size": 2**53, "model_id": "m"}), "edge")
        self.assert_block(self.run_hook(session="edge"))

    def test_whole_float_size_is_accepted_as_an_integer(self):
        self.seed("window", json.dumps({"context_window_size": 100000.0, "model_id": "m"}))
        self.write_transcript([assistant(80000)])
        self.assert_block(self.run_hook())


class SkipTest(HookTestCase):
    def setUp(self):
        super().setUp()
        self.seed_over_threshold()

    def assert_untouched(self, output):
        self.assertIsNone(output)
        self.assertIsNone(self.state())

    def test_subagent_events_are_skipped(self):
        self.assert_untouched(self.run_hook("PostToolUse", agent_id="agent-1", agent_type="Explore"))

    def test_headless_sessions_are_skipped(self):
        self.assert_untouched(self.run_hook(env=self.env(CLAUDE_CODE_SESSION_ATTENDED="0")))

    def test_other_attended_values_count_as_interactive(self):
        for value in ("1", "", "yes"):
            with self.subTest(value=value):
                session = "a-" + (value or "empty")
                self.seed_window(session=session)
                self.assert_block(self.run_hook(session=session, env=self.env(CLAUDE_CODE_SESSION_ATTENDED=value)))

    def test_other_events_are_ignored(self):
        self.assert_untouched(self.run_hook("UserPromptSubmit"))

    def test_invalid_session_ids_give_no_output_and_no_files(self):
        for session in ("../x", "", "a" * 129, "a b", None, 5):
            with self.subTest(session=session):
                self.assertIsNone(self.run_hook(stdin=json.dumps(self.hook_input(session=session)).encode()))
        self.assertEqual(sorted(os.listdir(self.folder)), [SESSION + ".window"])
        self.assertEqual(os.listdir(self.tmp), ["claude-context-handoff"])


class ReblockTest(HookTestCase):
    def setUp(self):
        super().setUp()
        self.seed_over_threshold()

    def test_stop_reblocks_with_the_same_reason_three_times_then_halts(self):
        first = self.run_hook("Stop")
        self.assert_block(first)
        for count in (1, 2, 3):
            again = self.run_hook("Stop")
            self.assert_block(again)
            self.assertEqual(again["reason"], first["reason"])
            self.assertEqual(self.state()["reblocks"], count)
        halt = self.run_hook("Stop")
        self.assert_halt(halt)
        self.assertEqual(halt["stopReason"], "handoff failed: no launcher call after 3 reminders; write the handoff, replace ROLE_SLOT, then run: "
                         + self.command_line(first))
        self.assertTrue(self.state()["done"])

    def test_post_tool_use_reblocks_only_after_ten_calls_and_can_halt(self):
        self.assert_block(self.run_hook("PostToolUse"))
        for call in range(1, 10):
            self.assertIsNone(self.run_hook("PostToolUse"), call)
        self.assert_block(self.run_hook("PostToolUse"))
        self.assertEqual(self.state()["reblocks"], 1)
        for call in range(1, 10):  # the counter restarted after the re-block
            self.assertIsNone(self.run_hook("PostToolUse"), call)
        self.assert_block(self.run_hook("PostToolUse"))
        self.assertEqual(self.state()["reblocks"], 2)
        # The third re-block is already used: the 10th call after it halts.
        self.seed("state", {**self.state(), "reblocks": 3, "calls_since_block": 8})
        self.assertIsNone(self.run_hook("PostToolUse"))
        self.assert_halt(self.run_hook("PostToolUse"))

    def test_a_halted_session_stays_silent_and_unchanged(self):
        self.seed("state", {**TRIGGERED_STATE, "reblocks": 3})
        self.assert_halt(self.run_hook("Stop"))
        path = os.path.join(self.folder, SESSION + ".state")
        with open(path, "rb") as handle:
            before = handle.read()
        for event in ("Stop", "PostToolUse", "Stop"):
            self.assertIsNone(self.run_hook(event))
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), before)

    def test_the_stored_command_does_not_change_after_a_model_change(self):
        first = self.run_hook("Stop")
        self.seed_window(model_id="claude-other-model")
        self.assertEqual(self.run_hook("Stop")["reason"], first["reason"])

    def test_sessions_have_separate_state(self):
        self.assert_block(self.run_hook("Stop"))
        self.seed_window(session="other")
        self.assert_block(self.run_hook("Stop", session="other"))
        self.assertEqual(self.state()["events"], 1)
        self.assertEqual(self.state("other")["events"], 1)

    def test_unknown_state_keys_survive_a_rewrite(self):
        self.seed("state", {**GOOD_STATE, "future": [1]})
        self.run_hook("Stop")
        self.assertEqual(self.state()["future"], [1])


class CommandTest(HookTestCase):
    def test_command_has_the_seven_filled_values_in_order(self):
        self.seed_window(model_id="claude-fable-5-1[1m]")
        self.write_transcript([assistant(90000)])
        args = self.command_args(self.run_hook())
        self.assertEqual(args, ["python3", "-I", os.path.join(os.path.realpath(HERE), "launch.py"), SESSION, self.folder,
                                os.path.join(self.folder, SESSION + ".handoff.md"), "claude-fable-5-1[1m]", "auto", "medium", "/work/repo", "ROLE_SLOT"])

    def test_missing_values_are_empty_arguments(self):
        self.seed_over_threshold()
        data = self.hook_input()
        for key in ("permission_mode", "effort", "cwd"):
            del data[key]
        args = self.command_args(self.run_hook(stdin=json.dumps(data).encode()))
        self.assertEqual(args[7:10], ["", "", ""])

    def test_values_with_spaces_and_quotes_stay_one_argument(self):
        tmp = os.path.join(self.root, "it's a \"tmp\" dir")
        os.mkdir(tmp)
        self.tmp, self.folder = tmp, os.path.join(tmp, "claude-context-handoff")
        self.seed_window(model_id="mod'el \"x\"; rm -rf /")
        self.write_transcript([assistant(90000)])
        copy = os.path.join(self.root, "hook dir 'x'")
        os.mkdir(copy)
        for name in ("hook.py", "runtime_dir.py"):
            shutil.copy(os.path.join(HERE, name), copy)
        output = self.run_hook(script=os.path.join(copy, "hook.py"), cwd="/work/my repo/it's $(x)")
        args = self.command_args(output)
        self.assertEqual(args[2:], [os.path.join(os.path.realpath(copy), "launch.py"), SESSION, self.folder,
                                    os.path.join(self.folder, SESSION + ".handoff.md"), "mod'el \"x\"; rm -rf /", "auto", "medium",
                                    "/work/my repo/it's $(x)", "ROLE_SLOT"])


class FolderTest(HookTestCase):
    def setUp(self):
        super().setUp()
        self.write_transcript([assistant(90000)])

    def make_work_dir(self):
        work = os.path.join(self.root, "work")
        os.mkdir(work)
        return work

    def test_symlinked_folder_gives_no_output(self):
        target = os.path.join(self.root, "target")
        os.mkdir(target, 0o700)
        os.symlink(target, self.folder)
        work = self.make_work_dir()
        self.assertIsNone(self.run_hook(run_cwd=work))
        self.assertEqual(os.listdir(target), [])
        self.assertEqual(os.listdir(work), [])  # no file falls back to the working directory

    def test_wide_mode_gives_no_output_and_is_not_repaired(self):
        os.mkdir(self.folder, 0o755)
        os.chmod(self.folder, 0o755)
        work = self.make_work_dir()
        self.assertIsNone(self.run_hook(run_cwd=work))
        self.assertEqual(os.listdir(self.folder), [])
        self.assertEqual(os.listdir(work), [])
        self.assertEqual(stat.S_IMODE(os.stat(self.folder).st_mode), 0o755)

    def test_the_hook_creates_the_folder_with_mode_0700(self):
        self.run_hook()
        self.assertEqual(stat.S_IMODE(os.stat(self.folder).st_mode), 0o700)


class OutputPipeTest(HookTestCase):
    def test_a_closed_output_pipe_still_exits_0_with_clean_stderr(self):
        self.seed_over_threshold()
        process = subprocess.Popen([sys.executable, "-I", HOOK], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env())
        process.stdout.close()  # the reader is gone before the hook prints
        process.stdin.write(json.dumps(self.hook_input()).encode())
        process.stdin.close()
        self.assertEqual(process.wait(timeout=30), 0)
        self.assertEqual(process.stderr.read(), b"")
        process.stderr.close()
        self.assertTrue(self.state()["triggered"])


class FailOpenTest(HookTestCase):
    def setUp(self):
        super().setUp()
        self.seed_over_threshold()

    def test_failed_state_write_gives_no_output_and_leaves_no_temp_file(self):
        def limit_file_size():
            resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))

        self.assertIsNone(self.run_hook(preexec_fn=limit_file_size))  # would block
        self.assertIsNone(self.state())
        self.seed("state", {**TRIGGERED_STATE, "reblocks": 3})
        self.assertIsNone(self.run_hook(preexec_fn=limit_file_size))  # would halt
        self.assertFalse(self.state()["done"])
        self.assertFalse([name for name in os.listdir(self.folder) if name.endswith(".tmp")])

    def test_corrupt_state_files_fail_open(self):
        corrupt = {
            "bad json": "{nope",
            "list": "[]",
            "boolean count": json.dumps({**GOOD_STATE, "events": True}),
            "negative count": json.dumps({**GOOD_STATE, "reblocks": -1}),
            "too many reblocks": json.dumps({**GOOD_STATE, "reblocks": 4}),
            "string done flag": json.dumps({**GOOD_STATE, "done": ""}),  # falsy: without validation the event would go on
            "string triggered flag": json.dumps({**TRIGGERED_STATE, "triggered": "yes"}),
            "missing key": json.dumps({"events": 0}),
            "triggered without command": json.dumps({**TRIGGERED_STATE, "command": ""}),
            "triggered without handoff": json.dumps({**TRIGGERED_STATE, "handoff": ""}),
            "command not a string": json.dumps({**GOOD_STATE, "command": 5}),
            "handoff not a string": json.dumps({**GOOD_STATE, "handoff": 5}),
        }
        for name, text in corrupt.items():
            with self.subTest(name=name):
                session = "c-" + name.replace(" ", "-")
                self.seed_window(session=session)
                self.seed("state", text, session)
                self.assertIsNone(self.run_hook(session=session))
        os.mkdir(os.path.join(self.folder, "c-dir.state"))
        self.seed_window(session="c-dir")
        self.assertIsNone(self.run_hook(session="c-dir"))
        os.mkfifo(os.path.join(self.folder, "c-fifo.state"))
        self.seed_window(session="c-fifo")
        self.assertIsNone(self.run_hook(session="c-fifo"))

    def test_garbled_input_and_broken_transcripts_fail_open(self):
        for stdin in (b"", b"not json", b"[1, 2]", b'{"hook_event_name": "Stop"}'):
            with self.subTest(stdin=stdin):
                self.assertIsNone(self.run_hook(stdin=stdin))
        for content in (b"\xff\xfe\x00garbage\n", b"", b"{}\n{}\n"):
            with self.subTest(content=content):
                with open(self.transcript, "wb") as handle:
                    handle.write(content)
                self.assertIsNone(self.run_hook(session="g-" + str(len(content))))
        os.mkfifo(os.path.join(self.root, "fifo"))
        # No measure, but the event is handled and counted (a read error would lose the event).
        for session, path in (("g-dir", self.root), ("g-fifo", os.path.join(self.root, "fifo")), ("g-empty", ""), ("g-int", 5), ("g-none", None), ("g-nul", "a\x00b")):
            with self.subTest(session=session):
                self.seed_window(session=session)
                self.assertIsNone(self.run_hook(session=session, transcript_path=path))
                self.assertEqual(self.state(session)["events"], 1)

    def test_a_missing_shared_module_fails_open(self):
        copy = os.path.join(self.root, "copy")
        os.mkdir(copy)
        shutil.copy(HOOK, copy)
        self.assertIsNone(self.run_hook(script=os.path.join(copy, "hook.py")))

    def test_a_lock_that_stays_taken_gives_no_output_and_no_state_change(self):
        # The first process holds the lock while a second hook run waits for it; the hook waits at most 5 s, then fails open.
        self.make_folder()
        fd = os.open(os.path.join(self.folder, SESSION + ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        self.assertIsNone(self.run_hook())
        self.assertIsNone(self.state())


class ConcurrencyTest(HookTestCase):
    def test_parallel_runs_of_one_session_lose_no_update(self):
        self.seed_window()
        self.write_transcript([assistant(10)])
        data = json.dumps(self.hook_input()).encode()
        processes = [subprocess.Popen([sys.executable, "-I", HOOK], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=self.env()) for _ in range(8)]
        for process in processes:
            process.stdin.write(data)
            process.stdin.close()
        for process in processes:
            self.assertEqual(process.wait(timeout=30), 0)
            process.stdout.close()
        self.assertEqual(self.state()["events"], 8)


class TranscriptScanTest(HookTestCase):
    def setUp(self):
        super().setUp()
        self.seed_window()

    def test_a_multibyte_character_on_a_chunk_edge_is_not_cut(self):
        # 3-byte characters in a line of about 800 KiB: 256 KiB is not a multiple of 3, so a chunk edge cuts a character.
        line = json.dumps({"type": "assistant", "message": {"model": "claude-sonnet-5-5", "text": "€" * 270000, "usage": {"input_tokens": 90000}}}, ensure_ascii=False)
        self.write_transcript([line])
        self.assert_block(self.run_hook())

    def test_a_line_longer_than_a_chunk_is_skipped_over(self):
        self.write_transcript([assistant(90000), filler(600000), filler(5)])
        self.assert_block(self.run_hook())

    def test_a_qualifying_line_longer_than_a_chunk_is_joined_across_chunks(self):
        big = json.dumps({"type": "assistant", "message": {"model": "claude-sonnet-5-5", "text": "x" * 600000, "usage": {"input_tokens": 90000}}})
        self.write_transcript([assistant(10), big, filler(5)])
        self.assert_block(self.run_hook())

    def test_a_line_over_the_line_cap_is_discarded_unparsed_and_the_scan_goes_on(self):
        # The big line is a qualifying assistant line with a low count. Parsed, it would decide (no block); discarded, the scan
        # goes on to the older high line (block). Stopping at the big line would also give no block.
        big = json.dumps({"type": "assistant", "message": {"model": "claude-sonnet-5-5", "text": "x" * (5 * 1024 * 1024), "usage": {"input_tokens": 10}}})
        self.write_transcript([assistant(90000), big, filler(5)])
        self.assert_block(self.run_hook())

    def test_a_complete_line_just_over_the_line_cap_is_discarded(self):
        # 4 MiB + 100 KiB: the line is joined from the carry and one more chunk, so only the length check on complete lines drops it.
        big = json.dumps({"type": "assistant", "message": {"model": "claude-sonnet-5-5", "text": "x" * (4 * 1024 * 1024 + 100 * 1024), "usage": {"input_tokens": 10}}})
        self.write_transcript([assistant(90000), big])
        self.assert_block(self.run_hook())

    def test_the_scan_stops_after_the_total_cap(self):
        lines = [assistant(90000)] + [filler(1000)] * 9500  # about 9.5 MiB after the only qualifying line
        self.write_transcript(lines)
        self.assertGreater(os.path.getsize(self.transcript), 9 * 1024 * 1024)
        start = time.monotonic()
        self.assertIsNone(self.run_hook())
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(self.state()["events"], 1)

    def test_one_run_on_a_10_mb_transcript_is_fast(self):
        lines = [filler(1000)] * 9500 + [assistant(90000)] + [filler(1000)] * 500
        self.write_transcript(lines)
        self.assertGreater(os.path.getsize(self.transcript), 10 * 1000 * 1000)
        start = time.monotonic()
        self.assert_block(self.run_hook())
        self.assertLess(time.monotonic() - start, 5)  # 5 s is a smoke bound for a shared PC; the run takes about 0.1 s


class NoTestSwitchTest(unittest.TestCase):
    def test_the_hook_reads_only_the_documented_environment(self):
        with open(HOOK) as handle:
            source = handle.read()
        self.assertEqual(source.count("os.environ"), 1)  # only CLAUDE_CODE_SESSION_ATTENDED; TMPDIR is read in runtime_dir


if __name__ == "__main__":
    unittest.main()
