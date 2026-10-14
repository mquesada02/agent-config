import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

import runtime_dir  # in-process tests only; test discovery puts this folder on the search path

HERE = os.path.dirname(os.path.abspath(__file__))


class DriverTestCase(unittest.TestCase):
    """Runs small driver scripts with `python3 -I`; each driver uses only the public functions of the shared module."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.tmp = os.path.join(self.root, "tmp")
        os.mkdir(self.tmp)
        self.folder = os.path.join(self.tmp, "claude-context-handoff")

    def write_driver(self, name, body):
        script = os.path.join(self.root, name)
        header = f"import json, os, sys\nsys.path.append({HERE!r})\nimport runtime_dir\n"
        with open(script, "w", encoding="utf-8") as handle:
            handle.write(header + textwrap.dedent(body))
        return script

    def drive(self, body, cwd=None, **env):
        script = self.write_driver("driver.py", body)
        full_env = {"PATH": "/usr/bin:/bin", "TMPDIR": self.tmp}
        full_env.update(env)
        full_env = {key: value for key, value in full_env.items() if value is not None}  # TMPDIR=None leaves it unset
        result = subprocess.run([sys.executable, "-I", script], env=full_env, cwd=cwd or self.root, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)


class LoadTest(DriverTestCase):
    def test_module_loads_under_isolated_mode(self):
        self.assertEqual(self.drive("print(json.dumps(runtime_dir.runtime_dir_path()))"), self.folder)


class RuntimeDirPathTest(DriverTestCase):
    def test_relative_or_empty_tmpdir_falls_back_to_tmp_without_touching_the_working_directory(self):
        work = os.path.join(self.root, "work")
        os.mkdir(work)
        for tmpdir in ("relative/dir", ""):
            with self.subTest(tmpdir=tmpdir):
                path = self.drive("print(json.dumps(runtime_dir.runtime_dir_path()))", cwd=work, TMPDIR=tmpdir)
                self.assertEqual(path, "/tmp/claude-context-handoff")
                self.assertEqual(os.listdir(work), [])

    def test_unset_tmpdir_falls_back_to_tmp(self):
        path = self.drive("print(json.dumps(runtime_dir.runtime_dir_path()))", TMPDIR=None)
        self.assertEqual(path, "/tmp/claude-context-handoff")

    def test_a_tmpdir_that_is_not_normalized_gives_a_normalized_path(self):
        # The launcher refuses a runtime folder that is not normalized, so every script must build the same normalized path.
        for tmpdir in (self.tmp + "/./x", self.tmp + "//x", self.tmp + "/y/../x"):
            with self.subTest(tmpdir=tmpdir):
                path = self.drive("print(json.dumps(runtime_dir.runtime_dir_path()))", TMPDIR=tmpdir)
                self.assertEqual(path, os.path.join(self.tmp, "x", "claude-context-handoff"))


class SessionIdTest(DriverTestCase):
    def test_only_plain_ascii_tokens_are_valid(self):
        cases = ["abc-123_X", "a" * 128, "", "a" * 129, "a/b", "..", "a b", "x\n", "sessión", None, 5]
        result = self.drive(f"print(json.dumps([runtime_dir.valid_session_id(s) for s in {cases!r}]))")
        self.assertEqual(result, [True, True, False, False, False, False, False, False, False, False, False])


class OpenRuntimeDirTest(DriverTestCase):
    def opens(self, path_literal=""):
        return self.drive(f"print(json.dumps(runtime_dir.open_runtime_dir({path_literal}) is not None))")

    def test_missing_folder_is_created_with_mode_0700(self):
        self.assertTrue(self.opens())
        self.assertEqual(stat.S_IMODE(os.stat(self.folder).st_mode), 0o700)

    def test_existing_safe_folder_opens(self):
        os.mkdir(self.folder, 0o700)
        self.assertTrue(self.opens())

    def test_explicit_path_is_used(self):
        other = os.path.join(self.root, "other")
        self.assertTrue(self.opens(repr(other)))
        self.assertTrue(os.path.isdir(other))

    def test_symlink_is_unsafe(self):
        target = os.path.join(self.root, "target")
        os.mkdir(target, 0o700)
        os.symlink(target, self.folder)
        self.assertFalse(self.opens())

    def test_wider_mode_is_unsafe_and_not_repaired(self):
        os.mkdir(self.folder)
        os.chmod(self.folder, 0o755)
        self.assertFalse(self.opens())
        self.assertEqual(stat.S_IMODE(os.stat(self.folder).st_mode), 0o755)

    def test_extra_mode_bit_is_unsafe(self):
        os.mkdir(self.folder)
        os.chmod(self.folder, 0o2700)
        self.assertFalse(self.opens())

    def test_regular_file_is_unsafe(self):
        with open(self.folder, "w"):
            pass
        self.assertFalse(self.opens())

    def test_other_owner_is_unsafe(self):
        # A non-root user cannot chown a real folder, so the driver makes os.geteuid report another user (test code only).
        os.mkdir(self.folder, 0o700)
        body = """
            os.geteuid = lambda: os.stat(runtime_dir.runtime_dir_path()).st_uid + 1
            print(json.dumps(runtime_dir.open_runtime_dir() is not None))
        """
        self.assertFalse(self.drive(body))


class WriteAtomicTest(DriverTestCase):
    def test_leaves_exactly_the_target_file_and_replaces_it(self):
        body = """
            fd = runtime_dir.open_runtime_dir()
            runtime_dir.write_atomic(fd, "a.window", "one")
            runtime_dir.write_atomic(fd, "a.window", "two")
            print(json.dumps(sorted(os.listdir(fd))))
        """
        self.assertEqual(self.drive(body), ["a.window"])
        with open(os.path.join(self.folder, "a.window")) as handle:
            self.assertEqual(handle.read(), "two")
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.folder, "a.window")).st_mode), 0o600)

    def test_failed_rename_removes_the_temp_file(self):
        body = """
            fd = runtime_dir.open_runtime_dir()
            os.mkdir("a.window", dir_fd=fd)
            try:
                runtime_dir.write_atomic(fd, "a.window", "x")
                raised = False
            except OSError:
                raised = True
            print(json.dumps([raised, sorted(os.listdir(fd))]))
        """
        self.assertEqual(self.drive(body), [True, ["a.window"]])


class ModuleSurfaceTest(DriverTestCase):
    def test_public_names_are_the_old_set_plus_create_exclusive_without_the_session_pattern(self):
        names = self.drive("print(json.dumps(sorted(n for n, v in vars(runtime_dir).items() if not n.startswith('_') and not hasattr(v, '__spec__'))))")  # modules have __spec__
        self.assertEqual(
            set(names),
            {"FOLDER_NAME", "MAX_READ_BYTES", "LOCK_WAIT_SECONDS", "LOCK_RETRY_SECONDS", "runtime_dir_path", "valid_session_id", "open_runtime_dir", "write_atomic", "create_exclusive", "read_file", "lock_file"},
        )


class CreateExclusiveTest(DriverTestCase):
    def test_publishes_the_full_content_and_leaves_no_temp_file(self):
        body = """
            fd = runtime_dir.open_runtime_dir()
            runtime_dir.create_exclusive(fd, "a.launch", "started\\n")
            print(json.dumps(sorted(os.listdir(fd))))
        """
        self.assertEqual(self.drive(body), ["a.launch"])
        with open(os.path.join(self.folder, "a.launch")) as handle:
            self.assertEqual(handle.read(), "started\n")
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.folder, "a.launch")).st_mode), 0o600)

    def test_an_existing_entry_of_any_kind_gives_file_exists_and_stays_unchanged(self):
        body = """
            fd = runtime_dir.open_runtime_dir()
            os.chdir(runtime_dir.runtime_dir_path())
            with open("keep", "w") as handle: handle.write("keep")
            os.mkdir("d", dir_fd=fd)
            os.symlink("keep", "link", dir_fd=fd)
            os.symlink("missing", "dangling", dir_fd=fd)
            os.mkfifo("fifo", dir_fd=fd)
            with open("regular", "w") as handle: handle.write("old")
            result = {}
            for name in ("regular", "d", "link", "dangling", "fifo"):
                before = os.lstat(name, dir_fd=fd)
                try:
                    runtime_dir.create_exclusive(fd, name, "new")
                    result[name] = "created"
                except FileExistsError:
                    result[name] = "exists"
                after = os.lstat(name, dir_fd=fd)
                result[name + " same"] = (before.st_ino, before.st_mode) == (after.st_ino, after.st_mode)
            result["listing"] = sorted(os.listdir(fd))
            print(json.dumps(result))
        """
        result = self.drive(body)
        for name in ("regular", "d", "link", "dangling", "fifo"):
            self.assertEqual(result[name], "exists", name)
            self.assertTrue(result[name + " same"], name)
        self.assertEqual(result["listing"], sorted(["regular", "d", "link", "dangling", "fifo", "keep"]))
        with open(os.path.join(self.folder, "regular")) as handle:
            self.assertEqual(handle.read(), "old")

    def test_another_operating_system_error_propagates_and_leaves_no_temp_file(self):
        body = """
            fd = runtime_dir.open_runtime_dir()
            try:
                runtime_dir.create_exclusive(fd, "x" * 300, "text")
                raised = None
            except OSError as error:
                raised = [type(error).__name__, error.errno]
            print(json.dumps([raised, sorted(os.listdir(fd))]))
        """
        self.assertEqual(self.drive(body), [["OSError", 36], []])


class InProcessFolderTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder)
        self.dir_fd = os.open(self.folder, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.dir_fd)


class DescriptorCloseTest(InProcessFolderTestCase):
    """In-process: the patch fails only the one file-object wrap and is restored afterwards."""

    def failing_fdopen(self, seen):
        real = os.fdopen

        def fail_once(file_fd, *args, **kwargs):
            seen.append(file_fd)
            if len(seen) == 1:
                raise OSError("wrap failed")
            return real(file_fd, *args, **kwargs)

        return fail_once

    def assert_closed(self, file_fd):
        with self.assertRaises(OSError) as caught:
            os.fstat(file_fd)
        self.assertEqual(caught.exception.errno, 9)

    def test_a_failing_wrap_closes_the_descriptor_in_the_read(self):
        with open(os.path.join(self.folder, "f"), "w") as handle:
            handle.write("text")
        seen = []
        with mock.patch.object(os, "fdopen", self.failing_fdopen(seen)):
            with self.assertRaises(OSError):
                runtime_dir.read_file(self.dir_fd, "f")
        self.assertEqual(len(seen), 1)
        self.assert_closed(seen[0])
        self.assertEqual(runtime_dir.read_file(self.dir_fd, "f"), "text")  # the patch is gone

    def test_a_failing_wrap_closes_the_descriptor_in_the_atomic_write_and_the_exclusive_create(self):
        for write in (lambda: runtime_dir.write_atomic(self.dir_fd, "t", "x"), lambda: runtime_dir.create_exclusive(self.dir_fd, "t", "x")):
            seen = []
            with mock.patch.object(os, "fdopen", self.failing_fdopen(seen)):
                with self.assertRaises(OSError):
                    write()
            self.assertEqual(len(seen), 1)
            self.assert_closed(seen[0])
            self.assertEqual(os.listdir(self.folder), [])
        runtime_dir.write_atomic(self.dir_fd, "t", "x")  # the patch is gone

    def test_a_successful_wrap_is_never_closed_by_the_module(self):
        with open(os.path.join(self.folder, "f"), "w") as handle:
            handle.write("text")
        wrapped, closed = [], []
        real_fdopen, real_close = os.fdopen, os.close

        def record_fdopen(file_fd, *args, **kwargs):
            wrapped.append(file_fd)
            return real_fdopen(file_fd, *args, **kwargs)

        def record_close(file_fd):
            closed.append(file_fd)
            real_close(file_fd)

        with mock.patch.object(os, "fdopen", record_fdopen), mock.patch.object(os, "close", record_close):
            runtime_dir.read_file(self.dir_fd, "f")
            runtime_dir.write_atomic(self.dir_fd, "t", "x")
            runtime_dir.create_exclusive(self.dir_fd, "u", "x")
        self.assertEqual(len(wrapped), 3)
        self.assertEqual(set(wrapped) & set(closed), set())


class TempNameCollisionTest(InProcessFolderTestCase):
    def test_a_taken_temp_name_retries_with_a_new_name(self):
        with open(os.path.join(self.folder, "aa.tmp"), "w") as handle:
            handle.write("taken")
        names = iter(["aa", "bb"])
        with mock.patch.object(runtime_dir.secrets, "token_hex", lambda size: next(names)):
            runtime_dir.create_exclusive(self.dir_fd, "t", "text")
        self.assertEqual(sorted(os.listdir(self.folder)), ["aa.tmp", "t"])
        with open(os.path.join(self.folder, "aa.tmp")) as handle:
            self.assertEqual(handle.read(), "taken")
        with open(os.path.join(self.folder, "t")) as handle:
            self.assertEqual(handle.read(), "text")


class ReadFileTest(DriverTestCase):
    def test_returns_text_and_none_for_a_missing_file(self):
        body = """
            fd = runtime_dir.open_runtime_dir()
            runtime_dir.write_atomic(fd, "a.window", "h\u00e9llo")
            print(json.dumps([runtime_dir.read_file(fd, "a.window"), runtime_dir.read_file(fd, "missing")]))
        """
        self.assertEqual(self.drive(body), ["h\u00e9llo", None])

    def test_refuses_a_symlink_a_fifo_an_oversize_file_and_bad_utf8(self):
        body = """
            fd = runtime_dir.open_runtime_dir()
            runtime_dir.write_atomic(fd, "real", "x")
            os.symlink("real", "link", dir_fd=fd)
            os.mkfifo("fifo", 0o600, dir_fd=fd)
            runtime_dir.write_atomic(fd, "big", "x" * (64 * 1024 + 1))
            with os.fdopen(os.open("bad", os.O_WRONLY | os.O_CREAT, 0o600, dir_fd=fd), "wb") as handle:
                handle.write(b"\\xff\\xfe")
            result = {}
            for name in ("link", "fifo", "big", "bad"):
                try:
                    runtime_dir.read_file(fd, name)
                    result[name] = "read"
                except (OSError, ValueError):
                    result[name] = "raised"
            runtime_dir.write_atomic(fd, "exact", "x" * (64 * 1024))
            result["exact"] = len(runtime_dir.read_file(fd, "exact"))
            print(json.dumps(result))
        """
        self.assertEqual(self.drive(body), {"link": "raised", "fifo": "raised", "big": "raised", "bad": "raised", "exact": 64 * 1024})


class LockFileTest(DriverTestCase):
    def test_creates_the_lock_file_with_mode_0600(self):
        body = """
            fd = runtime_dir.open_runtime_dir()
            lock = runtime_dir.lock_file(fd, "s.lock")
            os.close(lock)
            print(json.dumps(oct(os.stat("s.lock", dir_fd=fd).st_mode & 0o7777)))
        """
        self.assertEqual(self.drive(body), "0o600")

    def test_a_second_lock_waits_until_the_first_is_closed(self):
        # The processes are ordered through files, not time. The holder creates "released" before it closes the lock, so a waiter
        # that got the lock without waiting would not find the file.
        holder = """
            import time
            fd = runtime_dir.open_runtime_dir()
            lock = runtime_dir.lock_file(fd, "s.lock")
            open(os.path.join(os.environ["SIGNALS"], "held"), "w").close()
            while not os.path.exists(os.path.join(os.environ["SIGNALS"], "waiting")):
                time.sleep(0.01)
            open(os.path.join(os.environ["SIGNALS"], "released"), "w").close()
            os.close(lock)
            print("null")
        """
        waiter = """
            fd = runtime_dir.open_runtime_dir()
            open(os.path.join(os.environ["SIGNALS"], "waiting"), "w").close()
            lock = runtime_dir.lock_file(fd, "s.lock")
            print(json.dumps(os.path.exists(os.path.join(os.environ["SIGNALS"], "released"))))
        """
        signals = os.path.join(self.root, "signals")
        os.mkdir(signals)
        env = {"PATH": "/usr/bin:/bin", "TMPDIR": self.tmp, "SIGNALS": signals}
        scripts = {"holder": self.write_driver("holder.py", holder), "waiter": self.write_driver("waiter.py", waiter)}
        first = subprocess.Popen([sys.executable, "-I", scripts["holder"]], env=env, stdout=subprocess.PIPE, text=True)
        self.addCleanup(first.kill)
        while not os.path.exists(os.path.join(signals, "held")):
            self.assertIsNone(first.poll())
            time.sleep(0.01)
        second = subprocess.Popen([sys.executable, "-I", scripts["waiter"]], env=env, stdout=subprocess.PIPE, text=True)
        self.addCleanup(second.kill)
        out, _ = second.communicate(timeout=30)
        first.communicate(timeout=30)
        self.assertEqual(json.loads(out), True)

    def test_a_lock_that_stays_taken_raises_after_the_bounded_wait(self):
        body = """
            import time
            runtime_dir.LOCK_WAIT_SECONDS = 0.3
            fd = runtime_dir.open_runtime_dir()
            first = runtime_dir.lock_file(fd, "s.lock")
            start = time.monotonic()
            try:
                runtime_dir.lock_file(fd, "s.lock")
                raised = False
            except BlockingIOError:
                raised = True
            print(json.dumps([raised, time.monotonic() - start < 3]))
        """
        self.assertEqual(self.drive(body), [True, True])

    def test_refuses_a_fifo_and_a_symlink(self):
        body = """
            fd = runtime_dir.open_runtime_dir()
            os.mkfifo("f.lock", 0o600, dir_fd=fd)
            os.symlink("elsewhere", "l.lock", dir_fd=fd)
            result = []
            for name in ("f.lock", "l.lock"):
                try:
                    runtime_dir.lock_file(fd, name)
                    result.append("locked")
                except OSError:
                    result.append("raised")
            print(json.dumps(result))
        """
        self.assertEqual(self.drive(body), ["raised", "raised"])


if __name__ == "__main__":
    unittest.main()
