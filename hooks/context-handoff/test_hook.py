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
LAUNCHER = os.path.join(os.path.realpath(HERE), "launch.py")
NO_RESULT = "launcher gave no result; check Orca for a successor terminal before you start one"
RESULTS = {
    "ok": "ok context handoff done: successor term_abc",
    "failed": "failed successor failed: the Orca call timed out; the handoff file is at /tmp/x/claude-context-handoff/S.handoff.md; start the successor with cd /w && claude 'Read it'",
    "escalation-failed": "escalation-failed successor term_abc waits; tell the coordinator: 1) orca orchestration worker-stop --dispatch d1; the coordinator may already have the escalation, so check its inbox before you run them",
    "manual": "manual no Orca: the handoff file is at /tmp/x/claude-context-handoff/S.handoff.md; start the successor with cd /w && claude 'Read it'",
}
WINDOW = 100000  # a window file with this size puts the 40% line at 40000 tokens
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


# Runs a script as __main__ with a folder holding a shadow `runtime_dir` module first on the search path. The driver never imports the module itself.
SHADOW_DRIVER = """
import runpy, sys
shadow, script = sys.argv[1], sys.argv[2]
sys.path.insert(0, shadow)
sys.argv = [script] + sys.argv[3:]
runpy.run_path(script, run_name="__main__")
"""


class ModuleSearchPathTest(HookTestCase):
    def test_the_real_runtime_dir_module_wins_over_a_shadow_module_earlier_on_the_search_path(self):
        shadow = os.path.join(self.root, "shadow")
        os.mkdir(shadow)
        with open(os.path.join(shadow, "runtime_dir.py"), "w") as handle:
            handle.write("FOLDER_NAME = 'shadow'\n")
        self.seed_over_threshold()
        data = json.dumps(self.hook_input()).encode()
        result = subprocess.run([sys.executable, "-I", "-c", SHADOW_DRIVER, shadow, HOOK], input=data, env=self.env(), capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b"")
        self.assert_block(json.loads(result.stdout))


class ThresholdTest(HookTestCase):
    def test_below_40_percent_gives_no_output_but_counts_the_event(self):
        self.seed_window()
        self.write_transcript([assistant(39999)])
        self.assertIsNone(self.run_hook())
        self.assertEqual(self.state()["events"], 1)
        self.assertFalse(self.state()["triggered"])

    def test_exactly_40_percent_blocks_with_the_instruction(self):
        self.seed_window()
        self.write_transcript([assistant(40000)])
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
        self.assertEqual(reason.splitlines()[-1], self.command_line(output))  # the launcher command stays on its own last line
        state = self.state()
        self.assertTrue(state["triggered"])
        self.assertEqual(state["handoff"], handoff)

    def test_usage_adds_input_and_both_cache_counts(self):
        self.seed_window()
        entry = {"type": "assistant", "message": {"model": "claude-sonnet-5-5", "usage": {"input_tokens": 500, "cache_read_input_tokens": 35000, "cache_creation_input_tokens": 4500}}}
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
        self.write_transcript([assistant(40000, model="claude-sonnet-5-5")])
        self.assertEqual(self.command_args(self.run_hook())[6], "claude-sonnet-5-5[1m]")

    def test_table_is_used_without_a_window_file_and_gives_the_transcript_model(self):
        self.write_transcript([assistant(399999, model="claude-sonnet-5-5-20260101")])
        self.assertIsNone(self.run_hook())
        self.write_transcript([assistant(400000, model="claude-sonnet-5-5-20260101")])
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
        self.write_transcript([assistant(40000)])
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


class LauncherTestCase(HookTestCase):
    def setUp(self):
        super().setUp()
        self.seed("state", TRIGGERED_STATE)

    def launcher_command(self, session=SESSION, script=LAUNCHER, role="plain"):
        return "python3 -I " + shlex.join([script, session, self.folder, "/h", "claude-sonnet-5-5", "auto", "medium", "/work/repo", role])

    def launcher_call(self, response, command=None, **fields):
        return self.run_hook("PostToolUse", tool_name="Bash", tool_input={"command": command or self.launcher_command()}, tool_response=response, **fields)

    def seed_raw_launch(self, data):
        self.make_folder()
        with open(os.path.join(self.folder, SESSION + ".launch"), "wb") as handle:
            handle.write(data)


class LauncherCallTest(LauncherTestCase):
    def test_each_result_status_halts_with_the_text_after_the_status_word(self):
        for status, line in RESULTS.items():
            text = line[len(status) + 1:]
            for name, response in (("object", {"stdout": line + "\n", "stderr": "", "interrupted": False}), ("string", line + "\n"), ("blank lines", {"stdout": "\n  " + line + "  \n\n"})):
                with self.subTest(status=status, shape=name):
                    self.seed("state", TRIGGERED_STATE)
                    output = self.launcher_call(response)
                    self.assert_halt(output)
                    self.assertEqual(output["stopReason"], text)
                    self.assertTrue(self.state()["done"])

    def test_failed_and_manual_texts_name_the_handoff_path_and_the_start_command(self):
        for status in ("failed", "manual"):
            with self.subTest(status=status):
                self.seed("state", TRIGGERED_STATE)
                reason = self.launcher_call({"stdout": RESULTS[status] + "\n"})["stopReason"]
                self.assertIn("the handoff file is at /tmp/x/claude-context-handoff/S.handoff.md", reason)
                self.assertIn("start the successor with cd /w && claude", reason)

    def test_two_spaces_after_the_status_word_are_stripped(self):
        self.assertEqual(self.launcher_call({"stdout": "ok  context handoff done: successor t1\n"})["stopReason"], "context handoff done: successor t1")

    def test_responses_without_one_parsable_line_give_the_no_result_halt(self):
        bad = ["", None, [], {}, {"stdout": ""}, {"stdout": None}, {"stdout": {"x": 1}}, {"stdout": "ok a\nok b"}, {"stdout": "nonsense"}, {"stdout": "ok"},
               {"stdout": "ok   "}, {"stdout": "okay fine"}, 5, {"stdout": "garbled \x00 ok x"}, {"stdout": "ok a\u2029b"}]
        for response in bad:
            with self.subTest(response=response):
                self.seed("state", TRIGGERED_STATE)
                output = self.launcher_call(response)
                self.assert_halt(output)
                self.assertEqual(output["stopReason"], NO_RESULT)

    def test_other_bash_calls_are_ordinary_calls(self):
        ordinary = {
            "mentions the script": f"cat {shlex.quote(LAUNCHER)}",
            "other session": self.launcher_command(session="other"),
            "other script": self.launcher_command(script="/elsewhere/launch.py"),
            "too short": "python3 -I " + shlex.quote(LAUNCHER),
            "wrapped": "cd /x && " + self.launcher_command(),
            "not splittable": "python3 -I 'unterminated",
            "no python": self.launcher_command().replace("python3 -I", "python -I"),
            "no -I": self.launcher_command().replace("python3 -I", "python3"),
        }
        for name, command in ordinary.items():
            with self.subTest(name=name):
                self.seed("state", TRIGGERED_STATE)
                self.assertIsNone(self.launcher_call({"stdout": RESULTS["ok"]}, command=command))
                self.assertEqual(self.state()["calls_since_block"], 1)
        self.seed("state", TRIGGERED_STATE)
        self.assertIsNone(self.run_hook("PostToolUse", tool_name="Read", tool_input={"command": self.launcher_command()}, tool_response=RESULTS["ok"]))
        for tool_input in (None, {"command": 5}, {"command": None}, "x", {}):
            with self.subTest(tool_input=tool_input):
                self.assertIsNone(self.run_hook("PostToolUse", tool_name="Bash", tool_input=tool_input, tool_response=RESULTS["ok"]))

    def test_the_result_line_wins_over_the_launch_file(self):
        self.seed("launch", "started\n")
        output = self.launcher_call({"stdout": RESULTS["ok"] + "\n"})
        self.assertEqual(output["stopReason"], "context handoff done: successor term_abc")

    def test_a_halted_session_stays_silent(self):
        self.launcher_call({"stdout": RESULTS["ok"]})
        for event in ("Stop", "PostToolUse"):
            self.assertIsNone(self.run_hook(event))
        self.assertIsNone(self.launcher_call({"stdout": RESULTS["failed"]}))

    def test_a_launcher_call_while_not_triggered_is_an_ordinary_call_below_40_percent(self):
        self.seed("state", GOOD_STATE)
        self.seed_window()
        self.write_transcript([assistant(100)])
        self.seed("launch", "started\n")  # a stray launch file is ignored while not triggered
        self.assertIsNone(self.launcher_call({"stdout": RESULTS["ok"]}))
        self.assertIsNone(self.run_hook("Stop"))
        self.assertFalse(self.state()["triggered"])
        self.assertFalse(self.state()["done"])

    def test_a_launcher_call_while_not_triggered_over_the_threshold_triggers_the_block(self):
        self.seed("state", GOOD_STATE)
        self.seed_over_threshold()
        self.assert_block(self.launcher_call({"stdout": RESULTS["ok"]}))
        self.assertTrue(self.state()["triggered"])


class LaunchFileTest(LauncherTestCase):
    """The launch file shapes: A started only, B started and a result line, C other, D missing, E unreadable."""

    def events(self):
        yield "Stop", lambda: self.run_hook("Stop")
        yield "PostToolUse", lambda: self.run_hook("PostToolUse")
        yield "launcher call", lambda: self.launcher_call({"stdout": "garbled"})

    def check(self, content, expected):
        for name, run in self.events():
            with self.subTest(content=content, event=name):
                self.seed("state", TRIGGERED_STATE)
                if content is None:
                    path = os.path.join(self.folder, SESSION + ".launch")
                    if os.path.exists(path):
                        os.remove(path)
                else:
                    self.seed_raw_launch(content if isinstance(content, bytes) else content.encode())
                output = run()
                expected_for_event = expected[name] if isinstance(expected, dict) else expected
                if expected_for_event == "block":
                    self.assert_block(output)
                elif expected_for_event is None:
                    self.assertIsNone(output)
                else:
                    self.assert_halt(output)
                    self.assertEqual(output["stopReason"], expected_for_event)

    def test_shape_a_gives_the_no_result_halt(self):
        self.check("started\n", NO_RESULT)
        self.check("  started  \n\n", NO_RESULT)

    def test_shape_b_gives_the_text_of_the_result_line(self):
        self.check("started\nok context handoff done: successor t9\n", "context handoff done: successor t9")
        self.check("started\n\nmanual no Orca: the handoff file is at /h\n\n", "no Orca: the handoff file is at /h")

    def test_control_characters_in_the_result_text_become_spaces_and_the_result_is_trimmed_once(self):
        self.check("started\nok \x1b\x07a\x1bb\x07\n", "a b")

    def test_a_result_text_of_only_control_characters_gives_the_no_result_halt(self):
        self.check("started\nok \x1b\x07\n", NO_RESULT)

    def test_a_control_character_between_the_status_word_and_the_text_is_shape_c(self):
        self.check("started\nok\x1btext\n", NO_RESULT)

    def test_a_paragraph_separator_inside_the_result_text_is_shape_c(self):
        self.check("started\nok a\u2029b\n", NO_RESULT)

    def test_shape_c_gives_the_no_result_halt(self):
        for content in ("started\nok\n", "started\nok a\nok b\n", "garbage\n", "started\nbad line\n", "", "\n", "ok context handoff done: x\n"):
            self.check(content, NO_RESULT)

    def test_shape_d_re_blocks_on_stop_is_quiet_on_a_call_and_halts_a_launcher_call(self):
        self.check(None, {"Stop": "block", "PostToolUse": None, "launcher call": NO_RESULT})

    def test_shape_e_fails_open_except_for_a_launcher_call(self):
        self.check(b"started\n\xff\xfe", {"Stop": None, "PostToolUse": None, "launcher call": NO_RESULT})
        self.check(b"started\n" + b"x" * (64 * 1024 + 1), {"Stop": None, "PostToolUse": None, "launcher call": NO_RESULT})

    def test_shape_e_leaves_the_state_unchanged(self):
        self.seed("state", TRIGGERED_STATE)
        self.seed_raw_launch(b"\xff")
        self.assertIsNone(self.run_hook("Stop"))
        self.assertIsNone(self.run_hook("PostToolUse"))
        self.assertEqual(self.state(), TRIGGERED_STATE)

    def test_a_launch_file_that_is_a_directory_is_shape_e(self):
        os.mkdir(os.path.join(self.folder, SESSION + ".launch"))
        self.assertIsNone(self.run_hook("Stop"))
        self.assertEqual(self.state(), TRIGGERED_STATE)

    def test_the_launch_file_is_ignored_in_another_session(self):
        self.seed("launch", "started\n", session="other")
        self.assert_block(self.run_hook("Stop"))


class LoopGuardTest(HookTestCase):
    PREDECESSOR = "99999999-8888-7777-6666-555555555555"
    MANUAL = "the handoff file is at /h; start the successor with cd /w && claude 'Read it'"

    def setUp(self):
        super().setUp()
        self.marker = os.path.join(self.folder, self.PREDECESSOR + ".handoff.md")
        self.seed("manual", self.MANUAL + "\n", session=self.PREDECESSOR)
        self.seed_over_threshold()

    def run_marked(self, marker=None, event="Stop", **fields):
        return self.run_hook(event, env=self.env(CONTEXT_HANDOFF_SUCCESSOR=self.marker if marker is None else marker), **fields)

    def generic(self, percent=90):
        return f"handoff loop: context already at {percent}% after takeover"

    def test_the_first_event_over_the_threshold_with_the_marker_halts_with_the_manual_text(self):
        output = self.run_marked()
        self.assert_halt(output)
        self.assertEqual(output["stopReason"], self.generic() + "; " + self.MANUAL)
        state = self.state()
        self.assertTrue(state["done"])
        self.assertFalse(state["triggered"])
        self.assertEqual(state["events"], 1)
        self.assertIsNone(self.run_marked())
        self.assertIsNone(self.run_marked(event="PostToolUse"))

    def test_the_percent_is_rounded_down(self):
        self.write_transcript([assistant(40999)])
        self.assertEqual(self.run_marked()["stopReason"], self.generic(40) + "; " + self.MANUAL)

    def test_the_guard_also_fires_on_a_post_tool_use_event(self):
        self.assert_halt(self.run_marked(event="PostToolUse"))

    def test_no_marker_empty_marker_or_a_later_event_gives_the_block(self):
        self.assert_block(self.run_hook("Stop"))
        self.seed_window(session="empty")
        self.assert_block(self.run_marked(marker="", session="empty"))
        self.seed_window(session="later")
        self.seed("state", {**GOOD_STATE, "events": 1}, session="later")
        self.assert_block(self.run_marked(session="later"))

    def test_a_successor_with_a_first_event_below_40_percent_hands_over_normally_later(self):
        self.write_transcript([assistant(100)])
        self.assertIsNone(self.run_marked())
        self.write_transcript([assistant(90000)])
        self.assert_block(self.run_marked())

    def test_no_guard_without_a_transcript_measure(self):
        os.remove(self.transcript)
        self.assertIsNone(self.run_marked())
        self.assertEqual(self.state()["events"], 1)
        self.write_transcript([assistant(90000)])
        self.assert_block(self.run_marked())

    def test_the_window_table_is_the_fallback(self):
        os.remove(os.path.join(self.folder, SESSION + ".window"))
        self.write_transcript([assistant(400000, model="claude-sonnet-5-5-20260101")])
        self.assertEqual(self.run_marked()["stopReason"], self.generic(40) + "; " + self.MANUAL)

    def test_a_marker_that_cannot_be_trusted_gives_only_the_generic_text(self):
        other = os.path.join(self.root, "other", "claude-context-handoff")
        os.makedirs(other, mode=0o700)
        with open(os.path.join(other, self.PREDECESSOR + ".manual"), "w") as handle:
            handle.write("OTHER FOLDER TEXT")
        os.symlink(os.path.join(other, self.PREDECESSOR + ".handoff.md"), os.path.join(self.folder, self.PREDECESSOR + ".handoff.md"))  # same name as the manual file owner: only a real-path check sees that it leaves the folder
        os.mkdir(os.path.join(self.folder, "sub"))
        for guarded in ("abc", "bad id", "", "rel"):  # readable manual files that a missing name or session id check would show
            with open(os.path.join(self.folder, guarded + ".manual"), "w") as handle:
                handle.write("UNGUARDED TEXT")
        cases = {
            "relative": "claude-context-handoff/rel.handoff.md",
            "another folder": os.path.join(other, self.PREDECESSOR + ".handoff.md"),
            "through ..": os.path.join(self.folder, "sub", "..", "..", "other", "claude-context-handoff", self.PREDECESSOR + ".handoff.md"),
            "through a symlink": os.path.join(self.folder, self.PREDECESSOR + ".handoff.md"),
            "not a handoff name": os.path.join(self.folder, "abc12345678901"),  # without the name check, the last 11 characters would be cut and abc.manual read
            "invalid session id": os.path.join(self.folder, "bad id.handoff.md"),
            "empty session id": os.path.join(self.folder, ".handoff.md"),
            "below the folder": os.path.join(self.folder, "sub", self.PREDECESSOR + ".handoff.md"),
            "the folder": self.folder,
        }
        for name, marker in cases.items():
            with self.subTest(name=name):
                session = "g-" + name.replace(" ", "-").replace("..", "dots")
                self.seed_window(session=session)
                output = self.run_marked(marker=marker, session=session, run_cwd=self.tmp)  # the cwd makes the relative marker point into the folder
                self.assertEqual(output["stopReason"], self.generic())

    def test_a_missing_empty_or_unsafe_manual_file_gives_the_generic_text(self):
        manual = os.path.join(self.folder, self.PREDECESSOR + ".manual")
        os.remove(manual)
        self.assertEqual(self.run_marked()["stopReason"], self.generic())
        def write(data):
            with open(manual, "wb") as handle:
                handle.write(data)

        cases = {
            "empty": lambda: write(b""),
            "blank": lambda: write(b" \n"),
            "not utf-8": lambda: write(b"\xff"),
            "over the limit": lambda: write(b"x" * (64 * 1024 + 1)),
            "symlink": lambda: os.symlink(os.path.join(self.root, "target"), manual),
            "fifo": lambda: os.mkfifo(manual),
            "directory": lambda: os.mkdir(manual),
        }
        with open(os.path.join(self.root, "target"), "w") as handle:
            handle.write("TARGET TEXT")
        for name, make in cases.items():
            with self.subTest(name=name):
                if os.path.lexists(manual):
                    if os.path.isdir(manual) and not os.path.islink(manual):
                        os.rmdir(manual)
                    else:
                        os.remove(manual)
                make()
                session = "m-" + name.replace(" ", "-")
                self.seed_window(session=session)
                self.assertEqual(self.run_marked(session=session)["stopReason"], self.generic())

    def halt_text(self, manual):
        self.seed("manual", manual, session=self.PREDECESSOR)
        return self.run_marked()["stopReason"]

    def test_each_control_character_inside_the_manual_text_becomes_a_space(self):
        self.assertEqual(self.halt_text("the handoff\x1bfile is\x07\x00at /h\u2028x\u2029y"), self.generic() + "; the handoff file is  at /h x y")

    def test_control_characters_at_both_ends_are_trimmed_once(self):
        self.assertEqual(self.halt_text("\x1b\x07 " + self.MANUAL + " \x00\n"), self.generic() + "; " + self.MANUAL)

    def test_a_manual_text_of_only_control_characters_and_whitespace_gives_the_generic_text(self):
        self.assertEqual(self.halt_text("\x1b \n\x07\t\u2028"), self.generic())


class InstructionTest(HookTestCase):
    def reason(self, **fields):
        self.seed_over_threshold()
        return self.run_hook("Stop", **fields)["reason"]

    def test_step_4_gives_the_three_roles(self):
        reason = self.reason()
        self.assertIn("First replace the word ROLE_SLOT as the role blocks say. For a plain session (not an Orca coordinator or worker), the role is `plain`."
                      " If you have no Orca preamble and own no Orca Run, you are plain."
                      " For an Orca coordinator (a session that owns an Orca Run and dispatches workers on it), the role is `coordinator`."
                      " For an Orca worker (a session that Orca dispatched under a Task, with an injected preamble), the role is `worker`: replace the word ROLE_SLOT with"
                      " `worker` and then four more words copied from the preamble, in this order and each in single quotes: your own terminal handle (the `--from` value),"
                      " the Task ID, the Dispatch ID, and your coordinator's terminal handle."
                      " If a value contains a single quote or a control character, do not run the command; tell the user.", reason)

    def test_the_re_block_repeats_the_instruction(self):
        first = self.reason()
        self.assertEqual(self.run_hook("Stop")["reason"], first)

    def test_step_3_has_the_state_layout_with_the_filled_values(self):
        reason = self.reason()
        for field in ("session type: plain, worker or coordinator", "cwd and worktree path", "git branch", "model, permission mode and effort: copy them from the command in step 4",
                      "predecessor Orca terminal handle, or none", "links to the map, the spec and the ticket in progress", "the review phase (CLAUDE.md section 6) and its round count"):
            self.assertIn("   - " + field, reason)
        self.assertIn(f"   - predecessor session_id: {SESSION}", reason)
        self.assertIn(f"   - predecessor transcript_path: {self.transcript}", reason)
        self.assertIn("Write unknown for a field that you do not know. Run no command to find it", reason)

    def test_step_3_has_the_successor_steps_for_the_plain_and_coordinator_roles(self):
        reason = self.reason()
        self.assertIn('under the heading "Successor steps"', reason)
        self.assertIn("check each Orca ID that you take from the handoff with Orca before you use it (`run-show`, `task-list`, `worker-show`)", reason)
        self.assertIn("if any takeover step fails, keep the old terminal open, tell the user what failed, and stop", reason)
        self.assertIn("Plain session only:\n   1. Read the handoff.", reason)
        self.assertIn("then close that terminal. If your first prompt names no Orca terminal, tell the user to close the old session instead.", reason)
        self.assertIn("3. Continue the work.", reason)
        self.assertNotIn("Plain session:", reason)

    def test_step_3_has_the_worker_fields_after_the_core_and_before_the_coordinator_fields(self):
        reason = self.reason()
        lead_in = "A worker adds these fields after the core fields, one per line, in this order:"
        fields = ("the injected Orca preamble, copied exactly (terminal handle, Task ID, Dispatch ID, `ask` command, coordinator handle)",
                  "any ask that waits for an answer, with its message ID, or none",
                  "asks answered but not yet acted on: each with its message ID and the answer copied word for word, or none")
        self.assertLess(reason.index("the review phase (CLAUDE.md section 6)"), reason.index(lead_in))
        position = reason.index(lead_in)
        for field in fields:
            self.assertLess(position, reason.index("   - " + field, position))
            position = reason.index("   - " + field, position)
        self.assertLess(position, reason.index("A coordinator adds these fields"))
        self.assertIn("Write unknown for a field of this list that you do not know; run no command to find it.\n"
                      "   Before you write the handoff, fill the field of asks answered but not yet acted on: read the output of every `ask` command that ran in the background and finished."
                      " Use the Read tool: it is not a command, so step 1 allows it. An answer that is already in your context goes in this field too.",
                      reason[position:reason.index("A coordinator adds")])

    def test_step_3_has_the_worker_steps_after_the_coordinator_steps(self):
        reason = self.reason()
        label = "Worker (use these steps instead of the plain steps):"
        self.assertLess(reason.index("5. Skip the messages that the handoff marks as done"), reason.index(label))
        steps = reason[reason.index(label):reason.index("4. Run this command")]
        parts = ("1. Wait for the new Dispatch. It arrives soon. Do nothing else and set no timeout: the coordinator may be busy or handing over.",
                 "2. When it arrives, check the Task ID and the new Dispatch ID of the new preamble with `worker-show --dispatch <new Dispatch ID>`, then read the handoff before you act on the Task.",
                 "Use neither the old Dispatch ID nor the old terminal handle in any Orca call.",
                 "3. Do the Task under the new preamble. An ask from the old Dispatch is closed. Act on each answer that the handoff holds.",
                 "Ask again under the new Dispatch only for an ask that has no answer in the handoff and whose answer you still need.",
                 "4. Send `worker_done` with the IDs from the new preamble.",
                 "The coordinator's commands close the old terminal: a worker never closes it.")
        position = 0
        for part in parts:
            self.assertIn(part, steps[position:])
            position = steps.index(part, position)
        self.assertLess(reason.index("if any takeover step fails, keep the old terminal open"), reason.index(label))

    def test_step_3_has_the_coordinator_fields_after_the_core_and_before_the_steps(self):
        reason = self.reason()
        lead_in = "A coordinator adds these fields after the core fields, one per line, in this order:"
        fields = ("Run ID", "active Dispatches, each with its Task ID, or none", "unacked delivery IDs, each with every message in it, or none.",
                  "unanswered questions and escalations that wait for an answer, or none", "the next CLAUDE.md section-7 step per ticket")
        self.assertLess(reason.index("the review phase (CLAUDE.md section 6)"), reason.index(lead_in))
        position = reason.index(lead_in)
        for field in fields:
            self.assertIn("   - " + field, reason[position:])
            self.assertLess(position, reason.index("   - " + field, position))
            position = reason.index("   - " + field, position)
        self.assertLess(position, reason.index("Successor steps"))
        for text in ("Name each message by its Orca message ID, its sender and its subject, and mark it done or not done.",
                     "The successor matches a message by its message ID, because the delivery IDs change at redelivery.",
                     "Write unknown for a field of this list that you do not know; run no command to find it."):
            self.assertIn(text, reason)

    def test_step_3_has_the_coordinator_steps_after_the_plain_steps(self):
        reason = self.reason()
        label = "Coordinator (use these steps instead of the plain steps):"
        self.assertLess(reason.index("3. Continue the work."), reason.index(label))
        steps = reason[reason.index(label):reason.index("4. Run this command")]
        parts = ("1. Read the handoff. It holds the Run ID.", "2. Check the Run ID with `run-show --id <Run ID>`. Then bind the Run with `run-use --id <Run ID>`.",
                 "`consumer_fenced`", "its `task-create` and `worker-start` fail.", "3. Check the old terminal handle that your first prompt names", "then close that terminal.",
                 "4. Run `check`. Unacked deliveries return under new delivery IDs.", "`task-list` and `worker-show`", "do not act on that ID.",
                 "5. Skip the messages that the handoff marks as done. Match them by message ID. Ack each delivery once all of its messages are done or handled.")
        position = 0
        for part in parts:
            self.assertIn(part, steps[position:])
            position = steps.index(part, position)
        self.assertLess(steps.index("`run-use --id"), steps.index("close that terminal"))  # the close comes after the bind
        self.assertLess(reason.index("if any takeover step fails, keep the old terminal open"), reason.index(label))

    def test_the_state_layout_comes_before_step_4_and_the_command_is_last(self):
        reason = self.reason()
        self.assertLess(reason.index("The State section has these fields"), reason.index("4. Run this command"))
        self.assertLess(reason.index("Successor steps"), reason.index("4. Run this command"))
        self.assertTrue(reason.splitlines()[-1].startswith("python3 -I "))
        self.assertEqual(sum(line.startswith("python3 -I ") for line in reason.splitlines()), 1)

    def test_a_path_with_a_line_break_or_control_character_is_written_as_unknown(self):
        for index, name in enumerate(("tr\nans.jsonl", "tr\u2028ans.jsonl", "tr\u2029ans.jsonl", "tr\x1bans.jsonl", "tr\u202eans.jsonl", "tr\rans.jsonl")):
            with self.subTest(name=name):
                session = f"c-{index}"
                path = os.path.join(self.root, name)
                self.write_transcript([assistant(90000)], path=path)
                self.seed_window(session=session)
                reason = self.run_hook("Stop", session=session, transcript_path=path)["reason"]
                self.assertIn("   - predecessor transcript_path: unknown", reason.splitlines())

    def test_a_missing_or_empty_transcript_path_on_a_re_block_is_written_as_unknown(self):
        for transcript_path in (None, ""):
            with self.subTest(transcript_path=transcript_path):
                self.seed("state", TRIGGERED_STATE)
                reason = self.run_hook("Stop", transcript_path=transcript_path)["reason"]
                self.assertIn("   - predecessor transcript_path: unknown", reason.splitlines())
                self.assertIn(f"   - predecessor session_id: {SESSION}", reason.splitlines())

    def test_a_lock_timeout_does_not_count_an_event_with_the_launcher_rules_in_place(self):
        self.seed("state", TRIGGERED_STATE)
        self.seed("launch", "started\n")
        lock = os.open(os.path.join(self.folder, SESSION + ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, lock)
        fcntl.flock(lock, fcntl.LOCK_EX)
        self.assertIsNone(self.run_hook("Stop"))
        self.assertEqual(self.state(), TRIGGERED_STATE)


class NoTestSwitchTest(unittest.TestCase):
    def test_the_hook_reads_only_the_documented_environment(self):
        with open(HOOK) as handle:
            source = handle.read()
        self.assertEqual(source.count("os.environ"), 2)  # CLAUDE_CODE_SESSION_ATTENDED and CONTEXT_HANDOFF_SUCCESSOR; TMPDIR is read in runtime_dir
        self.assertIn('"CLAUDE_CODE_SESSION_ATTENDED"', source)
        self.assertIn('"CONTEXT_HANDOFF_SUCCESSOR"', source)


if __name__ == "__main__":
    unittest.main()
