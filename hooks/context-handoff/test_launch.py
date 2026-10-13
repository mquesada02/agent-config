import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LAUNCH = os.path.join(HERE, "launch.py")
SESSION = "11111111-2222-3333-4444-555555555555"
OLD_HANDLE = "term_old"
NEW_HANDLE = "term_new"
TASK = "task_abc123"
DISPATCH = "ctx_abc123"
COORDINATOR = "term_coord"

# A stand-in for the Orca CLI. It logs each call (with a snapshot of the launch and manual files at that moment) and
# answers from a scenario file: {"<command words>": {"out": <json or raw text>, "sleep": s, "exit": n, "grandchild": bool, "dir_over": path}}.
STUB = r'''#!/usr/bin/env python3
import json, os, subprocess, sys, time
argv = sys.argv[1:]
folder = os.environ["STUB_FOLDER"]
snapshot = {}
for name in os.listdir(folder):
    if name.endswith((".launch", ".manual")):
        path = os.path.join(folder, name)
        snapshot[name] = open(path).read() if os.path.isfile(path) else None
with open(os.environ["STUB_LOG"], "a") as handle:
    handle.write(json.dumps({"prog": os.path.basename(sys.argv[0]), "argv": argv, "files": snapshot}) + "\n")
scenario = json.load(open(os.environ["STUB_SCENARIO"]))
key = " ".join(argv[:2]) if argv[0] in ("terminal", "worktree", "orchestration") else argv[0]
entry = scenario.get(key, {"out": {"ok": False, "error": {"code": "unexpected", "message": "unexpected call " + key}}, "exit": 1})
if entry.get("dir_over"):
    if os.path.exists(entry["dir_over"]):
        os.remove(entry["dir_over"])
    os.mkdir(entry["dir_over"])
if entry.get("grandchild"):
    subprocess.Popen(["sleep", "30"])
time.sleep(entry.get("sleep", 0))
out = entry.get("out", {})
if "bytes" in entry:
    sys.stdout.buffer.write(bytes.fromhex(entry["bytes"]))
else:
    sys.stdout.write(out if isinstance(out, str) else json.dumps(out))
sys.stdout.flush()
sys.exit(entry.get("exit", 0))
'''


def reply(result):
    return {"out": {"ok": True, "result": result}}


def failure(message="boom", code="failed"):
    return {"out": {"ok": False, "error": {"code": code, "message": message}}, "exit": 1}


class LaunchTestCase(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.tmp = os.path.join(self.root, "tmp")
        self.bin = os.path.join(self.root, "bin")
        self.worktree = os.path.join(self.root, "work tree")
        self.cwd = os.path.join(self.worktree, "src dir")
        for path in (self.tmp, self.bin, self.cwd):
            os.makedirs(path)
        self.folder = os.path.join(self.tmp, "claude-context-handoff")
        os.mkdir(self.folder, 0o700)
        self.handoff = os.path.join(self.folder, SESSION + ".handoff.md")
        with open(self.handoff, "w", encoding="utf-8") as handle:
            handle.write("State section\n")
        for name in ("orca", "orca-ide"):
            path = os.path.join(self.bin, name)
            with open(path, "w") as handle:
                handle.write(STUB)
            os.chmod(path, 0o755)
        self.log_path = os.path.join(self.root, "calls.log")
        self.scenario = self.default_scenario()

    def default_scenario(self):
        row = {"path": self.worktree, "isArchived": False, "isBare": False, "hostId": "local", "isMainWorktree": False}
        return {
            "status": reply({"app": {"running": True}, "runtime": {"reachable": True}}),
            "worktree list": reply({"worktrees": [row], "truncated": False}),
            "terminal show": reply({"terminal": {"handle": OLD_HANDLE, "title": "◐ Fix the thing"}}),
            "terminal create": reply({"terminal": {"handle": NEW_HANDLE}}),
            "terminal wait": reply({"wait": {"satisfied": True}}),
            "terminal send": reply({"send": {"prompt": {"stages": ["input_accepted", "turn_started"]}}}),
            "terminal close": reply({"close": {"handle": NEW_HANDLE}}),
            "orchestration worker-show": reply({"dispatch": {"id": DISPATCH, "taskId": TASK, "assigneeHandle": OLD_HANDLE, "status": "dispatched"}}),
            "orchestration send": reply({"message": {"id": "msg_1"}}),
        }

    def arguments(self, **override):
        values = {
            "session_id": SESSION,
            "runtime_dir": self.folder,
            "handoff": self.handoff,
            "model": "claude-sonnet-5-5[1m]",
            "permission_mode": "auto",
            "effort": "medium",
            "cwd": self.cwd,
            "role": "plain",
        }
        values.update(override)
        return list(values.values())

    def env(self, handle=OLD_HANDLE, **extra):
        env = {"PATH": self.bin + ":/usr/bin:/bin", "TMPDIR": self.tmp, "STUB_FOLDER": self.folder, "STUB_LOG": self.log_path}
        if handle:
            env["ORCA_TERMINAL_HANDLE"] = handle
        env.update(extra)
        return {key: value for key, value in env.items() if value is not None}

    def launch(self, args=None, handle=OLD_HANDLE, timeout=60, **extra_env):
        scenario_path = os.path.join(self.root, "scenario.json")
        with open(scenario_path, "w") as handle_file:
            json.dump(self.scenario, handle_file)
        env = self.env(handle=handle, STUB_SCENARIO=scenario_path, **extra_env)
        result = subprocess.run([sys.executable, "-I", LAUNCH] + (args if args is not None else self.arguments()), env=env, capture_output=True, timeout=timeout)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b"")
        text = result.stdout.decode("utf-8")
        self.assertTrue(text.endswith("\n") and text.count("\n") == 1, repr(text))
        status, _, rest = text[:-1].partition(" ")
        return status, rest

    def calls(self):
        if not os.path.exists(self.log_path):
            return []
        with open(self.log_path) as handle:
            return [json.loads(line) for line in handle]

    def names(self):
        return [" ".join(call["argv"][:2]) if call["argv"][0] in ("terminal", "worktree", "orchestration") else call["argv"][0] for call in self.calls()]

    def call(self, name):
        return self.calls()[self.names().index(name)]

    def read(self, name):
        path = os.path.join(self.folder, SESSION + "." + name)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def assert_nothing_called_or_written(self):
        self.assertEqual(self.calls(), [])
        self.assertIsNone(self.read("launch"))
        self.assertIsNone(self.read("manual"))

    def launch_with_failing_temp_files(self, allowed, args=None):
        scenario_path = os.path.join(self.root, "scenario.json")
        with open(scenario_path, "w") as handle:
            json.dump(self.scenario, handle)
        env = self.env(STUB_SCENARIO=scenario_path)
        result = subprocess.run(
            [sys.executable, "-I", "-c", TEMP_FILE_DRIVER, LAUNCH, str(allowed)] + (args if args is not None else self.arguments()), env=env, capture_output=True, timeout=60
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b"")
        self.assertEqual(result.stdout.count(b"\n"), 1, result.stdout)
        status, _, text = result.stdout.decode()[:-1].partition(" ")
        return status, text

    def option(self, call, flag):
        return call["argv"][call["argv"].index(flag) + 1]

    def prompt_with_handle(self):
        return f"Read {self.handoff} and follow it. You are the successor of Orca terminal {OLD_HANDLE}. Close that terminal only after your takeover is done."

    def prompt_without_handle(self):
        return f"Read {self.handoff} and follow it. The session you replace did not run in an Orca terminal. When your takeover is done, tell the user to close the old session."

    def manual_command(self, cwd=None, model="claude-sonnet-5-5[1m]", prompt=None):
        parts = ["claude", "--model", model, "--permission-mode", "auto", "--effort", "medium", prompt or self.prompt_without_handle()]
        return "cd " + shlex.quote(cwd or self.cwd) + " && " + " ".join(shlex.quote(part) for part in parts)

    def manual_text(self):
        return f"the handoff file is at {self.handoff}; start the successor with {self.manual_command()}"


class PlainSuccessTest(LaunchTestCase):
    def test_start_in_an_orca_terminal(self):
        status, text = self.launch()
        self.assertEqual((status, text), ("ok", f"context handoff done: successor {NEW_HANDLE}"))
        self.assertEqual(self.names(), ["status", "worktree list", "terminal show", "terminal create", "terminal wait", "terminal send"])
        self.assertEqual({call["prog"] for call in self.calls()}, {"orca"})
        self.assertTrue(all(call["argv"][-1] == "--json" for call in self.calls()))
        self.assertEqual(self.read("launch"), f"started\nok {text}\n")
        self.assertEqual(self.read("manual"), self.manual_text())

    def test_create_call(self):
        self.launch()
        create = self.call("terminal create")
        self.assertEqual(self.option(create, "--worktree"), "path:" + self.worktree)
        self.assertIn("--title=Fix the thing ↻1", create["argv"])
        command = self.option(create, "--command")
        self.assertEqual(
            command,
            "env CONTEXT_HANDOFF_SUCCESSOR=" + shlex.quote(self.handoff) + " claude --model 'claude-sonnet-5-5[1m]' --permission-mode auto --effort medium",
        )
        self.assertNotIn("Read ", command)  # the prompt is sent after the idle wait
        self.assertNotIn("CLAUDE_CODE_DISABLE_TERMINAL_TITLE", command)  # it breaks Orca's idle detection after the first turn (thirteenth amendment on #8)

    def test_the_manual_command_carries_no_marker_and_no_title_variable(self):
        self.launch()
        manual = self.read("manual")
        self.assertNotIn("CONTEXT_HANDOFF_SUCCESSOR", manual)
        self.assertNotIn("CLAUDE_CODE_DISABLE_TERMINAL_TITLE", manual)

    def test_files_exist_before_create(self):
        self.launch()
        files = self.call("terminal create")["files"]
        self.assertEqual(files[SESSION + ".launch"], "started\n")
        self.assertEqual(files[SESSION + ".manual"], self.manual_text())

    def test_wait_then_send_the_prompt(self):
        self.launch()
        wait, send = self.call("terminal wait"), self.call("terminal send")
        self.assertEqual(self.option(wait, "--terminal"), NEW_HANDLE)
        self.assertEqual(self.option(wait, "--for"), "tui-idle")
        self.assertEqual(self.option(wait, "--timeout-ms"), "59000")
        self.assertEqual(self.option(send, "--terminal"), NEW_HANDLE)
        self.assertEqual(self.option(send, "--text"), self.prompt_with_handle())
        self.assertIn("--enter", send["argv"])
        self.assertEqual(self.option(send, "--wait-submit"), "8")

    def test_empty_model_mode_and_effort_pass_no_flag(self):
        status, _ = self.launch(self.arguments(model="", permission_mode="", effort=""))
        self.assertEqual(status, "ok")
        self.assertEqual(self.option(self.call("terminal create"), "--command"),
            "env CONTEXT_HANDOFF_SUCCESSOR=" + shlex.quote(self.handoff) + " claude",
        )
        self.assertIn(shlex.quote(self.prompt_without_handle()), self.read("manual"))
        self.assertNotIn("--model", self.read("manual"))

    def test_paths_with_spaces_and_quotes(self):
        folder = os.path.join(self.tmp, "o'wn dir", "claude-context-handoff")
        os.makedirs(folder, mode=0o700)
        self.folder = folder
        self.handoff = os.path.join(folder, SESSION + ".handoff.md")
        with open(self.handoff, "w") as handle:
            handle.write("x")
        cwd = os.path.join(self.worktree, "it's here")
        os.makedirs(cwd)
        status, _ = self.launch(self.arguments(cwd=cwd), TMPDIR=os.path.join(self.tmp, "o'wn dir"))
        self.assertEqual(status, "ok")
        create = self.call("terminal create")
        self.assertEqual(self.option(create, "--worktree"), "path:" + self.worktree)
        self.assertEqual(shlex.split(self.option(create, "--command"))[1:3], ["CONTEXT_HANDOFF_SUCCESSOR=" + self.handoff, "claude"])
        self.assertEqual(self.read("manual"), self.manual_text().replace(shlex.quote(self.cwd), shlex.quote(cwd)))

    def test_non_ascii_text_and_slash_models(self):
        cwd = os.path.join(self.worktree, "caf\u00e9 \u21bb")
        os.makedirs(cwd)
        status, text = self.launch(self.arguments(cwd=cwd, model="us.anthropic/claude x:0".replace(" ", "-")))
        self.assertEqual(status, "ok")
        self.assertIn(shlex.quote(cwd), self.read("manual"))
        self.assertIn("--model us.anthropic/claude-x:0", self.option(self.call("terminal create"), "--command"))
        self.assertIn("--model us.anthropic/claude-x:0", self.read("manual"))
        os.remove(self.log_path)
        self.scenario["terminal create"] = failure("bad \u21bb title")
        status, text = self.launch(self.arguments(cwd=cwd))
        self.assertEqual(status, "failed")
        self.assertIn("bad \u21bb title", text)  # non-ASCII text survives the UTF-8 result line

    def test_cwd_inside_a_worktree_uses_the_worktree_path(self):
        self.launch()
        self.assertEqual(self.option(self.call("terminal create"), "--worktree"), "path:" + self.worktree)

    def test_runtime_folder_comes_from_the_argument_not_from_tmpdir(self):
        other = os.path.join(self.root, "other-tmp")
        os.mkdir(other)
        status, _ = self.launch(TMPDIR=other)
        self.assertEqual(status, "ok")
        self.assertIsNotNone(self.read("launch"))
        self.assertIsNotNone(self.read("manual"))
        self.assertEqual(os.listdir(other), [])

    def test_no_orchestration_command(self):
        self.launch()
        self.assertFalse(any("orchestration" in call["argv"] for call in self.calls()))


class CliResolutionTest(LaunchTestCase):
    def test_orca_cli_command_comes_first(self):
        alias = os.path.join(self.bin, "my cli")
        shutil.copy(os.path.join(self.bin, "orca-ide"), alias)
        status, _ = self.launch(ORCA_CLI_COMMAND=shlex.quote(alias) + " extra-word")
        self.assertEqual(status, "manual")  # "extra-word" is the first argument, so the stub answers "unexpected call" to status
        self.assertEqual({call["prog"] for call in self.calls()}, {"my cli"})
        self.assertEqual(self.calls()[0]["argv"][0], "extra-word")

    def test_orca_with_a_handle_and_orca_ide_without(self):
        self.launch()
        self.assertEqual({call["prog"] for call in self.calls()}, {"orca"})
        os.remove(self.log_path)
        self.launch(handle=None)
        self.assertEqual({call["prog"] for call in self.calls()}, {"orca-ide"})

    def test_invalid_handle_in_the_environment_counts_as_no_handle(self):
        for handle in ("-term", "term\nx"):
            with self.subTest(handle=handle):
                if os.path.exists(self.log_path):
                    os.remove(self.log_path)
                status, _ = self.launch(handle=handle)
                self.assertEqual(status, "ok")
                self.assertEqual({call["prog"] for call in self.calls()}, {"orca-ide"})
                self.assertNotIn("terminal show", self.names())
                self.assertEqual(self.option(self.call("terminal send"), "--text"), self.prompt_without_handle())

    def test_invalid_orca_cli_command_fails_without_the_manual_case(self):
        for value in ("'unbalanced", "   "):
            with self.subTest(value=value):
                status, text = self.launch(ORCA_CLI_COMMAND=value)
                self.assertEqual(status, "failed")
                self.assertEqual(text, f"successor failed: ORCA_CLI_COMMAND is invalid; {self.manual_text()}")
                self.assertEqual(self.calls(), [])

    def test_empty_orca_cli_command_falls_back(self):
        status, _ = self.launch(handle=None, ORCA_CLI_COMMAND="")
        self.assertEqual(status, "ok")
        self.assertEqual({call["prog"] for call in self.calls()}, {"orca-ide"})


class TitleTest(LaunchTestCase):
    def title_of(self, shown):
        self.scenario["terminal show"] = reply({"terminal": {"title": shown}}) if not isinstance(shown, dict) else reply({"terminal": shown})
        if os.path.exists(self.log_path):
            os.remove(self.log_path)
        self.launch()
        argument = [part for part in self.call("terminal create")["argv"] if part.startswith("--title=")][0]
        return argument[len("--title="):]

    def test_numbering(self):
        self.assertEqual(self.title_of("Fix the thing"), "Fix the thing ↻1")
        self.assertEqual(self.title_of("◐ Fix the thing"), "Fix the thing ↻1")
        self.assertEqual(self.title_of("✳ Fix ↻1"), "Fix ↻2")
        self.assertEqual(self.title_of("Fix ↻9  "), "Fix ↻10")
        self.assertEqual(self.title_of("Fix ↻1234567"), "Fix ↻1234567 ↻1")  # more than 6 digits is not a number

    def test_titles_that_keep_their_start(self):
        for title in ("[x] build", "(draft)", "- build", "# fix", "+ x"):
            with self.subTest(title=title):
                self.assertEqual(self.title_of(title), title + " ↻1")

    def test_dash_title_is_one_argument(self):
        self.assertEqual(self.title_of("-dash"), "-dash ↻1")

    def test_fallback_to_claude(self):
        self.assertEqual(self.title_of({"title": ""}), "claude ↻1")
        self.assertEqual(self.title_of({"title": "◐ "}), "claude ↻1")
        self.assertEqual(self.title_of({"title": 5}), "claude ↻1")
        self.assertEqual(self.title_of({}), "claude ↻1")
        self.scenario["terminal show"] = failure()
        os.remove(self.log_path)
        self.assertEqual(self.launch()[0], "ok")
        self.assertIn("--title=claude ↻1", self.call("terminal create")["argv"])

    def test_title_is_one_line_and_cut(self):
        self.assertEqual(self.title_of("a b\x1bc"), "a b c ↻1")
        self.assertEqual(self.title_of("x" * 500), "x" * 200 + " ↻1")


class OutsideOrcaTerminalTest(LaunchTestCase):
    def test_successor_starts_with_the_base_claude_and_the_without_handle_prompt(self):
        status, text = self.launch(handle=None)
        self.assertEqual((status, text), ("ok", f"context handoff done: successor {NEW_HANDLE}"))
        self.assertEqual(self.names(), ["status", "worktree list", "terminal create", "terminal wait", "terminal send"])
        self.assertIn("--title=claude ↻1", self.call("terminal create")["argv"])
        self.assertEqual(self.option(self.call("terminal send"), "--text"), self.prompt_without_handle())
        self.assertFalse(any("orchestration" in call["argv"] for call in self.calls()))


class SharedRolePathTest(LaunchTestCase):
    """The plain and coordinator roles share one launcher path: every case runs for both roles."""

    ROLES = ("plain", "coordinator")

    def run_roles(self, handle=OLD_HANDLE, cwd=None):
        """Launch once per role, each with a fresh call log. Yields (role, status, text)."""
        for role in self.ROLES:
            with self.subTest(role=role):
                if os.path.exists(self.log_path):
                    os.remove(self.log_path)
                overrides = {"role": role, "cwd": cwd} if cwd else {"role": role}
                status, text = self.launch(self.arguments(**overrides), handle=handle)
                self.assertFalse(any("orchestration" in call["argv"] for call in self.calls()))
                yield role, status, text

    def test_start_in_an_orca_terminal(self):
        for _role, status, text in self.run_roles():
            self.assertEqual((status, text), ("ok", f"context handoff done: successor {NEW_HANDLE}"))
            self.assertEqual(self.names(), ["status", "worktree list", "terminal show", "terminal create", "terminal wait", "terminal send"])
            self.assertEqual(self.option(self.call("terminal create"), "--command"),
                "env CONTEXT_HANDOFF_SUCCESSOR=" + shlex.quote(self.handoff) + " claude --model 'claude-sonnet-5-5[1m]' --permission-mode auto --effort medium")
            self.assertEqual(self.option(self.call("terminal send"), "--text"), self.prompt_with_handle())
            self.assertEqual(self.read("manual"), self.manual_text())

    def test_start_outside_an_orca_terminal(self):
        for _role, status, text in self.run_roles(handle=None):
            self.assertEqual((status, text), ("ok", f"context handoff done: successor {NEW_HANDLE}"))
            self.assertEqual(self.option(self.call("terminal send"), "--text"), self.prompt_without_handle())

    def test_manual_case_for_stopped_orca(self):
        self.scenario["status"] = reply({"app": {"running": False}, "runtime": {"reachable": True}})
        for _role, status, text in self.run_roles():
            self.assertEqual((status, text), ("manual", "no Orca: " + self.manual_text()))
            self.assertEqual(self.read("manual"), self.manual_text())
            self.assertNotIn("terminal create", self.names())

    def test_manual_case_for_a_cwd_that_orca_does_not_manage(self):
        elsewhere = os.path.join(self.root, "elsewhere")
        os.mkdir(elsewhere)
        for _role, status, _text in self.run_roles(cwd=elsewhere):
            self.assertEqual(status, "manual")
            self.assertNotIn("terminal create", self.names())


class ManualCaseTest(LaunchTestCase):
    def assert_manual(self):
        status, text = self.launch()
        self.assertEqual((status, text), ("manual", "no Orca: " + self.manual_text()))
        self.assertEqual(self.read("launch"), f"started\n{status} {text}\n")
        self.assertEqual(self.read("manual"), self.manual_text())
        self.assertNotIn("terminal create", self.names())

    def test_orca_not_running(self):
        for result in ({"app": {"running": False}, "runtime": {"reachable": True}}, {"app": {"running": True}, "runtime": {"reachable": False}}):
            with self.subTest(result=result):
                self.scenario["status"] = reply(result)
                self.assert_manual()
                os.remove(self.log_path)

    def test_status_fails(self):
        self.scenario["status"] = failure()
        self.assert_manual()

    def test_cli_missing(self):
        status, text = self.launch(handle=None, PATH="/usr/bin:/bin")
        self.assertEqual((status, text), ("manual", "no Orca: " + self.manual_text()))

    def test_list_fails_or_is_not_json(self):
        for entry in (failure(), {"out": "not json"}, {"out": "[1]"}):
            with self.subTest(entry=entry):
                self.scenario["worktree list"] = entry
                self.assert_manual()
                os.remove(self.log_path)

    def test_cwd_not_managed(self):
        elsewhere = os.path.join(self.root, "elsewhere")
        os.mkdir(elsewhere)
        sibling = self.worktree + "-sibling"  # shares the string prefix with the worktree path
        os.mkdir(sibling)
        for cwd in (elsewhere, sibling):
            with self.subTest(cwd=cwd):
                status, _ = self.launch(self.arguments(cwd=cwd))
                self.assertEqual(status, "manual")
                os.remove(self.log_path)

    def test_rows_that_do_not_count(self):
        base = {"path": self.worktree, "isArchived": False, "isBare": False, "hostId": "local"}
        for change in ({"isArchived": True}, {"isBare": True}, {"hostId": "remote"}, {"path": "relative"}):
            with self.subTest(change=change):
                self.scenario["worktree list"] = reply({"worktrees": [{**base, **change}], "truncated": False})
                self.assertEqual(self.launch()[0], "manual")
                os.remove(self.log_path)

    def test_longest_match_wins(self):
        inner = {"path": self.cwd, "hostId": "local"}
        self.scenario["worktree list"] = reply({"worktrees": [{"path": self.worktree, "hostId": "local"}, inner], "truncated": False})
        self.launch()
        self.assertEqual(self.option(self.call("terminal create"), "--worktree"), "path:" + self.cwd)

    def test_truncated_list_accepts_only_an_exact_match(self):
        for truncated in (True, None, "yes"):
            with self.subTest(truncated=truncated):
                result = {"worktrees": [{"path": self.worktree, "hostId": "local"}]}
                if truncated is not None:
                    result["truncated"] = truncated
                self.scenario["worktree list"] = reply(result)
                self.assertEqual(self.launch()[0], "manual")  # the cwd is below the worktree, not equal to it
                os.remove(self.log_path)
        self.scenario["worktree list"] = reply({"worktrees": [{"path": self.cwd, "hostId": "local"}], "truncated": True})
        self.assertEqual(self.launch()[0], "ok")

    def test_symlinked_cwd_matches_by_real_path(self):
        link = os.path.join(self.root, "link")
        os.symlink(self.cwd, link)
        self.assertEqual(self.launch(self.arguments(cwd=link))[0], "ok")


class FailureTest(LaunchTestCase):
    def assert_closed(self):
        self.assertEqual(self.names()[-1], "terminal close")
        self.assertEqual(self.option(self.calls()[-1], "--terminal"), NEW_HANDLE)

    def test_idle_wait_failures_close_the_terminal(self):
        for entry in (failure("never idle", "timeout"), reply({"wait": {"satisfied": False}}), {"out": "garbage"}, reply("wrong shape")):
            with self.subTest(entry=entry):
                self.scenario["terminal wait"] = entry
                status, text = self.launch()
                self.assertEqual(status, "failed")
                self.assertTrue(text.startswith("successor failed: "), text)
                self.assertTrue(text.endswith("; " + self.manual_text()), text)
                self.assert_closed()
                self.assertNotIn("terminal send", self.names())
                self.assertEqual(self.read("launch"), f"started\n{status} {text}\n")
                os.remove(self.log_path)

    def test_send_failures_close_the_terminal(self):
        only_accepted = reply({"send": {"prompt": {"stages": ["input_accepted"]}}})
        for entry in (failure("no submit"), only_accepted, reply({"send": {"prompt": {"stages": "turn_started"}}}), reply({"send": "x"})):
            with self.subTest(entry=entry):
                self.scenario["terminal send"] = entry
                status, text = self.launch()
                self.assertEqual(status, "failed")
                self.assert_closed()
                os.remove(self.log_path)

    def test_failed_close_adds_a_note(self):
        self.scenario["terminal wait"] = failure("never idle")
        self.scenario["terminal close"] = failure("cannot close")
        status, text = self.launch()
        self.assertEqual(status, "failed")
        self.assertTrue(text.endswith(f"; {self.manual_text()}; terminal {NEW_HANDLE} may still run; close it before you start the manual command"), text)
        self.assertNotIn("check Orca for a stray terminal", text)

    def test_failed_create_adds_the_stray_note_and_closes_nothing(self):
        stray = "a terminal may have been created; check Orca for a stray terminal and close it"
        for entry in (
            failure("no", "timeout"),
            failure("no", "other"),
            {"out": "garbage"},
            reply({"terminal": {}}),
            reply({"terminal": {"handle": "-bad"}}),
            reply({"terminal": {"handle": "a\nb"}}),
        ):
            with self.subTest(entry=entry):
                self.scenario["terminal create"] = entry
                status, text = self.launch()
                self.assertEqual(status, "failed")
                self.assertTrue(text.endswith(f"; {self.manual_text()}; {stray}"), text)
                self.assertNotIn("terminal close", self.names())
                os.remove(self.log_path)

    def test_error_text_is_one_line_of_at_most_300_characters(self):
        self.scenario["terminal create"] = failure("first\nsecond\x1b[31m " + "y" * 600)
        status, text = self.launch()
        error = text[len("successor failed: "):].split("; the handoff file is at")[0]
        self.assertEqual(status, "failed")
        self.assertLessEqual(len(error), 300)
        self.assertTrue(error.startswith("first second [31m yyy"), error)

    def test_wrong_shaped_json_is_a_failure_not_a_crash(self):
        for out in ('{"ok": true, "result": null}', '{"ok": true, "result": [1]}', "[]", "null", '{"ok": "true"}', ""):
            with self.subTest(out=out):
                self.scenario["terminal create"] = {"out": out}
                self.assertEqual(self.launch()[0], "failed")
                os.remove(self.log_path)
        self.scenario["terminal create"] = reply({"terminal": NEW_HANDLE})
        self.assertEqual(self.launch()[0], "failed")

    def test_wrong_shaped_json_after_create_closes_the_terminal(self):
        self.scenario["terminal send"] = {"out": '{"ok": true, "result": []}'}
        self.assertEqual(self.launch()[0], "failed")
        self.assert_closed()

    def test_invalid_utf8_output_is_a_failure(self):
        self.scenario["status"] = {"bytes": "7b226f6b223a20747275652c202278223a2022ff227d"}  # {"ok": true, "x": "\xff"}: valid JSON but invalid UTF-8
        self.assertEqual(self.launch()[0], "manual")

    def test_launch_file_that_cannot_be_replaced_at_the_end_still_prints_ok(self):
        self.scenario["terminal send"]["dir_over"] = os.path.join(self.folder, SESSION + ".launch")
        status, text = self.launch()
        self.assertEqual((status, text), ("ok", f"context handoff done: successor {NEW_HANDLE}"))
        self.assertNotIn("terminal close", self.names())

    def test_manual_file_and_launch_file_write_failures(self):
        for name in ("launch", "manual"):
            with self.subTest(name=name):
                path = os.path.join(self.folder, SESSION + "." + name)
                os.mkdir(path)
                status, text = self.launch()
                self.assertEqual(status, "failed")
                self.assertTrue(text.startswith(f"successor failed: cannot write the {name} file"), text)
                self.assertEqual(self.calls(), [])
                os.rmdir(path)

    def test_a_missing_shared_module_gives_one_failed_line(self):
        copy = os.path.join(self.root, "copy")
        os.mkdir(copy)
        shutil.copy(LAUNCH, copy)
        result = subprocess.run([sys.executable, "-I", os.path.join(copy, "launch.py")] + self.arguments(), env=self.env(), capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, b"")
        self.assertTrue(result.stdout.startswith(b"failed successor failed: "), result.stdout)
        self.assertEqual(result.stdout.count(b"\n"), 1)


class EarlyFailureTest(LaunchTestCase):
    def test_roles_that_are_not_supported(self):
        for role in ("bogus", "r" * 400):
            with self.subTest(role=role[:12]):
                status, text = self.launch(self.arguments(role=role))
                self.assertEqual((status, text), ("failed", f"successor failed: role {role[:300]} is not supported"))
                self.assertEqual(self.read("launch"), f"started\n{status} {text}\n")
                self.assertIsNone(self.read("manual"))
                self.assertEqual(self.calls(), [])
                os.remove(os.path.join(self.folder, SESSION + ".launch"))

    def test_invalid_arguments_write_nothing_and_call_nothing(self):
        other = os.path.join(self.tmp, "not-the-folder")
        os.mkdir(other, 0o700)
        cases = {
            "count": self.arguments()[:-1],
            "session": self.arguments(session_id="a/b"),
            "relative runtime": self.arguments(runtime_dir="claude-context-handoff"),
            "relative cwd": self.arguments(cwd="work"),
            "newline": self.arguments(model="a\nb"),
            "role newline": self.arguments(role="plain\nx"),
            "u2028": self.arguments(effort="a b"),
            "c1": self.arguments(permission_mode="a\x85b"),
            "space in model": self.arguments(model="a b"),
            "semicolon in model": self.arguments(model="a;b"),
            "leading dash": self.arguments(model="--dangerous"),
            "folder name": self.arguments(runtime_dir=other, handoff=os.path.join(other, SESSION + ".handoff.md")),
            "not normalized": self.arguments(runtime_dir=self.folder + "/../claude-context-handoff", handoff=self.folder + "/../claude-context-handoff/" + SESSION + ".handoff.md"),
            "handoff name": self.arguments(handoff=os.path.join(self.folder, "other.handoff.md")),
        }
        for name, args in cases.items():
            with self.subTest(name=name):
                status, text = self.launch(args)
                self.assertEqual(status, "failed")
                self.assertTrue(text.startswith("successor failed: invalid arguments: "), text)
                self.assert_nothing_called_or_written()
        self.assertEqual(os.listdir(other), [])

    def test_models_with_brackets_slashes_and_at_signs_are_valid(self):
        for model in ("claude-sonnet-5-5[1m]", "us.anthropic.claude/x:0", "claude-sonnet-4@20250514"):
            with self.subTest(model=model):
                self.assertEqual(self.launch(self.arguments(model=model))[0], "ok")
                os.remove(self.log_path)

    def test_missing_empty_or_symlinked_handoff_file(self):
        os.remove(self.handoff)
        self.assertEqual(self.launch()[1], "successor failed: the handoff file is missing or empty")
        self.assertEqual(self.calls(), [])
        self.assertIsNone(self.read("manual"))
        self.assertEqual(self.read("launch"), "started\nfailed successor failed: the handoff file is missing or empty\n")
        open(self.handoff, "w").close()
        self.assertEqual(self.launch()[1], "successor failed: the handoff file is missing or empty")
        os.remove(self.handoff)
        real = os.path.join(self.root, "real.md")
        with open(real, "w") as handle:
            handle.write("x")
        os.symlink(real, self.handoff)
        self.assertEqual(self.launch()[1], "successor failed: the handoff file is missing or empty")
        self.assertEqual(self.calls(), [])

    def test_unsafe_runtime_folder(self):
        for change in (lambda: os.chmod(self.folder, 0o755), lambda: self.swap_for_symlink()):
            with self.subTest(change=change):
                change()
                status, text = self.launch()
                self.assertEqual((status, text), ("failed", "successor failed: runtime folder is not safe"))
                self.assertEqual(self.calls(), [])
                self.assertEqual([name for name in os.listdir(self.folder) if name.endswith((".launch", ".manual"))] if os.path.isdir(self.folder) else [], [])
                self.setUp()

    def swap_for_symlink(self):
        real = os.path.join(self.tmp, "real-folder")
        os.rename(self.folder, real)
        os.symlink(real, self.folder)


# Runs launch.py unchanged, after making the Nth and later temporary files fail (a full disk or no free file descriptor).
TEMP_FILE_DRIVER = """
import runpy, sys, tempfile
launch, allowed = sys.argv[1], int(sys.argv[2])
real, count = tempfile.TemporaryFile, [0]
def limited(*args, **kwargs):
    count[0] += 1
    if count[0] > allowed:
        raise OSError(28, "No space left on device")
    return real(*args, **kwargs)
tempfile.TemporaryFile = limited
sys.argv = [launch] + sys.argv[3:]
runpy.run_path(launch, run_name="__main__")
"""


# Runs a script as __main__ with a folder holding a shadow `runtime_dir` module first on the search path. The driver never imports the module itself.
SHADOW_DRIVER = """
import runpy, sys
shadow, script = sys.argv[1], sys.argv[2]
sys.path.insert(0, shadow)
sys.argv = [script] + sys.argv[3:]
runpy.run_path(script, run_name="__main__")
"""


class ModuleSearchPathTest(LaunchTestCase):
    def test_the_real_runtime_dir_module_wins_over_a_shadow_module_earlier_on_the_search_path(self):
        shadow = os.path.join(self.root, "shadow")
        os.mkdir(shadow)
        with open(os.path.join(shadow, "runtime_dir.py"), "w") as handle:
            handle.write("FOLDER_NAME = 'shadow'\n")
        scenario_path = os.path.join(self.root, "scenario.json")
        with open(scenario_path, "w") as handle:
            json.dump(self.scenario, handle)
        result = subprocess.run(
            [sys.executable, "-I", "-c", SHADOW_DRIVER, shadow, LAUNCH] + self.arguments(), env=self.env(STUB_SCENARIO=scenario_path), capture_output=True, timeout=60
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b"")
        self.assertEqual(result.stdout.decode().partition(" ")[0], "ok", result.stdout)


class TemporaryFileFailureTest(LaunchTestCase):
    def test_failure_before_any_call_gives_failed_not_manual(self):
        status, text = self.launch_with_failing_temp_files(0)
        self.assertEqual(status, "failed")
        self.assertTrue(text.startswith("successor failed: [Errno 28] No space left on device; "), text)
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.read("launch"), f"started\n{status} {text}\n")

    def test_failure_while_closing_gives_the_may_still_run_note(self):
        self.scenario["terminal wait"] = failure("never idle")
        status, text = self.launch_with_failing_temp_files(5)  # status, list, show, create and wait work; the close does not
        self.assertEqual(status, "failed")
        self.assertTrue(text.endswith(f"; terminal {NEW_HANDLE} may still run; close it before you start the manual command"), text)
        self.assertEqual(self.names()[-1], "terminal wait")


class TimingTest(LaunchTestCase):
    def test_a_grandchild_that_holds_the_output_does_not_hang_the_launcher(self):
        self.scenario["status"]["grandchild"] = True
        begin = time.monotonic()
        self.assertEqual(self.launch()[0], "ok")
        self.assertLess(time.monotonic() - begin, 20)

    def test_a_hung_call_is_killed_at_its_limit(self):
        self.scenario["status"]["sleep"] = 60
        begin = time.monotonic()
        self.assertEqual(self.launch()[0], "manual")
        self.assertGreaterEqual(time.monotonic() - begin, 9)
        self.assertLess(time.monotonic() - begin, 20)

    def test_a_hung_create_gives_failed_with_the_stray_note(self):
        self.scenario["terminal create"]["sleep"] = 60
        begin = time.monotonic()
        status, text = self.launch()
        self.assertEqual(status, "failed")
        self.assertTrue(text.endswith("; a terminal may have been created; check Orca for a stray terminal and close it"), text)
        self.assertNotIn("terminal close", self.names())
        self.assertLess(time.monotonic() - begin, 20)

    def test_a_hung_send_closes_the_terminal(self):
        self.scenario["terminal send"]["sleep"] = 60
        begin = time.monotonic()
        status, _ = self.launch()
        self.assertEqual(status, "failed")
        self.assertEqual(self.names()[-1], "terminal close")
        self.assertLess(time.monotonic() - begin, 30)

    def test_a_hung_close_gives_the_may_still_run_note(self):
        self.scenario["terminal wait"] = failure("never idle")
        self.scenario["terminal close"]["sleep"] = 60
        begin = time.monotonic()
        status, text = self.launch()
        self.assertEqual(status, "failed")
        self.assertTrue(text.endswith(f"terminal {NEW_HANDLE} may still run; close it before you start the manual command"), text)
        self.assertLess(time.monotonic() - begin, 30)

    def test_every_call_slow_stays_under_100_seconds(self):
        # The limits are constants (no test-only switch), so this case takes real time: up to about 95 s of wall time and
        # almost no CPU. Status, list, show and create take about 10 s each; the idle wait is clamped to the time left
        # before the 85 s work deadline (about 45 s); the close that follows takes at most 10 s.
        for name in ("status", "worktree list", "terminal show", "terminal create"):
            self.scenario[name]["sleep"] = 9.5
        self.scenario["terminal wait"]["sleep"] = 120
        begin = time.monotonic()
        status, text = self.launch(timeout=110)
        elapsed = time.monotonic() - begin
        self.assertEqual(status, "failed")
        self.assertLess(elapsed, 100)
        self.assertGreater(elapsed, 80)
        self.assertEqual(self.names()[-1], "terminal close")
        self.assertNotIn("terminal send", self.names())
        self.assertTrue(text.endswith(self.manual_text()), text)


WORKER_NAMES = ("worker_handle", "task_id", "dispatch_id", "coordinator_handle")


class NoTestSwitchTest(unittest.TestCase):
    def test_the_launcher_reads_only_the_documented_environment(self):
        with open(LAUNCH) as handle:
            source = handle.read()
        self.assertEqual(source.count("os.environ"), 2)  # ORCA_TERMINAL_HANDLE and ORCA_CLI_COMMAND; TMPDIR is read in runtime_dir
        self.assertIn('"ORCA_TERMINAL_HANDLE"', source)
        self.assertIn('"ORCA_CLI_COMMAND"', source)


class WorkerTestCase(LaunchTestCase):
    def worker_arguments(self, **override):
        values = dict(zip(WORKER_NAMES, (OLD_HANDLE, TASK, DISPATCH, COORDINATOR)))
        values.update({name: value for name, value in override.items() if name in WORKER_NAMES})
        base = {name: value for name, value in override.items() if name not in WORKER_NAMES}
        return self.arguments(role="worker", **base) + list(values.values())

    def worker_launch(self, **extra_env):
        return self.launch(self.worker_arguments(), **extra_env)

    def commands(self, successor, worktree=None, cli="orca"):
        worktree = worktree or self.worktree
        return (
            f"1) {cli} orchestration worker-stop --dispatch {DISPATCH}; 2) if step 1 returns stop_unknown (the worker ran on a reused terminal): "
            f"{cli} orchestration worker-abandon --dispatch {DISPATCH}, then {cli} terminal close --terminal {OLD_HANDLE}; "
            f"3) {cli} orchestration worker-start --task {TASK} --retry-of {DISPATCH} --worktree {shlex.quote('path:' + worktree)} --terminal {successor}"
        )

    def worker_prompt(self):
        return f"You are a worker successor. Wait. An Orca dispatch arrives soon. When it does, read {self.handoff} before you act on it."

    def worker_manual_text(self, worktree=None):
        return (
            f"the handoff file is at {self.handoff}; start the successor with {self.manual_command(prompt=self.worker_prompt())} in an Orca terminal of the worktree"
            f" (its handle is the value of $ORCA_TERMINAL_HANDLE there); then tell coordinator {COORDINATOR}: {self.commands('<new handle>', worktree)}"
        )

    def escalation_failed_text(self):
        return (
            f"successor {NEW_HANDLE} waits; tell the coordinator: {self.commands(NEW_HANDLE)};"
            " the coordinator may already have the escalation, so check its inbox before you run them"
        )

    def early_failed_text(self, error):
        return f"successor failed: {error}; the handoff file is at {self.handoff}"

    def assert_early_failure(self, status, text, error=None):
        self.assertEqual(status, "failed")
        self.assertTrue(text.startswith("successor failed: "), text)
        self.assertTrue(text.endswith(f"; the handoff file is at {self.handoff}"), text)
        if error:
            self.assertEqual(text, self.early_failed_text(error))
        self.assertNotIn("worker-stop", text)
        self.assertIsNone(self.read("manual"))
        self.assertNotIn("terminal create", self.names())
        self.assertNotIn("orchestration send", self.names())


class WorkerSuccessTest(WorkerTestCase):
    def test_call_order_start_command_and_prompt(self):
        status, text = self.worker_launch()
        self.assertEqual((status, text), ("ok", f"context handoff done: successor {NEW_HANDLE}"))
        self.assertEqual(
            self.names(),
            ["status", "worktree list", "orchestration worker-show", "terminal show", "terminal create", "terminal wait", "terminal send", "orchestration send"],
        )
        self.assertEqual(self.option(self.call("terminal create"), "--command"),
            "env CONTEXT_HANDOFF_SUCCESSOR=" + shlex.quote(self.handoff) + " claude --model 'claude-sonnet-5-5[1m]' --permission-mode auto --effort medium")
        self.assertEqual(self.option(self.call("terminal send"), "--text"), self.worker_prompt())
        self.assertEqual(self.option(self.call("orchestration worker-show"), "--dispatch"), DISPATCH)
        self.assertEqual(self.read("launch"), f"started\n{status} {text}\n")

    def test_the_worker_prompt_does_not_depend_on_the_title_lookup(self):
        self.scenario["terminal show"] = failure("no title")
        self.assertEqual(self.worker_launch()[0], "ok")
        self.assertEqual(self.option(self.call("terminal send"), "--text"), self.worker_prompt())

    def test_escalation_call(self):
        self.worker_launch()
        call = self.call("orchestration send")
        self.assertEqual(self.option(call, "--from"), OLD_HANDLE)
        self.assertEqual(self.option(call, "--type"), "escalation")
        self.assertEqual(self.option(call, "--task-id"), TASK)
        self.assertEqual(self.option(call, "--dispatch-id"), DISPATCH)
        self.assertEqual(self.option(call, "--subject"), f"Worker handover: successor {NEW_HANDLE}")
        self.assertNotIn("--to", call["argv"])
        self.assertEqual(
            self.option(call, "--body"),
            f"Worker {OLD_HANDLE} (Task {TASK}, Dispatch {DISPATCH}) reached 80% of its context. Its successor {NEW_HANDLE} waits in terminal {NEW_HANDLE}"
            f" for a dispatch; the handoff file is at {self.handoff}. For coordinator {COORDINATOR}, run: {self.commands(NEW_HANDLE)}",
        )

    def test_the_commands_use_the_orca_worktree_not_the_cwd_below_it(self):
        self.worker_launch()
        body = self.option(self.call("orchestration send"), "--body")
        self.assertIn(shlex.quote("path:" + self.worktree), body)
        self.assertNotIn(self.cwd, body)

    def test_the_manual_file_holds_the_worker_text_with_the_worktree_before_create(self):
        self.worker_launch()
        expected = self.worker_manual_text(self.worktree).replace(shlex.quote("path:" + self.cwd), shlex.quote("path:" + self.worktree))
        self.assertEqual(self.call("terminal create")["files"][SESSION + ".manual"], expected)
        self.assertEqual(self.read("manual"), expected)

    def test_orca_cli_command_names_the_cli_in_the_commands(self):
        alias = os.path.join(self.bin, "my cli")
        shutil.copy(os.path.join(self.bin, "orca-ide"), alias)
        self.worker_launch(ORCA_CLI_COMMAND=shlex.quote(alias))
        self.assertTrue(self.option(self.call("orchestration send"), "--body").endswith(self.commands(NEW_HANDLE, cli=shlex.quote(alias))))

    def test_no_other_orchestration_command(self):
        self.worker_launch()
        self.assertEqual({name for name in self.names() if name.startswith("orchestration")}, {"orchestration worker-show", "orchestration send"})


class WorkerEscalationFailureTest(WorkerTestCase):
    def assert_waiting_successor(self, status, text):
        self.assertEqual((status, text), ("escalation-failed", self.escalation_failed_text()))
        self.assertNotIn("terminal close", self.names())
        self.assertEqual(self.read("launch"), f"started\n{status} {text}\n")

    def test_a_failed_escalation(self):
        for entry in (failure("no mailbox"), {"out": "garbage"}, {"out": []}):
            with self.subTest(entry=entry):
                self.scenario["orchestration send"] = entry
                self.assert_waiting_successor(*self.worker_launch())
                os.remove(self.log_path)

    def test_a_hung_escalation_is_killed_at_its_limit(self):
        self.scenario["orchestration send"]["sleep"] = 60
        begin = time.monotonic()
        self.assert_waiting_successor(*self.worker_launch())
        self.assertLess(time.monotonic() - begin, 30)

    def test_an_unexpected_exception_after_the_prompt(self):
        # 7 temporary files, one per Orca call before the escalation: status, worktree list, worker-show, terminal show, create, wait and send.
        # A new call earlier in the worker flow changes this number; the assertion on the last logged call below then fails.
        status, text = self.launch_with_failing_temp_files(7, self.worker_arguments())
        self.assertEqual((status, text), ("escalation-failed", self.escalation_failed_text()))
        self.assertEqual(self.names()[-1], "terminal send")  # the 8th temporary file failed before the escalation call ran
        self.assertNotIn("terminal close", self.names())


class WorkerPreCheckTest(WorkerTestCase):
    def test_worker_show_failures_create_nothing(self):
        wrong = lambda **change: reply({"dispatch": {"id": DISPATCH, "taskId": TASK, "assigneeHandle": OLD_HANDLE, **change}})
        cases = {
            "call failed": failure("no such thing"),
            "not found": failure("Worker Dispatch ctx_abc123 was not found.", "dispatch_not_found"),
            "other dispatch": wrong(id="ctx_other"),
            "other task": wrong(taskId="task_other"),
            "other assignee": wrong(assigneeHandle="term_other"),
            "missing assignee": reply({"dispatch": {"id": DISPATCH, "taskId": TASK}}),
            "wrong shape": reply("x"),
            "garbage": {"out": "garbage"},
        }
        for name, entry in cases.items():
            with self.subTest(name=name):
                self.scenario["orchestration worker-show"] = entry
                status, text = self.worker_launch()
                self.assert_early_failure(status, text)
                self.assertEqual(self.names(), ["status", "worktree list", "orchestration worker-show"])
                self.assertEqual(self.read("launch"), f"started\n{status} {text}\n")
                os.remove(self.log_path)

    def test_the_mismatch_text(self):
        self.scenario["orchestration worker-show"] = reply({"dispatch": {"id": "ctx_other", "taskId": TASK, "assigneeHandle": OLD_HANDLE}})
        status, text = self.worker_launch()
        self.assertEqual(text, self.early_failed_text("the Dispatch does not match the worker handle and Task"))

    def test_the_terminal_handle_must_be_this_terminal(self):
        for handle in (None, "term_other", "-bad", "bad\nhandle"):
            with self.subTest(handle=handle):
                status, text = self.launch(self.worker_arguments(), handle=handle)
                self.assert_early_failure(status, text, "worker handle is not this terminal")
                self.assertEqual(self.calls(), [])

    def test_an_invalid_orca_cli_command_has_no_manual_part(self):
        status, text = self.worker_launch(ORCA_CLI_COMMAND="'unbalanced")
        self.assert_early_failure(status, text, "ORCA_CLI_COMMAND is invalid")
        self.assertEqual(self.calls(), [])

    def test_a_worktree_path_with_a_line_break_character(self):
        for name in ("wt\nx", "wt x"):
            with self.subTest(name=name):
                self.setUp()
                worktree = os.path.join(self.root, name)  # Orca lists a symlink with the odd name; the cwd is clean, below its target
                os.symlink(self.worktree, worktree)
                self.scenario["worktree list"] = reply({"worktrees": [{"path": worktree, "isArchived": False, "isBare": False, "hostId": "local"}], "truncated": False})
                status, text = self.launch(self.worker_arguments())
                self.assert_early_failure(status, text, "worktree path has a control character")

    def test_a_missing_handoff_file(self):
        os.remove(self.handoff)
        self.assertEqual(self.worker_launch()[1], "successor failed: the handoff file is missing or empty")
        self.assertEqual(self.calls(), [])


class WorkerManualCaseTest(WorkerTestCase):
    def test_orca_not_running(self):
        self.scenario["status"] = reply({"app": {"running": False}, "runtime": {"reachable": True}})
        status, text = self.worker_launch()
        self.assertEqual((status, text), ("manual", "no Orca: " + self.worker_manual_text(self.cwd)))
        self.assertEqual(self.read("manual"), self.worker_manual_text(self.cwd))
        self.assertEqual(self.names(), ["status"])
        self.assertIn("--terminal <new handle>", text)  # the placeholder is inserted unquoted
        self.assertIn("$ORCA_TERMINAL_HANDLE", text)

    def test_a_cwd_that_orca_does_not_manage(self):
        elsewhere = os.path.join(self.root, "elsewhere")
        os.mkdir(elsewhere)
        status, text = self.launch(self.worker_arguments(cwd=elsewhere))
        self.assertEqual(status, "manual")
        self.assertNotIn("orchestration worker-show", self.names())
        self.assertNotIn("terminal create", self.names())
        self.assertIn(shlex.quote("path:" + elsewhere), text)


class WorkerArgumentsTest(WorkerTestCase):
    def test_wrong_counts(self):
        full = self.worker_arguments()
        cases = {
            "worker with 8": self.arguments(role="worker"),
            "worker with 9": full[:9],
            "worker with 11": full[:11],
            "worker with 13": full + ["x"],
            "plain with 12": self.arguments(role="plain") + ["a", "b", "c", "d"],
            "coordinator with 12": self.arguments(role="coordinator") + ["a", "b", "c", "d"],
            "unknown role with 12": self.arguments(role="bogus") + ["a", "b", "c", "d"],
        }
        for name, args in cases.items():
            with self.subTest(name=name):
                status, text = self.launch(args)
                self.assertEqual(status, "failed")
                self.assertTrue(text.startswith("successor failed: invalid arguments: expected "), text)
                self.assert_nothing_called_or_written()

    def test_bad_values(self):
        for name in WORKER_NAMES:
            for bad in ("-lead", "a b", "a;b", "a\nb", "a\u2028b", "a\x85b", "", "x/y"):
                with self.subTest(name=name, bad=bad):
                    status, text = self.launch(self.worker_arguments(**{name: bad}))
                    self.assertEqual(status, "failed")
                    self.assertTrue(text.startswith("successor failed: invalid arguments: "), text)
                    if bad.strip():
                        self.assertNotIn(bad, text)
                    self.assert_nothing_called_or_written()


class WorkerTimingTest(WorkerTestCase):
    def test_a_work_deadline_after_the_prompt_gives_escalation_failed(self):
        # The limits are constants (no test-only switch), so this case takes real time: about 83 s of wall time and almost no CPU.
        # Five calls take 5 s each, the idle wait 55 s and the prompt send 3 s; under 3 s are left, so no escalation call is made.
        for name in ("status", "worktree list", "orchestration worker-show", "terminal show", "terminal create"):
            self.scenario[name]["sleep"] = 5
        self.scenario["terminal wait"]["sleep"] = 55
        self.scenario["terminal send"]["sleep"] = 3
        begin = time.monotonic()
        status, text = self.launch(self.worker_arguments(), timeout=110)
        self.assertLess(time.monotonic() - begin, 100)
        self.assertEqual((status, text), ("escalation-failed", self.escalation_failed_text()))
        self.assertNotIn("orchestration send", self.names())
        self.assertNotIn("terminal close", self.names())


if __name__ == "__main__":
    unittest.main()
