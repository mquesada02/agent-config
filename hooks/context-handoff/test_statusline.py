import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
STATUSLINE = os.path.join(HERE, "statusline.py")
SESSION = "11111111-2222-3333-4444-555555555555"

# Stub ccstatusline: copies stdin to $STUB_IN, prints a line on stdout and stderr, then exits with $STUB_EXIT (or kills itself).
STUB = """#!/bin/sh
cat > "$STUB_IN"
printf 'STATUS-LINE'
echo 'stub-err' >&2
[ -n "$STUB_KILL" ] && kill -TERM $$
exit ${STUB_EXIT:-0}
"""


def status_input(**overrides):
    data = {
        "session_id": SESSION,
        "model": {"id": "claude-fable-5-1[1m]"},
        "context_window": {"context_window_size": 1000000},
    }
    data.update(overrides)
    return json.dumps(data).encode()


class WrapperTestCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.tmp = os.path.join(self.root, "tmp")
        self.bin = os.path.join(self.root, "bin")
        os.mkdir(self.tmp)
        os.mkdir(self.bin)
        self.stub_in = os.path.join(self.root, "stub-in")
        self.write_stub(STUB)
        self.folder = os.path.join(self.tmp, "claude-context-handoff")
        self.window = os.path.join(self.folder, SESSION + ".window")

    def write_stub(self, text, mode=0o755):
        path = os.path.join(self.bin, "ccstatusline")
        with open(path, "w") as handle:
            handle.write(text)
        os.chmod(path, mode)

    def wrapper_env(self, **extra_env):
        return {"PATH": self.bin + ":/usr/bin:/bin", "TMPDIR": self.tmp, "STUB_IN": self.stub_in, **extra_env}

    def run_wrapper(self, stdin, script=STATUSLINE, **extra_env):
        return subprocess.run([sys.executable, "-I", script], input=stdin, env=self.wrapper_env(**extra_env), capture_output=True, timeout=30)

    def read_window(self):
        with open(self.window) as handle:
            return json.load(handle)

    def assert_passes_through_without_window_file(self, stdin):
        result = self.run_wrapper(stdin)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"STATUS-LINE")
        self.assertEqual(self.stub_received(), stdin)
        self.assertFalse(os.path.exists(self.window))

    def stub_received(self):
        with open(self.stub_in, "rb") as handle:
            return handle.read()


class CaptureTest(WrapperTestCase):
    def test_writes_window_file_with_size_and_full_model_id(self):
        result = self.run_wrapper(status_input())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.read_window(), {"context_window_size": 1000000, "model_id": "claude-fable-5-1[1m]"})

    def test_folder_is_created_with_mode_0700(self):
        self.run_wrapper(status_input())
        self.assertEqual(stat.S_IMODE(os.stat(self.folder).st_mode), 0o700)

    def test_whole_float_size_is_stored_as_integer(self):
        self.run_wrapper(status_input(context_window={"context_window_size": 1000000.0}))
        with open(self.window) as handle:
            self.assertEqual(handle.read(), '{"context_window_size": 1000000, "model_id": "claude-fable-5-1[1m]"}')

    def test_second_run_overwrites_and_leaves_no_temp_file(self):
        self.run_wrapper(status_input())
        self.run_wrapper(status_input(context_window={"context_window_size": 200000}))
        self.assertEqual(os.listdir(self.folder), [SESSION + ".window"])
        self.assertEqual(self.read_window()["context_window_size"], 200000)

    def test_rename_failure_leaves_no_temp_file(self):
        os.mkdir(self.folder, 0o700)
        os.mkdir(self.window)  # a directory with the target name makes the rename fail
        result = self.run_wrapper(status_input())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(os.listdir(self.folder), [SESSION + ".window"])
        self.assertTrue(os.path.isdir(self.window))


class NoWindowFileTest(WrapperTestCase):
    def test_bad_json(self):
        self.assert_passes_through_without_window_file(b"{not json")

    def test_empty_stdin(self):
        self.assert_passes_through_without_window_file(b"")

    def test_json_array(self):
        self.assert_passes_through_without_window_file(b"[1, 2]")

    def test_size_bounds_are_inclusive(self):
        for size in (1, 2**53):
            with self.subTest(size=size):
                self.run_wrapper(status_input(context_window={"context_window_size": size}))
                self.assertEqual(self.read_window()["context_window_size"], size)

    def test_size_problems(self):
        for size in (None, 0, -5, True, "100", 1.5, 2**53 + 1, 1e300):
            with self.subTest(size=size):
                self.assert_passes_through_without_window_file(status_input(context_window={"context_window_size": size}))
        self.assert_passes_through_without_window_file(status_input(context_window={}))
        self.assert_passes_through_without_window_file(status_input(context_window=None))

    def test_nan_and_infinity_sizes(self):
        for constant in (b"NaN", b"Infinity", b"-Infinity"):
            with self.subTest(constant=constant):
                payload = b'{"session_id": "%s", "model": {"id": "m"}, "context_window": {"context_window_size": %s}}' % (SESSION.encode(), constant)
                self.assert_passes_through_without_window_file(payload)

    def test_model_id_problems(self):
        for model in ({}, {"id": ""}, {"id": 5}, None, "x"):
            with self.subTest(model=model):
                self.assert_passes_through_without_window_file(status_input(model=model))

    def test_session_id_problems(self):
        for session_id in ("", None, 5, "a/b", "..", "../x", "a..b/c", SESSION + "\n", "sessión", "a" * 129):
            with self.subTest(session_id=session_id):
                self.assert_passes_through_without_window_file(status_input(session_id=session_id))
        self.assertEqual(sorted(os.listdir(self.root)), ["bin", "stub-in", "tmp"])
        self.assertEqual(os.listdir(self.tmp), [])

    def test_invalid_input_keeps_an_existing_window_file(self):
        self.run_wrapper(status_input())
        before = self.read_window()
        bad_inputs = [
            b"{not json",
            status_input(context_window={"context_window_size": 0}),
            status_input(model={"id": ""}),
            status_input(session_id=SESSION + "\n"),
        ]
        for stdin in bad_inputs:
            with self.subTest(stdin=stdin):
                self.run_wrapper(stdin)
                self.assertEqual(self.read_window(), before)


class UnsafeFolderTest(WrapperTestCase):
    def assert_passes_through(self):
        self.assert_passes_through_without_window_file(status_input())

    def test_symlinked_folder(self):
        target = os.path.join(self.root, "elsewhere")
        os.mkdir(target, 0o700)
        os.symlink(target, self.folder)
        self.assert_passes_through()
        self.assertEqual(os.listdir(target), [])

    def test_folder_with_wider_mode(self):
        os.mkdir(self.folder)
        os.chmod(self.folder, 0o755)
        self.assert_passes_through()
        self.assertEqual(os.listdir(self.folder), [])

    def test_folder_that_is_a_file(self):
        with open(self.folder, "w"):
            pass
        self.assert_passes_through()


class PassThroughTest(WrapperTestCase):
    def test_stdin_reaches_the_stub_byte_for_byte(self):
        payload = b"\xff\xfe not utf-8 \x00 no final newline"
        self.run_wrapper(payload)
        self.assertEqual(self.stub_received(), payload)

    def test_valid_input_reaches_the_stub_unchanged(self):
        payload = status_input()
        self.run_wrapper(payload)
        self.assertEqual(self.stub_received(), payload)

    def test_stdout_and_stderr_are_passed_through(self):
        result = self.run_wrapper(status_input())
        self.assertEqual(result.stdout, b"STATUS-LINE")
        self.assertEqual(result.stderr, b"stub-err\n")

    def test_exit_code_is_kept(self):
        for code in (0, 1, 3, 255):
            with self.subTest(code=code):
                self.assertEqual(self.run_wrapper(status_input(), STUB_EXIT=str(code)).returncode, code)

    def test_signal_death_gives_128_plus_signal(self):
        result = self.run_wrapper(status_input(), STUB_KILL="1")
        self.assertEqual(result.returncode, 128 + signal.SIGTERM)

    def test_stub_that_ignores_a_large_stdin(self):
        self.write_stub("#!/bin/sh\nexit 7\n")
        padding = "x" * (256 * 1024)
        result = self.run_wrapper(status_input(padding=padding))
        self.assertEqual(result.returncode, 7)

    def test_missing_ccstatusline_gives_127(self):
        os.unlink(os.path.join(self.bin, "ccstatusline"))
        result = self.run_wrapper(status_input(), PATH=self.bin)
        self.assertEqual(result.returncode, 127)
        self.assertEqual(len(result.stderr.decode().strip().splitlines()), 1)

    def test_non_executable_ccstatusline_gives_126(self):
        self.write_stub(STUB, mode=0o644)
        self.assertEqual(self.run_wrapper(status_input()).returncode, 126)


# Runs a script as __main__ with a folder holding a shadow `runtime_dir` module first on the search path. The driver never imports the module itself.
SHADOW_DRIVER = """
import runpy, sys
shadow, script = sys.argv[1], sys.argv[2]
sys.path.insert(0, shadow)
sys.argv = [script] + sys.argv[3:]
runpy.run_path(script, run_name="__main__")
"""

# Runs the wrapper as __main__ after blocking one module that only the capture needs (its module-table entry is None, so importing it fails).
# The pass-through's own modules (subprocess, sys) and the one the shared module reaches (secrets, which loads math) are imported first.
BLOCK_DRIVER = """
import runpy, secrets, subprocess, sys
blocked, script = sys.argv[1], sys.argv[2]
sys.modules[blocked] = None
sys.argv = [script]
runpy.run_path(script, run_name="__main__")
"""


class ModuleSearchPathTest(WrapperTestCase):
    def test_the_real_runtime_dir_module_wins_over_a_shadow_module_earlier_on_the_search_path(self):
        shadow = os.path.join(self.root, "shadow")
        os.mkdir(shadow)
        with open(os.path.join(shadow, "runtime_dir.py"), "w") as handle:
            handle.write("FOLDER_NAME = 'shadow'\n")
        env = self.wrapper_env()
        result = subprocess.run([sys.executable, "-I", "-c", SHADOW_DRIVER, shadow, STATUSLINE], input=status_input(), env=env, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read_window(), {"context_window_size": 1000000, "model_id": "claude-fable-5-1[1m]"})


class CaptureOnlyImportTest(WrapperTestCase):
    def test_a_failing_json_or_math_import_still_passes_the_status_line_through(self):
        for blocked in ("json", "math"):
            with self.subTest(blocked=blocked):
                stdin = status_input()
                env = self.wrapper_env()
                result = subprocess.run([sys.executable, "-I", "-c", BLOCK_DRIVER, blocked, STATUSLINE], input=stdin, env=env, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, b"STATUS-LINE")
                self.assertEqual(self.stub_received(), stdin)
                self.assertFalse(os.path.exists(self.window))


class BrokenSharedModuleTest(WrapperTestCase):
    def copy_wrapper(self, module_text):
        folder = os.path.join(self.root, "copy")
        os.mkdir(folder)
        shutil.copy(STATUSLINE, folder)
        if module_text is not None:
            with open(os.path.join(folder, "runtime_dir.py"), "w") as handle:
                handle.write(module_text)
        return os.path.join(folder, "statusline.py")

    def test_missing_module_still_passes_through(self):
        payload = status_input()
        result = self.run_wrapper(payload, script=self.copy_wrapper(None))
        self.assertEqual((result.returncode, result.stdout), (0, b"STATUS-LINE"))
        self.assertEqual(self.stub_received(), payload)
        self.assertFalse(os.path.exists(self.folder))

    def test_broken_module_still_passes_through(self):
        result = self.run_wrapper(status_input(), script=self.copy_wrapper("this is not python ("))
        self.assertEqual((result.returncode, result.stdout), (0, b"STATUS-LINE"))
        self.assertFalse(os.path.exists(self.folder))


if __name__ == "__main__":
    unittest.main()
